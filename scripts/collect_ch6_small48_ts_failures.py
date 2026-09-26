#!/usr/bin/env python3
"""Read-only, bounded diagnostics for the three frozen 3886776 TS exceptions.

No query is executed; no network, model record, credential or author-output is read.
Federation observation results, their public SPARQL and capped response prefixes
are inspected. Query text is retained exactly for offline parser diagnosis;
arbitrary logs, headers and model transcripts are excluded.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


SERVER_ROOT = Path('/home/hxc859/xgap-ch6-artifacts')
DEFAULT_OUTPUT = Path('/home/hxc859/xgap-small48-ts-errors-3886776-v2.tar.gz')
MAX_EXPORT = 4 * 1024**2
MAX_RESPONSE = 256 * 1024
MAX_METADATA = 1024**2
MAX_QUERY_EXPORT = 64 * 1024
MAX_STORED_RESPONSE = 8 * 1024**2
# Generated only from the verified archive's three method_error receipts.
CASES = [{'case_id': 'D1-test-uniform-bounded_path-000-W4-TS', 'receipt': {'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D1-rdf-small-r0/cells/D1-test-uniform-bounded_path-000-W4-TS/execution/receipt.json', 'sha256': '410773ee40aa849731845a603cd2c93c0833983390328313211b74634d4968b3', 'bytes': 14078}, 'worker': {'bytes': 2312, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D1-rdf-small-r0/cells/D1-test-uniform-bounded_path-000-W4-TS/execution/worker/receipt.json', 'sha256': '05d2e7c43a8884f2450fcb048990d0510a52a9f856bc17a5ccf9a3f6e446c508'}, 'ledger_index': {'bytes': 1155, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D1-rdf-small-r0/cells/D1-test-uniform-bounded_path-000-W4-TS/external-services/federation-observations/phase-0001-index.json', 'sha256': '3c7577911f4fb30942ce65c49401680c74de08e916205f27f7de10c32145b6ec'}, 'phase_seal': {'bytes': 1392, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D1-rdf-small-r0/cells/D1-test-uniform-bounded_path-000-W4-TS/external-services/federation-observations/phase-0001-summary.json', 'sha256': '8dd15c4340587b0a0d810bb9769687915580ef29c068281dabf42d91974a82de'}}, {'case_id': 'D3-test-uniform-bounded_path-000-W1-TS', 'receipt': {'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-bounded_path-000-W1-TS/execution/receipt.json', 'sha256': '21d708f220f99564600ce911dc775b8eda0a46eb9c31e2d6d0c84b6a7fad46b0', 'bytes': 13336}, 'worker': {'bytes': 2311, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-bounded_path-000-W1-TS/execution/worker/receipt.json', 'sha256': '7828b3a285a018261a6e64faa94a810a440a6a6b338ec4702efae02a4e6194a0'}, 'ledger_index': {'bytes': 567, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-bounded_path-000-W1-TS/external-services/federation-observations/phase-0001-index.json', 'sha256': '41ade3589db615ac6304acd71cf06ae05ffeef7069f7f411939de4fe51ab3612'}, 'phase_seal': {'bytes': 1385, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-bounded_path-000-W1-TS/external-services/federation-observations/phase-0001-summary.json', 'sha256': 'c9bd8b5e58d4d2db165d9051257ff3904136f340deb174509443bdb77f460d45'}}, {'case_id': 'D3-test-uniform-cycle-000-W3-TS', 'receipt': {'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-cycle-000-W3-TS/execution/receipt.json', 'sha256': '159a9a74e7abb0ab34ad357834e9acf14d89849e6ad40f017cd6505e934a6df6', 'bytes': 13408}, 'worker': {'bytes': 2582, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-cycle-000-W3-TS/execution/worker/receipt.json', 'sha256': '6c0a70fc4fcc7b35cc28fd952db4b37966a9988d6431f10b8c027609e1d8ddc7'}, 'ledger_index': {'bytes': 926, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-cycle-000-W3-TS/external-services/federation-observations/phase-0001-index.json', 'sha256': '8c45f79175d2e911c709bbfb0ff41fab594689105e2f79561d245bee386ba21c'}, 'phase_seal': {'bytes': 1373, 'path': '/home/hxc859/xgap-ch6-artifacts/small48-results-b86ada5-v1/units/D3-rdf-small-r0/cells/D3-test-uniform-cycle-000-W3-TS/external-services/federation-observations/phase-0001-summary.json', 'sha256': '8a0b22975ea10ab02ddca61caadab6cf428a233e3bf8b9cd08d0c91aed9bb73c'}}]
ARCHIVE_INDEX = {'path': '/home/hxc859/xgap-ch6-artifacts/small48-b86ada5-v1/archive-index.json', 'sha256': '7d86b7bc38b6e58b8f1bbdd640dc9af99f8bb171a220e3de685ba436af12f3eb', 'bytes': 749478}


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode()


def sha(data): return hashlib.sha256(data).hexdigest()


def path_at(root, original):
    relative = Path(original).relative_to(SERVER_ROOT)
    path = root / relative
    # Do not follow even an in-root symlink to a model/credential file.
    if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise ValueError('Symlink input refused')
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise ValueError('Input escapes the frozen source root') from error
    return path


def pinned_json(root, pin):
    path = path_at(root, pin['path'])
    with path.open('rb') as stream: raw = stream.read(MAX_METADATA + 1)
    if len(raw) > MAX_METADATA:
        raise ValueError('Metadata input exceeds bounded read')
    if len(raw) != pin['bytes'] or sha(raw) != pin['sha256']:
        raise ValueError('Frozen input hash/size mismatch')
    return json.loads(raw)


def classes(text):
    # Only syntactic exception class names are exported; never free-form messages.
    return sorted(set(re.findall(r'\b(?:[A-Za-z_][A-Za-z0-9_$]*\.)*'
                                r'[A-Z][A-Za-z0-9_$]*(?:Exception|Error)\b', text)))[:32]


def diagnostics(text):
    known = {
        'malformed_query': r'malformed\s*query|parseexception|queryparseexception|syntax\s+error',
        'unsupported_operation': r'unsupportedoperationexception|unsupported\s+(?:function|operation|query)',
        'query_evaluation': r'queryevaluationexception',
        'timeout': r'timeout|timed\s+out',
        'connection_failure': r'connectexception|connection\s+(?:refused|reset)|unknownhostexception',
        'authentication_failure': r'unauthorized|forbidden|authentication\s+failed',
        'memory_limit': r'outofmemoryerror|memory\s+(?:limit|budget)|allocation.*limit',
        'budget_limit': r'budget\s+(?:exceeded|exhausted)|harness_call_budget',
    }
    return {'exception_types': classes(text),
            'markers': sorted(k for k, pattern in known.items() if re.search(pattern, text, re.I)),
            'http_status_mentions': sorted(set(int(v) for v in re.findall(
                r'\bHTTP(?:/\d(?:\.\d)?)?\s+(?:Error\s+)?([45]\d\d)\b', text, re.I)))}


def selected(value, fields):
    return {k: value[k] for k in fields if k in value and
            (value[k] is None or type(value[k]) in (bool, int, float))}


def enum_fields(value, fields):
    return {k: value[k] for k in fields if isinstance(value.get(k), str)
            and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value[k])}


def response_summary(root, record, directory):
    original = record.get('response_path')
    if not original:
        return {'available': False, 'reason': 'no_recorded_response_path'}
    expected = directory / ('%04d-response.bin' % record['index'])
    if record.get('response_encoding') == 'gzip': expected = expected.with_suffix('.bin.gz')
    if Path(original) != expected:
        raise ValueError('Response is not this federation record body')
    path = path_at(root, original)
    storage = record.get('response_storage_pin')
    if storage is not None and storage['path'] != original:
        raise ValueError('Response storage pin path mismatch')
    size = path.stat().st_size
    if size > MAX_STORED_RESPONSE:
        return {'available': False, 'reason': 'stored_response_read_cap', 'source_path': original,
                'source_bytes': size, 'recorded_storage_pin': storage,
                'recorded_decoded_sha256': record.get('response_sha256')}
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''): digest.update(block)
    observed = {'path': original, 'sha256': digest.hexdigest(), 'bytes': size}
    if storage is not None and observed != storage:
        raise ValueError('Frozen response storage hash mismatch')
    opener = gzip.open if record.get('response_encoding') == 'gzip' else open
    with opener(path, 'rb') as stream: prefix = stream.read(MAX_RESPONSE + 1)
    truncated = len(prefix) > MAX_RESPONSE
    prefix = prefix[:MAX_RESPONSE]
    decoded_hash = record.get('response_sha256')
    if not truncated and decoded_hash is not None and sha(prefix) != decoded_hash:
        raise ValueError('Frozen decoded response hash mismatch')
    return {'available': True, 'storage_pin': observed,
            'recorded_decoded_sha256': decoded_hash, 'decoded_prefix_sha256': sha(prefix),
            'decoded_prefix_bytes': len(prefix), 'truncated': truncated,
            'prefix_limit_bytes': MAX_RESPONSE,
            'diagnostics': diagnostics(prefix.decode('utf-8', errors='replace')),
            'raw_content_exported': False}


def collect_case(root, spec):
    trial = pinned_json(root, spec['receipt'])
    worker = pinned_json(root, spec['worker'])
    if trial.get('status') != 'method_error' or trial.get('worker') != spec['worker']:
        raise ValueError('Expected the frozen method_error worker')
    federation = trial['observations']['federation']
    if any(federation[k] != spec[k] for k in ('ledger_index', 'phase_seal')):
        raise ValueError('Frozen federation phase changed')
    case_root = Path(spec['receipt']['path']).parent.parent
    directory = case_root / 'external-services/federation-observations'
    if Path(federation['record_directory']) != directory:
        raise ValueError('Unexpected federation observation directory')
    report = {'case_id': spec['case_id'], 'input_pins': spec,
        'trial': {**enum_fields(trial, ('status', 'guard_status')),
                  **selected(trial, ('final_plan_executions', 'worker_ms'))},
        'worker': {**enum_fields(worker, ('status', 'error_type')),
                   **selected(worker, ('final_query_submissions', 'wrapper_retries'))},
        'author_output': {'pin': worker.get('author_output'),
                          'content_read': False, 'reason': 'may_contain_model_content'},
        'failed_records': [], 'unavailable': []}
    try:
        seal = pinned_json(root, spec['phase_seal'])
        index = pinned_json(root, spec['ledger_index'])
    except (OSError, ValueError) as error:
        report['unavailable'].append({'component': 'federation_phase', 'error_type': type(error).__name__})
        return report
    if (seal['phase'] != federation['phase'] or index['phase'] != seal['phase']
            or index['generation'] != seal['generation'] or index['result_pattern'] != '{index:04}-result.json'
            or len(index['files']) > 256):
        raise ValueError('Federation phase index does not match its seal')
    report['federation'] = {**selected(seal, ('requests', 'forwarded_requests', 'failed_requests')),
                            'phase': seal['phase']}
    seen = set()
    for number, digest in index['files']:
        if type(number) is not int or not 0 <= number < 1000000 or number in seen:
            raise ValueError('Invalid/duplicate result index')
        seen.add(number)
        original = directory / ('%04d-result.json' % number)
        try:
            path = path_at(root, original)
            record = pinned_json(root, {'path': str(original), 'sha256': digest, 'bytes': path.stat().st_size})
            if record['index'] != number or record['phase'] != index['phase'] or record['generation'] != index['generation']:
                raise ValueError('Result does not belong to the sealed phase')
            if (record.get('status') == 'returned' and record.get('http_status', 599) < 400
                    and not record.get('failure_category')):
                continue
            result = {'result_pin': {'path': str(original), 'sha256': digest, 'bytes': path.stat().st_size},
                **enum_fields(record, ('status', 'error_type', 'failure_category', 'query_kind')),
                **selected(record, ('index', 'http_status', 'forwarded', 'response_complete',
                                    'observer_wall_ms', 'response_body_bytes')),
                'error_diagnostics': diagnostics(str(record.get('error', '')))}
            # A hash alone cannot distinguish an author syntax error from a FedX
            # internal query error. Preserve the exact public submitted SPARQL,
            # never the request headers, model transcript or private intent.
            query = record.get('query')
            if isinstance(query, str):
                query_raw = query.encode('utf-8')
                result['query_identity'] = {'sha256': sha(query_raw), 'bytes': len(query_raw)}
                result['query_exported'] = len(query_raw) <= MAX_QUERY_EXPORT
                if result['query_exported']:
                    result['query'] = query
                else:
                    result['query_unavailable_reason'] = 'query_export_cap'
            else:
                result['query_exported'] = False
                result['query_unavailable_reason'] = 'no_recorded_query'
            result['response'] = response_summary(root, record, directory)
            report['failed_records'].append(result)
        except (OSError, ValueError, KeyError) as error:
            report['unavailable'].append({'component': 'federation_record', 'index': number,
                'source_path': str(original), 'error_type': type(error).__name__})
    report['all_failed_records_collected'] = (not report['unavailable'] and
        len(report['failed_records']) == seal['failed_requests'])
    return report


def collect(root, output, *, cases=CASES, archive_index=ARCHIVE_INDEX):
    root = Path(root).resolve(); output = Path(output)
    sidecar = output.with_suffix(output.suffix + '.receipt.json')
    if output.exists() or sidecar.exists(): raise FileExistsError('Existing collection; preserve it')
    archive = pinned_json(root, archive_index)
    indexed = {p['path']: p for p in archive['files']}
    for case in cases:
        for name in ('receipt', 'worker', 'phase_seal'):
            if indexed.get(case[name]['path']) != case[name]:
                raise ValueError('Case pins differ from the verified archive index')
    members = {'manifest.json': encoded({'schema_version': 'xgap-small48-ts-error-manifest-v2',
        'job_id': '3886776', 'archive_index': archive_index, 'cases': cases,
        'archive_missing_coordinates': [c['ledger_index']['path'] for c in cases
            if c['ledger_index']['path'] not in indexed],
        'read_scope': 'frozen trial/worker summaries; federation results, public SPARQL and response prefixes only',
        'excluded': ['model observations', 'credentials', 'headers', 'author-output content', 'query execution'],
        'max_export_bytes': MAX_EXPORT, 'max_response_prefix_bytes': MAX_RESPONSE,
        'max_query_export_bytes': MAX_QUERY_EXPORT})}
    reports = [collect_case(root, case) for case in cases]
    for report in reports:
        members['cases/' + report['case_id'] + '.json'] = encoded(report)
    receipt = {'schema_version': 'xgap-small48-ts-error-collection-v2',
        'success': all(r.get('all_failed_records_collected', False) for r in reports),
        'cases': len(reports), 'failed_responses': sum(len(r['failed_records']) for r in reports),
        'unavailable': sum(len(r['unavailable']) for r in reports),
        'model_calls': 0, 'backend_calls': 0, 'network_calls': 0, 'submitted_jobs': 0,
        'raw_sources_modified': False, 'raw_response_exported': False,
        'public_query_texts_exported': sum(bool(record.get('query_exported'))
            for report in reports for record in report['failed_records']),
        'members': [{'path': name, 'bytes': len(raw), 'sha256': sha(raw)} for name, raw in members.items()]}
    members['receipt.json'] = encoded(receipt)
    if sum(map(len, members.values())) > MAX_EXPORT - 65536:
        raise ValueError('Bounded export exhausted; no archive written')
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, raw in members.items():
            info = tarfile.TarInfo(name); info.size = len(raw); info.mode = 0o600
            archive.addfile(info, io.BytesIO(raw))
    raw = buffer.getvalue()
    if len(raw) > MAX_EXPORT: raise ValueError('Archive exceeds four MiB')
    with output.open('xb') as stream: stream.write(raw)
    result = {**receipt, 'archive': {'path': str(output), 'bytes': len(raw), 'sha256': sha(raw)},
              'archive_receipt_sha256': sha(members['receipt.json'])}
    with sidecar.open('xb') as stream: stream.write(encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', default=str(SERVER_ROOT))
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    result = collect(args.source_root, args.output)
    print(json.dumps({k: result[k] for k in ('success', 'cases', 'failed_responses', 'unavailable', 'archive', 'archive_receipt_sha256')}))


if __name__ == '__main__': main()
