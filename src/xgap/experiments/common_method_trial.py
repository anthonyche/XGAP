"""One common native/RDF trial, complete timing, owned resources, no retry."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

from xgap.experiments.one_shot_profile import read_pinned, REQUEST_SCHEMA as NL_SCHEMA
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.owned_resources import OwnedResources
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command
from xgap.experiments.fixed_semantic_worker import REQUEST_SCHEMA
from xgap.experiments.source_failure_classification import classify_source_failure
from xgap.experiments.practical_methods import PRACTICAL_METHODS, external_engine
from xgap.agent.nl_strong_question import NL_STRONG_METHODS, NL_USER_METHODS, NL_FAMILY_METHODS
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.bounded_joint_contract import METHODS as HISTORICAL_JOINT_METHODS, TRACK as JOINT_TRACK, METRICS as JOINT_METRICS, CONTROLLED_TRACK
from xgap.experiments import unified_contract as unified_run
from xgap.experiments.ch6_direct import METHOD as DIRECT_METHOD, TRACK as DIRECT_TRACK
JOINT_METHODS=(*HISTORICAL_JOINT_METHODS,*unified_run.METHODS)


def _idle_source_reusable(result, child, guard, observed, *, sealed=False):
    """A terminal semantic rejection cannot taint a source it never contacted.

    This is intentionally narrower than arbitrary method failure. All worker
    descendants must be drained, the observed phase must be empty and healthy,
    and the caller still checks owned services and releases the sealed phase.
    """
    return bool(child and guard and observed and
        result.get('method') in unified_run.METHODS and
        result.get('status') in ('proposal_failed','intent_outside_proposed_scope') and
        child.get('status')==result['status'] and not result.get('success') and
        guard.get('success') is True and guard.get('status')=='completed' and
        (guard.get('cleanup') or {}).get('complete') is True and
        child.get('backend_calls')==0 and child.get('final_plan_executions')==0 and
        all(observed.get(k)==0 for k in ('requests','forwarded_requests','failed_requests',
                                         'late_calls','persistence_failures')) and
        observed.get('failure_categories')=={} and (not sealed or observed.get('phase_seal')))


def _run_trial(*, track,request_path,request_sha256,method,output,owned_services,observer,
               profile_path=None,profile_sha256=None,endpoint=None,budget=ProcessBudget(),source_rss_bytes=2*1024**3,
               package_monitor=None,oracle_path=None,oracle_sha256=None,user_max_calls=9,
               intent_family_path=None,intent_family_sha256=None,scope_path=None,scope_sha256=None,
               joint_config_path=None,joint_config_sha256=None,controlled_state_path=None,controlled_state_sha256=None):
    started=time.perf_counter();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    q=json.loads(read_pinned(request_path,request_sha256))
    practical=track=='trusted_template';nl=track in ('natural_language','trusted_template')
    if practical:
        from xgap.experiments.practical_profile import REQUEST_SCHEMA as PRACTICAL_SCHEMA
    schema=PRACTICAL_SCHEMA if practical else NL_SCHEMA if nl else REQUEST_SCHEMA
    if q.get('schema_version')!=schema:raise ValueError('A pinned request with the declared track is required')
    if practical!=(method in PRACTICAL_METHODS):raise ValueError('Practical methods require their explicit trusted-template track')
    hosted=external_engine(method) is not None
    dataset=json.loads(read_pinned(profile_path,profile_sha256))['dataset'] if nl else q['dataset']
    r={'schema_version':'xgap-common-method-trial-v1',**{k:q[k] for k in ('question_id','population','exposure')},
        'method':method,'track':track,'dataset':dataset,'request_sha256':request_sha256,
        'success':False,'status':'preparing','result':None,'can_continue_session':False,
        'model_calls':None if nl else 0,'fit_calls':0,'probe_calls':0,'automatic_retries':0,'paper_result':False}
    if practical:r['input_scope']='pinned trusted template and declared binding authority; not unaided open-domain NL'
    monitor=None;guard=None;child=None;observed=None;barrier=None;idle_reuse=False
    campaign_observer=callable(getattr(observer,'seal_phase',None));phase_opened=False
    phase=method+':'+q['question_id'];repo=Path(__file__).resolve().parents[3]
    try:
        monitor=OwnedResources(owned_services,method_rss_bytes=budget.max_group_rss_bytes,source_rss_bytes=source_rss_bytes,
            extra_monitor=package_monitor)
        if not any(s.role=='source' for s in owned_services) or (hosted and not any(s.role=='method_host' for s in owned_services)):
            raise ValueError('Live source and hosted-method resources must be owned and observed')
        observer.set_phase(phase)
        phase_opened=True
        command=[sys.executable,str(repo/('scripts/run_nl_method_worker.py' if nl else 'scripts/run_fixed_semantic_worker.py')),
            '--request-path',str(Path(request_path).resolve()),'--request-sha256',request_sha256,
            '--method',method,'--output',str(root/'worker'),'--seconds',str(budget.wall_seconds if nl else min(120,budget.wall_seconds))]
        if nl:
            from xgap.experiments.nl_method_worker import METHODS
            if method not in METHODS:raise ValueError('Unknown NL method')
            command+=['--profile-path',str(Path(profile_path).resolve()),'--profile-sha256',profile_sha256]
            joint_args=(scope_path,scope_sha256,joint_config_path,joint_config_sha256)
            if method not in JOINT_METHODS and (controlled_state_path or controlled_state_sha256):
                raise ValueError('Controlled state requires a current method')
            if method not in (*JOINT_METHODS,DIRECT_METHOD) and any(v is not None for v in joint_args):
                raise ValueError('Current scope/configuration requires a current method')
            if method not in NL_FAMILY_METHODS and (intent_family_path is not None or intent_family_sha256 is not None):
                raise ValueError('Finite-family input cannot be attached to another method')
            if method == DIRECT_METHOD:
                if (not joint_config_path or not joint_config_sha256 or scope_path or scope_sha256
                        or oracle_path or oracle_sha256 or endpoint is not None):
                    raise ValueError('Direct worker must not receive scope or private user artifacts')
                r.update(track=DIRECT_TRACK,joint_config_sha256=joint_config_sha256)
                command+=['--joint-config-path',str(Path(joint_config_path).resolve()),'--joint-config-sha256',joint_config_sha256]
            elif method in JOINT_METHODS:
                if not all(joint_args) or not oracle_path or not oracle_sha256 or endpoint is not None or user_max_calls!=9:
                    raise ValueError('Current method requires pinned scope/configuration/private user')
                r.update(track=unified_run.TRACK if method in unified_run.METHODS else JOINT_TRACK,scope_sha256=scope_sha256,joint_config_sha256=joint_config_sha256,
                    oracle_sha256=oracle_sha256)
                if controlled_state_path or controlled_state_sha256:
                    if not controlled_state_path or not controlled_state_sha256:raise ValueError('Pinned controlled state required')
                    r.update(track=unified_run.CONTROLLED_TRACK if method in unified_run.METHODS else CONTROLLED_TRACK,controlled_state_sha256=controlled_state_sha256)
                    command+=['--controlled-state-path',str(Path(controlled_state_path).resolve()),
                        '--controlled-state-sha256',controlled_state_sha256]
                for name,path,digest in (('scope',scope_path,scope_sha256),('joint-config',joint_config_path,joint_config_sha256),
                                         ('oracle',oracle_path,oracle_sha256)):
                    command+=['--'+name+'-path',str(Path(path).resolve()),'--'+name+'-sha256',digest]
            elif method in (*NL_USER_METHODS,*NL_FAMILY_METHODS):
                if oracle_path is None or oracle_sha256 is None:
                    raise ValueError('User interaction requires a separately pinned private oracle')
                r.update(track='natural_language_interaction',oracle_sha256=oracle_sha256)
                command+=['--oracle-path',str(Path(oracle_path).resolve()),'--oracle-sha256',oracle_sha256,
                    '--user-max-calls',str(user_max_calls)]
                if method in NL_FAMILY_METHODS:
                    if intent_family_path is None or intent_family_sha256 is None:
                        raise ValueError('Finite-family method needs a pinned public contract')
                    r.update(track='natural_language_finite_family',intent_family_sha256=intent_family_sha256)
                    command+=['--intent-family-path',str(Path(intent_family_path).resolve()),
                        '--intent-family-sha256',intent_family_sha256]
            elif oracle_path is not None or oracle_sha256 is not None:
                raise ValueError('Oracle cannot be attached to a non-interaction method')
            if hosted:command+=['--endpoint',endpoint]
        elif method in ('xgap-rdf','xgap-native'):
            command+=['--profile-path',str(Path(profile_path).resolve()),'--profile-sha256',profile_sha256]
        elif method in ('fedup','fedx'):command+=['--endpoint',endpoint]
        else:raise ValueError('Unknown method')
        elapsed=time.perf_counter()-started
        if elapsed>=budget.wall_seconds:raise TimeoutError('Outer request budget exhausted before worker spawn')
        guard=run_guarded_command(command,cwd=repo,output=root/'guard',budget=replace(budget,wall_seconds=budget.wall_seconds-elapsed),resource_monitor=monitor)
        path=root/'worker/receipt.json'
        if path.exists():
            child=json.loads(read_pinned(path,hashlib.sha256(path.read_bytes()).hexdigest()))
            if (child.get('schema_version')!=('xgap-nl-method-worker-v1' if nl else 'xgap-fixed-semantics-worker-v1') or child.get('method')!=method
                    or child.get('request_sha256')!=request_sha256 or child.get('question_id')!=q['question_id']):
                raise ValueError('Worker receipt identity mismatch')
            if nl and (child.get('profile_sha256')!=profile_sha256 or child.get('dataset') not in (None,dataset)):
                raise ValueError('NL worker profile or dataset identity mismatch')
            expected_kind='configured_external' if hosted else 'configured_native'
            if practical and (child.get('track')!=track or child.get('execution_kind') not in (None,expected_kind)
                              or (child.get('success') and child.get('execution_kind')!=expected_kind)):
                raise ValueError('Strong worker scope differs or replay was substituted for live execution')
            if method in NL_USER_METHODS and (child.get('track')!='natural_language_interaction'
                    or child.get('oracle_sha256')!=oracle_sha256):
                raise ValueError('Simulated-user worker track or private artifact identity differs')
            if method in NL_FAMILY_METHODS and (child.get('track')!='natural_language_finite_family'
                    or child.get('oracle_sha256')!=oracle_sha256 or child.get('intent_family_sha256')!=intent_family_sha256):
                raise ValueError('Finite-family worker track or artifact identity differs')
            if method in JOINT_METHODS and (child.get('track')!=r['track'] or
                    any(child.get(k)!=r[k] for k in ('scope_sha256','joint_config_sha256','oracle_sha256')) or
                    child.get('controlled_state_sha256')!=controlled_state_sha256):
                raise ValueError('Current worker track or artifact identity differs')
            if method == DIRECT_METHOD and (child.get('track') != DIRECT_TRACK
                    or child.get('joint_config_sha256') != joint_config_sha256
                    or child.get('oracle_available_to_worker') is not False):
                raise ValueError('Direct worker identity or private input boundary differs')
        observed=observer.snapshot(phase)
        r.update(success=bool(guard['success'] and child and child['success'] and observed['failed_requests']==0),
            status=child['status'] if guard['success'] and child else 'guard_'+guard['status'],
            result=child.get('result') if child else None,
            top_level_attempts=child.get('top_level_attempts') if child else None,
            planning_ms=child.get('planning_ms') if child else None,
            execution_ms=child.get('execution_ms') if child else None)
        if observed['failed_requests']:
            r['source_failure']=classify_source_failure(observed)
            r['status']=r['source_failure']['status']
        if nl:
            for key in ('model_calls','input_tokens','output_tokens','frontend_ms','interpretation_ms','grounding_ms','compilation_ms'):
                r[key]=child.get(key) if child else None
        if practical or method in (*NL_STRONG_METHODS,*NL_USER_METHODS,*NL_FAMILY_METHODS):
            for key in ('admission_ms','acquisition_ms','clarification_calls','strong_plan','semantic_validation',
                        'unvalidated_bindings','semantic_discrepancy_upper_bound','discrepancy_status','core_result',
                        'external_engine','information_strategy','input_scope','structure_validation','strong_scope',
                        'user_intent_verified','planning_cpu_ms','oracle_processing_ms','oracle_lowering_ms',
                        'declared_user_wait_ms','acquisition_policy_scope','user_observations',
                        'disclosed_coordinates','oracle_reply_bytes','certificate_ms','certificate_checks',
                        'physical_prepare_attempts','physical_plan_cache_hits','terminal_certificate','root_gap','search'):
                r[key]=child.get(key) if child else None
        if method in (*JOINT_METHODS,DIRECT_METHOD):
            for key in (*JOINT_METRICS,'core','search','user_observations','final_plan_executions',
                        'backend_calls','proposal_kind','epsilon','error','error_type','proposal_failure_category',
                        'interpretation_diagnostics','provider_adapter','scope_policy_adapter','execution_cost_feedback',
                        'controlled_processing_ms','initial_state',*unified_run.METRICS,'algorithm_profile','terminal_settings'):
                r['method_cost_scope' if key=='cost_scope' else key]=child.get(key) if child else None
        r['decision_e2e_ms']=(time.perf_counter()-started)*1000
    except Exception as error:
        r.update(success=False,status='supervisor_failed',error_type=type(error).__name__,error=str(error))
    finally:
        if campaign_observer and phase_opened and monitor is not None:
            idle_reuse=_idle_source_reusable(r,child,guard,observed)
            if idle_reuse:
                try:idle_reuse=monitor.sample([]) is None
                except Exception:idle_reuse=False
        if not r['success'] and not idle_reuse and monitor is not None:
            barrier=monitor.stop()
            try:observed=observer.snapshot(phase)
            except Exception as e:barrier.update(observer_settled=False,observer_error=str(e),complete=False)
        if campaign_observer and phase_opened:
            try:
                observed=observer.seal_phase(phase)
                if observed['failed_requests']:
                    idle_reuse=False
                    r['source_failure']=classify_source_failure(observed)
                    r.update(success=False,status=r['source_failure']['status'])
                    if barrier is None and monitor is not None:barrier=monitor.stop()
            except Exception as error:
                idle_reuse=False
                r.update(success=False,status='harness_observation_failure',observation_seal_error=str(error))
                if barrier is None and monitor is not None:barrier=monitor.stop()
        if idle_reuse and not _idle_source_reusable(r,child,guard,observed,sealed=True):
            idle_reuse=False
            if barrier is None and monitor is not None:barrier=monitor.stop()
        r['can_continue_session']=r['success'] or idle_reuse
        r['quiescence']={'kind':'normal_materialized_return_and_observed_source_drain','complete':True} if r['success'] else barrier or {
            'kind':'unverified','complete':False,'new_serving_session_required':True}
        if idle_reuse:
            r['quiescence']=dict(kind='terminal_worker_and_sealed_zero_source_requests',complete=True,
                                 new_serving_session_required=False)
            r['source_session_retained_after_preexecution_rejection']=True
        r['recovery_ms']=(barrier or {}).get('recovery_ms',0)
        r['source_observations']=observed
        r['session_reuse_requires_release']=campaign_observer
        r['resources']=monitor.summary() if monitor else None
        r['guard_status']=guard['status'] if guard else None
        if r['guard_status'] and r['guard_status'].startswith('study_'):
            r.update(secondary_status=r['status'], status=r['guard_status'], success=False,
                     failure_scope='study_budget_censoring_not_method_incorrectness')
        r['cost_scope']='full outer entry through durable outcome; recovery explicit; score and final timing telemetry separate'
        files=(root/'worker').rglob('*') if nl else (root/'worker').glob('*')
        r['partial_worker_files']=[file_pin(p) for p in sorted(files)
                                   if p.is_file() and (p.name.endswith('.json') or p.name.endswith('.json.gz'))]
        seal_started=time.perf_counter();pin=write_once(root/'receipt.json',r)
        finalization=None
        if campaign_observer:
            finalization={'receipt':pin,'can_continue_session':False,'records_released':False}
            try:
                if not observed or not observed.get('phase_seal'):raise ValueError('No valid source phase seal')
                observer.release_phase(phase,pin)
                finalization.update(records_released=True,can_continue_session=r['can_continue_session'])
            except Exception as error:
                finalization['release_error']=str(error)
                if barrier is None and monitor is not None:
                    barrier=monitor.stop();finalization['recovery']=barrier
            finalization['pin']=write_once(root/'session-finalization.json',finalization)
        complete_ms=(time.perf_counter()-started)*1000
        timing={'receipt':pin,'total_online_ms':complete_ms,'terminal_seal_ms':(time.perf_counter()-seal_started)*1000,
            'decision_e2e_ms':r.get('decision_e2e_ms'),'recovery_ms':(barrier or {}).get('recovery_ms',0),
            'session_finalization':finalization,
            'scope':'includes request read, worker preparation/execution/records, observation, recovery, terminal seal and source release; excludes this final measurement file and evaluation'}
        write_once(root/'timing.json',timing)
    return {**r,'receipt':pin,'timing':timing,
            'can_continue_session':finalization['can_continue_session'] if finalization else r['can_continue_session']}


def run_fixed_trial(**kwargs):
    return _run_trial(track='fixed_semantics',**kwargs)


def run_nl_trial(**kwargs):
    return _run_trial(track='natural_language',**kwargs)


def run_practical_trial(**kwargs):
    return _run_trial(track='trusted_template',**kwargs)
