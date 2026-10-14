"""Pure compilation and scoring reuse; no model or backend observations."""
from dataclasses import replace
import json

from test_unified_actions import fixture, target
from xgap.agent.unified_contract import UnifiedTerminalContract
from xgap.agent.unified_family import FamilyDomain, FamilyState, UnifiedSettings
from xgap.agent.unified_lookahead import Resources
from xgap.planning.joint_cost import JointCostProfile
from xgap.runtime.unified_physical import PhysicalMoves
from xgap.semantic.lowering_cache import RequestLoweringCache


def test_seed_and_physical_search_share_lowering_without_sharing_mutable_results():
    from xgap.agent.intent_execution import family_runtime
    data, options, calls, family, _, _ = fixture()
    cache = RequestLoweringCache(options['source_schema'], family.language_version)
    prepare, *_ = family_runtime(family, **options, seed_only=True, stepwise=True, lowering_cache=cache)
    seed = prepare(family.candidates[0], None)
    moves = PhysicalMoves(family, options['source_schema'], options['backends'],
                          options['physical_profile'], lowering_cache=cache)
    program = moves.program(0)
    assert seed.nodes and program.operators and cache.misses == cache.hits == 1
    query = json.loads(family.candidates[0].query_json)
    first, assignment = cache.lower(query)
    expected = first.to_dict()
    first.operators[0].parameters.clear()
    assignment.clear()
    assert cache.lower(query)[1]
    assert cache.lower(query)[0].to_dict() == expected
    assert calls == []


def test_lowering_cache_is_bounded_and_never_reuses_another_schema():
    data, options, _, family, _, _ = fixture()
    cache = RequestLoweringCache(options['source_schema'], family.language_version, max_entries=1)
    queries = [json.loads(c.query_json) for c in family.candidates[:2]]
    for query in queries:cache.lower(query)
    assert len(cache.entries) == 1
    cache.lower(queries[0])
    assert cache.misses == 3
    tiny = RequestLoweringCache(options['source_schema'], family.language_version, max_bytes=1)
    tiny.lower(queries[0]); tiny.lower(queries[0])
    assert tiny.misses == 2 and tiny.bytes == 0
    other = RequestLoweringCache(options['source_schema'], family.language_version)
    other.lower(queries[0])
    assert other.hits == 0


def test_probe_facts_rescore_without_repredicting_frozen_plan():
    _, _, _, family, prepare, _ = fixture()
    seed = prepare(family.candidates[0], None)
    item = target()
    class CountingCosts:
        calls = 0
        def execution(self, plan, estimator):
            self.calls += 1
            return JointCostProfile().execution(plan, estimator)
    costs = CountingCosts()
    domain = FamilyDomain('q', UnifiedTerminalContract(family, (), epsilon='1'),
        {0: (seed, 1, Resources())}, costs, authority_name='user', authority_version=family.identity,
        settings=UnifiedSettings(information_targets=(item,)))
    key = domain.seed_keys[0]
    scores = [domain.score(FamilyState(facts=((item.name, label),)), key) for label in item.labels]
    assert costs.calls == 1
    assert domain.base_estimate_cache_hits == len(item.labels)-1
    assert len(set(scores)) > 1, 'Changed evidence must not reuse a stale adjusted score'
