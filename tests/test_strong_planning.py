"""New risks: every AND outcome, global budgets, and incumbent retention."""
from dataclasses import replace

from xgap.agent.strong_planning import (AcquisitionAlternative as Action, DeclaredOutcome as Outcome,
    ResourceUsage, StrongSearchLimits, TerminalAlternative as Terminal, search_strong_policy)


class Domain:
    def __init__(self, terminals, actions):
        self.t, self.a = terminals, actions
    def terminals(self, state):
        return iter(self.t.get(state, ()))
    def actions(self, state):
        return iter(self.a.get(state, ()))


def action(name, children, cost=1, **kwargs):
    return Action(name, 'fixture.information', {}, tuple(Outcome(label, state) for label, state in children), cost, **kwargs)


def test_cheap_action_with_one_dead_outcome_is_not_a_strong_plan():
    domain = Domain({'a': [Terminal('answer-a', 10, {})], 'b': [Terminal('answer-b', 20, {})]},
        {'root': [action('cheap-incomplete', [('known', 'a'), ('unknown', 'dead')], .1),
                  action('complete', [('alice', 'a'), ('bob', 'b')], 2)]})
    result = search_strong_policy('root', domain)
    assert result.policy.action.action_id == 'complete'
    assert len(result.policy.children) == 2 and result.policy.estimated_cost == 22
    assert result.action_records[0]['outcomes'] == ['known', 'unknown']
    assert result.action_records[0]['status'] == 'no_complete_strong_continuation'
    assert not result.optimality_certified and result.root_lower_bound is None


def test_feasible_root_survives_incomplete_improvement_and_state_budget():
    domain = Domain({'root': [Terminal('safe', 30, {})], 'a': [Terminal('a', 1, {})]},
        {'root': [action('too-large', [(str(i), 'a') for i in range(4)], .1)]})
    result = search_strong_policy('root', domain, limits=StrongSearchLimits(max_states=3))
    assert result.policy.terminal.terminal_id == 'safe'
    assert result.first_feasible_estimated_cost == 30 and result.retained_states == 1
    assert result.action_records[0]['outcomes'] == ['0', '1', '2', '3']
    assert 'outcome_or_state_budget' in result.limit_events


def test_bounded_improvement_can_replace_but_never_worsen_incumbent():
    domain = Domain({'root': [Terminal('safe', 30, {})], 'a': [Terminal('a', 2, {})],
                     'b': [Terminal('b', 4, {})]},
        {'root': [action('better', [('a', 'a'), ('b', 'b')], 3),
                  action('expensive', [('a', 'a')], 100)]})
    result = search_strong_policy('root', domain, limits=StrongSearchLimits(improvement_actions=1))
    assert result.policy.action.action_id == 'better' and result.policy.estimated_cost == 7
    assert result.generated_actions == 1 and result.first_feasible_estimated_cost == 30


def test_unknown_estimate_still_returns_a_feasible_terminal():
    result = search_strong_policy('root', Domain({'root': [Terminal('unknown', None, {})]}, {}))
    assert result.policy.terminal.terminal_id == 'unknown' and result.status == 'feasible'
    assert result.policy.estimated_cost is None and result.incumbent_cost_upper_bound is None


def test_depth_and_resource_limits_are_pathwise_not_reset_per_outcome():
    domain = Domain({'done': [Terminal('answer', 1, {}, ResourceUsage(remote_calls=2))]},
        {'root': [action('first', [('a', 'middle')], resources=ResourceUsage(model_calls=1))],
         'middle': [action('second', [('a', 'done')], resources=ResourceUsage(model_calls=1))]})
    result = search_strong_policy('root', domain, limits=StrongSearchLimits(max_depth=1))
    assert result.policy is None and 'depth_budget' in result.limit_events
    result = search_strong_policy('root', domain)
    assert result.policy is None and 'resource_budget' in result.limit_events
    result = search_strong_policy('root', domain,
        limits=StrongSearchLimits(resources=ResourceUsage(2, 4096, 2)))
    assert result.policy is not None


def test_binary_outcome_tree_does_not_expand_past_global_cap():
    class Binary:
        def terminals(self, state):
            return [Terminal(state, 1, {})] if len(state) == 12 else []
        def actions(self, state):
            return [action('split-' + state, [('0', state + '0'), ('1', state + '1')])]
    result = search_strong_policy('', Binary(), limits=StrongSearchLimits(max_states=15, max_depth=12, max_actions=20))
    assert result.retained_states <= 15 and result.expanded_states <= 15 and result.generated_actions <= 20
    assert result.status == 'no_feasible_plan' and not result.optimality_certified


def test_deadline_preserves_already_found_plan_without_starting_actions():
    ticks = [0.0]
    class Slow(Domain):
        def terminals(self, state):
            yield Terminal('seed', 10, {})
            ticks[0] = 1
            yield Terminal('better', 5, {})
        def actions(self, state):
            raise AssertionError('Deadline must be checked before generating actions')
    result = search_strong_policy('root', Slow({}, {}), limits=StrongSearchLimits(planning_ms=10), clock=lambda:ticks[0])
    assert result.policy is not None and 'planning_deadline' in result.limit_events


def test_nonexhaustive_outcome_model_cannot_be_certified_strong():
    domain = Domain({'done': [Terminal('answer', 1, {})]},
        {'root': [action('guess', [('only-observed', 'done')], outcomes_exhaustive=False)]})
    result = search_strong_policy('root', domain)
    assert result.policy is None and result.retained_states == 1
