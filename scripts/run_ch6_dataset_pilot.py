#!/usr/bin/env python3
"""Run one admitted dataset repetition with per-cell accounting, no retries.

Tokens are observed stopping thresholds, not unverified worst-case estimates.
The current method request can cross a token threshold. Calls, request/response
bytes and each worker remain bounded by the frozen method/transport contracts.
"""
import argparse,fcntl,json,os,time
from pathlib import Path

from run_bounded_joint_batch import run,source_commit
from run_ch6_formal_campaign import usage,package_bytes
from xgap.experiments.ch6_pilot_release import audit_pilot
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.one_shot_records import write_once


def stop_reason(spent,budget,*,remaining_seconds,needed_seconds,next_call_cap):
    if spent['unsealed_cells']:return 'unsealed_cell_requires_accounting'
    if spent['unknown_model_usage']:return 'unknown_usage_requires_accounting'
    for kind in ('input_tokens','output_tokens'):
        if spent[kind]>=budget[kind+'_stop_threshold']:return 'observed_'+kind+'_threshold'
    if spent['model_calls']+next_call_cap>budget['model_calls_cap']:return 'model_call_budget'
    if remaining_seconds<needed_seconds:return 'pilot_wall_budget'
    return None


def dispatch(release_path,release_sha256,*,execute=False):
    rp=dict(path=release_path,sha256=release_sha256);release=load_pin(rp);audit=audit_pilot(release)
    if not execute:return dict(action='dry_run',ready=audit['success'],audit=audit,model_calls=0,backend_calls=0)
    if not audit['success']:raise ValueError('Pilot audit failed before any method starts: '+str(audit['failed_checks']))
    if source_commit()!=release['source_commit']:raise ValueError('Pilot source revision differs')
    if not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):raise ValueError('Model credential unavailable; no method starts')
    root=Path(release['output_root']);root.mkdir(parents=True,exist_ok=True)
    with (root/'.pilot.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        identity=dict(release=rp,source_commit=release['source_commit'])
        marker=root/'identity.json'
        if marker.exists():
            journal=json.loads(marker.read_text())
            if journal['identity']!=identity:raise ValueError('Pilot identity changed')
        else:
            if any(p.name!='.pilot.lock' for p in root.iterdir()):raise ValueError('Unidentified pilot output')
            journal=dict(identity=identity,started_unix=time.time());write_once(marker,journal)
        budget=release['budget'];status='all_pilot_requests_processed';invocations=[];attempted=0;error=None
        try:
            for unit in release['units']:
                manifest=load_pin(unit['manifest']);target=root/'units'/unit['unit_id'];design=manifest['design']
                external_cap=load_pin(manifest['external_runtime'])['model_budget']['max_calls'] if manifest.get('external_runtime') else 0
                def before(cell):
                    spent=usage(root)
                    reason=stop_reason(spent,budget,remaining_seconds=budget['total_wall_seconds']-(time.time()-journal['started_unix']),
                        needed_seconds=design['method_wall_seconds']+2*design['startup_seconds'],
                        next_call_cap=external_cap if cell['method']=='aruqula-fedx' else 1)
                    if reason:return reason
                    occupied=package_bytes(root);own=package_bytes(target) if target.exists() else 0
                    if occupied-own+design['package_max_bytes']>budget['package_max_bytes']:return 'pilot_package_budget'
                    return None
                while True:
                    spent=usage(root)
                    if spent['unsealed_cells'] or spent['unknown_model_usage']:
                        status='accounting_incomplete';break
                    pending=[c for c in manifest['cells'] if not (target/'cells'/c['cell_id']).exists()]
                    if not pending:break
                    reason=before(pending[0])
                    if reason:status=reason;break
                    result=run(manifest_path=unit['manifest']['path'],manifest_sha256=unit['manifest']['sha256'],
                        output=target,max_new_cells=min(len(pending),release['max_cells_per_source_session']),before_cell=before)
                    invocations.append(result.get('receipt'));attempted+=result['new_cells']
                    if result['status']!='returned':status=result.get('budget_status') or 'unit_'+result['status'];break
                    if not result['new_cells']:status='unit_no_progress';break
                if status!='all_pilot_requests_processed':break
        except (Exception,KeyboardInterrupt) as exc:
            status='pilot_supervisor_failure';error=dict(type=type(exc).__name__,message=str(exc))
        finally:
            spent=usage(root)
            if spent['unknown_model_usage'] or spent['unsealed_cells']:status='accounting_incomplete'
            histories=root/'pilot-invocations';histories.mkdir(exist_ok=True)
            result=dict(schema_version='xgap-ch6-dataset-pilot-invocation-v1',status=status,error=error,
                identity=identity,new_cells=attempted,usage=spent,invocations=invocations,automatic_retries=0,
                token_policy=release['token_policy'],thresholds_crossed=[k for k in ('input_tokens','output_tokens')
                    if spent[k]>=budget[k+'_stop_threshold']],formal_campaign_ready=False,purpose='development_pilot')
            result['receipt']=write_once(histories/f'{len(list(histories.iterdir()))+1:05d}.json',result)
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('release-path','release-sha256'):p.add_argument('--'+name,required=True)
    p.add_argument('--execute',action='store_true');result=dispatch(**vars(p.parse_args()))
    print(json.dumps(result),flush=True)
    raise SystemExit(0 if result.get('ready') or result.get('status')=='all_pilot_requests_processed' else 2)
