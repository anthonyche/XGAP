#!/usr/bin/env python3
"""Freeze the official MovieLens 20M archive; no queries, extraction or models.

Research source preparation only. Preserve the README and report independent
archive SHA-256 plus the publisher's MD5. This does not admit a held-out workload.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request
from zipfile import ZipFile

BASE = 'https://files.grouplens.org/datasets/movielens/'


def fetch(output):
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    receipt = dict(schema_version='xgap-ch6-movielens20m-intake-v1', success=False,
        url=BASE+'ml-20m.zip', model_calls=0, backend_calls=0, formal_workload_admitted=False,
        redistribution=False, elapsed_seconds=None)
    started=time.monotonic()
    try:
        if shutil.disk_usage(root).free < 6*1024**3 + 256*1024**2:
            raise ValueError('Insufficient space above the six-GiB reserve')
        with urllib.request.urlopen(BASE+'ml-20m.zip.md5', timeout=30) as response:
            checksum=response.read(1025)
        if len(checksum)>1024:raise ValueError('Unexpected checksum response')
        expected=checksum.decode('ascii').split()[0].lower()
        if len(expected)!=32 or any(c not in '0123456789abcdef' for c in expected):
            raise ValueError('Publisher checksum is not MD5')
        (root/'publisher.md5').write_bytes(checksum)
        md5=hashlib.md5();sha=hashlib.sha256();size=0
        archive=root/'ml-20m.zip'
        with urllib.request.urlopen(receipt['url'],timeout=45) as response, archive.open('xb') as stream:
            while chunk:=response.read(1024**2):
                size+=len(chunk)
                if size>256*1024**2:raise ValueError('Archive byte budget exceeded')
                stream.write(chunk);md5.update(chunk);sha.update(chunk)
        receipt['archive']=dict(path=str(archive),bytes=size,sha256=sha.hexdigest(),md5=md5.hexdigest())
        if md5.hexdigest()!=expected:raise ValueError('Publisher checksum mismatch')
        with ZipFile(archive) as package:
            names=package.namelist()
            if len(names)!=len(set(names)) or sum(i.file_size for i in package.infolist())>2*1024**3:
                raise ValueError('Invalid or unexpectedly large archive')
            needed=['ratings.csv','movies.csv','links.csv','tags.csv','genome-tags.csv','genome-scores.csv','README.txt']
            if any('ml-20m/'+n not in names for n in needed):raise ValueError('Missing official source member')
            if package.testzip() is not None:raise ValueError('Archive CRC failure')
            (root/'README.txt').write_bytes(package.read('ml-20m/README.txt'))
            members=[]
            for name in needed:
                info=package.getinfo('ml-20m/'+name)
                members.append(dict(name=info.filename,bytes=info.file_size,crc32=info.CRC))
            receipt['members']=members
        receipt.update(success=True,publisher_md5=expected,
            scope='Frozen official source only; mapping, graph materialization and held-out selection remain separate')
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    receipt['elapsed_seconds']=time.monotonic()-started
    (root/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt));return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    raise SystemExit(fetch(p.parse_args().output))
