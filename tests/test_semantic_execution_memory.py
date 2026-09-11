"""Observation reuse changes actions, not the question's executable meaning."""

from dataclasses import replace

import pytest

from test_question_interpretation import CASES, question_run
from test_semantic_planning import setup, registry, controlled_snapshot
from xgap.agent.memory import InMemoryStore, JsonlMemoryStore
from xgap.runtime.semantic_memory import SemanticPlanMemory
from xgap.runtime.semantic_planning import run_semantic_plans


def planning(question):
    return question["state"]["output"]["planning_run"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_cold_warm_and_no_memory_share_the_question_entry_and_gold(case):
    store = InMemoryStore()
    memory = SemanticPlanMemory(store, "controlled-database-episode", 3600)
    cold, cold_calls = question_run(case, plan_memory=memory)
    warm, warm_calls = question_run(case, plan_memory=memory)
    absent, absent_calls = question_run(case)
    for result in (cold, warm, absent):
        assert result["success"], result
        assert planning(result)["execution"]["value"]["final_rows"] == case["expected_rows"]
    c, w, a = map(planning, (cold, warm, absent))
    assert c["memory"]["state"] == "miss_stored" and c["memory"]["writes"] == 1
    assert w["memory"]["state"] == "hit" and w["memory"]["writes"] == 0
    assert w["snapshot_reused"] and w["observation_calls"] == 0
    assert c["candidate_count"] == w["candidate_count"]
    assert c["local_option_count"] == w["local_option_count"] == a["local_option_count"]
    assert c["selected_plan"] == w["selected_plan"]
    assert len(warm_calls) == w["execution_calls"] > 0  # Answers are never cached.
    assert len(cold_calls) == len(absent_calls) == len(warm_calls) + c["observation_calls"]
    assert w["memory"]["historical_acquisition"]["remote_calls"] == c["observation_calls"]
    assert w["memory"]["historical_acquisition"]["elapsed_ms"] == c["observation"]["elapsed_ms"]
    assert a["memory"]["state"] == "disabled"
    assert all(r["end_to_end_ms"] >= r["planning_ms"] >= r["memory_ms"] for r in (c, w, a))
    assert len(store.records()) == 1


def test_memory_survives_existing_jsonl_store_reload(tmp_path):
    path = tmp_path / "memory.jsonl"
    cold, _ = question_run(CASES[0], plan_memory=SemanticPlanMemory(JsonlMemoryStore(path), "db-v1", 3600))
    assert cold["success"]
    before = path.read_bytes()
    warm, calls = question_run(CASES[0], plan_memory=SemanticPlanMemory(JsonlMemoryStore(path), "db-v1", 3600))
    assert warm["success"] and planning(warm)["memory"]["state"] == "hit"
    assert len(calls) == 2 and path.read_bytes() == before


@pytest.mark.parametrize("change", ["source_snapshot", "meaning", "replicas", "cost", "episode"])
def test_changed_context_must_acquire_its_own_observations(change):
    store = InMemoryStore()
    memory = SemanticPlanMemory(store, "episode-a", 3600)
    space = setup(); tool, _ = registry(space)
    first = run_semantic_plans(space, tool, plan_memory=memory)
    assert first["success"]
    options = {}
    if change == "source_snapshot":
        space = setup(version="toy-v2")
    elif change == "meaning":
        space = replace(space, candidates=tuple(replace(c, semantic_equivalence_key="new meaning")
                                               for c in space.candidates))
    elif change == "replicas":
        space = setup(replicas=("rdf_a",))
    elif change == "cost":
        options["bandwidth_bytes_per_ms"] = 42
    elif change == "episode":
        memory = SemanticPlanMemory(store, "episode-b", 3600)
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, plan_memory=memory, **options)
    assert result["success"] and result["memory"]["state"] == "miss_stored"
    assert result["memory"]["key"] != first["memory"]["key"]
    assert result["observation_calls"] == len(space.observation_requests)
    assert len(calls) == result["observation_calls"] + result["execution_calls"]


def test_expired_observations_are_not_reused():
    now = [100.0]
    clock = lambda: now[0]
    store = InMemoryStore(clock=clock)
    memory = SemanticPlanMemory(store, "episode", 10, clock=clock)
    first, _ = question_run(CASES[0], plan_memory=memory)
    assert first["success"]
    now[0] = 110.0
    again, calls = question_run(CASES[0], plan_memory=memory)
    assert again["success"] and not planning(again)["snapshot_reused"]
    assert len(calls) == 6


def test_shorter_reader_age_does_not_extend_the_original_observation():
    now = [100.0]; clock = lambda: now[0]
    store = InMemoryStore(clock=clock)
    first, _ = question_run(CASES[0], plan_memory=SemanticPlanMemory(store, "episode", 100, clock))
    assert first["success"]
    now[0] = 111.0
    second, calls = question_run(CASES[0], plan_memory=SemanticPlanMemory(store, "episode", 10, clock))
    assert second["success"] and planning(second)["memory"]["state"] == "expired_stored"
    assert len(calls) == 6


@pytest.mark.parametrize("conflict", ["static", "snapshot"])
def test_conflicting_modes_stop_before_backend_actions(conflict):
    space = setup(); tool, calls = registry(space)
    options = ({"static_backend_order": ("rdf_a", "rdf_b")} if conflict == "static" else
               {"snapshot": controlled_snapshot(space, {"paths": "rdf_a", "people": "rdf_b"})})
    result = run_semantic_plans(space, tool, plan_memory=SemanticPlanMemory(InMemoryStore(), "db", 30), **options)
    assert not result["success"] and result["total_remote_calls"] == 0 and not calls


def test_corrupt_memory_fails_without_external_reacquisition():
    store = InMemoryStore(); memory = SemanticPlanMemory(store, "db", 30)
    first, _ = question_run(CASES[0], plan_memory=memory)
    assert first["success"]
    entry = store.records()[0]
    store.put(replace(entry, version="does-not-match-snapshot"))
    result, calls = question_run(CASES[0], plan_memory=memory)
    assert not result["success"] and not calls


def test_failed_acquisition_does_not_create_a_memory_entry():
    space = setup(); tool, calls = registry(space, fail=True)
    store = InMemoryStore()
    result = run_semantic_plans(space, tool, plan_memory=SemanticPlanMemory(store, "db", 30))
    assert not result["success"] and len(calls) == result["total_remote_calls"] == 1
    assert result["observation"]["attempted_calls"] == 1 and result["execution"] is None
    assert not store.records()


def test_failed_warm_execution_keeps_historical_cost_and_never_falls_back():
    space = setup(); tool, _ = registry(space)
    memory = SemanticPlanMemory(InMemoryStore(), "db", 30)
    cold = run_semantic_plans(space, tool, plan_memory=memory)
    assert cold["success"]
    broken, calls = registry(space, fail=True)
    result = run_semantic_plans(space, broken, plan_memory=memory)
    assert not result["success"] and result["memory"]["state"] == "hit"
    assert result["observation_calls"] == 0 and result["automatic_retries"] == 0
    assert result["total_remote_calls"] == len(calls) <= 2
    assert result["memory"]["historical_acquisition"]["remote_calls"] == 4


def test_failed_persistence_preserves_already_consumed_backend_calls():
    class BrokenStore(InMemoryStore):
        def put(self, record):
            raise OSError("controlled disk write failure")
    space = setup(); tool, calls = registry(space)
    result = run_semantic_plans(space, tool, plan_memory=SemanticPlanMemory(BrokenStore(), "db", 30))
    assert not result["success"] and result["total_remote_calls"] == len(calls) == 4
    assert result["execution"] is None and result["memory"]["writes"] == 0


@pytest.mark.parametrize("age", [0, -1, float("nan"), float("inf"), True])
def test_memory_requires_a_finite_age(age):
    with pytest.raises(ValueError):
        SemanticPlanMemory(InMemoryStore(), "db", age)
