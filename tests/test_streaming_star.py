"""Shape-driven star binding composes with a streaming tail, without observations."""
from dataclasses import replace
from test_native_spj import fixture
from xgap.agent.intent_certificate import IntentCandidate,IntentFamily
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.practical_planning import _baseline
from xgap.compilers.features import default_profile
from xgap.runtime.semantic_planning import LogicalSource
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.runtime.streaming_topk import islands
from xgap.semantic.compact_lowering import lower_compact_query


def star_plans(*,descending=False):
    _,s,b=fixture();b=replace(b,profile=default_profile('neo4j'))
    ref=lambda v:dict(var=v,property='name')
    q=dict(nodes=[dict(var=v,type=k,entity=None) for v,k in [('a','Actor'),('b','Item'),('c','Item')]],
        edges=[dict(var=v,type='LINK',source='a',target=t) for v,t in [('e','b'),('f','c')]],path=None,
        where=[dict(left=ref('a'),op='eq',right={'value':'anchor'},value_type='scalar'),
               dict(left=ref('b'),op='lt',right=ref('c'),value_type='lexical_string')],
        select=dict(result=ref('b'),other=ref('c')),contribution_by=None,
        order_by=[dict(field=f,direction='desc' if descending else 'asc') for f in ('result','other')],limit=3)
    program,slots=lower_compact_query(q,s,version='v2',optimize=True)
    policy=replace(OneShotPolicy.for_mode('performance'),max_parallelism=1)
    backends={'neo4j':b};sources={'graph':LogicalSource('graph','tiny',('neo4j',))}
    family=IntentFamily('star',(IntentCandidate.create('q',q),),(),'tiny',language_version='v2',coverage_basis='toy')
    moves=PhysicalMoves(family,s,backends,policy,sources)
    seed=_baseline(program,slots,sources,backends,policy,optimize_reads=False)
    current=next(p for p in moves.neighbors(0,seed) if p.metadata['unified_rewrite']['proof'].get('kind')=='mandatory_anchor_fanout')
    proofs=[]
    for _ in range(8):
        proposals=[p for p in moves.neighbors(0,current) if p.metadata['unified_rewrite']['rule']=='entity_bind']
        if not proposals:break
        # Fixed deterministic proposal order, no execution or observed selection.
        current=proposals[0];proofs.append(current.metadata['unified_rewrite']['proof'])
    return seed,current,proofs


def test_star_uses_early_restricted_key_domains_and_leaves_product_exclusive():
    original,refined,proofs=star_plans()
    assert any(p.get('early_driver') for p in proofs)
    pipelines=islands(refined);assert len(pipelines)==1
    nodes={n.node_id:n for n in refined.nodes}
    assert sum(nodes[n].kind.value=='coordinator_join' for n in pipelines[0]['nodes'])>=3
    for p in proofs:
        if 'early_driver' in p:
            d=p['early_driver'];n=nodes[p['target']+'/native']
            assert n.inputs==(refined.metadata['operator_outputs'][d['producer']],)
            assert n.parameters['bind_field']==d['producer_field']
    assert {n.node_id for n in original.nodes}<={n.node_id for n in refined.nodes}
