"""Lossless, bounded evidence storage; stored bytes never replace wire bytes."""
import gzip
import hashlib
import json
import os
from pathlib import Path

CHUNK = 64 * 1024
MAX_LOGICAL_BYTES = 512 * 1024 * 1024


def file_pin(path):
    path = Path(path)
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            digest.update(chunk)
            size += len(chunk)
    return dict(path=str(path.resolve()), sha256=digest.hexdigest(), bytes=size)


def write_json_evidence(path, value):
    """Exclusive streaming JSON+gzip write without a second full JSON string."""
    path = Path(path)
    digest = hashlib.sha256()
    logical = 0
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False,
                               separators=(',', ':'))
    with path.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', compresslevel=1, mtime=0) as saved:
            parts, count = [], 0
            for text in encoder.iterencode(value):
                parts.append(text)
                count += len(text)
                if count >= CHUNK:
                    data = ''.join(parts).encode('utf-8')
                    saved.write(data)
                    digest.update(data)
                    logical += len(data)
                    parts, count = [], 0
            data = (''.join(parts) + '\n').encode('utf-8')
            saved.write(data)
            digest.update(data)
            logical += len(data)
        raw.flush()
        os.fsync(raw.fileno())
    return {**file_pin(path), 'encoding': 'gzip', 'logical_bytes': logical,
            'logical_sha256': digest.hexdigest()}


def read_json_evidence(pin, *, max_bytes=MAX_LOGICAL_BYTES):
    """Read both old raw pins and new gzip pins, checking both identities."""
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_LOGICAL_BYTES:
        raise ValueError('Invalid evidence read bound')
    size = pin.get('bytes')
    logical = pin.get('logical_bytes', size)
    if any(type(n) is not int or not 0 < n <= max_bytes for n in (size, logical)):
        raise ValueError('Evidence exceeds the stored or logical size bound')
    path = Path(pin['path'])
    if path.stat().st_size != size or file_pin(path)['sha256'] != pin['sha256']:
        raise ValueError('Evidence stored size/hash mismatch')
    encoding = pin.get('encoding', 'identity')
    if encoding not in ('identity', 'gzip'):
        raise ValueError('Unknown evidence encoding')
    opener = gzip.open if encoding == 'gzip' else open
    with opener(path, 'rb') as stream:
        data = stream.read(logical + 1)
    if len(data) != logical or hashlib.sha256(data).hexdigest() != pin.get('logical_sha256', pin['sha256']):
        raise ValueError('Evidence logical size/hash mismatch')
    return json.loads(data)
