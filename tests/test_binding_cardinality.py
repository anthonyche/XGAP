"""Deduplicated bind keys, frozen versioning and conservative unknown lineage."""
from dataclasses import replace

import pytest

from xgap.planning.relative_source_work import FrozenSourceWorkRanker,KEY_SCHEMA
from xgap.planning.runtime_estimator import FrozenSourceStatistics,SourceStatistics
from xgap.planning.runtime_work_estimator import frozen_estimator_from_dict
from xgap.runtime.contracts import FederatedExecutionPlan,RuntimeNode as N,RuntimeNodeKind as R


def fixture():
    stats=FrozenSourceStatistics('tiny','source-counts',(SourceStatistics('neo4j','graph','tiny',11000,128.,'fixture'),))
    model=FrozenSourceWorkRanker(stats,(('neo4j',1000,10000),),('id',),'fixture-only',
        endpoint_degrees=(('neo4j','LINK','source',10000,1000,100000,10),('neo4j','LINK','target',10000,1000,100000,10)))
    def remote(name,edge=False,parent=None,field=None):
        a=dict(compiler='semantic_edge_match_v1' if edge else 'semantic_node_match_v1',scalar_properties={} if edge else {'id':'id'})
        if edge:a.update(edge_statistics_descriptor=dict(label='LINK',direction='OUT'),bound_identity_column='source')
        if name=='anchor':a['necessary_row_filters']=dict(conditions=[dict(op='eq',field='id',value='public')])
        p=dict(backend_id='neo4j',artifact=dict(parameters=a))
        if parent:p.update(bind_field=field,max_bindings=20)
        return N(name,R.REMOTE_BIND_QUERY if parent else R.REMOTE_QUERY,(parent,) if parent else (),p)
    nodes=[remote('anchor'),remote('left',True,'anchor','entity'),remote('right',True,'anchor','entity'),
        N('l',R.COORDINATOR_ROW_PROJECT,('left',),dict(projections={f:dict(kind='field',field=c) for f,c in [('a','source'),('b','target')]})),
        N('r',R.COORDINATOR_ROW_PROJECT,('right',),dict(projections={f:dict(kind='field',field=c) for f,c in [('a','source'),('c','target')]})),
        N('product',R.COORDINATOR_JOIN,('l','r'),dict(left_on='a',right_on='a')),
        remote('dimension',parent='product',field='c')]
    return model,FederatedExecutionPlan('toy',tuple(nodes),('dimension',),metadata=dict(source_identities={'neo4j':dict(source_id='graph',snapshot_version='tiny')}))


def test_join_multiplicity_is_not_binding_key_count():
    old,plan=fixture();new=replace(old,distinct_binding_keys=True)
    previous=old.predict(plan);prediction=new.predict(plan)
    detail=prediction.provenance['nodes'][-1]
    assert detail['binding_input_rows']==100
    assert detail['binding_distinct_key_proxy']==10
    assert detail['estimated_rows']==10
    assert prediction.provenance['bind_overflow_risk_work']==0
    assert previous.provenance['bind_overflow_risk_work']>0
    assert prediction.provenance['fit_calls']==prediction.provenance['current_query_observation_calls']==0
    # Concrete independent example: 10 x 10 matching pairs contain ten c keys.
    actual=[dict(a='anchor',b=b,c=c) for b in range(10) for c in range(10)]
    assert len(actual)==detail['binding_input_rows']
    assert len({r['c'] for r in actual})==detail['binding_distinct_key_proxy']


def test_v3_opt_in_keeps_old_model_serialization_and_predictions():
    old,plan=fixture();raw=old.to_dict();before=old.predict(plan).relative_cost
    new=replace(old,distinct_binding_keys=True)
    assert new.to_dict()['schema_version']==KEY_SCHEMA
    assert new.model_sha256!=old.model_sha256
    assert frozen_estimator_from_dict(new.to_dict()).to_dict()==new.to_dict()
    assert old.to_dict()==raw and frozen_estimator_from_dict(raw).predict(plan).relative_cost==before
    assert 'distinct_binding_keys' not in raw
    with pytest.raises(ValueError):replace(old,distinct_binding_keys=1)


def test_unknown_or_colliding_aliases_fall_back_to_rows():
    from xgap.planning.binding_cardinality import propagate,bind_keys
    node=N('join',R.COORDINATOR_JOIN,('left','right'),dict(left_on='k',right_on='k',right_prefix='r_'))
    rows={'left':100.,'right':200.,'join':20000.};cols={'left':{'k':1.,'x':2.},'right':{'k':1.,'x':50.}}
    cols['join']=propagate(node,20000,rows,cols,populations={},degrees={},unique_properties=())
    assert cols['join']['x']==2 and 'r_x' not in cols['join']
    probe=N('probe',R.REMOTE_BIND_QUERY,('join',),dict(bind_field='r_x'))
    assert bind_keys(probe,rows,cols)==20000


def test_renaming_and_equality_cap_keys_but_or_does_not():
    from xgap.planning.binding_cardinality import propagate
    common=dict(populations={},degrees={},unique_properties=())
    rows={'input':100};cols={'input':{'key':10}}
    p=N('renamed',R.COORDINATOR_ROW_PROJECT,('input',),dict(projections={'other':dict(kind='field',field='key')}))
    cols['renamed']=propagate(p,100,rows,cols,**common);rows['renamed']=100
    c=dict(op='eq',field='other',value='constant')
    f=N('f',R.COORDINATOR_FILTER,('renamed',),dict(condition=c))
    assert propagate(f,100,rows,cols,**common)=={'other':1}
    f=replace(f,parameters=dict(condition=dict(op='or',args=[c,dict(op='is_null',field='other')])))
    assert propagate(f,100,rows,cols,**common)=={'other':10}


def test_incoming_endpoint_ndv_uses_stored_direction_and_empty_stays_empty():
    from xgap.planning.binding_cardinality import propagate
    node=N('read',R.REMOTE_QUERY,parameters=dict(backend_id='b',artifact=dict(parameters=dict(
        compiler='semantic_edge_match_v1',edge_statistics_descriptor=dict(label='R',direction='IN')))))
    kwargs=dict(populations={'b':(1000,1000)},degrees={('b','R','source'):(1000,30,1,1),('b','R','target'):(1000,10,1,1)},unique_properties=())
    values=propagate(node,1000,{}, {},**kwargs)
    assert values['source']==10 and values['target']==30
    assert all(v==0 for v in propagate(node,0,{}, {},**kwargs).values())


def test_profile_revision_preserves_stores_statistics_and_previous_model(tmp_path):
    import json
    from test_ch6_fact_materialization import CoreMaterializationTest
    from test_compact_roles_v2 import PARENT,PIN
    from xgap.experiments.ch6_core_profile import publish
    from xgap.experiments.ch6_fact_index import write,pin
    from xgap.experiments.ch6_cost_pool import load
    from prepare_ch6_relative_work import prepare
    from prepare_ch6_binding_work import revise
    fixture=CoreMaterializationTest();index=fixture.index(tmp_path)
    fixture.generate(tmp_path/'facts',index)
    pp=publish(tmp_path/'facts/receipt.json',PARENT,PIN,tmp_path/'profile')
    seal=tmp_path/'seal.json';write(seal,dict(profile=pp))
    original=tmp_path/'prepared.json';stores={'graph':dict(path='unopened',bytes=1)}
    write(original,dict(success=True,profile=pp,input_seal=pin(seal),stores=stores))
    previous=prepare(pin(original),tmp_path/'relative');old=load(previous)
    before=load(old['profile']);original_model=load(before['estimator'])
    current=revise(previous,tmp_path/'ndv');new=load(current);doc=load(new['profile'])
    for field in ('dataset','sources','backends','catalog','source_schema'):assert doc[field]==before[field]
    assert new['stores']==stores and load(new['input_seal'])['profile']==new['profile']
    revised=load(doc['estimator'])
    assert revised['statistics']==original_model['statistics'] and revised['record_quantum']==original_model['record_quantum']
    assert revised['distinct_binding_keys'] is True and revised['schema_version']==KEY_SCHEMA
    assert load(before['estimator'])==original_model and load(previous)==old
    with pytest.raises(ValueError,match='unrevised'):revise(current,tmp_path/'again')
