"""Append-only second continuation with evidence-backed accounting correction.

No prior outcome is overwritten or retried. Only the already pinned model usage
lost by the outer source-drain exception may be reconciled. Unknown evidence
outside this narrow case remains blocking. Preparation performs no remote calls.
"""
import argparse
from copy import deepcopy
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

import run_ch6_small_continuation as first
from xgap.experiments.one_shot_records import write_once

SCHEMA='xgap-ch6-small-chain-continuation-v1'
RUNTIME_FILES=first.HARNESS_FILES|{'scripts/run_ch6_small_chain_continuation.py',
    'src/xgap/experiments/common_method_trial.py'}
PACKAGING_FILES=first.PACKAGING_FILES|{'scripts/build_ch6_small_chain_handoff.py'}
REPO=first.REPO


def same_pin(a,b):
    return all(a.get(k)==b.get(k) for k in ('path','sha256'))


def migration(repo,old,new):
    paths=subprocess.check_output(['git','diff','--name-only',old,new,'--'],cwd=repo,text=True).splitlines()
    illegal=[p for p in paths if p not in RUNTIME_FILES|PACKAGING_FILES and not p.startswith(('tests/','docs/')) and p!='AGENTS.md']
    if illegal:raise ValueError('Non-harness source changes: '+', '.join(illegal))
    return dict(parent_commit=old,continuation_commit=new,changed_paths=paths,
        allowed_runtime_paths=sorted(RUNTIME_FILES),experimental_algorithm_unchanged=True)


def _usage(outcome):
    result={}
    for k in first.USAGE_FIELDS:
        v=outcome.get(k)
        if v is None and outcome.get('model_calls')==0:v=0
        if type(v) is not int or v<0:raise ValueError('Model usage remains unknown')
        result[k]=v
    return result


def recover_usage(outcome,cell,logical,*,load,resolve):
    """Prove a missing outer counter from three immutable worker witnesses."""
    if (outcome.get('status')!='upstream_source_failure' or outcome.get('success') is not False or
        outcome.get('error_type')!='RuntimeError' or outcome.get('error')!='Source accounting not settled' or
        outcome.get('guard_status')!='completed' or (outcome.get('quiescence') or {}).get('complete') is not True or
        not all(outcome.get(k) is None for k in first.USAGE_FIELDS)):
        raise ValueError('Unknown usage is outside the proven source-drain accounting defect')
    pins=[]
    def worker_pin(name):
        matches=[p for p in outcome.get('partial_worker_files',[]) if p['path']==str(logical/'execution/worker'/name)]
        if len(matches)!=1:raise ValueError('Missing unique pinned worker evidence: '+name)
        pins.append(matches[0]);return matches[0]
    worker=worker_pin('receipt.json');child=load(worker)
    if (child.get('schema_version')!='xgap-nl-method-worker-v1' or
        any(child.get(k)!=outcome.get(k) for k in ('method','request_sha256','question_id','profile_sha256','track')) or
        child.get('dataset') not in (None,outcome.get('dataset')) or
        any(child.get(k+'_sha256')!=cell[k]['sha256'] for k in ('scope','oracle')) or
        child.get('joint_config_sha256')!=cell['config']['sha256'] or
        child.get('controlled_state_sha256')!=(cell.get('controlled_state') or {}).get('sha256')):
        raise ValueError('Recovered worker identity differs from its frozen cell')
    usage=_usage(child)
    core_pin=worker_pin('core.json.gz')
    if not same_pin(core_pin,child.get('core') or {}):raise ValueError('Worker core pin differs')
    data=Path(resolve(core_pin['path'])).read_bytes()
    if hashlib.sha256(data).hexdigest()!=core_pin['sha256']:raise ValueError('Worker core bytes differ')
    raw=gzip.decompress(data);core=json.loads(raw)
    logical_hash=child['core'].get('logical_sha256')
    if logical_hash and hashlib.sha256(raw).hexdigest()!=logical_hash:raise ValueError('Worker core logical hash differs')
    if _usage(core)!=usage:raise ValueError('Core and worker usage disagree')
    interpretation=worker_pin('interpretation.json');record=load(interpretation)
    if len(record.get('records',[]))!=1:raise ValueError('Expected the frozen one-call interpretation record')
    response=record['records'][0].get('response') or {}
    recorded=response.get('usage') or {}
    if (response.get('provenance',{}).get('usage_reported') is not True or
            response.get('provenance',{}).get('external_call_count_complete') is False or
            usage!=dict(model_calls=recorded.get('external_calls'),input_tokens=recorded.get('input_tokens'),
                        output_tokens=recorded.get('output_tokens'))):
        raise ValueError('Provider evidence does not corroborate complete model usage')
    return dict(cell_id=cell['cell_id'],usage=usage,evidence=pins,
        basis='validated worker receipt, matching core, and durable provider-reported usage',
        old_outcome_preserved=True,old_status=outcome['status'],old_success=False,
        correction_scope='model accounting only; no answer, timing or failure status changed')


def inspect_chain(parent_release,first_contract,*,mapper=None,repo=REPO):
    parent=first.inspect_parent(parent_release,mapper=mapper)
    load,resolve=first.reader(mapper);cfg=load(first_contract)
    if (cfg.get('schema_version')!=first.SCHEMA or not same_pin(cfg['parent_release'],parent_release) or
        cfg['prior_usage']!=parent['usage'] or cfg['parent_evidence']!=parent['evidence_pins'] or
        cfg['original_budget']!=parent['release']['budget'] or cfg['automatic_retries']!=0 or
        cfg['parent_output_root']!=parent['release']['output_root'] or cfg['remaining_cells']!=parent['remaining_cells'] or
        cfg['max_cells_per_source_session']!=parent['release']['max_cells_per_source_session']):
        raise ValueError('First continuation no longer binds the original study')
    if first.source_migration(repo,parent['source_commit'],cfg['source_commit'],cfg['source_migration']['allowed_runtime_paths'])!=cfg['source_migration']:
        raise ValueError('First continuation source migration differs')
    expected=[x for x in parent['units'] if x['pending_cells']]
    if len(expected)!=len(cfg['units']):raise ValueError('First continuation unit count differs')
    root=Path(cfg['output_root']);evidence=[first_contract];corrections=[];pending_units=[]
    def local(logical):
        ref=first.pin(resolve(str(logical)),logical_path=logical);evidence.append(ref);return load(ref)
    identity=local(root/'identity.json')
    if not same_pin(identity.get('contract',{}),first_contract) or identity.get('source_commit')!=cfg['source_commit']:
        raise ValueError('First continuation output identity differs')
    overall=local(root/'receipt.json')
    if not same_pin(overall.get('contract',{}),first_contract) or overall.get('error'):
        raise ValueError('Prior continuation supervisor is unresolved')
    elapsed=overall.get('elapsed_seconds')
    if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed<=0:
        raise ValueError('Prior continuation has no measured elapsed time')
    spent=dict(model_calls=0,input_tokens=0,output_tokens=0,unknown_model_usage=False,sealed_cells=0,unsealed_cells=0)
    original_spent=dict(spent);seen=set();pending_seen=False
    for original,unit in zip(expected,cfg['units']):
        manifest=load(unit['manifest']);evidence.append(unit['manifest'])
        wanted=deepcopy(original['manifest']);wanted['cells']=original['pending_cells']
        if unit['unit_id']!=original['unit']['unit_id'] or manifest!=wanted:
            raise ValueError('First continuation changed original cells, ordering or budgets')
        unit_root=root/'units'/unit['unit_id'];physical=Path(resolve(str(unit_root)))
        if physical.exists():
            ident=local(unit_root/'identity.json')
            if ident['identity']!=dict(source_commit=cfg['source_commit'],manifest_sha256=unit['manifest']['sha256']):
                raise ValueError('Prior continuation batch identity differs')
            invs=list((physical/'invocations').iterdir())
            if not invs:raise ValueError('Missing prior invocation closure')
            for inv in sorted(invs):
                receipt=local(unit_root/'invocations'/inv.name/'receipt.json')
                if not receipt.get('all_owned_closed') or receipt.get('error'):raise ValueError('Prior invocation not closed')
                for closure in receipt.get('closures',[]):first.require_closed(closure)
        pending=[]
        for cell in manifest['cells']:
            logical=unit_root/'cells'/cell['cell_id'];path=Path(resolve(str(logical)))
            if path in seen:raise ValueError('Duplicate continuation cell')
            seen.add(path)
            if not path.exists():pending_seen=True;pending.append(cell);continue
            if pending_seen:raise ValueError('Prior continuation is not an ordered prefix')
            if not (path/'terminal.json').is_file():raise ValueError('Unsealed prior continuation cell')
            terminal=local(logical/'terminal.json');outcome=load(terminal['outcome']);score=load(terminal['score'])
            evidence.extend((terminal['outcome'],terminal['score']))
            if (terminal['cell_id']!=cell['cell_id'] or outcome['method']!=cell['method'] or
                outcome['request_sha256']!=cell['request']['sha256'] or score['receipt_sha256']!=terminal['outcome']['sha256'] or
                score['reference_sha256']!=cell['reference']['sha256']):raise ValueError('Prior terminal identity differs')
            if 'query_loss' in terminal:
                loss=load(terminal['query_loss']);evidence.append(terminal['query_loss'])
                if loss['receipt_sha256']!=terminal['outcome']['sha256'] or loss['oracle_sha256']!=cell['oracle']['sha256']:
                    raise ValueError('Prior query-loss identity differs')
            for k in first.USAGE_FIELDS:
                v=outcome.get(k)
                if v is None:
                    if outcome.get('model_calls')!=0:original_spent['unknown_model_usage']=True
                else:original_spent[k]+=v
            original_spent['sealed_cells']+=1
            try:current=_usage(outcome)
            except ValueError:
                correction=recover_usage(outcome,cell,logical,load=load,resolve=resolve)
                correction.update(unit_id=unit['unit_id'],outcome=terminal['outcome'])
                corrections.append(correction);evidence.extend(correction['evidence']);current=correction['usage']
            for k in first.USAGE_FIELDS:spent[k]+=current[k]
            spent['sealed_cells']+=1
            if cell['method']=='aruqula-fedx':first.require_closed(local(logical/'external-services/closed.json'))
        if pending:pending_units.append(dict(unit=unit,manifest=manifest,pending_cells=pending))
    actual=set(Path(resolve(str(root))).glob('units/*/cells/*'))
    actual_units={p.name for p in Path(resolve(str(root))).glob('units/*')}
    if actual-seen or actual_units-{u['unit_id'] for u in cfg['units']}:
        raise ValueError('Unexpected prior continuation membership')
    reported_cumulative=dict(original_spent)
    for k in (*first.USAGE_FIELDS,'sealed_cells'):reported_cumulative[k]+=parent['usage'][k]
    if (overall.get('new_usage')!=original_spent or overall.get('parent_usage')!=parent['usage'] or
            overall.get('cumulative_usage')!=reported_cumulative):
        raise ValueError('Prior usage summary does not match immutable cells')
    if len(corrections)!=1:raise ValueError('This recovery requires exactly the one proven missing-accounting cell')
    inherited=dict(spent)
    for k in (*first.USAGE_FIELDS,'sealed_cells'):inherited[k]+=parent['usage'][k]
    remaining=sum(len(x['pending_cells']) for x in pending_units)
    if inherited['sealed_cells']+remaining!=216 or not remaining:raise ValueError('Not a strict complete-study suffix')
    return dict(parent=parent,first_contract=first_contract,first_config=cfg,evidence_pins=evidence,
        inherited_usage=inherited,first_usage_original=original_spent,first_usage_reconciled=spent,
        corrections=corrections,units=pending_units,remaining_cells=remaining,first_elapsed_seconds=elapsed)


def prepare(*,parent_release,first_contract,output,source_commit,prior_allocations_seconds,
            recovery_wall_seconds=None,mapper=None,repo=REPO):
    checked=inspect_chain(parent_release,first_contract,mapper=mapper,repo=repo)
    budget=checked['parent']['release']['budget']
    if (not isinstance(prior_allocations_seconds,list) or len(prior_allocations_seconds)!=2 or
        any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in prior_allocations_seconds)):
        raise ValueError('Two explicit observed positive prior allocation durations required')
    if (prior_allocations_seconds[0]!=checked['first_config']['prior_allocation_seconds'] or
            prior_allocations_seconds[1]<checked['first_elapsed_seconds']):
        raise ValueError('Prior allocation duration understates pinned ancestor accounting')
    maximum=budget['total_wall_seconds']-sum(prior_allocations_seconds)
    wall=maximum if recovery_wall_seconds is None else recovery_wall_seconds
    if type(wall) not in (int,float) or not math.isfinite(wall) or not 0<wall<=maximum:
        raise ValueError('Recovery would reset or exceed the cumulative active allocation budget')
    source=migration(repo,checked['parent']['source_commit'],source_commit)
    root=Path(output).resolve()
    for old in (checked['parent']['release']['output_root'],checked['first_config']['output_root']):
        old=Path((mapper or Path)(old)).resolve()
        if root==old or root in old.parents or old in root.parents:raise ValueError('Recovery output overlaps old evidence')
    root.mkdir(parents=True,exist_ok=False)
    correction=write_once(root/'reconciliation.json',dict(schema_version='xgap-model-accounting-reconciliation-v1',
        first_contract=first_contract,corrections=checked['corrections'],
        original_usage=checked['first_usage_original'],reconciled_usage=checked['first_usage_reconciled'],
        original_outcomes_preserved=True,model_calls=0,backend_calls=0))
    units=[]
    for item in checked['units']:
        manifest=deepcopy(item['manifest']);manifest['cells']=item['pending_cells'];unit=item['unit']
        ref=write_once(root/(unit['unit_id']+'-manifest.json'),manifest)
        units.append(dict(unit_id=unit['unit_id'],dataset=unit['dataset'],deployment=unit['deployment'],manifest=ref))
    return write_once(root/'continuation.json',dict(schema_version=SCHEMA,parent_release=parent_release,
        first_contract=first_contract,source_commit=source_commit,source_migration=source,
        parent_evidence=checked['parent']['evidence_pins'],first_evidence=checked['evidence_pins'],
        reconciliation=correction,prior_usage=checked['inherited_usage'],units=units,
        remaining_cells=checked['remaining_cells'],output_root=str(root/'results'),original_budget=budget,
        prior_allocations_seconds=prior_allocations_seconds,recovery_wall_seconds=wall,
        wall_policy='cumulative active allocation <= original allowance; repair handoff wait excluded explicitly',
        max_cells_per_source_session=checked['parent']['release']['max_cells_per_source_session'],
        automatic_retries=0,prepared_only=True,model_calls=0,backend_calls=0,submitted_jobs=0))


def execute(contract_pin):
    from run_bounded_joint_batch import run,source_commit
    from run_ch6_formal_campaign import usage,package_bytes
    from run_ch6_small_study import stop_reason
    from xgap.experiments.ch6_small_release import audit
    load,_=first.reader();cfg=load(contract_pin)
    if cfg.get('schema_version')!=SCHEMA or source_commit()!=cfg['source_commit']:
        raise ValueError('Current continuation source/contract differs')
    checked=inspect_chain(cfg['parent_release'],cfg['first_contract'])
    release=checked['parent']['release'];correction=load(cfg['reconciliation'])
    if (cfg['prior_usage']!=checked['inherited_usage'] or cfg['parent_evidence']!=checked['parent']['evidence_pins'] or
        cfg['first_evidence']!=checked['evidence_pins'] or correction['corrections']!=checked['corrections'] or
        cfg['original_budget']!=release['budget'] or cfg['remaining_cells']!=checked['remaining_cells'] or
        cfg['automatic_retries']!=0 or cfg['max_cells_per_source_session']!=release['max_cells_per_source_session']):
        raise ValueError('Ancestor evidence, accounting, membership or budgets changed')
    if not audit(release)['success']:raise ValueError('Original source/input audit failed')
    if migration(REPO,release['source_commit'],cfg['source_commit'])!=cfg['source_migration']:
        raise ValueError('Source migration differs')
    prior=cfg['prior_allocations_seconds'];wall=cfg['recovery_wall_seconds']
    if (not isinstance(prior,list) or len(prior)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in [*prior,wall]) or
        sum(prior)+wall>release['budget']['total_wall_seconds']):raise ValueError('Cumulative wall budget reset')
    if prior[0]!=checked['first_config']['prior_allocation_seconds'] or prior[1]<checked['first_elapsed_seconds']:
        raise ValueError('Prior allocation duration understates pinned ancestor accounting')
    if len(cfg['units'])!=len(checked['units']):raise ValueError('Remaining unit membership differs')
    for given,item in zip(cfg['units'],checked['units']):
        expected=deepcopy(item['manifest']);expected['cells']=item['pending_cells']
        if given['unit_id']!=item['unit']['unit_id'] or load(given['manifest'])!=expected:
            raise ValueError('Untouched query order, frozen inputs or budgets changed')
    if not os.environ.get('XGAP_EXTERNAL_LLM_API_KEY'):raise ValueError('Model credential unavailable')
    root=Path(cfg['output_root']).resolve()
    ancestors=[Path(release['output_root']),Path(checked['first_config']['output_root'])]
    for old in ancestors:
        old=old.resolve()
        if root==old or root in old.parents or old in root.parents:raise ValueError('Output overlaps ancestor')
    root.mkdir(parents=True,exist_ok=False)
    with (root/'.continuation.lock').open('x') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);started=time.monotonic()
        write_once(root/'identity.json',dict(contract=contract_pin,source_commit=cfg['source_commit'],started_unix=time.time()))
        status='all_unattempted_requests_processed';error=None;invocations=[]
        def cumulative(new=None):
            result=dict(usage(root) if new is None else new)
            for k in (*first.USAGE_FIELDS,'sealed_cells'):result[k]+=cfg['prior_usage'][k]
            return result
        try:
            for unit in cfg['units']:
                manifest=load(unit['manifest']);design=manifest['design'];target=root/'units'/unit['unit_id']
                external_cap=load(manifest['external_runtime'])['model_budget']['max_calls'] if manifest.get('external_runtime') else 0
                def before(cell):
                    reason=stop_reason(cumulative(),cfg['original_budget'],remaining_seconds=wall-(time.monotonic()-started),
                        needed_seconds=design['method_wall_seconds']+2*design['startup_seconds'],
                        next_call_cap=external_cap if cell['method']=='aruqula-fedx' else 1)
                    if reason:return reason
                    own=package_bytes(target) if target.exists() else 0
                    if sum(package_bytes(p) for p in ancestors)+package_bytes(root)-own+design['package_max_bytes']>cfg['original_budget']['package_max_bytes']:
                        return 'continuation_package_budget'
                    return None
                while True:
                    current=usage(root)
                    if current['unknown_model_usage'] or current['unsealed_cells']:status='accounting_incomplete';break
                    pending=[c for c in manifest['cells'] if not (target/'cells'/c['cell_id']).exists()]
                    if not pending:break
                    reason=before(pending[0])
                    if reason:status=reason;break
                    result=run(manifest_path=unit['manifest']['path'],manifest_sha256=unit['manifest']['sha256'],
                        output=target,max_new_cells=min(len(pending),cfg['max_cells_per_source_session']),before_cell=before)
                    invocations.append(result.get('receipt'))
                    if result['status']!='returned' or not result['new_cells']:
                        status=result.get('budget_status') or 'continuation_'+result['status'];break
                if status!='all_unattempted_requests_processed':break
        except (Exception,KeyboardInterrupt) as exc:
            status='continuation_supervisor_failure';error=dict(type=type(exc).__name__,message=str(exc))
        new=usage(root)
        if new['unknown_model_usage'] or new['unsealed_cells']:status='accounting_incomplete'
        elif status=='all_unattempted_requests_processed' and new['sealed_cells']!=cfg['remaining_cells']:status='continuation_incomplete_membership'
        result=dict(schema_version=SCHEMA,status=status,error=error,contract=contract_pin,parent_usage=cfg['prior_usage'],
            new_usage=new,cumulative_usage=cumulative(new),reconciliation=cfg['reconciliation'],invocations=invocations,
            elapsed_seconds=time.monotonic()-started,wall_policy=cfg['wall_policy'],automatic_retries=0,formal_campaign_ready=False)
        result['receipt']=write_once(root/'receipt.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract-path',required=True);parser.add_argument('--contract-sha256',required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    ref=dict(path=args.contract_path,sha256=args.contract_sha256)
    cfg=first.reader()[0](ref)
    result=execute(ref) if args.execute else dict(action='inspect_only',remaining_cells=cfg['remaining_cells'],model_calls=0,backend_calls=0)
    print(json.dumps(result))
    if args.execute and result['status']!='all_unattempted_requests_processed':raise SystemExit(2)
