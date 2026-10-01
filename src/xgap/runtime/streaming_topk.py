"""Exact pipelined SPJ tails with O(K) retained answers, not O(join output).

This evaluates existing runtime operators, not a new query operator. Exclusive
left-deep inner joins, filters and field projections can stream into a final
fully ordered string/null top-K. Remote consumers, aggregates, partial ordering,
ambiguous column collisions and noncanonical output types are barriers.
"""
from collections import Counter,defaultdict
from functools import cmp_to_key
import heapq
import math

from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.row_operations import condition_fields,_matches
from xgap.runtime.scalars import value_key,stable_text


def islands(plan):
    nodes={n.node_id:n for n in plan.nodes};uses=Counter(i for n in plan.nodes for i in n.inputs)
    result=[]
    for root in plan.roots:
        end=nodes[root];p=end.parameters
        if end.kind is not R.COORDINATOR_SORT_LIMIT or type(p.get('limit')) is not int or not 1<=p['limit']<=1000:continue
        group={root};boundaries=set()
        def visit(identifier,right=False):
            node=nodes[identifier]
            allowed=node.kind in (R.COORDINATOR_FILTER,R.COORDINATOR_ROW_PROJECT,R.COORDINATOR_JOIN)
            if (not allowed or uses[identifier]!=1 or identifier in plan.roots
                    or right and node.kind is R.COORDINATOR_JOIN):
                boundaries.add(identifier);return
            if node.kind is R.COORDINATOR_ROW_PROJECT and any(
                    v.get('kind')!='field' for v in node.parameters.get('projections',{}).values()):
                boundaries.add(identifier);return
            group.add(identifier)
            for i,child in enumerate(node.inputs):visit(child,right or node.kind is R.COORDINATOR_JOIN and i==1)
        visit(end.inputs[0])
        if len(group)<=64 and any(nodes[i].kind is R.COORDINATOR_JOIN for i in group):
            result.append(dict(root=root,nodes=group,boundaries=boundaries))
    return result


def run(island,nodes,results):
    """Return None before execution if the finite actual-column check declines."""
    root=island['root'];group=island['nodes'];schemas={};origins={};types={}
    for leaf in island['boundaries']:
        rows=results[leaf].rows
        if not rows:return None  # ordinary empty-input handling stays authoritative
        fields=set(rows[0]);schemas[leaf]=fields;origins[leaf]={f:{(leaf,f)} for f in fields}
        for row in rows:
            if set(row)!=fields:return None
            for f,v in row.items():
                if type(v) not in (type(None),str,int,bool,float) or type(v) is float and not math.isfinite(v):return None
                types.setdefault((leaf,f),set()).add(type(v))
    ordered=[]
    def prepare(identifier):
        if identifier in schemas:return schemas[identifier]
        node=nodes[identifier];p=node.parameters
        child=prepare(node.inputs[0]);fields=set(child);lineage=dict(origins[node.inputs[0]])
        if node.kind is R.COORDINATOR_JOIN:
            right=prepare(node.inputs[1]);lk,rk=p.get('left_on'),p.get('right_on')
            if lk not in child or rk not in right:raise ValueError('Missing join key')
            if not isinstance(p.get('right_prefix','right.'),str):raise ValueError('Invalid join prefix')
            if child&right-({lk} if lk==rk else set()):raise ValueError('Ambiguous join columns')
            fields|=right
            for f,source in origins[node.inputs[1]].items():lineage[f]=lineage.get(f,set())|source
        elif node.kind is R.COORDINATOR_FILTER:
            if not condition_fields(p['condition'])<=fields:raise ValueError('Missing filter field')
            # Calendar parsing has a separate lexical contract; keep its
            # materialized representative selection until independently proved.
            def calendar(c):return c.get('value_type')=='timestamp_ms' or any(calendar(a) for a in c.get('args',())) or ('arg' in c and calendar(c['arg']))
            if calendar(p['condition']):raise ValueError('Calendar filter barrier')
        elif node.kind is R.COORDINATOR_ROW_PROJECT:
            lineage={f:lineage[v['field']] for f,v in p['projections'].items()}
            fields=set(lineage)
        elif node.kind is R.COORDINATOR_SORT_LIMIT:
            ordering=p.get('order_by',());names=[o['field'] for o in ordering]
            if not names or set(names)!=fields or len(names)!=len(fields):raise ValueError('Partial order')
            if any(o.get('direction','asc') not in ('asc','desc') or o.get('nulls','last') not in ('first','last')
                   or set(o)-{'field','direction','nulls'} for o in ordering):raise ValueError('Invalid order')
            if any(not types[source]<={str,type(None)} for sources in lineage.values() for source in sources):
                raise ValueError('Noncanonical answer representation')
        else:raise ValueError('Non-SPJ tail')
        schemas[identifier]=fields;origins[identifier]=lineage;ordered.append(identifier);return fields
    try:prepare(root)
    except (ValueError,KeyError,TypeError):return None
    if set(ordered)!=group:return None

    counts=Counter();peak_index_rows=0
    def stream(identifier):
        nonlocal peak_index_rows
        if identifier not in group:
            yield from results[identifier].rows;return
        node=nodes[identifier];p=node.parameters
        if node.kind is R.COORDINATOR_JOIN:
            index=defaultdict(list);index_rows=0
            for row in stream(node.inputs[1]):
                if row[p['right_on']] is not None:
                    index[value_key(row[p['right_on']])].append(row);index_rows+=1
            peak_index_rows=max(peak_index_rows,index_rows)
            for left in stream(node.inputs[0]):
                if left[p['left_on']] is None:continue
                for right in index.get(value_key(left[p['left_on']]),()):
                    counts[identifier]+=1;yield {**left,**right}
        else:
            for row in stream(node.inputs[0]):
                if node.kind is R.COORDINATOR_FILTER and not _matches(row,p['condition']):continue
                if node.kind is R.COORDINATOR_ROW_PROJECT:row={f:row[v['field']] for f,v in p['projections'].items()}
                counts[identifier]+=1;yield row

    end=nodes[root];ordering=end.parameters['order_by'];limit=end.parameters['limit']
    def compare(a,b):
        for o in ordering:
            x,y=a[o['field']],b[o['field']]
            if x is None or y is None:
                c=((x is None)-(y is None))*(1 if o.get('nulls','last')=='last' else -1)
            else:c=((x>y)-(x<y))*(1 if o.get('direction','asc')=='asc' else -1)
            if c:return c
        x,y=stable_text(a),stable_text(b);return (x>y)-(x<y)
    class Worst:
        def __init__(self,row,key):self.row=row;self.key=key
        def __lt__(self,other):return compare(self.row,other.row)>0
    heap=[];retained=set();seen=0
    # Output fields are canonical strings/null. Therefore delaying intermediate
    # duplicate elimination cannot change predicates or answer representatives.
    # Evicted keys need not be remembered: the worst retained rank only improves.
    names=sorted(schemas[root])
    for row in stream(end.inputs[0]):
        seen+=1;key=tuple(row[f] for f in names)
        if key in retained:continue
        if len(heap)<limit:
            heapq.heappush(heap,Worst(row,key));retained.add(key)
        elif compare(row,heap[0].row)<0:
            old=heapq.heapreplace(heap,Worst(row,key));retained.remove(old.key);retained.add(key)
    output=tuple(sorted((v.row for v in heap),key=cmp_to_key(compare)))
    return output,dict(profile='exclusive-spj-string-topk-v1',nodes=ordered,streamed_rows=dict(counts),
        terminal_input_rows=seen,retained_answer_rows=len(heap),maximum_answer_rows=limit,
        maximum_single_join_index_rows=peak_index_rows,
        memory_contract='input payloads plus right-side indexes plus O(K) answers; no join-output materialization',
        scan_bound=None,intermediate_metrics='emitted stream occurrences, not materialized distinct relations')
