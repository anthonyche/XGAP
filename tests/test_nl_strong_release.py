"""Freeze shared frontend and select a denominator without opening answers."""
from copy import deepcopy
import json

from test_one_shot_records import prepare_profile
from xgap.experiments.nl_strong_release import first_groups, freeze_common_profile
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.nl_strong_worker import run_nl_strong


def test_common_profile_retains_frozen_data_and_uses_one_provider(tmp_path):
    args, parent = prepare_profile(tmp_path/'parent')
    pin = freeze_common_profile({'path': str(args['profile_path']), 'sha256': args['profile_sha256']}, tmp_path/'child.json')
    loaded = FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
    doc, _, _, _, _, _, modes = loaded.materialize()
    assert doc['dataset'] == parent['dataset'] and doc['sources'] == parent['sources']
    assert doc['estimator'] == parent['estimator'] and doc['catalog'] == parent['catalog']
    assert modes['precision'][0].candidate_cap == modes['performance'][0].candidate_cap == 1
    assert modes['precision'][1].config.safe_dict() == modes['performance'][1].config.safe_dict()


def test_stratified_selection_depends_only_on_frozen_order():
    groups = [dict(question_id=f'{f}-{i}', family=f, group_index=i*3+f,
        request={'path': '/must-not-read'}, reference_for_post_seal_scoring_only={'path': '/must-not-read'})
        for f in range(3) for i in range(16)]
    schedule = {'cells': [c for g in groups for c in (deepcopy(g), deepcopy(g))]}
    selected = first_groups(schedule)
    assert len(selected) == len({c['question_id'] for c in selected}) == 12
    assert [c['group_index'] for c in selected] == list(range(12))


def test_worker_rejects_question_scaffolding_before_model_or_execution(tmp_path):
    args, _ = prepare_profile(tmp_path/'parent')
    raw = json.loads(args['request_path'].read_text()); raw['operator_sources'] = {'op': 'gold-source'}
    pin = write_once(tmp_path/'bad.json', raw)
    result = run_nl_strong(**{**args, 'request_path':pin['path'], 'request_sha256':pin['sha256']},
        method='xgap-nl-strong-exact', output=tmp_path/'worker')
    assert not result['success'] and result['model_calls'] == result['top_level_attempts'] == 0
    assert 'per-question' in result['error']
    assert not (tmp_path/'worker/interpretation.json').exists()
