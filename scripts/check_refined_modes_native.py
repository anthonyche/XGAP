#!/usr/bin/env python3
"""Two new ordinary NL mode requests on frozen tiny stores; one attempt each."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess

from check_compact_roles_native import PREPARED, PREPARED_SHA
from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.compact_profile import derive_compact_contribution_profile
from xgap.experiments.equality_key_bounds import derive_equality_profile
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_records import write_once, run_record
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.refined_modes_profile import derive_refined_modes_profile
from xgap.experiments.row_normalization import normalize_rows


def main(output,read_key=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False);session=None
    previous=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
    receipt={'schema_version':'xgap-refined-modes-native-v1','success':False,'maximum_model_calls':2,
        'maximum_final_plans':2,'automatic_retries':0,'data_loads':0,'catalog_builds':0,'fit_calls':0,
        'baseline_calls':0,'paper_result':False,'cases':[],'closures':[],
        'scope':'new NL question; frozen tiny facts; mode wiring and correctness, not speedup statistics'}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
            raise ValueError('Commit before live mode gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        key=getpass.getpass('LLM credential (not recorded): ') if read_key else previous
        if not key:raise ValueError('Missing configured model credential')
        os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key;key=None
        fixture_path=REPO/'tests/fixtures/refined_modes_native_v1.json'
        fixture=json.loads(fixture_path.read_text());case=fixture['case']
        prep={'path':'/Users/anthonyche/xgap-data/equality-bounds-native-20260913-v1/offline/receipt.json',
            'sha256':'cdd6432e86e24695395c9977295f2270fcd5372c49b7a0f02103b70d0e334896'}
        stats=json.loads(read_pinned(prep['path'],prep['sha256']))['statistics']
        receipt['intent']=write_once(root/'intent.json',{'fixture':stream_pin(fixture_path),
            'prepared':{'path':str(PREPARED),'sha256':PREPARED_SHA},'frozen_statistics':prep,
            'row_budget':2,'max_quality_deficit':.1,'modes':['precision','performance'],
            'question_and_source_schema_only_to_model':True,'gold_input_to_runtime':False,
            'evaluation_questions_retried':False,'independent_full_gold_rows':2})
        session=NativeStoreSession(root=root/'session',prepared_path=PREPARED,prepared_sha256=PREPARED_SHA,
            discard_serving_copies=True,budget=SourceObservationBudget(max_calls=64,request_bytes=1024**2,
                phase_request_bytes=4*1024**2,response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
        with deadline(120):session.start()
        compact=derive_compact_contribution_profile(parent_path=session.profile['path'],
            parent_sha256=session.profile['sha256'],output=root/'contribution')
        equality=derive_equality_profile(parent_path=compact['path'],parent_sha256=compact['sha256'],
            statistics=stats,output=root/'equality.json')
        profile=derive_refined_modes_profile(parent_path=equality['path'],parent_sha256=equality['sha256'],
            output=root/'refined-profile.json',rows_per_relation=2,max_quality_deficit=.1)
        receipt['profile']=profile
        dataset=json.loads(read_pinned(profile['path'],profile['sha256']))['dataset']
        normalization=case['normalization']
        for mode in ('precision','performance'):
            path=root/mode;path.mkdir()
            request=write_once(path/'request.json',{'schema_version':'xgap-one-shot-evaluation-request-v1',
                'question_id':case['id']+'-'+mode,'question':case['question'],'population':fixture['population'],
                'exposure':fixture['exposure'],'require_complete_results':mode=='precision'})
            reference=write_once(path/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
                'question_id':case['id']+'-'+mode,'dataset':dataset,'ordered':True,'normalization':normalization,
                'rows':normalize_rows(case['expected_rows'],normalization),'derivation':fixture['derivation']})
            preflight=run_record(profile_path=profile['path'],profile_sha256=profile['sha256'],
                request_path=request['path'],request_sha256=request['sha256'],mode=mode,
                output=path/'preflight',operation='preflight')
            if not preflight['success']:raise ValueError('New mode request preflight failed')
            trial=run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],method='xgap-'+mode,
                output=path/'execution',owned_services=session.owned,observer=session.observer,
                profile_path=profile['path'],profile_sha256=profile['sha256'])
            score=score_trial(trial['receipt']['path'],receipt_sha256=trial['receipt']['sha256'],
                reference_path=reference['path'],reference_sha256=reference['sha256'],output=path/'score.json')
            core_path=path/'execution/worker/core/result.json';core=json.loads(core_path.read_text()) if core_path.exists() else {}
            item={'mode':mode,'trial':trial['receipt'],'score':stream_pin(path/'score.json'),
                'answer_em':score['answer_em'],'status':trial['status'],'model_calls':trial['model_calls'],
                'input_tokens':trial.get('input_tokens'),'output_tokens':trial.get('output_tokens'),
                'online_ms':trial['timing']['total_online_ms'],'source_calls':trial['source_observations']['requests'],
                'source_response_bytes':trial['source_observations']['response_body_bytes'],
                'final_plan_executions':core.get('final_plan_executions'),'selection':core.get('selection'),
                'answer_rows':core.get('answer_rows'),'approximation':core.get('approximation')}
            receipt['cases'].append(item)
            print(json.dumps({k:item[k] for k in ('mode','answer_em','status','model_calls','source_calls','online_ms')}),flush=True)
            if not trial['can_continue_session']:
                break  # No restart or retry after a failed live boundary.
        receipt['success']=len(receipt['cases'])==2 and all(
            c['answer_em']==1 and c['model_calls']==1 and c['final_plan_executions']==1 for c in receipt['cases'])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        if previous is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=previous
        key=None
        receipt['success'] &= all(all(c[k] for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped'))
                                 for c in receipt['closures'])
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--read-key',action='store_true')
    with deadline(600):raise SystemExit(main(**vars(parser.parse_args())))
