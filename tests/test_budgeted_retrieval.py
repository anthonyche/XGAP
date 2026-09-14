"""New source-budget semantics/estimation risks; independent tiny facts only."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from test_anchor_reduction import tiny, EXPECTED
from test_anchor_source_bind import fanout, space
from test_one_shot_question import PIN, BUNDLE_FIXTURE
from test_one_shot_split import parent as analytic_weights
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.question import run_question
from xgap.experiments.tiny_work_training import op, _program
from xgap.planning.runtime_estimator import FrozenSourceStatistics, SourceStatistics
from xgap.planning.runtime_instance_work import FrozenInstanceWorkDeployment
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.retrieval_budget import apply_retrieval_budget, retrieval_observation
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


@pytest.fixture
def model(analytic_weights):
    stats=FrozenSourceStatistics('independent-budget-fixture','v1',tuple(
        SourceStatistics(b,s,'tiny-v1',n,100,'fixture:five-nodes-eight-edges; width is analytic')
        for b,s,n in [('rdf_a','graph',13),('rdf_b','control',1)]))
    return FrozenInstanceWorkDeployment('independent-budget-fixture',analytic_weights,
        stats,(('rdf_a','fuseki'),('rdf_b','fuseki')),'fixture:no-fit-existing-weights')


def program(*, aggregate=False):
    nodes=[op('edges','match',parameters={'edge':{'label':'KNOWS'},
        'entity_field':'edge','source_field':'src','target_field':'dst','properties':{}})]
    if aggregate:
        nodes += [op('count','aggregate',('edges',),output='grouped_bindings',parameters={
            'group_by':[],'aggregations':{'n':{'op':'count','field':'edge','distinct':False}}}),
            op('top','order_limit',('count',),output='grouped_bindings',input_kind='grouped_bindings',
               parameters={'order_by':[{'field':'n','direction':'desc'}],'limit':1})]
    return _program('budget-independent-query',nodes)


def inputs():
    _,_,backends,graphs,clients,scheduler,calls=tiny()
    sources={s:LogicalSource(s,'tiny-v1',(b,)) for s,b in [('graph','rdf_a'),('control','rdf_b')]}
    return backends,sources,graphs,clients,scheduler,calls


def policy(rows=None,mode='performance'):
    return replace(OneShotPolicy.for_mode(mode),max_parallelism=1,retrieval_rows_per_relation=rows)


def domain(p,b,s,pol):
    return prepare_one_shot_domain(p,operator_sources={'edges':'graph'},sources=s,backends=b,policy=pol)[0]


@pytest.mark.parametrize('aggregate',[False,True])
def test_actual_native_limit_reduces_work_and_exposes_approximate_counts(aggregate):
    b,s,_,_,scheduler,calls=inputs();p=program(aggregate=aggregate);before=p.to_dict()
    full=domain(p,b,s,policy())[0].plan;limited=domain(p,b,s,policy(2))[0].plan
    a,z=scheduler.execute(full),scheduler.execute(limited)
    assert a.success and z.success and p.to_dict()==before
    assert len(calls)==2 and calls[1][1].endswith('\nLIMIT 3')
    ar,zr=next(n for n in a.node_results if n.kind is R.REMOTE_QUERY),next(n for n in z.node_results if n.kind is R.REMOTE_QUERY)
    assert ar.row_count==8 and zr.row_count==2 and zr.metadata['retrieval_budget']['source_rows_received']==3
    assert z.total_bytes_moved<a.total_bytes_moved
    summary=retrieval_observation(limited,z.to_dict())
    assert summary['source_rows_omitted'] and not summary['complete_for_selected_interpretation']
    if aggregate:
        assert a.final_rows==({'n':8},) and z.final_rows==({'n':2},)
        assert summary['aggregate_values_may_change'] and summary['ranking_may_change']
        assert not summary['aggregate_values_full_source_exact'] and not summary['ranking_full_source_exact']
    else:
        assert len(a.final_rows)==8 and len(z.final_rows)==2
        assert {r['edge'] for r in z.final_rows}<={r['edge'] for r in a.final_rows}
    print(json.dumps({'gate':'actual-tiny-budget','aggregate':aggregate,'full_source_rows':8,
        'limited_source_rows':3,'kept_source_rows':2,'full_exchange_bytes':a.total_bytes_moved,
        'limited_exchange_bytes':z.total_bytes_moved,'full_answer_rows':len(a.final_rows),
        'limited_answer_rows':len(z.final_rows)}))


@pytest.mark.parametrize('cap',[8,9])
def test_no_omitted_sentinel_means_complete_results_including_exact_cap(cap):
    b,s,_,_,scheduler,_=inputs();p=program(aggregate=True)
    limited=domain(p,b,s,policy(cap))[0].plan;result=scheduler.execute(limited)
    observed=retrieval_observation(limited,result.to_dict())
    assert result.success and result.final_rows==({'n':8},)
    assert observed['complete_for_selected_interpretation'] and not observed['source_rows_omitted']


def test_frozen_estimator_bounds_returned_work_without_claiming_fewer_native_scans(model):
    b,s,_,_,_,calls=inputs();p=program(aggregate=True);before=model.to_dict()
    full=domain(p,b,s,policy())[0];limited=domain(p,b,s,policy(2))[0]
    a,z=model.predict(full.plan),model.predict(limited.plan)
    assert a.status==z.status=='estimated' and model.to_dict()==before and not calls
    af,zf=(dict(zip(x.features.names,x.features.values)) for x in (a,z))
    for suffix in ('record_units','column_units','calls'):
        key='backend.fuseki.path.full.'+suffix
        assert af[key]==zf[key]
    assert zf['backend.fuseki.path.full.logical_byte_units']<af['backend.fuseki.path.full.logical_byte_units']
    assert zf['kind.coordinator_group_aggregate.input_units']<af['kind.coordinator_group_aggregate.input_units']
    assert not z.provenance['retrieval_work_extension']['native_scan_discounted']
    assert not z.provenance['retrieval_work_extension']['calibrated']
    assert z.provenance['fit_calls']==0
    assert limited.semantic_equivalence_key!=full.semantic_equivalence_key
    assert limited.features['native_query_bytes']==sum(len(n.parameters['artifact']['text'].encode())
        for n in limited.plan.nodes if n.kind in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY))


def test_changed_limit_is_rejected_before_dispatch_and_ignored_limit_is_not_an_approximate_answer(monkeypatch,model):
    b,s,_,clients,scheduler,calls=inputs();p=program();plan=domain(p,b,s,policy(2))[0].plan
    raw=deepcopy(plan.to_dict());remote=next(n for n in raw['nodes'] if n['kind']=='remote_query')
    remote['parameters']['artifact']['text']+='0'
    changed=FederatedExecutionPlan.from_dict(raw)
    assert model.predict(changed).status=='unavailable_missing_features'
    assert not scheduler.execute(changed).success and not calls
    original=clients['rdf_a']._post_query
    monkeypatch.setattr(clients['rdf_a'],'_post_query',lambda text:original(text.rsplit('\nLIMIT ',1)[0]))
    result=scheduler.execute(plan)
    assert not result.success and len(calls)==1 and result.total_remote_calls==1
    assert any(n.error and 'fetch bound' in n.error for n in result.node_results)
    assert any(n.metadata.get('retrieval_budget_violation')=={'received_rows':8,'fetch_bound':3}
               for n in result.node_results)


def test_budget_is_applied_after_real_bind_compilation_and_preserves_node_reads():
    p,slots,b,_,_,scheduler,calls=tiny()
    base=fanout(space(p,slots,b)).plan;limited=apply_retrieval_budget(base,p,1)
    for a,z in zip(base.nodes,limited.nodes):
        if a.kind in (R.REMOTE_QUERY,R.REMOTE_BIND_QUERY):
            compiler=a.parameters['artifact']['parameters']['compiler']
            if compiler=='semantic_node_match_v1':assert a==z
            else:assert z.parameters['artifact']['text'].endswith('\nLIMIT 2')
    result=scheduler.execute(limited)
    assert result.success,result.to_dict()
    assert {json.dumps(r,sort_keys=True) for r in result.final_rows}<={json.dumps(r,sort_keys=True) for r in EXPECTED}
    assert any('VALUES ?source' in text and text.endswith('\nLIMIT 2') for _,text in calls)


def test_ordinary_modes_execute_once_with_explicit_coverage_and_hard_completeness(model):
    b,s,_,clients,_,calls=inputs();p=program(aggregate=True)
    class Provider:
        provider_id='independent-budget-gold-interpretation'
        calls=0
        def interpret(self,request):
            self.calls+=1
            return InterpretationResponse({'schema_version':SCHEMA,'candidates':[{'candidate_id':'one',
                'quality_proxy':1,'program':p.to_dict(),'operator_sources':{'edges':'graph'}}]})
    provider=Provider()
    args=dict(estimator=model,catalog_root=BUNDLE_FIXTURE/PIN['root'],catalog_hash=PIN['bundle_hash'],
              sources=s,backends=b,backend_clients=clients)
    request=InterpretationRequest('Count all KNOWS relationships, allowing the selected mode budget.',context={'query_id':'budget-heldout'})
    exact=run_question(request,provider,mode='precision',one_shot_policy=policy(mode='precision'),**args)
    fast=run_question(request,provider,mode='performance',one_shot_policy=policy(2),**args)
    assert exact['success'] and fast['success'],(exact.get('error'),fast.get('error'))
    assert exact['answer_rows']==[{'n':8}] and fast['answer_rows']==[{'n':2}]
    assert exact['final_plan_executions']==fast['final_plan_executions']==1
    assert fast['answer_semantics']=='budgeted_source_relations'
    assert fast['approximation']['retrieval']['source_rows_omitted']
    assert not fast['approximation']['retrieval']['aggregate_values_full_source_exact']
    assert provider.calls==2 and len(calls)==2 and not fast['observation_calls']
    denied=run_question(replace(request,context={**request.context,'require_complete_results':True}),
        provider,mode='performance',one_shot_policy=policy(2),**args)
    assert denied['status']=='configuration_unavailable' and provider.calls==2 and len(calls)==2
    assert 'retrieval_rows_per_relation' not in policy().to_dict()
    with pytest.raises(ValueError,match='performance mode'):policy(2,mode='precision')


def test_approximation_survives_compact_outcome_and_method_handoff(tmp_path,monkeypatch):
    from xgap.experiments import one_shot_records as records, nl_method_worker as worker
    request=records.write_once(tmp_path/'request.json',{'question_id':'budget-handoff',
        'population':'development','exposure':'independent approximate-count boundary'})
    scope={'answer_semantics':'budgeted_source_relations','approximation':{'retrieval':{
        'source_rows_omitted':True,'aggregate_values_full_source_exact':False}}}
    core={'success':True,'status':'answered','answer_rows':[{'n':2}],**scope}
    trace=records.write_once(tmp_path/'trace.json',core)
    outcome=records.write_record_outcome(tmp_path,core,trace)
    child={'success':True,'status':'answered','model_network_calls':0,'input_tokens':0,'output_tokens':0,
        'final_plan_executions':1,'backend_network_calls':1,'result':trace,'outcome':outcome}
    monkeypatch.setattr(worker,'run_record',lambda **kw:child)
    result=worker.run_nl(request_path=request['path'],request_sha256=request['sha256'],
        profile_path='unused',profile_sha256='0'*64,method='xgap-performance',output=tmp_path/'worker')
    answer=json.loads(records.read_pinned(result['result']['path'],result['result']['sha256']))
    assert result['success'] and answer['answer']==[{'n':2}]
    assert all(answer[k]==result[k]==v for k,v in scope.items())
