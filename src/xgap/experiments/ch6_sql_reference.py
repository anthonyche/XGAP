"""Independent SQLite evaluation of the frozen non-path Chapter 6 core grammar.

No XGAP algebra, planner, compiler, backend or model is used. This evaluator is
offline only. Unsupported semantics fail explicitly; a timeout is never [] .
"""
from copy import deepcopy
import json
import re
import time

from xgap.experiments.ch6_fact_index import read_index


def evaluate(query, index_receipt, *, seconds=60, row_cap=100000, scale='1'):
    meta=json.loads(open(index_receipt).read());core=meta['core'];query=deepcopy(query)
    if query.get('path') is not None or any(n.get('entity') is not None for n in query['nodes']):
        raise ValueError('Independent SQL reference requires explicit ID literals and fixed edges')
    if scale not in ('1','.25','4'):raise ValueError('Unknown scale')
    params=[];conditions=[];tables=[];objects={};refs={};columns={}
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
    def ref(r):
        key=(r['var'],r['property'])
        if key in refs:return refs[key]
        kind,a=objects[r['var']];p=r['property']
        if p in (None,'id'):expr=a+'.id'
        elif kind=='edge' and p in ('timestamp',core['measure']):expr=a+('.ts' if p=='timestamp' else '.value')
        elif kind=='node':
            ident(p);expr="json_extract("+a+".props,'$."+p+"')"
        else:raise ValueError('Unknown reference property')
        refs[key]=expr;return expr
    for condition in query['where']:
        op={'eq':'=','ne':'!=','lt':'<','le':'<=','gt':'>','ge':'>='}[condition['op']]
        left=ref(condition['left']);right=condition['right']
        if 'var' in right:rhs=ref(right)
        else:rhs='?';params.append(right['value'])
        conditions.append(left+op+rhs)
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
    inner='SELECT DISTINCT '+','.join(base)+' FROM '+','.join(tables)+' WHERE '+' AND '.join(conditions)
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
    sql='WITH bindings AS ('+inner+') SELECT DISTINCT '+','.join(outer)+' FROM bindings'
    if has_aggregate and plain:sql+=' GROUP BY '+','.join(plain)
    if query['order_by']:sql+=' ORDER BY '+','.join(ident(o['field'])+' '+o['direction'].upper() for o in query['order_by'])
    if query['limit'] is not None:
        if type(query['limit']) is not int or query['limit']<=0:raise ValueError('Bad query limit')
        sql+=' LIMIT '+str(query['limit'])
    started=time.monotonic()
    with read_index(meta['database']['path']) as db:
        db.set_progress_handler(lambda:1 if time.monotonic()-started>seconds else 0,10000)
        cursor=db.execute(sql,params);rows=[];names=[c[0] for c in cursor.description]
        for r in cursor:
            if len(rows)>=row_cap:raise ValueError('Reference output bound exceeded, not an empty answer')
            rows.append(dict(zip(names,r)))
    return dict(rows=rows,engine='independent_relational',sql=sql,parameters=params,
                elapsed_seconds=time.monotonic()-started,scale=scale,
                scale4_scope='Queries anchored in the original replica; disconnected renamed copies cannot contribute')
