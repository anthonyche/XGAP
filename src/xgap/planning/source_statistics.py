"""Query-independent statistics preparation and main-entry snapshot binding.

Dataset plugins supply a complete stream of normalized source records. SQLite
keeps exact frequency counts off heap; only bounded frequent values enter models.
Preparation is explicit, never a side effect of answering a user query.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
import tempfile

from xgap.planning.cardinality_synopsis import ColumnSynopsis, token
from xgap.planning.joint_synopsis import JointSynopsis, atom
from xgap.planning.relative_source_work import FrozenSourceWorkRanker
from xgap.planning.runtime_estimator import SourceStatistics, FrozenSourceStatistics, _hash
from xgap.runtime.scalars import stable_text


@dataclass(frozen=True)
class SourceRecordStream:
    backend_id: str
    source_id: str
    snapshot_version: str
    records: object
    domains: dict
    joint_columns: tuple=()


def collect_source_statistics(streams, *, provenance_ref, unique_node_properties=(), heavy_limit=256):
    if type(heavy_limit) is not int or not 1<=heavy_limit<=256:
        raise ValueError('Statistics frequent-value limit must be in 1..256')
    summaries=[];populations=[];marginals=[];joints=[];degrees=[]
    for source in streams:
        if not isinstance(source,SourceRecordStream):raise TypeError('Typed source record stream required')
        if len(source.domains)>4096 or len(source.joint_columns)>1024:raise ValueError('Statistics profile budget exceeded')
        groups=[tuple(x) for x in source.joint_columns]
        if any(not 2<=len(g)<=4 or len(set(g))!=len(g) or any(c not in source.domains for c in g) for g in groups):
            raise ValueError('Joint columns must name distinct declared source columns')
        keys=[(c,) for c in source.domains]+groups
        if len(set(keys))!=len(keys):raise ValueError('Duplicate statistics profile')
        def scope(c):
            if c.startswith('node:'):return ('node',None)
            if c.startswith('edge:') and len(c.split(':'))>=3:return ('edge',c.split(':')[1])
            raise ValueError('Unknown normalized source column')
        if any(len({scope(c) for c in k})!=1 for k in keys):raise ValueError('Joint columns must share one population')
        with tempfile.TemporaryDirectory(prefix='xgap-stats-') as temp:
            db=sqlite3.connect(str(Path(temp)/'frequencies.sqlite'))
            try:
                db.execute('PRAGMA cache_size=-2048');db.execute('PRAGMA temp_store=FILE')
                db.execute('CREATE TABLE f (profile INTEGER, value TEXT, n INTEGER, PRIMARY KEY(profile,value)) WITHOUT ROWID')
                counts=[0]*len(keys);nodes=edges=width=0
                for record in source.records:
                    kind=record['kind'];values=record['values']
                    if kind not in ('node','edge') or not isinstance(values,dict):raise ValueError('Invalid source record')
                    nodes+=kind=='node';edges+=kind=='edge';width+=len(stable_text(record).encode())
                    for i,key in enumerate(keys):
                        expected,label=scope(key[0])
                        if kind!=expected or label is not None and label!=record.get('label'):continue
                        v=[values.get(c) for c in key]
                        # Canonicalize integer-valued floats for typed numeric equality.
                        text=json.dumps([json.loads(atom(x)) for x in v],separators=(',',':'),ensure_ascii=False)
                        counts[i]+=1
                        db.execute('INSERT INTO f VALUES(?,?,1) ON CONFLICT(profile,value) DO UPDATE SET n=n+1',(i,text))
                for i,key in enumerate(keys):
                    if len(key)==1:
                        nulls=db.execute('SELECT COALESCE(SUM(n),0) FROM f WHERE profile=? AND value=?',(i,'[null]')).fetchone()[0]
                        ndv=db.execute('SELECT COUNT(*) FROM f WHERE profile=? AND value!=?',(i,'[null]')).fetchone()[0]
                        top=db.execute('SELECT value,n FROM f WHERE profile=? AND value!=? ORDER BY n DESC,value LIMIT ?',
                            (i,'[null]',heavy_limit)).fetchall()
                        parts=key[0].split(':')
                        if len(parts)==3 and parts[0]=='edge' and parts[2] in ('source','target'):
                            if nulls:raise ValueError('Edge endpoint statistics cannot contain null identities')
                            square,maximum=db.execute('SELECT COALESCE(SUM(n*n),0),COALESCE(MAX(n),0) FROM f WHERE profile=?',(i,)).fetchone()
                            degrees.append((source.backend_id,parts[1],parts[2],counts[i],ndv,square,maximum))
                        marginals.append(ColumnSynopsis(source.backend_id,key[0],source.domains[key[0]],counts[i],ndv,
                            tuple((json.loads(v)[0],n) for v,n in top),nulls))
                    else:
                        ndv=db.execute('SELECT COUNT(*) FROM f WHERE profile=?',(i,)).fetchone()[0]
                        top=db.execute('SELECT value,n FROM f WHERE profile=? ORDER BY n DESC,value LIMIT ?',(i,heavy_limit)).fetchall()
                        joints.append(JointSynopsis(source.backend_id,key,_hash([source.domains[c] for c in key]),counts[i],ndv,
                            tuple((tuple(json.loads(v)),n) for v,n in top)))
                total=nodes+edges
                summaries.append(SourceStatistics(source.backend_id,source.source_id,source.snapshot_version,total,
                    max(1,width/max(1,total)),provenance_ref))
                populations.append((source.backend_id,nodes,edges))
            finally:db.close()
    for backend,nodes,_ in populations:
        for name in unique_node_properties:
            profile=next((p for p in marginals if p.backend==backend and p.column=='node:property:'+name),None)
            if profile is None or profile.nulls or profile.ndv!=nodes:
                raise ValueError('Declared unique node property is not verified by the complete source statistics')
    statistics=FrozenSourceStatistics('source-record-stream',_hash([s.to_dict() for s in summaries]),tuple(summaries))
    return FrozenSourceWorkRanker(statistics,tuple(populations),tuple(unique_node_properties),provenance_ref,
        endpoint_degrees=tuple(degrees),cardinality_aware=True,column_synopses=tuple(marginals),joint_synopses=tuple(joints),transfer_byte_quantum=1024)


def load_source_statistics(path):
    # Local metadata only. Reject unexpectedly large catalogs before parsing.
    p=Path(path)
    if p.stat().st_size>32*1024*1024:raise ValueError('Source statistics catalog exceeds 32 MiB')
    return FrozenSourceWorkRanker.from_dict(json.loads(p.read_text()))


def resolve_estimator(estimator, source_statistics, clients, sources):
    if estimator is not None and source_statistics is not None:raise ValueError('Specify an estimator or source statistics, not both')
    if estimator is not None:return estimator
    model=source_statistics
    if model is None:
        paths={c.descriptor.runtime.get('statistics_catalog_path') for c in clients.values()
               if getattr(c,'descriptor',None) is not None and c.descriptor.runtime.get('statistics_catalog_path')}
        if len(paths)>1:raise ValueError('Backends disagree on their statistics catalog')
        if paths:model=load_source_statistics(next(iter(paths)))
    if model is None:return None
    if isinstance(model,(str,Path)):model=load_source_statistics(model)
    if not isinstance(model,FrozenSourceWorkRanker) or not model.cardinality_aware:
        raise TypeError('Cardinality-aware frozen source statistics required')
    expected={(b,s.source_id,s.snapshot_version) for s in sources.values() for b in s.replica_backend_ids if b in clients}
    actual={(s.backend_id,s.source_id,s.snapshot_version) for s in model.statistics.entries}
    if actual!=expected:raise ValueError('Statistics catalog does not match all active source snapshots')
    return model
