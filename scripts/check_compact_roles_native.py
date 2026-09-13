#!/usr/bin/env python3
"""Three new ordinary NL cases, one attempt each on frozen tiny native stores."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess

from native_store_session import NativeStoreSession
from prepare_rdf_tdb import REPO, stream_pin
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.compact_profile import derive_compact_prompt_profile
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.one_shot_profile import read_pinned

PREPARED=Path('/Users/anthonyche/xgap-data/native-campaign-boundary-20260913-v2/prepared.json')
PREPARED_SHA='8f3c88515f52f8526faa4f9963a381ad1df1af7bf419f9bbdce0ec5e11648051'
FIXTURE=REPO/'tests/fixtures/compact_roles_v2.json'


def main(output,read_key=False):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    previous=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY');session=None;session_count=0
    receipt={'schema_version':'xgap-compact-role-native-gate-v2','success':False,'maximum_model_calls':3,
        'maximum_final_plans':3,'automatic_retries':0,'data_loads':0,'catalog_builds':0,'fit_calls':0,
        'baseline_calls':0,'paper_result':False,'cases':[],'closures':[]}
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before live gate')
        receipt['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        key=getpass.getpass('LLM credential (not recorded): ') if read_key else previous
        if not key:raise ValueError('Missing configured model credential')
        os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key;key=None
        fixture=json.loads(FIXTURE.read_text());assert len(fixture['cases'])==3
        dataset={'dataset_id':'financial-binding-tiny','version':'financial-tiny-v1'}
        receipt['input']=write_once(root/'input.json',{'fixture':stream_pin(FIXTURE),
            'prepared':{'path':str(PREPARED),'sha256':PREPARED_SHA},'prompt_version':'v2',
            'one_call_each':True,'old_formal_questions_retried':False,'overall_seconds':600})
        for i,case in enumerate(fixture['cases']):
            path=root/case['id'];path.mkdir()
            request=write_once(path/'request.json',{'schema_version':'xgap-one-shot-evaluation-request-v1',
                'question_id':case['id'],'question':case['question'],'population':fixture['population'],'exposure':fixture['exposure']})
            spec={'schema_version':'xgap-row-normalization-v1','fields':{k:('decimal3-half-up' if k=='total_amount' else 'text')
                for k in case['expected_rows'][0]}}
            from xgap.experiments.row_normalization import normalize_rows
            reference=write_once(path/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
                'question_id':case['id'],'dataset':dataset,'ordered':True,'normalization':spec,
                'rows':normalize_rows(case['expected_rows'],spec),'derivation':fixture['derivation']})
            if session is None:
                session_count+=1
                session=NativeStoreSession(root=root/f'session-{session_count:03}',prepared_path=PREPARED,
                    prepared_sha256=PREPARED_SHA,discard_serving_copies=True,
                    budget=SourceObservationBudget(max_calls=64,request_bytes=1024**2,phase_request_bytes=4*1024**2,
                        response_bytes=2*1024**2,phase_response_bytes=8*1024**2,timeout_seconds=20))
                with deadline(120):session.start()
                profile=derive_compact_prompt_profile(parent_path=session.profile['path'],parent_sha256=session.profile['sha256'],
                    output=session.root/'prompt-v2')
            outcome=run_nl_trial(request_path=request['path'],request_sha256=request['sha256'],
                method='xgap-'+case['mode'],output=path/'execution',owned_services=session.owned,observer=session.observer,
                profile_path=profile['path'],profile_sha256=profile['sha256'])
            score=score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
                reference_path=reference['path'],reference_sha256=reference['sha256'],output=path/'score.json')
            core_path=path/'execution/worker/core/result.json';core=json.loads(core_path.read_text()) if core_path.exists() else {}
            admitted=[c for c in core.get('interpretation',{}).get('candidates',[]) if c.get('status')=='admitted']
            mentions=[[h['mention'] for h in c['program']['holes']] for c in admitted]
            agreement=bool(mentions) and all(sorted(m)==sorted(case['expected_mentions']) for m in mentions)
            receipt['cases'].append({'question_id':case['id'],'mode':case['mode'],'profile':profile,'receipt':outcome['receipt'],
                'score':stream_pin(path/'score.json'),'answer_em':score['answer_em'],'status':outcome['status'],
                'model_calls':outcome['model_calls'],'source_calls':outcome['source_observations']['requests'],
                'online_ms':outcome['timing']['total_online_ms'],'admitted_mentions':mentions,'role_contract_match':agreement})
            if not outcome['can_continue_session']:
                receipt['closures'].append(session.close());session=None
        receipt['success']=all(c['answer_em']==1 and c['role_contract_match'] and c['model_calls']==1 for c in receipt['cases'])
    except Exception as error:receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:receipt['closures'].append(session.close())
        if previous is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
        else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=previous
        key=None
        receipt['success'] &= all(c['owned_groups_drained'] and c['owned_processes_terminal'] and c['observer_stopped'] for c in receipt['closures'])
        pin=write_once(root/'receipt.json',receipt)
    print(json.dumps({'success':receipt['success'],'receipt':pin,'cases':receipt['cases'],'error':receipt.get('error')}))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--read-key',action='store_true')
    with deadline(600):raise SystemExit(main(**vars(p.parse_args())))
