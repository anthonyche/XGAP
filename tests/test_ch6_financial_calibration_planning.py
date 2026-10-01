from copy import deepcopy
from dataclasses import replace
import json
import threading

import pytest

from test_ch6_financial_calibration_queries import _fixture, _schema
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments import ch6_financial_calibration_queries as queries
from xgap.experiments.ch6_financial_calibration_planning import plan_case, VERSION
from xgap.experiments.ch6_financial_materialize import _mapping, NS, RESOURCE, identity
from xgap.planning.relative_source_work import FrozenSourceWorkRanker
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource


def _inputs(*, all_rdf=False):
    ids = [queries.source_id(b) for b in range(32)]
    mapping = _mapping(ids)
    sources = {sid: LogicalSource(sid, 'fixture-frozen-snapshot', (sid,)) for sid in ids}
    backends = {}
    for sid in ids:
        rdf = all_rdf or sid.startswith('rdf')
        options = dict(backend_mapping=mapping['backend_mapping'],
            rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
            rdf_node_classes=(NS+'Account',)) if rdf else {}
        backends[sid] = SemanticBackend(sid, RESOURCE, identity_property='xgap_id',
            profile=replace(default_profile('fuseki' if rdf else 'neo4j'), backend_id=sid), **options)
    # Explicit synthetic count contract exercises bounded access-path decisions;
    # correctness data below remain hand-authored and do not provide rankings.
    stats = FrozenSourceStatistics('fixture-population', '1', tuple(SourceStatistics(s, s,
        'fixture-frozen-snapshot', 4125000, 128, 'synthetic-full-size-count-fixture') for s in ids))
    ranker = FrozenSourceWorkRanker(stats, tuple((s, 1000000, 3125000) for s in ids),
        ('id', 'xgap_id'), 'synthetic-full-size-count-fixture', distinct_binding_keys=True)
    return _schema(), sources, backends, ranker


def test_actual_unified_branch_selection_is_zero_call_and_composes_once():
    schema, sources, backends, estimator = _inputs()
    case = queries.build_workload(nodes_per_bank=9)['cases'][2]
    plan, report = plan_case(case, schema, sources, backends, estimator=estimator)
    assert report['schema_version'] == VERSION and report['status'] == 'planned_without_execution'
    assert report['backend_calls'] == report['model_calls'] == report['scope_confirmation_calls'] == 0
    assert report['final_plan_executions'] == 0 and report['final_runtime_executions_required'] == 1
    assert report['branch_count'] == 4 and not report['global_joint_search']
    assert report['settings']['limits']['depth'] == 2 and report['settings']['limits']['horizon'] == 12
    assert report['planning_cpu_ms'] >= report['controller_planning_cpu_ms'] > 0
    assert set(plan.metadata['source_identities']) == set(case['source_ids'])
    assert plan.max_parallelism == 4 and len(plan.roots) == 1
    assert FederatedExecutionPlan.from_dict(plan.to_dict()) == plan
    for branch in report['branches']:
        controller = branch['controller']
        assert controller['status'] == 'terminal_selected_without_execution'
        assert controller['terminal_selection_callbacks'] == 1 and controller['final_plan_executions'] == 0
        assert controller['execution'] is None and controller['answer_rows'] is None
        assert controller['external_calls_during_search'] == 0
        assert all(t['kind'] == 'transform' for t in controller['trace'])
        assert branch['selected_estimate'] <= branch['seed_estimate']
        assert any(n['kind'] == 'remote_bind_query' for n in branch['selected_plan']['nodes'])
    tags = [n for n in plan.nodes if n.node_id.endswith('/partial-tag')]
    assert len(tags) == 4 and {n.parameters['projections']['owner_bank']['value'] for n in tags} == set(case['banks'])


def test_real_selected_rdf_plans_compose_equal_partial_totals_without_loss():
    rdf = pytest.importorskip('rdflib', minversion='7.1.4')
    from xgap.backends.fuseki_client import FusekiClient
    from xgap.infrastructure.descriptors import BackendDescriptor
    from xgap.runtime.scheduler import FederatedScheduler
    from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin
    accounts, edges = _fixture(); node_map = {r[0]: r for r in accounts}
    uri = lambda business: rdf.URIRef(RESOURCE+identity(business))
    graphs = {queries.source_id(b): rdf.Graph() for b in range(32)}
    for row in edges:
        graph = graphs[queries.source_id(row[4])]; entity = uri('TRANSFERRED_TO:'+row[0])
        for account in row[2:4]:
            node = uri(account); graph.add((node, rdf.RDF.type, rdf.URIRef(NS+'Account')))
            for key, value in [('id', account), ('xgap_id', identity(account)), ('isBlocked', node_map[account][3] == 'true')]:
                graph.add((node, rdf.URIRef(NS+key), rdf.Literal(value)))
        graph.add((entity, rdf.RDF.type, rdf.URIRef(NS+'Edge')))
        for key, value in [('source', uri(row[2])), ('target', uri(row[3])), ('edgeLabel', rdf.URIRef(NS+'TRANSFERRED_TO')),
                           ('id', rdf.Literal(row[0])), ('xgap_id', rdf.Literal(identity('TRANSFERRED_TO:'+row[0]))),
                           ('amount', rdf.Literal(row[7])), ('timestamp', rdf.Literal(row[8]))]:
            graph.add((entity, rdf.URIRef(NS+key), value))
    calls = []; lock = threading.Lock()
    class IndependentRdf(FusekiClient):
        def _post_query(self, text):
            with lock:
                calls.append((self.backend_id, text))
                return json.loads(graphs[self.backend_id].query(text).serialize(format='json'))
    registry = BackendPluginRegistry()
    for sid in graphs:
        registry.register(NativeBackendPlugin(sid, IndependentRdf(BackendDescriptor(sid, 'fuseki', 'sparql', 'rdf'))))
    schema, sources, backends, estimator = _inputs(all_rdf=True)
    for case in queries.build_workload(nodes_per_bank=9)['cases'][2:4]:
        before = len(calls)
        plan, metadata = plan_case(case, schema, sources, backends, estimator=estimator)
        assert len(calls) == before  # Search never evaluates an alternative.
        result = FederatedScheduler(BackendInvokeTool(registry)).execute(plan)
        assert result.success, [(n.node_id, n.error) for n in result.node_results if n.error]
        assert list(result.final_rows) == queries.reference(case, iter(accounts), lambda: iter(edges))
        assert list(result.final_rows) == [{'total': 4 if case['aggregate'] == 'count' else 28}]
        assert set(s for s, _ in calls[before:]) == set(case['source_ids'])
        assert len(calls)-before <= metadata['selected_remote_nodes']


def test_no_unfrozen_case_changed_workers_or_unscored_planning():
    schema, sources, backends, estimator = _inputs()
    case = queries.build_workload(nodes_per_bank=9)['cases'][0]
    with pytest.raises(ValueError, match='parallelism'):
        plan_case(case, schema, sources, backends, estimator=estimator, parallelism=1)
    with pytest.raises(ValueError, match='frozen source-count'):
        plan_case(case, schema, sources, backends)
    changed = deepcopy(case); changed['branches'][0]['anchor'] = 'other'
    with pytest.raises(ValueError, match='frozen recipe'):
        plan_case(changed, schema, sources, backends, estimator=estimator)
    schema[case['source_ids'][0]]['owner_banks'] = [0, 1]
    with pytest.raises(ValueError, match='single owner-bank'):
        plan_case(case, schema, sources, backends, estimator=estimator)
