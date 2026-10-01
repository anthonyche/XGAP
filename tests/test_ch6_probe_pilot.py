"""Probe activation pins, paired configurations and a real portable scalar call."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import socket

import pytest

from test_one_shot_records import prepare_profile
from test_unified_actions import fixture, target
from test_unified_family import invocation
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.intent_certificate import canonical
from xgap.agent.unified_family import UnifiedSettings
from xgap.agent.unified_lookahead import Limits
from xgap.experiments.ch6_formal_protocol import load_pin
from xgap.experiments.ch6_probe_pilot import probe_summary, publish
from xgap.experiments.controlled_state import publish_state
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.experiments.unified_contract import configuration


def pilot(tmp_path):
    pins, doc = prepare_profile(tmp_path / 'profile')
    profile_pin = dict(path=str(pins['profile_path']), sha256=pins['profile_sha256'])
    profile = FrozenOneShotProfile.load(profile_pin['path'], expected_sha256=profile_pin['sha256'])
    _, _, _, sources, backends, _, _ = profile.materialize()
    data, _, _, family, _, _ = fixture()
    family = replace(family, source_snapshot=snapshot_identity(sources, backends, doc['source_schema']))
    save = lambda name, obj: write_once(tmp_path / (name + '.json'), obj)
    state = save('state', publish_state('q', family, data['query_template'],
        semantic_choices=[dict(name=s.name, type='coordinate', slots=[s.name]) for s in family.slots]))
    source_id, source = next((k, s) for k, s in sources.items() if 'fuseki' in s.replica_backend_ids)
    item = replace(target(probabilities=(.6, .3, .1)), backend='fuseki', source_id=source_id,
                   version=source.snapshot_version)
    registry = dict(schema_version='xgap-ch6-information-registry-v1', profile=profile_pin,
        targets=[asdict(item)], basis='Declared development work model, not calibrated latency')
    prior = dict(schema_version='xgap-ch6-candidate-prior-v1', controlled_state=state,
        candidate_ids=[c.candidate_id for c in family.candidates], weights=[1] * len(family.candidates),
        basis='Explicit equal candidate weights for this portable development scenario')
    spec = dict(schema_version='xgap-ch6-probe-pilot-input-v1',
        base_configuration=save('base', configuration(settings=UnifiedSettings(limits=Limits(depth=2)))),
        profile=profile_pin, request=save('request', dict(question='q')), controlled_state=state,
        information_registry=save('registry', registry), candidate_prior=save('prior', prior),
        aggregation='expectation', probe_price=5)
    return spec, registry, prior, save


def test_publisher_is_offline_and_pairs_same_registry_prior_and_prices(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *args, **kwargs: pytest.fail('Unexpected network call'))
    spec, _, _, save = pilot(tmp_path)
    original = load_pin(spec['base_configuration'])
    receipt = load_pin(publish(save('input', spec), tmp_path / 'out'))
    configs = {k: load_pin(v) for k, v in receipt['configurations'].items()}
    xgap, np = configs['XGAP'], deepcopy(configs['NP'])
    np['settings']['information_mode'] = 'all'
    assert np == xgap
    assert xgap['settings']['information_targets'][0]['action_cost'] == .5
    assert xgap['settings']['limits']['aggregation'] == 'expectation'
    assert configs['SH']['settings']['limits']['depth'] == configs['GR']['settings']['limits']['depth'] == 1
    assert configs['SH']['settings']['action_objective'] == 'continuation'
    assert configs['GR']['settings']['action_objective'] == 'myopic'
    assert load_pin(spec['base_configuration']) == original
    assert receipt['diagnostics']['XGAP']['probe_registered_count'] == 1
    assert receipt['diagnostics']['XGAP']['probe_enabled_count'] == 1
    assert receipt['diagnostics']['NP']['probe_enabled_count'] == 0
    assert receipt['diagnostics']['XGAP']['probe_selected_calls'] is None
    assert receipt['selection_claim'] is False and receipt['backend_calls'] == 0
    with pytest.raises(FileExistsError):
        publish(save('input-again', spec), tmp_path / 'out')


@pytest.mark.parametrize('change,match', [
    ('no_prior', 'explicit frozen candidate prior'),
    ('reordered_prior', 'original order'),
    ('source_version', 'source/version/backend'),
    ('registry_profile', 'identify this profile'),
    ('artifact_language', 'artifact language'),
    ('no_probabilities', 'outcome probability'),
    ('implicit_objective', 'input required'),
])
def test_incomplete_or_mismatched_probe_inputs_fail_before_publication(tmp_path, change, match):
    spec, registry, prior, save = pilot(tmp_path)
    if change == 'no_prior': spec['candidate_prior'] = None
    elif change == 'reordered_prior':
        prior['candidate_ids'].reverse(); spec['candidate_prior'] = save('bad-prior', prior)
    elif change == 'source_version':
        registry['targets'][0]['version'] = 'different'; spec['information_registry'] = save('bad-registry', registry)
    elif change == 'registry_profile':
        registry['profile'] = {**registry['profile'], 'sha256': '0' * 64}
        spec['information_registry'] = save('bad-registry', registry)
    elif change == 'artifact_language':
        artifact = json.loads(registry['targets'][0]['artifact_json'])
        artifact['language'] = 'cypher'
        registry['targets'][0]['artifact_json'] = canonical(artifact)
        spec['information_registry'] = save('bad-registry', registry)
    elif change == 'no_probabilities':
        registry['targets'][0]['probabilities'] = None; spec['information_registry'] = save('bad-registry', registry)
    elif change == 'implicit_objective': del spec['aggregation']
    with pytest.raises(ValueError, match=match):
        publish(save('input', spec), tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_max_and_empty_registry_remain_explicit_without_selection_claim(tmp_path):
    spec, registry, _, save = pilot(tmp_path)
    spec.update(aggregation='max', candidate_prior=None)
    result = load_pin(publish(save('max-input', spec), tmp_path / 'max'))
    assert result['aggregation'] == 'max'
    assert result['diagnostics']['XGAP']['probe_enabled_count'] == 1
    assert result['selection_claim'] is False
    registry['targets'] = []
    spec['information_registry'] = save('empty-registry', registry)
    result = load_pin(publish(save('empty-input', spec), tmp_path / 'empty'))
    assert result['diagnostics']['XGAP']['probe_axis_active'] is False


@pytest.mark.parametrize('aggregation,price,mode,selected', [
    ('expectation', .1, 'all', 1),
    ('expectation', 100, 'all', 0),
    ('expectation', .1, 'no_probe', 0),
    ('max', .1, 'all', 0),
])
def test_real_scalar_probe_is_paid_only_when_selected(tmp_path, aggregation, price, mode, selected):
    settings = UnifiedSettings(limits=Limits(depth=1, optional_ms=3000, aggregation=aggregation),
        candidate_weights=(1,) * 8, information_mode=mode,
        information_targets=(target(probabilities=(.6, .3, .1), action_cost=price),))
    report, calls = invocation(tmp_path, settings)
    assert report['success'], report
    core = report['joint_policy']
    summary = probe_summary(settings, report)
    assert summary['probe_registered_count'] == 1
    assert summary['probe_selected_calls'] == summary['probe_known_fact_count'] == selected
    assert report['probe_calls'] == selected
    assert len(calls) == report['backend_remote_calls'] + selected
    assert core['final_plan_executions'] == 1 and core['external_calls_during_search'] == 0
    receipts = [t for t in core['trace'] if t['kind'] == 'probe']
    if selected:
        assert receipts[0]['declared_action_cost'] == price
        assert receipts[0]['used']['remote_calls'] == 1
        assert receipts[0]['evidence']['semantic_authority'] is False
    assert report['terminal_certificate']['eligible']
    assert probe_summary(settings, dict(status='proposal_failed'))['probe_selected_calls'] is None
