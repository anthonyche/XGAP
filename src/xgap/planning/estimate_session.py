"""Bounded request-local reuse of cardinality subplans, including fact dependencies."""
from collections import OrderedDict
from copy import deepcopy
import pickle


class EstimateSession:
    strict_relative_units=True

    def __init__(self,model,max_entries=2048,max_bytes=16*1024*1024):
        if type(max_entries) is not int or max_entries<1 or type(max_bytes) is not int or max_bytes<1:
            raise ValueError('Positive memo capacity required')
        self.model=model
        self.max_entries=max_entries;self.max_bytes=max_bytes
        self.memo=OrderedDict();self.bytes=0;self.hits=0;self.misses=0

    @property
    def cardinality_aware(self):return self.model.cardinality_aware

    def get(self,key):
        if key not in self.memo:self.misses+=1;return None
        self.hits+=1;self.memo.move_to_end(key)
        return deepcopy(self.memo[key][0])

    def put(self,key,value):
        size=len(key)+len(pickle.dumps(value,protocol=4))
        if size>self.max_bytes:return
        while self.memo and (len(self.memo)>=self.max_entries or self.bytes+size>self.max_bytes):
            _,(_,n)=self.memo.popitem(last=False);self.bytes-=n
        self.memo[key]=(deepcopy(value),size);self.bytes+=size

    def predict(self,plan):return self.predict_conditioned(plan,{})

    def predict_conditioned(self,plan,node_rows,*,observed_filters=None):
        return self.model.predict_conditioned(plan,node_rows,observed_filters=observed_filters,_memo=self)

    def diagnostics(self):
        return dict(hits=self.hits,misses=self.misses,entries=len(self.memo),serialized_bytes=self.bytes,
                    scope='request-local typed subplans with source snapshots and transitive probe facts')
