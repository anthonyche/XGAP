#!/usr/bin/env python3
"""Offline gold-query backend admission; never an evaluated method or NL result.

Use a complete presampled bundle (or an explicitly labeled bounded diagnostic subset),
one compiled plan per intended query, and the
independent source-derived references. Stop on the first failure; do not replace
cases, retry, tune method policies, or feed these observations to an estimator.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.practical_planning import _baseline
from xgap.experiments.ch6_cost_pool import load, pin_identity
from xgap.experiments.ch6_fact_index import pin, write
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, native_clients
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.process_guard import ProcessBudget, run_guarded_command
from xgap.experiments.owned_resources import OwnedResources
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.external_federation import deadline
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.tools import BackendPluginRegistry, NativeBackendPlugin, BackendInvokeTool

REPO = Path(__file__).resolve().parents[1]


def worker(bundle_pin, case_id, profile_pin, output, planning='fixed_scan'):
    bundle = load(bundle_pin)
    case = next(c for c in bundle['cases'] if c['case_id'] == case_id)
    intent = load(case['oracle'])
    profile = FrozenOneShotProfile.load(profile_pin['path'], expected_sha256=profile_pin['sha256'])
    doc, estimator, _, sources, backends, specs, modes = profile.materialize()
    snapshot = snapshot_identity(sources, backends, doc['source_schema'])
    if snapshot != case['source_snapshot_sha256']:
        raise ValueError('Actual backend and authored snapshot differ')
    query = intent['query']
    program, assignment = lower_compact_query(query, doc['source_schema'], version='v2', optimize=True)
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    registry = BackendPluginRegistry()
    for name, client in native_clients(specs).items():
        registry.register(NativeBackendPlugin(name, client))
    scheduler=FederatedScheduler(BackendInvokeTool(registry), retention='roots')
    executions=[];plan_pin=None;policy=None
    def execute(plan):
        nonlocal plan_pin
        if executions:raise ValueError('Admission permits one final plan, never trial-and-select')
        plan_pin=write_once(root/'plan.json',plan.to_dict())
        result=scheduler.execute(plan);executions.append(result)
        return dict(success=result.success,answer_rows=list(result.final_rows))
    if planning=='fixed_scan':
        execute(_baseline(program,assignment,sources,backends,modes['performance'][0]))
    elif planning=='unified':
        from xgap.agent.intent_certificate import IntentCandidate,IntentFamily
        from xgap.agent.scope_authority import ScopedQueryUser
        from xgap.agent.unified_family import run_unified_family,UnifiedSettings
        from xgap.runtime.unified_physical import PhysicalMoves
        from xgap.planning.joint_cost import JointCostProfile
        question=load(case['request'])['question']
        family=IntentFamily('offline-admission-complete-query',(IntentCandidate.create(fingerprint(query),query),),(),snapshot,
            language_version='v2',coverage_basis='offline publisher supplied a complete query; no NL or intent-inference claim')
        user=ScopedQueryUser(family,case['oracle']['path'],case['oracle']['sha256'])
        physical=modes['performance'][0]
        policy=run_unified_family(question,family,user,
            prepare_seed=lambda *_:_baseline(program,assignment,sources,backends,physical,optimize_reads=False),
            execute=execute,costs=JointCostProfile(),settings=UnifiedSettings(),estimator=estimator,
            moves=PhysicalMoves(family,doc['source_schema'],backends,physical,sources))
        write(root/'planning.json',policy)
    else:raise ValueError('Unknown offline admission planning profile')
    result=executions[0] if executions else None
    answer = write_once(root/'answer.json', dict(rows=list(result.final_rows) if result else []))
    success=bool(result and result.success and (policy is None or policy['success']))
    write(root/'receipt.json', dict(success=success, case_id=case_id, bundle=bundle_pin,
        profile=profile_pin, query_sha256=fingerprint(query), source_snapshot_sha256=snapshot,
        plan=plan_pin, answer=answer, execution_ms=result.elapsed_ms if result else None,
        backend_calls=result.total_remote_calls if result else 0, bytes_moved=result.total_bytes_moved if result else 0,
        failures=[dict(node_id=n.node_id, error=n.error) for n in result.node_results if n.error] if result else [],
        planning=planning,final_plan_executions=len(executions),policy_status=policy.get('status') if policy else None,
        model_calls=0, evaluated_method=False))
    return 0 if success else 2


def selected_cases(bundle,case_id=None,case_ids=None):
    cases=list(enumerate(bundle['cases']))
    if len({c['case_id'] for _,c in cases})!=len(cases):
        raise ValueError('Duplicate case identity in frozen bundle')
    if case_id is not None and case_ids is not None:
        raise ValueError('Choose a single case or diagnostic subset, never both')
    if case_id is None and case_ids is None:return cases
    requested=[case_id] if case_id is not None else list(case_ids)
    if not 1<=len(requested)<=8 or len(set(requested))!=len(requested):
        raise ValueError('Diagnostic subset requires 1..8 distinct frozen case IDs')
    selected=[(i,c) for i,c in cases if c['case_id'] in requested]
    if len(selected)!=len(requested):raise ValueError('Replay case is absent from the frozen bundle')
    return selected


def admission_scope(case_id=None,case_ids=None):
    return 'diagnostic_subset' if case_ids is not None else ('single_case_replay' if case_id is not None else 'complete_bundle')


def run(bundle_pin, prepared_pin, output, planning='fixed_scan',serving_root=None,startup_seconds=300,rdf_file_mode='default',source_rss_bytes=4*1024**3,case_id=None,rdf_lazy_range=False,case_ids=None,source_runtime=None):
    if not os.environ.get('SLURM_JOB_ID') or os.environ.get('SLURM_JOB_GPUS'):
        raise ValueError('Explicit CPU-only allocation required')
    if planning not in ('fixed_scan','unified'):raise ValueError('Unknown admission planning profile')
    if rdf_file_mode not in ('default','direct'):raise ValueError('Unknown RDF serving file mode')
    if type(source_rss_bytes) is not int or not 1024**3<=source_rss_bytes<=16*1024**3:
        raise ValueError('Explicit aggregate source RSS budget must be 1..16 GiB')
    if type(startup_seconds) is not int or not 60<=startup_seconds<=3600:
        raise ValueError('Explicit offline serving startup limit required')
    bundle, prepared = load(bundle_pin), load(prepared_pin)
    if source_runtime is not None:
        from ch6_source_runtime import load as load_runtime, validate_contract
        validate_contract(load_runtime(source_runtime))
        if bundle['deployment']!='rdf' or rdf_file_mode!='direct' or not rdf_lazy_range:
            raise ValueError('Pinned repaired admission requires explicit Direct/lazy RDF configuration')
    if rdf_lazy_range and (rdf_file_mode!='direct' or bundle['deployment']=='native' or (case_id is None and case_ids is None and source_runtime is None)):
        raise ValueError('Experimental range overlay requires an explicit bounded Direct RDF diagnostic selection')
    if (bundle['schema_version'] not in ('xgap-ch6-heldout-cases-v1', 'xgap-ch6-factor-inputs-v1','xgap-ch6-deployment-factor-v1') or not prepared.get('success')
            or bundle['profile']['sha256'] != prepared['profile']['sha256']):
        raise ValueError('Frozen bundle/store identity mismatch')
    if not 1 <= len(bundle['cases']) <= 1024:
        raise ValueError('Admission requires 1..1024 preselected cases')
    cases=selected_cases(bundle,case_id,case_ids)
    scope=admission_scope(case_id,case_ids)
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    from run_bounded_joint_batch import BatchBudget, source_commit
    from native_store_session import NativeStoreSession
    from rdf_tdb_session import RdfTdbSession
    commit = source_commit()
    serving_bytes = sum(s['bytes'] for s in prepared['stores'].values())
    if type(serving_bytes) is not int or not 0 < serving_bytes <= 256*1024**3:
        raise ValueError('Explicit bounded serving-copy size required')
    limits = dict(total_wall_seconds=3600, package_max_bytes=serving_bytes+2*1024**3,
                  free_disk_reserve_bytes=6*1024**3)
    write(root/'intent.json', dict(bundle=bundle_pin, prepared=prepared_pin, limits=limits,
        planning=planning,worker_seconds=120, worker_rss_bytes=3*1024**3, source_rss_bytes=source_rss_bytes,
        rdf_file_mode=rdf_file_mode,experimental_lazy_range=rdf_lazy_range,
        source_runtime=source_runtime,
        case_order=[c['case_id'] for _,c in cases],admission_scope=scope,full_bundle_cases=len(bundle['cases']), model_calls=0, automatic_retries=0,
        serving_copy_bytes=serving_bytes, additional_output_budget_bytes=2*1024**3,
        serving_root=str(Path(serving_root).resolve()) if serving_root else None,startup_seconds=startup_seconds,
        scope='Offline compiler/backend/reference admission, not NL or policy evaluation'))
    budget = BatchBudget(root, limits, time.time(),extra_roots=(serving_root,) if serving_root else ())
    session = None; closure = None; outcomes = []; worker_attempts = 0
    result = dict(success=False, backend_roundtrip=False, bundle=bundle_pin,
        profile=bundle['profile'], prepared=prepared_pin, source_commit=commit,
        model_calls=0, evaluated_method=False, formal_campaign_started=False,
        source_runtime=source_runtime,rdf_file_mode=rdf_file_mode,experimental_lazy_range=rdf_lazy_range,
        admission_scope=scope,full_bundle_admitted=False)
    try:
        cls = NativeStoreSession if bundle['deployment'] == 'native' else RdfTdbSession
        session = cls(root=root/'session', prepared_path=prepared_pin['path'],
            prepared_sha256=prepared_pin['sha256'], discard_serving_copies=True,
            serving_root=serving_root,
            **({'file_mode':rdf_file_mode,'experimental_lazy_range':rdf_lazy_range,'runtime_contract':source_runtime} if bundle['deployment']!='native' else {}),
            budget=SourceObservationBudget(max_calls=128, request_bytes=1024**2,
                phase_request_bytes=16*1024**2, response_bytes=64*1024**2,
                phase_response_bytes=256*1024**2, timeout_seconds=60, capture_compression='gzip'))
        with deadline(startup_seconds):
            session.start()
        result['source_ready']=session.ready_pin
        for i, case in cases:
            if budget.sample([]):
                raise ValueError('Admission resource budget reached: '+budget.status)
            trial=root/f'case-{i:04d}'; trial.mkdir(); phase=f'admission:{i}'
            session.observer.set_phase(phase)
            resources=OwnedResources(session.owned, method_rss_bytes=3*1024**3,
                source_rss_bytes=source_rss_bytes, extra_monitor=budget)
            command=[sys.executable, str(Path(__file__).resolve()), '--worker',
                '--bundle-path', bundle_pin['path'], '--bundle-sha256', bundle_pin['sha256'],
                '--case-id', case['case_id'], '--profile-path', session.profile['path'],
                '--profile-sha256', session.profile['sha256'], '--output', str(trial/'worker'),'--planning',planning]
            worker_attempts += 1
            guard=run_guarded_command(command, cwd=REPO, output=trial/'guard',
                budget=ProcessBudget(wall_seconds=120, max_group_rss_bytes=3*1024**3), resource_monitor=resources)
            observed=session.observer.seal_phase(phase)
            path=trial/'worker/receipt.json'; child=json.loads(path.read_text()) if path.exists() else None
            success=bool(guard['success'] and child and child['success'] and not observed['failed_requests'])
            em=None
            if child and (child['case_id'] != case['case_id'] or pin_identity(child['bundle']) != pin_identity(bundle_pin)
                          or pin_identity(child['profile']) != pin_identity(session.profile)):
                raise ValueError('Admission worker identity mismatch')
            if success:
                reference=load(case['reference'])
                for k in ('query_sha256', 'source_snapshot_sha256'):
                    if reference[k] != child[k]:
                        raise ValueError('Reference query/source identity differs')
                actual=load(child['answer'])
                em=int(normalize_rows(actual['rows'], reference['normalization']) ==
                       normalize_rows(reference['rows'], reference['normalization']))
            row=dict(case_id=case['case_id'], success=success, answer_em=em, guard=guard,
                worker=pin(path) if child else None, source_observations=observed, resources=resources.summary())
            row,_=session.observer.persist_outcome(phase,trial/'outcome.json',row)
            outcomes.append(row)
            if not success or em != 1:
                raise ValueError('Admission failed at '+case['case_id']+'; preserve case and failure without retry')
        result.update(success=True, backend_roundtrip=True)
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
    finally:
        if session:
            closure=session.close()
    result.update(cases=outcomes, attempted=worker_attempts, audited=len(outcomes), planned=len(cases), full_bundle_cases=len(bundle['cases']), closure=closure)
    if closure is None or not all(closure.get(k) is True for k in
            ('owned_groups_drained', 'owned_processes_terminal', 'observer_stopped')):
        result.update(success=False, backend_roundtrip=False, closure_error='Unverified service cleanup')
    result['full_bundle_admitted']=bool(result['success'] and scope=='complete_bundle')
    write(root/'receipt.json', result)
    print(json.dumps(dict(success=result['success'], attempted=worker_attempts, audited=len(outcomes), output=str(root), error=result.get('error'))))
    return 0 if result['success'] else 2


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('bundle-path', 'bundle-sha256', 'output'):
        p.add_argument('--'+n, required=True)
    for n in ('prepared-path', 'prepared-sha256', 'profile-path', 'profile-sha256', 'case-id'):
        p.add_argument('--'+n)
    p.add_argument('--case-ids',nargs='+',help='1..8 diagnostic cases; frozen bundle order retained, never full admission')
    p.add_argument('--execute', action='store_true'); p.add_argument('--worker', action='store_true')
    p.add_argument('--planning',choices=['fixed_scan','unified'],default='fixed_scan')
    p.add_argument('--serving-root');p.add_argument('--startup-seconds',type=int,default=300)
    p.add_argument('--rdf-file-mode',choices=['default','direct'],default='default')
    p.add_argument('--rdf-lazy-range',action='store_true',help='Pinned overlay; bounded diagnosis or explicitly frozen runtime admission')
    p.add_argument('--source-runtime-path');p.add_argument('--source-runtime-sha256')
    p.add_argument('--source-rss-bytes',type=int,default=4*1024**3)
    a=p.parse_args(); bundle_pin=dict(path=a.bundle_path, sha256=a.bundle_sha256)
    if bool(a.source_runtime_path)!=bool(a.source_runtime_sha256):
        p.error('Both source runtime path and SHA-256 are required')
    runtime_pin=dict(path=a.source_runtime_path,sha256=a.source_runtime_sha256) if a.source_runtime_path else None
    if a.worker and runtime_pin:
        p.error('Runtime admission is configured by the parent, never the worker')
    if a.case_ids is not None and (a.case_id is not None or a.worker):
        p.error('--case-ids is for the diagnostic parent only and excludes --case-id')
    if a.worker:
        raise SystemExit(worker(bundle_pin, a.case_id,
            dict(path=a.profile_path, sha256=a.profile_sha256), a.output,a.planning))
    if a.execute:
        raise SystemExit(run(bundle_pin, dict(path=a.prepared_path, sha256=a.prepared_sha256), a.output,a.planning,
            a.serving_root,a.startup_seconds,a.rdf_file_mode,a.source_rss_bytes,a.case_id,a.rdf_lazy_range,a.case_ids,runtime_pin))
    b=load(bundle_pin)
    print(json.dumps(dict(stage='dry_run', cases=len(selected_cases(b,a.case_id,a.case_ids)),
        full_bundle_cases=len(b['cases']),admission_scope=admission_scope(a.case_id,a.case_ids),
        model_calls=0,backend_calls=0)))
