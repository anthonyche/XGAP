"""Actual ARUQULA->FedX services and trial adapter for a shared RDF campaign.

No private intent, reference answer or XGAP candidate is accepted by this API.
Public labels must already be included in the frozen common source snapshot.
The baseline's original exploratory calls and recovered errors are preserved.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.request import Request, urlopen, getproxies, proxy_bypass
from urllib.parse import urlsplit

from run_external_federation_tiny import Processes, ready
from check_chapter7_aruqula_fedup import observed_model_usage
from xgap.experiments.campaign_source_observer import CampaignSourceObserver, SourceObservationBudget
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.m15_native_services import LoopbackPortReservations
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedProcess, OwnedResources
from xgap.experiments.process_guard import run_guarded_command, ProcessBudget, _stop_group, _group_sample

REPO=Path(__file__).resolve().parents[1]
METHOD='aruqula-fedx'
COMPATIBILITY='https-iris-action-schema-fedx-v2'
HARNESS_BUDGET_CATEGORIES=frozenset(('harness_call_budget','harness_request_budget','harness_response_budget'))


def load(pin):return json.loads(read_pinned(pin['path'],pin['sha256']))


def verified_budget_censoring(result):
    """A known observer limit with complete evidence, never an integrity error.

    This permits closing a censored trial and advancing to another request. It
    does not permit reusing its source session or repeating the censored trial.
    The batch separately verifies shutdown of every owned service.
    """
    observed=result.get('observations') or {}
    if (set(observed)!={'source','model','lookup','federation'} or
            result.get('model_usage_complete') is not True or result.get('guard_status')!='completed' or
            (result.get('quiescence') or {}).get('complete') is not True or
            result.get('error_type') or result.get('observation_error_type')):
        return False
    categories={}
    for summary in observed.values():
        if (not summary.get('phase_seal') or summary.get('persistence_failures')!=0 or
                summary.get('late_calls')!=0):return False
        for category,count in summary.get('failure_categories',{}).items():
            # A recorded HTTP response can be an original method/backend error.
            # Transport faults and any unknown category require investigation.
            if category not in HARNESS_BUDGET_CATEGORIES|{'upstream_http_failure'}:return False
            if type(count) is not int or count<=0:return False
            if category.startswith('harness_'):
                categories[category]=categories.get(category,0)+count
    return bool(categories)


def verify_config(config,profile):
    if config.get('schema_version')!='xgap-ch6-external-runtime-v1':raise ValueError('Unknown TS runtime')
    if config.get('compatibility')!=COMPATIBILITY:raise ValueError('Unadmitted TS compatibility')
    # This is a data identity requirement, not a claim that labels improve answers.
    if profile['offline'].get('shared_public_metadata')!=config['metadata']:
        raise ValueError('TS metadata must be part of the shared frozen deployment')
    for name in ('java','python','python_environment','redis','classpath','lookup_jar','metadata','lookup_config','index_config'):
        if file_pin(config[name]['path'])!=config[name]:raise ValueError('Runtime artifact changed: '+name)
    if file_pin(config['python_command'])!=config['python']:
        raise ValueError('Virtual-environment interpreter no longer resolves to the pinned executable')
    if (Path(config['python_command']).parent.parent/'pyvenv.cfg').resolve()!=Path(config['python_environment']['path']).resolve():
        raise ValueError('Python invocation must retain its pinned virtual environment')
    for name in ('author_source','lookup_source'):
        pin=config[name];root=Path(pin['path'])
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
        if head!=pin['commit'] or subprocess.check_output(['git','diff','HEAD','--'],cwd=root):
            raise ValueError('Pinned author repository changed: '+name)
    build=load(config['fedx_build'])
    if not build.get('external_entries_byte_identical') or file_pin(build['jar']['path'])!=build['jar']:
        raise ValueError('FedX engine identity changed')
    return build


class ExternalSession:
    def __init__(self,*,root,config_pin,source_session):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=False)
        self.config_pin=config_pin;self.config=load(config_pin);self.source_session=source_session
        self.processes=Processes(self.root);self.observers={};self.owned=[];self.ports=None

    def start(self):
        at=time.perf_counter();cfg=self.config
        try:
            profile=load(self.source_session.profile);build=verify_config(cfg,profile)
            with socket.socket() as check:check.bind(('127.0.0.1',6379))
            redis=self.processes.start('redis',[cfg['redis']['path'],'--bind','127.0.0.1','--port','6379',
                '--save','','--appendonly','no','--dir',str(self.root)])
            self.owned.append(OwnedProcess('redis','method_host',redis));ready(redis,6379)
            self.ports=LoopbackPortReservations.acquire(2)
            endpoints=[]
            for source in sorted(profile['backends']):
                client=profile['backends'][source]['client']
                # Frozen profiles name datasets explicitly. No external endpoint bypass.
                if client.get('url')!=self.source_session.observer.base_url:
                    raise ValueError('All TS sources must use the common source observer')
                endpoints.append(client['url']+'/'+client['database']+'/sparql')
            port=self.ports.ports[0];self.ports.release(0)
            fedx=self.processes.start('fedx',[cfg['java']['path'],'-Xms64m','-Xmx512m','-jar',
                build['jar']['path'],str(port),str(cfg['query_seconds']),*endpoints])
            self.owned.append(OwnedProcess('fedx','method_host',fedx));ready(fedx,port)
            budget=SourceObservationBudget(**cfg['auxiliary_budget'])
            self.observers['federation']=CampaignSourceObserver({'/sparql':f'http://127.0.0.1:{port}/sparql'},
                self.root/'federation-observations',budget=budget)
            metadata=self.root/'public-metadata';metadata.mkdir()
            shutil.copyfile(cfg['metadata']['path'],metadata/'metadata.nt')
            config=load(cfg['lookup_config']);config['indexPath']=str(self.root/'lookup-index')
            index=load(cfg['index_config']);index['dataPath']=str(metadata)
            cp=write_once(self.root/'lookup-config.json',config);ip=write_once(self.root/'index-config.json',index)
            port=self.ports.ports[1];self.ports.release(1)
            lookup=self.processes.start('lookup',[cfg['java']['path'],'-Xms64m','-Xmx512m','-cp',
                cfg['lookup_jar']['path']+':'+Path(cfg['classpath']['path']).read_text().strip(),
                'org.dbpedia.lookup.Main','--config',cp['path'],'--port',str(port)],cwd=self.root)
            self.owned.append(OwnedProcess('lookup','method_host',lookup));ready(lookup,port)
            boundary='xgap-official-index-config'
            body=(f'--{boundary}\r\nContent-Disposition: form-data; name="config"; filename="index.json"\r\n'
                'Content-Type: application/json\r\n\r\n').encode()+Path(ip['path']).read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
            with urlopen(Request(f'http://127.0.0.1:{port}/api/index/run',data=body,
                headers={'Content-Type':'multipart/form-data; boundary='+boundary}),timeout=60) as response:
                if response.status!=200:raise ValueError('Lookup index failed')
            self.observers['lookup']=CampaignSourceObserver({'/api/search':f'http://127.0.0.1:{port}/api/search'},
                self.root/'lookup-observations',budget=budget)
            model=cfg['model_endpoint'].rstrip('/')
            proxy=None if proxy_bypass(urlsplit(model).hostname) else getproxies().get('http')
            self.observers['model']=CampaignSourceObserver({'/v1/chat/completions':model+'/chat/completions'},
                self.root/'model-observations',budget=SourceObservationBudget(**cfg['model_budget']),
                upstream_http_proxy=proxy,downstream_keepalive=False)
            self.ready=write_once(self.root/'ready.json',dict(runtime=self.config_pin,profile=self.source_session.profile,
                endpoints=endpoints,offline_setup_ms=(time.perf_counter()-at)*1000,
                query_aware_changes=0,algorithm_changes=0,compatibility=COMPATIBILITY))
            return self
        except BaseException:
            self.close();raise

    def close(self):
        rows=[]
        for name,process in reversed(self.processes.owned):
            cleanup=_stop_group(process,ProcessBudget())
            if cleanup['complete'] and process.poll() is None:
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:pass
            rows.append(dict(name=name,pid=process.pid,cleanup=cleanup,returncode=process.poll()))
        drained=all(r['cleanup']['complete'] and not _group_sample(r['pid']) for r in rows)
        if drained:
            for observer in self.observers.values():observer.close()
        for log in self.processes.logs:log.close()
        if self.ports:self.ports.close()
        result=dict(processes=rows,owned_groups_drained=drained,
            owned_processes_terminal=all(r['returncode'] is not None for r in rows),
            observer_stopped=all(not o.thread.is_alive() and not o.inflight for o in self.observers.values()))
        if not (self.root/'closed.json').exists():write_once(self.root/'closed.json',result)
        return result


def run_trial(*,request,output,session,budget,source_rss_bytes,package_monitor=None):
    """Accept only public question pin and owned services; never evaluator inputs."""
    started=time.perf_counter();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    q=load(request);cfg=session.config;source=session.source_session
    if q.get('schema_version')!='xgap-one-shot-evaluation-request-v1':raise ValueError('Public NL request required')
    phase='aruqula:'+q['question_id'];observers={'source':source.observer,**session.observers}
    result=dict(schema_version='xgap-common-method-trial-v1',method=METHOD,track='natural_language_external_composition',
        **{k:q[k] for k in ('question_id','population','exposure')},dataset=load(source.profile)['dataset'],
        request_sha256=request['sha256'],success=False,status='setup_error',result=None,automatic_retries=0,
        baseline_algorithm_changes=0,compatibility=COMPATIBILITY,private_intent_available=False,
        controlled_state_available=False,model_calls=None,input_tokens=None,output_tokens=None,planning_ms=None,
        clarification_calls=0,clarification_support='original author API has no authoritative clarification action',
        final_plan_executions=None,can_continue_session=False)
    monitor=OwnedResources([*source.owned,*session.owned],method_rss_bytes=budget.max_group_rss_bytes,
        source_rss_bytes=source_rss_bytes,extra_monitor=package_monitor)
    opened=[];guard=None;barrier=None
    try:
        for name,observer in observers.items():observer.set_phase(phase);opened.append(name)
        if not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):raise ValueError('Model credential missing')
        # The original worker's stricter two-key input boundary is retained.
        public=write_once(root/'public-question.json',{k:q[k] for k in ('question_id','question')})
        command=[cfg['python_command'],str(REPO/'scripts/run_chapter7_aruqula_worker.py'),
            '--method-id',METHOD,'--compatibility',COMPATIBILITY,'--author-source',cfg['author_source']['path'],
            '--request-path',public['path'],'--request-sha256',public['sha256'],
            '--model-endpoint',observers['model'].base_url+'/v1','--model-id',cfg['model_id'],
            '--federation-endpoint',observers['federation'].base_url+'/sparql',
            '--lookup-endpoint',observers['lookup'].base_url+'/api/search','--query-seconds',str(cfg['query_seconds']),
            '--output',str(root/'worker')]
        guard=run_guarded_command(command,cwd=REPO,output=root/'guard',budget=budget,resource_monitor=monitor)
        result['guard_status']=guard['status']
        path=root/'worker/receipt.json'
        if path.exists():
            pin=file_pin(path);child=load(pin)
            if (child.get('schema_version')!='xgap-ch7-aruqula-worker-v1' or child.get('request_sha256')!=public['sha256']
                    or child.get('method')!=METHOD or child.get('question_id')!=q['question_id']):
                raise ValueError('External worker identity differs')
            result.update(worker=pin,success=bool(guard['success'] and child['success']),status=child['status'],
                final_plan_executions=child.get('final_query_submissions'),worker_ms=child.get('worker_ms'))
            if result['success']:
                result['result']=write_once(root/'result.json',dict(answer_format='sparql_json',answer=load(child['answer'])))
        else:result['status']='guard_'+guard['status']
    except Exception as error:result.update(success=False,status='supervisor_failed',error_type=type(error).__name__)
    finally:
        if not result['success']:barrier=monitor.stop()
        observed={};harness={}
        try:
            for name in opened:observed[name]=observers[name].seal_phase(phase)
            usage=observed_model_usage(observers['model'])
            result.update(model_calls=usage['model_network_calls'],input_tokens=usage['input_tokens'],
                          output_tokens=usage['output_tokens'],model_usage_complete=usage['usage_complete'])
            harness={name:summary.get('failure_categories',{}) for name,summary in observed.items()
                     if any(k.startswith('harness_') for k in summary.get('failure_categories',{}))}
            if harness:
                result.update(success=False,status='harness_observation_failure',harness_failures=harness,
                              failure_scope='observation_integrity_failure_not_method_incorrectness')
                if barrier is None:barrier=monitor.stop()
        except Exception as error:
            result.update(success=False,status='harness_observation_failure',observation_error_type=type(error).__name__)
            if barrier is None:barrier=monitor.stop()
        # Original author exploration may recover from HTTP errors. Count them,
        # but do not override a materialized final answer merely for that reason.
        result.update(observations=observed,source_observations=observed.get('source'),resources=monitor.summary(),
            can_continue_session=result['success'],quiescence=barrier or dict(complete=True,kind='materialized_return'),
            decision_e2e_ms=(time.perf_counter()-started)*1000,paper_result=False)
        if harness and verified_budget_censoring(result):
            result.update(status='harness_budget_censored',
                          failure_scope='study_budget_censoring_not_method_incorrectness')
        if (guard and guard['status'].startswith('study_') and
                result['status'] not in ('harness_observation_failure','supervisor_failed')):
            result.update(status=guard['status'],success=False,can_continue_session=False,
                          failure_scope='study_budget_censoring_not_method_incorrectness')
        pin=write_once(root/'receipt.json',result)
        released=True
        for name in opened:
            try:observers[name].release_phase(phase,pin)
            except Exception:released=False
        timing=dict(receipt=pin,total_online_ms=(time.perf_counter()-started)*1000,
            scope='public request through materialized outcome, observation and seal; excludes offline service/index setup and scoring')
        write_once(root/'timing.json',timing)
        write_once(root/'session-finalization.json',dict(receipt=pin,records_released=released,
                   can_continue_session=released and result['success']))
    return {**result,'receipt':pin,'timing':timing,'can_continue_session':released and result['success']}
