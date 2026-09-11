"""Same meaning, optional physical selection, and cost-inclusive call accounting."""

from dataclasses import replace
import json

import pytest

from test_semantic_planning import CASES, setup, registry, controlled_snapshot
from test_question_interpretation import CASES as QUESTIONS, question_run
from xgap.runtime.semantic_planning import run_semantic_plans, select_static_semantic_plan


def canonical(rows):
    return sorted(json.dumps(row, sort_keys=True) for row in rows)


@pytest.mark.parametrize("order", [("rdf_a", "rdf_b"), ("rdf_b", "rdf_a")])
@pytest.mark.parametrize("case", CASES, ids=lambda c:c["id"])
def test_static_compositions_keep_gold_with_no_planning_observations(case, order):
    space = setup(case)
    original = [c.plan.to_dict() for c in space.candidates]
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, static_backend_order=order)
    assert result["success"], result
    actual = result["execution"]["value"]["final_rows"]
    assert (actual == case["expected_rows"] if case["ordered"] else
            canonical(actual) == canonical(case["expected_rows"]))
    assert set(result["selected_plan"]["metadata"]["source_bindings"].values()) == {order[0]}
    assert result["observation"] is None and result["observation_calls"] == 0
    assert result["selection"]["estimates"] is None and result["snapshot_reused"] is False
    assert result["total_remote_calls"] == result["execution_calls"] == len(calls) == case["expected_remote_calls"]
    assert original == [c.plan.to_dict() for c in space.candidates]
    assert result["end_to_end_ms"] >= result["planning_ms"] >= result["enumeration_ms"]


@pytest.mark.parametrize("order", [("rdf_a", "rdf_b"), ("rdf_b", "rdf_a")])
@pytest.mark.parametrize("case", QUESTIONS, ids=lambda c:c["id"])
def test_question_entry_uses_same_interpretation_binding_and_executor(case, order):
    result, calls = question_run(case, static_backend_order=order)
    assert result["success"], result
    output = result["state"]["output"]
    run = output["planning_run"]
    assert canonical(run["execution"]["value"]["final_rows"]) == canonical(case["expected_rows"])
    assert {h:v["value"] for h,v in output["bindings"].items()} == case["expected_bindings"]
    assert run["selection_policy"] == "static_backend_order"
    assert run["observation_calls"] == 0
    assert run["execution_calls"] == result["backend_remote_calls"] == len(calls)


def test_same_meaning_comparison_counts_the_default_acquisition_cost():
    costed, cost_calls = question_run(QUESTIONS[0])
    static, static_calls = question_run(QUESTIONS[0], static_backend_order=("rdf_a", "rdf_b"))
    c, s = costed["state"]["output"], static["state"]["output"]
    assert costed["success"] and static["success"]
    assert c["bound_program"] == s["bound_program"]
    assert c["planning_run"]["local_option_count"] == s["planning_run"]["local_option_count"] == 4
    assert c["planning_run"]["possible_placement_count"] == s["planning_run"]["possible_placement_count"] == 4
    assert s["planning_run"]["candidate_count"] == 1
    assert c["planning_run"]["observation_calls"] == 4
    assert s["planning_run"]["observation_calls"] == 0
    assert len(cost_calls) == 6 and len(static_calls) == 2
    assert costed["backend_remote_calls"] == 6 and static["backend_remote_calls"] == 2


def test_static_selection_cannot_read_costs_or_observe_backends(monkeypatch):
    import xgap.runtime.semantic_planning as module
    def forbidden(*args, **kwargs):
        raise AssertionError("Static baseline accessed cost selection or observations")
    monkeypatch.setattr(module, "PlanObservationCollector", forbidden)
    monkeypatch.setattr(module.FederatedPlanSelector, "select", forbidden)
    space = setup()
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, static_backend_order=("rdf_b", "rdf_a"))
    assert result["success"] and len(calls) == 2


@pytest.mark.parametrize("order", [(), ("rdf_a",), ("rdf_a", "rdf_a"), ["rdf_a", "rdf_b"]])
def test_invalid_static_policy_is_terminal_before_dispatch(order):
    space = setup()
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, static_backend_order=order)
    assert not result["success"] and result["selection"] is None
    assert result["total_remote_calls"] == 0 and calls == []


def test_static_and_snapshot_inputs_do_not_silently_override_each_other():
    space = setup()
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, static_backend_order=("rdf_a", "rdf_b"),
        snapshot=controlled_snapshot(space, {"paths":"rdf_b", "people":"rdf_b"}))
    assert not result["success"] and result["total_remote_calls"] == 0 and calls == []
    assert result["snapshot_reused"] is False


def test_static_selection_respects_compiler_admission_and_is_order_invariant():
    space = setup()
    admitted = tuple(c for c in space.candidates
                     if c.plan.metadata["source_bindings"] == {"paths":"rdf_b", "people":"rdf_a"})
    # A deployment with only this admitted combination cannot invent replicas.
    constrained = replace(space, candidates=admitted)
    tool, calls = registry(constrained)
    result = run_semantic_plans(constrained, tool, static_backend_order=("rdf_a", "rdf_b"))
    assert result["success"] and len(calls) == 2
    assert result["selected_plan"]["metadata"]["source_bindings"] == {"paths":"rdf_b", "people":"rdf_a"}
    assert select_static_semantic_plan(space.candidates, ("rdf_a", "rdf_b")) == \
           select_static_semantic_plan(tuple(reversed(space.candidates)), ("rdf_a", "rdf_b"))


def test_static_policy_does_not_compare_different_meanings():
    space = setup()
    mixed = (space.candidates[0], replace(space.candidates[1], semantic_equivalence_key="another-meaning"))
    tool, calls = registry(space)
    result = run_semantic_plans(replace(space, candidates=mixed), tool, static_backend_order=("rdf_a", "rdf_b"))
    assert not result["success"] and result["total_remote_calls"] == 0 and calls == []


def test_static_execution_failure_does_not_try_another_backend():
    space = setup(CASES[3])
    tool, calls = registry(space, fail=True)
    result = run_semantic_plans(space, tool, static_backend_order=("rdf_a", "rdf_b"))
    assert not result["success"] and result["automatic_retries"] == 0
    assert result["total_remote_calls"] == 1 and len(calls) == 1
    assert calls[0][0] == "rdf_a"
