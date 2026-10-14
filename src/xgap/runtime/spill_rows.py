"""Request-owned replayable row streams and exact disk-backed relational state."""
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from threading import Lock
import json
import sqlite3
import tempfile
import uuid
import time

from xgap.runtime.scalars import stable_text, row_key, decimal_binding


def key_text(key):
    def encode(x):
        if isinstance(x,Decimal):return {'decimal':decimal_binding(x)['value']}
        if isinstance(x,tuple):return [encode(v) for v in x]
        return x
    return json.dumps(encode(key),separators=(',',':'),ensure_ascii=False)


def key_value(text):
    return json.loads(text,object_hook=lambda x:Decimal(x['decimal']) if set(x)=={'decimal'} else x)


def compare_keys(a,b):
    a,b=key_value(a),key_value(b)
    return (a>b)-(a<b)


class SpillWorkspace:
    def __init__(self,control,max_bytes=1024**3):
        if type(max_bytes) is not int or max_bytes<1:raise ValueError("Positive spill byte limit required")
        self.control=control;self.max_bytes=max_bytes;self.lock=Lock();self.bytes=0;self.peak_bytes=0;self.stores=set()
        self.temp=tempfile.TemporaryDirectory(prefix='xgap-stream-')
    def __enter__(self):return self
    def __exit__(self,*args):
        for s in tuple(self.stores):s.close()
        self.temp.cleanup()
    def store(self):
        s=DiskRows(self)
        with self.lock:self.stores.add(s)
        return s
    def reserve(self,delta):
        self.control.check()
        with self.lock:
            if self.bytes+delta>self.max_bytes:raise ValueError('Request spill byte budget exceeded')
            self.bytes+=delta;self.peak_bytes=max(self.peak_bytes,self.bytes)


class DiskRows:
    """Sealed streams support repeated readers for DAG fan-out without heap lists."""
    def __init__(self,workspace):
        self.workspace=workspace;self.count=0;self.encoded_bytes=2;self.closed=False;self.accounted=0
        self.path=Path(workspace.temp.name)/(uuid.uuid4().hex+'.sqlite')
        self.db=sqlite3.connect(str(self.path),check_same_thread=False)
        try:
            self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('PRAGMA synchronous=OFF')
            self.db.execute('PRAGMA cache_size=-256');self.db.execute('PRAGMA temp_store=FILE')
            self.db.create_collation('TYPED',compare_keys)
            self.db.set_progress_handler(lambda:int(workspace.control.cancelled.is_set() or
                workspace.control.deadline is not None and time.perf_counter()>=workspace.control.deadline),1000)
            self.db.execute('CREATE TABLE rows (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, key TEXT, lookup TEXT)')
            self.db.execute('CREATE INDEX lookup_index ON rows(lookup)')
            self._account()
        except BaseException:
            self.db.close();self.path.unlink(missing_ok=True);raise
    def _account(self):
        size=self.db.execute('PRAGMA page_count').fetchone()[0]*self.db.execute('PRAGMA page_size').fetchone()[0]
        self.workspace.reserve(size-self.accounted);self.accounted=size
    def append(self,row,*,key=None,lookup=None):
        self.workspace.control.check()
        text=stable_text(row)
        self.db.execute('INSERT INTO rows(payload,key,lookup) VALUES(?,?,?)',(text,key,lookup))
        self.count+=1;self.encoded_bytes+=len(text.encode())+(self.count>1)
        self._account()
    def finish(self):self.db.commit();return self
    def __len__(self):return self.count
    def __iter__(self):
        for text, in self.db.execute('SELECT payload FROM rows ORDER BY seq'):
            self.workspace.control.check();yield json.loads(text)
    def select(self,sql,args=()):
        for text, in self.db.execute(sql,args):
            self.workspace.control.check();yield json.loads(text)
    def close(self):
        if not self.closed:
            self.db.close();self.path.unlink(missing_ok=True)
            with self.workspace.lock:
                self.workspace.bytes-=self.accounted;self.workspace.stores.discard(self)
            self.closed=True


def distinct(workspace,rows,*,preserve_order=False):
    with managed(workspace) as s:
        s.db.execute('CREATE UNIQUE INDEX distinct_key ON rows(key)')
        for row in rows:
            text=stable_text(row);k=key_text(row_key(row));s.workspace.control.check()
            s.db.execute('INSERT INTO rows(payload,key) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload=MIN(payload,excluded.payload)'
                if not preserve_order else 'INSERT OR IGNORE INTO rows(payload,key) VALUES(?,?)',(text,k))
            s._account()
        yield from s.select('SELECT payload FROM rows ORDER BY '+('seq' if preserve_order else 'payload'))


@contextmanager
def managed(workspace):
    s=workspace.store()
    try:yield s
    finally:s.close()
