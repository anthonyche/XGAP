"""Share identical complete source reads inside one frozen-snapshot plan.

No text rewriting, remote bindings, result cache, data reads or cost estimation.
Keep every consumer; decline any rewrite that collapses a node's input ports.
"""
from collections import defaultdict
from dataclasses import replace
import hashlib
import json

from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R


PROFILE='identical-complete-native-reads-v1'
COMPILERS=frozenset(('semantic_node_match_v1','semantic_edge_match_v1',
    'bounded_native_paths_v1','resource_triple_paths_v1'))


def _key(node,plan):
    if node.kind is not R.REMOTE_QUERY or node.inputs or node.node_id in plan.roots:
        return None
    if set(node.parameters)!= {'backend_id','artifact'}:return None
    backend=node.parameters['backend_id'];artifact=node.parameters['artifact']
    identity=plan.metadata.get('source_identities',{}).get(backend)
    if (not isinstance(identity,dict) or set(identity)!= {'source_id','snapshot_version'} or
            any(not isinstance(v,str) or not v for v in identity.values()) or
            plan.metadata.get('source_snapshot_versions',{}).get(backend)!=identity['snapshot_version']):
        return None
    if not isinstance(artifact,dict):return None
    p=artifact.get('parameters',{})
    if (not isinstance(p,dict) or p.get('compiler') not in COMPILERS or
            p.get('target_backend_id')!=backend or 'retrieval_budget' in p or
            artifact.get('kind')!='compiled' or artifact.get('source_path') is not None or
            artifact.get('language') not in ('cypher','sparql')):
        return None
    # Keep all compiler, capability, value and decoding fields; only the
    # per-invocation label is immaterial to this deterministic compiled read.
    return json.dumps({'backend':backend,'source':identity,
        'artifact':{k:v for k,v in artifact.items() if k!='artifact_id'}},
        sort_keys=True,separators=(',',':'),allow_nan=False)


def share_full_native_reads(plan: FederatedExecutionPlan, *, program=None, backends=None) -> FederatedExecutionPlan:
    """Preserve the feasible plan when there are no admissible duplicate reads."""
    if program is not None and backends is not None:
        from xgap.runtime.shared_match_projections import share_match_projections
        plan=share_match_projections(plan,program,backends,native_key=_key)
    from xgap.runtime.source_row_filters import pending_source_row_prefilters
    pending_filters=pending_source_row_prefilters(program,plan) if program is not None else frozenset()
    consumers=defaultdict(set)
    for node in plan.nodes:
        for parent in node.inputs:consumers[parent].add(node.node_id)
    representatives={};aliases={};semantic_ids={};declined=[]
    for node in sorted(plan.nodes,key=lambda n:n.node_id):
        if node.node_id in pending_filters:continue
        key=_key(node,plan)
        if key is None:continue
        representative=representatives.setdefault(key,node.node_id)
        semantic_ids.setdefault(representative,set(node.semantic_operator_ids))
        if representative==node.node_id:continue
        if consumers[representative] & consumers[node.node_id]:
            declined.append({'node':node.node_id,'representative':representative,'reason':'shared_consumer_input_ports'})
            continue
        aliases[node.node_id]=representative
        consumers[representative].update(consumers[node.node_id])
        semantic_ids[representative].update(node.semantic_operator_ids)
    if not aliases:return plan
    nodes=tuple(replace(n,inputs=tuple(aliases.get(i,i) for i in n.inputs),
        semantic_operator_ids=tuple(sorted(semantic_ids[n.node_id])) if n.node_id in semantic_ids else n.semantic_operator_ids)
        for n in plan.nodes if n.node_id not in aliases)
    metadata={**plan.metadata,'shared_native_reads':{'profile':PROFILE,'removed_to_representative':aliases,
        'saved_remote_calls':len(aliases),'declined':declined,'cross_query_cache':False,
        'assumption':'same frozen snapshot and deterministic complete compiled query results',
        'semantic_equivalence':'identical source relation reused with all consumer operators retained'}}
    if 'operator_outputs' in metadata:
        metadata['operator_outputs']={k:aliases.get(v,v) for k,v in metadata['operator_outputs'].items()}
    # `schemas` is keyed by semantic operators; every consumer schema stays.
    result=replace(plan,nodes=nodes,metadata=metadata)
    encoded=json.dumps(result.to_dict(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return replace(result,plan_id='shared:'+hashlib.sha256(encoded).hexdigest()[:20])
