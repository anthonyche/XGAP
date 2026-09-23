#!/usr/bin/env python3
"""Sequential, resumable formal dispatcher. Dry-run is the default.

Sealed/failed/incomplete cells are never silently retried. Authorization to run
the full study is separate from preparing this command. Source/worker budgets
are enforced by the existing owned-resource guard. Global observed token limits
are checked between cells, with explicit per-cell reservations, not hidden retries.
"""
import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path
import time

from run_bounded_joint_batch import run,source_commit
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.ch6_release_audit import audit_release
from xgap.experiments.one_shot_records import write_once


def usage(root):
    totals=dict(model_calls=0,input_tokens=0,output_tokens=0,unknown_model_usage=False,sealed_cells=0)
    for p in root.glob('units/*/cells/*/terminal.json'):
        terminal=json.loads(p.read_text());outcome=load_pin(terminal['outcome']);totals['sealed_cells']+=1
        for k in ('model_calls','input_tokens','output_tokens'):
            v=outcome.get(k)
            if v is None:
                if outcome.get('model_calls')!=0:totals['unknown_model_usage']=True
            else:totals[k]+=v
    return totals


def dispatch(*,release_path,release_sha256,execute=False,read_key=False,max_new_cells=1):
    pin=dict(path=release_path,sha256=release_sha256);release=load_pin(pin)
    audit=audit_release(release)
    if not execute:
        print(json.dumps(dict(action='dry_run',ready=audit['success'],failed_checks=audit['failed_checks'],
            units=len(release.get('units',[])),model_calls=0,backend_calls=0)));return 0 if audit['success'] else 1
    if not audit['success']:raise ValueError('Formal release audit failed; no method was started')
    if type(max_new_cells) is not int or not 1<=max_new_cells<=100000:raise ValueError('Invalid cell bound')
    commit=source_commit()
    if commit!=release['source_commit']:raise ValueError('Release/code commit differs')
    root=Path(release['output_root']).resolve();root.mkdir(parents=True,exist_ok=True)
    previous_key=os.environ.get('XGAP_EXTERNAL_LLM_API_KEY');result=None
    with (root/'.campaign.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        identity=dict(release=pin,source_commit=commit)
        if (root/'identity.json').exists():
            marker=json.loads((root/'identity.json').read_text())
            if marker['identity']!=identity:raise ValueError('Output belongs to a different frozen release')
        else:
            if any(p.name!='.campaign.lock' for p in root.iterdir()):raise ValueError('Unidentified output is not resumable')
            marker=dict(identity=identity,started_unix=time.time());write_once(root/'identity.json',marker)
        attempts=0;budget=release['budget'];status='ready';invocations=[]
        try:
            if read_key:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=getpass.getpass('Model credential (not recorded): ')
            for unit in release['units']:
                manifest=load_pin(unit['manifest']);target=root/'units'/unit['unit_id']
                for cell in manifest['cells']:
                    if (target/'cells'/cell['cell_id']).exists():continue
                    spent=usage(root)
                    reserve=release['per_method_reservations'][cell['method']]
                    if spent['unknown_model_usage']:status='unknown_usage_requires_accounting';break
                    if attempts>=max_new_cells:status='invocation_cell_limit';break
                    if time.time()-marker['started_unix']+reserve['wall_seconds']>budget['total_wall_seconds']:
                        status='campaign_wall_budget';break
                    if any(spent[k]+reserve[k]>budget[k+'_cap'] for k in ('model_calls','input_tokens','output_tokens')):
                        status='campaign_model_budget';break
                    batch=run(manifest_path=unit['manifest']['path'],manifest_sha256=unit['manifest']['sha256'],
                              output=target,max_new_cells=1)
                    invocations.append(batch.get('receipt'));attempts+=batch.get('new_cells',0)
                    if batch['status']!='returned':status='unit_'+batch['status'];break
                if status!='ready':break
            if status=='ready':status='all_scheduled_units_processed'
        finally:
            if previous_key is None:os.environ.pop('XGAP_EXTERNAL_LLM_API_KEY',None)
            else:os.environ['XGAP_EXTERNAL_LLM_API_KEY']=previous_key
            history=root/'campaign-invocations';history.mkdir(exist_ok=True)
            result=dict(status=status,new_cells=attempts,usage=usage(root),invocations=invocations,
                automatic_retries=0,identity=identity)
            write_once(history/f'{len(list(history.iterdir()))+1:05d}.json',result)
    print(json.dumps(result));return 0


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('release-path','release-sha256'):p.add_argument('--'+n,required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--read-key',action='store_true')
    p.add_argument('--max-new-cells',type=int,default=1)
    raise SystemExit(dispatch(**vars(p.parse_args())))
