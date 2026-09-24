"""Exact external membership, without executing candidate plans to select one."""
from copy import deepcopy
from dataclasses import replace

import pytest

from test_native_spj import fixture as native_fixture
from xgap.agent.intent_certificate import IntentCandidate, IntentFamily
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_planning import _baseline
from xgap.compilers.features import default_profile
from xgap.runtime.native_semijoin import _reduction, PARAMETER
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.semantic.compact_lowering import lower_compact_query


def fixture(query=None):
    q,s,b=native_fixture()
    s['control']=dict(nodes={'Item':dict(properties=['key','allowed'])},edges=[])
    s['scalar_semantics']['allowed']='boolean'
    q['where'].append(dict(left=dict(var='b',property='allowed'),op='eq',right={'value':True},value_type='scalar'))
    if query is not None:q=query
    mapping=dict(mapping_id='tiny',version='1',backends={'fuseki':dict(namespace='https://tiny/')},
        term_mappings={'fuseki':{k:dict(kind=kind,representation='https://tiny/'+k)
            for k,kind in [('Item','class'),('allowed','property'),('key','property')]}})
    backends=dict(neo4j=replace(b,profile=default_profile('neo4j')),
        fuseki=SemanticBackend('fuseki','https://tiny/',identity_property='key',backend_mapping=mapping,
            rdf_node_classes=('https://tiny/Item',)))
    sources={name:LogicalSource(name,'tiny',(backend,)) for name,backend in [('graph','neo4j'),('control','fuseki')]}
    program,slots=lower_compact_query(q,s,version='v2',optimize=True)
    policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)
    family=IntentFamily('tiny-semijoin',(IntentCandidate.create('q',q),),(),'tiny',language_version='v2',
        coverage_basis='authored development fixture')
    seed=_baseline(program,slots,sources,backends,policy,optimize_reads=False)
    moves=PhysicalMoves(family,s,backends,policy,sources)
    side=next(k for k,v in seed.metadata['source_bindings'].items() if v=='fuseki')
    bound=next(p for p in moves.neighbors(0,seed)
        if p.metadata['unified_rewrite']['rule']=='entity_bind'
        and p.metadata['unified_rewrite']['proof'].get('target')==side)
    return q,s,backends,program,seed,bound,moves


def fused_plan(query=None):
    values=fixture(query)
    fused=next(p for p in values[-1].neighbors(0,values[-2]) if p.metadata.get('native_external_semijoin'))
    return values,fused


def test_membership_precedes_witness_and_topk_and_keeps_paid_driver():
    (q,s,backends,program,seed,bound,moves),fused=fused_plan()
    proof=fused.metadata['native_external_semijoin']
    final=fused.nodes[-1];artifact=final.parameters['artifact']
    assert final.inputs==(bound.metadata['operator_outputs'][proof['external_output']],)
    assert any(n.parameters.get('backend_id')=='fuseki' for n in fused.nodes)
    assert PARAMETER not in artifact['parameters']  # real keys supplied only at execution
    assert artifact['text'].index('IN $'+PARAMETER)<artifact['text'].index('LIMIT')
    assert artifact['parameters']['source_pushdown']['identity_membership']['before_complete_witness_and_topk']
    assert len(fused.nodes)<len(bound.nodes)
    assert not list(moves.neighbors(0,fused))
    assert not any(p.metadata.get('native_external_semijoin') for p in moves.neighbors(0,seed))


@pytest.mark.parametrize('change',['side-output','cross-field','two-dimensions','different-namespace','partial-order'])
def test_unsafe_reductions_are_declined(change):
    q,s,backends,program,seed,bound,moves=fixture()
    if change=='different-namespace':
        backends['fuseki']=replace(backends['fuseki'],resource_namespace='https://different/')
    else:
        if change=='side-output':q['select']['flag']=dict(var='b',property='allowed')
        if change=='cross-field':q['where'][-1]['right']=dict(var='e',property='score')
        if change=='two-dimensions':q['where'].append(dict(left=dict(var='d',property='allowed'),op='eq',right={'value':True},value_type='scalar'))
        if change=='partial-order':q['order_by']=q['order_by'][:1]
        program,slots=lower_compact_query(q,s,version='v2',optimize=True)
        placement={k:'neo4j' if v=='graph' else 'fuseki' for k,v in slots.items()}
        seed=replace(seed,metadata={**seed.metadata,'source_bindings':placement})
    with pytest.raises(ValueError):_reduction(program,seed.metadata['source_bindings'],backends,s)


def test_ranker_charges_native_work_and_driver_and_rejects_unbound_membership():
    from xgap.planning.relative_source_work import FrozenSourceWorkRanker
    from xgap.planning.runtime_estimator import FrozenSourceStatistics,SourceStatistics
    from xgap.runtime.contracts import FederatedExecutionPlan
    _,fused=fused_plan()
    stats=FrozenSourceStatistics('tiny','fixture',tuple(SourceStatistics(b,s,'tiny',n,128.,'fixture')
        for b,s,n in [('neo4j','graph',11000),('fuseki','control',1000)]))
    model=FrozenSourceWorkRanker(stats,(('neo4j',1000,10000),('fuseki',1000,0)),('name',),'fixture')
    prediction=model.predict(fused)
    assert prediction.provenance['source_scan_record_units']>0
    assert prediction.provenance['source_join_record_proxy']>0
    assert prediction.provenance['current_query_observation_calls']==0
    raw=deepcopy(fused.to_dict());raw['nodes'][-1]['kind']='remote_query';raw['nodes'][-1]['inputs']=[]
    with pytest.raises(ValueError,match='bound key input'):model.predict(FederatedExecutionPlan.from_dict(raw))
    raw=deepcopy(fused.to_dict());raw['nodes'][-1]['parameters']['parameter']='wrong'
    with pytest.raises(ValueError,match='checked'):model.predict(FederatedExecutionPlan.from_dict(raw))


def test_final_membership_deduplicates_keys_but_never_truncates_overflow():
    from xgap.runtime.scheduler import FederatedScheduler
    _,plan=fused_plan();node=plan.nodes[-1];field=node.parameters['bind_field']
    node=replace(node,parameters={**node.parameters,'max_bindings':1})
    artifact=node.parameters['artifact']
    bound,count=FederatedScheduler._bind_artifact(node,artifact,[{field:'https://tiny/a'}]*3)
    assert count==1 and bound['parameters'][PARAMETER]==['https://tiny/a']
    with pytest.raises(ValueError):
        FederatedScheduler._bind_artifact(node,artifact,[{field:'https://tiny/a'},{field:'https://tiny/b'}])
