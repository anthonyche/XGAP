#!/usr/bin/env python3
"""Freeze six SF0.1 cases and 30 bounded cells before observing method results.

Three authored families, two source-only anchor strata; this is a feasibility
pilot, not the Chapter 6 template-disjoint evaluation or a FinBench official run.
"""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import random

from run_bounded_joint_batch import source_commit, UNIFIED_SCHEMA
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_strong import FamilyInformationPolicy
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits, Resources
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.ch6_direct import METHOD as DIRECT
from xgap.experiments.chapter7_finbench_families import TEMPLATES, make_family, reference_rows
from xgap.experiments.chapter7_finbench_coverage import fold
from xgap.experiments.compact_profile import derive_compact_contribution_profile
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.nl_strong_release import freeze_common_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration
from xgap.semantic.intent_scope import ScopePolicy, construct_scope

SEED = 'ch6-first-real-20260922-v1'
METHODS = ('xgap-unified-lookahead', 'xgap-unified-two-stage', DIRECT)


def family3(template, anchor, lower, upper, snapshot):
    old, policy, question, normalization = make_family(template, anchor, lower, upper, snapshot)
    query = json.loads(old.candidates[0].query_json)
    # Upper boundary is fixed and hard; three binary coordinates remain (N=8).
    if query['path']:
        query['path']['time']['upper_inclusive'] = True
        question = question.replace('and inclusivity of each time boundary are', 'and inclusivity of the lower time boundary are')
    else:
        query['where'][3]['op'] = 'le'
        question = question.replace('inclusivity of each time boundary,', 'inclusivity of the lower time boundary,')
    question += ' The upper time boundary is always inclusive.'
    domains = tuple(replace(d, slot=replace(d.slot, weight=1)) for d in policy.domains[:3])
    policy = ScopePolicy('ch6-first-'+policy.policy_id, domains, language_version='v2')
    family = construct_scope([query], policy, snapshot)
    if len(family.candidates) != 8 or len(family.slots) != 3: raise ValueError('N=8,u=3 required')
    return family, policy, question, normalization


def selection(data):
    rng = random.Random(SEED); selected = []; used = set()
    active_accounts = {t.from_id for t in data.transfers}
    active_companies = {data.company_by_account[t.to_id] for t in data.transfers if t.to_id in data.company_by_account}
    for template in TEMPLATES:
        kind = 'company' if template == 'company_transfer_summary' else 'account'
        all_ids = data.companies if kind == 'company' else data.accounts
        active = active_companies if kind == 'company' else active_accounts
        for stratum in ('uniform', 'active'):
            pool = sorted(str(i) for i in all_ids if fold(kind, str(i)) == 'pilot'
                and (kind, str(i)) not in used and (stratum == 'uniform' or i in active))
            if not pool: raise ValueError('Empty source-only pilot stratum')
            anchor = rng.choice(pool); used.add((kind, anchor))
            selected.append(dict(template=template, stratum=stratum, anchor=anchor, anchor_type=kind,
                frame_size=len(pool), truth_index=rng.randrange(8)))
    return selected


def release(*, archive, lock_path, prepared_path, prepared_sha256, output):
    commit = source_commit(); root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    (root/'private').mkdir(); (root/'cases').mkdir()
    parent = dict(path=str(Path(prepared_path).resolve()), sha256=prepared_sha256)
    prepared = json.loads(read_pinned(prepared_path, prepared_sha256))
    original = prepared['profile']
    child = derive_compact_contribution_profile(parent_path=original['path'], parent_sha256=original['sha256'], output=root/'compact')
    profile = freeze_common_profile(child, root/'profile.json')
    seal = json.loads(read_pinned(prepared['input_seal']['path'], prepared['input_seal']['sha256']))
    if seal['profile'] != original: raise ValueError('Prepared snapshot profile association differs')
    seal['profile'] = dict(path=profile['path'], sha256=profile['sha256'])
    prepared.update(profile=seal['profile'], input_seal=write_once(root/'input-seal.json', seal),
        ch6_association=dict(parent=parent, stores_changed=False, offline_catalog_builds=0))
    prepared_pin = write_once(root/'prepared.json', prepared)
    frozen = FrozenOneShotProfile.load(profile['path'], expected_sha256=profile['sha256'])
    doc, _, _, sources, backends, _, _ = frozen.materialize()
    artifact = load_finbench_artifact_lock(lock_path)
    if doc['dataset']['version'] != artifact.artifact.digest_value: raise ValueError('Source/profile mismatch')
    data = load_finbench_query_data(archive, artifact)
    chosen = selection(data)
    # Durable selection precedes any reference computation or method outcome.
    selected_pin = write_once(root/'private/selection.json', dict(seed=SEED, source_commit=commit, cases=chosen,
        source_lock=file_pin(lock_path), answer_reads_at_selection=0, method_output_reads=0,
        window=[data.minimum_transfer_time,data.maximum_transfer_time],
        strata='uniform IDs and source-edge-active IDs; separate results; neither selected using answer nonemptiness'))
    snapshot = snapshot_identity(sources, backends, doc['source_schema'])
    cells = []; cases = []
    for i, item in enumerate(chosen):
        qid = f'CH6-FIRST-{i:02}'; directory = root/'cases'/qid
        directory.mkdir()
        family, policy, question, normalization = family3(item['template'], item['anchor'],
            data.minimum_transfer_time, data.maximum_transfer_time, snapshot)
        truth = json.loads(family.candidates[item['truth_index']].query_json)
        request = write_once(directory/'request.json', dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id=qid, question=question, population='FinBench SF0.1 authored three-family feasibility pilot: '+item['stratum'],
            exposure='development; shared historical templates; not template-disjoint formal evaluation'))
        scope = write_once(directory/'scope.json', policy.to_dict())
        oracle = write_once(root/'private'/(qid+'-user.json'), private_query_intent(question, truth, language_version='v2'))
        reference = write_once(root/'private'/(qid+'-reference.json'), dict(schema_version='xgap-normalized-row-reference-v1',
            dataset=doc['dataset'], question_id=qid, ordered=True, normalization=normalization,
            rows=reference_rows(data,item['template'],truth), derivation='independent original CSV scan/DFS'))
        state = write_once(directory/'state.json', publish_state(question,family,truth,clue_names=(),
            semantic_choices=[dict(name=s.name,type=s.name,slots=[s.name]) for s in family.slots]))
        order = METHODS[i%3:] + METHODS[:i%3]
        for track in ('controlled','nl'):
            for method in order:
                if track == 'controlled' and method == DIRECT: continue
                settings = UnifiedSettings(epsilon='1/3', relaxable=() if method==DIRECT else tuple(s.name for s in family.slots),
                    limits=Limits(depth=2,horizon=12,optional_ms=1500,
                        resources=Resources(user_calls=9,remote_calls=32,bytes=None,peak_bytes=None)),
                    decision_order='two_stage' if method==METHODS[1] else 'joint')
                config = write_once(directory/(track+'-'+method+'-config.json'), configuration(settings=settings,
                    information=FamilyInformationPolicy(additional_scopes=((0,1),(0,2),(1,2)))))
                cells.append(dict(cell_id=f'c{i:02}-{track}-'+method.removeprefix('xgap-'),method=method,
                    request=request,scope=scope,oracle=oracle,reference=reference,config=config,
                    **({'controlled_state':state} if track=='controlled' else {})))
        cases.append(dict(question_id=qid,template=item['template'],stratum=item['stratum'],
            scope=scope,request=request,reference=reference,oracle=oracle,candidate_count=8,unknown_coordinates=3))
    cells.sort(key=lambda c:'controlled_state' not in c)
    design = dict(total_wall_seconds=3600,package_max_bytes=2*1024**3,free_disk_reserve_bytes=6*1024**3,
        method_wall_seconds=120,method_rss_bytes=1024**3,source_rss_bytes=2*1024**3,startup_seconds=120,
        source_budget=asdict(SourceObservationBudget(capture_compression='gzip',max_calls=64,request_bytes=1024**2,
            phase_request_bytes=16*1024**2,response_bytes=32*1024**2,phase_response_bytes=128*1024**2,timeout_seconds=30)))
    manifest = write_once(root/'manifest.json',dict(schema_version=UNIFIED_SCHEMA,deployment='native',prepared=prepared_pin,design=design,cells=cells))
    return write_once(root/'release.json',dict(schema_version='xgap-ch6-first-real-release-v1',source_commit=commit,
        manifest=manifest,selection=selected_pin,cases=cases,unique_cases=6,cells=len(cells),maximum_model_calls=18,
        maximum_output_tokens=18*4096,maximum_final_plans=30,automatic_retries=0,
        frozen_estimator_fit_calls=0,information_targets=[],cache='one fresh serving session then reuse until a failure; method order rotated, no warmup; not cache-controlled speed evidence',
        actual_trace_weights=dict(clarification_calls=1,disclosed_fields=.25,backend_http_attempts=1,planner_cpu_ms=.01),
        formal_result=False,template_generalization=False,scope='bounded first real results; no W1-W4/LC-QuAD/three-domain completeness claim'))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','lock-path','prepared-path','prepared-sha256','output'):p.add_argument('--'+name,required=True)
    print(json.dumps(release(**vars(p.parse_args()))))
