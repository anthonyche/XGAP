#!/usr/bin/env python3
"""One ordinary estimated-choice tiny native execution with frozen key bounds."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from prepare_tiny_equality_bounds import prepare
from xgap.agent.question import run_question
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.equality_key_bounds import derive_equality_profile
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients, read_pinned
from xgap.experiments.one_shot_records import CapturingClient, write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.schema_source_routing import source_assignments
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import SCHEMA


def main(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    receipt={'schema_version':'xgap-equality-bounds-native-v1','success':False,'closures':[],
        'model_calls':0,'fit_calls':0,'baseline_calls':0,'data_loads':0,'catalog_builds':0,
        'maximum_final_plan_executions':1,'automatic_retries':0,'paper_result':False,
        'scope':'authored tiny interpretation enters ordinary frozen-estimate selection; no forced strategy'}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise ValueError('Commit before native gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        prepared=json.loads(read_pinned(PREPARED,PREPARED_SHA));parent=prepared['profile']
        preparation=prepare(parent_path=parent['path'],parent_sha256=parent['sha256'],output=root/'offline')
        receipt['offline_preparation']=preparation
        stats=json.loads(read_pinned(preparation['path'],preparation['sha256']))['statistics']
        fixture=REPO/'tests/fixtures/compact_anchor_v1.json';case=json.loads(fixture.read_text())['cases'][0]
        receipt['intent']=write_once(root/'intent.json',{'fixture':stream_pin(fixture),'statistics':stats,
            'prepared':{'path':str(PREPARED),'sha256':PREPARED_SHA},'selection':'ordinary estimated argmin',
            'one_execution_only':True,'alternatives_executed':0,'scope':'deterministic planning chain'})
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=64,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        serving=derive_equality_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
            statistics=stats,output=root/'serving-profile.json')
        receipt['serving_profile']=serving
        at=time.perf_counter()
        profile=FrozenOneShotProfile.load(serving['path'],expected_sha256=serving['sha256'])
        doc,model,_,sources,backends,specs,modes=profile.materialize()
        program,_=lower_compact_query(case['gold_compact'],doc['source_schema'],version='v2')
        slots,_=source_assignments(program,doc['source_schema'],sources)
        class Authored:
            provider_id='independent-tiny-deterministic-interpretation'
            def interpret(self,request):
                return InterpretationResponse({'schema_version':SCHEMA,'candidates':[{'candidate_id':'tiny',
                    'quality_proxy':1.0,'program':program.to_dict(),'operator_sources':slots}]})
        records=[];lock=threading.Lock()
        clients={name:CapturingClient(client,root,records,lock) for name,client in native_clients(specs).items()}
        phase='frozen-key-bound-ordinary-entry';session.observer.set_phase(phase)
        with deadline(120):
            core=run_question(InterpretationRequest('Execute the independently authored tiny constrained path request.',
                context={'query_id':'tiny-frozen-key-bound-v1'}),Authored(),mode='performance',
                one_shot_policy=modes['performance'][0],estimator=model,
                catalog_root=profile.root/doc['catalog']['path'],catalog_hash=doc['catalog']['bundle_hash'],
                sources=sources,backends=backends,backend_clients=clients)
        core_pin=write_once(root/'core.json',core)
        observed=session.observer.seal_phase(phase)
        outcome={'success':core['success'],'status':core['status'],'core':core_pin,'selection':core.get('selection'),
            'final_plan_executions':core['final_plan_executions'],'source_calls':observed['requests'],
            'response_bytes':observed['response_body_bytes'],'source_observations':observed,
            'planning_ms':core['planning_ms'],'execution_ms':core['execution_ms'],
            'online_ms_before_outcome_seal':(time.perf_counter()-at)*1000}
        receipt['outcome']=write_once(root/'outcome.json',outcome)
        session.observer.release_phase(phase,receipt['outcome'])
        expected=normalize_rows(case['expected_rows'],case['normalization'])
        actual=normalize_rows(core['answer_rows'],case['normalization']) if core['success'] else None
        receipt['score']=write_once(root/'score.json',{'answer_em':int(actual==expected),'actual':actual,'expected':expected,
            'reference':stream_pin(fixture),'scope':'tiny deterministic correctness, no measured strategy optimality'})
        receipt.update(answer_em=int(actual==expected),selected_strategy=core.get('selection',{}).get('strategy_id'),
            success=core['success'] and actual==expected and core['final_plan_executions']==1,
            source_calls=observed['requests'],response_bytes=observed['response_body_bytes'])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        receipt['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped'))
                                 for c in receipt['closures'])
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'selected_strategy':receipt.get('selected_strategy'),
        'answer_em':receipt.get('answer_em'),'source_calls':receipt.get('source_calls'),'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args())))
