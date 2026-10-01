"""Reuse complete Match reads that differ only in output column names.

Recompile to prove the original artifact/decoder contract, then compile a
canonical projection solely for comparison. Execute the original representative
query unchanged. Other consumers project/rename its normalized rows. No native
text rewriting, source calls, cross-query cache or semantic candidate merging.
"""
from collections import defaultdict
from dataclasses import replace
import hashlib
import json
import re

from xgap.compilers.errors import CompilerError
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import compile_semantic_source
from xgap.runtime.source_row_filters import pending_source_row_prefilters
from xgap.semantic.program import SemanticOperatorKind as S


PROFILE = 'compiler-proved-match-projection-sharing-v1'


def share_match_projections(plan, program, backends, *, native_key):
    if PROFILE in plan.metadata:
        return plan
    operators = {op.operator_id: op for op in program.operators}
    pending_filters = pending_source_row_prefilters(program, plan)
    nodes = {node.node_id: node for node in plan.nodes}
    consumers = defaultdict(list)
    for node in plan.nodes:
        for parent in node.inputs:
            consumers[parent].append(node.node_id)
    groups = defaultdict(list)
    for node in sorted(plan.nodes, key=lambda n: n.node_id):
        if (node.node_id in pending_filters or native_key(node, plan) is None or
                len(node.semantic_operator_ids) != 1):
            continue
        op = operators.get(node.semantic_operator_ids[0])
        if (op is None or op.kind is not S.MATCH or op.constraints or
                node.node_id != op.operator_id + '/native' or
                consumers[node.node_id] != [op.operator_id + '/bindings'] or
                not op.parameters.get('properties')):
            continue
        backend = backends.get(node.parameters['backend_id'])
        if backend is None:
            continue
        # Filters/limits/bindings added after compilation must not disappear.
        # A constrained Match is conservatively left to the existing exact-read
        # sharing pass; no predicate alias rewrite is attempted here.
        try:
            original = compile_semantic_source(op, backend)
            expected = {n.node_id: n for n in original.nodes}
            adapter = nodes[op.operator_id + '/bindings']
            if (node.to_dict() != expected[node.node_id].to_dict() or
                    adapter.to_dict() != expected[adapter.node_id].to_dict()):
                continue
            fields = sorted(op.parameters['properties'],
                key=lambda alias: (op.parameters['properties'][alias], alias))
            properties = {f'xgap_shared_scalar_{i}': op.parameters['properties'][alias]
                          for i, alias in enumerate(fields)}
            canonical = replace(op, parameters={**op.parameters, 'properties': properties})
            fragment = compile_semantic_source(canonical, backend)
            remote = next(n for n in fragment.nodes if n.kind is R.REMOTE_QUERY)
            if remote.parameters['artifact']['language']=='sparql':
                # An original alias that accidentally joins a compiler-internal
                # variable is not a bijective output renaming. Decline it.
                native_vars=set(re.findall(r'\?([A-Za-z_][A-Za-z0-9_]*)',remote.parameters['artifact']['text']))
                if set(fields) & (native_vars-set(properties)):
                    continue
            key = native_key(remote, plan)
        except (ValueError, CompilerError, KeyError, TypeError):
            continue
        if key is not None:
            groups[key].append((node, adapter, fields))

    removed = {}; replacements = {}; proofs = []
    for group in groups.values():
        if len(group) < 2:
            continue
        representative, rep_adapter, rep_fields = group[0]
        rep_identities = rep_adapter.parameters.get('identity_fields',
            {'entity': rep_adapter.parameters['entity_field']})
        semantic_ids = set(representative.semantic_operator_ids)
        for remote, adapter, fields in group[1:]:
            identities = adapter.parameters.get('identity_fields',
                {'entity': adapter.parameters['entity_field']})
            # The canonical artifact fixes native identity columns; preserve
            # each consumer's logical aliases and the same decoder namespace.
            if (set(identities) != set(rep_identities) or any(
                    adapter.parameters[k] != rep_adapter.parameters[k]
                    for k in ('language', 'identity_property', 'resource_namespace'))):
                continue
            columns = {target: rep_identities[source] for source, target in identities.items()}
            columns.update(zip(fields, rep_fields))
            replacements[adapter.node_id] = replace(adapter,
                kind=R.COORDINATOR_ROW_PROJECT, inputs=(rep_adapter.node_id,),
                parameters={'projections': {target: {'kind': 'field', 'field': source}
                                            for target, source in columns.items()}})
            removed[remote.node_id] = representative.node_id
            semantic_ids.update(remote.semantic_operator_ids)
            proofs.append({'removed': remote.node_id, 'representative': representative.node_id,
                           'consumer': adapter.node_id, 'column_map': columns})
        if semantic_ids != set(representative.semantic_operator_ids):
            replacements[representative.node_id] = replace(representative,
                semantic_operator_ids=tuple(sorted(semantic_ids)))
    if not removed:
        return plan
    metadata = {**plan.metadata, PROFILE: {'saved_remote_calls': len(removed),
        'proofs': proofs, 'cross_query_cache': False,
        'equivalence': 'same frozen complete compiled Match under bijective output renaming'}}
    if 'operator_outputs' in metadata:
        metadata['operator_outputs'] = {k: removed.get(v, v)
                                       for k, v in metadata['operator_outputs'].items()}
    result = replace(plan, nodes=tuple(replacements.get(n.node_id, n) for n in plan.nodes
                                      if n.node_id not in removed), metadata=metadata)
    encoded = json.dumps(result.to_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return replace(result, plan_id='shared-projection:' + hashlib.sha256(encoded).hexdigest()[:20])
