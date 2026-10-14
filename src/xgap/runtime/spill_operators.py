"""Exact pull operators; blocking state is owned by a bounded spill workspace."""
from itertools import chain
from contextlib import contextmanager
from decimal import Decimal,localcontext
from fractions import Fraction
import json
import math

from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.scalars import value_key,row_key,stable_text,representative_key,numeric,scalar_order_key,decimal_binding
from xgap.runtime.spill_rows import managed,distinct,key_text,key_value
from xgap.runtime.binding_operations import aggregate_rows,sort_rows


def fold_aggregate(workspace,parameters,rows):
    """Non-DISTINCT aggregates retain one compact state per group, not members."""
    from xgap.runtime.adaptive_state import AdaptiveState
    groups=parameters['group_by'];specs=parameters['aggregations']
    def initial(values):
        return [values,{name:[0,Fraction(0),set(),None] for name in specs}]
    with AdaptiveState(workspace) as states:
        seen=False
        for row in rows:
            workspace.control.check();seen=True
            if any(f not in row for f in groups):raise ValueError('aggregate group fields are missing')
            values=tuple(row[f] for f in groups);key=tuple(map(value_key,values))
            state=states.get(key)
            if state is None:state=initial(values)
            elif tuple(map(representative_key,values))<tuple(map(representative_key,state[0])):state[0]=values
            for name,spec in specs.items():
                op=spec['op'];field=spec.get('field');acc=state[1][name]
                if field is not None and field not in row:raise ValueError('aggregate field is missing')
                value=row if field is None else row[field]
                if field is not None and value is None:continue
                row_key(value) if field is None else value_key(value)
                acc[0]+=1
                if op=='sum':
                    n=numeric(value)
                    if n is None:raise ValueError('aggregate field must be numeric')
                    acc[1]+=Fraction(n.value);acc[2].add(n.kind)
                elif op in ('min','max'):
                    scalar_order_key(value)
                    best=acc[3]
                    if best is None:acc[3]=value
                    else:
                        a,b=scalar_order_key(value),scalar_order_key(best)
                        if (a<b if op=='min' else a>b) or a==b and representative_key(value)<representative_key(best):acc[3]=value
            states.put(key,state)
        if not groups and not seen:states.put((),initial(()))
        for values,accs in states.items():
            output=dict(zip(groups,values))
            for name,spec in specs.items():
                count,total,domain,best=accs[name];op=spec['op']
                output[name]=count if op=='count' else finish_sum(count,total,domain) if op=='sum' else best
            yield output


def finish_sum(count,total,domain):
    if not count:return 0
    if domain=={'integer'}:return int(total)
    with localcontext() as context:
        # Finite decimal denominators contain only powers of 2 and 5. Their
        # bit length bounds the decimal expansion; decimal digit count does not
        # (1 / 2**1000 is the counterexample). Preserve the complete exact sum.
        context.prec=max(1,Decimal(abs(total.numerator)).adjusted()+1)+total.denominator.bit_length()+4
        exact=Decimal(total.numerator)/Decimal(total.denominator)
    answer=float(exact) if 'float' in domain else decimal_binding(exact)
    if isinstance(answer,float) and not math.isfinite(answer):raise ValueError('Aggregate floating result must be finite')
    return answer


def aggregate(workspace,parameters,rows):
    aggregate_rows(parameters,()) # Original option validation, including empty input.
    groups=parameters['group_by'];specs=parameters['aggregations']
    if not any(spec.get('distinct',False) for spec in specs.values()):
        yield from fold_aggregate(workspace,parameters,rows);return
    with managed(workspace) as store:
        for row in rows:
            if any(f not in row for f in groups):raise ValueError('aggregate group fields are missing')
            store.append(row,lookup=key_text(tuple(value_key(row[f]) for f in groups)))
        keys=(v[0] for v in store.db.execute('SELECT DISTINCT lookup FROM rows ORDER BY lookup COLLATE TYPED'))
        if not groups and not len(store):keys=iter([key_text(())])
        for key in keys:
            def members():return store.select('SELECT payload FROM rows WHERE lookup=? ORDER BY seq',(key,))
            group=None
            for row in members():
                v=tuple(row[f] for f in groups)
                if group is None or tuple(map(representative_key,v))<tuple(map(representative_key,group)):group=v
            output=dict(zip(groups,group or ()))
            for name,spec in specs.items():
                op=spec['op'];field=spec.get('field');domain=set()
                def values():
                    for row in members():
                        if field is not None and field not in row:raise ValueError('aggregate field is missing')
                        value=row if field is None else row[field]
                        if field is not None and value is None:continue
                        row_key(value) if field is None else value_key(value)
                        if op=='sum':
                            n=numeric(value)
                            if n is None:raise ValueError('aggregate field must be numeric')
                            domain.add(n.kind)
                        yield value
                with managed(workspace) as unique:
                    if spec.get('distinct',False):
                        unique.db.execute('CREATE UNIQUE INDEX distinct_value ON rows(key)')
                        for v in values():
                            k=key_text(row_key(v) if field is None else value_key(v))
                            previous=unique.db.execute('SELECT payload FROM rows WHERE key=?',(k,)).fetchone()
                            if previous is None:
                                unique.append(v,key=k)
                            else:
                                old=json.loads(previous[0]);rank=stable_text if field is None else representative_key
                                if rank(v)<rank(old):unique.db.execute('UPDATE rows SET payload=? WHERE key=?',(stable_text(v),k));unique._account()
                        stream=iter(unique)
                    else:stream=values()
                    count=0;total=Fraction(0);best=None
                    for v in stream:
                        count+=1
                        if op=='sum':total+=Fraction(numeric(v).value)
                        elif op in ('min','max'):
                            scalar_order_key(v)
                            if best is None:best=v
                            else:
                                a,b=scalar_order_key(v),scalar_order_key(best)
                                if (a<b if op=='min' else a>b) or a==b and representative_key(v)<representative_key(best):best=v
                    if op=='count':output[name]=count
                    elif op=='sum':output[name]=finish_sum(count,total,domain)
                    else:output[name]=best
            yield output


def ordered(workspace,parameters,rows):
    sort_rows(parameters,())
    order=parameters['order_by']
    def compare(a,b):
        left,right=json.loads(a),json.loads(b)
        for spec in order:
            x,y=left[spec['field']],right[spec['field']]
            if x is None or y is None:
                c=((x is None)-(y is None))*(1 if spec.get('nulls','last')=='last' else -1)
            else:
                x,y=scalar_order_key(x),scalar_order_key(y)
                c=((x>y)-(x<y))*(1 if spec.get('direction','asc')=='asc' else -1)
            if c:return c
        return (a>b)-(a<b)
    with managed(workspace) as store:
        store.collation('ANSWER_ORDER',compare)
        for row in rows:
            sort_rows(parameters,(row,));store.append(row)
        limit=parameters['limit']
        yield from store.select('SELECT payload FROM rows ORDER BY payload COLLATE ANSWER_ORDER'+(' LIMIT ?' if limit is not None else ''),
            () if limit is None else (limit,))


@contextmanager
def right_index(workspace,rows,field):
    buckets={};reserved=0;store=None
    try:
        for row in distinct(workspace,rows):
            if field not in row:raise ValueError('right join field is missing')
            if row[field] is None:continue
            key=value_key(row[field]);size=4*len(stable_text(row).encode())+512
            if store is None and workspace.claim_memory(size):
                reserved+=size;buckets.setdefault(key,[]).append(row);continue
            if store is None:
                store=workspace.store(buffered=False)
                for k,values in buckets.items():
                    for value in values:store.append(value,lookup=key_text(k))
                buckets.clear();workspace.release_memory(reserved);reserved=0
            store.append(row,lookup=key_text(key))
        if store is None:yield lambda key:iter(buckets.get(key,()))
        else:yield lambda key:store.select('SELECT payload FROM rows WHERE lookup=? ORDER BY seq',(key_text(key),))
    finally:
        buckets.clear();workspace.release_memory(reserved)
        if store is not None:store.close()


def join(workspace,node,left,right,*,unordered=False):
    p=node.parameters;lk,rk=p.get('left_on'),p.get('right_on');prefix=p.get('right_prefix','right.')
    if not isinstance(lk,str) or not isinstance(rk,str) or not isinstance(prefix,str):raise ValueError('Invalid join fields')
    semi=node.kind is R.COORDINATOR_SEMI_JOIN;mode=p.get('left_value_mode','scalar')
    if semi and mode not in ('scalar','collection'):raise ValueError('Invalid semi-join mode')
    schemas={}
    def track(rows,side):
        uniform=True;fields=None
        for row in rows:
            current=frozenset(row)
            if fields is None:fields=current
            elif fields!=current:uniform=False
            yield row
        schemas[side]=fields if uniform else None
    with right_index(workspace,track(right,'right'),rk) as lookup:
        def pairs():
            for a in distinct(workspace,track(left,'left')):
                if lk not in a:raise ValueError('left join field is missing')
                raw=a[lk]
                if semi:
                    if mode=='collection' and not isinstance(raw,(tuple,list)):raise ValueError('semi-join field must be a collection')
                    values=raw if mode=='collection' else [raw]
                    if any(next(lookup(value_key(v)),None) is not None for v in values if v is not None):yield a
                elif raw is not None:
                    for b in lookup(value_key(raw)):
                        merged=dict(a)
                        for name,value in b.items():
                            merged[name if name not in merged or value_key(merged[name])==value_key(value) else prefix+name]=value
                        yield merged
        values=iter(pairs());sentinel=object();first=next(values,sentinel)
        if first is sentinel:return
        # DISTINCT inputs plus disjoint non-key schemas make a merged row an
        # injective encoding of its input pair. Aggregation/sort consumers do
        # not observe pair order, so no redundant output DISTINCT/sort is needed.
        injective=(not semi and lk==rk and schemas.get('left') is not None and
            schemas.get('right') is not None and schemas['left']&schemas['right']=={lk})
        if unordered and injective:yield from chain((first,),values)
        else:yield from distinct(workspace,chain((first,),values))


def operate(workspace,node,inputs,*,unordered=False):
    from xgap.runtime.scheduler import FederatedScheduler
    from xgap.runtime.row_operations import filter_rows,project_rows,normalize_node_bindings
    k=node.kind;p=node.parameters
    if k in (R.COORDINATOR_JOIN,R.COORDINATOR_SEMI_JOIN):yield from join(workspace,node,*inputs,unordered=unordered)
    elif k is R.COORDINATOR_GROUP_AGGREGATE:yield from aggregate(workspace,p,inputs[0])
    elif k is R.COORDINATOR_SORT_LIMIT:yield from ordered(workspace,p,inputs[0])
    elif k in (R.COORDINATOR_PATH_SELECT,R.COORDINATOR_PATH_COMPOSE):
        from xgap.runtime.spill_paths import paths
        yield from paths(workspace,node,inputs)
    elif k is R.MERGE:yield from distinct(workspace,chain.from_iterable(inputs))
    else:
        functions={R.ALIGN:lambda rows:FederatedScheduler._align(node,rows),
            R.EXCHANGE:lambda rows:rows,R.COORDINATOR_FILTER:lambda rows:filter_rows(rows,p['condition']),
            R.COORDINATOR_ROW_PROJECT:lambda rows:project_rows(rows,p['projections'],namespace=p.get('resource_namespace')),
            R.NORMALIZE_NODE_BINDINGS:lambda rows:normalize_node_bindings(rows,p),
            R.PROJECT:lambda rows:FederatedScheduler._project(node,rows)}
        if k not in functions:raise ValueError('Unsupported stream operator')
        f=functions[k];f(())
        rows=(out for row in inputs[0] for out in f((row,)))
        if k in (R.PROJECT,R.NORMALIZE_NODE_BINDINGS,R.COORDINATOR_ROW_PROJECT):
            yield from distinct(workspace,rows,preserve_order=k is R.COORDINATOR_ROW_PROJECT)
        else:yield from rows
