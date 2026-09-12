"""New financial input boundary only: no old native/training/regression runs."""

import json
from pathlib import Path
import socket

import pytest

from xgap.experiments.financial_nl_profile import INPUT_ROOT, publish_profile, sha, verified_inputs
from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import run_record


FIXTURE = Path(__file__).resolve().parents[1]/'datasets/financial_nl_tiny_v1'


def test_financial_profile_both_modes_no_gold_or_network_and_correct_source_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('Unexpected network'))
    original = Path.open
    def guarded(path, *a, **k):
        if path.name in ('reference.json', 'F1-plan.json', 'F2-plan.json', 'F3-plan.json', 'result.json'):
            pytest.fail('Inference preparation read answer/program evidence')
        return original(path, *a, **k)
    monkeypatch.setattr(Path, 'open', guarded)
    pin = publish_profile(tmp_path/'inputs', endpoints={'neo4j':'http://127.0.0.1:1', 'fuseki':'http://127.0.0.1:2'})
    profile = FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
    doc, estimator, bundle, sources, _, _, modes = profile.materialize()
    assert sources['graph'].replica_backend_ids == ('neo4j',)
    assert sources['control'].replica_backend_ids == ('fuseki',)
    assert not doc['source_schema']['control']['edges']
    assert 'isBlocked' not in doc['source_schema']['graph']['nodes']['XGAPFinBenchAccount']['properties']
    alice = bundle.bindings['entity:person_31']
    assert alice.value == 'person_31' and alice.identity_property == 'xgap_id'
    catalog = json.loads((tmp_path/'inputs/catalog/catalog.json').read_text())
    assert not any(e['authoritative_mentions'] for e in catalog['entries'])
    assert estimator.to_dict()['training_provenance']['sample_count'] == 32
    for mode, cap in [('performance',1), ('precision',3)]:
        receipt = run_record(profile_path=pin['path'], profile_sha256=pin['sha256'],
            request_path=FIXTURE/'request.json', request_sha256=sha(FIXTURE/'request.json'),
            mode=mode, output=tmp_path/mode, operation='preflight')
        assert receipt['success'], receipt
        assert receipt['model_network_calls'] == receipt['backend_network_calls'] == 0
        inp = json.loads((tmp_path/mode/'input.json').read_text())['request']
        assert inp['required_constraints'] == [] and 'requested_output' not in inp['context']
        assert 'operator_sources' not in inp['context'] and 'population' not in inp['context']
        assert modes[mode][0].candidate_cap == cap


def test_changed_load_bytes_are_rejected_before_publication(tmp_path):
    (tmp_path/'manifest.json').write_bytes((INPUT_ROOT/'manifest.json').read_bytes())
    (tmp_path/'mapping.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='hash mismatch'):
        verified_inputs(tmp_path)
