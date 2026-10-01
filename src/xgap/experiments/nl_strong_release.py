"""Offline association of existing data with a frozen NL-only first pass."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from xgap.agent.nl_strong_question import NL_STRONG_METHODS, PROFILE_ID
from xgap.experiments.campaign_schedule import balanced_orders
from xgap.experiments.one_shot_profile import FrozenOneShotProfile, read_pinned
from xgap.experiments.one_shot_records import write_once


def load(pin):
    return json.loads(read_pinned(pin['path'], pin['sha256']))


def ident(pin):
    return {k: pin[k] for k in ('path', 'sha256')}


def freeze_common_profile(parent, output):
    doc = load(parent); origin = Path(parent['path']).parent
    for key in ('catalog', 'estimator'):
        doc[key]['path'] = str((origin/doc[key]['path']).resolve())
    for spec in doc['sources'].values():
        if 'equality_key_bounds' in spec:
            ref = spec['equality_key_bounds']; ref['path'] = str((origin/ref['path']).resolve())
    common = deepcopy(doc['modes']['performance'])
    common['provider']['prompt']['path'] = str((origin/common['provider']['prompt']['path']).resolve())
    if common['policy']['candidate_cap'] != 1 or common['policy'].get('retrieval_rows_per_relation') is not None:
        raise ValueError('The first pass needs a K=1 complete-result frontend')
    for mode in ('precision', 'performance'):
        doc['modes'][mode] = deepcopy(common); doc['modes'][mode]['policy']['mode'] = mode
    doc['profile_id'] += ':' + PROFILE_ID
    doc['offline']['nl_strong_frontend'] = dict(parent_profile=parent, profile_id=PROFILE_ID,
        candidate_cap=1, no_new_fit_or_build=True, same_frontend_all_methods=True,
        purpose='initial NL effectiveness and conditional execution; not acquisition tradeoff')
    pin = write_once(output, doc)
    FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
    return pin


def first_groups(schedule, per_family=4):
    """Stratified frozen prefix; no reference/answer/observed outcome is read."""
    groups = {c['question_id']: c for c in schedule['cells']}
    selected = []
    for family in sorted({c['family'] for c in groups.values()}):
        candidates = sorted((c for c in groups.values() if c['family'] == family), key=lambda c: c['group_index'])
        if len(candidates) < per_family:
            raise ValueError('Insufficient family population')
        selected.extend(candidates[:per_family])
    return sorted(selected, key=lambda c: c['group_index'])


def release(parent, output):
    old_release = load(parent); root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    original_schedule = load(old_release['schedules']['native'])
    groups = first_groups(original_schedule)
    if len(groups) != 12:
        raise ValueError('The first pass is fixed at three families times four questions')
    requests = {}; (root/'requests').mkdir()
    for group in groups:
        raw = load(group['request'])
        if set(raw) != {'schema_version', 'question_id', 'question', 'population', 'exposure'}:
            raise ValueError('NL first-pass input must not contain per-question structure or output scaffolding')
        raw['exposure'] += ';historically_exposed_population;20260916_NL_strong_first_pass;not_unseen_holdout'
        requests[group['question_id']] = write_once(root/'requests'/(group['question_id']+'.json'), raw)
    profiles, prepared, schedules = {}, {}, {}
    for kind in ('native', 'rdf'):
        (root/kind).mkdir(); profiles[kind] = freeze_common_profile(old_release['profiles'][kind], root/kind/'profile.json')
        old = load(old_release['prepared'][kind]); seal = load(old['input_seal'])
        association = dict(parent_preparation=old_release['prepared'][kind], parent_input_seal=old['input_seal'],
            profile_revision=ident(profiles[kind]), stores_changed=False, new_loads=0,
            offline_times_and_load_counts_inherited=True, profile_id=PROFILE_ID)
        if old['profile'] != ident(old_release['profiles'][kind]) or seal['profile'] != old['profile']:
            raise ValueError('Original profile/store identity mismatch')
        seal.update(profile=ident(profiles[kind]), interpretation_association=association)
        pin = write_once(root/kind/'input-seal.json', seal)
        old.update(profile=ident(profiles[kind]), input_seal=pin, interpretation_association=association)
        prepared[kind] = write_once(root/kind/'prepared.json', old)
        schedule = load(old_release['schedules'][kind])
        methods = list(NL_STRONG_METHODS) + ([] if kind == 'native' else ['fedx', 'fedup'])
        orders = balanced_orders(methods); cells = []
        for i, group in enumerate(groups):
            for position, method in enumerate(orders[i % len(orders)]):
                cells.append(dict(cell_id=f'nl-strong-00-{i:03}-{position}', block=0, group_index=i,
                    method_position=position, method=method, track='natural_language',
                    question_id=group['question_id'], family=group['family'], request=requests[group['question_id']],
                    reference_for_post_seal_scoring_only=group['reference_for_post_seal_scoring_only']))
        schedule.update(profile=ident(profiles[kind]), methods=methods, groups=len(groups), cells=cells, blocks=1,
            deployment=kind, method_profile=PROFILE_ID, maximum_model_calls=len(cells),
            maximum_top_level_method_attempts=len(cells), maximum_method_online_seconds=180*len(cells),
            subset_rule='first four in each family in the previously frozen question order; answers not read',
            original_population_groups=48, historical_results_inherited=False,
            order_design='alternating modes' if kind == 'native' else 'Williams method order; three complete cycles',
            baseline_label='same frozen NL frontend + unmodified FedX/FedUP' if kind == 'rdf' else None)
        schedules[kind] = write_once(root/kind/'schedule.json', schedule)
    summary = load(old_release['prepared']['summary'])
    summary.update(profile=ident(profiles['rdf']), interpretation_association=dict(
        parent_summary=old_release['prepared']['summary'], new_summary_builds=0, profile_id=PROFILE_ID))
    prepared['summary'] = write_once(root/'rdf/summary.json', summary)
    return write_once(root/'release.json', dict(schema_version='xgap-nl-strong-first-release-v1', parent=parent,
        profiles=profiles, prepared=prepared, schedules=schedules, unique_questions=12, original_population=48,
        reference_reads=0, model_calls=0, data_loads=0, catalog_builds=0, fit_calls=0, automatic_retries=0,
        old_artifacts_unchanged=True, baseline_algorithms_unchanged=True, global_optimality_claim=False))
