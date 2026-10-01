"""Frozen resolved financial calibration requests, independent of run outcomes.

The source domain is part of query meaning: each branch has one bank-owned
primary edge and a different sender's witness edge in that SAME bank. It is not
an unrestricted cross-bank witness join. Selected bank branches are combined
by SUM of disjoint contribution aggregates. No LLM, clarification or query
execution takes place when this module prepares the semantic program.
"""
from copy import deepcopy

from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.ch6_financial_scale import NODES_PER_BANK
from xgap.experiments.ch6_heldout import template_query
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import validate_query
from xgap.semantic.parameter_contract import validate_program_parameters
from xgap.semantic.program import SemanticGraphProgram

VERSION = 'xgap-financial-fixed-calibration-v1'
CUTOFF_MS = 1719792000000  # 2024-07-01T00:00:00Z, fixed before results.
DOMAINS = ((0,), (0, 1, 16, 17), tuple(range(8))+tuple(range(16, 24)), tuple(range(32)))
CORE = dict(node_type='Account', target_type='Account', relation='TRANSFERRED_TO',
            measure='amount', control='isBlocked', control_values=[False, True])


def source_id(bank):
    if type(bank) is not int or not 0 <= bank < 32:
        raise ValueError('Bank must be an integer in 0..31')
    return ('neo4j-' if bank < 16 else 'rdf-')+f'{bank:02d}'


def _branch(bank, name, nodes_per_bank):
    anchor = f'account:{bank*nodes_per_bank:010d}'
    query = template_query(CORE, name, anchor, CUTOFF_MS, cross=True)
    # Preserve e/f directions, c != a, all predicates and the e contribution
    # identity. Scalar output removes only the original grouping by recipient.
    query['select'] = {'total': query['select']['total']}
    query['order_by'] = []
    query['limit'] = None
    query = validate_query(query, version='v2')
    return dict(bank=bank, source_id=source_id(bank), anchor=anchor, query=query,
                query_sha256=fingerprint(query))


def build_workload(*, nodes_per_bank=NODES_PER_BANK):
    if type(nodes_per_bank) is not int or not 9 <= nodes_per_bank <= NODES_PER_BANK:
        raise ValueError('Frozen 32-bank generator account domain required')
    cases = []
    for banks in DOMAINS:
        for name, origin, aggregate in (('witnessed_count', 'W3', 'count'),
                                        ('witnessed_sum', 'W4', 'sum')):
            branches = [_branch(b, name, nodes_per_bank) for b in banks]
            query = dict(language=VERSION, branches=branches,
                         combine='sum_disjoint_bank_partial_totals', output='total')
            cases.append(dict(case_id=f'Q{len(cases)+1}', shape=name, template_origin=origin,
                query=query, query_sha256=fingerprint(query), banks=list(banks),
                source_ids=[b['source_id'] for b in branches], declared_source_span=len(banks),
                branches=branches, aggregate=aggregate, nodes_per_bank=nodes_per_bank,
                cutoff_ms=CUTOFF_MS, target_isBlocked=False, output_columns=['total'],
                maximum_answer_rows=1, executor_parallelism=4, repetitions=3,
                provenance=dict(module='xgap.experiments.ch6_heldout.template_query', template=name,
                    template_layer=origin, adaptation='Resolve intent; freeze local0 anchors, base relation, lower time, non-blocked target; replace recipient grouping/top20 with scalar aggregate and sum disjoint owner-bank branches',
                    fixed_intent=True, ambiguity_evaluation=False,
                    witness_scope='Both primary e:a->b and witness f:c->b belong to the branch owner bank; c differs from a; each e contributes once',
                    no_result_based_selection=True),
                model_calls=0, scope_confirmation_calls=0))
    return dict(schema_version=VERSION, cases=cases,
        schedule=[dict(case_id=c['case_id'], repetition=r, parallelism=4)
                  for c in cases for r in range(3)],
        execution_order='Q1..Q8; three consecutive repetitions per request; sequential requests',
        source_span_note='Declared domain, not measured source touches. Q1/Q2 use only PG bank0; other domains are balanced mixed engines.',
        repetition_scope='Three repetitions of each fixed query; not 24 independent workload samples',
        evaluation_boundary='Resolved semantic state through final materialized result; no NL interpretation or scope confirmation',
        query_selection='Fixed bank IDs, local0 anchors and July1 cutoff before outcomes',
        model_calls=0, backend_calls=0)


def lower_case(case, source_schema):
    """Compose source-specific normal lowerings into one existing semantic DAG.

    No extension of the compact 64-operator limit: each unchanged branch lowers
    separately and its ordinary typed operators are combined with UNION/SUM.
    Bank tags are retained across set-UNION so equal partial totals do not merge.
    The resulting DAG still requires the actual physical planner/compiler/runtime.
    """
    expected = next((c for c in build_workload(nodes_per_bank=case['nodes_per_bank'])['cases']
                     if c['case_id'] == case['case_id']), None)
    if case != expected:
        raise ValueError('Calibration case differs from the frozen recipe')
    if not isinstance(source_schema, dict) or not source_schema.get('identity_property'):
        raise ValueError('Explicit source schema and identity property required')
    operators, roots, sources = [], [], {}
    for branch in case['branches']:
        sid, bank = branch['source_id'], branch['bank']
        if sid not in source_schema:
            raise ValueError('Missing declared bank source: '+sid)
        if source_schema[sid].get('owner_banks') != [bank]:
            raise ValueError('Source must prove the exact single owner-bank domain: '+sid)
        schema = {k:deepcopy(v) for k,v in source_schema.items()
                  if k == sid or not (isinstance(v, dict) and 'nodes' in v and 'edges' in v)}
        program, bindings = lower_compact_query(branch['query'], schema,
            program_id=f"{case['case_id']}-bank-{bank:02d}", version='v2', optimize=True)
        raw = program.to_dict()
        names = {op['operator_id']:f"bank{bank:02d}/{op['operator_id']}" for op in raw['operators']}
        for op in raw['operators']:
            op['operator_id'] = names[op['operator_id']]
            op['input_ids'] = [names[i] for i in op['input_ids']]
            operators.append(op)
        sources.update({names[oid]:sid for oid in bindings})
        tag = f'bank{bank:02d}/tag'
        operators.append(dict(operator_id=tag, kind='project', input_ids=[names[raw['roots'][0]]],
            input_kinds=['binding_set'], output_kind='binding_set',
            parameters=dict(projections={'total':dict(kind='field',field='total'),
                                         'owner_bank':dict(kind='literal',value=bank)})))
        roots.append(tag)
    current = roots[0]
    for i, other in enumerate(roots[1:], 1):
        merged = f'bank-partials/union-{i:02d}'
        operators.append(dict(operator_id=merged, kind='union', input_ids=[current,other],
            input_kinds=['binding_set','binding_set'], output_kind='binding_set', parameters={}))
        current = merged
    operators.append(dict(operator_id='bank-partials/sum', kind='aggregate', input_ids=[current],
        input_kinds=['binding_set'], output_kind='grouped_bindings',
        parameters=dict(group_by=[], aggregations={'total':dict(op='sum',field='total',distinct=False)})))
    operators.append(dict(operator_id='answer', kind='project', input_ids=['bank-partials/sum'],
        input_kinds=['grouped_bindings'], output_kind='binding_set',
        parameters=dict(projections={'total':dict(kind='field',field='total')})))
    raw = dict(program_id=case['case_id'], operators=operators, roots=['answer'], holes=[],
        metadata=dict(financial_calibration=dict(schema_version=VERSION, query_sha256=case['query_sha256'],
            owner_banks=case['banks'], scalar_partial_aggregation=True,
            distinct_partial_bank_tags=True, fixed_intent=True, model_calls=0,
            semantic_proof='Each transfer is owned by one bank. Both witness edges use that bank. Each e contributes once within branch, and distinct bank tags preserve equal partial values under set union. SUM partials equals the scalar aggregate over disjoint e contributions.')))
    validate_program_parameters(raw)
    return SemanticGraphProgram.from_dict(raw), sources


def _reference_by_bank(banks, anchors, cutoff, target_blocked, accounts, transfer_rows_factory):
    """Two edge streams, one account stream, at most ten primary rows per bank."""
    primary = {}
    for row in transfer_rows_factory():
        eid, label, source, target, owner, source_bank, target_bank, amount, timestamp = row
        if (owner in banks and source == anchors[owner] and label == 'TRANSFERRED_TO'
                and timestamp >= cutoff and amount >= 0):
            primary[eid] = (owner, target, amount)
            if len(primary) > 10*len(banks):
                raise ValueError('Reference primary-edge bound exceeded')
    needed = {target for _,target,_ in primary.values()}
    blocked = {r[0]:r[3] == 'true' for r in accounts if r[0] in needed}
    if set(blocked) != needed:
        raise ValueError('Reference target attributes missing from canonical accounts')
    witnessed = set()
    targets = {(owner,target) for owner,target,_ in primary.values()}
    for row in transfer_rows_factory():
        _, label, source, target, owner, *_ = row
        if owner in banks and label == 'TRANSFERRED_TO' and source != anchors[owner] and (owner,target) in targets:
            witnessed.add((owner,target))
    result = {bank:dict(count=0, sum=0) for bank in banks}
    for owner,target,amount in primary.values():
        if (owner,target) in witnessed and blocked[target] == target_blocked:
            result[owner]['count'] += 1
            result[owner]['sum'] += amount
    return result


def reference(case, accounts, transfer_rows_factory):
    """Independent streaming reference over actual canonical tuples.

    At most ten primary outgoing edges per selected anchor and their targets are
    kept. The callable must yield the SAME frozen input each pass. This computes
    from data, not from the SHA recipe or a backend query, and never chooses cases.
    Use reference_workload to share the two full edge passes across all eight Qs.
    """
    totals = _reference_by_bank(set(case['banks']),
        {b['bank']:b['anchor'] for b in case['branches']}, case['cutoff_ms'],
        case['target_isBlocked'], accounts, transfer_rows_factory)
    return [{'total':sum(totals[bank][case['aggregate']] for bank in case['banks'])}]


def reference_workload(workload, accounts_factory, transfer_rows_factory):
    """All eight answers in two edge passes and ONE accounts pass (<=320 e).

    Each factory streams actual frozen CSV tuples; references remain offline and
    outside timed method requests. This exploits the predetermined nested bank
    domains and identical fixed predicates, not measured query outcomes.
    """
    cases = workload['cases']
    if not cases or cases != build_workload(nodes_per_bank=cases[0]['nodes_per_bank'])['cases']:
        raise ValueError('All eight unchanged calibration cases required')
    full = cases[-1]
    totals = _reference_by_bank(set(full['banks']),
        {b['bank']:b['anchor'] for b in full['branches']}, full['cutoff_ms'],
        full['target_isBlocked'], accounts_factory(), transfer_rows_factory)
    return {case['case_id']:[{'total':sum(totals[bank][case['aggregate']] for bank in case['banks'])}]
            for case in cases}
