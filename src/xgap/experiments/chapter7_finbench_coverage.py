"""Pre-answer, three-shape development pilot; formal anchors remain untouched."""
from dataclasses import asdict
import json
from pathlib import Path
import random
import time

from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.scope_authority import private_query_intent
from xgap.agent.strong_planning import StrongSearchLimits
from xgap.experiments.bounded_joint_contract import METHODS, configuration
from xgap.experiments.campaign_source_observer import SourceObservationBudget
from xgap.experiments.chapter7_finbench_families import TEMPLATES, make_family, reference_rows
from xgap.experiments.chapter7_finbench_pilot import split_group, windows
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.m15_finbench_artifacts import load_finbench_artifact_lock
from xgap.experiments.m15_finbench_workload import load_finbench_query_data
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once

SEED = 'xgap-ch7-three-shape-pilot-20260921-v1'


def fold(kind, anchor):
    if kind == 'account':
        return split_group(anchor)  # Preserve the first pilot/formal account split.
    if kind != 'company':
        raise ValueError('Unknown anchor type')
    return 'pilot' if int(fingerprint([SEED, 'company-fold', str(anchor)]), 16) % 5 == 0 else 'formal'


def sample(accounts, companies):
    """Eight distinct anchors per shape, then uniform quarter window and intent.

    Read IDs only. Account anchors are distinct across the two account shapes;
    type-qualified group IDs keep every anchor's windows/intents in the same fold.
    """
    pools = {}
    for kind, identifiers in (('account', accounts), ('company', companies)):
        all_ids = sorted(str(value) for value in identifiers)
        if len(all_ids) != len(set(all_ids)):
            raise ValueError('Duplicate source identifiers')
        pools[kind] = [value for value in all_ids if fold(kind, value) == 'pilot']
    if len(pools['account']) < 16 or len(pools['company']) < 8:
        raise ValueError('Insufficient independent pilot anchors')
    rng = random.Random(SEED)
    account_anchors = rng.sample(pools['account'], 16)
    company_anchors = rng.sample(pools['company'], 8)
    selected = []
    for ti, template in enumerate(TEMPLATES):
        kind = 'company' if ti == 2 else 'account'
        anchors = company_anchors if ti == 2 else account_anchors[ti*8:(ti+1)*8]
        for j, anchor in enumerate(anchors):
            selected.append(dict(index=ti*8+j, template=template, anchor_type=kind, anchor=anchor,
                family_group_id=fingerprint(['finbench-sf0.1', kind, anchor]),
                window=rng.randrange(4), truth_index=rng.randrange(16), track='nl' if j%2==0 else 'controlled',
                method_order=list(METHODS) if (j//2)%2==0 else list(reversed(METHODS))))
    return selected


def release(*, archive, lock_path, prepared_path, prepared_sha256, output, source_commit):
    started = time.perf_counter()
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root/'private').mkdir(); (root/'cases').mkdir()
    prepared_pin = dict(path=str(Path(prepared_path).resolve()), sha256=prepared_sha256)
    prepared = json.loads(read_pinned(prepared_path, prepared_sha256))
    profile_pin = prepared['profile']
    frozen = FrozenOneShotProfile.load(profile_pin['path'], expected_sha256=profile_pin['sha256'])
    doc, _, _, sources, backends, _, _ = frozen.materialize()
    lock = load_finbench_artifact_lock(lock_path)
    if lock.artifact.digest_value != doc['dataset']['version']:
        raise ValueError('Source/profile identity differs')
    if any(m['provider']['wire_profile'] != 'compact-graph-schema-v2' for m in doc['modes'].values()):
        raise ValueError('Compact-v2 profile required')
    data = load_finbench_query_data(archive, lock)
    selected = sample(data.accounts, data.companies)
    time_windows = windows(data.minimum_transfer_time, data.maximum_transfer_time)
    selection = write_once(root/'private/selection.json', dict(schema_version='xgap-ch7-preanswer-selection-v1',
        source_commit=source_commit, seed=SEED, selected=selected, time_windows=time_windows,
        answer_reads_at_selection=0, method_output_reads=0, frames=dict(accounts=len(data.accounts), companies=len(data.companies)),
        unit='type-qualified anchor family; all windows/intents of an anchor have one fold',
        controlled_clues='first structural choice and lower time-boundary comparison; two unknown choices remain',
        templates_shared_with_formal=True, unseen_template_generalization=False))
    config = write_once(root/'config.json', configuration(epsilon='1/2',
        limits=StrongSearchLimits(planning_ms=10000, improvement_actions=16)))
    snapshot = snapshot_identity(sources, backends, doc['source_schema'])
    cases, cells = [], []
    for item in selected:
        i = item['index']; identifier = f'CH7-FB-C{i:02}'
        path = root/'cases'/identifier; path.mkdir()
        family, policy, question, normalization = make_family(item['template'], item['anchor'],
            *time_windows[item['window']], snapshot)
        truth = json.loads(family.candidates[item['truth_index']].query_json)
        request = write_once(path/'request.json', dict(schema_version='xgap-one-shot-evaluation-request-v1',
            question_id=identifier, question=question, population='FinBench SF0.1 derived three-shape uniform pilot',
            exposure='development; anchor-family disjoint from reserved formal pool; templates shared'))
        scope = write_once(path/'scope.json', policy.to_dict())
        oracle = write_once(root/'private'/(identifier+'-user.json'), private_query_intent(question, truth, language_version='v2'))
        reference = write_once(root/'private'/(identifier+'-reference.json'), dict(
            schema_version='xgap-normalized-row-reference-v1', dataset=doc['dataset'], question_id=identifier,
            ordered=True, normalization=normalization, rows=reference_rows(data, item['template'], truth),
            derivation='independent scan/DFS of pinned original CSV; no shared compiler or backend evaluation'))
        state = {}
        if item['track'] == 'controlled':
            choices = [dict(name=s.name, type=s.name, slots=[s.name]) for s in family.slots]
            state['controlled_state'] = write_once(path/'state.json', publish_state(question, family, truth,
                clue_names=(family.slots[0].name, family.slots[2].name), semantic_choices=choices))
        for position, method in enumerate(item['method_order']):
            cells.append(dict(cell_id=f'c{i:02}-{position}-'+method.rsplit('-', 1)[-1], method=method,
                request=request, scope=scope, oracle=oracle, reference=reference, config=config, **state))
        cases.append(dict(question_id=identifier, template_family_id=item['template'], family_group_id=item['family_group_id'],
            candidate_family_id=family.family_id, track=item['track'], window_id=item['window'],
            request=request, scope=scope, oracle=oracle, reference=reference, **state))
    design = dict(total_wall_seconds=3600, package_max_bytes=3*1024**3, free_disk_reserve_bytes=6*1024**3,
        method_wall_seconds=90, method_rss_bytes=1024**3, source_rss_bytes=2*1024**3, startup_seconds=120,
        source_budget=asdict(SourceObservationBudget(capture_compression='gzip', max_calls=64,
            request_bytes=1024**2, phase_request_bytes=16*1024**2, response_bytes=64*1024**2,
            phase_response_bytes=256*1024**2, timeout_seconds=20)))
    batch = write_once(root/'batch.json', dict(schema_version='xgap-bounded-joint-batch-v1', deployment='native',
        prepared=prepared_pin, design=design, cells=cells))
    return write_once(root/'release.json', dict(schema_version='xgap-ch7-finbench-pilot-v1',
        protocol='three-shape-coverage-v1', source_commit=source_commit, dataset=doc['dataset'],
        selection=selection, source_lock=file_pin(lock_path), archive_sha256=lock.artifact.digest_value,
        prepared=prepared_pin, profile=profile_pin, batch=batch, cases=cases, unique_base_cases=24, cells=48,
        maximum_new_model_calls=24, maximum_final_plans=48, formal_result=False,
        selection_uses_answer_nonemptiness=False, template_generalization_claim=False,
        offline_release_ms=(time.perf_counter()-started)*1000))
