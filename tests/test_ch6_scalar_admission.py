"""Replay the formal ID-order/epoch mismatch without model or remote calls."""
from rdflib import Graph

from xgap.compilers.global_semantic_sparql import condition, literal
from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_heldout import template_query
from xgap.runtime.row_operations import filter_rows
from xgap.semantic.compact_lowering import lower_compact_query


def test_explicit_lexical_type_agrees_across_coordinator_and_global_rdf():
    pairs=[('person:10','person:2',True),('person:2','person:10',False),
           ('a','a',False),('é','中',True),('10','2',True),
           (1,'2',False),(True,'2',False),(None,'2',False)]
    c=dict(op='lt',field='a',right_field='b',value_type='lexical_string')
    graph=Graph()
    for a,b,expected in pairs:
        assert bool(filter_rows([dict(a=a,b=b)],c)) is expected
        values=['UNDEF' if v is None else literal(v) for v in (a,b)]
        sql='SELECT * WHERE { VALUES (?a ?b) { ('+' '.join(values)+') } FILTER('+condition(c,dict(a='?a',b='?b'))+') }'
        assert bool(list(graph.query(sql))) is expected
    assert not filter_rows([dict(a='10',b='2')],dict(op='lt',field='a',right_field='b'))
    assert not filter_rows([dict(a={'type':'uri','value':'urn:a'},b='b')],c)
    assert filter_rows([dict(a={'type':'literal','value':'a'},b='b')],c)


def test_formal_lowering_keeps_explicit_id_order_and_numeric_epoch():
    core=CORES['D3']
    schema={'identity_property':'xgap_id','graph':{
        'nodes':{'Account':{'properties':['id','timestamp','isBlocked']}},
        'edges':[dict(label='TRANSFERRED_TO',source='Account',target='Account',properties=['id','timestamp','amount'])]}}
    for name in ('outgoing_maximum','ordered_star'):
        q=template_query(core,name,'account:10',1577836800000)
        p,_=lower_compact_query(q,schema,version='v2',optimize=True)
        serialized=str(p.to_dict())
        assert 'lexical_string' in serialized and 'timestamp_ms' not in serialized
        for predicate in q['where']:
            if predicate['left']['property']=='timestamp':
                assert predicate['value_type']=='scalar'
                assert filter_rows([{'t':1577836800001}],dict(op='ge',field='t',value=predicate['right']['value']))
