"""Bounded source fusion, independent of any dataset/case identifier."""
from copy import deepcopy
from dataclasses import replace

import pytest

from xgap.compilers.native_spj import compile_native_spj, PROFILE
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.semantic.compact_lowering import lower_compact_query


def fixture():
    schema = dict(identity_property='key', scalar_semantics={'name':'string','score':'number','stamp':'integer'},
        graph=dict(nodes={k:dict(properties=['key','name']) for k in ('Actor','Item')},
            edges=[dict(label='LINK',source='Actor',target='Item',properties=['key','score','stamp'])]))
    def ref(v, p='name'): return dict(var=v,property=p)
    query = dict(nodes=[dict(var=v,type=k,entity=None) for v,k in [('a','Actor'),('b','Item'),('c','Actor'),('d','Item')]],
        edges=[dict(var=v,type='LINK',source=a,target=b) for v,a,b in [('e','a','b'),('f','c','b'),('g','c','d')]],
        path=None,where=[dict(left=ref('a'),op='eq',right={'value':'anchor'},value_type='scalar'),
            dict(left=ref('c'),op='ne',right=ref('a'),value_type='scalar'),
            dict(left=ref('b'),op='ne',right=ref('d'),value_type='scalar'),
            dict(left=ref('e','score'),op='ge',right={'value':0},value_type='scalar')],
        select=dict(result=ref('b'),other=ref('c'),destination=ref('d')),contribution_by=None,
        order_by=[dict(field=f,direction='asc') for f in ('result','other','destination')],limit=2)
    return query,schema,SemanticBackend('neo4j','https://tiny/',identity_property='key')


def compile_query(query=None,schema=None,backend=None,condition_wrapper=None,*,prefix_topk=False,nulls=None):
    q,s,b=fixture();query=q if query is None else query;schema=s if schema is None else schema;backend=backend or b
    p,sources=lower_compact_query(query,schema,version='v2',optimize=True)
    if nulls:
        p=replace(p,operators=tuple(replace(o,parameters={**o.parameters,
            'order_by':[{**order,'nulls':nulls} for order in o.parameters['order_by']]})
            if o.kind.value=='order_limit' else o for o in p.operators))
    if condition_wrapper:
        def wrap(c):
            if c['op']=='eq' and 'value' in c:
                return (dict(op='not',arg=c) if condition_wrapper=='not' else
                    dict(op='or',args=[c,dict(op='is_null',field=c['field'])]))
            return {**c,'args':[wrap(x) for x in c['args']]} if 'args' in c else c
        p=replace(p,operators=tuple(replace(o,parameters={'condition':wrap(o.parameters['condition'])})
            if o.kind.value=='filter' else o for o in p.operators))
    return compile_native_spj(p,backend,schema,{op:backend.backend_id for op in sources},prefix_topk=prefix_topk)


def test_prefix_limits_require_complete_witnesses_and_regenerate_values():
    artifact,_=compile_query(prefix_topk=True)
    proof=artifact.parameters['source_pushdown'];prefix=proof['prefix_topk']
    assert prefix['profile']=='complete-prefix-topk-v1'
    assert prefix['width']==3 and prefix['maximum_prefix_subqueries']==5
    assert prefix['value_prefix_regeneration'] and prefix['completion_checks_before_limits']
    assert not prefix['source_work_bounded_by_limit']
    assert artifact.text.count('RETURN DISTINCT')==3
    assert artifact.text.count('LIMIT')==7
    assert artifact.text.count('WHERE EXISTS {')==2
    assert 'spj_rank_0 IS NULL' in artifact.text
    assert 'coalesce(' in artifact.text and proof['complete_result_distinct']
    assert not proof['native_identity_coalescing']


def test_prefix_edge_projection_retains_connected_contraction():
    _,q,s,b=list(native_cases())[-1]
    artifact,_=compile_query(q,s,b,prefix_topk=True)
    assert 'prefix_topk' not in artifact.parameters['source_pushdown']
    assert artifact.text.count('LIMIT')==1


def test_prefix_width_bound_retains_original_supported_output():
    q,s,b=fixture()
    q['select']={f'column{i}':dict(var='b',property='name') for i in range(9)}
    q['order_by']=[dict(field=f,direction='asc') for f in q['select']]
    artifact,_=compile_query(q,s,b,prefix_topk=True)
    assert 'prefix_topk' not in artifact.parameters['source_pushdown']
    assert len(artifact.parameters['output_columns'])==9


def test_one_final_limit_parameters_and_no_dataset_dispatch():
    artifact,bare=compile_query()
    assert artifact.parameters['compiler']==PROFILE
    assert artifact.text.count('LIMIT')==1 and artifact.text.endswith('LIMIT 2')
    assert 'anchor' not in artifact.text and 'anchor' in artifact.parameters.values()
    assert artifact.text.count('MATCH ')==7
    assert artifact.parameters['source_pushdown']['intermediate_limits']==0
    assert artifact.parameters['source_pushdown']['joins_use_logical_identity']
    assert len(bare.nodes)>1


@pytest.mark.parametrize('wrapper',[None,'not','or-null'])
def test_native_access_equalities_are_necessary_conjuncts(wrapper):
    artifact,_=compile_query(condition_wrapper=wrapper)
    proof=artifact.parameters['source_pushdown']
    equalities=proof['access_equalities']
    assert proof['nullable_predicates_retained'] and not proof['native_identity_coalescing']
    assert 'coalesce(' in artifact.text
    assert len([s for s in equalities if '.key = ' in s])==6
    scalar=[s for s in equalities if '.name = ' in s]
    assert bool(scalar)==(wrapper is None)
    assert all(s in artifact.text for s in equalities)
    assert proof['join_order_profile']=='bound-connected-matches-v1'
    assert artifact.text.count('CALL {')==proof['correlated_match_calls']==6
    assert len(set(proof['pattern_order']))==7


def test_connected_access_declines_an_unbound_branch():
    from xgap.compilers.native_spj import _connected_matches
    with pytest.raises(ValueError,match='connected equality'):
        _connected_matches(['MATCH (a:A)','MATCH (b:B)'],[('a',),('b',)],{'a.key = $p':frozenset(['a'])})


@pytest.mark.parametrize('change,reason',[
    ('partial_order','every output'),('aggregate','aggregation'),('float_output','floating'),
    ('no_types','frozen type'),('entity','grounded'),('unbounded','bounded output')])
def test_unsupported_shapes_keep_the_original_path(change,reason):
    q,s,b=fixture()
    if change=='partial_order':q['order_by']=q['order_by'][:1]
    elif change=='aggregate':q['select']['destination']=dict(aggregate='count',field=None,distinct=False)
    elif change=='float_output':q['select']['destination']=dict(var='e',property='score')
    elif change=='no_types':s['scalar_semantics']={}
    elif change=='entity':q['nodes'][0]['entity']='somebody'
    elif change=='unbounded':q['limit']=None
    with pytest.raises(ValueError,match=reason):compile_query(q,s,b)


def test_cross_source_and_non_native_are_not_fused():
    q,s,b=fixture();p,sources=lower_compact_query(q,s,version='v2',optimize=True)
    placement={op:'neo4j' for op in sources};placement[next(iter(placement))]='other'
    with pytest.raises(ValueError,match='same placed backend'):compile_native_spj(p,b,s,placement)
    with pytest.raises(ValueError,match='Neo4j'):compile_native_spj(p,replace(b,backend_id='fuseki'),s,placement)


def native_cases():
    """Small real-backend differential gate inputs, never formal workload rows."""
    q,s,b=fixture();yield 'zigzag',q,s,b
    q=deepcopy(q);q['where'][0]['right']['value']='missing';yield 'empty',q,s,b
    q=fixture()[0];q['order_by'][0]['direction']='desc';q['limit']=1000
    q['where']=[q['where'][0],q['where'][1],q['where'][3]]
    yield 'descending-null-and-unicode',q,s,b
    q=fixture()[0];q['where']=q['where'][:1];q['select']={'edge':dict(var='e',property=None)}
    q['order_by']=[dict(field='edge',direction='asc')];q['limit']=20
    yield 'relationship-reuse-and-parallel-edges',q,s,b


def test_physical_move_and_relative_model_charge_source_work_separately(tmp_path):
    import json
    from types import SimpleNamespace
    from xgap.runtime.unified_physical import PhysicalMoves
    from xgap.planning.relative_source_work import FrozenSourceWorkRanker
    from xgap.planning.runtime_estimator import FrozenSourceStatistics,SourceStatistics
    from xgap.runtime.contracts import FederatedExecutionPlan
    q,s,b=fixture();artifact,seed=compile_query(q,s,b,prefix_topk=True)
    family=SimpleNamespace(candidates=[SimpleNamespace(query_json=json.dumps(q))],language_version='v2')
    seed=replace(seed,metadata={**seed.metadata,'source_identities':{'neo4j':{'source_id':'graph','snapshot_version':'tiny'}}})
    moves=PhysicalMoves(family,s,{'neo4j':b},None)
    fused=next(moves.neighbors(0,seed))
    assert fused.metadata['unified_rewrite']['rule']=='native_spj_pushdown'
    assert len(fused.nodes)==1 and fused.nodes[0].parameters['artifact']==artifact.to_dict()
    assert list(moves.neighbors(0,fused))==[]
    stats=FrozenSourceStatistics('tiny','fixture',(SourceStatistics('neo4j','graph','tiny',11000,128.,'fixture'),))
    ranker=FrozenSourceWorkRanker(stats,(('neo4j',1000,10000),),('name',),'fixture',
        endpoint_degrees=(('neo4j','LINK','source',10000,100,1000000,200),('neo4j','LINK','target',10000,50,2000000,400)))
    before=ranker.predict(fused)
    raw=deepcopy(fused.to_dict());a=raw['nodes'][0]['parameters']['artifact'];a['text']='Never execute or parse'
    after=ranker.predict(FederatedExecutionPlan.from_dict(raw))
    assert before.provenance['source_scan_record_units']==after.provenance['source_scan_record_units']>0
    assert before.provenance['source_join_record_proxy']==after.provenance['source_join_record_proxy']>0
    assert before.provenance['returned_record_proxy']==after.provenance['returned_record_proxy']==2
    assert before.provenance['nodes'][0]['source_work']['prefix_passes_charged']==5
    assert before.provenance['current_query_observation_calls']==0
    # A final LIMIT is not an unearned source-work bound. The old contraction
    # still charges unchanged full scans/joins when only its final K changes.
    connected,_=compile_query(q,s,b)
    from xgap.planning.native_spj_work import source_work
    kwargs=dict(backend='neo4j',populations=(1000,10000),endpoint_degrees={},unique_properties=('name',))
    original_work=source_work(connected.parameters,**kwargs)
    smaller=deepcopy(connected.parameters);smaller['source_pushdown']['final_output_limit']=1
    assert source_work(smaller,**kwargs)['join_records']==original_work['join_records']
    with pytest.raises(ValueError,match='prefix'):
        inconsistent=deepcopy(artifact.parameters);inconsistent['source_pushdown']['final_output_limit']=1
        source_work(inconsistent,**kwargs)
    from xgap.agent.intent_certificate import IntentCandidate,IntentFamily
    from xgap.agent.scope_authority import ScopedQueryUser,private_query_intent
    from xgap.agent.unified_family import run_unified_family
    from xgap.agent.one_shot_policy import OneShotPolicy
    from xgap.planning.joint_cost import JointCostProfile
    import hashlib
    question='Tiny complete query; no NL claim'
    family=IntentFamily('tiny',(IntentCandidate.create('tiny',q),),(),'tiny-source',
        coverage_basis='authored complete-query test',language_version='v2')
    oracle=tmp_path/'user.json';oracle.write_text(json.dumps(private_query_intent(question,q,language_version='v2')))
    user=ScopedQueryUser(family,oracle,hashlib.sha256(oracle.read_bytes()).hexdigest())
    chosen=[]
    def execute(plan):chosen.append(plan);return dict(success=True)
    report=run_unified_family(question,family,user,prepare_seed=lambda *_:seed,execute=execute,
        costs=JointCostProfile(),estimator=ranker,
        moves=PhysicalMoves(family,s,{'neo4j':b},OneShotPolicy.for_mode('performance')))
    assert report['success'] and report['final_plan_executions']==len(chosen)==1,report
    assert chosen[0].metadata.get('native_spj_pushdown'),report
    assert report['external_calls_during_search']==report['clarification_calls']==0
