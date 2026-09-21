"""Pinned read-only scalar information targets; estimates never certify semantics.

Hosts register artifacts and categories before a request. Search reads only these
public declarations. Only the chosen action invokes the backend. Raw scalar values
are receipts; the planner receives a finite category and its frozen cost model.
"""
from dataclasses import asdict, dataclass
import math
import time

from xgap.agent.intent_certificate import fingerprint, canonical
from xgap.agent.unified_lookahead import cost
from xgap.infrastructure.runtime import QueryArtifact


@dataclass(frozen=True)
class InformationTarget:
    name: str
    backend: str
    source_id: str
    version: str
    kind: str
    artifact_json: str
    column: str = 'value'
    thresholds: tuple[int, ...] = (100,)
    labels: tuple[str, ...] = ('small','large','unknown')
    row_estimates: tuple[float, ...] = (50.0,10000.0,10000.0)
    probabilities: tuple[float, ...] | None = None
    action_cost: float = 0.1
    row_cost: float = 0.001
    bind_fraction: float = 0.1
    bind_startup: float = 0.25
    gates_rule: str | None = None
    gate_label: str | None = None

    def __post_init__(self):
        if (not all(isinstance(s,str) and s for s in (self.name,self.backend,self.source_id,self.version,self.column))
                or self.kind not in ('probe','metadata') or not isinstance(self.thresholds,tuple)
                or not 1<=len(self.thresholds)<=8 or any(type(x) is not int or not 0<=x<2**63 for x in self.thresholds)
                or tuple(sorted(set(self.thresholds)))!=self.thresholds or not isinstance(self.labels,tuple)
                or len(self.labels)!=len(self.thresholds)+2 or len(set(self.labels))!=len(self.labels)
                or self.labels[-1]!='unknown' or len(self.row_estimates)!=len(self.labels)
                or not isinstance(self.artifact_json,str) or len(self.artifact_json.encode())>65536):
            raise ValueError('Invalid finite information target')
        import json
        artifact = json.loads(self.artifact_json)
        if (canonical(artifact)!=self.artifact_json or set(artifact)!=set(QueryArtifact.from_dict(artifact).to_dict())
                or artifact['source_path'] is not None or artifact['language'] not in ('sparql','cypher')):
            raise ValueError('Registered inline native scalar artifact required')
        for value in (*self.row_estimates,self.action_cost,self.row_cost,self.bind_fraction,self.bind_startup):cost(value)
        if self.bind_fraction>1:raise ValueError('Bind selectivity estimate exceeds one')
        if self.probabilities is not None:
            if not isinstance(self.probabilities,tuple) or len(self.probabilities)!=len(self.labels):
                raise ValueError('An explicit probability for every outcome is required')
            for p in self.probabilities:cost(p)
            if not math.isclose(sum(self.probabilities),1,rel_tol=0,abs_tol=1e-12):raise ValueError('Probabilities must sum to one')
        if (self.gates_rule is None)!=(self.gate_label is None) or self.gate_label is not None and self.gate_label not in self.labels[:-1]:
            raise ValueError('Metadata rule gate needs a supported non-unknown label')
        if self.gates_rule not in (None,'entity_bind','share_read','prefilter','source_placement'):
            raise ValueError('Unknown physical rule gate')

    @property
    def identity(self):return fingerprint(asdict(self))

    def category(self,rows):
        if not isinstance(rows,list) or len(rows)!=1 or set(rows[0])!={self.column}:return 'unknown'
        value=rows[0][self.column]
        # Native scalar adapters commonly represent RDF integers as strings.
        if isinstance(value,str) and value.isdecimal() and len(value)<=19:value=int(value)
        if type(value) is not int or not 0<=value<2**63:return 'unknown'
        return self.labels[next((i for i,t in enumerate(self.thresholds) if value<=t),len(self.thresholds))]

    def invoke(self,clients,sources):
        import json
        source=sources.get(self.source_id)
        if source is None or source.snapshot_version!=self.version or self.backend not in source.replica_backend_ids:
            raise ValueError('Information source version/replica changed')
        started=time.perf_counter()
        report=clients[self.backend].execute(QueryArtifact.from_dict(json.loads(self.artifact_json)))
        if report.backend_id!=self.backend:raise ValueError('Information backend identity differs')
        label=self.category(report.rows) if report.success else 'unknown'
        return label,dict(target=self.name,target_sha256=self.identity,backend=self.backend,
            source_id=self.source_id,version=self.version,label=label,success=report.success,
            rows=report.rows,error=report.error,elapsed_ms=(time.perf_counter()-started)*1000,
            remote_adapter_calls=1,semantic_authority=False)


def targets_from_dict(items):
    result=[]
    for item in items:
        raw=dict(item)
        for name in ('thresholds','labels','row_estimates','probabilities'):
            if raw.get(name) is not None:raw[name]=tuple(raw[name])
        result.append(InformationTarget(**raw))
    return tuple(result)
