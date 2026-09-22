"""Bounded counterexamples, reserve guarantees, and realized-only effects."""
from dataclasses import dataclass, replace

import pytest

from xgap.agent.unified_lookahead import (Action, ActionFailure, Completion, Limits, Observation, Outcome,
                                         Resources, State, Terminal, choose, run_online)


@dataclass(frozen=True)
class Toy:
    validated: int = 0
    informed: bool = False


class Domain:
    def __init__(self, useful=False):
        self.useful = useful

    def key(self, p):
        return str((p.validated, p.informed))

    knowledge_key = key

    def valid(self, p):
        return 0 <= p.validated <= 2

    def execution_cost(self, p):
        return 1 if p.informed or not self.useful else 100

    def terminals(self, p):
        return (Terminal('answer', self.execution_cost(p), Resources(remote_calls=1)),) if p.validated == 2 else ()

    def validation(self, p):
        return Action('validate', 'binding', (Outcome('ok', replace(p, validated=p.validated+1), 5,
                      Resources(user_calls=1), 1),))

    def probe(self, p):
        return Action('probe', 'probe', (Outcome('small' if self.useful else 'unknown',
                      replace(p, informed=self.useful), .1, Resources(remote_calls=1), 1),))

    def actions(self, p):
        return (() if p.validated == 2 else (self.validation(p),)) + (self.probe(p),)

    def completion(self, p):
        if not self.valid(p):
            return None
        return Completion('fixed-validations', self.key(p), 2-p.validated,
                          Resources(user_calls=2-p.validated, remote_calls=1),
                          (('required_validation', 5*(2-p.validated)), ('execution', self.execution_cost(p))),
                          self.terminals(p)[0] if p.validated == 2 else self.validation(p))

    def verify_completion(self, p, w):
        return w == self.completion(p)


def run(domain, limits, *, override=None):
    calls, executions = [], []
    def perform(action):
        calls.append(action.key)
        o = action.outcomes[0]
        return override(action) if override else Observation(o.label, o.payload, o.resources, {'actual': True})
    def execute(terminal):
        executions.append(terminal.key)
        return dict(success=True, answer_rows=[{'answer': 42}])
    return run_online(Toy(), domain, perform=perform, execute=execute, limits=limits), calls, executions


@pytest.mark.parametrize('useful', [False, True])
def test_two_step_budget_cannot_be_spent_on_probes_even_when_they_look_cheaper(useful):
    report, calls, executed = run(Domain(useful), Limits(horizon=2))
    assert report['success'] and calls == ['validate', 'validate'] and executed == ['answer']
    assert any(r['status'] == 'completion_reserve_lost' for r in report['rounds'][0]['records'])
    assert report['rounds'][0]['reserved_steps'] == 2
    assert not report['strong_plan'] and report['root_gap'] is None


def test_useful_probe_is_allowed_when_it_preserves_completion_and_replans():
    report, calls, executed = run(Domain(True), Limits(horizon=3))
    assert report['success'] and calls == ['probe', 'validate', 'validate']
    assert len(report['rounds']) == 4 and executed == ['answer']
    assert report['rounds'][0]['estimated_cost'] == pytest.approx(11.1)
    assert report['external_calls_during_search'] == 0


def test_remaining_execution_resources_are_reserved_separately_from_action_steps():
    report, calls, _ = run(Domain(True), Limits(horizon=3, resources=Resources(
        user_calls=2, remote_calls=1, bytes=None, peak_bytes=None)))
    assert report['success'] and calls == ['validate', 'validate']


def test_zero_probability_bad_outcome_still_rejects_action():
    class BadBranch(Domain):
        def probe(self, p):
            return Action('probe', 'probe', (
                Outcome('good', replace(p, informed=True), .1, Resources(), 1),
                Outcome('impossible', Toy(3), .1, Resources(), 0)))
    report, calls, _ = run(BadBranch(True), Limits(horizon=3, aggregation='expectation'))
    assert report['success'] and 'probe' not in calls


def test_expected_cost_is_request_fixed_and_not_silently_replaced_by_max():
    class Stochastic(Domain):
        def probe(self, p):
            return Action('probe', 'probe', (
                Outcome('small', replace(p, informed=True), 1, Resources(), .99),
                Outcome('unknown', p, 1, Resources(), .01)))
    expected = choose(State(Toy()), Stochastic(True), limits=Limits(horizon=3, aggregation='expectation'))
    robust = choose(State(Toy()), Stochastic(True), limits=Limits(horizon=3))
    assert expected['choice'].key == 'probe' and robust['choice'].key == 'validate'


def test_unknown_probe_cannot_repeat_just_because_steps_or_receipts_changed():
    domain = Domain()
    state = State(Toy(), steps=1, attempts=((('probe', domain.knowledge_key(Toy())), 1),))
    result = choose(state, domain, limits=Limits(horizon=4))
    assert any(r['status'] == 'no_progress_repeat' for r in result['records'])
    changed = State(Toy(informed=True), attempts=state.attempts)
    result = choose(changed, domain, limits=Limits(horizon=4))
    assert not any(r['status'] == 'no_progress_repeat' for r in result['records'])


@pytest.mark.parametrize('limit', [Limits(horizon=2, optional_ms=0), Limits(horizon=2, max_states=1)])
def test_optional_limits_fall_back_to_saved_completion(limit):
    report, calls, executed = run(Domain(True), limit)
    assert report['success'] and calls == ['validate', 'validate'] and executed == ['answer']
    assert report['rounds'][0]['status'] != 'completed'


def test_timeout_keeps_only_fully_scored_root_action_with_all_outcome_reservations():
    now=[0.0]
    class Interrupted(Domain):
        def actions(self,p):
            return super().actions(p)+(Action('unfinished','probe',(
                Outcome('first',Toy(0,True),0,Resources(),.5),
                Outcome('slow',Toy(2,True),0,Resources(),.5))),)
        def completion(self,p):
            if p==Toy(2,True):now[0]=2.0
            return super().completion(p)
    domain=Interrupted(True)
    result=choose(State(Toy()),domain,limits=Limits(depth=1,horizon=3,optional_ms=1000),clock=lambda:now[0])
    assert result['status']=='optional_deadline_or_state_limit'
    assert result['choice'].key=='probe' and result['estimated_cost']==pytest.approx(11.1)
    assert result['selection_basis']=='completed_root_incumbent'
    assert result['completed_root_actions']==2
    assert len(result['tails'])==len(result['choice'].outcomes)
    assert result['records'][-1]['status']=='interrupted'
    assert 'estimated_cost' not in result['records'][-1]


def test_action_use_and_actual_payload_must_match_the_declared_contract():
    report, _, executed = run(Domain(), Limits(horizon=2), override=lambda a:
        Observation('ok', Toy(2), Resources(user_calls=1)))
    assert not report['success'] and not executed and 'transition' in report['error']
    report, _, executed = run(Domain(), Limits(horizon=2), override=lambda a:
        Observation('ok', a.outcomes[0].payload, Resources(user_calls=2)))
    assert not report['success'] and not executed and 'resource' in report['error']
    assert report['consumed_nonterminal_resources']['user_calls'] == 2


def test_failed_call_is_charged_without_authorizing_its_transition():
    def failed(action):
        raise ActionFailure('unavailable authority', Resources(user_calls=1), {'received': 'failure'})
    report, _, executed = run(Domain(), Limits(horizon=2), override=failed)
    assert not report['success'] and not executed and report['completed_actions'] == 0
    assert report['attempted_actions'] == report['consumed_nonterminal_resources']['user_calls'] == 1
    assert report['trace'][0]['failed'] and report['trace'][0]['evidence'] == {'received': 'failure'}


def test_unknown_bound_is_not_zero_under_hard_resource_limit():
    class Unknown(Domain):
        def completion(self, p):
            return replace(super().completion(p), resources=Resources(user_calls=2-p.validated, remote_calls=None))
    report, calls, executed = run(Unknown(), Limits(resources=Resources(user_calls=2, remote_calls=3)))
    assert report['status'] == 'completion_witness_unavailable' and not calls and not executed


def test_peak_resources_compose_by_max_and_unknown_remains_unknown():
    assert Resources(peak_bytes=5).then(Resources(peak_bytes=7)).peak_bytes == 7
    assert Resources(bytes=None).then(Resources(bytes=10)).bytes is None
    with pytest.raises(ValueError):
        Resources(tokens=True)
    with pytest.raises(ValueError):
        Limits(depth=5)


def test_terminal_ties_prefer_execution_and_horizon_zero_allows_it():
    domain = Domain()
    for horizon in (0, 4):
        result = choose(State(Toy(2)), domain, limits=Limits(horizon=horizon))
        assert isinstance(result['choice'], Terminal)


def test_depth_bounds_count_symbolic_work_without_performing_actions():
    domain = Domain(True)
    shallow = choose(State(Toy()), domain, limits=Limits(depth=1, horizon=3))
    deep = choose(State(Toy()), domain, limits=Limits(depth=2, horizon=3))
    assert shallow['expanded_states'] < deep['expanded_states'] <= 4096
    # At depth two, validation then probe has the same score as probe first;
    # the saved completion action wins the tie.
    assert shallow['choice'].key == 'probe' and deep['choice'].key == 'validate'
    assert shallow['estimated_cost'] == pytest.approx(deep['estimated_cost'])
