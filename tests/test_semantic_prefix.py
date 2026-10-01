"""A2: execute and reuse an exact source prefix, then plan unfinished work.

Historical cardinalities and latencies below are synthetic mechanism inputs.
The local RDF query answers and prefix observations are unmodified.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from test_polynomial_semantic_placement import inputs
from test_question_interpretation import question_run
from test_semantic_planning import registry
from test_semantic_refresh import B04, planning
from xgap.agent.memory import JsonlMemoryStore
from xgap.backends.fuseki_client import FusekiClient
from xgap.runtime.adaptive import ReplanPolicy
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R, RuntimeNodeStatus
from xgap.runtime.planning import PlanObservationSnapshot, RemoteEstimate
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_adaptive import SemanticPrefixPolicy, ResidualPlanSelector
from xgap.runtime.semantic_memory import SemanticPlanMemory
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.runtime.semantic_planning import run_semantic_plans
from xgap.runtime.semantic_refresh import SemanticRefreshPolicy
from xgap.semantic.program import SemanticOperator, SemanticOperatorKind as S, SemanticValueKind as V


def two_source_fixture():
    program, options = inputs(m=2)
    alice = replace(program.operators[0], parameters={"node": {
        "label": "Person", "properties": {"name": "Alice"}}, "entity_field": "person"})
    join = SemanticOperator("join", S.JOIN, ("s0", "s1"), (V.BINDING_SET, V.BINDING_SET),
        V.BINDING_SET, {"left_on": "person", "right_on": "person"})
    program = replace(program, operators=(alice, program.operators[1], join), roots=("join",))
    options["max_remote_calls"] = 2
    space = prepare_semantic_placements(program, **options)
    owners = {node.parameters["observation_key"]: (operator, backend)
        for (operator, backend), nodes in space.local_nodes.items()
        for node in nodes if node.kind is R.REMOTE_QUERY}
    # The old s0 critical path hides s1 latency, making low-cardinality rdf_0
    # preferable. Once s0 is finished, s1's faster rdf_1 placement wins.
    values = {("s0", "rdf_0"): (1000, 100), ("s0", "rdf_1"): (2000, 100),
        ("s1", "rdf_0"): (100, 1), ("s1", "rdf_1"): (1, 10)}
    snapshot = PlanObservationSnapshot("controlled-A2-history", "v1", tuple(
        RemoteEstimate(request.observation_key, request.backend_id,
            *values[owners[request.observation_key]], 40, "synthetic A2 cost table", "v1")
        for request in space.observation_requests), 1000, 0, 0.1)
    return space, snapshot


def source_prefix(space, initial):
    return replace(initial.plan, plan_id="A2-test-prefix",
        nodes=space.local_nodes["s0", "rdf_0"], roots=(space.fragments["s0", "rdf_0"].output,))


@pytest.mark.parametrize("mode", ["replan", "disabled", "below_threshold"])
def test_only_unfinished_placement_changes_and_completed_source_executes_once(mode, monkeypatch):
    import xgap.runtime.semantic_planning as module

    def forbidden(*args, **kwargs):
        pytest.fail("prefix planning reached acquisition or Cartesian enumeration")

    monkeypatch.setattr(module, "enumerate_semantic_plans", forbidden)
    monkeypatch.setattr(module, "product", forbidden)
    monkeypatch.setattr(FusekiClient, "profile", forbidden, raising=False)
    space, history = two_source_fixture()
    before = history.to_dict()
    initial, old_selection = space.select(history)
    assert initial.plan.metadata["source_bindings"] == {"s0": "rdf_0", "s1": "rdf_0"}
    assert old_selection["certificate"]["upper_bound_ms"] == pytest.approx(1024.1)
    policy = ReplanPolicy(max_replans=0) if mode == "disabled" else (
        ReplanPolicy(cardinality_factor_threshold=1e99, latency_factor_threshold=1e99)
        if mode == "below_threshold" else ReplanPolicy())
    tool, calls = registry(space)
    run = run_semantic_plans(space, tool, snapshot=history,
        prefix_policy=SemanticPrefixPolicy(source_operator="s0", replan_policy=policy))
    assert run["success"], run
    detail = run["prefix"]
    assert run["execution"]["value"]["final_rows"] == [{"person": "https://xgap.test/toy/a"}]
    expected_remaining = "rdf_1" if mode == "replan" else "rdf_0"
    assert run["selected_plan"]["metadata"]["source_bindings"] == {"s0": "rdf_0", "s1": expected_remaining}
    assert detail["fixed_source_bindings"] == {"s0": "rdf_0"}
    assert detail["source_operator"] == "s0"
    assert detail["residual_domain"] == {"local_options": 3, "possible_placement_count": 2,
        "max_remote_calls_including_prefix": 2}
    assert detail["initial_selection"] == old_selection
    assert detail["selection_runs"] == (2 if mode == "replan" else 1)
    assert detail["replan_count"] == int(mode == "replan")
    assert bool(detail["replan_reasons"]) == (mode != "below_threshold")
    if mode == "replan":
        assert run["selection"] == detail["selection_after_prefix"]
        assert run["selection"]["certificate"]["objective"] == "estimated_remaining_critical_path_ms"
        assert run["selection"]["certificate"]["fixed_source_bindings"] == {"s0": "rdf_0"}
        assert detail["residual_executed_estimate"]["predicted_latency_ms"] < detail["residual_initial_estimate"]["predicted_latency_ms"]
    else:
        assert detail["selection_after_prefix"] is None
        assert run["selection"] == detail["initial_selection"]
    assert run["selected_plan"]["max_remote_calls"] == space.max_remote_calls == 2
    assert run["observation_calls"] == 0
    assert run["execution_calls"] == run["total_remote_calls"] == len(calls) == 2
    assert detail["prefix_remote_calls"] == detail["continuation_new_remote_calls"] == 1
    assert [backend for backend, _ in calls] == ["rdf_0", expected_remaining]
    assert run["automatic_retries"] == 0 and run["search_space_materialized"] is False
    expected_prefix = source_prefix(space, initial)
    assert set(detail["reused_node_ids"]) == {node.node_id for node in expected_prefix.nodes}
    prefix_results = {node["node_id"]: node for node in detail["probe_run"]["node_results"]}
    continued_results = {node["node_id"]: node for node in detail["continuation_run"]["node_results"]}
    assert all(continued_results[node_id] == result for node_id, result in prefix_results.items())
    updated = PlanObservationSnapshot.from_dict(detail["updated_snapshot"])
    refreshed_keys = {node.parameters["observation_key"] for node in expected_prefix.nodes if node.kind is R.REMOTE_QUERY}
    assert len(refreshed_keys) == 1 and updated.version != history.version
    assert all(estimate == updated.by_key[key] for key, estimate in history.by_key.items() if key not in refreshed_keys)
    observed = updated.by_key[next(iter(refreshed_keys))]
    assert observed.row_count == 1
    assert observed.elapsed_ms == prefix_results["s0/native"]["metadata"]["tool_metrics"]["elapsed_ms"]
    assert run["selection"]["snapshot_version"] == (updated.version if mode == "replan" else history.version)
    assert history.to_dict() == before == detail["history_snapshot"]
    assert run["end_to_end_ms"] >= run["planning_ms"] >= detail["planning_ms"]


def test_b04_ordinary_question_reuses_its_only_source_and_keeps_memory_read_only(tmp_path):
    path = tmp_path / "B04-history.jsonl"
    memory = SemanticPlanMemory(JsonlMemoryStore(path), "A2-B04-episode", 3600)
    cold, _ = question_run(B04, plan_memory=memory)
    assert cold["success"], cold
    before = path.read_bytes()
    records = deepcopy([record.to_dict() for record in memory.store.records()])
    result, calls = question_run(B04, plan_memory=memory,
        prefix_policy=SemanticPrefixPolicy(replan_policy=ReplanPolicy(max_replans=0)))
    assert result["success"], result
    run = planning(result)
    detail = run["prefix"]
    assert run["execution"]["value"]["final_rows"] == B04["expected_rows"]
    assert run["memory"]["state"] == "hit" and run["memory"]["writes"] == 0
    assert detail["residual_initial_estimate"]["predicted_latency_ms"] == 0
    assert detail["residual_executed_estimate"]["remote_calls"] == 0
    assert detail["continuation_new_remote_calls"] == 0
    assert detail["prefix_remote_calls"] == run["execution_calls"] == run["total_remote_calls"] == len(calls) == 1
    assert run["observation_calls"] == 0
    assert path.read_bytes() == before
    assert [record.to_dict() for record in memory.store.records()] == records


def test_residual_scores_zero_completed_work_and_bounds_the_two_unfinished_options():
    space, history = two_source_fixture()
    initial, _ = space.select(history)
    probe = source_prefix(space, initial)
    tool, calls = registry(space)
    executed = FederatedScheduler(tool).execute(probe)
    assert executed.success and len(calls) == 1
    results = {node.node_id: node for node in executed.node_results}
    selector = ResidualPlanSelector(probe, results)
    # Scoring residual work uses the actual completed rows even if the historical
    # table still says 100; no historical latency/calls/bytes are paid again.
    done = selector.estimate(probe, history)
    assert done.predicted_latency_ms == done.predicted_transfer_bytes == done.remote_calls == 0
    assert all(value == 0 for value in done.node_completion_ms.values())
    assert done.node_row_counts == {node_id: result.row_count for node_id, result in results.items()}
    remaining = replace(initial.plan, nodes=space.local_nodes["s1", "rdf_1"],
        roots=(space.fragments["s1", "rdf_1"].output,))
    assert selector.estimate_local(remaining, history).remote_calls == 1
    with pytest.raises(ValueError):
        selector.estimate(remaining, history)
    restricted = replace(space, baseline=initial, options={"s0": ("rdf_0",), "s1": space.options["s1"]})
    chosen, selection = restricted.select(history, _selector=selector)
    costs = [selector.estimate(space.compile({"s0": "rdf_0", "s1": backend}).plan, history).predicted_latency_ms
        for backend in space.options["s1"]]
    certificate = selection["certificate"]
    assert chosen.plan.metadata["source_bindings"] == {"s0": "rdf_0", "s1": "rdf_1"}
    assert certificate["lower_bound_ms"] <= min(costs) <= certificate["upper_bound_ms"] <= max(costs)
    assert certificate["upper_bound_ms"] == min(costs)
    assert selection["evaluated_plan_count"] <= selection["evaluation_bound"]
    assert chosen.plan.max_remote_calls == 2
    assert len(calls) == 1


def test_exact_reuse_rejects_changed_source_and_incomplete_or_failed_results():
    space, history = two_source_fixture()
    initial, _ = space.select(history)
    probe = source_prefix(space, initial)
    tool, calls = registry(space)
    executed = FederatedScheduler(tool).execute(probe)
    assert executed.success and len(calls) == 1
    results = {node.node_id: node for node in executed.node_results}
    remote = next(node for node in initial.plan.nodes if node.node_id == "s0/native")
    for field in ("backend_id", "observation_key", "artifact"):
        changed_value = ({**remote.parameters["artifact"], "artifact_id": "different-query"}
            if field == "artifact" else "different-identity")
        changed_remote = replace(remote, parameters={**remote.parameters, field: changed_value})
        changed_plan = replace(initial.plan, nodes=tuple(changed_remote if node.node_id == remote.node_id else node
            for node in initial.plan.nodes))
        with pytest.raises(ValueError):
            ResidualPlanSelector(probe, results).estimate(changed_plan, history)
    for invalid in ({key: value for key, value in results.items() if key != probe.roots[0]},
            {**results, remote.node_id: replace(results[remote.node_id], status=RuntimeNodeStatus.ERROR,
                error="saved failed prefix")}):
        with pytest.raises(ValueError):
            ResidualPlanSelector(probe, invalid).estimate(initial.plan, history)
    assert len(calls) == 1


def test_failed_prefix_retains_its_attempt_and_never_continues():
    space, history = two_source_fixture()
    tool, calls = registry(space, fail=True)
    run = run_semantic_plans(space, tool, snapshot=history,
        prefix_policy=SemanticPrefixPolicy(source_operator="s0"))
    assert not run["success"]
    detail = run["prefix"]
    assert not detail["probe_run"]["success"]
    assert detail["continuation_run"] is detail["selection_after_prefix"] is None
    assert detail["prefix_remote_calls"] == run["execution_calls"] == run["total_remote_calls"] == len(calls) == 1
    assert detail["continuation_new_remote_calls"] == run["observation_calls"] == run["automatic_retries"] == 0
    assert detail["replan_count"] == 0 and not detail["reused_node_ids"]


@pytest.mark.parametrize("conflict", ["static", "refresh", "unknown_source"])
def test_prefix_conflicts_fail_before_backend_actions(conflict):
    space, history = two_source_fixture()
    tool, calls = registry(space)
    options = {"static_backend_order": ("rdf_0", "rdf_1")} if conflict == "static" else (
        {"refresh_policy": SemanticRefreshPolicy()} if conflict == "refresh" else {})
    policy = SemanticPrefixPolicy(source_operator="missing" if conflict == "unknown_source" else "s0")
    run = run_semantic_plans(space, tool, snapshot=history, prefix_policy=policy, **options)
    assert not run["success"] and run["error"]
    assert run["total_remote_calls"] == 0 and not calls
