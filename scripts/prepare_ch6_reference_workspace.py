#!/usr/bin/env python3
"""Offline covering indexes for an independent reference copy, never a method."""
import argparse
import hashlib
from pathlib import Path
import shutil
import sqlite3
import time

from xgap.experiments.ch6_fact_index import pin,write
from xgap.experiments.ch6_formal_protocol import load_pin

DDL=('CREATE INDEX reference_src_dst ON edges(src,dst)',
     'CREATE INDEX reference_dst_src ON edges(dst,src)')


def prepare(index_pin,output,work_root):
    started=time.monotonic();meta=load_pin(index_pin)
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    work=Path(work_root).resolve();work.mkdir(parents=True,exist_ok=False)
    source=meta['database'];size=source['bytes'];reserve=3*size+6*1024**3
    if any(shutil.disk_usage(p).free<reserve for p in (root,work)):
        raise ValueError('Insufficient space for independent reference copy and indexes')
    write(root/'intent.json',dict(source_index=index_pin,original_database=source,ddl=list(DDL),
        work_root=str(work),required_free_bytes=reserve,model_calls=0,backend_calls=0))
    copied=work/'reference.sqlite';digest=hashlib.sha256()
    with open(source['path'],'rb') as src,copied.open('xb') as dst:
        for block in iter(lambda:src.read(4*1024**2),b''):
            digest.update(block);dst.write(block)
    if digest.hexdigest()!=source['sha256'] or copied.stat().st_size!=size:
        raise ValueError('Frozen reference source copy differs')
    with sqlite3.connect(copied) as db:
        db.execute('PRAGMA cache_size=-65536');db.execute('PRAGMA temp_store=FILE')
        for ddl in DDL:db.execute(ddl)
        db.commit()
    local=pin(copied);target=root/'reference.sqlite'
    shutil.copyfile(copied,target);durable=pin(target)
    if local['sha256']!=durable['sha256']:raise ValueError('Derived reference copy differs')
    receipt=dict(schema_version='xgap-independent-reference-index-v1',success=True,
        source_index=index_pin,original_database=source,database=durable,
        source_copy_verified_before_ddl=True,ddl=list(DDL),row_mutations=0,
        model_calls=0,backend_calls=0,query_reads=0,answer_reads=0,
        offline_seconds=time.monotonic()-started,
        scope='Source-only covering indexes on an independent SQLite copy; no XGAP or baseline changes')
    write(root/'receipt.json',receipt);return pin(root/'receipt.json')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('index','output','work-root'):p.add_argument('--'+n,required=True)
    a=p.parse_args();print(prepare(pin(a.index),a.output,a.work_root))
