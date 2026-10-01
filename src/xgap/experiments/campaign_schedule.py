"""Freeze balanced cells and dispatch each at most once, independent of answers."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once

METHODS={'natural_language':('xgap-precision','xgap-performance','fedx','fedup'),
         'fixed_semantics':('xgap-rdf','fedx','fedup')}


def balanced_orders(methods):
    """Williams rows: positions and first-order predecessors balanced per cycle."""
    n=len(methods);base=[0]
    for i in range(1,n):base.append((i+1)//2 if i%2 else n-i//2)
    rows=[tuple(methods[(v+k)%n] for v in base) for k in range(n)]
    return rows+[tuple(reversed(r)) for r in rows] if n%2 else rows


def freeze_schedule(*,population_path,population_sha256,profile_path,profile_sha256,track,output,deployment='rdf'):
    population=json.loads(read_pinned(population_path,population_sha256))
    profile=json.loads(read_pinned(profile_path,profile_sha256))
    if population.get('schema_version')!='xgap-finbench-one-shot-population-v1' or population['dataset']!=profile['dataset']:
        raise ValueError('Frozen population and serving dataset must match')
    if deployment not in ('rdf','native'):raise ValueError('Unknown deployment')
    methods=(('xgap-precision','xgap-performance') if track=='natural_language' else ('xgap-native',)) if deployment=='native' else METHODS[track]
    blocks=1 if track=='natural_language' else 3
    groups=[g for g in population['artifacts'] if g['split']=='evaluation']
    if len(groups)!=48 or len({g['question_id'] for g in groups})!=48:raise ValueError('The frozen 48-group evaluation denominator is required')
    seed='xgap-formal-evaluation-order-v1'
    groups.sort(key=lambda g:hashlib.sha256((seed+':'+g['question_id']).encode()).hexdigest())
    orders=balanced_orders(methods);cells=[]
    for block in range(blocks):
        for i,group in enumerate(groups):
            order=orders[(block*len(groups)+i)%len(orders)]
            for position,method in enumerate(order):
                cell={'cell_id':f'{track}-{block:02}-{i:03}-{position}', 'block':block,'group_index':i,
                    'method_position':position,'method':method,'track':track,'question_id':group['question_id'],
                    'family':group['family'],'request':group['files']['request'],
                    'reference_for_post_seal_scoring_only':group['files']['reference']}
                if track=='fixed_semantics':cell['fixed_semantics_input']=group['files']['gold']
                cells.append(cell)
    receipt={'schema_version':'xgap-balanced-campaign-schedule-v1','population':{
        'path':str(Path(population_path).resolve()),'sha256':population_sha256},
        'profile':{'path':str(Path(profile_path).resolve()),'sha256':profile_sha256},
        'dataset':profile['dataset'],'track':track,'methods':list(methods),'blocks':blocks,'groups':48,
        'order_seed':seed,'order_design':'Williams rows; balanced position and directed adjacency over complete cycles',
        'cells':cells,'maximum_model_calls':len(cells) if track=='natural_language' else 0,
        'maximum_top_level_method_attempts':len(cells),'maximum_method_online_seconds':180*len(cells),
        'source_budget':asdict(SourceObservationBudget()),'outer_request_seconds':180,
        'method_rss_bytes':2*1024**3,'source_rss_bytes':2*1024**3,
        'execution_chunk':'at most one query group per dispatch call; same manifest/journal resumes without retries',
        'warmup_queries':0,'cache_policy':'retain healthy owned sessions; declare fresh initial/recovered sessions',
        'automatic_retries':0,'reference_or_method_outputs_read':False,
        'formal_campaign_ready':False,'remaining_gate':'pinned external summary, owned hosts and package controller'}
    if deployment=='native':
        receipt.update(deployment='native',remaining_gate='owned native serving copies and common controller',
            order_design='alternating two-mode order' if track=='natural_language' else 'one deterministic native method; same frozen question order')
    return write_once(output,receipt)


def dispatch_one_group(*,schedule_path,schedule_sha256,ledger,execute,ready):
    """Callbacks own live resources. A durable intent is never dispatched twice.

    Indeterminate prior intents are retained and skipped on resume. The controller
    must retire/reconcile their old sessions before reporting ready for a new cell.
    An unavailable prerequisite leaves the current and remaining cells unrun.
    """
    schedule=json.loads(read_pinned(schedule_path,schedule_sha256))
    if schedule.get('schema_version')!='xgap-balanced-campaign-schedule-v1':raise ValueError('Expected frozen campaign schedule')
    root=Path(ledger);root.mkdir(parents=True,exist_ok=True)
    identity={'path':str(Path(schedule_path).resolve()),'sha256':schedule_sha256}
    marker=root/'schedule.json'
    if marker.exists():
        if json.loads(marker.read_text())!=identity:raise ValueError('Cannot mix schedules in one journal')
    else:write_once(marker,identity)
    seen=[];target=None
    for cell in schedule['cells']:
        path=root/cell['cell_id'];group=(cell['block'],cell['group_index'])
        if target is not None and group!=target:break
        if path.exists():
            seen.append({'cell_id':cell['cell_id'],'status':'already_sealed' if (path/'terminal.json').exists() else 'indeterminate_prior_intent'})
            continue
        target=group
        readiness=ready(cell)
        if not readiness.get('ready'):
            seen.append({'cell_id':cell['cell_id'],'status':'unrun_prerequisite','readiness':readiness});break
        path.mkdir(exist_ok=False)
        write_once(path/'intent.json',{'schedule':identity,'cell':cell,'readiness':readiness,'attempts':1})
        try:
            pin=execute(cell,path/'execution')
            outcome=json.loads(read_pinned(pin['path'],pin['sha256']))
            if any(outcome.get(k)!=cell[k] for k in ('method','question_id','track')):
                raise ValueError('Method outcome identity mismatch')
            terminal={'cell_id':cell['cell_id'],'status':'outcome_sealed','outcome':pin}
        except Exception as error:
            terminal={'cell_id':cell['cell_id'],'status':'dispatch_failed','error_type':type(error).__name__,
                      'error':str(error),'method_calls_unknown':True,'automatic_retries':0}
        write_once(path/'terminal.json',terminal);seen.append(terminal)
    return seen
