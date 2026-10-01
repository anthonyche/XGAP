#!/usr/bin/env python3
"""Freeze the approved dual-frame NL primary comparison before any answers.

Other Chapter 7 sweeps and matched-RDF baselines need their own admitted releases.
This publisher does not run a model/backend or replace a failed pilot record.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import time

from run_bounded_joint_batch import source_commit, validate
from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_contract import METHODS, configuration
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.chapter7_finbench_families import TEMPLATES, make_family, reference_rows
from xgap.experiments.chapter7_finbench_pilot import windows
from xgap.experiments.chapter7_finbench_strata import structural_frames, select_families, STRATA, SEED
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.external_federation import deadline
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once


def execution_order(selection):
    """Balance first mode per shape/frame, interleave frames independently of truth."""
    rows=selection['selected'];count=selection['per_shape']
    if count%2:raise ValueError('Even per-shape count required for balanced first mode')
    orders={}
    for stratum in STRATA:
        for template in TEMPLATES:
            indices=[r['index'] for r in rows if r['stratum']==stratum and r['template']==template]
            first=[list(METHODS)]*(count//2)+[list(reversed(METHODS))]*(count//2)
            random.Random(fingerprint([SEED,'method-order',stratum,template])).shuffle(first)
            orders.update(zip(indices,first))
    indices=[r['index'] for r in rows]
    random.Random(fingerprint([SEED,'interleaved-cases'])).shuffle(indices)
    return [dict(index=i,methods=orders[i]) for i in indices]


def release(*, archive, lock_path, prepared_path, prepared_sha256, output):
    started=time.perf_counter();commit=source_commit()
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    (root/'private').mkdir();(root/'cases').mkdir()
    prepared_pin=dict(path=str(Path(prepared_path).resolve()),sha256=prepared_sha256)
    prepared=json.loads(read_pinned(prepared_path,prepared_sha256))
    profile_pin=prepared['profile']
    frozen=FrozenOneShotProfile.load(profile_pin['path'],expected_sha256=profile_pin['sha256'])
    doc,_,_,sources,backends,_,_=frozen.materialize()
    lock=load_finbench_artifact_lock(lock_path)
    if lock.artifact.digest_value!=doc['dataset']['version']:raise ValueError('Source/profile identity differs')
    if any(m['provider']['wire_profile']!='compact-graph-schema-v2' for m in doc['modes'].values()):
        raise ValueError('Compact-v2 profile required')
    data=load_finbench_query_data(archive,lock)
    frames=structural_frames(data.accounts,data.companies,data.transfers,data.company_by_account)
    frame_pin=write_once(root/'frames.json',frames)
    # The earlier offline constructor check used the lexically first typed IDs
    # outside the pilot sampler. Exclude these exposed families as well.
    selected=select_families(frames,per_shape=8,
        excluded=dict(account=(min(data.accounts),),company=(min(data.companies),)))
    order=execution_order(selected)
    time_windows=windows(data.minimum_transfer_time,data.maximum_transfer_time)
    selection=write_once(root/'private/selection.json',dict(**selected,source_commit=commit,
        frame=frame_pin,time_windows=time_windows,execution_order=order))
    protocol=file_pin(Path(__file__).resolve().parents[1]/'docs/decisions/chapter7_finbench_primary_freeze_20260921.md')
    config=write_once(root/'config.json',configuration(epsilon='1/2',
        limits=StrongSearchLimits(planning_ms=10000,improvement_actions=16)))
    snapshot=snapshot_identity(sources,backends,doc['source_schema'])
    cases=[];by_index={}
    for item in selected['selected']:
        i=item['index'];identifier=f'CH7-FB-F{i:02}'
        case_root=root/'cases'/identifier;case_root.mkdir()
        family,scope,question,normalization=make_family(item['template'],item['anchor'],
            *time_windows[item['window']],snapshot)
        truth=json.loads(family.candidates[item['truth_index']].query_json)
        request=write_once(case_root/'request.json',dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id=identifier,question=question,population='FinBench SF0.1 derived '+item['stratum'],
            exposure='formal fold; never used in Chapter 7 pilots; templates shared'))
        scope_pin=write_once(case_root/'scope.json',scope.to_dict())
        oracle=write_once(root/'private'/(identifier+'-user.json'),private_query_intent(question,truth,language_version='v2'))
        reference=write_once(root/'private'/(identifier+'-reference.json'),dict(
            schema_version='xgap-normalized-row-reference-v1',dataset=doc['dataset'],question_id=identifier,
            ordered=True,normalization=normalization,rows=reference_rows(data,item['template'],truth),
            derivation='independent original-CSV scan/DFS after sealing selection; no compiler/backend'))
        by_index[i]=dict(request=request,scope=scope_pin,oracle=oracle,reference=reference,config=config)
        cases.append(dict(question_id=identifier,template_family_id=item['template'],stratum=item['stratum'],
            family_group_id=item['family_group_id'],candidate_family_id=family.family_id,track='nl',
            window_id=item['window'],**by_index[i]))
    cells=[dict(cell_id=f"f{block['index']:02}-{position}-"+method.rsplit('-',1)[-1],method=method,
        **by_index[block['index']]) for block in order for position,method in enumerate(block['methods'])]
    design=dict(total_wall_seconds=7200,package_max_bytes=2*1024**3,free_disk_reserve_bytes=6*1024**3,
        method_wall_seconds=90,method_rss_bytes=1024**3,source_rss_bytes=2*1024**3,startup_seconds=120,
        source_budget=asdict(SourceObservationBudget(capture_compression='gzip',max_calls=64,
            request_bytes=1024**2,phase_request_bytes=16*1024**2,response_bytes=64*1024**2,
            phase_response_bytes=256*1024**2,timeout_seconds=20)))
    manifest=dict(schema_version='xgap-bounded-joint-batch-v1',deployment='native',prepared=prepared_pin,
        design=design,cells=cells)
    validate(manifest)
    batch=write_once(root/'batch.json',manifest)
    pin=write_once(root/'release.json',dict(schema_version='xgap-ch7-finbench-formal-v1',source_commit=commit,
        protocol=protocol,dataset=doc['dataset'],selection=selection,frames=frame_pin,prepared=prepared_pin,
        profile=profile_pin,source_lock=file_pin(lock_path),batch=batch,cases=cases,
        unique_anchor_groups=selected['distinct_anchor_groups'],base_case_records=48,cells=96,
        repetitions=1,maximum_new_model_calls=96,maximum_final_plans=96,
        formal_result=True,executed=False,panels=['E1','E2','E7','E8'],
        reporting='two sampling frames reported separately; native XGAP comparison only; external RDF comparison remains pending',
        automatic_retries=0,offline_release_ms=(time.perf_counter()-started)*1000))
    print(json.dumps(pin));return pin


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','lock-path','prepared-path','prepared-sha256','output'):p.add_argument('--'+name,required=True)
    with deadline(300):release(**vars(p.parse_args()))
