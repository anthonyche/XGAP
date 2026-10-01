"""Bounded, read-only export of public source failures from sealed study cells.

This is post-execution evidence collection. It never opens model observations,
request headers, author output, credentials, unsealed phases, or query services.
Missing evidence and export limits are reported without changing study results.
"""
import base64
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re


MIB = 1024**2
MAX_METADATA = 4 * MIB
MAX_PREFIX = 256 * 1024
MAX_STORED_RESPONSE = 64 * MIB
MAX_RECORDS_PER_PHASE = 10000
KINDS = ('source', 'federation', 'lookup')


def _raw(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(path, raw):
    return dict(path=str(path), sha256=_sha(raw), bytes=len(raw))


def _safe(root, path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('nonabsolute_evidence_path')
    relative = path.relative_to(root)
    if '..' in relative.parts or any('model-observations' in part for part in relative.parts):
        raise ValueError('excluded_evidence_path')
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink_evidence_path')
    return path


def _read(root, pin):
    path = _safe(root, pin['path'])
    with path.open('rb') as stream:
        raw = stream.read(MAX_METADATA + 1)
    if len(raw) > MAX_METADATA:
        raise ValueError('metadata_read_cap')
    if _sha(raw) != pin['sha256'] or ('bytes' in pin and len(raw) != pin['bytes']):
        raise ValueError('evidence_pin_mismatch')
    return json.loads(raw)


def _response(root, record, directory, *, verify_storage):
    original = record.get('response_path')
    if not original:
        return None, dict(available=False, reason='no_recorded_response')
    name = f"{record['index']:04}-response.bin"
    if record.get('response_encoding') == 'gzip':
        name += '.gz'
    elif record.get('response_encoding') not in (None, 'identity'):
        raise ValueError('unknown_response_encoding')
    if Path(original) != directory / name:
        raise ValueError('response_path_not_record_body')
    path = _safe(root, original)
    size = path.stat().st_size
    opener = gzip.open if record.get('response_encoding') == 'gzip' else open
    with opener(path, 'rb') as stream:
        prefix = stream.read(MAX_PREFIX + 1)
    truncated = len(prefix) > MAX_PREFIX
    prefix = prefix[:MAX_PREFIX]
    result = dict(available=True, source_path=original, source_storage_bytes=size,
                  recorded_storage_pin=record.get('response_storage_pin'),
                  recorded_decoded_sha256=record.get('response_sha256'),
                  decoded_prefix_bytes=len(prefix), decoded_prefix_sha256=_sha(prefix),
                  prefix_limit_bytes=MAX_PREFIX, truncated=truncated,
                  storage_pin_verified=False, decoded_sha256_verified=False)
    if not truncated and record.get('response_sha256') is not None:
        if _sha(prefix) != record['response_sha256']:
            raise ValueError('decoded_response_pin_mismatch')
        result['decoded_sha256_verified'] = True
    if verify_storage:
        storage = record.get('response_storage_pin')
        if storage is not None and storage['path'] != original:
            raise ValueError('response_storage_path_mismatch')
        if size <= MAX_STORED_RESPONSE:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(65536), b''):
                    digest.update(block)
            observed = dict(path=original, sha256=digest.hexdigest(), bytes=size)
            if storage is not None and observed != storage:
                raise ValueError('response_storage_pin_mismatch')
            result['observed_storage_pin'] = observed
            result['storage_pin_verified'] = storage is not None
        else:
            result['storage_verification_omitted'] = 'stored_response_read_cap'
    return prefix, result


def _public_result(record):
    # Deliberately exclude arbitrary headers, URLs, author output and free-form
    # exception messages. Queries and native parameters are public source inputs.
    fields = ('index', 'phase', 'generation', 'status', 'http_status', 'failure_category',
              'error_type', 'query_kind', 'query_language', 'forwarded', 'response_complete',
              'observer_wall_ms', 'request_body_bytes', 'response_body_bytes')
    public = {k: record[k] for k in fields if k in record and
              (record[k] is None or type(record[k]) in (str, bool, int, float))}
    if isinstance(record.get('query'), str):
        public['query'] = record['query']
    if isinstance(record.get('native_statements'), list):
        public['native_statements'] = [
            {k: row[k] for k in ('statement', 'parameters', 'resultDataContents', 'includeStats') if k in row}
            for row in record['native_statements'] if isinstance(row, dict)]
    return public


def collect_failure_evidence(evidence_root, output_root, *, max_total_bytes=32 * MIB):
    """Export sealed failures to a new directory; omissions do not fail the study.

    All referenced paths must be inside evidence_root. Call after worker/source
    shutdown. The return value includes a pinned report and counts, not outcomes.
    """
    root = Path(evidence_root).absolute()
    output = Path(output_root).absolute()
    if root.is_symlink() or root.resolve() != root:
        raise ValueError('evidence_root_must_be_resolved_without_symlinks')
    if type(max_total_bytes) is not int or max_total_bytes < 16384:
        raise ValueError('failure_export_budget_too_small')
    output.mkdir(parents=True, exist_ok=False)
    reserve = min(MIB, max_total_bytes // 2)
    record_budget = max_total_bytes - reserve
    used = 0
    exported = []
    omitted = []
    reasons = Counter()
    counts = Counter()
    omission_bytes = 0

    def omit(reason, **coordinates):
        nonlocal omission_bytes
        reasons[reason] += 1
        item = dict(reason=reason, **coordinates)
        length = len(_raw(item))
        if omission_bytes + length <= reserve // 2:
            omitted.append(item)
            omission_bytes += length

    terminals = sorted(root.glob('units/*/cells/*/terminal.json'))
    for terminal_path in terminals:
        counts['sealed_cell_candidates'] += 1
        cell_id = terminal_path.parent.name
        try:
            safe_terminal = _safe(root, terminal_path)
            with safe_terminal.open('rb') as stream:
                terminal_raw = stream.read(MAX_METADATA + 1)
            if len(terminal_raw) > MAX_METADATA:
                raise ValueError('terminal_read_cap')
            terminal = json.loads(terminal_raw)
            if terminal['cell_id'] != cell_id:
                raise ValueError('terminal_cell_mismatch')
            outcome_pin = terminal['outcome']
            if Path(outcome_pin['path']) != terminal_path.parent / 'execution' / 'receipt.json':
                raise ValueError('outcome_path_not_cell_receipt')
            outcome = _read(root, outcome_pin)
            if outcome.get('status') in ('answered', 'success'):
                continue
            counts['failed_cells'] += 1
            observations = {k: v for k, v in (outcome.get('observations') or {}).items() if k in KINDS}
            if 'source' not in observations and outcome.get('source_observations'):
                observations['source'] = outcome['source_observations']
            for kind, observation in observations.items():
                directory = Path(observation.get('record_directory', ''))
                coordinates = dict(cell_id=cell_id, kind=kind)
                try:
                    directory = _safe(root, directory)
                    if directory.name != kind + '-observations':
                        raise ValueError('observation_directory_kind_mismatch')
                    if kind != 'source' and directory != terminal_path.parent / 'external-services' / (kind + '-observations'):
                        raise ValueError('external_phase_not_this_cell')
                    if kind == 'source' and directory.relative_to(terminal_path.parents[2]).parts[0] != 'sessions':
                        raise ValueError('source_phase_not_this_unit')
                    seal_pin, index_pin = observation['phase_seal'], observation['ledger_index']
                    for pin in (seal_pin, index_pin):
                        if Path(pin['path']).parent != directory:
                            raise ValueError('phase_pin_directory_mismatch')
                    seal = _read(root, seal_pin)
                    index = _read(root, index_pin)
                    if (seal['phase'] != observation['phase'] or seal['generation'] != observation['generation']
                            or index['phase'] != seal['phase'] or index['generation'] != seal['generation']
                            or index['result_pattern'] != '{index:04}-result.json'
                            or len(index['files']) > MAX_RECORDS_PER_PHASE):
                        raise ValueError('phase_identity_mismatch')
                    counts['sealed_phases'] += 1
                    seen = set()
                    for number, digest in index['files']:
                        if type(number) is not int or not 0 <= number < 1000000 or number in seen:
                            raise ValueError('invalid_result_index')
                        seen.add(number)
                        loc = dict(**coordinates, index=number)
                        try:
                            pin = dict(path=str(directory / f'{number:04}-result.json'), sha256=digest)
                            record = _read(root, pin)
                            if any(record[k] != v for k, v in dict(index=number, phase=index['phase'], generation=index['generation']).items()):
                                raise ValueError('result_phase_mismatch')
                            failed = (record.get('http_status', 200) >= 400 or bool(record.get('failure_category'))
                                      or record.get('status') != 'returned')
                            native = record.get('query_language') == 'cypher' or bool(record.get('native_statements'))
                            if not failed and not native:
                                continue
                            try:
                                prefix, response = _response(root, record, directory, verify_storage=failed)
                            except (OSError, ValueError, EOFError) as error:
                                omit(type(error).__name__ + ':response_unavailable', **loc)
                                prefix, response = None, dict(available=False, reason='response_unavailable',
                                    error_type=type(error).__name__, recorded_storage_pin=record.get('response_storage_pin'))
                            native_error = False
                            if not failed and prefix is not None:
                                try:
                                    body = json.loads(prefix)
                                    native_error = isinstance(body, dict) and bool(body.get('errors'))
                                except (ValueError, UnicodeError):
                                    if response.get('truncated'):
                                        omit('native_error_check_prefix_truncated', **loc)
                                if not native_error:
                                    continue
                                prefix, response = _response(root, record, directory, verify_storage=True)
                            if not failed and not native_error:
                                continue
                            if prefix is not None:
                                response['decoded_prefix_base64'] = base64.b64encode(prefix).decode('ascii')
                            document = dict(schema_version='xgap-public-failure-record-v1', cell_id=cell_id,
                                observation_kind=kind, original_terminal=_pin(terminal_path, terminal_raw),
                                original_outcome=outcome_pin, phase_seal=seal_pin, ledger_index=index_pin,
                                result_pin=pin, native_errors_detected=native_error,
                                public_result=_public_result(record), response=response,
                                excluded=['model observations', 'headers', 'author output', 'credentials'])
                            raw = _raw(document)
                            if len(raw) > MAX_METADATA:
                                omit('per_document_export_cap', **loc)
                                continue
                            # Each index entry also occupies report space.
                            if used + len(raw) > record_budget or len(exported) >= 1024:
                                omit('total_export_cap', **loc)
                                continue
                            path = output / f'failure-{len(exported):04}.json'
                            with path.open('xb') as stream:
                                stream.write(raw)
                            used += len(raw)
                            exported.append(_pin(path, raw))
                            counts['exported_records'] += 1
                        except (OSError, ValueError, KeyError, TypeError, EOFError) as error:
                            omit(type(error).__name__ + ':' + (str(error) if isinstance(error, ValueError) else 'record_unavailable'), **loc)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    omit(type(error).__name__ + ':' + (str(error) if isinstance(error, ValueError) else 'phase_unavailable'), **coordinates)
        except (OSError, ValueError, KeyError, TypeError) as error:
            omit(type(error).__name__ + ':' + (str(error) if isinstance(error, ValueError) else 'cell_unavailable'), cell_id=cell_id)
    report = dict(schema_version='xgap-public-failure-archive-v1', source_root=str(root),
        counts=dict(counts), files=exported, omissions=omitted, omission_counts=dict(reasons),
        omitted_detail_count=sum(reasons.values()) - len(omitted), complete=not reasons,
        max_total_bytes=max_total_bytes, record_bytes=used, original_evidence_retained=True,
        model_calls=0, backend_calls=0, network_calls=0, outcome_modified=False)
    raw = _raw(report)
    if len(raw) > reserve:
        report['omissions'] = []
        report['omitted_detail_count'] = sum(reasons.values())
        raw = _raw(report)
    # The fixed entry cap keeps the report below one MiB; tiny budgets may need
    # file coordinates summarized while every exported document remains intact.
    if used + len(raw) > max_total_bytes:
        report['files'] = []
        report['file_index_omitted'] = 'report_budget; use failure-*.json'
        raw = _raw(report)
    path = output / 'report.json'
    with path.open('xb') as stream:
        stream.write(raw)
    return dict(report=_pin(path, raw), counts=dict(counts), omission_counts=dict(reasons),
                complete=not reasons, export_bytes=used + len(raw))
