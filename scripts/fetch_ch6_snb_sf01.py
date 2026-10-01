#!/usr/bin/env python3
"""Freeze the official SNB Interactive v1 SF0.1 source and bounded core CSVs.

The archive URL is published in the official SNB dataset table. This derivative
uses the complete Person/knows core, not the repository's tiny example data.
No query, model output or result is used for source selection.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import time
import urllib.request

URL = ('https://datasets.ldbcouncil.org/snb-interactive-v1/'
       'social_network-sf0.1-CsvBasic-LongDateFormatter.tar.zst')


def fetch(output):
    import zstandard
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = dict(schema_version='xgap-ch6-snb-source-v1', success=False,
        url=URL, source_page='https://ldbcouncil.org/benchmarks/snb/datasets/',
        format='CsvBasic/LongDateFormatter', scale_factor='0.1',
        query_reads=0, answer_reads=0, model_calls=0, backend_calls=0,
        publisher_checksum=None, formal_workload_admitted=False)
    try:
        if shutil.disk_usage(root).free < 7*1024**3:
            raise ValueError('Six-GiB reserve plus one-GiB input allowance required')
        archive = root/'social_network-sf0.1.tar.zst'
        sha = hashlib.sha256(); size = 0
        request = urllib.request.Request(URL, headers={'User-Agent':'XGAP-research-source-intake/1'})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open('xb') as target:
            receipt['http_etag'] = response.headers.get('ETag')
            while chunk := response.read(1024**2):
                size += len(chunk)
                if size > 512*1024**2: raise ValueError('Compressed source exceeds 512 MiB')
                sha.update(chunk); target.write(chunk)
        receipt['archive'] = dict(path=str(archive), sha256=sha.hexdigest(), bytes=size)
        members = []; selected = []; total = 0
        with archive.open('rb') as raw, zstandard.ZstdDecompressor().stream_reader(raw) as reader:
            with tarfile.open(fileobj=reader, mode='r|') as package:
                for member in package:
                    name = PurePosixPath(member.name)
                    if name.is_absolute() or '..' in name.parts or not (member.isfile() or member.isdir()):
                        raise ValueError('Unsafe archive entry')
                    total += member.size
                    if len(members) >= 4096 or total > 4*1024**3:
                        raise ValueError('Expanded source exceeds bounded intake')
                    members.append(dict(name=member.name, bytes=member.size))
                    if not member.isfile(): continue
                    # Read every payload to validate the stream, retain only the
                    # declared Person/knows projection. No directory extraction.
                    keep = bool(re.fullmatch(r'person(?:_knows_person)?_\d+_\d+\.csv', name.name))
                    target = (root/name.name).open('xb') if keep else None
                    h = hashlib.sha256(); count = 0
                    try:
                        source = package.extractfile(member)
                        while block := source.read(1024**2):
                            count += len(block); h.update(block)
                            if target: target.write(block)
                    finally:
                        if target: target.close()
                    if count != member.size: raise ValueError('Truncated archive payload')
                    if keep: selected.append(dict(path=name.name, bytes=count, sha256=h.hexdigest()))
            while reader.read(1024**2): pass
        if not any(p['path'].startswith('person_knows_') for p in selected):
            raise ValueError('No complete knows table found')
        if not any(re.fullmatch(r'person_\d+_\d+\.csv', p['path']) for p in selected):
            raise ValueError('No complete Person table found')
        receipt.update(success=True, members=members, files=selected,
            core_projection='All rows of Person and person_knows_person; excludes other SNB relations',
            checksum_scope='Local SHA-256 pins downloaded HTTPS bytes; no publisher checksum was supplied')
    except Exception as error:
        receipt.update(error_type=type(error).__name__, error=str(error))
    receipt['elapsed_seconds'] = time.monotonic()-started
    (root/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(success=receipt['success'], receipt=str(root/'receipt.json'), error=receipt.get('error'))))
    return 0 if receipt['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(fetch(parser.parse_args().output))
