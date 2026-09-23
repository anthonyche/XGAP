#!/usr/bin/env python3
"""Offline gold-query backend admission; never an evaluated method or NL result.

Use a complete presampled bundle, one compiled plan per intended query, and the
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


def worker(bundle_pin, case_id, profile_pin, output):
    bundle = load(bundle_pin)
    case = next(c for c in bundle['cases'] if c['case_id'] == case_id)
    intent = load(case['oracle'])
    profile = FrozenOneShotProfile.load(profile_pin['path'], expected_sha256=profile_pin['sha256'])
    doc, _, _, sources, backends, specs, modes = profile.materialize()
    snapshot = snapshot_identity(sources, backends, doc['source_schema'])
    if snapshot != case['source_snapshot_sha256']:
        raise ValueError('Actual backend and authored snapshot differ')
    query = intent['query']
    program, assignment = lower_compact_query(query, doc['source_schema'], version='v2', optimize=True)
    plan = _baseline(program, assignment, sources, backends, modes['performance'][0])
    root = Path(output); root.mkdir(parents=True, exist_ok=False)
    plan_pin = write_once(root/'plan.json', plan.to_dict())
    registry = BackendPluginRegistry()
    for name, client in native_clients(specs).items():
        registry.register(NativeBackendPlugin(name, client))
    result = FederatedScheduler(BackendInvokeTool(registry), retention='roots').execute(plan)
    answer = write_once(root/'answer.json', dict(rows=list(result.final_rows)))
    write(root/'receipt.json', dict(success=result.success, case_id=case_id, bundle=bundle_pin,
        profile=profile_pin, query_sha256=fingerprint(query), source_snapshot_sha256=snapshot,
        plan=plan_pin, answer=answer, execution_ms=result.elapsed_ms,
        backend_calls=result.total_remote_calls, bytes_moved=result.total_bytes_moved,
        failures=[dict(node_id=n.node_id, error=n.error) for n in result.node_results if n.error],
        model_calls=0, evaluated_method=False))
    return 0 if result.success else 2


def run(bundle_pin, prepared_pin, output):
    if not os.environ.get('SLURM_JOB_ID') or os.environ.get('SLURM_JOB_GPUS'):
        raise ValueError('Explicit CPU-only allocation required')
    bundle, prepared = load(bundle_pin), load(prepared_pin)
    if (bundle['schema_version'] not in ('xgap-ch6-heldout-cases-v1', 'xgap-ch6-factor-inputs-v1') or not prepared.get('success')
            or bundle['profile']['sha256'] != prepared['profile']['sha256']):
        raise ValueError('Frozen bundle/store identity mismatch')
    if not 1 <= len(bundle['cases']) <= 1024:
        raise ValueError('Admission requires 1..1024 preselected cases')
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
        worker_seconds=120, worker_rss_bytes=3*1024**3, source_rss_bytes=4*1024**3,
        case_order=[c['case_id'] for c in bundle['cases']], model_calls=0, automatic_retries=0,
        serving_copy_bytes=serving_bytes, additional_output_budget_bytes=2*1024**3,
        scope='Offline compiler/backend/reference admission, not NL or policy evaluation'))
    budget = BatchBudget(root, limits, time.time())
    session = None; closure = None; outcomes = []
    result = dict(success=False, backend_roundtrip=False, bundle=bundle_pin,
        profile=bundle['profile'], prepared=prepared_pin, source_commit=commit,
        model_calls=0, evaluated_method=False, formal_campaign_started=False)
    try:
        cls = NativeStoreSession if bundle['deployment'] == 'native' else RdfTdbSession
        session = cls(root=root/'session', prepared_path=prepared_pin['path'],
            prepared_sha256=prepared_pin['sha256'], discard_serving_copies=True,
            budget=SourceObservationBudget(max_calls=128, request_bytes=1024**2,
                phase_request_bytes=16*1024**2, response_bytes=64*1024**2,
                phase_response_bytes=256*1024**2, timeout_seconds=60, capture_compression='gzip'))
        with deadline(300):
            session.start()
        for i, case in enumerate(bundle['cases']):
            if budget.sample([]):
                raise ValueError('Admission resource budget reached: '+budget.status)
            trial=root/f'case-{i:04d}'; trial.mkdir(); phase=f'admission:{i}'
            session.observer.set_phase(phase)
            resources=OwnedResources(session.owned, method_rss_bytes=3*1024**3,
                source_rss_bytes=4*1024**3, extra_monitor=budget)
            command=[sys.executable, str(Path(__file__).resolve()), '--worker',
                '--bundle-path', bundle_pin['path'], '--bundle-sha256', bundle_pin['sha256'],
                '--case-id', case['case_id'], '--profile-path', session.profile['path'],
                '--profile-sha256', session.profile['sha256'], '--output', str(trial/'worker')]
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
                worker=pin(path) if child else None, observations=observed, resources=resources.summary())
            sealed=write_once(trial/'outcome.json', row)
            session.observer.release_phase(phase, sealed); outcomes.append(row)
            if not success or em != 1:
                raise ValueError('Admission failed at '+case['case_id']+'; preserve case and failure without retry')
        result.update(success=True, backend_roundtrip=True)
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
    finally:
        if session:
            closure=session.close()
    result.update(cases=outcomes, attempted=len(outcomes), planned=len(bundle['cases']), closure=closure)
    if closure is None or not all(closure.get(k) is True for k in
            ('owned_groups_drained', 'owned_processes_terminal', 'observer_stopped')):
        result.update(success=False, backend_roundtrip=False, closure_error='Unverified service cleanup')
    write(root/'receipt.json', result)
    print(json.dumps(dict(success=result['success'], attempted=len(outcomes), output=str(root), error=result.get('error'))))
    return 0 if result['success'] else 2


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('bundle-path', 'bundle-sha256', 'output'):
        p.add_argument('--'+n, required=True)
    for n in ('prepared-path', 'prepared-sha256', 'profile-path', 'profile-sha256', 'case-id'):
        p.add_argument('--'+n)
    p.add_argument('--execute', action='store_true'); p.add_argument('--worker', action='store_true')
    a=p.parse_args(); bundle_pin=dict(path=a.bundle_path, sha256=a.bundle_sha256)
    if a.worker:
        raise SystemExit(worker(bundle_pin, a.case_id,
            dict(path=a.profile_path, sha256=a.profile_sha256), a.output))
    if a.execute:
        raise SystemExit(run(bundle_pin, dict(path=a.prepared_path, sha256=a.prepared_sha256), a.output))
    b=load(bundle_pin)
    print(json.dumps(dict(stage='dry_run', cases=len(b['cases']), model_calls=0, backend_calls=0)))
