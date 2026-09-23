"""Frozen analytic ordering, in work units, never latency or a cost bound.

Use source counts and typed descriptors only. Uniform-degree/inner-join proxies
are explicit heuristics; no query result, native text or observed winner is read.
The model is opt-in and leaves all old trained artifacts unchanged.
"""
from collections import deque
from dataclasses import dataclass
import math
import time

from xgap.planning.runtime_estimator import FrozenSourceStatistics, _hash
from xgap.runtime.contracts import RuntimeNodeKind as R

SCHEMA='xgap-relative-source-work-v1'
REMOTE={R.REMOTE_QUERY,R.REMOTE_BIND_QUERY}


@dataclass(frozen=True)
class RelativePrediction:
    relative_cost: float
    prediction_elapsed_ms: float
    provenance: dict
    status: str='ranked'
    estimated_ms: None=None

    def to_dict(self):
        return dict(status=self.status,relative_cost=self.relative_cost,unit='declared_work_units',
            estimated_ms=None,prediction_elapsed_ms=self.prediction_elapsed_ms,provenance=self.provenance)


@dataclass(frozen=True)
class FrozenSourceWorkRanker:
    strict_relative_units=True
    statistics: FrozenSourceStatistics
    # backend, complete node records, complete stored edge records
    populations: tuple
    unique_node_properties: tuple
    preparation_ref: str
    record_quantum: int=1024

    def __post_init__(self):
        if any(not isinstance(p,(tuple,list)) or len(p)!=3 or not isinstance(p[0],str)
               for p in self.populations):
            raise ValueError('Typed source population triples required')
        object.__setattr__(self,'populations',tuple(sorted(tuple(p) for p in self.populations)))
        object.__setattr__(self,'unique_node_properties',tuple(sorted(self.unique_node_properties)))
        known={s.backend_id:s for s in self.statistics.entries}
        if (len(self.populations)!=len(known) or {p[0] for p in self.populations}!=set(known)
                or any(len(p)!=3 or any(type(v) is not int or v<0 for v in p[1:])
                    or sum(p[1:])!=known[p[0]].total_rows for p in self.populations)
                or type(self.record_quantum) is not int or self.record_quantum<=0
                or not isinstance(self.preparation_ref,str) or not self.preparation_ref
                or any(not isinstance(p,str) or not p for p in self.unique_node_properties)
                or len(set(self.unique_node_properties))!=len(self.unique_node_properties)):
            raise ValueError('Frozen complete source populations and provenance required')

    @property
    def model_sha256(self):return self.to_dict()['model_sha256']

    def to_dict(self):
        body=dict(schema_version=SCHEMA,statistics=self.statistics.to_dict(),populations=self.populations,
            unique_node_properties=self.unique_node_properties,preparation_ref=self.preparation_ref,
            record_quantum=self.record_quantum)
        return {**body,'model_sha256':_hash(body)}

    @classmethod
    def from_dict(cls,raw):
        doc=dict(raw);digest=doc.pop('model_sha256',None)
        if doc.get('schema_version')!=SCHEMA or _hash(doc)!=digest:raise ValueError('Relative work model hash/schema differs')
        doc.pop('schema_version');doc['statistics']=FrozenSourceStatistics.from_dict(doc['statistics'])
        return cls(**doc)

    def predict(self,plan):
        started=time.perf_counter();sources={s.backend_id:s for s in self.statistics.entries}
        counts={b:(n,e) for b,n,e in self.populations};nodes={n.node_id:n for n in plan.nodes}
        children={k:[] for k in nodes};degree={k:len(n.inputs) for k,n in nodes.items()}
        for node in plan.nodes:
            for parent in node.inputs:children[parent].append(node.node_id)
        queue=deque(sorted(k for k,v in degree.items() if v==0));rows={};unique={}
        scan=transfer=local=keys=calls=risk=0.;details=[]
        total_population=sum(n+e for n,e in counts.values())

        def singleton(condition,fields):
            if condition.get('op')=='and':return any(singleton(c,fields) for c in condition['args'])
            return (condition.get('op')=='eq' and condition.get('field') in fields
                and 'right_field' not in condition and condition.get('value') is not None)

        while queue:
            node=nodes[queue.popleft()];p=node.parameters
            incoming=sum(rows[i] for i in node.inputs);out=incoming
            fields=set(unique[node.inputs[0]]) if len(node.inputs)==1 else set()
            if node.kind in REMOTE:
                backend=p['backend_id'];s=sources.get(backend)
                if s is None or plan.metadata['source_identities'].get(backend)!={
                        'source_id':s.source_id,'snapshot_version':s.snapshot_version}:
                    raise ValueError('Relative work/source snapshot mismatch')
                node_rows,edge_rows=counts[backend];a=p['artifact']['parameters'];compiler=a.get('compiler')
                node_read=compiler=='semantic_node_match_v1'
                if not node_read and compiler!='semantic_edge_match_v1':
                    raise ValueError('Relative work v1 admits node and one-edge Match only')
                population=float(node_rows if node_read else edge_rows)
                fields={'entity'}
                if node_read:
                    fields.update(k for k,v in a.get('scalar_properties',{}).items() if v in self.unique_node_properties)
                work=out=population
                if node.kind is R.REMOTE_BIND_QUERY:
                    cap=p.get('max_bindings')
                    if type(cap) is not int or cap<=0:raise ValueError('Typed runtime bind cap required')
                    sent=min(incoming,float(cap));keys+=sent
                    # Uniform-degree proxy, not an assertion about a particular
                    # key or an upper bound. Full edge scans always have work.
                    fanout=1. if node_read else edge_rows/max(1,node_rows)
                    work=out=min(population,sent*fanout)
                    if incoming>cap:
                        risk+=(incoming/cap)*total_population
                for c in a.get('necessary_row_filters',{}).get('conditions',[]):
                    if singleton(c,fields):out=min(out,1.)
                scan+=work;transfer+=out;calls+=1
            else:
                local+=incoming
                if node.kind is R.NORMALIZE_NODE_BINDINGS:
                    aliases=p.get('identity_fields',{'entity':p.get('entity_field','entity')})
                    fields={aliases.get(f,f) for f in fields}
                elif node.kind is R.COORDINATOR_FILTER:
                    if singleton(p['condition'],fields):out=min(out,1.)
                elif node.kind is R.COORDINATOR_ROW_PROJECT:
                    fields={name for name,value in p['projections'].items()
                        if value.get('kind')=='field' and value['field'] in fields}
                elif node.kind is R.COORDINATOR_JOIN:
                    left,right=node.inputs;l,r=rows[left],rows[right]
                    lu=p['left_on'] in unique[left];ru=p['right_on'] in unique[right]
                    out=min(l,r) if lu and ru else l if ru else r if lu else max(l,r)
                    if not l or not r:out=0.
                    fields=set(unique[left]) if ru else set()
                    # Right fields can be renamed. Only the same-name equality
                    # key has an unambiguous preserved name without full schema.
                    if lu and p['left_on']==p['right_on'] and p['right_on'] in unique[right]:fields.add(p['left_on'])
                elif node.kind is R.COORDINATOR_SEMI_JOIN:out=rows[node.inputs[0]];fields=set(unique[node.inputs[0]])
                elif node.kind is R.COORDINATOR_GROUP_AGGREGATE:
                    group=p.get('group_by',[]);out=out if group else 1.;fields=set(group) if len(group)==1 else set()
                elif node.kind is R.COORDINATOR_SORT_LIMIT:
                    if type(p.get('limit')) is int:out=min(out,p['limit'])
                elif node.kind is R.MERGE:fields=set()
                elif node.kind not in (R.EXCHANGE,R.ALIGN):raise ValueError('Unadmitted relative-work operator')
            if not math.isfinite(out) or out<0:raise ValueError('Invalid relative row proxy')
            rows[node.node_id]=out;unique[node.node_id]=fields
            details.append(dict(node=node.node_id,estimated_rows=out,unique_fields=sorted(fields)))
            for child in children[node.node_id]:
                degree[child]-=1
                if degree[child]==0:queue.append(child)
        if len(rows)!=len(nodes):raise ValueError('Cyclic relative-work dependency')
        score=calls+(scan+transfer+keys+risk)/self.record_quantum+local/(10*self.record_quantum)
        if not math.isfinite(score) or score<0:raise ValueError('Relative score overflow')
        return RelativePrediction(score,(time.perf_counter()-started)*1000,
            dict(model_sha256=self.model_sha256,source_statistics_sha256=self.statistics.sha256,
                source_scan_record_units=scan,returned_record_proxy=transfer,transmitted_key_proxy=keys,
                coordinator_input_proxy=local,bind_overflow_risk_work=risk,remote_call_units=calls,nodes=details,
                assumptions='Uniform average degree, key-preserving joins, conservative identity equality; proxies, not bounds',
                measured_latency=False,quality_bound=None,fit_calls=0,current_query_observation_calls=0))
