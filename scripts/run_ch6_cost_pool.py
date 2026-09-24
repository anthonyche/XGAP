#!/usr/bin/env python3
"""Explicit offline equivalent-plan measurements; never an online plan selector."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from dataclasses import asdict

from xgap.agent.intent_execution import snapshot_identity
from xgap.experiments.ch6_cost_pool import load,freeze,pin_identity
from xgap.experiments.ch6_fact_index import pin,write
from xgap.experiments.one_shot_profile import FrozenOneShotProfile,native_clients
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.row_normalization import normalize_rows
from xgap.experiments.process_guard import ProcessBudget,run_guarded_command
from xgap.experiments.owned_resources import OwnedResources
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.external_federation import deadline
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.unified_physical import identity
from xgap.tools import BackendPluginRegistry,NativeBackendPlugin,BackendInvokeTool

REPO=Path(__file__).resolve().parents[1]


def worker(pool_pin,plan_id,profile_pin,output):
    root=Path(output);root.mkdir(parents=True,exist_ok=False)
    pool=load(pool_pin);profile=FrozenOneShotProfile.load(profile_pin['path'],expected_sha256=profile_pin['sha256'])
    doc,_,_,sources,backends,specs,_,=profile.materialize()
    if snapshot_identity(sources,backends,doc['source_schema'])!=pool['source_snapshot_sha256']:raise ValueError('Pool source snapshot changed')
    record=next(p for p in pool['plans'] if p['plan_id']==plan_id)
    plan=FederatedExecutionPlan.from_dict(load(record['plan']))
    if identity(plan)!=plan_id:raise ValueError('Pinned executable DAG identity differs')
    registry=BackendPluginRegistry()
    for name,client in native_clients(specs).items():registry.register(NativeBackendPlugin(name,client))
    write(root/'intent.json',dict(pool=pool_pin,plan_id=plan_id,profile=profile_pin,maximum_executions=1,model_calls=0))
    result=FederatedScheduler(BackendInvokeTool(registry),retention='roots').execute(plan)
    answer=write_once(root/'answer.json',dict(rows=list(result.final_rows)))
    write(root/'receipt.json',dict(success=result.success,plan_id=plan_id,pool=pool_pin,profile=profile_pin,answer=answer,
        execution_ms=result.elapsed_ms,backend_calls=result.total_remote_calls,bytes_moved=result.total_bytes_moved,
        retention=result.retention,model_calls=0))
    return 0 if result.success else 2


def run(pool_pin,prepared_pin,deployment,output,source_storage='evidence',source_runtime=None,startup_seconds=300):
    if not os.environ.get('SLURM_JOB_ID') or os.environ.get('SLURM_JOB_GPUS'):raise ValueError('CPU-only allocation required')
    if source_storage not in ('evidence','node_local') or not 60<=startup_seconds<=3600:raise ValueError('Explicit serving storage/startup contract required')
    if source_runtime is not None and deployment!='rdf':raise ValueError('Repaired runtime is RDF only')
    from ch6_source_runtime import session_options,validate_contract
    if source_runtime is not None:validate_contract(load(source_runtime))
    pool=load(pool_pin);prepared=load(prepared_pin)
    if not prepared.get('success') or prepared['profile']['sha256']!=pool['profile']['sha256']:raise ValueError('Pool/store profile differs')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    serving_bytes=sum(s['bytes'] for s in prepared['stores'].values())
    if type(serving_bytes) is not int or not 0<serving_bytes<=256*1024**3:raise ValueError('Bounded frozen serving-copy size required')
    from run_bounded_joint_batch import BatchBudget,source_commit
    commit=source_commit()
    source_budget=SourceObservationBudget(max_calls=256,request_bytes=1024**2,phase_request_bytes=16*1024**2,
        response_bytes=64*1024**2,phase_response_bytes=256*1024**2,timeout_seconds=60,capture_compression='gzip')
    write(root/'intent.json',dict(pool=pool_pin,prepared=prepared_pin,deployment=deployment,automatic_retries=0,
                                 source_commit=commit,source_storage=source_storage,source_runtime=source_runtime,
                                 source_budget=asdict(source_budget),startup_seconds=startup_seconds,
                                 serving_copy_bytes=serving_bytes,additional_output_budget_bytes=pool['budget']['output_bytes'],
                                 stage='offline measurement; no model calls and no formal method campaign'))
    from native_store_session import NativeStoreSession
    from rdf_tdb_session import RdfTdbSession
    workspace=Path(tempfile.mkdtemp(prefix='xgap-f6-',dir=os.environ.get('SLURM_TMPDIR','/tmp'))) if source_storage=='node_local' else None
    b=pool['budget'];budget=BatchBudget(root,dict(total_wall_seconds=b['total_seconds'],package_max_bytes=serving_bytes+b['output_bytes'],
        free_disk_reserve_bytes=b['free_reserve_bytes']),time.time(),extra_roots=(workspace,) if workspace else ())
    observations=[];session=None;closure=None;result=dict(success=False,model_calls=0,online_feedback=False,
        pool=pool_pin,prepared=prepared_pin,source_commit=commit,intent=pin(root/'intent.json'))
    try:
        cls=NativeStoreSession if deployment=='native' else RdfTdbSession
        session=cls(root=root/'session',prepared_path=prepared_pin['path'],prepared_sha256=prepared_pin['sha256'],
            discard_serving_copies=True,budget=source_budget,serving_root=workspace/'stores' if workspace else None,
            **session_options(dict(contract=source_runtime) if source_runtime else None))
        with deadline(startup_seconds):session.start()
        result.update(source_ready=session.ready_pin,storage_placement=pin(root/'session/storage-placement.json'))
        for position,item in enumerate(pool['order']):
            if budget.sample([]):raise ValueError('Offline study budget reached: '+budget.status)
            directory=root/f'trial-{position:03d}';directory.mkdir();phase=f'cost-pool:{position}'
            session.observer.set_phase(phase)
            monitor=OwnedResources(session.owned,method_rss_bytes=b['worker_rss_bytes'],source_rss_bytes=b['source_rss_bytes'],extra_monitor=budget)
            command=[sys.executable,str(Path(__file__).resolve()),'--worker','--pool-path',pool_pin['path'],'--pool-sha256',pool_pin['sha256'],
                '--plan-id',item['plan_id'],'--profile-path',session.profile['path'],'--profile-sha256',session.profile['sha256'],'--output',str(directory/'worker')]
            guard=run_guarded_command(command,cwd=REPO,output=directory/'guard',
                budget=ProcessBudget(wall_seconds=b['worker_seconds'],max_group_rss_bytes=b['worker_rss_bytes']),resource_monitor=monitor)
            sealed=session.observer.seal_phase(phase);child_path=directory/'worker/receipt.json'
            child=json.loads(child_path.read_text()) if child_path.exists() else None
            if child and (child['plan_id']!=item['plan_id'] or pin_identity(child['pool'])!=pin_identity(pool_pin)
                          or pin_identity(child['profile'])!=pin_identity(session.profile)):
                raise ValueError('Offline worker identity differs')
            success=bool(guard['success'] and child and child['success'] and sealed['failed_requests']==0)
            em=None
            if success:
                reference=load(pool['reference']);answer=load(child['answer'])
                em=int(normalize_rows(answer['rows'],reference['normalization'])==normalize_rows(reference['rows'],reference['normalization']))
            row=dict(**item,query_sha256=pool['query_sha256'],source_snapshot_sha256=pool['source_snapshot_sha256'],
                unit=pool['unit'],timing_scope=pool['timing_scope'],success=success,answer_em=em,
                actual_cost=child['execution_ms'] if success else None,source_observations=sealed,
                guard=pin(directory/'guard/receipt.json') if (directory/'guard/receipt.json').exists() else guard,
                worker=pin(child_path) if child else None,resources=monitor.summary())
            row,_=session.observer.persist_outcome(phase,directory/'outcome.json',row);observations.append(row)
            if not success or em!=1:raise ValueError('Prespecified plan failed admission; stop without pruning or retrying it')
        result.update(success=True)
    except Exception as error:result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if session:closure=session.close()
    result.update(observations=observations,closure=closure)
    if closure is None or not all(closure.get(k) is True for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped')):
        result.update(success=False,closure_error='Owned sources did not close verifiably')
    if result['success']:
        freeze(pool,observations,root/'frozen-costs.json');result.update(frozen_costs=pin(root/'frozen-costs.json'))
    write(root/'receipt.json',result);print(json.dumps(dict(success=result['success'],observations=len(observations),output=str(root))))
    return 0 if result['success'] else 2


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('pool-path','pool-sha256','output'):p.add_argument('--'+n,required=True)
    for n in ('prepared-path','prepared-sha256','profile-path','profile-sha256','plan-id'):p.add_argument('--'+n)
    p.add_argument('--deployment',choices=['native','rdf'],default='rdf');p.add_argument('--execute',action='store_true');p.add_argument('--worker',action='store_true')
    p.add_argument('--source-storage',choices=['evidence','node_local'],default='evidence')
    p.add_argument('--source-runtime-path');p.add_argument('--source-runtime-sha256')
    p.add_argument('--startup-seconds',type=int,default=300)
    a=p.parse_args();pool_pin=dict(path=a.pool_path,sha256=a.pool_sha256)
    if a.worker:raise SystemExit(worker(pool_pin,a.plan_id,dict(path=a.profile_path,sha256=a.profile_sha256),a.output))
    if not a.execute:
        pool=load(pool_pin);print(json.dumps(dict(stage='dry_run',executions=len(pool['order']),budget=pool['budget'],model_calls=0)))
    else:
        if bool(a.source_runtime_path)!=bool(a.source_runtime_sha256):raise ValueError('Runtime path and digest are required together')
        runtime=dict(path=a.source_runtime_path,sha256=a.source_runtime_sha256) if a.source_runtime_path else None
        raise SystemExit(run(pool_pin,dict(path=a.prepared_path,sha256=a.prepared_sha256),a.deployment,a.output,
            a.source_storage,runtime,a.startup_seconds))
