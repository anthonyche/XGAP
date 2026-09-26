"""Bounded filesystem-only TS diagnosis; deliberately no executable backend."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

import collect_ch6_small48_ts_failures as collector


def put(root, relative, value, raw=False):
    data = value if raw else collector.encoded(value)
    path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    return {'path': str(collector.SERVER_ROOT / relative), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def fixture(root, *, oversized=False, forbidden=False):
    case = 'D1-test-uniform-bounded_path-000-W4-TS'
    base = Path('small48-results-b86ada5-v1/units/D1-rdf-small-r0/cells') / case
    fed = base / 'external-services/federation-observations'
    phase = 'aruqula:D1-test-uniform-bounded_path-000-W4'
    text = b'HTTP 500 org.eclipse.rdf4j.query.QueryEvaluationException: malformed query\n'
    text += b'Authorization: Bearer should-never-export-this-secret\n'
    if oversized: text += b'x' * collector.MAX_RESPONSE
    response = put(root, fed / '0000-response.bin.gz', gzip.compress(text), raw=True)
    record = dict(index=0, phase=phase, generation=1, status='returned', http_status=500,
                  failure_category='upstream_http_failure', response_path=response['path'],
                  response_encoding='gzip', response_storage_pin=response,
                  response_sha256=collector.sha(text), query='SELECT * WHERE { ?s ?p ?o }')
    if forbidden:
        model = put(root, base / 'external-services/model-observations/0000-response.bin.gz',
                    gzip.compress(b'not permitted to read'), raw=True)
        record.update(response_path=model['path'], response_storage_pin=model)
    result = put(root, fed / '0000-result.json', record)
    index = put(root, fed / 'phase-0001-index.json', dict(phase=phase, generation=1,
                result_pattern='{index:04}-result.json', files=[[0, result['sha256']]]))
    seal = put(root, fed / 'phase-0001-summary.json', dict(phase=phase, generation=1,
                requests=1, forwarded_requests=1, failed_requests=1))
    worker = put(root, base / 'execution/worker/receipt.json', dict(status='method_error', error_type='HTTPError',
                author_output={'path': '/do-not-open', 'bytes': 10, 'sha256': 'f'*64}))
    trial = put(root, base / 'execution/receipt.json', dict(status='method_error', worker=worker,
                observations={'federation': dict(phase=phase, record_directory=str(collector.SERVER_ROOT/fed),
                                                ledger_index=index, phase_seal=seal)}))
    case = dict(case_id=case, receipt=trial, worker=worker, ledger_index=index, phase_seal=seal)
    archive = put(root, 'small48-b86ada5-v1/archive-index.json', dict(files=[trial, worker, seal]))
    return case, archive


def read_archive(path):
    with tarfile.open(path) as package:
        return {m.name: json.load(package.extractfile(m)) for m in package.getmembers()}


def test_pinned_typed_collection_preserves_raw_inputs_and_marks_truncation(tmp_path, monkeypatch):
    root = tmp_path/'sources'; case, index = fixture(root, oversized=True)
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    monkeypatch.setattr('socket.socket.connect', lambda *a, **k: pytest.fail('No network'))
    output = tmp_path/'diagnostics.tar.gz'
    report = collector.collect(root, output, cases=[case], archive_index=index)
    assert report['success'] and report['failed_responses'] == 1
    assert report['network_calls'] == report['backend_calls'] == report['model_calls'] == 0
    members = read_archive(output); result = members['cases/'+case['case_id']+'.json']
    response = result['failed_records'][0]['response']
    assert response['truncated'] and response['decoded_prefix_bytes'] == collector.MAX_RESPONSE
    assert response['diagnostics']['exception_types'] == ['org.eclipse.rdf4j.query.QueryEvaluationException']
    assert response['diagnostics']['http_status_mentions'] == [500]
    assert not result['author_output']['content_read']
    assert 'should-never-export-this-secret' not in json.dumps(members)
    assert 'Authorization' not in json.dumps(members)
    assert sum(map(len, [collector.encoded(m) for m in members.values()])) < collector.MAX_EXPORT
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError): collector.collect(root, output, cases=[case], archive_index=index)


def test_response_path_cannot_route_collection_into_model_records(tmp_path, monkeypatch):
    root = tmp_path/'sources'; case, index = fixture(root, forbidden=True)
    original = Path.open
    def guarded(path, *args, **kwargs):
        assert 'model-observations' not in path.parts
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    output = tmp_path/'diagnostics.tar.gz'
    result = collector.collect(root, output, cases=[case], archive_index=index)
    assert not result['success'] and result['unavailable'] == 1
    assert not result['failed_responses']


def test_phase_missing_is_explicit_and_hash_changes_are_rejected(tmp_path):
    root = tmp_path/'sources'; case, index = fixture(root)
    collector.path_at(root, case['ledger_index']['path']).unlink()
    result = collector.collect(root, tmp_path/'missing.tar.gz', cases=[case], archive_index=index)
    assert not result['success'] and result['unavailable'] == 1
    collector.path_at(root, case['worker']['path']).write_text('{}')
    with pytest.raises(ValueError, match='hash/size'):
        collector.collect(root, tmp_path/'changed.tar.gz', cases=[case], archive_index=index)
