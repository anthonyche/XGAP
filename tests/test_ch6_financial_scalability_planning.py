"""Scale planning integration: immutable logical meaning and explicit runtime P."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_ch6_financial_grouped_materialize import frozen, run as materialize_fixture
from test_ch6_financial_scalability_queries import _fixture
from xgap.agent.intent_certificate import fingerprint
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding
from xgap.experiments import ch6_financial_scalability_planning as planning
from xgap.experiments import ch6_financial_scalability_queries as queries
from xgap.experiments.ch6_financial_calibration_planning import _branch
from xgap.experiments.ch6_financial_grouped_materialize import grouped_layout
from xgap.experiments.ch6_financial_materialize import _mapping, NS, RESOURCE, identity
from xgap.planning.joint_cost import JointCostProfile
from xgap.planning.relative_source_work import FrozenSourceWorkRanker
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource


def inputs(count=2):
    layout=grouped_layout(count,nodes_per_bank=9)
    schema=dict(identity_property='xgap_id',financial_canonical_ownership=queries.ownership_basis(9))
    mapping=_mapping([s['source_id'] for s in layout['sources']]);assignment={};sources={};backends={}
    populations=[];stats=[]
    for item in layout['sources']:
        sid=item['source_id'];rdf=item['engine']=='rdf'
        schema[sid]=dict(owner_banks=item['atoms'],nodes={'Account':dict(properties=['id','xgap_id','isBlocked'])},
            edges=[dict(label='TRANSFERRED_TO',source='Account',target='Account',properties=['id','xgap_id','amount','timestamp'])])
        assignment.update({b:sid for b in item['atoms']});sources[sid]=LogicalSource(sid,'frozen-fixture',(sid,))
        options=dict(backend_mapping=mapping['backend_mapping'],rdf_edge_encoding=RdfEdgeEncoding(**mapping['rdf_edge_encoding']),
            rdf_node_classes=(NS+'Account',)) if rdf else {}
        backends[sid]=SemanticBackend(sid,RESOURCE,identity_property='xgap_id',
            profile=replace(default_profile('fuseki' if rdf else 'neo4j'),backend_id=sid),**options)
        nodes=1000000*len(item['atoms']);edges=3125000*len(item['atoms'])
        populations.append((sid,nodes,edges));stats.append(SourceStatistics(sid,sid,'frozen-fixture',nodes+edges,128,'synthetic-counts'))
    estimator=FrozenSourceWorkRanker(FrozenSourceStatistics('test','1',tuple(stats)),tuple(populations),
        ('id','xgap_id'),'synthetic-counts',distinct_binding_keys=True)
    return schema,assignment,sources,backends,estimator


def stub_branch(seen):
    def select(branch,**kwargs):
        seen.append((deepcopy(branch),kwargs['physical'].max_parallelism,kwargs['grouped']))
        sid=branch['source_id']
        # Deterministic executable-node identity; no backend call is made.
        node=RuntimeNode('selected',R.REMOTE_QUERY,parameters=dict(backend_id=sid,
            artifact=dict(query_id=branch['query_sha256'],language='fixture',text=branch['query_sha256'])))
        plan=FederatedExecutionPlan('fixture',nodes=(node,),roots=('selected',),max_remote_calls=1,
            max_parallelism=4,metadata=dict(source_identities={sid:'frozen-fixture'}))
        return plan,dict(controller=dict(planning_cpu_ms=float(len(seen))))
    return select


def test_execution_worker_scan_preserves_selected_dag_and_all_logical_branches(monkeypatch):
    schema,assignment,sources,backends,estimator=inputs(32)
    case=queries.build_workload(nodes_per_bank=9)['cases'][0];original=deepcopy(case)
    seen=[];monkeypatch.setattr(planning,'_branch',stub_branch(seen))
    hashes=[];node_lists=[]
    for workers in (1,2,4,8,16):
        plan,report=planning.plan_case(case,schema,sources,backends,bank_to_source=assignment,
            estimator=estimator,workers=workers)
        assert plan.max_parallelism==workers and report['planning_parallelism']==4
        assert report['query_sha256']==case['query_sha256']
        assert report['branch_count']==report['selected_remote_nodes']==32
        assert report['backend_calls']==report['model_calls']==report['final_plan_executions']==0
        assert len({n.parameters['projections']['owner_bank']['value'] for n in plan.nodes if n.node_id.endswith('/partial-tag')})==32
        hashes.append(report['selected_dag_sha256']);node_lists.append([n.to_dict() for n in plan.nodes])
    assert len(set(hashes))==1 and all(nodes==node_lists[0] for nodes in node_lists)
    assert all(p==4 and grouped for _,p,grouped in seen)
    assert case==original


def test_grouping_changes_routes_not_meaning_and_does_not_claim_one_call_per_source(monkeypatch):
    case=queries.build_workload(nodes_per_bank=9)['cases'][1];original=deepcopy(case)
    seen=[];monkeypatch.setattr(planning,'_branch',stub_branch(seen));hashes=[]
    for count in (2,4,8,16,32):
        schema,assignment,sources,backends,estimator=inputs(count)
        plan,report=planning.plan_case(case,schema,sources,backends,bank_to_source=assignment,estimator=estimator)
        remote=[n for n in plan.nodes if n.kind in planning.REMOTE]
        assert len(remote)==32 and len({n.parameters['backend_id'] for n in remote})==count
        assert report['selected_remote_nodes']==32 and report['branch_count']==32
        assert report['query_sha256']==case['query_sha256'];hashes.append(report['selected_dag_sha256'])
        for branch,_,_ in seen[-32:]:
            assert branch['query']==case['branches'][branch['bank']]['query']
    assert len(set(hashes))==5 and case==original


def test_actual_materialized_group_schema_admits_same_fixed_cases(frozen,tmp_path):
    result=materialize_fixture(frozen,tmp_path/'grouped',2)
    schema=json.loads(Path(result['source_schema']['path']).read_text())
    assignment={b:s['source_id'] for s in result['sources'] for b in s['atoms']}
    assert schema['financial_canonical_ownership']==queries.ownership_basis(9)
    for case in queries.build_workload(nodes_per_bank=9)['cases']:
        branches=queries.bind_sources(case,schema,assignment)
        assert len(branches)==32 and len({b['source_id'] for b in branches})==2


def test_new_query_or_ownership_change_rejected_before_physical_search(monkeypatch):
    schema,assignment,sources,backends,estimator=inputs(2)
    def forbidden(*args,**kwargs):raise AssertionError('Invalid contracts must fail before physical planning')
    monkeypatch.setattr(planning,'_branch',forbidden)
    case=queries.build_workload(nodes_per_bank=9)['cases'][0]
    for workers in (0,3,True,32):
        with pytest.raises(ValueError,match='workers'):
            planning.plan_case(case,schema,sources,backends,bank_to_source=assignment,estimator=estimator,workers=workers)
    changed=deepcopy(case);changed['branches'][0]['query']['where'].pop()
    with pytest.raises(ValueError,match='frozen logical recipe'):
        planning.plan_case(changed,schema,sources,backends,bank_to_source=assignment,estimator=estimator)
    schema.pop('financial_canonical_ownership')
    with pytest.raises(ValueError,match='ownership basis'):
        planning.plan_case(case,schema,sources,backends,bank_to_source=assignment,estimator=estimator)


def independent_rdf_client(sid):
    rdf=pytest.importorskip('rdflib',minversion='7.1.4')
    from xgap.backends.fuseki_client import FusekiClient
    from xgap.infrastructure.descriptors import BackendDescriptor
    accounts,edges=_fixture();graph=rdf.Graph();uri=lambda s:rdf.URIRef(RESOURCE+identity(s))
    for aid,_,_,blocked in accounts:
        entity=uri(aid);graph.add((entity,rdf.RDF.type,rdf.URIRef(NS+'Account')))
        for key,value in [('id',aid),('xgap_id',identity(aid)),('isBlocked',blocked=='true')]:
            graph.add((entity,rdf.URIRef(NS+key),rdf.Literal(value)))
    for e in edges:
        if e[4]<16:continue
        entity=uri(e[1]+':'+e[0]);graph.add((entity,rdf.RDF.type,rdf.URIRef(NS+'Edge')))
        for key,value in [('source',uri(e[2])),('target',uri(e[3])),('edgeLabel',rdf.URIRef(NS+e[1])),
            ('id',rdf.Literal(e[0])),('xgap_id',rdf.Literal(identity(e[1]+':'+e[0]))),
            ('amount',rdf.Literal(e[7])),('timestamp',rdf.Literal(e[8]))]:
            graph.add((entity,rdf.URIRef(NS+key),value))
    sent=[]
    class IndependentRdf(FusekiClient):
        def _post_query(self,text):
            sent.append(text)
            return json.loads(graph.query(text).serialize(format='json'))
    return IndependentRdf(BackendDescriptor(sid,'fuseki','sparql','rdf')),sent


def test_actual_selected_grouped_rdf_plan_preserves_bank_witness_and_deduplicated_sum():
    from xgap.runtime.scheduler import FederatedScheduler
    from xgap.tools import BackendInvokeTool,BackendPluginRegistry,NativeBackendPlugin
    schema,assignment,sources,backends,estimator=inputs(2)
    case=queries.build_workload(nodes_per_bank=9)['cases'][1]
    branch=queries.bind_sources(case,schema,assignment)[16];sid=branch['source_id']
    client,sent=independent_rdf_client(sid)
    physical=replace(OneShotPolicy.for_mode('performance'),max_parallelism=4,retrieval_rows_per_relation=None)
    plan,report=_branch(branch,source_schema=schema,sources=sources,backends=backends,
        costs=JointCostProfile(),estimator=estimator,physical=physical,grouped=True)
    assert not sent and report['controller']['external_calls_during_search']==0
    plugins=BackendPluginRegistry();plugins.register(NativeBackendPlugin(sid,client))
    result=FederatedScheduler(BackendInvokeTool(plugins)).execute(plan)
    assert result.success,[(n.node_id,n.error) for n in result.node_results if n.error]
    assert list(result.final_rows)==[{'total':7}]
    # Invalid cross-bank-only witness and duplicate witness rows must not add
    # either the 9999 contribution or repeated copies of the amount 7.
    assert sent and report['selected_remote_nodes']>=len(sent)
    assert any(queries.account_id(16,0,9) in text or queries.account_id(17,0,9) in text for text in sent)


def test_variants_forward_actual_settings_without_artificial_plan_hash_difference(monkeypatch):
    schema,assignment,sources,backends,estimator=inputs(2)
    case=queries.build_workload(nodes_per_bank=9)['cases'][0]
    seen=[];select=stub_branch([]);hashes=[];method_hash_pairs=[]
    clients={'fixture':object()}
    def recording_branch(branch,**kwargs):
        seen.append(kwargs)
        return select(branch,**kwargs)
    monkeypatch.setattr(planning,'_branch',recording_branch)
    for method in planning.METHODS:
        _,report=planning.plan_case(case,schema,sources,backends,bank_to_source=assignment,
            estimator=estimator,method=method,probes=True,backend_clients=clients)
        assert report['method']==method and report['status']=='planned_without_final_execution'
        settings=planning.settings_for(method,probes=True)
        assert settings.limits.depth==(1 if method in ('SH','GR') else 2)
        assert settings.information_mode==('no_probe' if method=='NP' else 'all')
        assert settings.action_objective==('myopic' if method=='GR' else 'continuation')
        assert settings.live_probe_policy is not None
        assert all(k['settings']==settings and k['backend_clients'] is clients for k in seen[-32:])
        hashes.append(report['selected_dag_sha256']);method_hash_pairs.append((method,report['selected_dag_sha256']))
    # A shared physical DAG is genuine overlap, never renamed to manufacture
    # different plans. Result/comparability keys must carry method separately.
    assert len(set(hashes))==1 and len(set(method_hash_pairs))==4
    with pytest.raises(ValueError,match='TS is unsupported'):
        planning.plan_case(case,schema,sources,backends,bank_to_source=assignment,estimator=estimator,method='TS')


@pytest.mark.parametrize('method',planning.METHODS)
def test_live_probe_registration_and_actual_variant_controller_on_fixed_rdf(method,monkeypatch):
    from xgap.experiments import ch6_financial_calibration_planning as branch_planning
    schema,assignment,sources,backends,estimator=inputs(2)
    case=queries.build_workload(nodes_per_bank=9)['cases'][1]
    branch=queries.bind_sources(case,schema,assignment)[16];sid=branch['source_id']
    client,sent=independent_rdf_client(sid)
    settings=planning.settings_for(method,probes=True)
    observed=[];original=branch_planning.run_online
    def checked_controller(*args,**kwargs):
        observed.append((kwargs['limits'],kwargs['action_objective']))
        return original(*args,**kwargs)
    monkeypatch.setattr(branch_planning,'run_online',checked_controller)
    physical=replace(OneShotPolicy.for_mode('performance'),max_parallelism=4,retrieval_rows_per_relation=None)
    plan,report=branch_planning._branch(branch,source_schema=schema,sources=sources,backends=backends,
        costs=JointCostProfile(),estimator=estimator,physical=physical,grouped=True,
        settings=settings,backend_clients={sid:client})
    assert observed==[(settings.limits,settings.action_objective)]
    binding=report['live_probe_binding']
    assert binding['registered_targets'] and binding['backend_calls']==binding['private_inputs_read']==0
    assert len(binding['candidate_ids'])==1
    assert report['backend_calls']==report['probe_calls']==len(sent)==len(report['information_records'])
    assert report['controller']['external_calls_during_search']==0
    assert report['final_plan_executions']==0 and plan.roots
    assert all('COUNT(*) AS ?value' in query and 'LIMIT 101' in query for query in sent)
    assert all(record['semantic_authority'] is False for record in report['information_records'])
    if method=='NP':
        assert not sent and report['settings']['information_mode']=='no_probe'
