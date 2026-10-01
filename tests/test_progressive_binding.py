"""Progressive semijoin composition risks on independent tiny RDF facts."""
from dataclasses import replace
import json
import pytest

from test_anchor_reduction import tiny, EXPECTED
from test_anchor_source_bind import fanout
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.one_shot_planning import prepare_one_shot_domain
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.program import SemanticGraphProgram


def domain(p,s,b,**options):
    return prepare_physical_strategies(p,source_bindings=s,backends=b,max_parallelism=1,
                                      progressive_bindings=True,**options)


def progressive(space):
    return next(c for c in space.candidates if c.strategy_id == 'progressive_entity_bind')


def test_progressive_frontiers_restrict_later_hops_and_preserve_independent_path_gold():
    p,s,b,_,_,scheduler,calls = tiny(); before = p.to_dict()
    space = domain(p,s,b); old = fanout(space); new = progressive(space)
    assert not calls and p.to_dict() == before
    assert len(space.candidates) <= space.candidate_count_upper_bound == 3 + 2 * space.join_count
    a,z = scheduler.execute(old.plan), scheduler.execute(new.plan)
    assert a.success and z.success and a.final_rows == z.final_rows == EXPECTED
    assert new.features['bind_query_count'] == 6 and old.features['bind_query_count'] == 3
    first = set(old.plan.metadata['anchor_reduction']['target_matches'])
    later = [o.operator_id+'/native' for o in p.operators if o.kind.value == 'match'
             and 'edge' in o.parameters and o.operator_id not in first]
    rows_a = {n.node_id:n.row_count for n in a.node_results}
    rows_z = {n.node_id:n.row_count for n in z.node_results}
    assert len(later) == 3 and all(rows_z[n] < rows_a[n] for n in later)
    assert a.total_remote_calls == z.total_remote_calls == len(s)
    assert z.total_bytes_moved < a.total_bytes_moved
    print(json.dumps({'gate':'progressive-vs-first-hop-component','gold_rows':len(EXPECTED),
        'source_calls_each':len(s),'later_hop_rows_before':sum(rows_a[n] for n in later),
        'later_hop_rows_after':sum(rows_z[n] for n in later),
        'first_hop_exchange_bytes':a.total_bytes_moved,'progressive_exchange_bytes':z.total_bytes_moved,
        'actual_http_or_speed_claim':False}))


@pytest.mark.parametrize('boundary',['empty','overflow'])
def test_empty_frontier_skips_all_relation_requests_and_overflow_fails_without_retry(boundary):
    p,s,b,_,clients,scheduler,calls = tiny()
    attempted = []
    for client in clients.values():
        original = client.execute
        def capture(artifact, original=original):
            attempted.append(artifact.artifact_id)
            return original(artifact)
        client.execute = capture
    if boundary == 'empty':
        raw = p.to_dict()
        next(o for o in raw['operators'] if o['kind']=='filter' and o['parameters']['condition'].get('value')==20)['parameters']['condition']['value'] = 999
        p = SemanticGraphProgram.from_dict(raw)
    candidate = progressive(domain(p,s,b,max_bindings=1 if boundary=='overflow' else 100))
    result = scheduler.execute(candidate.plan)
    if boundary == 'empty':
        assert result.success and result.final_rows == ()
        assert len(calls) == len(s)-6
        assert not any('VALUES ?source' in text for _,text in calls)
    else:
        assert not result.success and any('bindings but limit' in (n.error or '') for n in result.node_results)
        assert len(calls) <= len(s) and len(attempted) == len(set(attempted))


def test_shared_answer_target_is_never_restricted_and_composed_dag_is_acyclic():
    p,s,b,_,_,_,calls = tiny()
    target = next(r['target_match'] for r in progressive(domain(p,s,b)).plan.metadata['strategy_details']['rewrites'])
    raw = p.to_dict(); raw['roots'].append(target)
    shared = SemanticGraphProgram.from_dict(raw)
    candidate = progressive(domain(shared,s,b))
    assert next(n for n in candidate.plan.nodes if n.node_id == target+'/native').kind is R.REMOTE_QUERY
    by_id = {n.node_id:n for n in candidate.plan.nodes}
    def visit(n, stack):
        assert n not in stack
        for child in by_id[n].inputs: visit(child,stack|{n})
    for root in candidate.plan.roots: visit(root,set())
    assert not calls


def test_legacy_domain_unchanged_and_progressive_candidate_is_visible_to_new_domain():
    p,s,b,_,_,_,calls = tiny()
    old = prepare_physical_strategies(p,source_bindings=s,backends=b,max_parallelism=1)
    new = domain(p,s,b)
    assert not any(c.strategy_id=='progressive_entity_bind' for c in old.candidates)
    assert [c.to_dict() for c in old.candidates] == [c.to_dict() for c in new.candidates[:-1]]
    assert progressive(new).to_dict() == progressive(domain(p,s,b)).to_dict()
    sources = {'graph':LogicalSource('graph','tiny-v1',('rdf_a',)),
               'control':LogicalSource('control','tiny-v1',('rdf_b',))}
    slots = {op:'graph' if backend=='rdf_a' else 'control' for op,backend in s.items()}
    policy = replace(OneShotPolicy(),max_parallelism=1)
    candidates,record = prepare_one_shot_domain(p,operator_sources=slots,sources=sources,backends=b,
        policy=policy,progressive_bindings=True)
    assert sum(c.strategy_id.endswith('/progressive_entity_bind') for c in candidates) == 1
    assert record['construction_bound'] == new.candidate_count_upper_bound
    with pytest.raises(ValueError,match='candidate-work budget'):
        prepare_one_shot_domain(p,operator_sources=slots,sources=sources,backends=b,
            policy=replace(policy,max_physical_candidates=record['construction_bound']-1),progressive_bindings=True)
    assert not calls


def test_composition_preserves_parallel_edge_bag_count_without_anchor_fanout():
    from xgap.experiments.tiny_work_training import op
    from test_anchor_reduction import NS
    _,_,backends,_,_,scheduler,calls = tiny()
    first = op('first','match',parameters={'edge':{'label':'KNOWS'},'entity_field':'edge1',
        'source_field':'start','target_field':'middle','properties':{}})
    anchor = op('start_a','filter',('first',),parameters={'condition':{'op':'eq','field':'start','value':NS+'a'}})
    second = op('second','match',parameters={'edge':{'label':'KNOWS'},'entity_field':'edge2',
        'source_field':'middle','target_field':'end','properties':{}})
    joined = op('join','join',('start_a','second'),parameters={'left_on':'middle','right_on':'middle'})
    count = op('count','aggregate',('join',),output='grouped_bindings',parameters={'group_by':[],
        'aggregations':{'n':{'op':'count','field':'edge2','distinct':False}}})
    program = SemanticGraphProgram.from_dict({'program_id':'independent-two-hop-bag',
        'operators':[first,anchor,second,joined,count],'roots':['count']})
    candidate = progressive(domain(program,{'first':'rdf_a','second':'rdf_a'},backends))
    assert candidate.plan.metadata['strategy_details']['seed_bind_count'] == 0
    result = scheduler.execute(candidate.plan)
    # a->b twice followed by b->c:2; a->c->d:1; a->a then four outgoing a edges:4.
    assert result.success and result.final_rows == ({'n':7},) and len(calls) == 2
