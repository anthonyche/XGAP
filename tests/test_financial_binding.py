"""Only the new financial semantics, not the historical accepted suites."""

from dataclasses import replace
import json
from pathlib import Path

import pytest
from rdflib import Graph

from test_finbench_rdf import prepared, parameters, expected_rows
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments.finbench_rdf import RESOURCE
from xgap.experiments.finbench_semantic import financial_program
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics
from xgap.planning.runtime_work_estimator import load_frozen_estimator
from xgap.planning.runtime_work_deployment import FrozenWorkDeployment
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.runtime.row_operations import condition_fields, filter_rows, normalize_node_bindings
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_source
from xgap.runtime.semantic_planning import LogicalSource
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.program import SemanticGraphProgram, SemanticProgramError
from xgap.semantic.parameter_contract import validate_program_parameters
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


MODEL = Path('/Users/anthonyche/xgap-data/work-estimator-v2-native-20260912-a2c1908/frozen_work_estimator.json')


def backends_for(mapping):
    return {'neo4j': SemanticBackend('neo4j', RESOURCE, 'xgap_id'),
        'fuseki': SemanticBackend('fuseki', RESOURCE, 'xgap_id', backend_mapping=mapping['backend_mapping'],
            rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
            rdf_node_classes=tuple(mapping['rdf_node_classes']))}


def deployment(*, combined=True):
    parent = load_frozen_estimator(MODEL)
    stats = FrozenSourceStatistics('financial-tiny-statistics', 'v1', tuple(
        SourceStatistics(backend, 'tiny' if combined else source, 'financial-tiny-v1', rows, 128,
            'development-fixture:entity-edge-record-count;fixed-128-byte-work-proxy-not-measurement')
        for backend, source, rows in [('fuseki', 'control', 24 if combined else 8), ('neo4j', 'graph', 24)]))
    # Keep the trained schema's ordered backend names and frozen coefficients.
    stats = replace(stats, entries=tuple(sorted(stats.entries, key=lambda s:
        [x.backend_id for x in parent.statistics.entries].index(s.backend_id))))
    return FrozenWorkDeployment('financial-tiny-v1', parent, stats, 'development-fixture:financial-binding-v1')


@pytest.fixture(scope='module')
def data(tmp_path_factory):
    _, root, graph, _ = prepared(tmp_path_factory.mktemp('financial'))
    return root, graph, backends_for(json.loads((root/'mapping.json').read_text()))


def test_explicit_field_time_truth_and_legacy_scalar_boundary():
    start, end = '2020-01-01 00:00:00.000', '2020-01-02 00:00:00.000'
    good = {'a': start, 'b': end}
    rows = [good, {'a': start, 'b': start}, {'a': end, 'b': start},
        {'a': '2020-02-30 00:00:00.000', 'b': end}, {'a': None, 'b': end}]
    c = {'op': 'lt', 'field': 'a', 'right_field': 'b', 'value_type': 'timestamp_ms'}
    assert filter_rows(rows, c) == (good,)
    assert filter_rows(rows[:3], {k:v for k,v in c.items() if k!='value_type'}) == ()
    assert filter_rows([{'a': True, 'b': 1}, {'a': 2, 'b': 3}], {'op':'lt','field':'a','right_field':'b'}) == ({'a':2,'b':3},)
    for bad in ({**c, 'value': end}, {**c, 'value_type':'arbitrary_date'}, {**c, 'right_field':''}):
        with pytest.raises(ValueError): condition_fields(bad)
    with pytest.raises(ValueError, match='missing'): filter_rows([{'a':start}], c)


def test_edge_native_projection_preserves_multiplicity_null_and_identities(data):
    _, graph, backends = data
    program, _ = financial_program('F1', parameters()[0])
    op = replace(program.operators[0], parameters={**program.operators[0].parameters,
        'properties':{'amount':'amount','timestamp':'createTime','absent':'nickname'}})
    rdf = compile_semantic_source(op, backends['fuseki'])
    artifact = rdf.nodes[0].parameters['artifact']
    raw = json.loads(graph.query(artifact['text']).serialize(format='json'))['results']['bindings']
    rows = normalize_node_bindings(raw, rdf.nodes[1].parameters)
    assert len(rows)==8 and len({r['transfers_edge'] for r in rows})==8 and all(r['absent'] is None for r in rows)
    # Cypher is generated through the same one-edge typed path; no mock execution claim.
    native = compile_semantic_source(op, backends['neo4j'])
    assert native.nodes[0].parameters['artifact']['parameters']['compiler']=='semantic_edge_match_v1'
    first = raw[0]
    neo_row = {name:{'xgap_id':first[name]['value'].removeprefix(RESOURCE)} for name in ('entity','source','target')}
    neo_row.update(amount=float(first['amount']['value']),timestamp=first['timestamp']['value'],absent=None)
    assert normalize_node_bindings([neo_row], native.nodes[1].parameters)==normalize_node_bindings([first],rdf.nodes[1].parameters)
    with pytest.raises(ValueError, match='reified'):
        compile_semantic_source(op, replace(backends['fuseki'],rdf_edge_encoding=None))


def test_wire_contract_and_rejections_match_core_admission(data):
    from xgap.llm.candidate_interpretation import candidate_interpretation_schema
    from xgap.semantic.interpretation_candidates import SCHEMA
    from jsonschema import Draft202012Validator
    program,_=financial_program('F2',parameters()[1])
    payload={'schema_version':SCHEMA,'candidates':[{'candidate_id':'gold','quality_proxy':None,
        'program':program.to_dict(),'operator_sources':{op.operator_id:'graph' for op in program.operators if op.kind.value=='match'}}]}
    Draft202012Validator(candidate_interpretation_schema(1)).validate(payload)
    op=program.operators[0]
    for extra in ({'node':{}},{'source_field':op.parameters['entity_field']},{'properties':{'e1':'amount'}}):
        broken=replace(op,parameters={**op.parameters,**extra})
        with pytest.raises((SemanticProgramError,ValueError)):
            compile_semantic_source(broken,data[2]['fuseki'])
    broken=program.to_dict();broken['operators'][0]['parameters']['node']={}
    with pytest.raises(SemanticProgramError):validate_program_parameters(broken)


@pytest.mark.parametrize('index',[0,1,2],ids=['F1','F2','F3'])
def test_financial_program_ordinary_estimated_planning_one_selected_rdf_execution(data,index):
    _,graph,backends=data
    program,slots=financial_program(f'F{index+1}',parameters()[index])
    policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)
    candidates,domain=prepare_one_shot_domain(program,operator_sources={op:'tiny' for op in slots},
        sources={'tiny':LogicalSource('tiny','financial-tiny-v1',('fuseki',))},backends=backends,policy=policy)
    frozen=deployment()
    predictions=[(c,frozen.predict(c.plan)) for c in candidates]
    assert all(not p.features.unknown_fields for _,p in predictions)
    usable=[(c,p) for c,p in predictions if p.estimated_ms is not None]
    assert usable,[(c.strategy_id,p.status,p.provenance) for c,p in predictions]
    selected,prediction=min(usable,key=lambda item:(item[1].estimated_ms,item[0].strategy_id))
    assert prediction.provenance['workload_lowering_extension']['calibrated'] is False
    calls=[]
    class LocalRDF(FusekiClient):
        def _post_query(self,text):
            calls.append(text)
            return json.loads(graph.query(text).serialize(format='json'))
    client=LocalRDF(BackendDescriptor('fuseki','fuseki','sparql','rdf'))
    registry=BackendPluginRegistry();registry.register(NativeBackendPlugin('fuseki',client))
    assert not calls and domain['candidate_count']<=domain['construction_bound']
    result=FederatedScheduler(BackendInvokeTool(registry)).execute(selected.plan)
    assert result.success,result.to_dict()
    assert list(result.final_rows)==expected_rows()[index]
    assert result.total_remote_calls==len(calls)<=len(slots)
    assert all(p.provenance['fit_calls']==p.provenance['current_query_observation_calls']==0 for _,p in predictions)


def test_endpoint_bind_targets_the_endpoint_and_keeps_final_join(data):
    # Only inspect this distinct rewrite risk; the three financial tests execute
    # their estimated winner once, never every candidate to choose a winner.
    program,slots=financial_program('F1',parameters()[0])
    space=prepare_physical_strategies(program,source_bindings={op:'fuseki' for op in slots},backends=data[2])
    edge_binds=[n for c in space.candidates for n in c.plan.nodes if n.kind.value=='remote_bind_query'
        and n.parameters['artifact']['parameters'].get('bound_identity_column') in ('source','target')]
    assert edge_binds
    for node in edge_binds:
        p=node.parameters['artifact']['parameters']
        assert p['sparql_iri_binding']['variable']==p['bound_identity_column']
    assert all(sum(n.kind.value=='coordinator_join' for n in c.plan.nodes)==space.join_count for c in space.candidates)


def test_order_without_limit_does_not_truncate_and_keeps_old_missing_limit_error():
    from xgap.runtime.binding_operations import sort_rows
    rows=({'x':2},{'x':1},{'x':3})
    assert sort_rows({'order_by':[{'field':'x'}],'limit':None},rows)==({'x':1},{'x':2},{'x':3})
    with pytest.raises(ValueError):sort_rows({'order_by':[{'field':'x'}]},rows)


def test_endpoint_hole_grounding_enforces_identity_and_keeps_prediction_non_authoritative(data):
    from xgap.semantic.binding import SemanticBindingValue, bind_semantic_query
    from xgap.semantic.program import SemanticHole, SemanticHoleKind, hard_constraints_sha256
    source,_=financial_program('F1',parameters()[0])
    op=source.operators[0]
    op=replace(op,parameters={**op.parameters,'source':{'properties':{'xgap_id':{'$hole':'who'}}}})
    program=SemanticGraphProgram('endpoint-hole',(op,),(op.operator_id,),
        holes=(SemanticHole('who',SemanticHoleKind.ENTITY,'account one'),))
    def bind(p):
        return bind_semantic_query(p,{'program_id':p.program_id,'hard_constraints_sha256':hard_constraints_sha256(p),
            'hard_constraints_preserved':True,'candidate_sets':[{'hole_id':'who','candidate_ids':['candidate'],
                'authoritative':False,'selection_policy':'predicted_catalog_choice','sources':['frozen-tiny']}]},
            binding_values={'candidate':SemanticBindingValue(SemanticHoleKind.ENTITY,'account_31','xgap_id')},
            operator_sources={op.operator_id:'graph'},allow_predicted_entities=True)
    bound=bind(program)
    assert bound.bindings['who']['authoritative'] is False
    assert bound.program.operators[0].parameters['source']['properties']['xgap_id']=='account_31'
    fragment=compile_semantic_source(bound.program.operators[0],data[2]['neo4j'])
    assert 'xgap_id' in fragment.nodes[0].parameters['artifact']['text']
    wrong=replace(op,parameters={**op.parameters,'source':{},'edge':{'properties':{'xgap_id':{'$hole':'who'}}}})
    with pytest.raises(SemanticProgramError,match='node identity'):bind(replace(program,operators=(wrong,)))


def test_one_endpoint_bind_microquery_filters_real_rdf_rows(data):
    from xgap.experiments.finbench_semantic import _Program
    b=_Program('endpoint-micro')
    account=b.node('a','account','account',{},control=True,values={'id':'2'})
    transfers=b.edge('t','TRANSFERRED_TO','sender','account',{'amount':'amount'})
    program,slots=b.finish(b.join('j',account,transfers,'account','account'))
    space=prepare_physical_strategies(program,source_bindings={op:'fuseki' for op in slots},backends=data[2],max_parallelism=1)
    candidate=next(c for c in space.candidates if c.strategy_id=='entity_bind/j/left_to_right')
    calls=[]
    class LocalRDF(FusekiClient):
        def _post_query(self,text):
            calls.append(text)
            return json.loads(data[1].query(text).serialize(format='json'))
    registry=BackendPluginRegistry();registry.register(NativeBackendPlugin('fuseki',LocalRDF(BackendDescriptor('fuseki','fuseki','sparql','rdf'))))
    result=FederatedScheduler(BackendInvokeTool(registry)).execute(candidate.plan)
    assert result.success,result.to_dict()
    assert len(result.final_rows)==3 and sum(r['amount'] for r in result.final_rows)==66
    assert len(calls)==2 and 'VALUES ?target' in calls[1]


def test_financial_provider_uses_generic_new_contract_without_gold_program_access(monkeypatch):
    from xgap.experiments import finbench_semantic
    from xgap.semantic.interpretation import InterpretationRequest
    monkeypatch.setattr(finbench_semantic,'financial_program',lambda *a,**k:pytest.fail('gold program in provider input'))
    provider=finbench_semantic.load_financial_provider()
    request=InterpretationRequest('Find transactions with increasing timestamps.',{'source_schema':{'identity_property':'xgap_id'}})
    payload=provider.build_request_payload(request)
    assert provider.token_guard.check(payload,call_kind='generation')['passed']
    assert provider.config.safe_dict()['parameter_contract_version']=='xgap-semantic-parameters-v2'
    assert 'financial-binding-v1' in provider.provider_id
