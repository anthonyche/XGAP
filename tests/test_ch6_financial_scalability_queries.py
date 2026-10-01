"""Fixed scale-query semantics; no external database, model or benchmark run."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from xgap.experiments import ch6_financial_scalability_queries as queries
from xgap.experiments.ch6_financial_scale import iter_accounts, iter_transfers, source_layout
from xgap.semantic.compact_lowering import lower_compact_query


def _schema(count=2, n=9):
    layout = source_layout(count, nodes_per_bank=n)
    schema = dict(identity_property='xgap_id', financial_canonical_ownership=queries.ownership_basis(n))
    assignment = {}
    for source in layout['sources']:
        sid = source['source_id']
        schema[sid] = dict(owner_banks=source['atoms'],
            nodes={'Account':dict(properties=['id', 'xgap_id', 'isBlocked'])},
            edges=[dict(label='TRANSFERRED_TO', source='Account', target='Account',
                        properties=['id', 'xgap_id', 'amount', 'timestamp'])])
        assignment.update({bank:sid for bank in source['atoms']})
    return schema, assignment


def _fixture():
    accounts = []; edges = []
    for bank in range(32):
        aid = lambda local:queries.account_id(bank, local, 9)
        accounts.extend((aid(local), 'Account', bank, 'true' if local == 4 else 'false') for local in range(9))
        def edge(name, a, b, amount, stamp=queries.CUTOFF_MS, label='TRANSFERRED_TO'):
            edges.append((f'{bank}:{name}', label, aid(a), aid(b), bank, bank, bank, amount, stamp))
        edge('local0-primary', 0, 2, 7)
        edge('local1-primary', 1, 3, 11)
        edge('local0-witness', 5, 2, 1000, queries.CUTOFF_MS-1)
        edge('local0-duplicate-witness', 5, 2, 2000)
        edge('local1-witness', 6, 3, 3000)
        edge('local1-duplicate-witness', 7, 3, 4000)
        edge('blocked-primary', 0, 4, 999)
        edge('blocked-witness', 6, 4, 999)
        edge('too-old-primary', 0, 5, 999, queries.CUTOFF_MS-1)
        edge('too-old-primary-witness', 6, 5, 999)
        edge('negative-primary', 1, 5, -999)
        edge('wrong-relation-primary', 0, 5, 999, label='OTHER')
        edge('cross-only-primary', 0, 6, 9999)
        # A real different-bank sender must not witness the bank's primary edge,
        # even when both banks are physically merged into the same source.
        other = (bank+1)%32
        edges.append((f'{bank}:cross-witness', 'TRANSFERRED_TO',
            queries.account_id(other, 7, 9), aid(6), other, other, bank, 9, queries.CUTOFF_MS))
        edge('self-only-primary', 1, 7, 10000)
        edge('self-only-duplicate', 1, 7, 10001)
    return accounts, edges


def _direct_join(case, accounts, edges):
    blocked = {row[0]:row[3] == 'true' for row in accounts}
    anchors = {bank:queries.account_id(bank, case['anchor_local'], case['nodes_per_bank']) for bank in range(32)}
    selected = [e for e in edges if e[1] == 'TRANSFERRED_TO' and e[2] == anchors[e[4]]
        and e[8] >= queries.CUTOFF_MS and e[7] >= 0 and not blocked[e[3]]
        and any(f[1] == 'TRANSFERRED_TO' and f[4] == e[4] and f[3] == e[3] and f[2] != e[2] for f in edges)]
    return [{'total':len(selected) if case['aggregate'] == 'count' else sum(e[7] for e in selected)}]


def test_four_fixed_cases_keep_all_banks_and_explicit_witness_ranges():
    workload = queries.build_workload(nodes_per_bank=9)
    assert [(c['case_id'], c['aggregate'], c['anchor_local']) for c in workload['cases']] == [
        ('Q1', 'count', 0), ('Q2', 'sum', 0), ('Q3', 'count', 1), ('Q4', 'sum', 1)]
    assert workload['reference_memory_bound_primary_edges'] == 640
    for case in workload['cases']:
        assert case['banks'] == list(range(32)) and len(case['branches']) == 32
        assert 'executor_parallelism' not in case and 'source_ids' not in case
        for branch in case['branches']:
            query = branch['query']; bank = branch['bank']
            assert branch['anchor'] == queries.account_id(bank, case['anchor_local'], 9)
            assert query['contribution_by'] == ['e'] and query['limit'] is None and query['order_by'] == []
            ranges = [p for p in query['where'] if p['left'] == dict(var='c', property='id') and p['op'] in ('ge', 'lt')]
            assert [(p['op'], p['right']['value'], p['value_type']) for p in ranges] == [
                ('ge', queries.account_id(bank, 0, 9), 'lexical_string'),
                ('lt', queries.account_id(bank+1, 0, 9), 'lexical_string')]
            assert 'source_id' not in branch
    assert workload == queries.build_workload(nodes_per_bank=9)


def test_reference_all_four_answers_filters_deduplicates_and_uses_three_stream_passes():
    accounts, edges = _fixture(); calls = dict(accounts=0, edges=0)
    def account_stream(): calls['accounts'] += 1; return iter(accounts)
    def edge_stream(): calls['edges'] += 1; return iter(edges)
    workload = queries.build_workload(nodes_per_bank=9)
    result = queries.reference_workload(workload, account_stream, edge_stream)
    assert result == {'Q1':[{'total':32}], 'Q2':[{'total':224}], 'Q3':[{'total':32}], 'Q4':[{'total':352}]}
    assert calls == dict(accounts=1, edges=2)
    assert result == {case['case_id']:_direct_join(case, accounts, edges) for case in workload['cases']}


def test_reference_agrees_with_brute_join_over_real_canonical_generator():
    accounts = [row for bank in range(32) for row in iter_accounts(bank, nodes_per_bank=9)]
    edges = [row for bank in range(32) for row in iter_transfers(bank, nodes_per_bank=9)]
    workload = queries.build_workload(nodes_per_bank=9)
    result = queries.reference_workload(workload, lambda:iter(accounts), lambda:iter(edges))
    assert result == {case['case_id']:_direct_join(case, accounts, edges) for case in workload['cases']}


@pytest.mark.parametrize('fault', ['bounds', 'missing_account', 'duplicate_e', 'ownership'])
def test_reference_rejects_broken_input_bounds_or_ownership(fault):
    accounts, edges = _fixture(); workload = queries.build_workload(nodes_per_bank=9)
    if fault == 'bounds':
        primary = edges[0]
        edges.extend((f'extra-{i}', *primary[1:]) for i in range(11))
    elif fault == 'missing_account': accounts = [a for a in accounts if a[0] != queries.account_id(0, 2, 9)]
    elif fault == 'duplicate_e': edges.append(edges[0])
    else: edges[0] = (*edges[0][:4], 1, *edges[0][5:])
    with pytest.raises(ValueError): queries.reference_workload(workload, lambda:iter(accounts), lambda:iter(edges))


def test_layout_bindings_do_not_change_logical_fingerprints_or_cases():
    workload = queries.build_workload(nodes_per_bank=9); original = deepcopy(workload)
    for count in (2, 4, 8, 16, 32):
        schema, assignment = _schema(count)
        for case in workload['cases']:
            branches = queries.bind_sources(case, schema, assignment)
            assert len({b['source_id'] for b in branches}) == count
            assert all(b['query'] == case['branches'][b['bank']]['query'] for b in branches)
    assert workload == original


@pytest.mark.parametrize('fault', ['missing_basis', 'wrong_basis', 'missing_bank', 'wrong_coverage', 'changed_query'])
def test_grouped_lowering_rejects_unproven_or_changed_logical_ownership(fault):
    schema, assignment = _schema(); case = deepcopy(queries.build_workload(nodes_per_bank=9)['cases'][0])
    if fault == 'missing_basis': schema.pop('financial_canonical_ownership')
    elif fault == 'wrong_basis': schema['financial_canonical_ownership']['nodes_per_bank'] = 10
    elif fault == 'missing_bank': assignment.pop(0)
    elif fault == 'wrong_coverage': schema[assignment[0]]['owner_banks'] = [0]
    else: case['branches'][0]['query']['where'].pop()
    with pytest.raises(ValueError): queries.lower_case(case, schema, assignment)


def test_grouped_lowering_retains_both_range_predicates_and_bank_tags():
    schema, assignment = _schema(); case = queries.build_workload(nodes_per_bank=9)['cases'][0]
    program, bindings = queries.lower_case(case, schema, assignment)
    assert set(bindings.values()) == set(assignment.values()) and not program.holes
    assert len([op for op in program.operators if op.operator_id.endswith('/tag')]) == 32
    text = str(program.to_dict())
    assert 'lexical_string' in text and queries.account_id(32, 0, 9) in text
    assert program.metadata['financial_scalability']['query_sha256'] == case['query_sha256']


def test_independent_scans_vary_only_one_factor_and_never_edit_query_meaning():
    workload = queries.build_workload(nodes_per_bank=9)
    schedule = queries.build_schedule(workload, source_counts=[2,4,8,16,32], worker_counts=[1,2,4,8,16],
        source_scan_workers=4, worker_scan_sources=2, repetitions=3)
    rows = schedule['requests']
    assert len(rows) == 120 and len({row['cell_id'] for row in rows}) == 120
    assert {row['parallelism'] for row in rows if row['axis'] == 'source_count'} == {4}
    assert {row['source_count'] for row in rows if row['axis'] == 'parallelism'} == {2}
    assert all(row['query_sha256'] == schedule['logical_query_identities'][row['case_id']] for row in rows)
    assert schedule['model_calls'] == schedule['backend_calls'] == schedule['submitted_jobs'] == 0


def test_real_sparql_range_filters_exclude_other_bank_witnesses_in_merged_graph():
    rdf = pytest.importorskip('rdflib', minversion='7.1.4')
    from xgap.backends.fuseki_client import FusekiClient
    from xgap.compilers.features import default_profile
    from xgap.compilers.rdf_encoding import RdfEdgeEncoding
    from xgap.infrastructure.descriptors import BackendDescriptor
    from xgap.runtime.scheduler import FederatedScheduler
    from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
    from xgap.experiments.ch6_financial_calibration_planning import _branch
    from xgap.agent.one_shot_policy import OneShotPolicy
    from xgap.planning.joint_cost import JointCostProfile
    from xgap.planning.runtime_estimator import SourceStatistics, FrozenSourceStatistics
    from xgap.planning.relative_source_work import FrozenSourceWorkRanker
    from xgap.runtime.semantic_planning import LogicalSource
    from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin
    ns = 'https://xgap.dev/ch6/schema/'; resource = 'https://xgap.dev/ch6/resource/'
    sid = 'rdf-merged'; graph = rdf.Graph(); accounts, edges = _fixture()
    # Two real logical banks in one store suffice to expose cross-bank witness
    # leakage without turning a semantic unit check into a volume benchmark.
    accounts = [row for row in accounts if row[2] < 2]
    edges = [row for row in edges if row[5] < 2 and row[6] < 2]
    ident = lambda value:'r0_'+value.encode().hex()
    uri = lambda value:rdf.URIRef(resource+ident(value))
    for aid, _, _, blocked in accounts:
        graph.add((uri(aid), rdf.RDF.type, rdf.URIRef(ns+'Account')))
        for key, value in [('id', aid), ('xgap_id', ident(aid)), ('isBlocked', blocked == 'true')]:
            graph.add((uri(aid), rdf.URIRef(ns+key), rdf.Literal(value)))
    for e in edges:
        edge = uri(e[1]+':'+e[0]); graph.add((edge, rdf.RDF.type, rdf.URIRef(ns+'Edge')))
        for key, value in [('source', uri(e[2])), ('target', uri(e[3])), ('edgeLabel', rdf.URIRef(ns+e[1])),
                           ('id', rdf.Literal(e[0])), ('xgap_id', rdf.Literal(ident(e[1]+':'+e[0]))),
                           ('amount', rdf.Literal(e[7])), ('timestamp', rdf.Literal(e[8]))]:
            graph.add((edge, rdf.URIRef(ns+key), value))
    properties = ['id', 'xgap_id', 'isBlocked', 'amount', 'timestamp']
    terms = {k:dict(kind='property', representation=ns+k) for k in properties}
    terms.update(Account=dict(kind='class', representation=ns+'Account'),
                 TRANSFERRED_TO=dict(kind='relation', representation=ns+'TRANSFERRED_TO'))
    mapping = dict(mapping_id='merged-fixture', version='1', backends={sid:dict(namespace=ns)}, term_mappings={sid:terms})
    encoding = RdfEdgeEncoding('merged-fixture', ns+'Edge', ns+'source', ns+'target', ns+'edgeLabel')
    backend = SemanticBackend(sid, resource, identity_property='xgap_id', backend_mapping=mapping,
        rdf_edge_encoding=encoding, rdf_node_classes=(ns+'Account',), profile=replace(default_profile('fuseki'), backend_id=sid))
    source = dict(owner_banks=[0, 1], nodes={'Account':dict(properties=['id', 'xgap_id', 'isBlocked'])},
        edges=[dict(label='TRANSFERRED_TO', source='Account', target='Account', properties=['id', 'xgap_id', 'amount', 'timestamp'])])
    schema = {sid:source, 'identity_property':'xgap_id'}
    sent = []
    class IndependentRdf(FusekiClient):
        def _post_query(self, text):
            sent.append(text)
            return json.loads(graph.query(text).serialize(format='json'))
    plugins = BackendPluginRegistry()
    plugins.register(NativeBackendPlugin(sid, IndependentRdf(BackendDescriptor(sid, 'fuseki', 'sparql', 'rdf'))))
    estimator = FrozenSourceWorkRanker(FrozenSourceStatistics('fixture', 'fixture',
        (SourceStatistics(sid, sid, 'fixture', len(accounts)+len(edges), None, 'fixture'),)),
        ((sid, len(accounts), len(edges)),), ('id', 'xgap_id'), 'fixture', distinct_binding_keys=True)
    for case in queries.build_workload(nodes_per_bank=9)['cases']:
        branch = dict(case['branches'][0], source_id=sid)
        plan, evidence = _branch(branch, source_schema=schema,
            sources={sid:LogicalSource(sid, 'fixture', (sid,))}, backends={sid:backend},
            costs=JointCostProfile(), estimator=estimator,
            physical=replace(OneShotPolicy.for_mode('performance'), max_parallelism=1, retrieval_rows_per_relation=None), grouped=True)
        result = FederatedScheduler(BackendInvokeTool(plugins)).execute(plan)
        assert result.success, [(n.node_id, n.error) for n in result.node_results if n.error]
        expected = {'Q1':1, 'Q2':7, 'Q3':1, 'Q4':11}[case['case_id']]
        assert list(result.final_rows) == [{'total':expected}]
        assert evidence['model_calls'] == evidence['backend_calls'] == 0
    assert sent
