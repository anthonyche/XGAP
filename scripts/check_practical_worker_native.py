#!/usr/bin/env python3
"""One new strong/common-worker boundary on already frozen tiny native stores.

The authored semantic template is an explicit input, not an NL interpretation
result. No model, alternative execution, data load, training or baseline call.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession, resolve_profile_inputs
from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_practical_trial
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_records import run_record
from xgap.experiments.process_guard import ProcessBudget
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.schema_source_routing import source_assignments
from xgap.semantic.compact_lowering import lower_compact_query


FIXTURE=REPO/'tests/fixtures/compact_anchor_v1.json'
MODES=REPO/'datasets/practical_model_profile_v1/profile.json'


def prepare_inputs(root):
    """Pin a trusted development template; expected rows remain outside inputs."""
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    prepared=json.loads(read_pinned(PREPARED,PREPARED_SHA));parent=prepared['profile']
    path=Path(parent['path'])
    doc,_,_,sources,_,_,_=FrozenOneShotProfile.load(path,expected_sha256=parent['sha256']).materialize()
    doc=deepcopy(doc);resolve_profile_inputs(doc,path.parent)
    case=json.loads(FIXTURE.read_text())['cases'][0]
    program,_=lower_compact_query(case['gold_compact'],doc['source_schema'],version='v2')
    operators=[];replaced=[]
    for op in program.operators:
        raw=op.to_dict()
        if raw.pop('constraints'):raise ValueError('This fixture expects inline typed conditions')
        raw['hole_ids']=[]
        condition=raw['parameters'].get('condition',{})
        for atom in condition.get('args',[]):
            if atom.get('op')=='eq' and type(atom.get('value')) is str and atom['value']=='1':
                atom['value']={'$hole':'business_id'};raw['hole_ids'].append('business_id');replaced.append(op.operator_id)
        operators.append(raw)
    if len(replaced)!=1:raise ValueError('Expected exactly one authored business-ID binding')
    template={'schema_version':'m15-e3-semantic-intake-template-v1','template_id':'strong-worker-native-tiny',
        'template_version':'1','holes':[{'hole_id':'business_id','kind':'constraint','phrases':['business ID 1'],'required':True}],
        'constraints':[],'operators':operators,'roots':list(program.roots),
        'metadata':{'development_only':True,'scope':'trusted authored compact fixture; not unaided NL'}}
    intake=write_once(root/'intake.json',template)
    assignments,_=source_assignments(program,doc['source_schema'],sources)
    modes=deepcopy(json.loads(MODES.read_text())['modes'])
    for name,mode in modes.items():
        mode['semantic'].update(allowed_unvalidated=[],improve_physical=False)
        mode['search']['improvement_actions']=0
        mode['search']['resources'].update(model_calls=0,tokens=0,remote_calls=16)
        mode['actions']={}
    for spec in doc['backends'].values():spec['client']['url']='http://127.0.0.1:1'
    profile={'schema_version':'xgap-frozen-practical-profile-v1','profile_id':'strong-worker-native-tiny-v1',
        'dataset':doc['dataset'],'intake':{'path':intake['path'],'sha256':intake['sha256']},
        'operator_sources':assignments,'catalog':doc['catalog'],'estimator':doc['estimator'],
        'sources':doc['sources'],'backends':doc['backends'],'acquisitions':{},'modes':modes,
        'offline':{'prepared_stores':{'path':str(PREPARED),'sha256':PREPARED_SHA},'parent_profile':parent,
            'fixture':stream_pin(FIXTURE),'scope':'one development outer-worker boundary; no paper population',
            'formal_campaign_release':False,'fit_calls':0,'catalog_builds':0,'weights_changed':False}}
    pin=write_once(root/'profile.json',profile)
    FrozenPracticalProfile.load(pin['path'],expected_sha256=pin['sha256'])
    request=write_once(root/'request.json',{'schema_version':'xgap-practical-request-v1',
        'question_id':'STRONG-WORKER-NATIVE-01','question':case['question'],
        'trusted_bindings':{'business_id':'constraint:1'},'predictions':{},'clarifications':{},
        'population':'development','exposure':'previously exposed tiny authored semantic template'})
    return {'profile':pin,'request':request,'fixture':stream_pin(FIXTURE)}


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    receipt={'schema_version':'xgap-practical-worker-native-gate-v1','success':False,'paper_result':False,
        'model_calls':0,'fit_calls':0,'baseline_calls':0,'catalog_builds':0,'data_loads':0,
        'automatic_retries':0,'maximum_final_plans':1,'closures':[]}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit first')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        pins=prepare_inputs(root/'inputs');receipt['input']=write_once(root/'input-seal.json',pins)
        p,q=pins['profile'],pins['request']
        preflight=run_record(profile_path=p['path'],profile_sha256=p['sha256'],request_path=q['path'],
            request_sha256=q['sha256'],mode='exact',output=root/'preflight')
        if not preflight['success']:raise ValueError('Strong preflight failed before service startup')
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=16,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        native=json.loads(read_pinned(session.profile['path'],session.profile['sha256']))
        deployed=json.loads(read_pinned(p['path'],p['sha256']))
        if native['sources']!=deployed['sources']:raise ValueError('Serving source identity differs')
        for name,spec in deployed['backends'].items():
            if spec['semantic']!=native['backends'][name]['semantic']:raise ValueError('Serving semantics differ')
            current=native['backends'][name]['client']
            if any(spec['client'][k]!=current[k] for k in spec['client'] if k!='url'):
                raise ValueError('Serving client contract differs beyond its endpoint')
            spec['client']['url']=current['url']
        deployed['offline']['serving_ready']=session.ready_pin
        profile=write_once(root/'deployment-profile.json',deployed)
        outcome=run_practical_trial(request_path=q['path'],request_sha256=q['sha256'],
            profile_path=profile['path'],profile_sha256=profile['sha256'],method='xgap-strong-exact',
            output=root/'trial',owned_services=session.owned,observer=session.observer,
            budget=ProcessBudget(wall_seconds=30))
        receipt['trial']=outcome['receipt'];receipt['timing']=stream_pin(root/'trial/timing.json')
        # Only the external scorer reads expected answers, after a sealed outcome.
        case=json.loads(read_pinned(pins['fixture']['path'],pins['fixture']['sha256']))['cases'][0]
        actual=None
        if outcome['success']:
            answer=json.loads(read_pinned(outcome['result']['path'],outcome['result']['sha256']))['answer']
            actual=normalize_rows(answer,case['normalization'])
        expected=normalize_rows(case['expected_rows'],case['normalization'])
        receipt['score']=write_once(root/'score.json',{'answer_em':int(actual==expected),'actual':actual,'expected':expected,
            'scope':'independent authored tiny gold after durable method result','reference':pins['fixture']})
        observed=outcome['source_observations']
        core=json.loads(read_pinned(outcome['core_result']['path'],outcome['core_result']['sha256'])) if outcome.get('core_result') else {}
        replay_path=root/'trial/worker/core/replay.json'
        captures=json.loads(replay_path.read_text())['backends'] if replay_path.exists() else []
        receipt.update(source_calls=observed['requests'],response_bytes=observed['response_body_bytes'],
            source_rows=sum(len(json.loads(read_pinned(p['path'],p['sha256']))['execution']['rows']) for p in captures),
            answer_em=int(actual==expected),final_plan_executions=core.get('final_plan_executions'),
            online_ms=outcome['timing']['total_online_ms'],model_calls=outcome['model_calls'],
            semantic_validation=outcome.get('semantic_validation'),serving=session.ready_pin,
            success=bool(outcome['success'] and outcome['can_continue_session'] and actual==expected and
                observed['requests']==core.get('backend_remote_calls')==11 and core.get('final_plan_executions')==1 and
                outcome['model_calls']==outcome['input_tokens']==outcome['output_tokens']==0 and
                outcome.get('unvalidated_bindings')==[]))
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        receipt['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped')) for c in receipt['closures'])
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'source_calls':receipt.get('source_calls'),
        'answer_em':receipt.get('answer_em'),'error':receipt.get('error')}),flush=True)
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    with deadline(240):raise SystemExit(main(**vars(parser.parse_args())))
