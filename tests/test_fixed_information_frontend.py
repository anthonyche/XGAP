"""Matched binding semantics and one unchanged external answer; controlled tools."""
import json
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef

from test_practical_profile import FIXTURE, ROOT, no_network, sha
from xgap.agent.fixed_information_frontend import prepare_fixed_information_query
from xgap.agent.practical_planning import program_identity
from xgap.experiments import fixed_information_worker as worker
from xgap.experiments.nl_method_worker import run_nl
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_records import publish_profile
from xgap.tools import ToolRegistry
from xgap.tools.contracts import FunctionTool, ToolResult


def setup(root, *, prediction='predicate:knows', authority='predicate:follows', unsupported=False):
    doc=json.loads((FIXTURE/'profile.json').read_text())
    template={'schema_version':'m15-e3-semantic-intake-template-v1','template_id':'shared-slot-toy','template_version':'1',
        'holes':[{'hole_id':'predicate','kind':'predicate','phrases':['connections'],'required':True}],
        'constraints':[],'operators':[{'operator_id':'links','kind':'match','input_ids':[],'input_kinds':[],
            'output_kind':'binding_set','parameters':{'edge':{'label':{'$hole':'predicate'}},'entity_field':'edge',
                'source_field':'person','target_field':'friend'},'required_capabilities':[],'hole_ids':['predicate']}],
        'roots':['links'],'metadata':{'scope':'controlled shared frontend fixture'}}
    if unsupported:
        template['operators'].append({'operator_id':'min','kind':'aggregate','input_ids':['links'],'input_kinds':['binding_set'],
            'output_kind':'grouped_bindings','parameters':{'group_by':[],'aggregations':{'n':{'op':'min','field':'edge'}}},
            'required_capabilities':[],'hole_ids':[]})
        template['roots']=['min']
    pin=write_once(root/'intake.json',template);doc['intake']={k:pin[k] for k in ('path','sha256')}
    doc['catalog']['path']=str((FIXTURE/doc['catalog']['path']).resolve());doc['estimator']=None
    doc['operator_sources']={'links':'toy'}
    doc['sources']={'toy':{**doc['sources']['toy'],'replicas':['fuseki']}}
    doc['backends']={'fuseki':doc['backends']['fuseki']}
    semantic=doc['backends']['fuseki']['semantic']
    mapping={k:semantic[k] for k in ('resource_namespace','identity_property','backend_mapping','rdf_edge_encoding','rdf_node_classes')}
    pin=write_once(root/'mapping.json',mapping)
    doc['external_frontend']={'policy':'fixed_action_order_v1','mapping':{k:pin[k] for k in ('path','sha256')}}
    for spec in doc['acquisitions'].values():
        if spec['kind']=='model':spec['provider']['prompt']['path']=str((FIXTURE/spec['provider']['prompt']['path']).resolve())
    p=write_once(root/'profile.json',doc)
    profile,cfg=FrozenPracticalProfile.load_materialized(p['path'],expected_sha256=p['sha256'])
    raw={'schema_version':'xgap-practical-request-v1','question_id':'SHARED-SLOT-01','question':'Return connections',
        'population':'controlled-tiny','exposure':'shared input scope fixture','trusted_bindings':{},
        'predictions':{} if prediction is None else {'predicate':prediction},'clarifications':{}}
    q=profile.prepare(raw,request_sha256='0'*64,request_root=root,mode='exact',materialized=cfg)
    a=doc['acquisitions']['predicate-clarification']
    response=write_once(root/'clarification.json',{'schema_version':'xgap-clarification-bindings-v1',
        'program_sha256':program_identity(q.program),'source_id':a['source_id'],'version':a['version'],'bindings':{'predicate':authority}})
    raw['clarifications']={'predicate-clarification':{k:response[k] for k in ('path','sha256')}}
    request=write_once(root/'request.json',raw)
    return profile,cfg,p,request,mapping


def prepared(parts,mode):
    profile,cfg,_,request,_=parts
    return profile.prepare(json.loads(Path(request['path']).read_text()),request_sha256=request['sha256'],
        request_root=Path(request['path']).parent,mode=mode,materialized=cfg)


def run(parts,mode,*,handler=None):
    q=prepared(parts,mode);cfg=parts[1];opts=q.options
    registry=ToolRegistry()
    for spec in opts.resolution_tools.specs():
        tool=opts.resolution_tools.get(spec.name)
        if handler and spec.remote:tool=FunctionTool(spec,handler)
        registry.register(tool)
    return prepare_fixed_information_query(q.program,initial_state=opts.initial_state,mode=opts.mode,
        actions=opts.actions,predictions=opts.predictions,resolution_tools=registry,limits=opts.limits,
        physical_profile=opts.physical_profile,operator_sources=q.provider.operator_sources,binding_values=cfg[2].bindings,
        sources=cfg[4],backends=cfg[5],mapping=parts[4])


def proposal(args,context,*,candidate='predicate:knows',alter=None):
    value={k:args[k] for k in ('slot','program_sha256','source_id','version')};value['candidate_id']=candidate
    metrics={'model_calls':1,'tokens':5,'remote_calls':1}
    if alter=='scope':value['version']='another-snapshot'
    if alter=='extra':value['authoritative']=True
    if alter=='unknown_usage':metrics.pop('tokens')
    if alter=='null_usage':metrics['tokens']=None
    if alter=='overspend':metrics['tokens']=999999
    if alter=='invalid_usage':metrics['model_calls']=-1
    return ToolResult.success('practical.llm:predicate',value,metrics=metrics)


@pytest.mark.parametrize('mode,expected,clarifications',[('exact','FOLLOWS',1),('performance','KNOWS',0)])
def test_same_prediction_preserves_exact_authority_and_performance_permission(tmp_path,monkeypatch,mode,expected,clarifications):
    parts=setup(tmp_path)
    from xgap.agent import practical_planning
    monkeypatch.setattr(practical_planning,'_baseline',lambda *a,**kw:pytest.fail('Fixed frontend generated an XGAP plan'))
    result=run(parts,mode)
    assert result['success'] and result['compilations']==1 and result['strong_plan'] is None,result
    assert result['model_calls']==0 and result['clarification_calls']==clarifications
    assert result['selected_program']['operators'][0]['parameters']['edge']['label']==expected
    assert result['unvalidated_bindings']==([] if mode=='exact' else ['predicate'])
    graph=Graph().parse(ROOT/'datasets/practical_model_toy_v1/load.ttl')
    actual={str(row.asdict()['edge']) for row in graph.query(result['artifact']['text'])}
    expected_edges={str(edge) for edge in graph.subjects(URIRef('https://xgap.test/toy/label'),Literal(expected))}
    assert actual==expected_edges and actual
    assert result['physical_candidates']==result['source_calls']==result['estimator_calls']==0


@pytest.mark.parametrize('alter,success',[('scope',False),('extra',False),('overspend',False),('unknown_usage',True),('null_usage',True),('invalid_usage',False)])
def test_paid_observation_scope_budget_and_unknown_usage_are_preserved(tmp_path,alter,success):
    parts=setup(tmp_path,prediction=None);calls=[]
    def handler(args,context):
        calls.append(args);return proposal(args,context,alter=alter)
    result=run(parts,'performance',handler=handler)
    assert result['success'] is success and len(calls)==1
    assert result['model_calls']==(None if alter=='invalid_usage' else 1) and result['clarification_calls']==0
    assert result['compilations']==int(success)
    if alter in ('unknown_usage','null_usage'):
        assert result['tokens'] is None and not result['usage_complete']
        assert result['resource_usage_for_admission']['tokens']==4096
    if alter=='overspend':assert result['tokens']==999999


def test_declared_model_failure_advances_once_to_the_frozen_authority_continuation(tmp_path):
    parts=setup(tmp_path,prediction=None);calls=[]
    def failed(args,context):
        calls.append(args);return ToolResult.error_result('practical.llm:predicate','controlled unknown paid failure')
    result=run(parts,'performance',handler=failed)
    assert result['success'] and result['model_calls'] is None and result['tokens'] is None
    assert result['acquisition_attempts']==2 and result['clarification_calls']==1 and len(calls)==1
    assert result['selected_program']['operators'][0]['parameters']['edge']['label']=='FOLLOWS'
    assert [a['observed_outcome'] for a in result['actions']]==['error','candidate-1']


def test_selected_global_unsupported_form_does_not_try_another_binding(tmp_path):
    result=run(setup(tmp_path,unsupported=True),'performance')
    assert not result['success'] and result['status']=='global_compilation_failed'
    assert result['compilations']==1 and result['artifact'] is None
    assert result['acquisition_attempts']==result['model_calls']==0


@pytest.mark.parametrize('status', ['returned', 'timeout'])
def test_composed_worker_submits_one_query_and_keeps_native_wrong_or_failed_response(tmp_path,monkeypatch,status):
    parts=setup(tmp_path);_,_,p,q,_=parts;calls=[]
    wrong={'head':{'vars':['native_wrong']},'results':{'bindings':[]}}
    def query(endpoint,text,*,seconds,output):
        calls.append((endpoint,text))
        result={'status':status,'http_status':200 if status=='returned' else None,
            'body_utf8':json.dumps(wrong),'client_wall_ms':12}
        write_once(output,result);return result
    monkeypatch.setattr(worker,'query_once',query)
    result=run_nl(request_path=q['path'],request_sha256=q['sha256'],profile_path=p['path'],profile_sha256=p['sha256'],
        method='fixed-info-performance-fedx',endpoint='http://method.invalid/sparql',output=tmp_path/'worker')
    assert result['success']==(status=='returned'),result
    assert result['track']=='trusted_template' and result['external_engine']=='fedx'
    assert result['top_level_attempts']==len(calls)==1 and result['model_calls']==0
    assert result['strong_plan'] is None and result['planning_ms'] is None and result['automatic_retries']==0
    assert 'SERVICE' not in calls[0][1]
    answer=json.loads(Path(result['result']['path']).read_text())['answer']
    assert answer==(wrong if status=='returned' else None)


def test_mapping_is_pinned_relocated_and_required_before_any_action(tmp_path,monkeypatch):
    parts=setup(tmp_path);_,_,p,q,_=parts
    (tmp_path/'relocated').mkdir()
    pin=publish_profile(profile_path=p['path'],profile_sha256=p['sha256'],output=tmp_path/'relocated/profile.json')
    doc=json.loads(Path(pin['path']).read_text())
    assert Path(doc['external_frontend']['mapping']['path']).is_absolute()
    Path(doc['external_frontend']['mapping']['path']).write_text('{}')
    monkeypatch.setattr(worker,'query_once',lambda *a,**kw:pytest.fail('Query after mapping drift'))
    result=run_nl(request_path=q['path'],request_sha256=q['sha256'],profile_path=pin['path'],profile_sha256=pin['sha256'],
        method='fixed-info-exact-fedup',endpoint='http://method.invalid/sparql',output=tmp_path/'failed-worker')
    assert not result['success'] and result['model_calls']==result['top_level_attempts']==0
    assert not (tmp_path/'failed-worker/frontend-intent.json').exists()
