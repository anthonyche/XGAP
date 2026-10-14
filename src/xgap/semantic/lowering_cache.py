"""Bounded request-local compilation reuse over a frozen public schema."""
from copy import deepcopy
import json

from xgap.agent.intent_certificate import canonical
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.semantic.program import SemanticGraphProgram


class RequestLoweringCache:
    def __init__(self, schema, version, *, max_entries=1024, max_bytes=32*1024*1024):
        if type(max_entries) is not int or max_entries < 1 or type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('Positive lowering cache limits required')
        self.schema = deepcopy(schema)
        self.version = version
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.entries = {}
        self.bytes = self.hits = self.misses = 0

    def lower(self, query):
        key = canonical(query)
        if key in self.entries:
            self.hits += 1
            program, assignment = json.loads(self.entries[key][0])
            return SemanticGraphProgram.from_dict(program), assignment
        self.misses += 1
        result = lower_compact_query(query, self.schema, version=self.version, optimize=True)
        # Store one immutable serialized value, avoiding a deep object-graph
        # copy on insertion and sharing no mutable parameters with consumers.
        payload = canonical([result[0].to_dict(), result[1]])
        size = len(key.encode()) + len(payload.encode())
        if size <= self.max_bytes:
            while self.entries and (len(self.entries) >= self.max_entries or self.bytes + size > self.max_bytes):
                _, old_size = self.entries.pop(next(iter(self.entries)))
                self.bytes -= old_size
            self.entries[key] = (payload, size)
            self.bytes += size
        return result

    def metrics(self):
        return dict(hits=self.hits, misses=self.misses, entries=len(self.entries),
                    serialized_bytes=self.bytes, scope='request-local frozen-schema compilation')
