#!/usr/bin/env python3
"""Three new shapes on existing tiny stores, both modes and both input tracks.

Twelve development cells, six model calls maximum. No formal sample or rerun.
"""
import argparse
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

from run_bounded_joint_batch import source_commit, SCHEMA
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_contract import METHODS, configuration
from xgap.experiments.bounded_joint_toy import FIXTURE
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.chapter7_finbench_families import TEMPLATES, make_family, reference_rows
from xgap.experiments.compact_profile import derive_compact_contribution_profile
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.m15_finbench_workload import FinBenchQueryData, Transfer
from xgap.experiments.nl_strong_release import freeze_common_profile, ident, load
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once


def reference_data():
    raw = json.loads((FIXTURE/'family_reference.json').read_text())
    transfers = tuple(Transfer(a, b, Decimal(v), t, str(i))
                      for i, (a, b, v, t) in enumerate(raw['transfers']))
    outgoing = defaultdict(list)
    for transfer in transfers:
        outgoing[transfer.from_id].append(transfer)
    return FinBenchQueryData({}, raw['accounts'], raw['companies'], {}, {}, raw['company_by_account'], {},
                            transfers, dict(outgoing), min(t.create_time for t in transfers),
                            max(t.create_time for t in transfers))


def selected_truth(family):
    """Fixed tiny boundary: blocked recipients, closed lower/open upper, depth2/sum."""
    for candidate in family.candidates:
        query = json.loads(candidate.query_json)
        if query['where'][1]['right']['value'] is not True:
            continue
        if query['path']:
            path = query['path']
            if path['max_hops'] != 2 or not path['time']['lower_inclusive'] or path['time']['upper_inclusive']:
                continue
        elif (query['select']['total']['aggregate'] != 'sum' or
              query['where'][2]['op'] != 'ge' or query['where'][3]['op'] != 'lt'):
            continue
        return query
    raise ValueError('Tiny boundary absent from complete scope')


def release(*, output, prepared_path, prepared_sha256, track='full'):
    if track not in ('full', 'nl-exact'):
        raise ValueError('Unknown shape admission track')
    commit = source_commit()
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    parent = dict(path=str(Path(prepared_path).resolve()), sha256=prepared_sha256)
    prepared = load(parent)
    if prepared['dataset'] != dict(dataset_id='financial-binding-tiny', version='financial-tiny-v1'):
        raise ValueError('This development release admits the existing eight-node tiny snapshot only')
    old_profile = prepared['profile']
    child = derive_compact_contribution_profile(parent_path=old_profile['path'],
        parent_sha256=old_profile['sha256'], output=root/'compact-v2')
    profile = freeze_common_profile(child, root/'profile.json')
    seal = load(prepared['input_seal'])
    if seal['profile'] != old_profile:
        raise ValueError('Original store/profile association differs')
    association = dict(parent_preparation=parent, parent_input_seal=prepared['input_seal'],
                       profile_revision=ident(profile), stores_changed=False, new_loads=0)
    seal.update(profile=ident(profile), interpretation_association=association)
    prepared.update(profile=ident(profile), input_seal=write_once(root/'input-seal.json', seal),
                    interpretation_association=association)
    prepared_pin = write_once(root/'prepared.json', prepared)
    frozen = FrozenOneShotProfile.load(profile['path'], expected_sha256=profile['sha256'])
    doc, _, _, sources, backends, _, _ = frozen.materialize()
    snapshot = snapshot_identity(sources, backends, doc['source_schema'])
    data = reference_data()
    config = write_once(root/'config.json', configuration(epsilon='1/2',
        limits=StrongSearchLimits(planning_ms=10000, improvement_actions=16)))
    cells, cases = [], []
    for index, template in enumerate(TEMPLATES):
        path = root/template
        path.mkdir()
        family, scope, question, normalization = make_family(template, '1',
            data.minimum_transfer_time, data.maximum_transfer_time, snapshot)
        truth = selected_truth(family)
        request = write_once(path/'request.json', dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id=template, question=question, population='authored eight-node development boundary', exposure='development'))
        scope_pin = write_once(path/'scope.json', scope.to_dict())
        oracle = write_once(path/'private-user.json', private_query_intent(question, truth, language_version='v2'))
        reference = write_once(path/'reference.json', dict(schema_version='xgap-normalized-row-reference-v1',
            dataset=doc['dataset'], question_id=template, ordered=True, normalization=normalization,
            rows=reference_rows(data, template, truth), derivation='independent tabular transcription and CSV scan/DFS'))
        state = write_once(path/'state.json', publish_state(question, family, truth, clue_names=(),
            semantic_choices=[dict(name=s.name, type=s.name, slots=[s.name]) for s in family.slots]))
        for track in ('controlled', 'nl'):
            for method in (METHODS if index % 2 == 0 else tuple(reversed(METHODS))):
                cells.append(dict(cell_id=f's{index}-{track}-'+method.rsplit('-', 1)[-1],
                    method=method, request=request, scope=scope_pin, oracle=oracle, config=config,
                    reference=reference, **({'controlled_state':state} if track=='controlled' else {})))
        cases.append(dict(template=template, request=request, scope=scope_pin, oracle=oracle, reference=reference, controlled_state=state))
    # All deterministic cells precede model calls, exposing execution errors cheaply.
    cells.sort(key=lambda c: 'controlled_state' not in c)
    if track == 'nl-exact':
        cells = [c for c in cells if 'controlled_state' not in c and c['method'] == METHODS[0]]
    design = dict(total_wall_seconds=1800, package_max_bytes=1024**3, free_disk_reserve_bytes=6*1024**3,
        method_wall_seconds=90, method_rss_bytes=1024**3, source_rss_bytes=2*1024**3, startup_seconds=120,
        source_budget=asdict(SourceObservationBudget(capture_compression='gzip', max_calls=64,
            request_bytes=1024**2, phase_request_bytes=4*1024**2, response_bytes=2*1024**2,
            phase_response_bytes=8*1024**2, timeout_seconds=20)))
    batch = write_once(root/'batch.json', dict(schema_version=SCHEMA, deployment='native',
        prepared=prepared_pin, design=design, cells=cells))
    return write_once(root/'release.json', dict(schema_version='xgap-ch7-shapes-native-gate-v1',
        source_commit=commit, batch=batch, cases=cases, track=track,
        maximum_model_calls=sum('controlled_state' not in c for c in cells), maximum_final_plans=len(cells),
        formal_result=False, source_reference=file_pin(FIXTURE/'family_reference.json')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'prepared-path', 'prepared-sha256'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--track', choices=('full', 'nl-exact'), default='full')
    print(json.dumps(release(**vars(parser.parse_args()))))
