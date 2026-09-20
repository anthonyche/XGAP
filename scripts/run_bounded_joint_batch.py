#!/usr/bin/env python3
"""Frozen ordered batch for the current two modes. Resume unattempted cells only.

Native and RDF serving copies use the existing owned-session implementations.
References are opened only after a common outcome is sealed. No baselines,
profile rewrites, estimator fitting, automatic retries or acquisition replay.
"""
import argparse
import fcntl
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

from native_store_session import NativeStoreSession
from rdf_tdb_session import RdfTdbSession
from xgap.experiments.bounded_joint_contract import METHODS
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget
from xgap.experiments.query_loss_score import score_query_loss

REPO=Path(__file__).resolve().parents[1]
SCHEMA='xgap-bounded-joint-batch-v1'


def load(pin):
    return json.loads(read_pinned(pin['path'],pin['sha256']))


def validate(manifest):
    if set(manifest)!={'schema_version','deployment','prepared','design','cells'} or manifest['schema_version']!=SCHEMA:
        raise ValueError('Unexpected bounded joint manifest')
    if manifest['deployment'] not in ('native','rdf'):raise ValueError('Unknown deployment')
    design=manifest['design']
    numeric=('total_wall_seconds','package_max_bytes','free_disk_reserve_bytes','method_wall_seconds',
             'method_rss_bytes','source_rss_bytes','startup_seconds')
    if set(design)!=set(numeric)|{'source_budget'}:raise ValueError('Explicit batch budgets required')
    if any(type(design[k]) not in (int,float) or not math.isfinite(design[k]) or design[k]<=0 for k in numeric):
        raise ValueError('Invalid batch budgets')
    SourceObservationBudget(**design['source_budget'])
    ProcessBudget(wall_seconds=design['method_wall_seconds'],max_group_rss_bytes=design['method_rss_bytes'])
    if any(type(design[k]) is not int for k in ('package_max_bytes','free_disk_reserve_bytes','source_rss_bytes')):
        raise ValueError('Byte budgets must be integers')
    cells=manifest['cells']
    if not isinstance(cells,list) or not 1<=len(cells)<=10000:raise ValueError('Bounded nonempty cells required')
    ids=[]
    for cell in cells:
        if set(cell)-{'controlled_state'}!={'cell_id','method','request','scope','oracle','config','reference'}:
            raise ValueError('Invalid cell fields')
        if not isinstance(cell['cell_id'],str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}',cell['cell_id']):
            raise ValueError('Invalid cell ID')
        if cell['method'] not in METHODS:raise ValueError('Only current bounded joint methods are allowed')
        ids.append(cell['cell_id'])
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate cell IDs')
    # Only pin syntax is inspected here, not private intent or reference contents.
    for pin in [manifest['prepared'],*(c[k] for c in cells for k in ('request','scope','oracle','config','reference')),
                *(c['controlled_state'] for c in cells if 'controlled_state' in c)]:
        if not isinstance(pin,dict) or not isinstance(pin.get('path'),str) or not Path(pin['path']).is_absolute() or not re.fullmatch(r'[a-f0-9]{64}',pin.get('sha256','')):
            raise ValueError('Absolute artifact paths and SHA-256 pins required')


class BatchBudget:
    """Sticky study censoring; wall budget includes time between invocations."""
    def __init__(self,root,design,started):
        self.root=root;self.design=design;self.started=started;self.status=None;self.sampled=0;self.size=0;self.free=0

    def sample(self,_):
        if self.status:return self.status
        if time.time()-self.started>=self.design['total_wall_seconds']:self.status='study_wall_budget'
        if time.monotonic()-self.sampled>1:
            self.sampled=time.monotonic()
            self.size=sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
            self.free=shutil.disk_usage(self.root).free
            if self.size>=self.design['package_max_bytes']:self.status=self.status or 'study_disk_budget'
            if self.free<self.design['free_disk_reserve_bytes']:self.status=self.status or 'study_disk_reserve'
        return self.status


def source_commit():
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
        raise ValueError('Commit before batch execution')
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()


def closed(receipt):
    return all(receipt.get(k) is True for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped'))


def inventory(root,cells):
    counts=dict(sealed=0,execution_success=0,execution_failed=0,incomplete=0,unattempted=0)
    for cell in cells:
        path=root/'cells'/cell['cell_id']
        if not path.exists():counts['unattempted']+=1
        elif not (path/'terminal.json').exists():counts['incomplete']+=1
        else:
            terminal=json.loads((path/'terminal.json').read_text())
            outcome=load(terminal['outcome']);score=load(terminal['score'])
            if (terminal['cell_id']!=cell['cell_id'] or outcome['method']!=cell['method'] or
                    outcome['request_sha256']!=cell['request']['sha256'] or
                    score['receipt_sha256']!=terminal['outcome']['sha256'] or
                    score['reference_sha256']!=cell['reference']['sha256']):
                raise ValueError('Sealed cell identity differs')
            if 'query_loss' in terminal:
                loss=load(terminal['query_loss'])
                if loss['receipt_sha256']!=terminal['outcome']['sha256'] or loss['oracle_sha256']!=cell['oracle']['sha256']:
                    raise ValueError('Sealed query loss identity differs')
            counts['sealed']+=1
            counts['execution_success' if outcome['success'] else 'execution_failed']+=1
    return counts


def run(manifest_path,manifest_sha256,output,*,max_new_cells=10000):
    if type(max_new_cells) is not int or not 1<=max_new_cells<=10000:raise ValueError('Invalid invocation cell bound')
    manifest=json.loads(read_pinned(manifest_path,manifest_sha256));validate(manifest)
    commit=source_commit();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=True)
    with (root/'.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another batch invocation owns this output') from None
        return _run(manifest,manifest_sha256,commit,root,max_new_cells)


def _run(manifest,digest,commit,root,max_new_cells):
    identity=dict(manifest_sha256=digest,source_commit=commit)
    marker=root/'identity.json'
    if marker.exists():
        old=json.loads(marker.read_text())
        if old['identity']!=identity:raise ValueError('Cannot change code or inputs during a batch')
        started=old['started_unix']
    else:
        if any(p.name!='.lock' for p in root.iterdir()):raise ValueError('Output has no verified batch identity')
        started=time.time();write_once(marker,dict(identity=identity,started_unix=started))
    runs=root/'invocations';runs.mkdir(exist_ok=True)
    previous=sorted(runs.iterdir())
    for old in previous:
        if not (old/'receipt.json').exists() or not json.loads((old/'receipt.json').read_text()).get('all_owned_closed'):
            raise ValueError('Previous invocation lacks verified closure; explicit recovery required before resume')
    before=inventory(root,manifest['cells'])
    if not before['unattempted']:return dict(status='no_unattempted_cells',counts=before,new_cells=0)
    invocation=runs/f'{len(previous)+1:04}';invocation.mkdir()
    write_once(invocation/'intent.json',dict(identity=identity,max_new_cells=max_new_cells))
    (root/'cells').mkdir(exist_ok=True);(root/'sessions').mkdir(exist_ok=True)
    design=manifest['design'];budget=BatchBudget(root,design,started);session=None;closures=[];attempts=0;error=None
    try:
        for cell in manifest['cells']:
            path=root/'cells'/cell['cell_id']
            if path.exists():continue
            if attempts>=max_new_cells or budget.sample([]):break
            needed=design['method_wall_seconds']+(design['startup_seconds'] if session is None else 0)
            if design['total_wall_seconds']-(time.time()-started)<needed:
                budget.status='study_insufficient_time_for_cell';break
            if session is None:
                cls=NativeStoreSession if manifest['deployment']=='native' else RdfTdbSession
                session=cls(root=root/'sessions'/f'{len(list((root/"sessions").iterdir()))+1:04}',
                    prepared_path=manifest['prepared']['path'],prepared_sha256=manifest['prepared']['sha256'],
                    discard_serving_copies=True,budget=SourceObservationBudget(**design['source_budget']))
                with deadline(design['startup_seconds']):session.start()
            if budget.sample([]):break
            if design['total_wall_seconds']-(time.time()-started)<design['method_wall_seconds']:
                budget.status='study_insufficient_time_for_cell';break
            path.mkdir();attempts+=1
            # This journal is supervisor-only; the worker never receives reference pins.
            write_once(path/'intent.json',dict(identity=identity,cell=cell,session_root=str(session.root),
                fresh_source_session=session.observer.generation==0,attempts=1))
            kwargs={}
            for key,argument in (('request','request'),('scope','scope'),('oracle','oracle'),('config','joint_config')):
                kwargs[argument+'_path']=cell[key]['path'];kwargs[argument+'_sha256']=cell[key]['sha256']
            if 'controlled_state' in cell:
                kwargs.update(controlled_state_path=cell['controlled_state']['path'],
                    controlled_state_sha256=cell['controlled_state']['sha256'])
            outcome=run_nl_trial(**kwargs,method=cell['method'],output=path/'execution',
                profile_path=session.profile['path'],profile_sha256=session.profile['sha256'],
                observer=session.observer,owned_services=session.owned,
                budget=ProcessBudget(wall_seconds=design['method_wall_seconds'],max_group_rss_bytes=design['method_rss_bytes']),
                source_rss_bytes=design['source_rss_bytes'],package_monitor=budget)
            # Costly sources close before scoring a failed method. Never reuse a failed phase.
            if not outcome['can_continue_session']:
                closure=session.close();closures.append(closure);session=None
                if not closed(closure):raise ValueError('Failed trial sources did not close')
            ref=cell['reference']
            score=score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
                reference_path=ref['path'],reference_sha256=ref['sha256'],output=path/'score.json')
            loss_pin=None
            if outcome.get('core'):
                score_query_loss(receipt=outcome['receipt'],request=cell['request'],oracle=cell['oracle'],output=path/'query-loss.json')
                loss_pin=file_pin(path/'query-loss.json')
            write_once(path/'terminal.json',dict(cell_id=cell['cell_id'],outcome=outcome['receipt'],
                score=file_pin(path/'score.json'),**({'query_loss':loss_pin} if loss_pin else {}),
                execution_success=outcome['success'],answer_em=score['answer_em']))
            print(json.dumps(dict(cell_id=cell['cell_id'],status=outcome['status'],answer_em=score['answer_em'])),flush=True)
            if outcome['status'] in ('guard_monitor_failed','supervisor_failed','harness_observation_failure'):
                budget.status='study_harness_failure';break
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc))
    finally:
        if session:closures.append(session.close())
        result=dict(schema_version='xgap-bounded-joint-batch-invocation-v1',identity=identity,
            new_cells=attempts,counts=inventory(root,manifest['cells']),budget_status=budget.status,error=error,
            closures=closures,all_owned_closed=all(closed(c) for c in closures),automatic_retries=0,
            scope='sealed counts include failed outcomes; incomplete intents are never retried; offline startup/scoring excluded from method latency')
        result['status']='failed' if error or not result['all_owned_closed'] else 'budget_stopped' if budget.status else 'returned'
        result['receipt']=write_once(invocation/'receipt.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest-path','manifest-sha256','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--max-new-cells',type=int,default=10000)
    result=run(**vars(parser.parse_args()));print(json.dumps(result))
    raise SystemExit(1 if result['status']=='failed' else 0)
