#!/usr/bin/env python3
"""Frozen ordered method batch; resume unattempted cells only.

One shared native/RDF source session, independent workers and sealed scoring.
Historical schemas remain readable; the formal schema dispatches all five
current methods without profile fitting or automatic retries.
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from native_store_session import NativeStoreSession
from rdf_tdb_session import RdfTdbSession
from ch6_source_runtime import validate_admission, session_options, entry_cohort, entry_serving_profile
from xgap.experiments.bounded_joint_contract import METHODS
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.common_method_trial import run_nl_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.interpretation_diagnostics import batch_cell_summary
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.external_federation import DeadlineExceeded, deadline
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.process_guard import ProcessBudget
from xgap.experiments.query_loss_score import score_query_loss
from xgap.experiments.ch6_direct import METHOD as DIRECT_METHOD
from xgap.experiments.batch_cell_identity import validate_cell_id

REPO=Path(__file__).resolve().parents[1]
SCHEMA='xgap-bounded-joint-batch-v1'
UNIFIED_SCHEMA='xgap-unified-lookahead-batch-v1'
FORMAL_SCHEMA='xgap-ch6-five-method-batch-v1'
EXTERNAL_METHOD='aruqula-fedx'


def load(pin):
    return json.loads(read_pinned(pin['path'],pin['sha256']))


def validate(manifest):
    formal=manifest.get('schema_version')==FORMAL_SCHEMA
    expected={'schema_version','deployment','prepared','design','cells'}|({'external_runtime'} if formal else set())
    entry_fields={'entry_migration','entry_profile'}
    present=entry_fields.intersection(manifest)
    if present and (not formal or present!=entry_fields):
        raise ValueError('Formal entry migration and profile must be pinned together')
    expected|=present
    if set(manifest)!=expected or manifest['schema_version'] not in (SCHEMA,UNIFIED_SCHEMA,FORMAL_SCHEMA):
        raise ValueError('Unexpected bounded joint manifest')
    if manifest['deployment'] not in ('native','rdf'):raise ValueError('Unknown deployment')
    design=manifest['design']
    numeric=('total_wall_seconds','package_max_bytes','free_disk_reserve_bytes','method_wall_seconds',
             'method_rss_bytes','source_rss_bytes','startup_seconds')
    if set(design)-{'source_storage','source_runtime'}!=set(numeric)|{'source_budget'}:raise ValueError('Explicit batch budgets required')
    if design.get('source_storage','evidence') not in ('evidence','node_local'):
        raise ValueError('Unknown common source storage policy')
    if any(type(design[k]) not in (int,float) or not math.isfinite(design[k]) or design[k]<=0 for k in numeric):
        raise ValueError('Invalid batch budgets')
    SourceObservationBudget(**design['source_budget'])
    ProcessBudget(wall_seconds=design['method_wall_seconds'],max_group_rss_bytes=design['method_rss_bytes'])
    if any(type(design[k]) is not int for k in ('package_max_bytes','free_disk_reserve_bytes','source_rss_bytes')):
        raise ValueError('Byte budgets must be integers')
    from xgap.experiments.unified_contract import METHODS as UNIFIED_METHODS
    from xgap.experiments.ch6_formal_protocol import METHODS as PAPER_METHODS
    allowed=tuple(PAPER_METHODS.values()) if formal else (*UNIFIED_METHODS,DIRECT_METHOD) if manifest['schema_version']==UNIFIED_SCHEMA else METHODS
    cells=manifest['cells']
    if not isinstance(cells,list) or not 1<=len(cells)<=10000:raise ValueError('Bounded nonempty cells required')
    ids=[]
    for cell in cells:
        if formal and cell.get('method')==EXTERNAL_METHOD:
            if manifest['deployment']!='rdf':raise ValueError('ARUQULA->FedX requires matched RDF deployment')
            if set(cell)!={'cell_id','method','request','reference'}:
                raise ValueError('External cell accepts public request and evaluator reference only; no private oracle/config/state')
            if not manifest['external_runtime']:raise ValueError('Pinned original external runtime required')
        elif set(cell)-{'controlled_state'}!={'cell_id','method','request','scope','oracle','config','reference'}:
            raise ValueError('Invalid cell fields')
        validate_cell_id(cell['cell_id'])
        if cell['method'] not in allowed:raise ValueError('Only current bounded joint methods are allowed')
        if cell['method']==DIRECT_METHOD and 'controlled_state' in cell:
            raise ValueError('Direct baseline requires a natural-language proposal, not controlled truth')
        ids.append(cell['cell_id'])
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate cell IDs')
    # Only pin syntax is inspected here, not private intent or reference contents.
    for pin in [manifest['prepared'],*(c[k] for c in cells for k in ('request','scope','oracle','config','reference','controlled_state') if k in c),
                *(manifest[k] for k in entry_fields if k in manifest),
                *([manifest['external_runtime']] if formal and manifest['external_runtime'] else [])]:
        if not isinstance(pin,dict) or not isinstance(pin.get('path'),str) or not Path(pin['path']).is_absolute() or not re.fullmatch(r'[a-f0-9]{64}',pin.get('sha256','')):
            raise ValueError('Absolute artifact paths and SHA-256 pins required')
    validate_admission(design,manifest['deployment'],manifest['prepared'],cells=cells,
        entry_migration=manifest.get('entry_migration'),entry_profile=manifest.get('entry_profile'))


class BatchBudget:
    """Sticky study censoring; wall budget includes time between invocations."""
    def __init__(self,root,design,started,extra_roots=(),global_deadline_monotonic=None):
        self.root=root;self.design=design;self.started=started;self.status=None;self.sampled=0;self.size=0;self.free=0
        self.global_deadline_monotonic=global_deadline_monotonic
        self.extra_roots=tuple(Path(p).resolve() for p in extra_roots)
        roots=(Path(root).resolve(),*self.extra_roots)
        if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(roots) for b in roots[i+1:]):
            raise ValueError('Budget roots must be disjoint')

    def sample(self,_):
        if self.status:return self.status
        if self.global_deadline_monotonic is not None and time.monotonic()>=self.global_deadline_monotonic:
            self.status='study_global_wall_budget'
        if time.time()-self.started>=self.design['total_wall_seconds']:self.status='study_wall_budget'
        if time.monotonic()-self.sampled>1:
            self.sampled=time.monotonic()
            roots=(self.root,*self.extra_roots)
            self.size=sum(p.stat().st_size for root in roots for p in root.rglob('*') if p.is_file())
            self.free=min(shutil.disk_usage(root).free for root in roots if root.exists())
            if self.size>=self.design['package_max_bytes']:self.status=self.status or 'study_disk_budget'
            if self.free<self.design['free_disk_reserve_bytes']:self.status=self.status or 'study_disk_reserve'
        return self.status


def cell_admission_context(design,cell,*,source_ready,external_ready=False,phase='before_cell'):
    """Remaining phases, not cumulative charges or an estimated runtime.

    Source startup is shared while its session is live. The external method has
    a separate per-request startup; a cold external request needs both phases.
    """
    source=0 if source_ready else design['startup_seconds']
    external=design['startup_seconds'] if cell['method']==EXTERNAL_METHOD and not external_ready else 0
    method=design['method_wall_seconds']
    return dict(phase=phase,source_ready=source_ready,external_ready=external_ready,
        source_startup_seconds=source,external_startup_seconds=external,method_seconds=method,
        minimum_method_seconds=method,maximum_startup_seconds=source+external,
        needed_total_seconds=source+external+method)


def source_commit():
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True):
        raise ValueError('Commit before batch execution')
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()


def closed(receipt):
    return all(receipt.get(k) is True for k in ('owned_groups_drained','owned_processes_terminal','observer_stopped'))


def inventory(root,cells):
    counts=dict(sealed=0,execution_success=0,execution_failed=0,study_censored=0,incomplete=0,unattempted=0)
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
            if (outcome.get('failure_scope')=='study_budget_censoring_not_method_incorrectness' or
                    outcome['status']=='harness_budget_censored'):
                counts['study_censored']+=1
    return counts


def run(manifest_path,manifest_sha256,output,*,max_new_cells=10000,before_cell=None,
        before_cell_phase=None,global_deadline_monotonic=None):
    if type(max_new_cells) is not int or not 1<=max_new_cells<=10000:raise ValueError('Invalid invocation cell bound')
    if before_cell is not None and before_cell_phase is not None:
        raise ValueError('Choose the legacy or phase-aware admission callback, not both')
    if global_deadline_monotonic is not None and (type(global_deadline_monotonic) not in (int,float) or
            not math.isfinite(global_deadline_monotonic) or global_deadline_monotonic<=0):
        raise ValueError('A finite positive global monotonic deadline is required')
    manifest=json.loads(read_pinned(manifest_path,manifest_sha256));validate(manifest)
    commit=source_commit();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=True)
    with (root/'.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another batch invocation owns this output') from None
        return _run(manifest,manifest_sha256,commit,root,max_new_cells,before_cell,
                    before_cell_phase,global_deadline_monotonic)


def _run(manifest,digest,commit,root,max_new_cells,before_cell=None,
         before_cell_phase=None,global_deadline_monotonic=None):
    migration=entry_cohort(manifest.get('entry_migration'),manifest.get('entry_profile'),
        manifest['prepared'],manifest['deployment'],cells=manifest['cells'])
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
        if json.loads((old/'receipt.json').read_text()).get('budget_status')=='study_harness_failure':
            raise ValueError('Previous invocation has an unresolved harness failure; explicit recovery required before resume')
        if manifest['design'].get('source_storage')=='node_local' and any(
                c.get('serving_copy_reclamation_complete') is False for c in json.loads((old/'receipt.json').read_text())['closures']):
            raise ValueError('Prior node-local serving copies require explicit storage recovery')
    before=inventory(root,manifest['cells'])
    if not before['unattempted']:return dict(status='no_unattempted_cells',counts=before,new_cells=0)
    invocation=runs/f'{len(previous)+1:04}';invocation.mkdir()
    write_once(invocation/'intent.json',dict(identity=identity,max_new_cells=max_new_cells))
    (root/'cells').mkdir(exist_ok=True);(root/'sessions').mkdir(exist_ok=True)
    design=manifest['design'];budget=BatchBudget(root,design,started,global_deadline_monotonic=global_deadline_monotonic)
    session=None;external=None;closures=[];attempts=0;error=None;admission_stop=None;provisional_cell=None;active_startup_limit=None
    phase_aware=before_cell_phase is not None or global_deadline_monotonic is not None
    def admit(cell,phase,*,check_callback=True):
        nonlocal admission_stop
        context=cell_admission_context(design,cell,source_ready=session is not None,
            external_ready=external is not None,phase=phase)
        context['unit_remaining_seconds']=design['total_wall_seconds']-(time.time()-started)
        context['global_remaining_seconds']=(None if global_deadline_monotonic is None else
            global_deadline_monotonic-time.monotonic())
        # Startup is a cap, not a mandatory duration. With an enclosing deadline
        # it may consume only the time left after a complete method grant.
        required=(context['minimum_method_seconds'] if global_deadline_monotonic is not None else context['needed_total_seconds'])
        context['admission_required_seconds']=required
        reason=budget.sample([]) if check_callback else budget.status
        if reason is None and check_callback and before_cell_phase is not None:reason=before_cell_phase(cell,dict(context))
        if reason is not None and (not isinstance(reason,str) or not reason):
            raise ValueError('Phase admission callback must return a reason or None')
        # Accounting callbacks can inspect many sealed files. Their elapsed time
        # is real work and cannot be spent twice using a stale admission grant.
        context['unit_remaining_seconds']=design['total_wall_seconds']-(time.time()-started)
        context['global_remaining_seconds']=(None if global_deadline_monotonic is None else
            global_deadline_monotonic-time.monotonic())
        if reason is None and context['unit_remaining_seconds']<required:
            reason='study_insufficient_time_for_cell'
        if reason is None and context['global_remaining_seconds'] is not None and context['global_remaining_seconds']<required:
            reason='study_global_insufficient_time_for_cell'
        if reason is None and global_deadline_monotonic is not None and context['maximum_startup_seconds']:
            if min(context['unit_remaining_seconds'],context['global_remaining_seconds'])<=required:
                reason='study_insufficient_startup_time'
        if reason:
            budget.status=reason;admission_stop=dict(cell_id=cell['cell_id'],reason=reason,context=context)
        return reason
    def startup_seconds():
        nonlocal active_startup_limit
        if global_deadline_monotonic is None:return design['startup_seconds']
        remaining=min(global_deadline_monotonic-time.monotonic(),design['total_wall_seconds']-(time.time()-started))
        available=remaining-design['method_wall_seconds']
        active_startup_limit=dict(seconds=max(0,min(design['startup_seconds'],available)),
            capped_by_study=available<design['startup_seconds'],reserved_method_seconds=design['method_wall_seconds'])
        if available<=0:raise DeadlineExceeded('Study startup allowance exhausted; full method grant retained')
        return active_startup_limit['seconds']
    internal_profile=None
    try:
        workspace=None
        if design.get('source_storage')=='node_local':
            if not os.environ.get('SLURM_JOB_ID'):
                raise ValueError('Node-local storage requires an explicit Slurm allocation')
            workspace=Path(tempfile.mkdtemp(prefix='xgap-source-',dir=os.environ.get('SLURM_TMPDIR','/tmp')))
            budget=BatchBudget(root,design,started,extra_roots=(workspace,),global_deadline_monotonic=global_deadline_monotonic)
            write_once(invocation/'source-workspace.json',dict(path=str(workspace),job_id=os.environ['SLURM_JOB_ID'],
                common_to_all_methods=True,storage_accounted=True))
        for cell in manifest['cells']:
            path=root/'cells'/cell['cell_id']
            if path.exists():continue
            if attempts>=max_new_cells or budget.sample([]):break
            # Supervisor accounting only. Check before opening services or
            # journaling a new attempt; a stop still closes the shared session.
            if before_cell is not None:
                reason=before_cell(cell)
                if reason is not None:
                    if not isinstance(reason,str) or not reason:
                        raise ValueError('Cell admission callback must return a reason or None')
                    budget.status=reason;break
            if phase_aware:
                if admit(cell,'before_cell'):break
            else:
                # Preserve the legacy invocation contract for existing callers.
                needed=design['method_wall_seconds']+(design['startup_seconds'] if session is None or cell['method']==EXTERNAL_METHOD else 0)
                if design['total_wall_seconds']-(time.time()-started)<needed:
                    budget.status='study_insufficient_time_for_cell';break
            if session is None:
                cls=NativeStoreSession if manifest['deployment']=='native' else RdfTdbSession
                ordinal=f'{len(list((root/"sessions").iterdir()))+1:04}'
                session=cls(root=root/'sessions'/ordinal,
                    prepared_path=manifest['prepared']['path'],prepared_sha256=manifest['prepared']['sha256'],
                    discard_serving_copies=True,budget=SourceObservationBudget(**design['source_budget']),
                    serving_root=workspace/ordinal if workspace else None,
                    **session_options(design.get('source_runtime')))
                with deadline(startup_seconds()):session.start()
                active_startup_limit=None
                internal_profile=session.profile if migration is None else entry_serving_profile(
                    serving_profile=session.profile,entry_profile=manifest['entry_profile'],cohort=migration,
                    migration_pin=manifest['entry_migration'],output=session.root/'entry-profile.json')
                if phase_aware and admit(cell,'after_source_startup'):break
            if budget.sample([]):break
            if design['total_wall_seconds']-(time.time()-started)<design['method_wall_seconds']:
                budget.status='study_insufficient_time_for_cell';break
            # The preceding storage scan or profile setup can itself consume
            # time. Refresh the grant without repeating accounting callbacks.
            if phase_aware and admit(cell,'before_request_journal',check_callback=False):break
            path.mkdir()
            if phase_aware and cell['method']==EXTERNAL_METHOD:
                # Setup can spend time but cannot run the author method. Keep it
                # outside the attempted-cell ledger until the full method grant
                # has been checked again. Interrupted setup is retained below.
                provisional_cell=path
                from ch6_external_session import ExternalSession
                external=ExternalSession(root=path/'external-services',config_pin=manifest['external_runtime'],source_session=session)
                with deadline(startup_seconds()):external.start()
                active_startup_limit=None
                if admit(cell,'after_external_startup'):break
            attempts+=1
            # This journal is supervisor-only; the worker never receives reference pins.
            write_once(path/'intent.json',dict(identity=identity,cell=cell,session_root=str(session.root),
                fresh_source_session=session.observer.generation==0,attempts=1))
            provisional_cell=None
            kwargs={}
            for key,argument in (('request','request'),('scope','scope'),('oracle','oracle'),('config','joint_config')):
                if cell['method']==EXTERNAL_METHOD:continue
                if cell['method']==DIRECT_METHOD and key in ('scope','oracle'):continue
                kwargs[argument+'_path']=cell[key]['path'];kwargs[argument+'_sha256']=cell[key]['sha256']
            if 'controlled_state' in cell:
                kwargs.update(controlled_state_path=cell['controlled_state']['path'],
                    controlled_state_sha256=cell['controlled_state']['sha256'])
            process_budget=ProcessBudget(wall_seconds=design['method_wall_seconds'],max_group_rss_bytes=design['method_rss_bytes'])
            if cell['method']==EXTERNAL_METHOD:
                from ch6_external_session import ExternalSession,run_trial as external_trial
                if external is None:
                    external=ExternalSession(root=path/'external-services',config_pin=manifest['external_runtime'],source_session=session)
                    with deadline(startup_seconds()):external.start()
                    active_startup_limit=None
                outcome=external_trial(request=cell['request'],output=path/'execution',session=external,
                    budget=process_budget,source_rss_bytes=design['source_rss_bytes'],package_monitor=budget)
                closure=external.close();closures.append(closure);external=None
                if not closed(closure):raise ValueError('External method resources did not close')
            else:
                outcome=run_nl_trial(**kwargs,method=cell['method'],output=path/'execution',
                    profile_path=internal_profile['path'],profile_sha256=internal_profile['sha256'],
                    observer=session.observer,owned_services=session.owned,budget=process_budget,
                    source_rss_bytes=design['source_rss_bytes'],package_monitor=budget)
            # Costly sources close before scoring a failed method. Never reuse a failed phase.
            if not outcome['can_continue_session'] or outcome['status']=='harness_budget_censored':
                closure=session.close();closures.append(closure);session=None
                if not closed(closure):raise ValueError('Failed trial sources did not close')
            ref=cell['reference']
            score=score_trial(outcome['receipt']['path'],receipt_sha256=outcome['receipt']['sha256'],
                reference_path=ref['path'],reference_sha256=ref['sha256'],output=path/'score.json')
            loss_pin=None
            if outcome.get('core') and cell['method']!=DIRECT_METHOD:
                score_query_loss(receipt=outcome['receipt'],request=cell['request'],oracle=cell['oracle'],output=path/'query-loss.json')
                loss_pin=file_pin(path/'query-loss.json')
            answer_em=None if (outcome.get('failure_scope')=='study_budget_censoring_not_method_incorrectness' or
                outcome['status'] in ('harness_budget_censored','harness_observation_failure','supervisor_failed','guard_monitor_failed')) else score['answer_em']
            write_once(path/'terminal.json',dict(cell_id=cell['cell_id'],outcome=outcome['receipt'],
                score=file_pin(path/'score.json'),**({'query_loss':loss_pin} if loss_pin else {}),
                execution_success=outcome['success'],answer_em=answer_em))
            summary=batch_cell_summary(cell['cell_id'],outcome,answer_em)
            print(json.dumps(summary),flush=True)
            if outcome['status'] in ('guard_monitor_failed','supervisor_failed','harness_observation_failure'):
                budget.status='study_harness_failure';break
            if outcome['status']=='harness_budget_censored' and cell['method']==EXTERNAL_METHOD:
                from ch6_external_session import verified_budget_censoring
                if not verified_budget_censoring(outcome):
                    budget.status='study_harness_failure';break
    except (Exception,KeyboardInterrupt) as exc:
        if isinstance(exc,DeadlineExceeded) and active_startup_limit and active_startup_limit['capped_by_study']:
            budget.status='study_startup_wall_budget'
        elif isinstance(exc,DeadlineExceeded) and global_deadline_monotonic is not None and time.monotonic()>=global_deadline_monotonic:
            budget.status='study_global_wall_budget'
        else:error=dict(type=type(exc).__name__,message=str(exc))
    finally:
        if external:closures.append(external.close())
        if session:closures.append(session.close())
        unstarted_setup=None
        if provisional_cell is not None and all(closed(c) for c in closures):
            if (provisional_cell/'intent.json').exists() or (provisional_cell/'execution').exists():
                raise ValueError('Cannot release a cell with a method attempt')
            destination=invocation/'unstarted-setups'/provisional_cell.name
            destination.parent.mkdir(exist_ok=True)
            original=str(provisional_cell);provisional_cell.rename(destination)
            unstarted_setup=write_once(destination/'unstarted.json',dict(cell_id=provisional_cell.name,
                source_identity=identity,original_path=original,retained_path=str(destination),setup_attempts=1,
                method_attempts=0,model_calls=0,answer_query_executions=0,
                stop_reason=budget.status,error=error,all_owned_closed=True,
                evidence_path_semantics='Setup records retain original absolute paths; no method or cell intent was started'))
        result=dict(schema_version='xgap-ch6-five-method-invocation-v1' if manifest['schema_version']==FORMAL_SCHEMA else 'xgap-unified-batch-invocation-v1' if manifest['schema_version']==UNIFIED_SCHEMA else 'xgap-bounded-joint-batch-invocation-v1',identity=identity,
            new_cells=attempts,counts=inventory(root,manifest['cells']),budget_status=budget.status,error=error,
            closures=closures,all_owned_closed=all(closed(c) for c in closures),automatic_retries=0,
            scope='execution_failed counts unsuccessful executions, not algorithm quality; study_censored is a subset; incomplete intents are never retried; offline startup/scoring excluded from method latency')
        if phase_aware:result.update(admission_stop=admission_stop,unstarted_setup=unstarted_setup,
            stopped_startup_limit=active_startup_limit,
            global_deadline_monotonic=global_deadline_monotonic,
            global_deadline_scope='Work deadline; verified resource shutdown and ledger sealing remain mandatory after stopping work')
        result['status']='failed' if error or not result['all_owned_closed'] else 'budget_stopped' if budget.status else 'returned'
        result['receipt']=write_once(invocation/'receipt.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest-path','manifest-sha256','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--max-new-cells',type=int,default=10000)
    result=run(**vars(parser.parse_args()));print(json.dumps(result))
    raise SystemExit(1 if result['status']=='failed' else 0)
