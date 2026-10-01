"""Frozen authored intent tasks on FinBench facts, independently scored from CSV.

No model or method outcome participates in selection. Nonempty/empty reference
stratification is intentional and disclosed; this is not a population estimate.
"""
from copy import deepcopy
from dataclasses import asdict
from itertools import product
import json
from pathlib import Path
import time

from xgap.agent.intent_certificate import IntentCandidate, IntentFamily, IntentSlot, fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.intent_user import private_family_intent
from xgap.experiments.campaign_schedule import balanced_orders
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once


METHODS={
    'search_exact':('xgap-nl-family-exact','0'),
    'full':('xgap-nl-family-full','0'),
    'search_025':('xgap-nl-family-performance','1/4'),
    'fixed_025':('xgap-nl-family-fixed','1/4'),
    'search_050':('xgap-nl-family-performance','1/2'),
    'fixed_050':('xgap-nl-family-fixed','1/2'),
}
NORMALIZATION={'schema_version':'xgap-row-normalization-v1','fields':{
    'other_id':'text','account_distance':'integer','medium_id':'text','medium_type':'text'}}


def family_for(anchor, lower, upper, scenario, snapshot):
    """Same path skeleton; no answer rows, choices or execution cost in family."""
    ref=lambda v,p:{'var':v,'property':p}
    q=dict(nodes=[{'var':v,'type':'XGAPFinBench'+kind,'entity':None}
        for v,kind in [('start','Account'),('other','Account'),('medium','Medium')]],
        edges=[dict(var='signin',type='SIGNED_IN_TO',source='medium',target='other')],
        path=dict(var='reach',type='TRANSFERRED_TO',source='start',target='other',min_hops=1,max_hops=2,
            mode='ACYCLIC',time=dict(property='createTime',lower=lower,upper=upper,
                lower_inclusive=True,upper_inclusive=True,increasing=True)),
        where=[dict(left=ref(v,p),op='eq',right={'value':value},value_type='scalar')
            for v,p,value in [('medium','isBlocked',True),('start','id',str(anchor))]],
        select={k:ref(v,p) for k,v,p in [('other_id','other','id'),('account_distance','reach','length'),
            ('medium_id','medium','id'),('medium_type','medium','mediumType')]},deduplicate_by=None,
        order_by=[{'field':f,'direction':'asc'} for f in ('account_distance','other_id','medium_id')],limit=None)
    if scenario=='near_cluster':
        slots=(IntentSlot('hops',('path','max_hops')),IntentSlot('lower_inclusive',('path','time','lower_inclusive')),
            IntentSlot('upper_inclusive',('path','time','upper_inclusive')),IntentSlot('path_semantics',('path','mode')))
        queries=[q]
        for slot,value in zip(slots,(1,False,False,'WALK')):
            changed=deepcopy(q);parent=changed
            for key in slot.path[:-1]:parent=parent[key]
            parent[slot.path[-1]]=value;queries.append(changed)
    elif scenario in ('partial_information','hard_confirmation','cheap_full'):
        hard=scenario=='hard_confirmation'
        slots=(IntentSlot('lower_inclusive',('path','time','lower_inclusive'),hard=hard),
            IntentSlot('upper_inclusive',('path','time','upper_inclusive'),hard=hard),
            IntentSlot('hops',('path','max_hops'),weight=2,hard=hard))
        queries=[]
        for low,high,hops in product((False,True),(False,True),(1,2)):
            changed=deepcopy(q);changed['path']['max_hops']=hops
            changed['path']['time'].update(lower_inclusive=low,upper_inclusive=high);queries.append(changed)
    else:raise ValueError('Unknown frozen scenario')
    return IntentFamily('policy-study-'+scenario,tuple(IntentCandidate.create('q'+str(i),q)
        for i,q in enumerate(queries)),slots,snapshot,'authored exhaustive intent family; hidden user restricted to this family')


def csv_reference(data, query):
    """Independent directed temporal DFS over original source records; max depth2."""
    path=query['path'];window=path['time']
    if path['max_hops'] not in (1,2) or path['mode'] not in ('ACYCLIC','WALK') or not window['increasing']:
        raise ValueError('Reference scope is fixed temporal depth1..2')
    anchor=query['where'][1]['right']['value'];rows=set()
    def visit(node,visited,last,depth):
        if depth>=path['max_hops']:return
        for t in data.outgoing.get(node,()):
            if (t.create_time<window['lower'] or t.create_time==window['lower'] and not window['lower_inclusive']
                or t.create_time>window['upper'] or t.create_time==window['upper'] and not window['upper_inclusive']
                or last is not None and t.create_time<=last
                or path['mode']=='ACYCLIC' and t.to_id in visited):continue
            for medium in data.media_by_account.get(t.to_id,()):
                if data.media[medium]['isBlocked']=='true':rows.add((t.to_id,depth+1,medium,data.media[medium]['mediumType']))
            visit(t.to_id,visited|{t.to_id},t.create_time,depth+1)
    visit(anchor,{anchor},None,0)
    return [dict(zip(('other_id','account_distance','medium_id','medium_type'),row))
        for row in sorted(rows,key=lambda row:(row[1],row[0],row[2]))]


def information_for(design, scenario, index):
    kw=design['third_case_budget'][scenario] if index==2 else {}
    return FamilyInformationPolicy(cost_basis='interactions' if scenario=='cheap_full' else 'disclosed_coordinates',**kw)


def release(*,design_path,archive,lock_path,parent_release,output,excluded_selection,excluded_primary):
    started=time.perf_counter();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    design=json.loads(Path(design_path).read_text())
    if (design['schema_version']!='xgap-family-policy-study-design-v1' or design['cases_per_scenario']!=4 or
            design['nonempty_per_scenario']!=3 or design['methods']!=list(METHODS)):
        raise ValueError('Unexpected frozen design')
    def pin(path):
        import hashlib
        path=Path(path).resolve();return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    input_pins={k:pin(p) for k,p in dict(design=design_path,lock=lock_path,parent=parent_release,
        excluded_selection=excluded_selection,excluded_primary=excluded_primary).items()}
    write_once(root/'intent.json',dict(inputs=input_pins,design=design,reference_stratification=True,
        method_output_reads=0,model_calls=0,backend_calls=0))
    parent=json.loads(read_pinned(input_pins['parent']['path'],input_pins['parent']['sha256']))
    profile_pin=parent['profiles']['native'];profile=FrozenOneShotProfile.load(profile_pin['path'],expected_sha256=profile_pin['sha256'])
    materialized=profile.materialize();doc,_,_,sources,backends,_,_=materialized
    snapshot=snapshot_identity(sources,backends,doc['source_schema'])
    lock=load_finbench_artifact_lock(lock_path)
    data=load_finbench_query_data(archive,lock)
    if lock.artifact.digest_value!=doc['dataset']['version']:raise ValueError('Serving store and independent reference dataset differ')
    old=json.loads(Path(excluded_selection).read_text())['selected']
    primary=json.loads(Path(excluded_primary).read_text())['instances']
    excluded={p['parameters']['start_account_id'] for p in [*old,*primary] if 'start_account_id' in p['parameters']}
    selected=[];used=set(excluded);seed=design['seed']
    for scenario in design['scenarios']:
        for index in range(4):
            wanted_nonempty=index<3;size=5 if scenario=='near_cluster' else 8
            truth='q'+str(int(fingerprint([seed,scenario,index]),16)%size)
            prototype=family_for('selection-only',data.minimum_transfer_time,data.maximum_transfer_time,scenario,snapshot)
            template=json.loads(next(c.query_json for c in prototype.candidates if c.candidate_id==truth))
            pool=(a for a in data.accounts if a not in used and (bool(data.outgoing.get(a)) if wanted_nonempty else True))
            ranked=sorted(pool,key=lambda a:(fingerprint([seed,scenario,index,a]),a))
            chosen=None;examined=0
            for anchor in ranked:
                template['where'][1]['right']['value']=anchor
                rows=csv_reference(data,template);examined+=1
                if bool(rows)==wanted_nonempty:
                    family=family_for(anchor,data.minimum_transfer_time,data.maximum_transfer_time,scenario,snapshot)
                    chosen=(anchor,family,rows);break
            if chosen is None:raise ValueError('Declared reference stratum is unavailable; no silent replacement')
            anchor,family,rows=chosen;used.add(anchor)
            qid=f'FPS-{scenario}-{index+1:02}'
            question=(f'For account business ID {anchor}, list distinct reachable accounts and their blocked sign-in media '
                f'within {data.minimum_transfer_time} to {data.maximum_transfer_time}. Use the intended path-depth and '
                'time-boundary conventions from the declared choices; return other_id, account_distance, medium_id, '
                'medium_type ordered by distance and IDs. Resolve unspecified conventions through the scoped user when needed.')
            path=root/qid;path.mkdir()
            request=write_once(path/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
                question_id=qid,question=question,population=design['scope'],
                exposure='new anchor; authored known semantic families; reference-stratified; not unseen language'))
            oracle=write_once(path/'private-user.json',private_family_intent(family,question,truth))
            reference=write_once(path/'reference.json',dict(schema_version='xgap-normalized-row-reference-v1',
                question_id=qid,dataset=doc['dataset'],ordered=True,normalization=NORMALIZATION,rows=rows,
                derivation='independent depth-bounded DFS over pinned original SF0.1 CSV; no XGAP execution'))
            info=information_for(design,scenario,index);families={}
            for epsilon in design['performance_epsilons']:
                families[epsilon]=write_once(path/('family-'+epsilon.replace('/','-')+'.json'),dict(
                    schema_version='xgap-family-strong-profile-v1',question_sha256=fingerprint(question),family=family.to_dict(),
                    information_policy=asdict(info),search_limits=design['search_limits'],performance_epsilon=epsilon,
                    propose_with_model=False))
            selected.append(dict(question_id=qid,scenario=scenario,index=index,anchor=anchor,request=request,oracle=oracle,
                reference=reference,families=families,hidden_truth_for_scoring_only=truth,information=asdict(info),
                expected_nonempty=wanted_nonempty,reference_rows=len(rows),selection_candidates_examined=examined))
    orders=balanced_orders(list(METHODS));cells=[]
    for i,case in enumerate(selected):
        for position,label in enumerate(orders[i%len(orders)]):
            method,epsilon=METHODS[label];family_epsilon=epsilon if epsilon!='0' else '1/2'
            cells.append(dict(cell_id=f'first-{i:02}-{position}',round='first',group_index=i,method_position=position,
                label=label,method=method,epsilon=epsilon,question_id=case['question_id'],scenario=case['scenario'],
                request=case['request'],oracle=case['oracle'],family=case['families'][family_epsilon],reference=case['reference']))
    for i,case in enumerate(selected):
        if case['index']!=0:continue
        chosen=[label for label in reversed(orders[i%len(orders)]) if label in design['timing_repeat']['method_labels']]
        for position,label in enumerate(chosen):
            method,epsilon=METHODS[label]
            cells.append(dict(cell_id=f'repeat-{i:02}-{position}',round='repeat',group_index=i,method_position=position,
                label=label,method=method,epsilon=epsilon,question_id=case['question_id'],scenario=case['scenario'],
                request=case['request'],oracle=case['oracle'],family=case['families']['1/2'],reference=case['reference']))
    if len(cells)!=design['maximum_cells']:raise ValueError('Schedule denominator differs')
    return write_once(root/'release.json',dict(schema_version='xgap-family-policy-study-release-v1',inputs=input_pins,
        design=design,dataset=doc['dataset'],profile=profile_pin,prepared=parent['prepared']['native'],cases=selected,cells=cells,
        archive_sha256=lock.artifact.digest_value,excluded_anchor_count=len(excluded),unique_questions=len(selected),
        first_pass_cells=96,repeat_cells=16,offline_release_ms=(time.perf_counter()-started)*1000,
        method_runs=0,model_calls=0,backend_calls=0,external_baselines=0))
