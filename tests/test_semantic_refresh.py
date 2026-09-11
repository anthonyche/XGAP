"""A1 mechanism gate: synthetic estimate drift, real local toy query answers.

Reported profile latency is deliberately controlled; this is not a workload
speedup experiment. The NL fixture, gold rows and frozen catalog stay unchanged.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from test_polynomial_semantic_placement import inputs, snapshot
from test_question_interpretation import CASES, question_run
from test_semantic_planning import registry, setup as oracle_setup
from xgap.agent.memory import InMemoryStore, JsonlMemoryStore
from xgap.backends.fuseki_client import FusekiClient
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.planning import FederatedPlanSelector, PlanObservationSnapshot
from xgap.runtime.semantic_memory import SemanticPlanMemory
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.runtime.semantic_planning import run_semantic_plans
from xgap.runtime.semantic_refresh import SemanticRefreshPolicy


B04 = next(case for case in CASES if case["id"] == "B04")


def planning(question):
    return question["state"]["output"]["planning_run"]


def synthetic_profiles(monkeypatch, latencies):
    """Keep RDFLib answers, replacing only the declared profile elapsed value."""
    attempts = []

    def profile(client, artifact):
        attempts.append((client.backend_id, artifact.artifact_id))
        report = client.execute(artifact)
        return replace(report, elapsed_ms=latencies[client.backend_id],
            metadata={**report.metadata, "latency_source": "synthetic A1 mechanism fixture"})

    monkeypatch.setattr(FusekiClient, "profile", profile, raising=False)
    return attempts


def local_space(m=1):
    program, options = inputs(m=m)
    return prepare_semantic_placements(program, **options)


def historical_snapshot(space):
    return replace(snapshot(space), estimates=tuple(replace(e,
        elapsed_ms=1 if e.backend_id == "rdf_0" else 10)
        for e in snapshot(space).estimates))


def assert_accounting(run, calls):
    detail = run["refresh"]
    observed_ms = detail["observation"]["elapsed_ms"] if detail["observation"] else 0
    assert run["total_remote_calls"] == len(calls) == run["observation_calls"] + run["execution_calls"]
    assert run["automatic_retries"] == 0
    assert detail["elapsed_ms"] == pytest.approx(
        detail["selection_ms"] + observed_ms + detail["overhead_ms"])
    assert run["planning_ms"] == pytest.approx(run["enumeration_ms"] + run["memory_ms"]
        + run["selection_ms"] + observed_ms + detail["overhead_ms"])
    assert run["end_to_end_ms"] >= run["planning_ms"] >= detail["elapsed_ms"]


def test_b04_question_entry_refresh_arms_share_history_and_gold_without_enumeration(tmp_path, monkeypatch):
    import xgap.runtime.semantic_planning as module

    def forbidden(*args, **kwargs):
        pytest.fail("ordinary refresh entry reached Cartesian placement enumeration")

    monkeypatch.setattr(module, "enumerate_semantic_plans", forbidden)
    monkeypatch.setattr(module, "product", forbidden)
    latencies = {"rdf_a": 1, "rdf_b": 10}
    profiles = synthetic_profiles(monkeypatch, latencies)
    path = tmp_path / "shared-history.jsonl"
    memory = SemanticPlanMemory(JsonlMemoryStore(path), "synthetic-drift-episode", 3600)
    cold, _ = question_run(B04, plan_memory=memory)
    assert cold["success"], cold
    cold_run = planning(cold)
    assert set(cold_run["selected_plan"]["metadata"]["source_bindings"].values()) == {"rdf_a"}
    frozen_bytes = path.read_bytes()
    frozen_records = deepcopy([record.to_dict() for record in memory.store.records()])
    latencies["rdf_a"] = 1000

    runs = {}
    for mode in ("refresh_reselect", "refresh_only", "no_refresh"):
        before = len(profiles)
        result, calls = question_run(B04, plan_memory=memory,
            refresh_policy=SemanticRefreshPolicy(mode))
        assert result["success"], result
        run = runs[mode] = planning(result)
        detail = run["refresh"]
        assert run["execution"]["value"]["final_rows"] == B04["expected_rows"]
        assert {h: v["value"] for h, v in result["state"]["output"]["bindings"].items()} == B04["expected_bindings"]
        expected_backend = "rdf_b" if mode == "refresh_reselect" else "rdf_a"
        assert set(run["selected_plan"]["metadata"]["source_bindings"].values()) == {expected_backend}
        expected_acquisition = int(mode != "no_refresh")
        assert len(profiles) - before == run["observation_calls"] == expected_acquisition
        assert run["execution_calls"] == 1
        assert len(calls) == result["backend_remote_calls"]
        assert detail["state"] == "completed"
        assert detail["selection_runs"] == (2 if mode == "refresh_reselect" else 1)
        assert detail["executed_plan_id"] == run["selection"]["selected_plan_id"] == run["selected_plan"]["plan_id"]
        assert run["search_space_materialized"] is False
        assert run["memory"]["state"] == "hit" and run["memory"]["writes"] == 0
        assert detail["history"]["source"] == "plan_memory"
        assert detail["history"]["historical_acquisition"] == run["memory"]["historical_acquisition"]
        assert detail["history"]["historical_acquisition"]["remote_calls"] == cold_run["observation_calls"]
        assert detail["history"]["historical_acquisition"]["elapsed_ms"] == cold_run["observation"]["elapsed_ms"]
        old = detail["history"]["snapshot"]
        assert detail["initial_selection"]["snapshot_version"] == old["version"]
        if mode == "no_refresh":
            assert detail["post_selection"] is detail["updated_snapshot"] is detail["observation"] is None
            assert run["selection"] == detail["initial_selection"]
            current = old
        else:
            current = detail["updated_snapshot"]
            assert current["snapshot_id"] == old["snapshot_id"]
            assert current["version"] != old["version"]
            assert detail["observation"]["attempted_calls"] == 1
            assert detail["observation"]["requests"] == [detail["request"]]
            refreshed = detail["request"]["observation_key"]
            old_by_key = {e["observation_key"]: e for e in old["estimates"]}
            current_by_key = {e["observation_key"]: e for e in current["estimates"]}
            assert set(old_by_key) == set(current_by_key)
            assert current_by_key[refreshed]["elapsed_ms"] == 1000
            assert all(e == current_by_key[key] for key, e in old_by_key.items() if key != refreshed)
            if mode == "refresh_reselect":
                assert run["selection"] == detail["post_selection"]
                assert run["selection"]["snapshot_version"] == current["version"]
            else:
                assert detail["post_selection"] is None
                assert run["selection"] == detail["initial_selection"]
                assert run["selection"]["snapshot_version"] == old["version"]
        executed = detail["executed_plan_estimate"]
        assert (executed["snapshot_id"], executed["snapshot_version"]) == (current["snapshot_id"], current["version"])
        score = FederatedPlanSelector().estimate(FederatedExecutionPlan.from_dict(run["selected_plan"]),
            PlanObservationSnapshot.from_dict(current)).to_dict()
        assert executed["estimate"] == score
        assert_accounting(run, calls)
        assert path.read_bytes() == frozen_bytes
        assert [record.to_dict() for record in memory.store.records()] == frozen_records

    reselect, refresh_only, no_refresh = (runs[m]["refresh"] for m in runs)
    assert reselect["request"] == refresh_only["request"] == no_refresh["request"]
    assert reselect["request"]["operation"] == "profile"
    assert reselect["request"]["backend_id"] == "rdf_a"
    assert reselect["history"] == refresh_only["history"] == no_refresh["history"]
    assert reselect["initial_selection"] == refresh_only["initial_selection"] == no_refresh["initial_selection"]
    assert refresh_only["executed_plan_estimate"]["estimate"]["predicted_latency_ms"] > no_refresh["executed_plan_estimate"]["estimate"]["predicted_latency_ms"]


def test_explicit_history_cost_is_unavailable_and_refresh_does_not_relabel_old_certificate(monkeypatch):
    space = local_space()
    historical = historical_snapshot(space)
    before = historical.to_dict()
    synthetic_profiles(monkeypatch, {"rdf_0": 1000, "rdf_1": 10})
    tool, calls = registry(space)
    run = run_semantic_plans(space, tool, snapshot=historical,
        refresh_policy=SemanticRefreshPolicy("refresh_only"))
    assert run["success"], run
    detail = run["refresh"]
    assert detail["history"] == {"source": "explicit_snapshot", "snapshot": before,
        "historical_acquisition": None}
    assert historical.to_dict() == before
    assert run["selection"] == detail["initial_selection"]
    assert run["selection"]["snapshot_version"] == historical.version
    assert detail["executed_plan_estimate"]["snapshot_version"] == detail["updated_snapshot"]["version"] != historical.version
    assert detail["executed_plan_estimate"]["estimate"]["predicted_latency_ms"] > run["selection"]["certificate"]["upper_bound_ms"]
    assert_accounting(run, calls)


def test_request_uses_largest_historical_initial_plan_key_and_stable_ties():
    space = local_space(m=2)
    historical = historical_snapshot(space)
    initial, _ = space.select(historical)
    keys = sorted(n.parameters["observation_key"] for n in initial.plan.nodes if "observation_key" in n.parameters)
    assert len(keys) == 2
    policy = SemanticRefreshPolicy()
    # Unselected alternatives are slower still; they must not drive acquisition.
    largest = replace(historical, estimates=tuple(replace(e,
        elapsed_ms=3 if e.observation_key == keys[1] else e.elapsed_ms) for e in historical.estimates))
    assert policy.choose_request(space, initial.plan, largest).observation_key == keys[1]
    assert policy.choose_request(space, initial.plan, historical).observation_key == keys[0]


@pytest.mark.parametrize("fault", ["missing", "empty_memory", "incomplete", "backend_identity", "static", "enumerated_space"])
def test_invalid_warm_admission_stops_before_backend_calls(fault):
    space = oracle_setup() if fault == "enumerated_space" else local_space()
    tool, calls = registry(space)
    history = historical_snapshot(space)
    options = {"snapshot": history}
    if fault == "missing":
        options = {}
    elif fault == "empty_memory":
        options = {"plan_memory": SemanticPlanMemory(InMemoryStore(), "missing-episode", 30)}
    elif fault == "incomplete":
        options["snapshot"] = replace(history, estimates=history.estimates[:-1])
    elif fault == "backend_identity":
        options["snapshot"] = replace(history, estimates=(replace(history.estimates[0], backend_id="wrong-backend"), *history.estimates[1:]))
    elif fault == "static":
        options["static_backend_order"] = ("rdf_0", "rdf_1")
    run = run_semantic_plans(space, tool, refresh_policy=SemanticRefreshPolicy(), **options)
    assert not run["success"] and run["error"]
    assert run["total_remote_calls"] == 0 and not calls
    assert run["selection"] is run["execution"] is None
    assert run["memory"]["writes"] == 0


def test_expired_warm_history_stops_without_reacquisition_or_ttl_extension(tmp_path):
    now = [100.0]
    clock = lambda: now[0]
    path = tmp_path / "history.jsonl"
    store = JsonlMemoryStore(path, clock=clock)
    writer = SemanticPlanMemory(store, "episode", 100, clock)
    cold, _ = question_run(B04, plan_memory=writer)
    assert cold["success"], cold
    frozen = path.read_bytes()
    now[0] = 110.0
    reader = SemanticPlanMemory(store, "episode", 10, clock)
    result, calls = question_run(B04, plan_memory=reader,
        refresh_policy=SemanticRefreshPolicy("no_refresh"))
    assert not result["success"] and result["backend_remote_calls"] == 0 and not calls
    assert path.read_bytes() == frozen


def test_failed_refresh_keeps_one_attempt_and_read_only_memory(tmp_path):
    space = local_space()
    path = tmp_path / "history.jsonl"
    memory = SemanticPlanMemory(JsonlMemoryStore(path), "episode", 3600)
    tool, _ = registry(space)
    cold = run_semantic_plans(space, tool, plan_memory=memory)
    assert cold["success"], cold
    frozen = path.read_bytes()
    broken, calls = registry(space, fail=True)
    run = run_semantic_plans(space, broken, plan_memory=memory,
        refresh_policy=SemanticRefreshPolicy())
    assert not run["success"] and run["execution"] is None
    assert run["observation_calls"] == run["total_remote_calls"] == len(calls) == 1
    assert run["execution_calls"] == run["automatic_retries"] == run["memory"]["writes"] == 0
    detail = run["refresh"]
    assert detail["state"] == "failed" and detail["selection_runs"] == 1
    assert detail["observation"]["attempted_calls"] == 1 and not detail["observation"]["success"]
    assert detail["updated_snapshot"] is detail["post_selection"] is detail["executed_plan_id"] is None
    assert detail["history"]["historical_acquisition"]["remote_calls"] == cold["observation_calls"]
    assert path.read_bytes() == frozen
    assert_accounting(run, calls)


def test_ablation_retains_correct_answer_as_contract_failure_for_wrong_backend(monkeypatch):
    import xgap.experiments.toy_refresh as module
    from xgap.agent.memory import MemoryRecord, MemoryScope
    from xgap.runtime.planning import RemoteEstimate

    clock = lambda: 100.0
    store = InMemoryStore(clock=clock)
    acquisition = {"remote_calls": 2, "elapsed_ms": 7.0, "goal_id": "fake-B04-history"}
    history = PlanObservationSnapshot("semantic-observation/fake-B04", "history-v1", tuple(
        RemoteEstimate("B04/" + backend, backend, 1.0, 1, 40, "fake B04 history", "history-v1")
        for backend in ("neo4j", "fuseki")), 1000)
    store.put(MemoryRecord(MemoryScope.EXECUTION, history.snapshot_id,
        {"snapshot": history.to_dict(), "acquisition": acquisition}, "fake B04 complete history",
        history.version, created_at=100, expires_at=3700))
    memory = SemanticPlanMemory(store, "fake-B04-episode", 3600, clock)
    attempted_modes = []

    def answer_with_wrong_backend(case, mapping, *, refresh_policy, plan_memory, **options):
        assert case is B04
        attempted_modes.append(refresh_policy.mode)
        return {"success": True, "actual_rows": deepcopy(B04["expected_rows"]),
            "agent_run": {"state": {"output": {"planning_run": {
                "observation_calls": 1, "execution_calls": 1,
                "selected_plan": {"metadata": {"source_bindings": {"people": "neo4j"}}},
                "refresh": {"selection_runs": 2},
                "memory": {"historical_acquisition": acquisition, "writes": 0}}}}}}

    monkeypatch.setattr(module, "execute_binding_case", answer_with_wrong_backend)
    record, retained = {}, []
    with pytest.raises(ValueError, match="A1 mechanism contract failed: expected_backend"):
        module.execute_refresh_ablation(B04, {}, clients={}, memory=memory, record=record,
            on_update=lambda: retained.append(deepcopy(record)))

    assert attempted_modes == ["refresh_reselect"]
    assert not record["success"]
    failed, *following = record["arms"]
    assert failed["execution_answer_success"] is True
    assert failed["actual_rows"] == B04["expected_rows"]
    assert failed["success"] is failed["contract_passed"] is False
    assert failed["status"] == "contract_failed"
    assert [name for name, passed in failed["contract_checks"].items() if not passed] == ["expected_backend"]
    assert all(arm["status"] == "not_attempted_after_failure" and not arm["success"] for arm in following)
    assert retained[-1] == record
    checking = [update["arms"][0] for update in retained if update["arms"][0]["status"] == "checking_contract"]
    assert checking and all(arm["success"] is False for arm in checking)
