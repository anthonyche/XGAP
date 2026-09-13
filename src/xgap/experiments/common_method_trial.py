"""One common RDF trial, complete outer timing, owned resource boundary, no retry."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedResources
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command
from xgap.experiments.fixed_semantic_worker import REQUEST_SCHEMA


def run_fixed_trial(*, request_path,request_sha256,method,output,owned_services,observer,
                    profile_path=None,profile_sha256=None,endpoint=None,budget=ProcessBudget(),source_rss_bytes=2*1024**3):
    started=time.perf_counter();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    q=json.loads(read_pinned(request_path,request_sha256))
    if q.get('schema_version')!=REQUEST_SCHEMA:raise ValueError('A pinned fixed-semantics request is required')
    r={'schema_version':'xgap-common-method-trial-v1',**{k:q[k] for k in ('question_id','dataset','population','exposure')},
        'method':method,'track':'fixed_semantics','request_sha256':request_sha256,
        'success':False,'status':'preparing','result':None,'can_continue_session':False,
        'model_calls':0,'fit_calls':0,'probe_calls':0,'automatic_retries':0,'paper_result':False}
    monitor=None;guard=None;child=None;observed=None;barrier=None
    phase=method+':'+q['question_id'];repo=Path(__file__).resolve().parents[3]
    try:
        monitor=OwnedResources(owned_services,method_rss_bytes=budget.max_group_rss_bytes,source_rss_bytes=source_rss_bytes)
        if not any(s.role=='source' for s in owned_services) or (method in ('fedup','fedx') and not any(s.role=='method_host' for s in owned_services)):
            raise ValueError('Live source and hosted-method resources must be owned and observed')
        observer.set_phase(phase)
        command=[sys.executable,str(repo/'scripts/run_fixed_semantic_worker.py'),
            '--request-path',str(Path(request_path).resolve()),'--request-sha256',request_sha256,
            '--method',method,'--output',str(root/'worker'),'--seconds',str(min(120,budget.wall_seconds))]
        if method=='xgap-rdf':
            command+=['--profile-path',str(Path(profile_path).resolve()),'--profile-sha256',profile_sha256]
        elif method in ('fedup','fedx'):command+=['--endpoint',endpoint]
        else:raise ValueError('Unknown method')
        elapsed=time.perf_counter()-started
        if elapsed>=budget.wall_seconds:raise TimeoutError('Outer request budget exhausted before worker spawn')
        guard=run_guarded_command(command,cwd=repo,output=root/'guard',budget=replace(budget,wall_seconds=budget.wall_seconds-elapsed),resource_monitor=monitor)
        path=root/'worker/receipt.json'
        if path.exists():
            child=json.loads(read_pinned(path,hashlib.sha256(path.read_bytes()).hexdigest()))
            if (child.get('schema_version')!='xgap-fixed-semantics-worker-v1' or child.get('method')!=method
                    or child.get('request_sha256')!=request_sha256 or child.get('question_id')!=q['question_id']):
                raise ValueError('Worker receipt identity mismatch')
        observed=observer.snapshot(phase)
        r.update(success=bool(guard['success'] and child and child['success'] and observed['failed_requests']==0),
            status=child['status'] if guard['success'] and child else 'guard_'+guard['status'],
            result=child.get('result') if child else None,
            top_level_attempts=child.get('top_level_attempts') if child else None,
            planning_ms=child.get('planning_ms') if child else None,
            execution_ms=child.get('execution_ms') if child else None)
        if observed['failed_requests']:r['status']='observed_source_failure'
        r['decision_e2e_ms']=(time.perf_counter()-started)*1000
    except Exception as error:
        r.update(success=False,status='supervisor_failed',error_type=type(error).__name__,error=str(error))
    finally:
        if not r['success'] and monitor is not None:
            barrier=monitor.stop()
            try:observed=observer.snapshot(phase)
            except Exception as e:barrier.update(observer_settled=False,observer_error=str(e),complete=False)
        r['can_continue_session']=r['success']
        r['quiescence']={'kind':'normal_materialized_return_and_observed_source_drain','complete':True} if r['success'] else barrier or {
            'kind':'unverified','complete':False,'new_serving_session_required':True}
        r['recovery_ms']=(barrier or {}).get('recovery_ms',0)
        r['source_observations']=observed
        r['resources']=monitor.summary() if monitor else None
        r['guard_status']=guard['status'] if guard else None
        r['cost_scope']='full outer entry through durable outcome; recovery explicit; score and final timing telemetry separate'
        r['partial_worker_files']=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((root/'worker').glob('*.json'))]
        seal_started=time.perf_counter();pin=write_once(root/'receipt.json',r)
        complete_ms=(time.perf_counter()-started)*1000
        timing={'receipt':pin,'total_online_ms':complete_ms,'terminal_seal_ms':(time.perf_counter()-seal_started)*1000,
            'decision_e2e_ms':r.get('decision_e2e_ms'),'recovery_ms':r['recovery_ms'],
            'scope':'includes request read, worker preparation/execution/records, observation, recovery and terminal seal; excludes this final measurement file and evaluation'}
        write_once(root/'timing.json',timing)
    return {**r,'receipt':pin,'timing':timing}
