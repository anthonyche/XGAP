#!/usr/bin/env python3
"""One paired tiny native budget boundary; no new data, fit, model or baseline."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import threading
import time

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.agent.question import run_question
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.equality_key_bounds import derive_equality_profile
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients, read_pinned
from xgap.experiments.one_shot_records import BackendReplay, CapturingClient, write_once, write_record_outcome
from xgap.experiments.tiny_work_training import op
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA
from xgap.semantic.program import SemanticGraphProgram


def query():
    nodes=[];slots={};roots=[]
    for name,source,parameters in (
        ('transfers','graph',{'edge':{'label':'TRANSFERRED_TO'},'entity_field':'e',
                             'source_field':'src','target_field':'dst','properties':{}}),
        ('no_control_edges','control',{'edge':{'label':'TRANSFERRED_TO'},'entity_field':'e',
                             'source_field':'src','target_field':'dst','properties':{}}),
        ('accounts','control',{'node':{'label':'XGAPFinBenchAccount'},'entity_field':'e','properties':{}})):
        nodes.append(op(name,'match',parameters=parameters));slots[name]=source
        root=name+'_count';roots.append(root)
        nodes.append(op(root,'aggregate',(name,),output='grouped_bindings',parameters={
            'group_by':[],'aggregations':{'n':{'op':'count','field':'e','distinct':False}}}))
    return SemanticGraphProgram.from_dict({'program_id':'independent-native-budget-counts',
        'operators':nodes,'roots':roots,'holes':[],'metadata':{}}),slots


def main(output,mode='both'):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    receipt={'schema_version':'xgap-budgeted-relations-native-v1','success':False,'closures':[],
        'model_calls':0,'fit_calls':0,'baseline_calls':0,'data_loads':0,'catalog_builds':0,
        'automatic_retries':0,'paper_result':False,'cases':[],
        'scope':'same independent query; one estimated final plan per mode; correctness boundary, not speedup evaluation'}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise ValueError('Commit before native gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        prep={'path':'/Users/anthonyche/xgap-data/equality-bounds-native-20260913-v1/offline/receipt.json',
            'sha256':'cdd6432e86e24695395c9977295f2270fcd5372c49b7a0f02103b70d0e334896'}
        stats=json.loads(read_pinned(prep['path'],prep['sha256']))['statistics']
        program,slots=query()
        receipt['intent']=write_once(root/'intent.json',{'prepared':{'path':str(PREPARED),'sha256':PREPARED_SHA},
            'frozen_statistics':prep,'fixture_source':stream_pin(REPO/'tests/test_finbench_rdf.py'),
            'program':program.to_dict(),'operator_sources':slots,'budget':2,
            'full_gold_counts':[0,4,8],'budget_scope_counts':[0,2,4],
            'derivation':'eight transfer edges in graph; four complete control account nodes; no control edges',
            'new_population':'independent-native-budget-development','evaluation_questions_retried':False})
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=32,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        serving=derive_equality_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
            statistics=stats,output=root/'serving-profile.json')
        receipt['serving_profile']=serving
        profile=FrozenOneShotProfile.load(serving['path'],expected_sha256=serving['sha256'])
        doc,model,_,sources,backends,specs,modes=profile.materialize()
        class Authored:
            provider_id='independent-native-budget-interpretation'
            def interpret(self,request):
                return InterpretationResponse({'schema_version':SCHEMA,'candidates':[{'candidate_id':'one',
                    'quality_proxy':1,'program':program.to_dict(),'operator_sources':slots}]})
        request=InterpretationRequest('Count graph transfers, control transfers and control accounts.',
            context={'query_id':'independent-native-budget-counts'})
        selected_modes=('precision','performance') if mode=='both' else (mode,)
        receipt['requested_modes']=list(selected_modes)
        for mode in selected_modes:
            path=root/mode;path.mkdir();records=[];lock=threading.Lock()
            policy=replace(modes[mode][0],retrieval_rows_per_relation=2 if mode=='performance' else None)
            clients={b:CapturingClient(c,path,records,lock,retain_payloads=False) for b,c in native_clients(specs).items()}
            args=dict(mode=mode,one_shot_policy=policy,estimator=model,catalog_root=profile.root/doc['catalog']['path'],
                catalog_hash=doc['catalog']['bundle_hash'],sources=sources,backends=backends)
            phase='native-budget-'+mode;session.observer.set_phase(phase);at=time.perf_counter()
            with deadline(120):core=run_question(request,Authored(),backend_clients=clients,**args)
            pin=write_once(path/'core.json',core);outcome=write_record_outcome(path,core,pin)
            observed=session.observer.seal_phase(phase)
            source_outcome=write_once(path/'source-outcome.json',{'outcome':outcome,'source_observations':observed})
            elapsed=(time.perf_counter()-at)*1000
            session.observer.release_phase(phase,source_outcome)
            ledger=write_once(path/'ledger.json',records)
            actual=sorted(row['n'] for row in core['answer_rows']) if core['success'] else None
            expected=[0,4,8] if mode=='precision' else [0,2,4]
            replay_clients={b:BackendReplay(b,[r for r in records if r['backend_id']==b]) for b in clients}
            replay=run_question(request,Authored(),backend_clients=replay_clients,**args)
            replay_pin=write_once(path/'replay.json',replay)
            # Grounding timings differ in replay; compare retrieval evidence separately.
            replay_ok=(replay['success'] and replay['answer_rows']==core['answer_rows']
                and replay['selected_plan']==core['selected_plan']
                and replay.get('approximation',{}).get('retrieval')==core.get('approximation',{}).get('retrieval')
                and all(c.position==len(c.records) for c in replay_clients.values()))
            scope=core.get('approximation',{}).get('retrieval')
            passed=(core['success'] and actual==expected and core['final_plan_executions']==1 and replay_ok
                and (mode=='precision' or (scope and scope['source_rows_omitted']
                     and not scope['aggregate_values_full_source_exact'])))
            item={'mode':mode,'success':passed,'core':pin,'outcome':outcome,'ledger':ledger,'actual':actual,
                'expected_budget_scope':expected,'full_source_answer_em':int(actual==[0,4,8]),
                'source_observations':observed,'source_outcome':source_outcome,'source_calls':observed['requests'],
                'source_response_bytes':observed['response_body_bytes'],'online_ms_through_outcome_seal':elapsed,
                'planning_ms':core['planning_ms'],'execution_ms':core['execution_ms'],
                'replay':replay_pin,'replay_success':replay_ok,'replay_network_calls':0}
            receipt['cases'].append(item);print(json.dumps({k:item[k] for k in (
                'mode','success','actual','full_source_answer_em','source_calls','source_response_bytes')}),flush=True)
        receipt['success']=len(receipt['cases'])==len(selected_modes) and all(c['success'] for c in receipt['cases'])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        receipt['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped'))
                                 for c in receipt['closures'])
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--mode',choices=('both','precision','performance'),default='both')
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args())))
