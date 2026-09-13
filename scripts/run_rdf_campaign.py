#!/usr/bin/env python3
"""Run a bounded chunk of an immutable RDF evaluation schedule, without retries."""
import argparse
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

from campaign_method_hosts import CampaignMethodHosts
from rdf_tdb_session import RdfTdbSession
from xgap.experiments.campaign_budget import CampaignBudget
from xgap.experiments.campaign_schedule import dispatch_one_group
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_fixed_trial, run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.external_federation import deadline
from xgap.experiments.fixed_semantic_worker import REQUEST_SCHEMA
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget

REPO=Path(__file__).resolve().parents[1]


def bind_campaign_identity(root,identity,epoch_reason=None):
    """Append an explicit harness epoch without rewriting inputs or old outcomes."""
    anchor=root/'campaign.json';epochs=root/'harness-epochs'
    if not anchor.exists():return write_once(anchor,identity)
    previous_path=sorted(epochs.glob('*.json'))[-1] if epochs.exists() and list(epochs.glob('*.json')) else anchor
    raw=previous_path.read_bytes();previous=json.loads(raw);old=previous.get('identity',previous)
    if old==identity:return {'path':str(previous_path),'sha256':hashlib.sha256(raw).hexdigest()}
    if ({k:v for k,v in old.items() if k!='implementation_sha256'}!=
            {k:v for k,v in identity.items() if k!='implementation_sha256'}):raise ValueError('Cannot change frozen evaluation inputs')
    if not epoch_reason:raise ValueError('Implementation changed: a documented harness epoch is required')
    epochs.mkdir(exist_ok=True)
    return write_once(epochs/f'epoch-{len(list(epochs.glob("*.json")))+1:04}.json',{'identity':identity,
        'previous':{'path':str(previous_path),'sha256':hashlib.sha256(raw).hexdigest()},'reason':epoch_reason,
        'prior_intents_retained_and_never_redispatched':True,'cross_epoch_times_not_pooled_without_disclosure':True})


class Controller:
    def __init__(self,root,run_root,schedule,prepared,summary,budget):
        self.root=root;self.run_root=run_root;self.schedule=schedule;self.prepared=prepared;self.summary=summary;self.budget=budget
        self.session=None;self.hosts=None;self.sessions=0;self.current_request=None;self.events=[];self.halted=None

    def close_session(self,cause):
        if self.session is None:return 0
        at=time.perf_counter();session=self.session
        # Detach before cleanup: an exception must never leave dead sources ready.
        self.session=None;self.hosts=None
        try:closure=session.close()
        except Exception as error:
            closure={'owned_groups_drained':False,'error_type':type(error).__name__,'error':str(error),
                'traceback':traceback.format_exc()};self.halted='retirement_failed'
        elapsed=(time.perf_counter()-at)*1000
        event={'kind':'serving_session_retired','cause':cause,'session':str(session.root),'closure':closure,'elapsed_ms':elapsed}
        self.events.append(event)
        try:write_once(session.root/'retirement.json',event)
        except Exception as error:self.halted='retirement_record_failed';event['persistence_error']=str(error)
        if not closure['owned_groups_drained']:self.halted=self.halted or 'owned_groups_not_drained'
        return elapsed

    def request_for(self,cell):
        raw=json.loads(read_pinned(cell['request']['path'],cell['request']['sha256']))
        if raw['question_id']!=cell['question_id']:raise ValueError('Question identity mismatch')
        if cell['track']=='natural_language':return cell['request']
        gold=cell['fixed_semantics_input'];g=json.loads(read_pinned(gold['path'],gold['sha256']))
        fixed={'schema_version':REQUEST_SCHEMA,**{k:raw[k] for k in ('question_id','population','exposure')},
            'dataset':self.schedule['dataset'],'program':g['program'],'sparql':g['reference_sparql']}
        path=self.root/'fixed-requests'/(cell['question_id']+'.json');path.parent.mkdir(exist_ok=True)
        if path.exists():
            data=path.read_bytes()
            if json.loads(data)!=fixed:raise ValueError('Fixed request changed between methods')
            return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}
        return write_once(path,fixed)

    def ready(self,cell):
        ready=self.budget.readiness()
        if self.halted:return {'ready':False,'reason':self.halted}
        if not ready['ready']:return ready
        at=time.perf_counter()
        try:
            self.current_request=self.request_for(cell)
            if self.session is None:
                self.sessions+=1
                self.session=RdfTdbSession(root=self.run_root/f'session-{self.sessions:03}',
                    prepared_path=self.prepared['path'],prepared_sha256=self.prepared['sha256'],
                    budget=SourceObservationBudget(**self.schedule['source_budget']),discard_serving_copies=True)
                with deadline(120):self.session.start()
                self.hosts=CampaignMethodHosts(self.session,summary_path=self.summary['path'],summary_sha256=self.summary['sha256'])
            if cell['method'] in ('fedup','fedx'):self.hosts.start(cell['method'])
            if not self.budget.readiness()['ready']:raise ValueError('Package budget exhausted during initialization')
            return {'ready':True,'session_ready':self.session.ready_pin,'source_session':str(self.session.root),
                'method_initialization':self.hosts.initializations.get(cell['method']),
                'initial_preparation_ms':(time.perf_counter()-at)*1000,'request':self.current_request,
                'preparation_scope':'source/host startup and shared fixed-input preparation; outside current method query cost'}
        except Exception as error:
            self.halted='preparation_failed'
            failure={'kind':'preparation_failed','cell_id':cell['cell_id'],'error_type':type(error).__name__,
                'error':str(error),'elapsed_ms':(time.perf_counter()-at)*1000,'query_attempted':False}
            self.events.append(failure);self.close_session(cell['cell_id']+':preparation-failed')
            return {'ready':False,**failure}

    def execute(self,cell,output):
        self.budget.admit();method=cell['method'];request=self.current_request
        runner=run_nl_trial if cell['track']=='natural_language' else run_fixed_trial
        try:
            result=runner(request_path=request['path'],request_sha256=request['sha256'],method=method,output=output,
                owned_services=self.hosts.owned_for(method),observer=self.session.observer,
                profile_path=self.session.profile['path'],profile_sha256=self.session.profile['sha256'],
                endpoint=self.hosts.endpoints.get(method),budget=ProcessBudget(),package_monitor=self.budget)
            post_close_ms=0 if result['can_continue_session'] else self.close_session(cell['cell_id']+':failed-outcome')
            write_once(output/'controller-timing.json',{'receipt':result['receipt'],
                'common_online_ms':result['timing']['total_online_ms'],'post_outcome_retirement_ms':post_close_ms,
                'online_through_retirement_ms':result['timing']['total_online_ms']+post_close_ms,
                'scope':'common complete online boundary plus required extra idle-host/copy retirement; startup and scoring separate'})
            reference=cell['reference_for_post_seal_scoring_only']
            try:
                score_trial(result['receipt']['path'],receipt_sha256=result['receipt']['sha256'],
                    reference_path=reference['path'],reference_sha256=reference['sha256'],output=output/'score.json')
            except Exception as error:
                write_once(output/'score-error.json',{'error_type':type(error).__name__,'error':str(error),'receipt':result['receipt']})
            return result['receipt']
        except BaseException:
            self.close_session(cell['cell_id']+':dispatch-exception');raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('schedule','schedule-sha256','prepared','prepared-sha256','summary','summary-sha256','output'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--max-groups',type=int,default=1,choices=range(1,5));p.add_argument('--read-key',action='store_true')
    p.add_argument('--harness-epoch-reason',help='Explicit append-only correction epoch; never rerun old cell intents')
    args=p.parse_args();root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    with (root/'active.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before campaign execution')
        tree=subprocess.check_output(['git','ls-tree','-r','HEAD','src','scripts','prompts','experiments/environments'],cwd=REPO)
        schedule=json.loads(read_pinned(args.schedule,args.schedule_sha256))
        if schedule['schema_version']!='xgap-balanced-campaign-schedule-v1':raise ValueError('Unknown schedule')
        prepared={'path':str(Path(args.prepared).resolve()),'sha256':args.prepared_sha256}
        summary={'path':str(Path(args.summary).resolve()),'sha256':args.summary_sha256}
        for pin in (prepared,summary):
            d=json.loads(read_pinned(pin['path'],pin['sha256']))
            if not d['success'] or d['profile']!=schedule['profile']:raise ValueError('Preparation/profile mismatch')
        identity={'schedule':{'path':str(Path(args.schedule).resolve()),'sha256':args.schedule_sha256},
            'prepared':prepared,'summary':summary,'implementation_sha256':hashlib.sha256(tree).hexdigest()}
        epoch=bind_campaign_identity(root,identity,args.harness_epoch_reason)
        runs=root/'runs';runs.mkdir(exist_ok=True);run_root=runs/f'run-{len(list(runs.iterdir())):04}';run_root.mkdir(exist_ok=False)
        budget=CampaignBudget(root,maximum_cells=args.max_groups*len(schedule['methods']))
        ctl=Controller(root,run_root,schedule,prepared,summary,budget);previous=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY')
        report={'schema_version':'xgap-rdf-campaign-chunk-v1','campaign':identity,'harness_epoch':epoch,'dispatches':[],
            'maximum_groups':args.max_groups,'maximum_model_calls':budget.maximum_cells if schedule['track']=='natural_language' else 0,
            'model_output_tokens_per_call_maximum':6144,'automatic_retries':0,
            'formal_campaign_dispatched':False,'excludes_native_finbench_and_remaining_tracks':True}
        try:
            if schedule['track']=='natural_language':
                key=getpass.getpass('LLM credential (not recorded): ') if args.read_key else previous
                if not key:raise ValueError('Model credential missing before dispatch')
                os.environ['XGAP_EXTERNAL_LLM_API_KEY']=key;key=None
            write_once(run_root/'budget.json',{'campaign':identity,'package':budget.summary(),
                'maximum_groups':args.max_groups,'maximum_model_calls':report['maximum_model_calls'],
                'model_output_tokens_per_call_maximum':6144,'warmup_queries':0,'discard_only_new_reconstructable_serving_copies':True})
            for _ in range(args.max_groups):
                rows=dispatch_one_group(schedule_path=args.schedule,schedule_sha256=args.schedule_sha256,
                    ledger=root/'cells',execute=ctl.execute,ready=ctl.ready)
                new=[r for r in rows if r['status'] not in ('already_sealed','indeterminate_prior_intent')]
                report['dispatches'].extend(new)
                if not new or any(r['status']=='unrun_prerequisite' for r in new):break
            report['formal_campaign_dispatched']=any(r['status']=='outcome_sealed' for r in report['dispatches'])
        except Exception as error:report.update(error_type=type(error).__name__,error=str(error))
        finally:
            ctl.close_session('chunk-complete');report.update(events=ctl.events,budget=budget.summary())
            if previous is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
            else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=previous
            pin=write_once(run_root/'receipt.json',report)
        print(json.dumps({'receipt':pin,'outcomes':report['dispatches'],'error':report.get('error'),'halted':ctl.halted}))
        return 1 if report.get('error') or ctl.halted else 0


if __name__=='__main__':raise SystemExit(main())
