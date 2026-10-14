"""Request-owned adaptive row streams and exact memory/disk relational state."""
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from threading import Lock
import json
import sqlite3
import tempfile
import uuid
import time
import sys

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
    def __init__(self,control,max_bytes=1024**3,memory_bytes=0):
        if type(max_bytes) is not int or max_bytes<1:raise ValueError("Positive spill byte limit required")
        if type(memory_bytes) is not int or memory_bytes<0:raise ValueError("Nonnegative memory byte limit required")
        self.memory_limit=memory_bytes;self.memory_bytes=0;self.peak_memory_bytes=0;self.spilled_stores=0
        self.control=control;self.max_bytes=max_bytes;self.lock=Lock();self.bytes=0;self.peak_bytes=0;self.stores=set()
        self.temp=tempfile.TemporaryDirectory(prefix='xgap-stream-')
    def __enter__(self):return self
    def __exit__(self,*args):
        for s in tuple(self.stores):s.close()
        self.temp.cleanup()
    def store(self,*,buffered=True):
        s=BufferedRows(self) if buffered and self.memory_limit else DiskRows(self)
        with self.lock:self.stores.add(s)
        return s
    def claim_memory(self,delta):
        self.control.check()
        with self.lock:
            if self.memory_bytes+delta>self.memory_limit:return False
            self.memory_bytes+=delta;self.peak_memory_bytes=max(self.peak_memory_bytes,self.memory_bytes)
            return True
    def release_memory(self,size):
        with self.lock:self.memory_bytes-=size
    def reserve(self,delta):
        self.control.check()
        with self.lock:
            if self.bytes+delta>self.max_bytes:raise ValueError('Request spill byte budget exceeded')
            self.bytes+=delta;self.peak_bytes=max(self.peak_bytes,self.bytes)


class DiskRows:
    """Sealed streams support repeated readers for DAG fan-out without heap lists."""
    def __init__(self,workspace):
        self.workspace=workspace;self.count=0;self.encoded_bytes=2;self.closed=False;self.accounted=0;self.in_memory=workspace.memory_limit>0
        self.collations={'TYPED':compare_keys}
        self.path=Path(workspace.temp.name)/(uuid.uuid4().hex+'.sqlite')
        self.db=sqlite3.connect(":memory:" if self.in_memory else str(self.path),check_same_thread=False)
        try:
            self.db.execute('PRAGMA journal_mode=OFF');self.db.execute('PRAGMA synchronous=OFF')
            self.db.execute('PRAGMA cache_size=-256');self.db.execute('PRAGMA temp_store=FILE')
            self.db.create_collation('TYPED',compare_keys)
            self.db.set_progress_handler(lambda:int(workspace.control.cancelled.is_set() or
                workspace.control.deadline is not None and time.perf_counter()>=workspace.control.deadline),1000)
            self.db.execute('CREATE TABLE rows (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, key TEXT, lookup TEXT)')
            self.page_size=self.db.execute('PRAGMA page_size').fetchone()[0]
            self.has_lookup_index=False
            self._account()
        except BaseException:
            self.db.close();self.path.unlink(missing_ok=True);raise
    def _account(self):
        self.workspace.control.check()
        size=self.db.execute('PRAGMA page_count').fetchone()[0]*self.page_size
        if self.in_memory:
            with self.workspace.lock:
                if self.workspace.memory_bytes+size-self.accounted<=self.workspace.memory_limit:
                    self.workspace.memory_bytes+=size-self.accounted;self.accounted=size
                    self.workspace.peak_memory_bytes=max(self.workspace.peak_memory_bytes,self.workspace.memory_bytes)
                    return
            # This store is single-writer and only read once sealed. Promote all
            # indexes and exact state before exposing the replacement connection.
            self.workspace.reserve(size)
            target=None
            try:
                self.db.commit()
                target=sqlite3.connect(str(self.path),check_same_thread=False)
                self.db.backup(target)
                target.execute('PRAGMA journal_mode=OFF');target.execute('PRAGMA synchronous=OFF')
                target.execute('PRAGMA cache_size=-256');target.execute('PRAGMA temp_store=FILE')
                for name,fn in self.collations.items():target.create_collation(name,fn)
                target.set_progress_handler(lambda:int(self.workspace.control.cancelled.is_set() or
                    self.workspace.control.deadline is not None and time.perf_counter()>=self.workspace.control.deadline),1000)
            except BaseException:
                if target is not None:target.close()
                with self.workspace.lock:self.workspace.bytes-=size
                self.path.unlink(missing_ok=True)
                raise
            self.db.close();self.db=target
            with self.workspace.lock:
                self.workspace.memory_bytes-=self.accounted;self.workspace.spilled_stores+=1
            self.in_memory=False;self.accounted=size
        else:
            self.workspace.reserve(size-self.accounted);self.accounted=size
    def collation(self,name,fn):
        self.collations[name]=fn;self.db.create_collation(name,fn)

    def append(self,row,*,key=None,lookup=None):
        self.workspace.control.check()
        self.append_encoded(stable_text(row),key=key,lookup=lookup)
    def append_encoded(self,text,*,key=None,lookup=None):
        self.workspace.control.check()
        if lookup is not None and not self.has_lookup_index:
            self.db.execute('CREATE INDEX lookup_index ON rows(lookup)');self.has_lookup_index=True
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
                if self.in_memory:self.workspace.memory_bytes-=self.accounted
                else:self.workspace.bytes-=self.accounted
                self.workspace.stores.discard(self)
            self.closed=True


class BufferedRows(DiskRows):
    """Small replayable payloads need neither SQL nor a filesystem write."""
    def __init__(self,workspace):
        self.workspace=workspace;self.buffer=[];self.reserved=0;self.disk=None
        self.count=0;self.encoded_bytes=2;self.closed=False
    def _promote(self):
        if self.disk is not None:return self.disk
        disk=self.workspace.store(buffered=False)
        try:
            for text in self.buffer:disk.append_encoded(text)
        except BaseException:
            disk.close();raise
        self.workspace.release_memory(self.reserved);self.reserved=0;self.buffer.clear();self.disk=disk
        return disk
    @property
    def db(self):return self._promote().db
    def _account(self):return self._promote()._account()
    def append(self,row,*,key=None,lookup=None):
        self.workspace.control.check();text=stable_text(row)
        if key is not None or lookup is not None:self._promote()
        charge=sys.getsizeof(text)+64
        if self.disk is None and self.workspace.claim_memory(charge):
            self.buffer.append(text);self.reserved+=charge
        else:self._promote().append_encoded(text,key=key,lookup=lookup)
        self.count+=1;self.encoded_bytes+=len(text.encode())+int(self.count>1)
    def finish(self):
        if self.disk is not None:self.disk.finish()
        return self
    def __iter__(self):
        if self.disk is not None:yield from self.disk
        else:
            for text in self.buffer:
                self.workspace.control.check();yield json.loads(text)
    def close(self):
        if not self.closed:
            if self.disk is not None:self.disk.close()
            self.workspace.release_memory(self.reserved);self.reserved=0;self.buffer.clear()
            with self.workspace.lock:self.workspace.stores.discard(self)
            self.closed=True


def distinct_bucket(canonical):
    # Request-local bucket only: Python hashes honor typed tuple/Decimal equality.
    # Never persisted as an identity; full row equality resolves every collision.
    return str(hash(canonical))


def distinct(workspace,rows,*,preserve_order=False,ordered_output=True):
    memory={};reserved=0;store=None
    def insert(text,canonical):
        digest=distinct_bucket(canonical)
        # Hashes locate buckets only. Full typed equality resolves collisions.
        inserted=store.db.execute("INSERT OR IGNORE INTO rows(payload,key,lookup) VALUES(?,?,'0')",(text,digest))
        if inserted.rowcount:
            store._account();return
        match=None;bucket_size=0
        for seq,previous in store.db.execute('SELECT seq,payload FROM rows WHERE key=?',(digest,)):
            bucket_size+=1
            if row_key(json.loads(previous))==canonical:match=(seq,previous);break
        if match is None:
            store.db.execute('INSERT INTO rows(payload,key,lookup) VALUES(?,?,?)',(text,digest,str(bucket_size)))
        elif not preserve_order and text<match[1]:store.db.execute('UPDATE rows SET payload=? WHERE seq=?',(text,match[0]))
        store._account()
    try:
        for row in rows:
            workspace.control.check();text=stable_text(row);canonical=row_key(row)
            if store is None:
                previous=memory.get(canonical)
                if previous is not None and (preserve_order or text>=previous[0]):continue
                charge=2*len(text.encode())+2*len(key_text(canonical).encode())+512
                delta=charge-(previous[1] if previous is not None else 0)
                if workspace.claim_memory(delta):
                    memory[canonical]=(text,charge);reserved+=delta;continue
                store=workspace.store(buffered=False);store.db.execute('CREATE UNIQUE INDEX distinct_key ON rows(key,lookup)')
                for key,(value,size) in memory.items():insert(value,key)
                memory.clear();workspace.release_memory(reserved);reserved=0
            insert(text,canonical)
        if store is None:
            values=memory.values() if preserve_order or not ordered_output else sorted(memory.values(),key=lambda v:v[0])
            for text,_ in values:workspace.control.check();yield json.loads(text)
        else:yield from store.select('SELECT payload FROM rows ORDER BY '+('seq' if preserve_order or not ordered_output else 'payload'))
    finally:
        memory.clear();workspace.release_memory(reserved)
        if store is not None:store.close()


@contextmanager
def managed(workspace):
    s=workspace.store(buffered=False)
    try:yield s
    finally:s.close()
