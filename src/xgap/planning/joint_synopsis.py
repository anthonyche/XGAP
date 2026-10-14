"""Bounded multicolumn frequencies, preserving observed within-row correlation."""
from dataclasses import dataclass, replace
import json
from xgap.planning.cardinality_synopsis import token, Distribution


def atom(v):
    return 'null' if v is None else token(v)


@dataclass(frozen=True)
class JointSynopsis:
    backend: str
    columns: tuple
    domain: str
    rows: int
    ndv: int
    frequencies: tuple = ()

    def __post_init__(self):
        columns=tuple(self.columns)
        pairs=tuple((tuple(v),n) for v,n in self.frequencies)
        keys=[tuple(map(atom,v)) for v,n in pairs]
        if (not self.backend or not self.domain or not 2<=len(columns)<=4 or len(set(columns))!=len(columns)
            or any(not isinstance(c,str) or not c for c in columns)
            or type(self.rows) is not int or type(self.ndv) is not int or not 0<=self.ndv<=self.rows
            or bool(self.rows)!=bool(self.ndv) or len(pairs)>256 or len(pairs)>self.ndv
            or len(set(keys))!=len(keys) or any(len(v)!=len(columns) or type(n) is not int or n<=0 for v,n in pairs)):
            raise ValueError('Invalid joint column synopsis')
        remaining=self.rows-sum(n for _,n in pairs)
        if remaining<self.ndv-len(pairs) or (remaining==0)!=(self.ndv==len(pairs)):
            raise ValueError('Joint frequency mass and NDV disagree')
        object.__setattr__(self,'columns',columns)
        object.__setattr__(self,'frequencies',tuple(sorted(pairs,key=lambda p:tuple(map(atom,p[0])))))

    def to_dict(self):return dict(vars(self))

    def distribution(self,out,fields):
        scale=out/max(1,self.rows)
        return JointDistribution(tuple(fields),out,tuple((tuple(map(atom,v)),n*scale) for v,n in self.frequencies),
            (self.rows-sum(n for _,n in self.frequencies))*scale,self.ndv-len(self.frequencies))


@dataclass(frozen=True)
class JointDistribution:
    fields: tuple
    rows: float
    heavy: tuple
    tail: float
    tail_ndv: float
    predicates: tuple=()

    def scaled(self,out):
        f=out/max(1e-100,self.rows)
        return replace(self,rows=out,heavy=tuple((v,n*f) for v,n in self.heavy),tail=self.tail*f,
            tail_ndv=min(out,self.tail_ndv))

    def marginal(self,field,prior):
        # Exact observed tuple mass plus explicitly heuristic residual mass.
        index=self.fields.index(field);counts={};nulls=0.
        residual=prior.scaled(self.tail)
        counts.update(residual.heavy);nulls=residual.nulls
        for values,n in self.heavy:
            if values[index]=='null':nulls+=n
            else:counts[values[index]]=counts.get(values[index],0)+n
        return Distribution(prior.domain,self.rows,tuple(sorted(counts.items())),
                            residual.tail,residual.tail_ndv,nulls)

    def filtered(self,condition,tail_fraction):
        from xgap.runtime.row_operations import _matches
        from xgap.planning.runtime_estimator import _hash
        key=_hash(condition)
        if key in self.predicates:return self
        kept=tuple((v,n) for v,n in self.heavy if _matches(dict(zip(self.fields,map(json.loads,v))),condition))
        tail=self.tail*tail_fraction
        return replace(self,rows=sum(n for _,n in kept)+tail,heavy=kept,tail=tail,
            tail_ndv=self.tail_ndv*tail_fraction,predicates=self.predicates+(key,))


def remote_joint(node,out,profiles):
    a=node.parameters['artifact']['parameters'];compiler=a.get('compiler')
    prefix='node:' if compiler=='semantic_node_match_v1' else 'edge:'+a.get('edge_statistics_descriptor',{}).get('label','')+':'
    names={'entity':prefix+'entity',**{f:prefix+'property:'+p for f,p in a.get('scalar_properties',{}).items()}}
    if compiler=='semantic_edge_match_v1':
        inverse=a.get('edge_statistics_descriptor',{}).get('direction')=='IN'
        names.update({f:prefix+('target' if f=='source' else 'source') if inverse else prefix+f for f in ('source','target')})
    reverse={v:k for k,v in names.items()}
    return {tuple(reverse[c] for c in p.columns):p.distribution(out,tuple(reverse[c] for c in p.columns))
        for p in profiles if p.backend==node.parameters['backend_id'] and all(c in reverse for c in p.columns)}
