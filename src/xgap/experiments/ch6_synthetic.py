"""Deterministic bounded-degree D4 stress data, separate from empirical D1–D3."""
import hashlib
from pathlib import Path
import shutil
import sqlite3
import time

from xgap.experiments.ch6_fact_index import encoded, pin, write

GENERATOR = 'xgap-d4-ring-chords-v1'
CORE = dict(node_type='Entity', target_type='Entity', relation='LINKS', measure='weight',
            control='isMarked', control_values=[False, True], sum_meaningful=True)


def generate(output, *, nodes=4096, degree=8, seed=20260926, reserve_bytes=6 * 1024**3):
    if (type(nodes) is not int or not 16 <= nodes <= 1048576 or type(degree) is not int
            or not 1 <= degree < min(nodes, 65) or type(seed) is not int):
        raise ValueError('Explicit bounded node/degree/seed values required')
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    # Estimate storage before generating, and retain the reserve during insertion.
    if shutil.disk_usage(root).free < reserve_bytes + nodes * (degree * 256 + 256):
        raise ValueError('D4 generation would exceed declared disk allowance')
    started = time.monotonic()
    offsets = [1]
    for i in range(1, degree):
        offset = 1 + int.from_bytes(hashlib.sha256(f'{seed}:{i}'.encode()).digest()[:8], 'big') % (nodes - 1)
        while offset in offsets:
            offset = 1 + offset % (nodes - 1)
        offsets.append(offset)
    write(root/'generator.json', dict(generator=GENERATOR, nodes=nodes, degree=degree, seed=seed,
                                    offsets=offsets, synthetic=True,
                                    semantics='directed ring plus distinct modular chords; no self-loops; degree fixed'))
    h = hashlib.sha256()
    with sqlite3.connect(root/'facts.sqlite') as db:
        db.executescript('PRAGMA journal_mode=DELETE; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-32768;'
            'CREATE TABLE nodes(id TEXT PRIMARY KEY,kind TEXT NOT NULL,props TEXT NOT NULL) WITHOUT ROWID;'
            'CREATE TABLE edges(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,ts INTEGER NOT NULL,value REAL NOT NULL);')
        for start in range(0, nodes, 4096):
            rows = [(f'entity:{i:09d}', 'Entity', encoded(dict(isMarked=i % 4 == 0)))
                    for i in range(start, min(start+4096, nodes))]
            db.executemany('INSERT INTO nodes VALUES(?,?,?)', rows)
            for row in rows: h.update((encoded(row)+'\n').encode())
        batch = []
        for i in range(nodes):
            for j, offset in enumerate(offsets):
                ordinal = i * degree + j + 1
                row = (ordinal, f'edge:{ordinal:012d}', f'entity:{i:09d}',
                       f'entity:{(i+offset)%nodes:09d}', ordinal * 1000, float(ordinal % 97 + 1))
                batch.append(row); h.update((encoded(row)+'\n').encode())
                if len(batch) == 10000:
                    db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)', batch); db.commit(); batch.clear()
                    if shutil.disk_usage(root).free < reserve_bytes: raise ValueError('D4 disk reserve reached')
        db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)', batch)
        db.executescript('CREATE INDEX edge_src ON edges(src,ordinal); CREATE INDEX edge_dst ON edges(dst,ordinal);'
                         'CREATE INDEX edge_ts ON edges(ts,ordinal); CREATE INDEX node_kind ON nodes(kind,id);')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('D4 index failed integrity check')
    edges = nodes * degree
    cut = (edges // 2 + 1) * 1000
    result = dict(schema_version='xgap-ch6-fact-index-v1', success=True, dataset='D4', core=CORE,
                  database=pin(root/'facts.sqlite'), counts=dict(nodes=nodes, edges=edges,
                  node_types={'Entity': nodes}, early_edges=edges//2+1, late_edges=edges-edges//2-1),
                  scope_cut_ms=cut, provenance=dict(generator=pin(root/'generator.json'),
                  synthetic=True, expected_edges=edges, logical_facts_sha256=h.hexdigest(),
                  benchmark_equivalence=False, degree_distribution='exact regular directed out/in degree'),
                  source_archive_rows_complete=True, model_calls=0, backend_calls=0,
                  query_reads=0, answer_reads=0, formal_workload_admitted=False,
                  offline_seconds=time.monotonic()-started)
    write(root/'receipt.json', result)
    return pin(root/'receipt.json')
