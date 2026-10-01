"""Replay the formal ID-order/epoch mismatch without model or remote calls."""
from rdflib import Graph

from xgap.compilers.global_semantic_sparql import condition, literal
from xgap.experiments.ch6_fact_index import CORES
from xgap.experiments.ch6_heldout import template_query
from xgap.runtime.row_operations import filter_rows
from xgap.semantic.compact_lowering import lower_compact_query
from xgap.experiments.ch6_profile_revision import revise_schema


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


def test_replicated_node_provider_preserves_all_edge_shards_and_single_source_stratum():
    from copy import deepcopy
    core=CORES['D1']
    for count in (2,4,8):
        names=['graph'] if count==2 else ['graph'+str(i) for i in range(count-1)]
        schema={n:dict(nodes={'Person':dict(properties=['id','xgap_id','firstName'])},
            edges=[dict(label='KNOWS',source='Person',target='Person',properties=['id','timestamp','value'])]) for n in names}
        schema.update(identity_property='xgap_id',control=dict(nodes={'Person':dict(properties=['id','xgap_id','gender'])},edges=[]))
        original=deepcopy(schema);revised=revise_schema(schema)
        assert schema==original
        for name in ('incoming_minimum','outgoing_maximum'):
            for cross in (False,True):
                q=template_query(core,name,'person:1',0,cross=cross)
                program,assignment=lower_compact_query(q,revised,version='v2',optimize=True)
                assert set(assignment.values())==set(names)|({'control'} if cross else set())
                assert len(program.operators)<=64
        for n in names:assert revised[n]['edges']==schema[n]['edges']


def test_profile_revision_reuses_stores_without_changing_source_or_estimator(tmp_path):
    import json
    import pytest
    from test_ch6_fact_materialization import CoreMaterializationTest
    from test_compact_roles_v2 import PARENT,PIN
    from xgap.experiments.ch6_core_profile import publish
    from xgap.experiments.ch6_fact_index import write,pin
    from xgap.experiments.ch6_profile_revision import revise
    from xgap.experiments.ch6_cost_pool import load
    from xgap.experiments.one_shot_profile import FrozenOneShotProfile
    fixture=CoreMaterializationTest();index=fixture.index(tmp_path)
    fixture.generate(tmp_path/'facts',index)
    parent=publish(tmp_path/'facts/receipt.json',PARENT,PIN,tmp_path/'profile')
    build=tmp_path/'build.json';write(build,dict(profile=parent,engine='fixture-unopened'))
    receipt=tmp_path/'prepared.json';stores={'graph':dict(path='fixture-not-opened',bytes=1)}
    write(receipt,dict(success=True,profile=parent,input_seal=pin(build),stores=stores))
    before=receipt.read_bytes();old=load(parent)
    new_prepared=revise(pin(receipt),tmp_path/'child');prepared=load(new_prepared);new=load(prepared['profile'])
    for key in ('dataset','sources','backends','estimator','catalog'):assert new[key]==old[key]
    assert prepared['stores']==stores and receipt.read_bytes()==before
    assert load(prepared['input_seal'])['profile']==prepared['profile']
    for _,provider in FrozenOneShotProfile.load(prepared['profile']['path'],expected_sha256=prepared['profile']['sha256']).materialize()[-1].values():
        assert 'lexical_string' in provider.system_prompt and 'Integer epoch-millisecond' in provider.system_prompt
    with pytest.raises(ValueError,match='already applied'):revise(new_prepared,tmp_path/'again')
