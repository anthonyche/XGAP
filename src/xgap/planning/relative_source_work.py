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
DEGREE_SCHEMA='xgap-relative-source-work-v2'
KEY_SCHEMA='xgap-relative-source-work-v3'
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
    # backend, edge label, stored endpoint role, rows, NDV, sum(degree^2), max
    endpoint_degrees: tuple=()
    distinct_binding_keys: bool=False

    def __post_init__(self):
        if type(self.distinct_binding_keys) is not bool:raise ValueError('Distinct binding-key profile must be boolean')
        if any(not isinstance(p,(tuple,list)) or len(p)!=3 or not isinstance(p[0],str)
               for p in self.populations):
            raise ValueError('Typed source population triples required')
        object.__setattr__(self,'populations',tuple(sorted(tuple(p) for p in self.populations)))
        object.__setattr__(self,'unique_node_properties',tuple(sorted(self.unique_node_properties)))
        object.__setattr__(self,'endpoint_degrees',tuple(sorted(tuple(r) for r in self.endpoint_degrees)))
        known={s.backend_id:s for s in self.statistics.entries}
        if (len(self.populations)!=len(known) or {p[0] for p in self.populations}!=set(known)
                or any(len(p)!=3 or any(type(v) is not int or v<0 for v in p[1:])
                    or sum(p[1:])!=known[p[0]].total_rows for p in self.populations)
                or type(self.record_quantum) is not int or self.record_quantum<=0
                or not isinstance(self.preparation_ref,str) or not self.preparation_ref
                or any(not isinstance(p,str) or not p for p in self.unique_node_properties)
                or len(set(self.unique_node_properties))!=len(self.unique_node_properties)):
            raise ValueError('Frozen complete source populations and provenance required')
        if (len({r[:3] for r in self.endpoint_degrees})!=len(self.endpoint_degrees)
                or any(len(r)!=7 or r[0] not in known or not isinstance(r[1],str) or r[2] not in ('source','target')
                    or any(type(v) is not int or v<0 for v in r[3:]) or r[4]>r[3]
                    or bool(r[3])!=bool(r[4]) or r[5]<r[3] or r[6]>r[3]
                    for r in self.endpoint_degrees)):
            raise ValueError('Invalid frozen endpoint degree statistics')

    @property
    def model_sha256(self):return self.to_dict()['model_sha256']

    def to_dict(self):
        body=dict(schema_version=KEY_SCHEMA if self.distinct_binding_keys else DEGREE_SCHEMA if self.endpoint_degrees else SCHEMA,statistics=self.statistics.to_dict(),populations=self.populations,
            unique_node_properties=self.unique_node_properties,preparation_ref=self.preparation_ref,
            record_quantum=self.record_quantum)
        if self.endpoint_degrees:body['endpoint_degrees']=self.endpoint_degrees
        if self.distinct_binding_keys:body['distinct_binding_keys']=True
        return {**body,'model_sha256':_hash(body)}

    @classmethod
    def from_dict(cls,raw):
        doc=dict(raw);digest=doc.pop('model_sha256',None)
        if doc.get('schema_version') not in (SCHEMA,DEGREE_SCHEMA,KEY_SCHEMA) or _hash(doc)!=digest:raise ValueError('Relative work model hash/schema differs')
        if (doc['schema_version']==KEY_SCHEMA)!=bool(doc.get('distinct_binding_keys')):raise ValueError('Binding-key model schema differs')
        if doc['schema_version']!=KEY_SCHEMA and (doc['schema_version']==DEGREE_SCHEMA)!=bool(doc.get('endpoint_degrees')):raise ValueError('Degree model schema differs')
        doc.pop('schema_version');doc['statistics']=FrozenSourceStatistics.from_dict(doc['statistics'])
        return cls(**doc)

    def predict(self,plan):
        started=time.perf_counter();sources={s.backend_id:s for s in self.statistics.entries}
        counts={b:(n,e) for b,n,e in self.populations};nodes={n.node_id:n for n in plan.nodes}
        children={k:[] for k in nodes};degree={k:len(n.inputs) for k,n in nodes.items()}
        for node in plan.nodes:
            for parent in node.inputs:children[parent].append(node.node_id)
        queue=deque(sorted(k for k,v in degree.items() if v==0));rows={};unique={};columns={}
        scan=transfer=local=keys=calls=risk=0.;details=[];source_join_work=0.
        total_population=sum(n+e for n,e in counts.values())
        degrees={r[:3]:r[3:] for r in self.endpoint_degrees}

        def singleton(condition,fields):
            if condition.get('op')=='and':return any(singleton(c,fields) for c in condition['args'])
            return (condition.get('op')=='eq' and condition.get('field') in fields
                and 'right_field' not in condition and condition.get('value') is not None)

        while queue:
            node=nodes[queue.popleft()];p=node.parameters
            incoming=sum(rows[i] for i in node.inputs);out=incoming
            sent=None;key_input=incoming
            if self.distinct_binding_keys and node.kind is R.REMOTE_BIND_QUERY:
                from xgap.planning.binding_cardinality import bind_keys
                key_input=bind_keys(node,rows,columns)
            fields=set(unique[node.inputs[0]]) if len(node.inputs)==1 else set();degree_evidence=None
            if node.kind in REMOTE:
                backend=p['backend_id'];s=sources.get(backend)
                if s is None or plan.metadata['source_identities'].get(backend)!={
                        'source_id':s.source_id,'snapshot_version':s.snapshot_version}:
                    raise ValueError('Relative work/source snapshot mismatch')
                node_rows,edge_rows=counts[backend];a=p['artifact']['parameters'];compiler=a.get('compiler')
                if compiler=='native-spj-final-topk-v1':
                    from xgap.planning.native_spj_work import source_work
                    membership=a.get('source_pushdown',{}).get('identity_membership')
                    if node.kind is R.REMOTE_BIND_QUERY:
                        cap=p.get('max_bindings')
                        if (not membership or membership.get('profile')!='exact-external-key-semijoin-v1'
                                or membership.get('parameter')!=p.get('parameter')
                                or not membership.get('before_complete_witness_and_topk')
                                or type(cap) is not int or cap<=0):
                            raise ValueError('Native SPJ bind requires checked complete-query membership')
                        sent=min(key_input,float(cap));keys+=sent
                        if key_input>cap:risk+=(key_input/cap)*total_population
                    elif membership:
                        raise ValueError('Native SPJ membership requires a bound key input')
                    work=source_work(a,backend,counts[backend],degrees,self.unique_node_properties)
                    scan+=work['scan_records'];source_join_work+=work['join_records']
                    out=work['output_records'];transfer+=out;calls+=1
                    rows[node.node_id]=out;unique[node.node_id]=set()
                    details.append(dict(node=node.node_id,estimated_rows=out,unique_fields=[],source_work=work))
                    if self.distinct_binding_keys:
                        from xgap.planning.binding_cardinality import propagate
                        columns[node.node_id]=propagate(node,out,rows,columns,populations=counts,degrees=degrees,
                            unique_properties=self.unique_node_properties,sent=sent)
                        details[-1].update(column_ndv_proxy=columns[node.node_id],binding_input_rows=incoming,
                            binding_distinct_key_proxy=key_input if node.kind is R.REMOTE_BIND_QUERY else None)
                    for child in children[node.node_id]:
                        degree[child]-=1
                        if degree[child]==0:queue.append(child)
                    continue
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
                    sent=min(key_input,float(cap));keys+=sent
                    # Uniform-degree proxy, not an assertion about a particular
                    # key or an upper bound. Full edge scans always have work.
                    fanout=1. if node_read else edge_rows/max(1,node_rows)
                    descriptor=a.get('edge_statistics_descriptor',{});role=a.get('bound_identity_column')
                    if descriptor.get('direction')=='IN' and role in ('source','target'):
                        role='target' if role=='source' else 'source'
                    endpoint_info=degrees.get((backend,descriptor.get('label'),role))
                    if not node_read and endpoint_info:
                        count,ndv,squared,maximum=endpoint_info
                        # Edge-derived keys oversample high-degree endpoints.
                        # This frozen second moment is still a proxy, never a
                        # claim about the current query's literal/key set.
                        fanout=(squared/max(1,count) if sent>1 else count/max(1,ndv))
                        degree_evidence=dict(endpoint=role,rows=count,ndv=ndv,mean=count/max(1,ndv),
                            size_biased_mean=squared/max(1,count),maximum=maximum,
                            selected_proxy=fanout,origin='frozen complete source; no current keys read')
                    work=out=min(population,sent*fanout)
                    witness=a.get('leaf_witness')
                    if witness:
                        if witness.get('profile')!='contribution-leaf-witness-v1' or witness.get('returned_rows_per_key_upper_bound')!=1:
                            raise ValueError('Unknown leaf witness cardinality contract')
                        out=min(out,sent)
                        fields.add(a['bound_identity_column'])
                        # The output bound does NOT bound adjacency scanning;
                        # retain the unreduced scan-work proxy above.
                    if key_input>cap:
                        risk+=(key_input/cap)*total_population
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
                    unknown_join=(min(1e100,l*r) if self.endpoint_degrees else max(l,r))
                    out=min(l,r) if lu and ru else l if ru else r if lu else unknown_join
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
            details.append(dict(node=node.node_id,estimated_rows=out,unique_fields=sorted(fields),endpoint_degree=degree_evidence))
            if self.distinct_binding_keys:
                from xgap.planning.binding_cardinality import propagate
                columns[node.node_id]=propagate(node,out,rows,columns,populations=counts,degrees=degrees,
                    unique_properties=self.unique_node_properties,sent=sent)
                details[-1].update(column_ndv_proxy=columns[node.node_id],binding_input_rows=incoming if node.kind is R.REMOTE_BIND_QUERY else None,
                    binding_distinct_key_proxy=key_input if node.kind is R.REMOTE_BIND_QUERY else None)
            for child in children[node.node_id]:
                degree[child]-=1
                if degree[child]==0:queue.append(child)
        if len(rows)!=len(nodes):raise ValueError('Cyclic relative-work dependency')
        score=calls+(scan+source_join_work+transfer+keys+risk)/self.record_quantum+local/(10*self.record_quantum)
        if not math.isfinite(score) or score<0:raise ValueError('Relative score overflow')
        return RelativePrediction(score,(time.perf_counter()-started)*1000,
            dict(model_sha256=self.model_sha256,source_statistics_sha256=self.statistics.sha256,
                source_scan_record_units=scan,source_join_record_proxy=source_join_work,
                returned_record_proxy=transfer,transmitted_key_proxy=keys,
                coordinator_input_proxy=local,bind_overflow_risk_work=risk,remote_call_units=calls,nodes=details,
                assumptions=('Column NDV propagated through typed lineage for deduplicated bind requests; unknown NDV falls back to rows; ' if self.distinct_binding_keys else '')+('Endpoint-specific mean / size-biased degree; unknown many-many join uses capped Cartesian proxy (1e100); proxies, not bounds'
                             if self.endpoint_degrees else 'Uniform average degree, key-preserving joins, conservative identity equality; proxies, not bounds'),
                measured_latency=False,quality_bound=None,fit_calls=0,current_query_observation_calls=0))
