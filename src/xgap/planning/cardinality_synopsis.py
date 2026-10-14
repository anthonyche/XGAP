"""Bounded, source-owned column frequencies and typed cardinality propagation.

Heavy values are exact frozen counts; the remaining distinct values are uniform
proxies. Domains declare comparable key encodings. Nothing here is a semantic
certificate, a resource bound, or a query-answer observation.
"""
from dataclasses import dataclass, replace
import json
import math
from xgap.runtime.contracts import RuntimeNodeKind as R


def token(value):
    if type(value) not in (str, int, float, bool) or isinstance(value,float) and not math.isfinite(value):
        raise ValueError('Synopsis values must be finite non-null JSON scalars')
    if type(value) is float and value.is_integer():value=int(value)
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


@dataclass(frozen=True)
class ColumnSynopsis:
    backend: str
    column: str  # node:property:<name>, node:entity, edge:<label>:source/target
    domain: str  # same domain means comparable raw keys, including across engines
    rows: int
    ndv: int
    frequencies: tuple = ()  # (JSON scalar, positive count), at most 256 heavy values
    nulls: int = 0

    def __post_init__(self):
        if (any(not isinstance(v,str) or not v for v in (self.backend,self.column,self.domain))
                or any(type(v) is not int or v<0 for v in (self.rows,self.ndv,self.nulls))
                or self.nulls>self.rows or self.ndv>self.rows-self.nulls
                or bool(self.ndv)!=bool(self.rows-self.nulls) or len(self.frequencies)>256):
            raise ValueError('Invalid bounded column synopsis')
        pairs=tuple((v,n) for v,n in self.frequencies)
        keys=[token(v) for v,n in pairs]
        if (len(set(keys))!=len(keys) or len(pairs)>self.ndv
                or any(type(n) is not int or n<=0 for v,n in pairs)):
            raise ValueError('Invalid heavy-value frequencies')
        remaining=self.rows-self.nulls-sum(n for v,n in pairs)
        if remaining<0 or (self.ndv-len(pairs)==0)!=(remaining==0) or remaining<self.ndv-len(pairs):
            raise ValueError('Frequency mass and NDV disagree')
        object.__setattr__(self,'frequencies',tuple(sorted(pairs,key=lambda p:token(p[0]))))

    def to_dict(self):
        return dict(backend=self.backend,column=self.column,domain=self.domain,rows=self.rows,
                    ndv=self.ndv,frequencies=self.frequencies,nulls=self.nulls)

    def distribution(self,out):
        scale=out/max(1,self.rows)
        return Distribution(self.domain,out,tuple((token(v),n*scale) for v,n in self.frequencies),
                            (self.rows-self.nulls-sum(n for v,n in self.frequencies))*scale,
                            self.ndv-len(self.frequencies),self.nulls*scale)


@dataclass(frozen=True)
class Distribution:
    domain: str
    rows: float
    heavy: tuple
    tail: float
    tail_ndv: float
    nulls: float=0
    predicates: tuple=()

    @property
    def ndv(self):return min(self.rows,sum(n>0 for _,n in self.heavy)+self.tail_ndv)

    def scaled(self,out):
        f=out/max(self.rows,1e-100)
        return replace(self,rows=out,heavy=tuple((v,n*f) for v,n in self.heavy),tail=self.tail*f,
                       tail_ndv=min(self.tail_ndv,out),nulls=self.nulls*f)

    def filtered(self,op,value,value_type=None):
        key=token(value)
        predicate=(op,key,value_type)
        if predicate in self.predicates:return self
        def matches(k):
            from xgap.runtime.row_operations import _matches
            condition=dict(op=op,field='v',value=value)
            if value_type is not None:condition['value_type']=value_type
            return _matches({'v':json.loads(k)},condition)
        kept=tuple((k,n) for k,n in self.heavy if matches(k))
        tail=self.tail;ndv=self.tail_ndv
        if op=='eq':
            tail=0 if any(k==key for k,_ in self.heavy) else tail/max(1,ndv)
            ndv=min(1,ndv) if tail else 0
            if tail:kept=((key,tail),);tail=ndv=0
        elif op=='ne':
            if not any(k==key for k,_ in self.heavy):tail=max(0,tail-tail/max(1,ndv));ndv=max(0,ndv-1)
        else:
            # Unknown tail location: half-range heuristic, explicitly not a bound.
            tail*=.5;ndv*=.5
        total=sum(n for _,n in kept)+tail
        return Distribution(self.domain,total,kept,tail,ndv,predicates=self.predicates+(predicate,))


def join_rows(left,right):
    if left.domain!=right.domain:return None
    l=dict(left.heavy);r=dict(right.heavy)
    la=left.tail/max(1,left.tail_ndv);ra=right.tail/max(1,right.tail_ndv)
    # Explicit heavy overlap plus heavy/tail matches, then residual uniform tail.
    left_only=set(l)-set(r);right_only=set(r)-set(l)
    value=sum(l[k]*r[k] for k in set(l)&set(r))
    # Tail domains are unknown; cap unmatched-heavy allocation by available NDV.
    lr=min(1,right.tail_ndv/max(1,len(left_only)))
    rl=min(1,left.tail_ndv/max(1,len(right_only)))
    value+=sum(l[k]*ra*lr for k in left_only)+sum(r[k]*la*rl for k in right_only)
    ln=max(0,left.tail_ndv-len(right_only));rn=max(0,right.tail_ndv-len(left_only))
    value+=min(ln,rn)*la*ra
    return min(left.rows*right.rows,value)


def remote_columns(node,out,synopses):
    a=node.parameters['artifact']['parameters'];backend=node.parameters['backend_id'];compiler=a.get('compiler')
    if compiler=='semantic_node_match_v1':
        names={'entity':'node:entity',**{f:'node:property:'+p for f,p in a.get('scalar_properties',{}).items()}}
    elif compiler=='semantic_edge_match_v1':
        d=a.get('edge_statistics_descriptor',{});label=d.get('label','')
        names={f:'edge:'+label+':'+('target' if f=='source' else 'source' if f=='target' else f)
               if d.get('direction')=='IN' else 'edge:'+label+':'+f for f in ('source','target')}
        names.update({f:'edge:'+label+':property:'+p for f,p in a.get('scalar_properties',{}).items()})
    else:return {}
    return {f:synopses[(backend,name)].distribution(out) for f,name in names.items() if (backend,name) in synopses}


def filter_columns(columns,condition,out):
    if condition.get('op')=='and':
        for c in condition['args']:columns,out=filter_columns(columns,c,out)
        return columns,out
    field=condition.get('field');op=condition.get('op');value=condition.get('value')
    if op in ('or','not','is_null','is_not_null') or 'right_field' in condition or value is None:
        from xgap.runtime.row_operations import condition_fields
        used=condition_fields(condition)
        groups=[(k,v) for k,v in columns.items() if isinstance(k,tuple) and used<=set(k)]
        if groups:
            key,joint=max(groups,key=lambda kv:(len(kv[0]),kv[0]))
            # Tuple frequencies are exact; unobserved tuple predicates retain a
            # declared half-range proxy (null comparisons are always false).
            fraction=0. if 'value' in condition and value is None else .5
            selected=joint.filtered(condition,fraction);new=min(out,selected.rows)
            return {k:(selected if k==key else selected.marginal(k,v) if isinstance(k,str) and k in key else v.scaled(new))
                    for k,v in columns.items()},new
    if field not in columns or op not in ('eq','ne','lt','le','gt','ge') or 'right_field' in condition or value is None:
        return columns,out
    groups=[(k,v) for k,v in columns.items() if isinstance(k,tuple) and field in k]
    if groups:
        key,joint=max(groups,key=lambda kv:(len(kv[0]),kv[0]))
        marginal=columns[field].filtered(op,value,condition.get('value_type'))
        selected=joint.filtered(condition,min(1,marginal.rows/max(out,1e-100)))
        new=min(out,selected.rows)
        return {k:(selected if k==key else selected.marginal(k,v) if isinstance(k,str) and k in key else v.scaled(new)) for k,v in columns.items()},new
    selected=columns[field].filtered(op,value,condition.get('value_type'));new=min(out,selected.rows)
    return {k:(selected if k==field else v.scaled(new)) for k,v in columns.items()},new


def local_columns(node,out,distributions):
    p=node.parameters;incoming=dict(distributions[node.inputs[0]]) if node.inputs else {}
    if node.kind is R.NORMALIZE_NODE_BINDINGS:
        aliases=p.get('identity_fields',{'entity':p.get('entity_field','entity')})
        incoming={aliases.get(f,f) if isinstance(f,str) else tuple(aliases.get(c,c) for c in f):
                  v if isinstance(f,str) else replace(v,fields=tuple(aliases.get(c,c) for c in f)) for f,v in incoming.items()}
    elif node.kind is R.COORDINATOR_ROW_PROJECT:
        aliases={s['field']:name for name,s in p['projections'].items() if s.get('kind')=='field'}
        groups={tuple(aliases[c] for c in k):replace(v,fields=tuple(aliases[c] for c in k)) for k,v in incoming.items()
                if isinstance(k,tuple) and all(c in aliases for c in k)}
        incoming={name:incoming[s['field']] for name,s in p['projections'].items()
                  if s.get('kind')=='field' and s['field'] in incoming}
        incoming.update(groups)
    elif node.kind not in (R.COORDINATOR_FILTER,R.EXCHANGE):
        # Joins/aggregations change key frequency shape; do not reuse input MCVs.
        return {}
    return {k:v.scaled(out) for k,v in incoming.items()}
