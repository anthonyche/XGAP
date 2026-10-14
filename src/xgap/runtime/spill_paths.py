"""Exact finite path algebra with disk-backed deduplication/frontiers."""
from contextlib import ExitStack
import json
from xgap.algebra.types import Path
from xgap.algebra.ops import RecursiveMode
from xgap.algebra.evaluator import _path_allowed
from xgap.runtime.path_selection import select_native_paths,normalized_pathset
from xgap.runtime.path_composition import compose_paths
from xgap.runtime.spill_rows import managed,key_text
from xgap.runtime.contracts import RuntimeNodeKind as R


def setup(store):
    store.db.execute('CREATE TABLE paths (path TEXT PRIMARY KEY, source TEXT, target TEXT, length INTEGER)')
    store.db.execute('CREATE INDEX path_source ON paths(source)')
    store.db.execute('CREATE INDEX path_pair ON paths(source,target,length)')


def add(store,path):
    store.workspace.control.check()
    store.db.execute('INSERT OR IGNORE INTO paths VALUES(?,?,?,?)',(key_text(path.sequence),path.first(),path.last(),len(path)))
    store._account()


def read(store,sql='SELECT path FROM paths ORDER BY path COLLATE TYPED',args=()):
    for text, in store.db.execute(sql,args):
        store.workspace.control.check();yield Path(tuple(json.loads(text)))


def select(workspace,rows,p):
    select_native_paths((),p)
    with managed(workspace) as store:
        setup(store)
        for i,row in enumerate(rows,1):
            if p.get('input_model')=='rdf-resource-triples-v1' and i>p['max_rows']:
                raise ValueError('Complete resource path result exceeds the row budget')
            # Decode/bound-check each path, then apply global selectors below.
            one={**p,'selector':'ALL','k':None,'recursive_shortest':False,'post_shortest_lengths':[]}
            for decoded in select_native_paths((row,),one):add(store,Path(tuple(decoded['path'])))
        if p.get('recursive_shortest'):
            zero='' if p.get('shortest_includes_zero',False) else ' AND b.length>0'
            store.db.execute('DELETE FROM paths AS a WHERE a.length>(SELECT MIN(b.length) FROM paths b WHERE a.source=b.source AND a.target=b.target'+zero+')')
        for length in p.get('post_shortest_lengths',()):store.db.execute('DELETE FROM paths WHERE length!=?',(length,))
        selector=p['selector'];k=p.get('k') or 1
        if selector=='ALL':sql='SELECT path FROM paths'
        else:
            rank='DENSE_RANK' if selector in ('ALL_SHORTEST','SHORTEST_K_GROUP') else 'ROW_NUMBER'
            order='length' if rank=='DENSE_RANK' else ('path COLLATE TYPED' if selector in ('ANY','ANY_K') else 'length,path COLLATE TYPED')
            sql=f'SELECT path FROM (SELECT path,{rank}() OVER(PARTITION BY source,target ORDER BY {order}) AS rank FROM paths) WHERE rank<={k}'
        for path in read(store,sql+' ORDER BY path COLLATE TYPED'):yield {'path':list(path.sequence)}


def compose(workspace,inputs,p):
    compose_paths([() for _ in inputs],p)
    with ExitStack() as stack:
        def create():
            store=stack.enter_context(managed(workspace));setup(store);return store
        base=create()
        for row in inputs[-1]:
            for path in normalized_pathset((row,)):add(base,path)
        result=create()
        if p['operation']=='join':
            left=read(base) if len(inputs)==1 else (path for row in inputs[0] for path in normalized_pathset((row,)))
            for a in left:
                for b in read(base,'SELECT path FROM paths WHERE source=?',(a.last(),)):add(result,a.concatenate(b))
        else:
            mode=RecursiveMode(p['mode']);shortest=mode is RecursiveMode.SHORTEST
            frontier=create()
            for path in read(base):
                if shortest or _path_allowed(path,mode):add(frontier,path)
            for depth in range(p['max_depth']):
                for path in read(frontier):add(result,path)
                if depth+1==p['max_depth']:break
                nxt=create()
                for a in read(frontier):
                    for b in read(base,'SELECT path FROM paths WHERE source=?',(a.last(),)):
                        c=a.concatenate(b)
                        if result.db.execute('SELECT 1 FROM paths WHERE path=?',(key_text(c.sequence),)).fetchone():continue
                        if shortest:
                            best=result.db.execute('SELECT MIN(length) FROM paths WHERE source=? AND target=?',(c.first(),c.last())).fetchone()[0]
                            if best is not None and best<len(c):continue
                        elif not _path_allowed(c,mode):continue
                        add(nxt,c)
                frontier.close();frontier=nxt
                if not frontier.db.execute('SELECT 1 FROM paths LIMIT 1').fetchone():break
            if shortest:result.db.execute('DELETE FROM paths AS a WHERE length>(SELECT MIN(b.length) FROM paths b WHERE a.source=b.source AND a.target=b.target)')
        for path in read(result):
            if len(path)>p['max_edges']:raise ValueError('Composed path exceeds its compiled finite edge bound')
            yield {'path':list(path.sequence)}


def paths(workspace,node,inputs):
    if node.kind is R.COORDINATOR_PATH_SELECT:yield from select(workspace,inputs[0],node.parameters)
    else:yield from compose(workspace,inputs,node.parameters)
