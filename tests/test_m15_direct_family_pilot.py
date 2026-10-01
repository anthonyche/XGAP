from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_direct_family_pilot import (
    DIRECT_FAMILY_PILOT_SCHEDULE_SCHEMA_VERSION,
    M15DirectFamilyPilotError,
    compile_m15_direct_family_pilot_schedule,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
PROTOCOL = CONFIGS / "m15_f2c10d_family_memory_pilot_dev.json"
PREDICTOR = CONFIGS / "m15_f2c10_family_memory_predictor_dev.json"


def _workload(tmp_path: Path):
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=CONFIGS / "m15_f2c_parameterized_workload_dev.json",
        query_template_spec=(
            CONFIGS / "m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=tmp_path / "base",
    )
    return generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=CONFIGS / "m15_f2c6_semantic_relaxation_dev.json",
        mapping=CONFIGS / "m15_f2c8_predicate_mapping_dev.json",
        policy=CONFIGS / "m15_f2c10_direct_semantic_workload_dev.json",
        destination=tmp_path / "direct",
    )


def _compile(tmp_path: Path):
    return compile_m15_direct_family_pilot_schedule(
        workload=_workload(tmp_path),
        protocol=PROTOCOL,
        predictor_policy=PREDICTOR,
    )


def test_option_a_schedule_has_bounded_phase_counts_and_boundaries(
    tmp_path: Path,
) -> None:
    schedule = _compile(tmp_path).to_dict()

    assert schedule["schema_version"] == DIRECT_FAMILY_PILOT_SCHEDULE_SCHEMA_VERSION
    assert schedule["counts"] == {
        "training_plan_runs": 144,
        "online_selected_plan_runs": {"minimum": 2, "maximum": 8},
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": {"minimum": 226, "maximum": 232},
        "total_backend_calls": {"minimum": 452, "maximum": 464},
    }
    assert len(schedule["training_runs"]) == 144
    assert len(schedule["online_execution_slots"]) == 8
    assert len(schedule["shadow_runs"]) == 80
    assert schedule["balance_proof"]["passed"] is True
    assert schedule["selection_boundary"] == {
        "current_query_observation_operations": [],
        "selection_sealed_before_online_and_shadow": True,
        "heldout_evaluation_records_opened_only_after_selection": True,
        "training_oracles_used_only_for_postexecution_admission": True,
        "shadow_is_selection_input": False,
        "online_and_shadow_accounted_separately": True,
        "online_cardinality": {
            "mode": "per_query_frontier",
            "minimum_total": 2,
            "maximum_total": 8,
            "maximum_per_query": 4,
        },
    }
    assert schedule["external_calls_made"] == 0
    assert schedule["contains_measurements"] is False
    assert schedule["automatic_retries"] == 0
    assert schedule["paper_result"] is False


def test_training_and_shadow_are_disjoint_complete_and_counterbalanced(
    tmp_path: Path,
) -> None:
    schedule = _compile(tmp_path).to_dict()
    training = schedule["training_runs"]
    shadow = schedule["shadow_runs"]
    training_tasks = {item["semantic_task_id"] for item in training}
    shadow_tasks = {item["semantic_task_id"] for item in shadow}

    assert len(training_tasks) == 18
    assert len(shadow_tasks) == 10
    assert training_tasks.isdisjoint(shadow_tasks)
    assert len({item["run_sha256"] for item in training + shadow}) == 224
    for runs, task_ids in ((training, training_tasks), (shadow, shadow_tasks)):
        for task_id in task_ids:
            selected = [item for item in runs if item["semantic_task_id"] == task_id]
            for strategy in ("parallel_hash_join", "risk_first_bind_join"):
                strategy_runs = [
                    item for item in selected if item["physical_strategy"] == strategy
                ]
                assert len(strategy_runs) == 4
                assert sorted(
                    item["strategy_order_position"] for item in strategy_runs
                ) == [1, 1, 2, 2]


def test_schedule_is_deterministic_and_hash_bound(tmp_path: Path) -> None:
    first = _compile(tmp_path / "first").to_dict()
    second = _compile(tmp_path / "second").to_dict()
    assert first == second

    changed = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    changed["training"]["schedule_seed"] = "m15-f2c10d-option-a-training-v2"
    third = compile_m15_direct_family_pilot_schedule(
        workload=_workload(tmp_path / "third"),
        protocol=changed,
        predictor_policy=PREDICTOR,
    ).to_dict()
    assert third["schedule_sha256"] != first["schedule_sha256"]
    assert third["training_runs"] != first["training_runs"]


def test_compiler_also_supports_an_explicit_exact_total_policy(
    tmp_path: Path,
) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    protocol["selection"]["online_cardinality"] = {
        "mode": "exact_total",
        "minimum_total": 4,
        "maximum_total": 4,
        "maximum_per_query": 4,
    }
    protocol["expected_counts"].update(
        {
            "online_selected_plan_runs": {"minimum": 4, "maximum": 4},
            "total_plan_runs": {"minimum": 228, "maximum": 228},
            "total_backend_calls": {"minimum": 456, "maximum": 456},
        }
    )

    schedule = compile_m15_direct_family_pilot_schedule(
        workload=_workload(tmp_path),
        protocol=protocol,
        predictor_policy=PREDICTOR,
    ).to_dict()

    assert schedule["counts"]["online_selected_plan_runs"] == {
        "minimum": 4,
        "maximum": 4,
    }
    assert len(schedule["online_execution_slots"]) == 4


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["training"].__setitem__(
                "repetitions_per_plan", 2
            ),
            "not option A",
        ),
        (
            lambda value: value["selection"][
                "current_query_observation_operations"
            ].append("profile"),
            "not option A",
        ),
        (
            lambda value: value["execution"].__setitem__(
                "automatic_retries", 1
            ),
            "not option A",
        ),
        (
            lambda value: value["expected_counts"].__setitem__(
                "total_plan_runs", {"minimum": 227, "maximum": 232}
            ),
            "inconsistent",
        ),
        (
            lambda value: value.__setitem__("paper_result", True),
            "cannot be a paper result",
        ),
    ],
)
def test_protocol_drift_fails_closed(
    tmp_path: Path, mutator, message: str
) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    mutator(protocol)
    with pytest.raises(M15DirectFamilyPilotError, match=message):
        compile_m15_direct_family_pilot_schedule(
            workload=_workload(tmp_path),
            protocol=protocol,
            predictor_policy=PREDICTOR,
        )


def test_predictor_cannot_reintroduce_current_query_observations(
    tmp_path: Path,
) -> None:
    predictor = json.loads(PREDICTOR.read_text(encoding="utf-8"))
    predictor["current_query_observation_operations"] = ["profile"]
    with pytest.raises(M15DirectFamilyPilotError, match="current-query"):
        compile_m15_direct_family_pilot_schedule(
            workload=_workload(tmp_path),
            protocol=PROTOCOL,
            predictor_policy=predictor,
        )


def test_protocol_input_is_not_mutated(tmp_path: Path) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    before = copy.deepcopy(protocol)
    compile_m15_direct_family_pilot_schedule(
        workload=_workload(tmp_path),
        protocol=protocol,
        predictor_policy=PREDICTOR,
    )
    assert protocol == before
