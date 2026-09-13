"""Only shared-NL and ordinary RDF instance connection risks, controlled I/O."""
from copy import deepcopy
import json
import threading
from types import SimpleNamespace

import pytest
from rdflib import Graph

from test_compact_provider import ResponseTransport, pool
from test_compact_lowering import financial_intents, EXPECTED
from test_global_semantic_sparql import ROOT, PIN, inputs
from xgap.agent.one_shot_question import run_one_shot_question
from xgap.agent.shared_external_frontend import prepare_external_query
from xgap.compilers.global_semantic_sparql import compile_global_program
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, REQUEST_SCHEMA, native_clients
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.program import SemanticGraphProgram


def setup_provider(monkeypatch,intents,mode='precision'):
    monkeypatch.setenv('XGAP_EXTERNAL_LLM_API_KEY','fixture-never-transmitted')
    profile=FrozenOneShotProfile.load(ROOT/'profile.json',expected_sha256=PIN)
    materialized=profile.materialize();doc,model,_,sources,backends,specs,modes=materialized
    policy,provider=modes[mode];transport=ResponseTransport(pool(*intents));provider.transport=transport
    raw={'schema_version':REQUEST_SCHEMA,'question_id':'SHARED-NL-TOY','question':'Find transfers from accounts owned by Alice.',
        'population':'tiny_development','exposure':'controlled interpretation; not measured model correctness'}
    request=profile.request(raw,mode,materialized)
    return profile,materialized,raw,request,policy,provider,transport


def test_highest_grounded_quality_chosen_once_without_cost_or_execution(monkeypatch,inputs):
    _,m,_,request,policy,provider,transport=setup_provider(monkeypatch,financial_intents()[:2])
    transport.payload['candidates'][0]['quality_proxy']=.1;transport.payload['candidates'][1]['quality_proxy']=.9
    r=prepare_external_query(request,provider,policy=policy,catalog_root=m[0]['catalog']['path'],
        catalog_hash=m[0]['catalog']['bundle_hash'],sources=m[3],mapping=inputs[2])
    assert r['success'] and r['selection']['candidate_id']=='c1'
    assert not r['selection']['estimated_cost_used'] and r['compilations']==1
    assert len(transport.calls)==r['model_calls']==1 and (r['input_tokens'],r['output_tokens'])==(10,20)
    assert r['backend_calls']==r['fit_calls']==r['automatic_retries']==0


def test_selected_unsupported_compilation_does_not_try_another_meaning(monkeypatch,inputs):
    unsupported=deepcopy(financial_intents()[0]);unsupported['select']['total_amount']['aggregate']='min'
    _,m,_,request,policy,provider,transport=setup_provider(monkeypatch,[unsupported,financial_intents()[0]])
    transport.payload['candidates'][0]['quality_proxy']=.9;transport.payload['candidates'][1]['quality_proxy']=.1
    r=prepare_external_query(request,provider,policy=policy,catalog_root=m[0]['catalog']['path'],
        catalog_hash=m[0]['catalog']['bundle_hash'],sources=m[3],mapping=inputs[2])
    assert not r['success'] and r['status']=='global_compilation_failed'
    assert r['selection']['candidate_id']=='c0' and r['compilations']==1 and len(transport.calls)==1
    assert r['artifact'] is None and r['backend_calls']==0


def test_ordinary_entry_accepts_instance_estimator_and_executes_only_selected_rdf_plan(monkeypatch,tmp_path):
    _,m,_,request,policy,provider,transport=setup_provider(monkeypatch,financial_intents()[:1],mode='performance')
    doc,model,_,sources,backends,specs,_=m;clients=native_clients(specs);calls=[];local_parser=threading.Lock()
    for name,client in clients.items():
        graph=Graph().parse(doc['offline']['rdf_loads'][specs[name]['database']]['path'])
        def post(query,graph=graph,name=name):
            # The controlled RDFLib parser is not a concurrent native endpoint.
            with local_parser:
                calls.append(name);return json.loads(graph.query(query).serialize(format='json'))
        monkeypatch.setattr(client,'_post_query',post)
    r=run_one_shot_question(request,provider,policy=policy,estimator=model,catalog_root=doc['catalog']['path'],
        catalog_hash=doc['catalog']['bundle_hash'],sources=sources,backends=backends,backend_clients=clients)
    write_once(tmp_path/'ordinary-core.json',r)
    assert r['success'],{'status':r['status'],'error':r['error'],'execution':r['execution']}
    assert r['answer_rows']==EXPECTED[0] and r['final_plan_executions']==1
    assert set(calls)=={'rdf_graph','rdf_control'} and len(calls)==r['backend_remote_calls']
    assert len(transport.calls)==1 and r['observation_calls']==r['automatic_retries']==0


def test_global_count_null_order_and_literal_variable_tokens(inputs):
    def op(identifier,kind,parents,parameters,output='binding_set',inkind='binding_set'):
        return {'operator_id':identifier,'kind':kind,'input_ids':parents,'input_kinds':[inkind]*len(parents),
            'output_kind':output,'parameters':parameters,'constraints':[],'required_capabilities':[]}
    source=op('accounts','match',[],{'node':{'label':'XGAPFinBenchAccount'},'entity_field':'account',
        'properties':{'id':'id','missing':'riskLevel'}})
    marker='literal ?source "quoted" <urn:test>'
    project=op('project','project',['accounts'],{'projections':{'id':{'kind':'field','field':'id'},
        'missing':{'kind':'field','field':'missing'},'marker':{'kind':'literal','value':marker}}})
    order=op('order','order_limit',['project'],{'order_by':[{'field':'missing','direction':'asc','nulls':'first'},
        {'field':'id','direction':'desc'}],'limit':None})
    aggregate=op('count','aggregate',['accounts'],{'group_by':[],'aggregations':{'all':{'op':'count','field':None,'distinct':True},
        'present':{'op':'count','field':'missing'},'sum_missing':{'op':'sum','field':'missing'}}},output='grouped_bindings')
    for operators,root in [([source,project,order],'order'),([source,aggregate],'count')]:
        program=SemanticGraphProgram.from_dict({'program_id':root,'operators':operators,'roots':[root],'holes':[],'metadata':{}})
        artifact=compile_global_program(program,inputs[2]);rows=[r.asdict() for r in inputs[3].query(artifact.text)]
        if root=='order':
            assert [str(r['id']) for r in rows]==['4','3','2','1']
            assert all('missing' not in r and str(r['marker'])==marker for r in rows)
        else:assert [{str(k):v.toPython() for k,v in r.items()} for r in rows]==[{'all':4,'present':0,'sum_missing':0}]


def test_external_nl_worker_preserves_native_wrong_response_with_one_query(monkeypatch,tmp_path):
    from xgap.experiments import nl_method_worker as worker
    profile,m,raw,_,_,_,transport=setup_provider(monkeypatch,financial_intents()[:1])
    request=write_once(tmp_path/'request.json',raw)
    monkeypatch.setattr(worker.FrozenOneShotProfile,'load',lambda *a,**kw:SimpleNamespace(materialize=lambda:m,request=profile.request))
    calls=[];wrong={'head':{'vars':['wrong']},'results':{'bindings':[]}}
    def query(endpoint,text,*,seconds,output):
        calls.append((endpoint,text,seconds));result={'status':'returned','http_status':200,'body_utf8':json.dumps(wrong),'client_wall_ms':12}
        write_once(output,result);return result
    monkeypatch.setattr(worker,'query_once',query)
    r=worker.run_nl(request_path=request['path'],request_sha256=request['sha256'],profile_path=ROOT/'profile.json',
        profile_sha256=PIN,method='fedx',output=tmp_path/'worker',endpoint='http://unused.invalid/sparql')
    assert r['success'] and r['top_level_attempts']==1 and r['model_calls']==1
    assert len(calls)==len(transport.calls)==1 and 'SERVICE' not in calls[0][1]
    answer=json.loads((tmp_path/'worker'/'answer.json').read_text())
    assert answer=={'answer_format':'sparql_json','answer':wrong}
    assert r['planning_ms'] is None and r['automatic_retries']==0


def test_common_nl_supervision_routes_nl_only_input_and_keeps_interrupted_usage_unknown(monkeypatch,tmp_path):
    from xgap.experiments import common_method_trial as module
    raw={'schema_version':REQUEST_SCHEMA,'question_id':'NL','question':'A natural-language request.',
         'population':'tiny_development','exposure':'controlled supervisor routing'}
    request=write_once(tmp_path/'request.json',raw)
    doc=json.loads((ROOT/'profile.json').read_text())
    monitor=SimpleNamespace(sample=lambda *a:None,summary=lambda:{'scope':'mock'},stop=lambda:{'complete':True,'recovery_ms':0})
    monkeypatch.setattr(module,'OwnedResources',lambda *a,**kw:monitor)
    observer=SimpleNamespace(set_phase=lambda phase:None,snapshot=lambda phase:{'failed_requests':0,'requests':0})
    for returned in (True,False):
        def guard(command,*,output,**kwargs):
            assert 'run_nl_method_worker.py' in command[1] and '--profile-sha256' in command
            target=output.parent/'worker';target.mkdir()
            if returned:write_once(target/'receipt.json',{'schema_version':'xgap-nl-method-worker-v1',
                'method':'fedx','question_id':'NL','request_sha256':request['sha256'],'profile_sha256':PIN,
                'dataset':doc['dataset'],'success':True,'status':'returned','model_calls':1,'input_tokens':10,'output_tokens':20})
            return {'success':returned,'status':'completed' if returned else 'wall_limit'}
        monkeypatch.setattr(module,'run_guarded_command',guard)
        r=module.run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],method='fedx',
            output=tmp_path/str(returned),owned_services=[SimpleNamespace(role='source'),SimpleNamespace(role='method_host')],
            observer=observer,profile_path=ROOT/'profile.json',profile_sha256=PIN,endpoint='http://unused.invalid')
        assert r['track']=='natural_language' and r['dataset']==doc['dataset'] and r['success'] is returned
        assert (r['model_calls'],r['input_tokens'])==((1,10) if returned else (None,None))
        assert r['quiescence']['complete'] and r['can_continue_session'] is returned
