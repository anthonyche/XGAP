"""Decision-local transpositions preserve resource and validation certificates."""
from dataclasses import replace

import pytest

from test_unified_lookahead import Domain, Toy, run
from xgap.agent.unified_lookahead import Action, Limits, Outcome, Resources, State, choose


class Diamond(Domain):
    def actions(self, payload):
        if payload.validated == 2:
            return ()
        validation = self.validation(payload)
        return (validation, replace(validation, key='same-transition'))


class CachedDiamond(Diamond):
    search_cache_key = staticmethod(lambda payload: payload)


def test_repeated_subtrees_are_scored_once_without_changing_choice_or_effects():
    limits = Limits(depth=3, horizon=3, optional_ms=10000)
    plain = choose(State(Toy()), Diamond(), limits=limits)
    cached = choose(State(Toy()), CachedDiamond(), limits=limits)
    for field in ('choice', 'estimated_cost', 'tails', 'witness', 'status'):
        assert cached[field] == plain[field]
    assert cached['search_cache_hits']['evaluation'] > 0
    assert cached['expanded_states'] < plain['expanded_states']
    a, calls_a, executions_a = run(Diamond(), limits)
    b, calls_b, executions_b = run(CachedDiamond(), limits)
    assert calls_a == calls_b == ['validate', 'validate']
    assert executions_a == executions_b == ['answer']
    assert a['answer_rows'] == b['answer_rows']


@pytest.mark.parametrize('horizon', [2, 3, 4])
@pytest.mark.parametrize('remote_budget', [1, 2, 3])
def test_cached_completion_keeps_resource_horizon_and_retry_reserves(horizon, remote_budget):
    class Cached(Domain):
        search_cache_key = staticmethod(lambda payload: payload)
    limits = Limits(depth=3, horizon=horizon, optional_ms=10000,
                    resources=Resources(user_calls=2, remote_calls=remote_budget,
                                        bytes=None, peak_bytes=None))
    for history in ((), ((('probe', Domain().knowledge_key(Toy())), 1),)):
        state = State(Toy(), attempts=history)
        plain = choose(state, Domain(True), limits=limits)
        cached = choose(state, Cached(True), limits=limits)
        for field in ('choice', 'estimated_cost', 'tails', 'witness', 'status'):
            assert cached[field] == plain[field]


def test_same_payload_with_different_resource_use_must_not_share_a_subtree():
    class Spending(Diamond):
        def actions(self, payload):
            if payload.validated:
                return super().actions(payload)
            # Both paths are admissible, but only the first retains probe budget.
            return (Action('cheap', 'binding', (Outcome('ok', Toy(1), 5,
                        Resources(user_calls=1)),)),
                    Action('spent', 'binding', (Outcome('ok', Toy(1), 0,
                        Resources(user_calls=1, remote_calls=1)),)))
    class Cached(Spending):
        search_cache_key = staticmethod(lambda payload: payload)
    limits = Limits(depth=3, horizon=3, optional_ms=10000,
                    resources=Resources(user_calls=2, remote_calls=1, bytes=None, peak_bytes=None))
    plain = choose(State(Toy()), Spending(), limits=limits)
    cached = choose(State(Toy()), Cached(), limits=limits)
    assert plain['choice'] == cached['choice']
    assert plain['estimated_cost'] == cached['estimated_cost']
    assert any(r['action'] == 'spent' and r['status'] == 'completion_reserve_lost'
               for r in cached['records'])


def test_no_cache_survives_a_new_decision_with_a_changed_estimator():
    domain = CachedDiamond(True)
    first = choose(State(Toy(2)), domain)
    domain.useful = False
    second = choose(State(Toy(2)), domain)
    assert first['estimated_cost'] == 100
    assert second['estimated_cost'] == 1


def test_actual_family_reuses_transpositions_without_changing_validation_choice():
    from test_ch6_variants import domain_for
    from xgap.agent.unified_family import UnifiedSettings, FamilyState
    settings = UnifiedSettings(epsilon='1/3', relaxable=('hops', 'lower', 'upper'),
                              limits=Limits(depth=3, optional_ms=10000))
    plain, _ = domain_for(settings)
    plain.search_cache_key = None
    cached, calls = domain_for(settings)
    a = choose(State(FamilyState()), plain, limits=settings.limits)
    b = choose(State(FamilyState()), cached, limits=settings.limits)
    assert a['choice'] == b['choice'] and a['estimated_cost'] == b['estimated_cost']
    assert a['status'] == b['status'] == 'completed'
    assert b['expanded_states'] < a['expanded_states'] and not calls


def test_mutated_action_registry_invalidates_scored_subtrees():
    class MutableDiamond(CachedDiamond):
        def __init__(self):
            super().__init__()
            self.epoch = 0
        def search_cache_epoch(self):
            return self.epoch
        def actions(self, payload):
            self.epoch += 1
            return super().actions(payload)
    result = choose(State(Toy()), MutableDiamond(), limits=Limits(depth=3, optional_ms=10000))
    assert result['status'] == 'completed'
    assert result['search_cache_hits']['evaluation'] == 0
    assert result['choice'].key == 'validate'
