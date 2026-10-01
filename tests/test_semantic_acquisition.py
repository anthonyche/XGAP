"""A3's one-request forecast decision is conditional on a synthetic model.

Tiny RDF query answers remain real local evaluations. Forecast scenarios and
reported profile latencies are explicitly controlled mechanism fixtures.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from test_polynomial_semantic_placement import inputs
from test_question_interpretation import question_run
from test_semantic_planning import registry
from test_semantic_prefix import two_source_fixture
from test_semantic_refresh import B04, historical_snapshot, planning
from xgap.agent.memory import JsonlMemoryStore
from xgap.backends.fuseki_client import FusekiClient
from xgap.runtime.planning import FederatedExecutionPlan, FederatedPlanSelector, PlanObservationSnapshot
from xgap.runtime.semantic_acquisition import ProfileForecast, SemanticAcquisitionPolicy
from xgap.runtime.semantic_adaptive import SemanticPrefixPolicy
from xgap.runtime.semantic_memory import SemanticPlanMemory
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.runtime.semantic_planning import run_semantic_plans
from xgap.runtime.semantic_refresh import SemanticRefreshPolicy


def single_source_fixture(preferred="rdf_0"):
    program, options = inputs(m=1)
    source = replace(program.operators[0], parameters={"node": {
        "label": "Person", "properties": {"name": "Alice"}}, "entity_field": "person"})
    space = prepare_semantic_placements(replace(program, operators=(source,)), **options)
    history = historical_snapshot(space)
    return space, replace(history, estimates=tuple(replace(estimate,
        elapsed_ms=1 if estimate.backend_id == preferred else 10) for estimate in history.estimates))


def forecast_policy(*, acquisition=1, reselection=1, budget=1000, rows=5, width=40, outcomes=None):
    return SemanticAcquisitionPolicy(outcomes=outcomes or (
        ProfileForecast("slow", 0.5, 1000, rows, width),
        ProfileForecast("unchanged", 0.5, 1, rows, width)),
        expected_acquisition_ms=acquisition, expected_reselection_ms=reselection,
        max_expected_extra_ms=budget, source="synthetic A3 development forecast", version="v1")


def synthetic_profiles(monkeypatch, latencies):
    attempts = []

    def profile(client, artifact):
        attempts.append((client.backend_id, artifact.artifact_id))
        report = client.execute(artifact)
        return replace(report, elapsed_ms=latencies[client.backend_id], metadata={
            **report.metadata, "latency_source": "synthetic A3 mechanism fixture"})

    monkeypatch.setattr(FusekiClient, "profile", profile, raising=False)
    return attempts


@pytest.mark.parametrize("acquisition,budget,action,gain", [
    (1, 1000, "acquire", 493), (500, 1000, "stop", -6),
    (1, 1, "stop", 493), (494, 1000, "stop", 0)])
def test_positive_net_gain_and_forecast_budget_jointly_control_the_action(acquisition, budget, action, gain, monkeypatch):
    import xgap.runtime.semantic_planning as module

    def forbidden(*args, **kwargs):
        pytest.fail("forecast decision reached Cartesian enumeration")

    monkeypatch.setattr(module, "enumerate_semantic_plans", forbidden)
    monkeypatch.setattr(module, "product", forbidden)
    space, history = single_source_fixture()
    before = history.to_dict()
    initial, _ = space.select(history)
    policy = forecast_policy(acquisition=acquisition, budget=budget)
    decision = policy.decide(space, history, initial)
    assert decision["action"] == action and decision["reason"]
    assert decision["request"] == SemanticRefreshPolicy().choose_request(space, initial.plan, history).to_dict()
    assert decision["expected_stop_execution_ms"] == pytest.approx(501.2)
    assert decision["expected_response_execution_ms"] == pytest.approx(6.2)
    assert decision["expected_extra_ms"] == acquisition + 1
    assert decision["expected_net_gain_ms"] == pytest.approx(gain)
    assert decision["optimal_net_gain_upper_ms"] == pytest.approx(gain)
    assert decision["decision_regret_bound_ms"] == pytest.approx(0 if action == "acquire" else max(0, gain))
    assert decision["forecast_budget_feasible"] is (acquisition + 1 <= budget)
    expected_total = 6.2 + acquisition + 1 if action == "acquire" else 501.2
    assert decision["expected_policy_total_ms"] == pytest.approx(expected_total)
    assert decision["scenario_selection_runs"] == len(decision["scenarios"]) == 2
    assert history.to_dict() == before


def test_two_scenario_tiny_oracle_checks_nonzero_gap_and_conditional_decision_regret():
    space, history = two_source_fixture()
    initial, _ = space.select(history)
    policy = forecast_policy(outcomes=(ProfileForecast("old", 0.5, 1000, 100, 40),
        ProfileForecast("small-fast", 0.5, 0, 1, 40)))
    decision = policy.decide(space, history, initial)
    key = decision["request"]["observation_key"]
    remote = next(node for node in initial.plan.nodes if node.node_id == "s0/native")
    assert key == remote.parameters["observation_key"]
    expected_stop = expected_response = expected_optimum = weighted_gap = 0.0
    for forecast, scenario in zip(policy.outcomes, decision["scenarios"]):
        changed = replace(history.by_key[key], elapsed_ms=forecast.elapsed_ms,
            row_count=forecast.row_count, row_width_bytes=forecast.row_width_bytes)
        hypothetical = history.with_estimates((changed,), version="oracle/" + forecast.outcome_id)
        selector = FederatedPlanSelector()
        baseline = selector.estimate(initial.plan, hypothetical).predicted_latency_ms
        # Four explicit tiny placements are an independent oracle for P1;
        # production planning never calls the Cartesian enumerator.
        optimum = min(selector.estimate(space.compile({"s0": first, "s1": second}).plan,
            hypothetical).predicted_latency_ms for first in space.options["s0"] for second in space.options["s1"])
        certificate = scenario["selection"]["certificate"]
        upper, lower = certificate["upper_bound_ms"], certificate["lower_bound_ms"]
        assert scenario["probability"] == forecast.probability
        assert scenario["baseline_cost_ms"] == pytest.approx(baseline)
        assert scenario["response_cost_ms"] == pytest.approx(upper)
        assert certificate["baseline_ms"] == pytest.approx(baseline)
        assert lower <= optimum <= upper <= baseline
        expected_stop += forecast.probability * baseline
        expected_response += forecast.probability * upper
        expected_optimum += forecast.probability * optimum
        weighted_gap += forecast.probability * (upper - lower)
    assert weighted_gap > 0
    extra = policy.expected_acquisition_ms + policy.expected_reselection_ms
    assert decision["action"] == "acquire"
    assert decision["expected_stop_execution_ms"] == pytest.approx(expected_stop)
    assert decision["expected_response_execution_ms"] == pytest.approx(expected_response)
    gain = expected_stop - expected_response - extra
    assert decision["expected_net_gain_ms"] == pytest.approx(gain)
    assert decision["optimal_net_gain_upper_ms"] == pytest.approx(gain + weighted_gap)
    assert decision["decision_regret_bound_ms"] == pytest.approx(weighted_gap)
    independent_best_action = min(expected_stop, expected_optimum + extra)
    assert decision["expected_policy_total_ms"] - independent_best_action <= weighted_gap + 1e-9


def test_uncertified_scenario_cannot_invent_a_decision_regret_bound():
    space, history = single_source_fixture()
    space = replace(space, same_cost_topology=False)
    initial, _ = space.select(history)
    decision = forecast_policy().decide(space, history, initial)
    assert decision["action"] == "acquire"
    assert all(scenario["selection"]["certificate"]["lower_bound_ms"] is None for scenario in decision["scenarios"])
    assert decision["optimal_net_gain_upper_ms"] is decision["decision_regret_bound_ms"] is None


def test_scenario_and_actual_reselection_are_anchored_at_the_initial_selected_plan(monkeypatch):
    space, history = single_source_fixture(preferred="rdf_1")
    initial, _ = space.select(history)
    assert initial.plan.plan_id != space.baseline.plan.plan_id
    before = history.to_dict()
    profiles = synthetic_profiles(monkeypatch, {"rdf_0": 10, "rdf_1": 1000})
    tool, calls = registry(space)
    run = run_semantic_plans(space, tool, snapshot=history, acquisition_policy=forecast_policy())
    assert run["success"], run
    assert run["execution"]["value"]["final_rows"] == [{"person": "https://xgap.test/toy/a"}]
    acquisition, refresh = run["acquisition"], run["refresh"]
    assert acquisition["decision"]["action"] == "acquire"
    assert len(profiles) == run["observation_calls"] == 1
    assert run["execution_calls"] == 1 and run["total_remote_calls"] == len(calls) == 2
    assert refresh["request"] == acquisition["decision"]["request"]
    assert refresh["request"]["backend_id"] == "rdf_1"
    for scenario in acquisition["decision"]["scenarios"]:
        assert scenario["selection"]["certificate"]["baseline_ms"] == pytest.approx(scenario["baseline_cost_ms"])
    updated = PlanObservationSnapshot.from_dict(refresh["updated_snapshot"])
    initial_cost = FederatedPlanSelector().estimate(initial.plan, updated).predicted_latency_ms
    assert run["selection"]["certificate"]["baseline_ms"] == pytest.approx(initial_cost)
    assert run["selection"]["certificate"]["upper_bound_ms"] <= initial_cost
    assert run["selected_plan"]["metadata"]["source_bindings"] == {"s0": "rdf_0"}
    # Actual Alice cardinality is 1, outside the forecast's declared 5-row
    # support; deterministic execution still succeeds, without a realized bound.
    assert acquisition["forecast_support_match"] is False
    assert history.to_dict() == before
    assert run["end_to_end_ms"] >= run["planning_ms"] >= acquisition["decision_ms"] >= 0


def test_b04_ordinary_entry_acquires_or_stops_with_identical_gold_and_read_only_history(tmp_path, monkeypatch):
    latencies = {"rdf_a": 1, "rdf_b": 10}
    profiles = synthetic_profiles(monkeypatch, latencies)
    path = tmp_path / "shared-B04-history.jsonl"
    memory = SemanticPlanMemory(JsonlMemoryStore(path), "A3-B04-episode", 3600)
    cold, _ = question_run(B04, plan_memory=memory)
    assert cold["success"], cold
    cold_run = planning(cold)
    saved = deepcopy([record.to_dict() for record in memory.store.records()])
    before = path.read_bytes()
    historical = PlanObservationSnapshot.from_dict(saved[0]["value"]["snapshot"])
    selected_history = next(estimate for estimate in historical.estimates if estimate.backend_id == "rdf_a")
    latencies["rdf_a"] = 1000
    for acquisition_cost, action, backend in ((1, "acquire", "rdf_b"), (500, "stop", "rdf_a")):
        attempted = len(profiles)
        policy = forecast_policy(acquisition=acquisition_cost,
            rows=selected_history.row_count, width=selected_history.row_width_bytes)
        result, calls = question_run(B04, plan_memory=memory, acquisition_policy=policy)
        assert result["success"], result
        run = planning(result)
        acquisition, refresh = run["acquisition"], run["refresh"]
        assert acquisition["decision"]["action"] == action
        assert run["execution"]["value"]["final_rows"] == B04["expected_rows"]
        assert set(run["selected_plan"]["metadata"]["source_bindings"].values()) == {backend}
        assert len(profiles) - attempted == run["observation_calls"] == int(action == "acquire")
        assert run["execution_calls"] == 1
        assert len(calls) == result["backend_remote_calls"] == run["total_remote_calls"]
        assert run["automatic_retries"] == run["memory"]["writes"] == 0
        assert run["memory"]["state"] == "hit"
        assert refresh["history"]["historical_acquisition"]["remote_calls"] == cold_run["observation_calls"]
        assert refresh["selection_runs"] == (2 if action == "acquire" else 1)
        observation_ms = refresh["observation"]["elapsed_ms"] if refresh["observation"] else 0
        assert run["planning_ms"] == pytest.approx(run["enumeration_ms"] + run["memory_ms"]
            + run["selection_ms"] + acquisition["decision_ms"] + observation_ms + refresh["overhead_ms"])
        assert run["end_to_end_ms"] >= run["planning_ms"]
        assert path.read_bytes() == before
        assert [record.to_dict() for record in memory.store.records()] == saved

    # Frozen A1 controls use the same history and current toy state. They do
    # not pay A3's scenario-rollout CPU or receive an acquisition decision.
    for mode, backend in (("refresh_reselect", "rdf_b"), ("no_refresh", "rdf_a")):
        attempted = len(profiles)
        result, calls = question_run(B04, plan_memory=memory,
            refresh_policy=SemanticRefreshPolicy(mode))
        assert result["success"], result
        run = planning(result)
        refresh = run["refresh"]
        assert run["acquisition"] is None
        assert run["execution"]["value"]["final_rows"] == B04["expected_rows"]
        assert set(run["selected_plan"]["metadata"]["source_bindings"].values()) == {backend}
        assert len(profiles) - attempted == run["observation_calls"] == int(mode == "refresh_reselect")
        assert run["execution_calls"] == 1
        assert run["total_remote_calls"] == result["backend_remote_calls"] == len(calls)
        assert refresh["history"]["snapshot"] == historical.to_dict()
        assert run["memory"]["state"] == "hit" and run["memory"]["writes"] == 0
        observation_ms = refresh["observation"]["elapsed_ms"] if refresh["observation"] else 0
        assert run["planning_ms"] == pytest.approx(run["enumeration_ms"] + run["memory_ms"]
            + run["selection_ms"] + observation_ms + refresh["overhead_ms"])
        assert path.read_bytes() == before
        assert [record.to_dict() for record in memory.store.records()] == saved


def test_acquire_decision_retains_first_failed_profile_without_execution_or_retry():
    space, history = single_source_fixture()
    before = history.to_dict()
    tool, calls = registry(space, fail=True)
    run = run_semantic_plans(space, tool, snapshot=history, acquisition_policy=forecast_policy())
    assert not run["success"] and run["error"]
    acquisition, refresh = run["acquisition"], run["refresh"]
    assert acquisition["decision"]["action"] == "acquire"
    assert acquisition["state"] == refresh["state"] == "failed"
    assert refresh["request"] == acquisition["decision"]["request"]
    assert refresh["observation"]["attempted_calls"] == 1
    assert not refresh["observation"]["success"]
    assert run["observation_calls"] == run["total_remote_calls"] == len(calls) == 1
    assert run["execution_calls"] == run["automatic_retries"] == 0
    assert run["execution"] is refresh["updated_snapshot"] is refresh["post_selection"] is None
    assert history.to_dict() == before
    assert run["planning_ms"] >= acquisition["decision_ms"] + refresh["observation"]["elapsed_ms"]


@pytest.mark.parametrize("fault", ["missing", "incomplete", "static", "refresh", "prefix"])
def test_invalid_acquisition_admission_stops_before_backend_calls(fault):
    space, history = single_source_fixture()
    tool, calls = registry(space)
    options = {"snapshot": history}
    if fault == "missing":
        options = {}
    elif fault == "incomplete":
        options["snapshot"] = replace(history, estimates=history.estimates[:-1])
    elif fault == "static":
        options["static_backend_order"] = ("rdf_0", "rdf_1")
    elif fault == "refresh":
        options["refresh_policy"] = SemanticRefreshPolicy()
    else:
        options["prefix_policy"] = SemanticPrefixPolicy()
    run = run_semantic_plans(space, tool, acquisition_policy=forecast_policy(), **options)
    assert not run["success"] and run["error"]
    assert run["total_remote_calls"] == 0 and not calls
    assert run["execution"] is None
