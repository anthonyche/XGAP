#!/usr/bin/env python3
"""Next frozen query group, six first-pass cells or four predeclared repeats.

Never retry an existing cell intent. Each fresh native session is owned and
closed before return. Answer and private-intent scoring stay outside the worker.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from native_store_session import NativeStoreSession,NativeSources
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.external_federation import deadline
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget

REPO=Path(__file__).resolve().parents[1]


class StudyBudget:
    def __init__(self,root,design,started):
        self.root=root;self.d=design;self.started=started;self.sampled=0;self.status=None;self.size=0;self.free=0
    def sample(self,_):
        if time.time()-self.started>self.d['total_wall_seconds']:self.status='study_wall_budget'
        if time.monotonic()-self.sampled>1:
            self.sampled=time.monotonic()
            self.size=sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
            self.free=shutil.disk_usage(self.root).free
            if self.size>self.d['package_max_bytes']:self.status='study_disk_budget'
            if self.free<self.d['free_disk_reserve_bytes']:self.status='study_disk_reserve'
        return self.status


def run(release_path,release_sha256,output):
    r=json.loads(read_pinned(release_path,release_sha256));d=r['design'];root=Path(output).resolve();root.mkdir(parents=True,exist_ok=True)
    if r['schema_version']!='xgap-family-policy-study-release-v1' or len(r['cells'])!=112:raise ValueError('Unexpected release')
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):raise ValueError('Commit before study execution')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    identity=dict(release_path=str(Path(release_path).resolve()),release_sha256=release_sha256,source_commit=commit)
    marker=root/'identity.json'
    if marker.exists():
        old=json.loads(marker.read_text())
        if old['identity']!=identity:raise ValueError('Cannot change code or inputs during the study')
        started=old['started_unix']
    else:
        started=time.time();write_once(marker,dict(identity=identity,started_unix=started))
    journal=root/'cells';journal.mkdir(exist_ok=True)
    pending=[c for c in r['cells'] if not (journal/c['cell_id']).exists()]
    if not pending:
        print(json.dumps(dict(status='all_cells_have_intents',count=len(r['cells']))));return
    group=(pending[0]['round'],pending[0]['group_index'])
    cells=[c for c in pending if (c['round'],c['group_index'])==group]
    budget=StudyBudget(root,d,started);session=None;closures=[];outputs=[]
    session_base=root/'sessions';session_base.mkdir(exist_ok=True)
    group_root=root/('group-'+group[0]+'-'+str(group[1]));group_root.mkdir(exist_ok=False)
    write_once(group_root/'intent.json',dict(identity=identity,cells=[c['cell_id'] for c in cells],group=group))
    try:
        for cell in cells:
            if budget.sample([]):break
            if d['total_wall_seconds']-(time.time()-started)<d['method_wall_seconds']+120:
                budget.status='insufficient_time_for_complete_cell';break
            if session is None:
                if budget.free<d['free_disk_reserve_bytes']+1024**3:
                    budget.status='insufficient_serving_copy_reserve';break
                number=len(list(session_base.iterdir()))+1
                session=NativeStoreSession(root=session_base/f'{number:03}',prepared_path=r['prepared']['path'],
                    prepared_sha256=r['prepared']['sha256'],discard_serving_copies=True,budget=SourceObservationBudget(**d['source_budget']))
                with deadline(120):session.start()
            path=journal/cell['cell_id'];path.mkdir(exist_ok=False)
            write_once(path/'intent.json',dict(identity=identity,cell=cell,session_root=str(session.root),
                fresh_source_session=session.observer.generation==0,attempts=1))
            q=cell['request'];family=cell['family'];oracle=cell['oracle']
            outcome=run_nl_trial(request_path=q['path'],request_sha256=q['sha256'],method=cell['method'],
                output=path/'execution',profile_path=session.profile['path'],profile_sha256=session.profile['sha256'],
                oracle_path=oracle['path'],oracle_sha256=oracle['sha256'],intent_family_path=family['path'],
                intent_family_sha256=family['sha256'],owned_services=NativeSources(session).owned_for(cell['method']),
                observer=session.observer,budget=ProcessBudget(wall_seconds=d['method_wall_seconds'],
                    max_group_rss_bytes=d['method_rss_bytes']),source_rss_bytes=d['source_rss_bytes'],package_monitor=budget)
            ref=cell['reference']
            score=score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
                reference_path=ref['path'],reference_sha256=ref['sha256'],output=path/'score.json')
            terminal=dict(cell_id=cell['cell_id'],status='sealed',outcome=outcome['receipt'],
                score=dict(path=str(path/'score.json'),sha256=hashlib.sha256((path/'score.json').read_bytes()).hexdigest()),
                execution_success=outcome['success'],answer_em=score['answer_em'],source_calls=(outcome['source_observations'] or {}).get('requests'),
                end_to_end_ms=outcome['timing']['total_online_ms'],model_calls=outcome['model_calls'])
            write_once(path/'terminal.json',terminal);outputs.append(terminal)
            print(json.dumps(dict(cell_id=cell['cell_id'],label=cell['label'],status=outcome['status'],
                answer_em=score['answer_em'],calls=terminal['source_calls'],ms=round(terminal['end_to_end_ms'],1))),flush=True)
            if not outcome['can_continue_session']:
                closures.append(session.close());session=None
            if outcome['status'] in ('guard_monitor_failed','supervisor_failed','harness_observation_failure'):
                budget.status=budget.status or 'harness_integration_failure';break
    finally:
        if session:closures.append(session.close())
        write_once(group_root/'receipt.json',dict(identity=identity,group=group,outputs=outputs,closures=closures,
            budget_status=budget.status,artifact_bytes=budget.size,free_bytes=budget.free,
            all_owned_closed=all(c['owned_groups_drained'] and c['owned_processes_terminal'] and c['observer_stopped'] for c in closures)))
    print(json.dumps(dict(group=group,sealed=len(outputs),budget_status=budget.status)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release-path',required=True);p.add_argument('--release-sha256',required=True);p.add_argument('--output',required=True)
    run(**vars(p.parse_args()))
