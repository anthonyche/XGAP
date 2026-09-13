#!/usr/bin/env python3
"""Only new summary mapping, hosted-method and common observer integration."""
import argparse
import json
from pathlib import Path
import subprocess

from campaign_method_hosts import CampaignMethodHosts
from rdf_tdb_session import RdfTdbSession
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_fixed_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.finbench_semantic import _Program
from xgap.experiments.fixed_semantic_worker import REQUEST_SCHEMA
from xgap.experiments.one_shot_records import write_once

REPO=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before native boundary')
    r={'success':False,'model_calls':0,'maximum_baseline_queries':2,'automatic_retries':0,'runs':[],
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'paper_result':False,'scope':'new host/summary/common observer only; no NL, old financial query or comparison sweep'}
    session=RdfTdbSession(root=root/'session',
        prepared_path='/Users/anthonyche/xgap-data/rdf-tdb-tiny-20260913-v1/receipt.json',
        prepared_sha256='cf4190cb71ec7ad635c34ab9a852b3f6bfe14d649b2048c9f897905564e2577d',
        prepared_input_sha256='5e8d77a2a70789e677258f31baddbda49a4ea67d972a8019c974df16bdef4c0c',budget=SourceObservationBudget())
    try:
        b=_Program('host-account-identities');a=b.node('accounts','account','account',{'account_id':'sourceId'})
        program,_=b.finish(b.project('result',a,account_id='account_id'));dataset=session.prepared['dataset']
        query='PREFIX fb: <https://xgap.dev/benchmark/finbench/v0.1.0/schema/> SELECT ?account_id WHERE { ?account a fb:Account; fb:sourceId ?account_id . }'
        request=write_once(root/'request.json',{'schema_version':REQUEST_SCHEMA,'question_id':'CAMPAIGN-HOST-ACCOUNT-IDS',
            'dataset':dataset,'population':'tiny_development','exposure':'new hosted disk/source-identity boundary',
            'program':program.to_dict(),'sparql':query})
        reference=write_once(root/'reference.json',{'schema_version':'xgap-normalized-row-reference-v1',
            'question_id':'CAMPAIGN-HOST-ACCOUNT-IDS','dataset':dataset,'ordered':False,
            'rows':[{'account_id':str(i)} for i in (1,2,3,4)],
            'normalization':{'schema_version':'xgap-row-normalization-v1','fields':{'account_id':'text'}}})
        session.start();hosts=CampaignMethodHosts(session,
            summary_path='/Users/anthonyche/xgap-data/fedup-summary-tiny-20260913-v2/receipt.json',
            summary_sha256='d42a45b1a8436f80ee431f423bd383465bde4deb7f9a81b7e0ad4a1b118eb02c')
        for method in ('fedup','fedx'):
            endpoint=hosts.start(method)
            trial=run_fixed_trial(request_path=request['path'],request_sha256=request['sha256'],method=method,
                output=root/method,owned_services=hosts.owned_for(method),observer=session.observer,endpoint=endpoint)
            score=score_trial(trial['receipt']['path'],receipt_sha256=trial['receipt']['sha256'],
                reference_path=reference['path'],reference_sha256=reference['sha256'],output=root/(method+'-score.json'))
            r['runs'].append({'method':method,'receipt':trial['receipt'],'status':trial['status'],'success':trial['success'],
                'answer_em':score['answer_em'],'source_requests':trial['source_observations']['requests'],
                'source_failed':trial['source_observations']['failed_requests'],'online_ms':trial['timing']['total_online_ms'],
                'initialization':hosts.initializations[method]})
            if not trial['can_continue_session']:break
        r['success']=len(r['runs'])==2 and all(q['success'] and q['source_failed']==0 for q in r['runs'])
    except Exception as error:r.update(error_type=type(error).__name__,error=str(error))
    finally:
        r['closure']=session.close()
        r['success'] &= r['closure']['owned_processes_terminal'] and r['closure']['observer_stopped']
        pin=write_once(root/'receipt.json',r)
    print(json.dumps({'receipt':pin,**r}));return 0 if r['success'] else 1


if __name__=='__main__':raise SystemExit(main())
