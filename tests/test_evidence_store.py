import gzip
import hashlib
import json
import threading
import tracemalloc
from types import SimpleNamespace

import pytest

from xgap.experiments.evidence_store import read_json_evidence, write_json_evidence
from xgap.experiments.one_shot_records import BackendReplay, CapturingClient, write_once
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from test_campaign_source_observer import observer, call, release


def test_streaming_capture_preserves_data_and_bounds_extra_memory(tmp_path):
    payload = {'rows': [{'id': i, 'text': 'repeated evidence ' * 30} for i in range(16000)]}
    tracemalloc.start()
    pin = write_json_evidence(tmp_path/'rows.json.gz', payload)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert pin['bytes'] < pin['logical_bytes'] / 10
    assert peak < pin['logical_bytes'] / 2
    assert read_json_evidence(pin) == payload
    assert read_json_evidence(write_once(tmp_path/'old.json', payload)) == payload
    with pytest.raises(FileExistsError): write_json_evidence(tmp_path/'rows.json.gz', payload)
    with pytest.raises(ValueError, match='bound'): read_json_evidence(pin, max_bytes=1024)
    with pytest.raises(ValueError, match='logical'): read_json_evidence({**pin, 'logical_bytes': 50})
    path = tmp_path/'rows.json.gz'
    path.write_bytes(path.read_bytes()[:-1] + b'x')
    with pytest.raises(ValueError, match='hash'): read_json_evidence(pin)


def test_compressed_native_capture_has_identical_offline_replay(tmp_path):
    artifact = QueryArtifact('q', 'cypher', 'MATCH (n) RETURN n', {})
    report = ExecutionReport('b', 'q', 'cypher', True, [{'n': 1}, {'n': 1}], 3.0)
    ledger = []
    client = CapturingClient(SimpleNamespace(backend_id='b', execute=lambda _: report),
                             tmp_path, ledger, threading.Lock(), retain_payloads=False, compress=True)
    assert client.execute(artifact) == report
    assert 'execution' not in ledger[0]
    replay = BackendReplay('b', ledger).execute(artifact)
    assert replay.rows == report.rows  # Multiplicity is not deduplicated by storage.


def test_compressed_observer_preserves_wire_payload_and_logical_accounting(tmp_path):
    with observer(tmp_path/'source', capture_compression='gzip') as proxy:
        proxy.set_phase('compressed')
        assert call(proxy) == (200, b'abcdefghij')
        summary = release(proxy, tmp_path)
        record = json.loads((proxy.root/'0000-result.json').read_text())
        assert gzip.decompress(open(record['response_path'], 'rb').read()) == b'abcdefghij'
        assert record['response_sha256'] == hashlib.sha256(b'abcdefghij').hexdigest()
        assert summary['response_body_bytes'] == 10
        assert summary['capture_storage_bytes'] == record['response_storage_pin']['bytes']


def test_study_budget_cause_survives_secondary_transport_error(tmp_path, monkeypatch):
    import xgap.experiments.common_method_trial as common
    class Resources:
        def __init__(self, *a, **kw): pass
        def stop(self): return {'complete': True, 'recovery_ms': 0}
        def summary(self): return {}
    monkeypatch.setattr(common, 'OwnedResources', Resources)
    request = write_once(tmp_path/'request.json', {'schema_version': common.REQUEST_SCHEMA,
        'question_id': 'q', 'population': 'toy', 'exposure': 'toy', 'dataset': {'dataset_id': 't', 'version': '1'}})
    with observer(tmp_path/'source', response_bytes=4) as proxy:
        def guarded(*a, **kw):
            assert call(proxy)[0] == 502
            return {'success': False, 'status': 'study_disk_budget'}
        monkeypatch.setattr(common, 'run_guarded_command', guarded)
        result = common.run_fixed_trial(request_path=request['path'], request_sha256=request['sha256'],
            method='fedx', endpoint='http://fixture', output=tmp_path/'trial', observer=proxy,
            owned_services=[SimpleNamespace(role='source'), SimpleNamespace(role='method_host')])
        assert result['status'] == 'study_disk_budget' and not result['success']
        assert result['secondary_status'] == 'harness_budget_censored'
        assert not result['can_continue_session']
