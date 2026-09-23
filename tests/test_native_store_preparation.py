"""Only the new frozen native loading boundary; no accepted query gates rerun."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def loader(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    import prepare_native_stores
    return prepare_native_stores


def source(tmp_path, module):
    batches = [
        {'kind': 'constraint', 'statement': 'CREATE CONSTRAINT x FOR (n:N) REQUIRE n.id IS UNIQUE'},
        {'kind': 'nodes', 'statement': 'UNWIND $rows AS r CREATE (:N {id:r.id})', 'parameters': {'rows': []}},
        {'kind': 'nodes', 'statement': 'UNWIND $rows AS r CREATE (:N {id:r.id})', 'parameters': {'rows': [{'id': 1}, {'id': 2}]}},
        {'kind': 'relationships', 'statement': 'MATCH (a:N),(b:N) WHERE a.id=1 AND b.id=2 CREATE (a)-[:R]->(b)',
         'parameters': {'rows': [{}]}},
    ]
    native = tmp_path/'load_neo4j_batches.jsonl'
    native.write_text(''.join(json.dumps(b)+'\n' for b in batches))
    control = tmp_path/'control.ttl';control.write_text('<urn:1> <urn:p> <urn:2> .\n')
    files = {}
    for p in (native, control):
        pin = module.stream_pin(p)
        files[p.name] = {'path': p.name, 'sha256': pin['sha256'], 'size_bytes': pin['bytes']}
    return {'offline': {'materialization_root': str(tmp_path), 'load_files': files}}, native


def test_changed_inputs_rejected_before_any_service_start(tmp_path, loader):
    doc, native = source(tmp_path, loader)
    pins, counts = loader.input_sources(doc)
    assert counts == {'nodes': 2, 'relationships': 1, 'load_calls': 3}
    assert [index for index, _, _ in loader.batches(native)] == [0, 2, 3]
    native.write_text(native.read_text()+'\n')
    with pytest.raises(ValueError, match='Native input changed'):
        loader.input_sources(doc)


def test_first_load_failure_preserved_without_retry_or_later_batches(tmp_path, loader):
    _, native = source(tmp_path, loader);out = tmp_path/'out';out.mkdir();calls = []
    class Client:
        def execute(self, artifact):
            calls.append(artifact.artifact_id)
            return SimpleNamespace(success=False, error='recorded native transaction error',
                                   to_dict=lambda: {'success': False, 'error': 'recorded native transaction error'})
    with pytest.raises(RuntimeError, match='Native batch 0 failed; no retry'):
        loader.load_batches(Client(), native, out)
    assert calls == ['load-0']
    assert sorted(p.name for p in out.iterdir()) == ['batch-0000-intent.json', 'batch-0000-result.json']
    assert json.loads((out/'batch-0000-result.json').read_text())['error'] == 'recorded native transaction error'


def test_silent_missing_relationships_prevent_store_acceptance(tmp_path, loader):
    calls = []
    class Client:
        def execute(self, artifact):
            calls.append(artifact.text)
            rows = [{'count': 2 if len(calls) == 1 else 0}]
            return SimpleNamespace(success=True, rows=rows, to_dict=lambda: {'success': True, 'rows': rows})
    with pytest.raises(ValueError, match='count differs.*relationships'):
        loader.verify_counts(Client(), {'nodes': 2, 'relationships': 1}, tmp_path)
    assert len(calls) == 2
    assert json.loads((tmp_path/'integrity-relationships-result.json').read_text())['rows'] == [{'count': 0}]


def test_compressed_core_load_uses_sealed_external_paths(tmp_path, loader):
    import gzip
    doc,native=source(tmp_path,loader)
    compressed=tmp_path/'core.jsonl.gz'
    with gzip.open(compressed,'wb') as f:f.write(native.read_bytes())
    native_pin=loader.stream_pin(compressed)
    control_pin=loader.stream_pin(tmp_path/'control.ttl')
    doc['offline']['native_load_files']={'load_neo4j_batches.jsonl':native_pin,'control.ttl':control_pin}
    sources,counts=loader.input_sources(doc)
    assert counts=={'nodes':2,'relationships':1,'load_calls':3}
    assert sources['load_neo4j_batches.jsonl']==native_pin
    with compressed.open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='Native input changed'):loader.input_sources(doc)
