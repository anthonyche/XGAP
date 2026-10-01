import base64
import gzip
import hashlib
import json
from pathlib import Path

from ch6_failure_archive import collect_failure_evidence


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    path.write_bytes(raw)
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def fixture(root, *, status='method_error', kind='federation', body=b'MalformedQueryException',
            native=False, failed=True, sealed=True):
    cell = root / 'units/u/cells/c'
    directory = (root / 'units/u/sessions/1/source-observations' if kind == 'source' else
                 cell / ('external-services/' + kind + '-observations'))
    directory.mkdir(parents=True)
    response = directory / '0000-response.bin.gz'
    raw = gzip.compress(body)
    response.write_bytes(raw)
    record = dict(index=0, phase='p', generation=1, status='returned', http_status=500 if failed else 200,
        query='SELECT * WHERE {?s ?p ?o}', response_complete=True, response_path=str(response),
        response_encoding='gzip', response_storage_pin=dict(path=str(response),
            sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)),
        response_sha256=hashlib.sha256(body).hexdigest(), observer_wall_ms=12.5,
        headers={'Authorization': 'NEVER_EXPORT'}, error='NEVER_EXPORT')
    if native:
        record.update(query_language='cypher', native_statements=[dict(statement='RETURN 1',
            parameters={'a': 1}, headers={'secret': 'NEVER_EXPORT'})])
    rp = write(directory / '0000-result.json', record)
    index = write(directory / 'phase-0001-index.json', dict(phase='p', generation=1,
        result_pattern='{index:04}-result.json', files=[[0, rp['sha256']]]))
    seal = write(directory / 'phase-0001-summary.json', dict(phase='p', generation=1))
    observation = dict(phase='p', generation=1, record_directory=str(directory), ledger_index=index, phase_seal=seal)
    outcome = write(cell / 'execution/receipt.json', dict(status=status, observations={kind: observation,
        'model': {'record_directory': str(root / 'SHOULD_NOT_BE_OPENED')}}))
    if sealed:
        write(cell / 'terminal.json', dict(cell_id='c', outcome=outcome))
    return cell, directory


def reports(output):
    return [json.loads(p.read_text()) for p in sorted(output.glob('failure-*.json'))]


def test_exports_only_sealed_public_failure_and_exact_bounded_response(tmp_path):
    root = tmp_path / 'runs'; output = tmp_path / 'archive'
    fixture(root)
    result = collect_failure_evidence(root, output)
    records = reports(output)
    assert result['complete'] and result['counts']['exported_records'] == 1
    public = records[0]['public_result']
    assert public['query'] == 'SELECT * WHERE {?s ?p ?o}'
    assert public['http_status'] == 500 and public['observer_wall_ms'] == 12.5
    assert 'headers' not in public and 'error' not in public
    response = records[0]['response']
    assert base64.b64decode(response['decoded_prefix_base64']) == b'MalformedQueryException'
    assert response['storage_pin_verified'] and response['decoded_sha256_verified']
    assert not response['truncated']
    assert 'NEVER_EXPORT' not in ''.join(p.read_text() for p in output.glob('*.json'))


def test_http200_neo4j_errors_are_failures_but_successes_and_unsealed_ignored(tmp_path):
    root = tmp_path / 'runs'; output = tmp_path / 'archive'
    fixture(root, kind='source', native=True, failed=False,
            body=b'{"results":[],"errors":[{"code":"SyntaxError"}]}')
    result = collect_failure_evidence(root, output)
    assert result['counts']['exported_records'] == 1
    assert reports(output)[0]['native_errors_detected']
    root2 = tmp_path / 'unsealed'; fixture(root2, sealed=False)
    assert not collect_failure_evidence(root2, tmp_path / 'unused')['counts'].get('exported_records')
    root3 = tmp_path / 'answered'; fixture(root3, status='answered')
    assert not collect_failure_evidence(root3, tmp_path / 'success')['counts'].get('exported_records')


def test_hash_failures_and_missing_raw_preserve_omissions_without_changing_outcome(tmp_path):
    root = tmp_path / 'runs'; output = tmp_path / 'archive'
    cell, directory = fixture(root)
    before = (cell / 'execution/receipt.json').read_bytes()
    (directory / '0000-response.bin.gz').unlink()
    result = collect_failure_evidence(root, output)
    assert not result['complete'] and result['counts']['exported_records'] == 1
    assert reports(output)[0]['public_result']['query']
    assert not reports(output)[0]['response']['available']
    assert (cell / 'execution/receipt.json').read_bytes() == before
    root2 = tmp_path / 'bad'; _, d2 = fixture(root2)
    (d2 / '0000-result.json').write_text('{}')
    result2 = collect_failure_evidence(root2, tmp_path / 'badarchive')
    assert not result2['complete'] and not result2['counts'].get('exported_records')
    assert 'ValueError:evidence_pin_mismatch' in result2['omission_counts']


def test_export_and_response_prefix_caps_with_symlink_exclusion(tmp_path):
    root = tmp_path / 'runs'; fixture(root, body=b'e' * 400000)
    result = collect_failure_evidence(root, tmp_path / 'archive')
    row = reports(tmp_path / 'archive')[0]
    assert row['response']['truncated'] and row['response']['decoded_prefix_bytes'] == 256 * 1024
    limited = collect_failure_evidence(root, tmp_path / 'limited', max_total_bytes=16384)
    assert limited['export_bytes'] <= 16384 and limited['omission_counts']['total_export_cap'] == 1
    root2 = tmp_path / 'linked'; _, directory = fixture(root2)
    response = directory / '0000-response.bin.gz'
    response.unlink(); response.symlink_to(tmp_path / 'credential-must-not-open')
    result2 = collect_failure_evidence(root2, tmp_path / 'linkarchive')
    assert not result2['complete'] and not reports(tmp_path / 'linkarchive')[0]['response']['available']
