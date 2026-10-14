"""Bounded compact operator state, promoted atomically to an indexed spill table."""
import pickle
import sys
from xgap.runtime.spill_rows import key_text


def key_charge(key):
    # Typed canonical keys are immutable tuples. Charge their actual Python
    # structure once per new group, including shared values conservatively.
    pending=[key];size=0
    while pending:
        value=pending.pop();size+=sys.getsizeof(value)
        if isinstance(value,tuple):pending.extend(value)
    return size


class AdaptiveState:
    def __init__(self,workspace):
        self.workspace=workspace;self.values={};self.reserved=0;self.store=None
    def __enter__(self):return self
    def __exit__(self,*args):
        self.workspace.release_memory(self.reserved);self.reserved=0;self.values.clear()
        if self.store is not None:self.store.close()
    def get(self,key):
        if self.store is None:raw=self.values.get(key)
        else:
            found=self.store.db.execute('SELECT value FROM states WHERE key=?',(key_text(key),)).fetchone()
            raw=None if found is None else found[0]
        # Only bytes created within this request are deserialized, never files
        # supplied by callers or persisted cross-request cache entries.
        return None if raw is None else pickle.loads(raw)
    def put(self,key,value):
        self.workspace.control.check();raw=pickle.dumps(value,protocol=5)
        if self.store is None:
            old=self.values.get(key)
            charge=len(raw)-(len(old) if old is not None else 0)+(0 if old is not None else key_charge(key)+256)
            if self.workspace.claim_memory(charge):
                self.reserved+=charge;self.values[key]=raw;return
            self.store=self.workspace.store(buffered=False)
            self.store.db.execute('CREATE TABLE states (key TEXT PRIMARY KEY COLLATE TYPED, value BLOB) WITHOUT ROWID')
            for k,v in self.values.items():
                self.store.db.execute('INSERT INTO states VALUES(?,?)',(key_text(k),v));self.store._account()
            self.workspace.release_memory(self.reserved);self.reserved=0;self.values.clear()
        self.store.db.execute('INSERT INTO states VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key_text(key),raw))
        self.store._account()
    def items(self):
        if self.store is None:
            for k in sorted(self.values):
                self.workspace.control.check();yield pickle.loads(self.values[k])
        else:
            for raw, in self.store.db.execute('SELECT value FROM states ORDER BY key COLLATE TYPED'):
                self.workspace.control.check();yield pickle.loads(raw)
