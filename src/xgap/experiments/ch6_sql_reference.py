"""Independent SQLite evaluation of the frozen Chapter 6 core grammar.

No XGAP algebra, planner, compiler, backend or model is used. This evaluator is
offline only. Unsupported semantics fail explicitly; a timeout is never [] .
"""
from copy import deepcopy
import json
import re
import time

from xgap.experiments.ch6_fact_index import read_index


def compile_reference(query, index_receipt, *, scale='1', projection_exists=True):
    meta=json.loads(open(index_receipt).read());core=meta['core'];query=deepcopy(query)
    if any(n.get('entity') is not None for n in query['nodes']):
        raise ValueError('Independent SQL reference requires explicit ID literals')
    if scale not in ('1','.25','4'):raise ValueError('Unknown scale')
    if scale=='4':
        # Evaluating only replica zero is equivalent only when every connected
        # component is anchored there. Unanchored aggregates must not use this shortcut.
        adjacent={n['var']:set() for n in query['nodes']}
        for edge in query['edges']+([query['path']] if query.get('path') else []):
            adjacent[edge['source']].add(edge['target']);adjacent[edge['target']].add(edge['source'])
        anchored={p['left']['var'] for p in query['where'] if p['op']=='eq' and p['left']['property']=='id'
                  and 'value' in p['right'] and isinstance(p['right']['value'],str) and '@replica' not in p['right']['value']}
        covered=set(anchored);pending=list(anchored)
        while pending:
            for v in adjacent[pending.pop()]-covered:covered.add(v);pending.append(v)
        if covered!=set(adjacent):raise ValueError('Scale-four reference needs every component anchored in replica zero')
    params=[];conditions=[];tables=[];objects={};refs={};columns={}
    ctes=[];prefix_params=[]
    def ident(s):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',s):raise ValueError('Unsafe reference identifier')
        return '"'+s+'"'
    for i,n in enumerate(query['nodes']):
        alias='n'+str(i);objects[n['var']]=('node',alias);tables.append('nodes '+alias)
        conditions.append(alias+'.kind=?');params.append(n['type'])
    for i,e in enumerate(query['edges']):
        alias='e'+str(i);objects[e['var']]=('edge',alias);tables.append('edges '+alias)
        conditions.extend([alias+'.src='+objects[e['source']][1]+'.id',alias+'.dst='+objects[e['target']][1]+'.id'])
        if e['type']==core['relation']:pass
        elif e['type']==core['relation']+'_EARLY':conditions.append(alias+'.ts<=?');params.append(meta['scope_cut_ms'])
        elif e['type']==core['relation']+'_LATE':conditions.append(alias+'.ts>?');params.append(meta['scope_cut_ms'])
        else:raise ValueError('Unknown source relation')
        if scale=='.25':conditions.append(alias+'.ordinal%4=0')
    path=query.get('path')
    if path:
        if path['time'] is not None or path['mode'] not in ('ACYCLIC','WALK') or not 1<=path['min_hops']<=path['max_hops']<=3:
            raise ValueError('Reference admits untimed WALK/ACYCLIC paths of at most three edges')
        anchors=[p['right']['value'] for p in query['where'] if p['left']==dict(var=path['source'],property='id')
                 and p['op']=='eq' and set(p['right'])=={'value'}]
        if len(anchors)!=1:raise ValueError('Bounded path reference requires one explicit start ID')
        restrict=[]
        if path['type']==core['relation']:pass
        elif path['type']==core['relation']+'_EARLY':restrict.append('ts<=?');prefix_params.append(meta['scope_cut_ms'])
        elif path['type']==core['relation']+'_LATE':restrict.append('ts>?');prefix_params.append(meta['scope_cut_ms'])
        else:raise ValueError('Unknown path relation')
        if scale=='.25':restrict.append('ordinal%4=0')
        ctes.append('path_edges AS (SELECT * FROM edges'+(' WHERE '+' AND '.join(restrict) if restrict else '')+')')
        prefix_params.append(anchors[0])
        seed_cycle=' AND e.src!=e.dst' if path['mode']=='ACYCLIC' else ''
        step_cycle=' AND NOT EXISTS (SELECT 1 FROM json_each(p.visited) WHERE value=e.dst)' if path['mode']=='ACYCLIC' else ''
        ctes.append('paths(id,src,dst,depth,visited) AS ('
            "SELECT hex(e.id),e.src,e.dst,1,json_array(e.src,e.dst) FROM path_edges e WHERE e.src=?"+seed_cycle+
            " UNION ALL SELECT p.id||'/'||hex(e.id),p.src,e.dst,p.depth+1,json_insert(p.visited,'$[#]',e.dst) "
            'FROM paths p JOIN path_edges e ON e.src=p.dst WHERE p.depth<'+str(path['max_hops'])+step_cycle+')')
        objects[path['var']]=('path','p');tables.append('paths p')
        conditions.extend(['p.src='+objects[path['source']][1]+'.id','p.dst='+objects[path['target']][1]+'.id',
                           'p.depth>='+str(path['min_hops'])])
    def ref(r):
        key=(r['var'],r['property'])
        if key in refs:return refs[key]
        kind,a=objects[r['var']];p=r['property']
        if p in (None,'id'):expr=a+'.id'
        elif kind=='edge' and p in ('timestamp',core['measure']):expr=a+('.ts' if p=='timestamp' else '.value')
        elif kind=='path' and p=='length':expr=a+'.depth'
        elif kind=='node':
            ident(p);expr="json_extract("+a+".props,'$."+p+"')"
        else:raise ValueError('Unknown reference property')
        refs[key]=expr;return expr
    for condition in query['where']:
        op={'eq':'=','ne':'!=','lt':'<','le':'<=','gt':'>','ge':'>='}[condition['op']]
        left=ref(condition['left']);right=condition['right']
        if 'var' in right:rhs=ref(right)
        else:rhs='?';params.append(right['value'])
        if condition['value_type']=='lexical_string':
            conditions.append("typeof("+left+")='text'")
            if 'var' in right:conditions.append("typeof("+rhs+")='text'")
            elif type(right['value']) is not str:conditions.append('0')
            conditions.append(left+' COLLATE BINARY '+op+rhs)
        elif condition['value_type']=='scalar':
            # SQL must not supply string order for the legacy numeric-only
            # scalar inequality contract. IDs require explicit lexical_string.
            if condition['op'] in ('lt','le','gt','ge'):
                conditions.append("typeof("+left+") IN ('integer','real')")
                if 'var' in right:conditions.append("typeof("+rhs+") IN ('integer','real')")
                elif type(right['value']) not in (int,float):conditions.append('0')
            conditions.append(left+op+rhs)
        else:raise ValueError('Core SQL reference requires numeric epoch or explicit lexical strings')
    # Distinct complete bindings preserve parallel edge identities. A declared
    # contribution grain then removes existential witnesses before aggregation.
    selected=query['select'];retained=set(objects) if query['contribution_by'] is None else set(query['contribution_by'])
    for expression in selected.values():
        r=expression if 'var' in expression else expression['field']
        if r:retained.add(r['var']);ref(r)
    base=[]
    for v in sorted(retained):base.append(objects[v][1]+'.id AS '+ident('identity_'+v))
    for (v,p),expr in refs.items():
        # Where-only values do not become extra contribution keys.
        if any((e if 'var' in e else e['field'])==dict(var=v,property=p) for e in selected.values()):
            name='c'+str(len(columns));columns[(v,p)]=name;base.append(expr+' AS '+name)
    # Explicit anchor/adjacency join order prevents a statistics-free SQLite
    # planner scanning every node range before applying a selective edge join.
    # This changes only the independent offline evaluator, not an XGAP plan.
    order=[];seen=set()
    def add(var):
        if var not in seen:order.append(var);seen.add(var)
    for p in query['where']:
        if p['op']=='eq' and p['left']['property']=='id' and 'value' in p['right'] and p['left']['var'] in {n['var'] for n in query['nodes']}:
            add(p['left']['var'])
    if not order:add(query['nodes'][0]['var'])
    pending=list(query['edges'])+([path] if path else [])
    while pending:
        connected=[e for e in pending if {e['source'],e['target']}&seen]
        if not connected:raise ValueError('Reference requires a connected anchored graph')
        edge=max(connected,key=lambda e:len({e['source'],e['target']}&seen))
        add(edge['var']);add(edge['source']);add(edge['target']);pending.remove(edge)
    for n in query['nodes']:add(n['var'])
    table_by_alias={table.split()[-1]:table for table in tables}
    # Set-valued node projections do not observe edge multiplicity. When every
    # unanchored node is projected and no predicate couples two edge variables,
    # replace each independent edge witness by EXISTS. This permits lexicographic
    # node-index iteration with early LIMIT instead of sorting all edge paths.
    # Aggregation, paths, edge projections and coupled edge predicates stay on
    # the general reference below. This never changes an evaluated method.
    anchored={p['left']['var'] for p in query['where'] if p['op']=='eq' and p['left']['property']=='id'
              and 'value' in p['right']}
    projected={e['var'] for e in selected.values() if 'var' in e}
    node_vars={n['var'] for n in query['nodes']}
    admissible=(projection_exists and path is None and all('var' in e and e['var'] in node_vars
        and e['property']=='id' for e in selected.values()) and node_vars<=projected|anchored)
    if admissible:
        edge_aliases=[objects[e['var']][1] for e in query['edges']]
        grouped={a:[] for a in edge_aliases};bound={a:[] for a in edge_aliases}
        outer_conditions=[];outer_params=[];offset=0
        for expression in conditions:
            arity=expression.count('?');values=params[offset:offset+arity];offset+=arity
            owners=[a for a in edge_aliases if re.search(r'\b'+re.escape(a)+r'\.',expression)]
            if len(owners)>1:admissible=False;break
            if owners:grouped[owners[0]].append(expression);bound[owners[0]].extend(values)
            else:outer_conditions.append(expression);outer_params.extend(values)
        if admissible:
            if offset!=len(params):raise ValueError('Reference parameter association differs')
            node_order=[]
            for var in ([v for v in order if v in anchored]+
                        [selected[o['field']]['var'] for o in query['order_by']]+
                        [n['var'] for n in query['nodes']]):
                if var not in node_order:node_order.append(var)
            for alias in edge_aliases:
                outer_conditions.append('EXISTS (SELECT 1 FROM edges '+alias+' WHERE '+' AND '.join(grouped[alias])+')')
                outer_params.extend(bound[alias])
            sql='SELECT DISTINCT '+','.join(ref(e)+' AS '+ident(k) for k,e in selected.items())
            sql+=' FROM '+' CROSS JOIN '.join(table_by_alias[objects[v][1]] for v in node_order)
            sql+=' WHERE '+' AND '.join(outer_conditions)
            if query['order_by']:sql+=' ORDER BY '+','.join(ident(o['field'])+' '+o['direction'].upper() for o in query['order_by'])
            if query['limit'] is not None:
                if type(query['limit']) is not int or query['limit']<=0:raise ValueError('Bad query limit')
                sql+=' LIMIT '+str(query['limit'])
            return dict(sql=sql,parameters=outer_params,database=meta['database']['path'])
    # A declared contribution grain existentially removes unused witnesses.
    # Keep anchored nodes outside so the reference starts at a source ID. One
    # correlated EXISTS preserves joint witness constraints, including cycles;
    # do not use independent EXISTS tests for different edges of the same witness.
    anchored={p['left']['var'] for p in query['where'] if p['op']=='eq' and p['left']['property']=='id'
              and 'value' in p['right']}
    essential=retained|anchored
    witnesses=set(objects)-essential if query['contribution_by'] is not None else set()
    outside=[table_by_alias[objects[v][1]] for v in order if v not in witnesses]
    inside=[table_by_alias[objects[v][1]] for v in order if v in witnesses]
    witness_aliases={objects[v][1] for v in witnesses}
    outer_conditions=[];inner_conditions=[];outer_params=[];inner_params=[];offset=0
    for expression in conditions:
        arity=expression.count('?');values=params[offset:offset+arity];offset+=arity
        nested=any(re.search(r'\b'+re.escape(a)+r'\.',expression) for a in witness_aliases)
        (inner_conditions if nested else outer_conditions).append(expression)
        (inner_params if nested else outer_params).extend(values)
    if offset!=len(params):raise ValueError('Reference parameter association differs')
    if inside:
        outer_conditions.append('EXISTS (SELECT 1 FROM '+' CROSS JOIN '.join(inside)+' WHERE '+' AND '.join(inner_conditions)+')')
    elif inner_conditions:raise ValueError('Reference witness condition has no relation')
    params=outer_params+inner_params
    inner='SELECT DISTINCT '+','.join(base)+' FROM '+' CROSS JOIN '.join(outside)+' WHERE '+' AND '.join(outer_conditions)
    plain=[];outer=[];has_aggregate=False
    for name,e in selected.items():
        alias=ident(name)
        if 'var' in e:
            expr=columns[(e['var'],e['property'])];plain.append(expr)
        else:
            has_aggregate=True;field=e['field'];value=columns[(field['var'],field['property'])] if field else '*'
            op=e['aggregate']
            if op not in ('count','sum','min','max') or field is None and op!='count':raise ValueError('Unsupported reference aggregate')
            if e['distinct'] and value=='*':raise ValueError('COUNT DISTINCT * not in reference grammar')
            expr=op.upper()+'('+('DISTINCT ' if e['distinct'] else '')+value+')'
        outer.append(expr+' AS '+alias)
    ctes.append('bindings AS ('+inner+')')
    sql='WITH RECURSIVE '+','.join(ctes)+' SELECT DISTINCT '+','.join(outer)+' FROM bindings'
    if has_aggregate and plain:sql+=' GROUP BY '+','.join(plain)
    if query['order_by']:sql+=' ORDER BY '+','.join(ident(o['field'])+' '+o['direction'].upper() for o in query['order_by'])
    if query['limit'] is not None:
        if type(query['limit']) is not int or query['limit']<=0:raise ValueError('Bad query limit')
        sql+=' LIMIT '+str(query['limit'])
    return dict(sql=sql,parameters=prefix_params+params,database=meta['database']['path'])


class ReferenceExecutionError(RuntimeError):
    def __init__(self, error, evidence):
        super().__init__(str(error));self.evidence=evidence


def evaluate(query, index_receipt, *, seconds=60, row_cap=100000, scale='1'):
    if seconds<=0 or row_cap<1:raise ValueError('Positive reference bounds required')
    compiled=compile_reference(query,index_receipt,scale=scale)
    sql,parameters=compiled['sql'],compiled['parameters']
    started=time.monotonic();explain=[]
    with read_index(compiled['database']) as db:
        explain=[list(r) for r in db.execute('EXPLAIN QUERY PLAN '+sql,parameters)]
        db.set_progress_handler(lambda:1 if time.monotonic()-started>seconds else 0,10000)
        try:
            cursor=db.execute(sql,parameters);rows=[];names=[c[0] for c in cursor.description]
            for r in cursor:
                if len(rows)>=row_cap:raise ValueError('Reference output bound exceeded, not an empty answer')
                rows.append(dict(zip(names,r)))
        except Exception as error:
            if isinstance(error,ValueError):raise
            raise ReferenceExecutionError(error,dict(**compiled,explain=explain,seconds=seconds,
                elapsed_seconds=time.monotonic()-started,scale=scale)) from error
    return dict(rows=rows,engine='independent_relational',sql=sql,parameters=parameters,explain=explain,
                elapsed_seconds=time.monotonic()-started,scale=scale,
                scale4_scope='Queries anchored in the original replica; disconnected renamed copies cannot contribute')
