"""Four fixed financial requests for independent source/worker scale scans.

This is a new recipe; it does not change the completed eight-query calibration.
All four queries cover the same 32 logical owner banks. A physical source may
contain several banks, but a witness must remain inside its logical bank. The
canonical ingest validates edge ownership against the sender account's bank.
Exact primary anchors and explicit lexical witness-ID ranges therefore preserve
the bank domains without adding an owner property to the existing stores.
"""
from copy import deepcopy

from xgap.agent.intent_certificate import fingerprint
from xgap.experiments.ch6_financial_scale import BANKS, DEGREE, NODES_PER_BANK, SOURCE_COUNTS, VERSION as CANONICAL_VERSION
from xgap.experiments.ch6_heldout import predicate, template_query
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.compact_query import validate_query
from xgap.semantic.parameter_contract import validate_program_parameters
from xgap.semantic.program import SemanticGraphProgram

VERSION = 'xgap-financial-fixed-scalability-queries-v1'
CUTOFF_MS = 1719792000000
CORE = dict(node_type='Account', target_type='Account', relation='TRANSFERRED_TO',
            measure='amount', control='isBlocked', control_values=[False, True])
OWNERSHIP_BASIS = dict(canonical_schema=CANONICAL_VERSION,
    version='xgap-financial-canonical-owner-proof-v1', account_id_format='account:{ordinal:010d}',
    decimal_ordinal_width=10,
    account_id='account: followed by a zero-padded ten-digit global account ordinal',
    sender_bank='global sender account ordinal // nodes_per_bank',
    edge_owner='canonical owner_bank equals source_bank equals sender_bank; checked by canonical materialization',
    bank_partition='0..31, disjoint contiguous equal-size account domains',
    query_enforcement='a.id is the exact owner-bank anchor; lower_bank_id <= c.id < upper_bank_id, lexical_string',
    additional_stored_owner_property_required=False)


def ownership_basis(nodes_per_bank=NODES_PER_BANK):
    if type(nodes_per_bank) is not int or not 9 <= nodes_per_bank <= NODES_PER_BANK:
        raise ValueError('Frozen canonical 32-bank account domain required')
    return dict(deepcopy(OWNERSHIP_BASIS), nodes_per_bank=nodes_per_bank, owner_banks=BANKS)


def account_id(bank, local, nodes_per_bank):
    return f'account:{bank*nodes_per_bank+local:010d}'


def _branch(bank, local, shape, nodes_per_bank):
    anchor = account_id(bank, local, nodes_per_bank)
    query = template_query(CORE, shape, anchor, CUTOFF_MS, cross=True)
    query['select'] = {'total': query['select']['total']}
    query['order_by'] = []; query['limit'] = None
    # This predicate is present even for 32 singleton stores. Source count can
    # therefore change without changing logical meaning or its fingerprint.
    query['where'].extend([
        predicate('c', 'id', 'ge', account_id(bank, 0, nodes_per_bank)),
        predicate('c', 'id', 'lt', account_id(bank+1, 0, nodes_per_bank)),
    ])
    query = validate_query(query, version='v2')
    return dict(bank=bank, anchor_local=local, anchor=anchor, query=query,
                query_sha256=fingerprint(query))


def build_workload(*, nodes_per_bank=NODES_PER_BANK):
    """Freeze meaning and query choice independently of layouts and outcomes."""
    if type(nodes_per_bank) is not int or not 9 <= nodes_per_bank <= NODES_PER_BANK:
        raise ValueError('Frozen canonical 32-bank account domain required')
    cases = []
    for local in (0, 1):
        for shape, origin, aggregate in (('witnessed_count', 'W3', 'count'),
                                         ('witnessed_sum', 'W4', 'sum')):
            branches = [_branch(bank, local, shape, nodes_per_bank) for bank in range(BANKS)]
            query = dict(language=VERSION, branches=branches,
                combine='sum_disjoint_owner_bank_partial_totals', output='total')
            cases.append(dict(case_id=f'Q{len(cases)+1}', shape=shape, template_origin=origin,
                aggregate=aggregate, anchor_local=local, nodes_per_bank=nodes_per_bank,
                banks=list(range(BANKS)), branches=branches, query=query, query_sha256=fingerprint(query),
                cutoff_ms=CUTOFF_MS, minimum_amount=0, target_isBlocked=False,
                output_columns=['total'], maximum_answer_rows=1,
                ownership_basis=ownership_basis(nodes_per_bank),
                provenance=dict(module='xgap.experiments.ch6_heldout.template_query', template=shape,
                    adaptation='Resolved scalar aggregate over every owner bank; local0/local1 anchor, July1 cutoff, non-blocked target, same-bank different-sender witness; each primary e contributes once',
                    selected_before_outcomes=True, fixed_intent=True, ambiguity_evaluation=False,
                    witness_timestamp_constrained=False, query_depends_on_layout_or_parallelism=False),
                model_calls=0, scope_confirmation_calls=0))
    return dict(schema_version=VERSION, cases=cases, logical_owner_banks=BANKS,
        query_selection='Q1=count/local0, Q2=sum/local0, Q3=count/local1, Q4=sum/local1; all 32 banks',
        evaluation_boundary='Resolved semantic state through final scalar result; setup and LLM excluded',
        ownership_basis=ownership_basis(nodes_per_bank),
        reference_memory_bound_primary_edges=2*BANKS*DEGREE,
        model_calls=0, backend_calls=0, query_calls=0)


def _validate_case(case):
    expected = next((c for c in build_workload(nodes_per_bank=case['nodes_per_bank'])['cases']
                     if c['case_id'] == case['case_id']), None)
    if case != expected:
        raise ValueError('Scalability case differs from the frozen logical recipe')


def _validate_workload(workload):
    cases = workload.get('cases', [])
    if not cases or workload != build_workload(nodes_per_bank=cases[0]['nodes_per_bank']):
        raise ValueError('All four unchanged scalability queries required')


def bind_sources(case, source_schema, bank_to_source):
    """Check a complete ownership assignment, keeping the logical case untouched.

    The schema's owner_banks are source coverage, not a replacement for the
    explicit bank-range predicates. Canonical materialization already checks
    owner == sender bank; a supplied ownership declaration must match that basis.
    """
    _validate_case(case)
    if (not isinstance(source_schema, dict) or not source_schema.get('identity_property')
            or not isinstance(bank_to_source, dict)
            or any(type(bank) is not int for bank in bank_to_source)
            or set(bank_to_source) != set(range(BANKS))
            or any(not isinstance(sid, str) or not sid for sid in bank_to_source.values())):
        raise ValueError('Explicit complete bank-to-source assignment and schema required')
    expected_basis = ownership_basis(case['nodes_per_bank'])
    grouped = len(set(bank_to_source.values())) < BANKS
    declared = source_schema.get('financial_canonical_ownership')
    if (grouped and declared is None) or (declared is not None and declared != expected_basis):
        raise ValueError('Source schema contradicts the canonical ownership basis')
    ids = set(bank_to_source.values())
    for sid in ids:
        expected = sorted(bank for bank, owner in bank_to_source.items() if owner == sid)
        schema = source_schema.get(sid)
        if (not isinstance(schema, dict) or schema.get('owner_banks') != expected
                or any(type(bank) is not int for bank in schema['owner_banks'])):
            raise ValueError('Source must declare its exact assigned owner-bank coverage: '+sid)
        if not {'id', 'isBlocked'} <= set(schema.get('nodes', {}).get('Account', {}).get('properties', [])):
            raise ValueError('Account identity and block property required: '+sid)
        relations = [edge for edge in schema.get('edges', []) if edge.get('label') == 'TRANSFERRED_TO'
                     and edge.get('source') == edge.get('target') == 'Account']
        if len(relations) != 1 or not {'amount', 'timestamp'} <= set(relations[0].get('properties', [])):
            raise ValueError('Canonical transfer relation/properties required: '+sid)
    return [dict(deepcopy(branch), source_id=bank_to_source[branch['bank']]) for branch in case['branches']]


def lower_case(case, source_schema, bank_to_source):
    """Lower each bounded branch through normal compiler input, then UNION/SUM.

    Equal partial values remain separate through owner-bank tags. No plan
    alternatives or real sources are executed by this preparation function.
    """
    branches = bind_sources(case, source_schema, bank_to_source)
    operators, roots, sources = [], [], {}
    for branch in branches:
        sid, bank = branch['source_id'], branch['bank']
        schema = {k: deepcopy(v) for k, v in source_schema.items()
                  if k == sid or not (isinstance(v, dict) and 'nodes' in v and 'edges' in v)}
        program, bindings = lower_compact_query(branch['query'], schema,
            program_id=f"{case['case_id']}-bank-{bank:02d}", version='v2', optimize=True)
        raw = program.to_dict()
        names = {op['operator_id']: f"bank{bank:02d}/{op['operator_id']}" for op in raw['operators']}
        for op in raw['operators']:
            op['operator_id'] = names[op['operator_id']]
            op['input_ids'] = [names[i] for i in op['input_ids']]
            operators.append(op)
        sources.update({names[oid]: sid for oid in bindings})
        tag = f'bank{bank:02d}/tag'
        operators.append(dict(operator_id=tag, kind='project', input_ids=[names[raw['roots'][0]]],
            input_kinds=['binding_set'], output_kind='binding_set',
            parameters=dict(projections={'total':dict(kind='field', field='total'),
                                         'owner_bank':dict(kind='literal', value=bank)})))
        roots.append(tag)
    current = roots[0]
    for index, other in enumerate(roots[1:], 1):
        merged = f'bank-partials/union-{index:02d}'
        operators.append(dict(operator_id=merged, kind='union', input_ids=[current, other],
            input_kinds=['binding_set', 'binding_set'], output_kind='binding_set', parameters={}))
        current = merged
    operators.append(dict(operator_id='bank-partials/sum', kind='aggregate', input_ids=[current],
        input_kinds=['binding_set'], output_kind='grouped_bindings',
        parameters=dict(group_by=[], aggregations={'total':dict(op='sum', field='total', distinct=False)})))
    operators.append(dict(operator_id='answer', kind='project', input_ids=['bank-partials/sum'],
        input_kinds=['grouped_bindings'], output_kind='binding_set',
        parameters=dict(projections={'total':dict(kind='field', field='total')})))
    raw = dict(program_id=case['case_id'], operators=operators, roots=['answer'], holes=[],
        metadata=dict(financial_scalability=dict(schema_version=VERSION, query_sha256=case['query_sha256'],
            bank_to_source={str(k):v for k,v in sorted(bank_to_source.items())},
            ownership_basis=ownership_basis(case['nodes_per_bank']), fixed_intent=True, model_calls=0,
            semantic_proof='Canonical sender-bank ownership; exact a anchors and explicit lexical c-bank ranges; contribution_by e; disjoint bank-tagged scalar partials summed once')))
    validate_program_parameters(raw)
    return SemanticGraphProgram.from_dict(raw), sources


def reference_workload(workload, accounts_factory, transfer_rows_factory):
    """Compute all four scalar answers in two full edge and one account pass.

    Only eligible primary edges from two fixed anchors per bank are retained:
    <= 2 * 32 * 10 = 640 edges, <=640 target attributes and witness memberships.
    Uses actual canonical tuples, independent of compact lowering and backends.
    """
    _validate_workload(workload)
    n = workload['cases'][0]['nodes_per_bank']
    anchors = {account_id(bank, local, n):(bank, local) for bank in range(BANKS) for local in (0, 1)}
    primary = {}; primary_counts = {}; targets = {}
    for row in transfer_rows_factory():
        eid, label, source, target, owner, source_bank, target_bank, amount, timestamp = row
        if label != 'TRANSFERRED_TO' or source not in anchors or timestamp < CUTOFF_MS or amount < 0:
            continue
        bank, local = anchors[source]
        if owner != bank or source_bank != bank:
            raise ValueError('Canonical primary ownership contradicts sender-bank identity')
        if eid in primary:
            raise ValueError('Duplicate canonical primary edge identity')
        key = (bank, local); primary_counts[key] = primary_counts.get(key, 0)+1
        if primary_counts[key] > DEGREE or len(primary) >= 2*BANKS*DEGREE:
            raise ValueError('Reference primary-edge memory bound exceeded')
        primary[eid] = (bank, local, target, amount)
        targets.setdefault((bank, target), set()).add(local)
    needed = {target for _, _, target, _ in primary.values()}; blocked = {}
    for aid, label, owner, value in accounts_factory():
        if aid not in needed:
            continue
        if aid in blocked or label != 'Account' or value not in ('true', 'false'):
            raise ValueError('Canonical target account identity/type/attribute differs')
        blocked[aid] = value == 'true'
    if set(blocked) != needed:
        raise ValueError('Reference target attributes missing from canonical accounts')
    witnessed = set()
    for row in transfer_rows_factory():
        _, label, source, target, owner, source_bank, *_ = row
        if label != 'TRANSFERRED_TO':
            continue
        for local in targets.get((owner, target), ()):
            # Independent reference interprets canonical tuple owner. Check its
            # equivalence with the query's sender-ID range on relevant witnesses.
            lower = account_id(owner, 0, n); upper = account_id(owner+1, 0, n)
            if not lower <= source < upper or source_bank != owner:
                raise ValueError('Canonical witness ownership contradicts sender-bank identity')
            if source != account_id(owner, local, n):
                witnessed.add((owner, local, target))
    totals = {local:dict(count=0, sum=0) for local in (0, 1)}
    for bank, local, target, amount in primary.values():
        if (bank, local, target) in witnessed and not blocked[target]:
            totals[local]['count'] += 1; totals[local]['sum'] += amount
    return {case['case_id']:[{'total':totals[case['anchor_local']][case['aggregate']]}]
            for case in workload['cases']}


def build_schedule(workload, *, source_counts, worker_counts, source_scan_workers,
                   worker_scan_sources, repetitions):
    """Prepare two independent one-factor scans; no inferred scan levels."""
    _validate_workload(workload)
    for values, allowed in ((source_counts, SOURCE_COUNTS), (worker_counts, range(1, 17))):
        if not values or len(values) != len(set(values)) or any(type(v) is not int or v not in allowed for v in values):
            raise ValueError('Scan levels must be explicit distinct supported integers')
    if (type(source_scan_workers) is not int or not 1 <= source_scan_workers <= 16
            or type(worker_scan_sources) is not int or worker_scan_sources not in SOURCE_COUNTS
            or type(repetitions) is not int or not 1 <= repetitions <= 10):
        raise ValueError('Explicit fixed factors and bounded repetitions required')
    scans = [('source_count', source_counts, source_scan_workers), ('parallelism', worker_counts, worker_scan_sources)]
    rows = []
    for axis, levels, fixed in scans:
        for level in levels:
            count, workers = (level, fixed) if axis == 'source_count' else (fixed, level)
            for case in workload['cases']:
                for repetition in range(repetitions):
                    rows.append(dict(cell_id=f'{axis}-s{count:02d}-p{workers:02d}-{case["case_id"]}-r{repetition:02d}',
                        axis=axis, source_count=count, parallelism=workers, case_id=case['case_id'],
                        query_sha256=case['query_sha256'], repetition=repetition))
    return dict(schema_version=VERSION+'-schedule', requests=rows, sequential_requests=True,
        logical_query_identities={c['case_id']:c['query_sha256'] for c in workload['cases']},
        source_scan=dict(levels=list(source_counts), fixed_parallelism=source_scan_workers),
        worker_scan=dict(levels=list(worker_counts), fixed_source_count=worker_scan_sources),
        repetitions=repetitions, overlap_policy='Shared factor settings remain explicit independent scan cells; no unrecorded result substitution',
        model_calls=0, backend_calls=0, submitted_jobs=0)
