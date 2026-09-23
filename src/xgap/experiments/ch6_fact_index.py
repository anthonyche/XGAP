"""Source-only streaming fact index for the three declared Chapter 6 cores.

SQLite is an offline reference/index format, never the evaluated graph backend.
All original core rows are retained. No query, outcome or latency is consulted.
"""
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tarfile
import time
from zipfile import ZipFile


CORES = {
    'D1': dict(node_type='Person', target_type='Person', relation='KNOWS',
               measure='value', control='gender', control_values=['female', 'male'], sum_meaningful=False),
    'D2': dict(node_type='User', target_type='Movie', relation='RATED',
               measure='rating', control='isDrama', control_values=[False, True], sum_meaningful=True),
    'D3': dict(node_type='Account', target_type='Account', relation='TRANSFERRED_TO',
               measure='amount', control='isBlocked', control_values=[False, True], sum_meaningful=True),
}


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def pin(path):
    path = Path(path).resolve(); h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024**2), b''): h.update(block)
    return dict(path=str(path), sha256=h.hexdigest(), bytes=path.stat().st_size)


def write(path, value):
    with Path(path).open('x') as f: f.write(encoded(value)+'\n')


def verify(pin_value):
    actual = pin(pin_value['path'])
    if actual['sha256'] != pin_value['sha256'] or actual['bytes'] != pin_value.get('bytes', pin_value.get('size_bytes')):
        raise ValueError('Frozen source changed: '+pin_value['path'])
    return actual


@contextmanager
def read_index(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON'); connection.execute('PRAGMA cache_size=-32768')
    try: yield connection
    finally: connection.close()


def add_nodes(db, rows):
    batch = []
    for row in rows:
        ident = row['id']; kind = row['type']; props = {k:v for k,v in row.items() if k not in ('id', 'type')}
        batch.append((ident, kind, encoded(props)))
        if len(batch) == 10000:
            db.executemany('INSERT INTO nodes VALUES(?,?,?)', batch); db.commit(); batch.clear()
    db.executemany('INSERT INTO nodes VALUES(?,?,?)', batch); db.commit()


def add_edges(db, rows):
    batch = []; count = 0
    for row in rows:
        count += 1
        batch.append((count, row['id'], row['from'], row['to'], row['timestamp'], row['value']))
        if len(batch) == 10000:
            db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)', batch); db.commit(); batch.clear()
    db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)', batch); db.commit()
    return count


def snb(db, source):
    root = Path(source); receipt = json.loads((root/'receipt.json').read_text())
    if not receipt['success'] or receipt['schema_version'] != 'xgap-ch6-snb-source-v1':
        raise ValueError('Verified official SNB intake required')
    for p in receipt['files']: verify({**p, 'path':str(root/p['path'])})
    def people():
        for p in sorted(root.glob('person_*.csv')):
            if not re.fullmatch(r'person_\d+_\d+\.csv', p.name): continue
            with p.open(newline='') as f:
                for r in csv.DictReader(f, delimiter='|'):
                    yield dict(id='person:'+r['id'], type='Person', firstName=r['firstName'], gender=r['gender'])
    def edges():
        for p in sorted(root.glob('person_knows_person_*.csv')):
            with p.open(newline='') as f:
                rows=csv.reader(f, delimiter='|'); header=next(rows)
                if header != ['Person.id','Person.id','creationDate']: raise ValueError('Unknown knows header')
                for index, r in enumerate(rows, 2):
                    yield dict(id=p.name+':'+str(index), **{'from':'person:'+r[0], 'to':'person:'+r[1]}, timestamp=int(r[2]), value=1)
    add_nodes(db, people()); count=add_edges(db, edges())
    return dict(source=pin(root/'receipt.json'), archive=receipt['archive'], selected_core='complete Person + stored directed knows rows',
                timestamp_unit='milliseconds since Unix epoch, original LongDateFormatter', expected_edges=count,
                excluded='All other SNB vertex/edge types; no claim of official SNB query-suite compliance')


def movielens(db, source):
    root=Path(source); receipt=json.loads((root/'receipt.json').read_text())
    if not receipt['success'] or receipt['schema_version'] != 'xgap-ch6-movielens20m-intake-v1':
        raise ValueError('Verified MovieLens 20M intake required')
    archive=verify(receipt['archive'])
    with ZipFile(archive['path']) as z:
        def rows(name):
            with z.open('ml-20m/'+name) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', newline=''))
        add_nodes(db, (dict(id='movie:'+r['movieId'], type='Movie', title=r['title'],
                            isDrama='Drama' in r['genres'].split('|')) for r in rows('movies.csv')))
        count=add_edges(db, (dict(id='ratings.csv:'+str(i), **{'from':'user:'+r['userId'],'to':'movie:'+r['movieId']},
                                  timestamp=int(r['timestamp'])*1000, value=float(r['rating']))
                             for i,r in enumerate(rows('ratings.csv'),2)))
    # Disk grouping derives the complete user domain, including every rated user.
    db.execute("INSERT INTO nodes SELECT DISTINCT src,'User','{}' FROM edges"); db.commit()
    if count != 20000263 or db.execute("SELECT count(*) FROM nodes WHERE kind='Movie'").fetchone()[0] != 27278:
        raise ValueError('Full MovieLens 20M release counts differ')
    return dict(source=pin(root/'receipt.json'), archive=archive, selected_core='all 20,000,263 ratings, all movies and users',
                timestamp_unit='original Unix seconds converted exactly to integer milliseconds', expected_edges=count,
                measure_semantics='SUM is total rating score, not average or money',
                excluded='tags and genome scores; no external Wikidata claims', redistribution=False)


def finbench(db, source):
    archive=pin(source)
    if archive['sha256'] != 'f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60':
        raise ValueError('Expected previously verified FinBench v0.1.0 SF0.1 archive')
    with tarfile.open(source) as t:
        def rows(name):
            member=t.getmember('sf0.1/snapshot/'+name)
            with t.extractfile(member) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8', newline=''), delimiter='|')
        add_nodes(db,(dict(id='account:'+r['accountId'],type='Account',isBlocked={'false':False,'true':True}[r['isBlocked']],
                           nickname=r['nickname']) for r in rows('Account.csv')))
        def edges():
            for index,r in enumerate(rows('AccountTransferAccount.csv'),2):
                instant=datetime.strptime(r['createTime'],'%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=timezone.utc)
                stamp=int(instant.timestamp())*1000+instant.microsecond//1000
                yield dict(id='AccountTransferAccount.csv:'+str(index),**{'from':'account:'+r['fromId'],'to':'account:'+r['toId']},
                           timestamp=stamp,value=float(r['amount']))
        count=add_edges(db,edges())
    return dict(archive=archive, selected_core='complete snapshot Account and AccountTransferAccount, no incremental writes',
                timestamp_unit='calendar fields normalized to UTC milliseconds as an ordering convention; no timezone inference',
                expected_edges=count, excluded='Other FinBench types/relations; authored bounded queries, not official FinBench query-suite compliance')


def build(dataset, source, output):
    if dataset not in CORES: raise ValueError('Unknown domain')
    root=Path(output).resolve(); root.mkdir(parents=True,exist_ok=False); started=time.monotonic()
    receipt=dict(schema_version='xgap-ch6-fact-index-v1',success=False,dataset=dataset,core=CORES[dataset],
                 model_calls=0,backend_calls=0,query_reads=0,answer_reads=0,formal_workload_admitted=False)
    db=None
    try:
        if shutil.disk_usage(root).free < 22*1024**3: raise ValueError('Index admission reserves 16 GiB plus six GiB free')
        write(root/'intent.json',dict(dataset=dataset,source=str(Path(source).resolve()),
            representation='SQLite disk index, fixed 32-MiB page cache and 10,000-row insert batches',
            selection='All declared core rows; no workload/outcomes read',
            scale_contract='1x original full core; .25x edge ordinal modulo four; 4x four disconnected identity-renamed replicas'))
        db=sqlite3.connect(root/'facts.sqlite')
        db.executescript('PRAGMA journal_mode=DELETE; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-32768; PRAGMA temp_store=FILE;'
            'CREATE TABLE nodes(id TEXT PRIMARY KEY,kind TEXT NOT NULL,props TEXT NOT NULL) WITHOUT ROWID;'
            'CREATE TABLE edges(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,ts INTEGER NOT NULL,value REAL NOT NULL);')
        provenance={'D1':snb,'D2':movielens,'D3':finbench}[dataset](db,source)
        db.executescript('CREATE INDEX edge_src ON edges(src,ordinal); CREATE INDEX edge_dst ON edges(dst,ordinal);'
                         'CREATE INDEX edge_ts ON edges(ts,ordinal); CREATE INDEX node_kind ON nodes(kind,id);')
        missing=db.execute('SELECT e.id FROM edges e LEFT JOIN nodes a ON a.id=e.src LEFT JOIN nodes b ON b.id=e.dst WHERE a.id IS NULL OR b.id IS NULL LIMIT 1').fetchone()
        if missing: raise ValueError('Unmapped edge endpoint: '+missing[0])
        count=db.execute('SELECT count(*) FROM edges').fetchone()[0]
        if not count or count!=provenance['expected_edges']: raise ValueError('Missing source rows')
        cut=db.execute('SELECT ts FROM edges ORDER BY ts,ordinal LIMIT 1 OFFSET ?', (count//2,)).fetchone()[0]
        counts=dict(nodes=db.execute('SELECT count(*) FROM nodes').fetchone()[0],edges=count,
                    node_types=dict(db.execute('SELECT kind,count(*) FROM nodes GROUP BY kind')),
                    early_edges=db.execute('SELECT count(*) FROM edges WHERE ts<=?',(cut,)).fetchone()[0],
                    late_edges=db.execute('SELECT count(*) FROM edges WHERE ts>?',(cut,)).fetchone()[0])
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok': raise ValueError('Fact index integrity failure')
        db.close();db=None
        receipt.update(success=True,provenance=provenance,counts=counts,scope_cut_ms=cut,
                       database=pin(root/'facts.sqlite'),source_archive_rows_complete=True)
    except Exception as error: receipt.update(error_type=type(error).__name__,error=str(error))
    finally:
        if db: db.close()
        receipt['offline_seconds']=time.monotonic()-started
        write(root/'receipt.json',receipt)
    return receipt
