"""Frozen per-question strong profiles and one-group dispatch; no old campaign mutation."""
import json
from pathlib import Path
import time

from xgap.experiments.campaign_schedule import dispatch_one_group
from xgap.experiments.common_method_trial import run_practical_trial
from xgap.experiments.common_row_score import score_trial
from xgap.experiments.one_shot_profile import read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.practical_profile import FrozenPracticalProfile
from xgap.experiments.practical_records import publish_profile
from xgap.experiments.process_guard import ProcessBudget


SCHEMA='xgap-practical-study-input-v1'
METHODS=('xgap-strong-exact','xgap-strong-performance')


def _pin(raw,root):
    if (not isinstance(raw,dict) or not {'path','sha256'}<=set(raw) or set(raw)-{'path','sha256','bytes'} or
            not isinstance(raw['path'],str) or not raw['path'] or
            not isinstance(raw['sha256'],str) or len(raw['sha256'])!=64 or
            any(c not in '0123456789abcdef' for c in raw['sha256'])):
        raise ValueError('Explicit path and exact SHA-256 pin required')
    return {'path':str((root/raw['path']).resolve()),'sha256':raw['sha256']}


def freeze_study(*,input_path,input_sha256,output):
    """Freeze declared input cells; do not read gold answers or invoke any tool."""
    origin=Path(input_path).resolve().parent
    raw=json.loads(read_pinned(input_path,input_sha256))
    if (set(raw)!={'schema_version','study_id','groups'} or raw['schema_version']!=SCHEMA or
            not isinstance(raw['study_id'],str) or not raw['study_id'] or
            not isinstance(raw['groups'],list) or not 1<=len(raw['groups'])<=128):
        raise ValueError('Expected a named practical study with1..128 explicit groups')
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    cells=[];seen=set();dataset=source_contract=None;profiles={}
    for index,group in enumerate(raw['groups']):
        if not isinstance(group,dict) or set(group)!={'request','profile','reference'}:
            raise ValueError('Each group requires request/profile/post-seal reference pins')
        request,profile,reference=(_pin(group[k],origin) for k in ('request','profile','reference'))
        identity=(profile['path'],profile['sha256'])
        if identity not in profiles:
            published=publish_profile(profile_path=profile['path'],profile_sha256=profile['sha256'],
                output=root/f'profile-{len(profiles):03}.json')
            obj,cfg=FrozenPracticalProfile.load_materialized(published['path'],expected_sha256=published['sha256'])
            profiles[identity]=(published,obj,cfg)
        published,obj,cfg=profiles[identity];doc=cfg[0]
        current={'sources':doc['sources'],'backends':doc['backends']}
        if dataset is None:dataset=doc['dataset'];source_contract=current
        if doc['dataset']!=dataset or current!=source_contract:
            raise ValueError('One study needs the same dataset and source/client contracts')
        question=json.loads(read_pinned(request['path'],request['sha256']))
        if question['question_id'] in seen:raise ValueError('Question groups must have distinct IDs')
        seen.add(question['question_id'])
        for mode in ('exact','performance'):
            obj.prepare(question,request_sha256=request['sha256'],request_root=Path(request['path']).parent,
                mode=mode,materialized=cfg)
        # Preserve the declared group order. Alternate mode order before outcomes.
        for position,method in enumerate(METHODS if index%2==0 else tuple(reversed(METHODS))):
            cells.append({'cell_id':f'trusted-template-00-{index:03}-{position}','block':0,
                'group_index':index,'method_position':position,'method':method,'track':'trusted_template',
                'question_id':question['question_id'],'population':question['population'],'exposure':question['exposure'],
                'request':request,'practical_profile':published,'reference_for_post_seal_scoring_only':reference})
    return write_once(root/'schedule.json',{'schema_version':'xgap-balanced-campaign-schedule-v1',
        'profile_kind':'practical_per_question_v1','deployment':'caller_owned_practical','study_id':raw['study_id'],
        'input':{'path':str(Path(input_path).resolve()),'sha256':input_sha256},'dataset':dataset,
        'track':'trusted_template','methods':list(METHODS),'groups':len(seen),'blocks':1,'cells':cells,
        'order_design':'declared group order; alternating two-mode order; frozen before outcomes',
        'maximum_top_level_method_attempts':len(cells),'automatic_retries':0,
        'reference_answers_read':False,'paper_result':False,'formal_campaign_ready':False,
        'scope':'new explicit strong-study mapping; no replacement of old NL/RDF schedules'})


def _deployment(declared,supplied,observer_url):
    """A provider may relocate pins/endpoints; it cannot change method inputs."""
    pin=_pin(supplied,Path('.').resolve())
    original=json.loads(read_pinned(declared['path'],declared['sha256']))
    current=json.loads(read_pinned(pin['path'],pin['sha256']))
    if not isinstance(observer_url,str) or any(s['client']['url']!=observer_url for s in current['backends'].values()):
        raise ValueError('Every deployed source must use the owned observation boundary')
    # Compare semantic/configuration values, allowing endpoint-only deployment and
    # explicit offline deployment provenance. Published dependency paths are fixed.
    for doc in (original,current):
        doc.pop('offline',None)
        for spec in doc['backends'].values():spec['client'].pop('url',None)
    if current!=original:raise ValueError('Deployment changed frozen practical inputs beyond endpoints')
    return pin


def dispatch_practical_group(*,schedule_path,schedule_sha256,ledger,owned_services,observer,
        deployment_for,ready=lambda cell:{'ready':True},budget=ProcessBudget()):
    """Run at most one group on caller-owned serving sources, with no retry.

    The caller owns startup/closing. Failed common trials retire sources and stop
    the rest of this dispatch; later calls may use a new owned serving session.
    Reference pins reach only the scorer, after a sealed method outcome.
    """
    schedule=json.loads(read_pinned(schedule_path,schedule_sha256))
    if (schedule.get('schema_version')!='xgap-balanced-campaign-schedule-v1' or
            schedule.get('profile_kind')!='practical_per_question_v1' or schedule.get('track')!='trusted_template' or
            schedule.get('methods')!=list(METHODS) or
            any(c.get('track')!='trusted_template' or c.get('method') not in METHODS for c in schedule.get('cells',[]))):
        raise ValueError('Expected an explicit practical per-question schedule')
    halted=False;deployed={};starts={};preparation={}
    def check(cell):
        if halted:return {'ready':False,'reason':'previous_method_requires_new_serving_session'}
        starts[cell['cell_id']]=time.perf_counter()
        public={k:v for k,v in cell.items() if k!='reference_for_post_seal_scoring_only'}
        state=ready(public)
        if not state['ready']:return state
        supplied=deployment_for(public)
        deployed[cell['cell_id']]=_deployment(cell['practical_profile'],supplied,getattr(observer,'base_url',None))
        preparation[cell['cell_id']]=(time.perf_counter()-starts[cell['cell_id']])*1000
        return {**state,'profile':deployed[cell['cell_id']],'deployment_preparation_ms':preparation[cell['cell_id']]}
    def execute(cell,output):
        nonlocal halted
        request=cell['request'];profile=deployed[cell['cell_id']]
        result=run_practical_trial(request_path=request['path'],request_sha256=request['sha256'],
            profile_path=profile['path'],profile_sha256=profile['sha256'],method=cell['method'],output=output,
            owned_services=owned_services,observer=observer,budget=budget)
        halted=not result['can_continue_session']
        write_once(output/'study-timing.json',{'receipt':result['receipt'],
            'deployment_preparation_ms':preparation[cell['cell_id']],
            'common_online_ms':result['timing']['total_online_ms'],
            'study_online_ms_before_timing':(time.perf_counter()-starts[cell['cell_id']])*1000,
            'scope':'readiness and endpoint-profile validation plus journal intent and common trial; excludes this measurement file, scoring and journal terminal; serving startup owned by caller separately'})
        reference=cell['reference_for_post_seal_scoring_only']
        try:
            score_trial(result['receipt']['path'],receipt_sha256=result['receipt']['sha256'],
                reference_path=reference['path'],reference_sha256=reference['sha256'],output=output/'score.json')
        except Exception as error:
            write_once(output/'score-error.json',{'error_type':type(error).__name__,'error':str(error),'receipt':result['receipt']})
        return result['receipt']
    return dispatch_one_group(schedule_path=schedule_path,schedule_sha256=schedule_sha256,
        ledger=ledger,execute=execute,ready=check)
