"""Pre-answer sampling and release of a new grounded-family FinBench pilot.

Pure historical query construction/CSV reference functions are reused, not the
historical sampler, controller, scenarios, results or nonempty-answer strata.
"""
from dataclasses import asdict,replace
from datetime import datetime,timedelta
import json
from pathlib import Path
import random
import sys
import time

from xgap.agent.intent_certificate import IntentCandidate,fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_contract import METHODS,configuration
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.family_policy_study import family_for,csv_reference,NORMALIZATION
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_profile import FrozenOneShotProfile,read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.semantic.intent_scope import ScopePolicy,ScopeDomain

SEED='xgap-ch7-pilot-20260920-v1'
TEMPLATE='outgoing-temporal-path-blocked-signin-v1'


def split_group(anchor):
    # Every window/intent for this account stays together. Independent of outcomes.
    return 'pilot' if int(fingerprint([SEED,'anchor-fold',str(anchor)]),16)%5==0 else 'formal'


def sample_families(accounts,*,count=24,seed=SEED):
    """Uniform distinct pilot anchors, then uniform windows and 8 legal intents.

    Inputs contain account IDs only: answers, degree and method outcomes cannot
    participate. Templates are shared; no unseen-template claim is made.
    """
    pool=sorted(str(a) for a in accounts if split_group(a)=='pilot')
    if len(set(pool))!=len(pool) or len(pool)<count:raise ValueError('Distinct pilot anchor frame is too small')
    rng=random.Random(seed)
    return [dict(index=i,anchor=a,window=rng.randrange(4),truth_index=rng.randrange(8),
        track='nl' if i%2==0 else 'controlled',method_order=list(METHODS) if (i//2)%2==0 else list(reversed(METHODS)),
        family_group_id=fingerprint(['finbench-sf0.1',a])) for i,a in enumerate(rng.sample(pool,count))]


def windows(lower,upper):
    low=datetime.fromisoformat(lower);high=datetime.fromisoformat(upper)
    millis=(high-low)//timedelta(milliseconds=1)
    if millis<4:raise ValueError('Snapshot time span is too short for four fixed windows')
    points=[low+timedelta(milliseconds=millis*i//4) for i in range(5)]
    return [(a.isoformat(sep=' ',timespec='milliseconds'),b.isoformat(sep=' ',timespec='milliseconds'))
            for a,b in zip(points,points[1:])]


def make_family(anchor,lower,upper,snapshot):
    base=family_for(anchor,lower,upper,'partial_information',snapshot)
    candidates=[]
    for candidate in base.candidates:
        query=json.loads(candidate.query_json);query['contribution_by']=query.pop('deduplicate_by')
        candidates.append(IntentCandidate.create(candidate.candidate_id,query))
    family=replace(base,family_id=fingerprint([TEMPLATE,str(anchor),lower,upper]),
        candidates=tuple(candidates),coverage_basis=None,language_version='v2')
    domains=[]
    for j,slot in enumerate(family.slots):
        values=tuple(json.loads(v) for v in sorted({values[j] for values in family.values}))
        domains.append(ScopeDomain(slot,values))
    return family,ScopePolicy('ch7-finbench-path-window-v1',tuple(domains),language_version='v2')


def question(anchor,lower,upper):
    return (f'For account with business ID {anchor}, list distinct reachable accounts and their blocked sign-in media. '
        'Follow outgoing money transfers along acyclic paths, with strictly increasing transfer createTime '
        f'between {lower} and {upper}. Paths start at one hop; the maximum depth (one or two) and whether '
        'each time boundary is inclusive are unspecified conventions to clarify with the user if needed. '
        'Include each reachable account and path length with each medium that signed in to that account and '
        'has isBlocked=true. Different paths with the same endpoint and length count once per medium. '
        'Return other_id, account_distance, medium_id, medium_type, ordered by account_distance, other_id, '
        'medium_id ascending, without a result limit.')


def release(*,archive,lock_path,prepared_path,prepared_sha256,output,source_commit):
    started=time.perf_counter();root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    (root/'private').mkdir();(root/'cases').mkdir()
    prepared_pin=dict(path=str(Path(prepared_path).resolve()),sha256=prepared_sha256)
    prepared=json.loads(read_pinned(prepared_path,prepared_sha256));profile_pin=prepared['profile']
    frozen=FrozenOneShotProfile.load(profile_pin['path'],expected_sha256=profile_pin['sha256'])
    doc,_,_,sources,backends,_,_=frozen.materialize()
    lock=load_finbench_artifact_lock(lock_path)
    if lock.artifact.digest_value!=doc['dataset']['version']:raise ValueError('Dataset/profile source mismatch')
    if any(mode['provider']['wire_profile']!='compact-graph-schema-v2' for mode in doc['modes'].values()):
        raise ValueError('Pilot language must match the frozen compact-v2 profile')
    data=load_finbench_query_data(archive,lock)
    selection=sample_families(data.accounts);time_windows=windows(data.minimum_transfer_time,data.maximum_transfer_time)
    # This durable selection predates every reference answer and method outcome.
    selection_pin=write_once(root/'private/selection.json',dict(schema_version='xgap-ch7-preanswer-selection-v1',
        source_commit=source_commit,seed=SEED,python_version=sys.version,accounts_in_frame=len(data.accounts),pilot_pool=sum(split_group(a)=='pilot' for a in data.accounts),
        time_windows=time_windows,selected=selection,answer_reads_at_selection=0,method_output_reads=0,
        unit='grounded query family; all windows and intents sharing an anchor have one fold',
        shared_template=TEMPLATE,unseen_template_generalization=False))
    config=write_once(root/'config.json',configuration(epsilon='1/2',limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16)))
    snapshot=snapshot_identity(sources,backends,doc['source_schema']);cells=[];cases=[]
    for item in selection:
        i=item['index'];identifier=f'CH7-FB-P{i:02}';path=root/'cases'/identifier;path.mkdir()
        lower,upper=time_windows[item['window']];family,scope=make_family(item['anchor'],lower,upper,snapshot)
        q=question(item['anchor'],lower,upper);truth=json.loads(family.candidates[item['truth_index']].query_json)
        request=write_once(path/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',question_id=identifier,
            question=q,population='FinBench SF0.1 derived grounded-family uniform pilot',
            exposure='development; anchor-family disjoint from reserved formal pool; template shared'))
        scope_pin=write_once(path/'scope.json',scope.to_dict())
        oracle=write_once(root/'private'/(identifier+'-user.json'),private_query_intent(q,truth,language_version='v2'))
        reference=write_once(root/'private'/(identifier+'-reference.json'),dict(schema_version='xgap-normalized-row-reference-v1',
            dataset=doc['dataset'],question_id=identifier,ordered=True,normalization=NORMALIZATION,rows=csv_reference(data,truth),
            derivation='independent directed temporal DFS over pinned original SF0.1 CSV; no model/compiler/backend execution'))
        state={}
        if item['track']=='controlled':
            choices=[dict(name=s.name,type='path_depth' if s.name=='hops' else 'time_boundary',slots=[s.name]) for s in family.slots]
            state['controlled_state']=write_once(path/'state.json',publish_state(q,family,truth,clue_names=('hops',),semantic_choices=choices))
        for position,method in enumerate(item['method_order']):
            cells.append(dict(cell_id=f'p{i:02}-{position}-'+method.rsplit('-',1)[-1],method=method,request=request,
                scope=scope_pin,oracle=oracle,config=config,reference=reference,**state))
        cases.append(dict(question_id=identifier,template_family_id=TEMPLATE,family_group_id=item['family_group_id'],
            candidate_family_id=family.family_id,track=item['track'],window_id=item['window'],
            request=request,scope=scope_pin,oracle=oracle,reference=reference,**state))
    design=dict(total_wall_seconds=7200,package_max_bytes=3*1024**3,free_disk_reserve_bytes=6*1024**3,
        method_wall_seconds=90,method_rss_bytes=1024**3,source_rss_bytes=2*1024**3,startup_seconds=120,
        source_budget=asdict(SourceObservationBudget(max_calls=64,request_bytes=1024**2,phase_request_bytes=16*1024**2,
            response_bytes=64*1024**2,phase_response_bytes=256*1024**2,timeout_seconds=20,capture_compression='gzip')))
    batch=write_once(root/'batch.json',dict(schema_version='xgap-bounded-joint-batch-v1',deployment='native',
        prepared=prepared_pin,design=design,cells=cells))
    return write_once(root/'release.json',dict(schema_version='xgap-ch7-finbench-pilot-v1',source_commit=source_commit,
        dataset=doc['dataset'],selection=selection_pin,source_lock=file_pin(lock_path),archive_sha256=lock.artifact.digest_value,
        prepared=prepared_pin,profile=profile_pin,batch=batch,cases=cases,unique_base_cases=24,cells=48,
        maximum_new_model_calls=24,maximum_final_plans=48,formal_result=False,
        selection_uses_answer_nonemptiness=False,template_generalization_claim=False,
        offline_release_ms=(time.perf_counter()-started)*1000))
