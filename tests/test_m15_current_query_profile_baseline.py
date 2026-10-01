from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_current_query_profile_baseline import (
    CURRENT_QUERY_PROFILE_SCHEDULE_SCHEMA_VERSION,
    M15CurrentQueryProfileBaselineError,
    compile_m15_current_query_profile_baseline_schedule,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
PROTOCOL = CONFIGS / "m15_f2c12_current_query_profile_baseline_dev.json"


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
    return compile_m15_current_query_profile_baseline_schedule(
        workload=_workload(tmp_path), protocol=PROTOCOL
    )


def test_schedule_freezes_profile_acquisition_and_all_costs(tmp_path: Path) -> None:
    schedule = _compile(tmp_path).to_dict()

    assert schedule["schema_version"] == CURRENT_QUERY_PROFILE_SCHEDULE_SCHEMA_VERSION
    assert schedule["counts"] == {
        "acquisition_plan_runs": 20,
        "selected_plan_runs": 10,
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 110,
        "acquisition_backend_calls": 40,
        "selected_plan_backend_calls": 20,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 220,
    }
    assert len(schedule["acquisition_runs"]) == 20
    assert len(schedule["selection_slots"]) == 10
    assert len(schedule["selected_execution_slots"]) == 10
    assert len(schedule["shadow_runs"]) == 80
    assert schedule["cost_accounting"] == {
        "method_latency": (
            "sum_acquisition_elapsed_ms_plus_selected_execution_elapsed_ms"
        ),
        "method_bytes": "sum_acquisition_bytes_plus_selected_execution_bytes",
        "shadow_cost_excluded_from_method_cost": True,
        "acquisition_cost_reported_separately": True,
    }
    assert schedule["external_calls_made"] == 0
    assert schedule["contains_measurements"] is False
    assert schedule["live_execution_authorized"] is False
    assert schedule["paper_result"] is False


def test_profile_selection_is_cost_only_and_result_blind(tmp_path: Path) -> None:
    schedule = _compile(tmp_path).to_dict()

    assert schedule["selection_boundary"] == {
        "candidate_set_sealed_before_profile_calls": True,
        "profile_costs_sealed_before_selected_execution": True,
        "selection_fields": ["elapsed_ms", "total_bytes_moved", "plan_id"],
        "answer_rows_selection_input": False,
        "answer_oracle_opened_before_selection_seal": False,
        "online_or_shadow_measurements_used_for_selection": False,
        "selection_scope": "within_one_semantic_class",
    }
    assert schedule["input_boundary"]["training_memory_allowed"] is False
    assert schedule["input_boundary"]["family_memory_predictions_allowed"] is False
    assert schedule["input_boundary"]["current_query_profile_operations_per_task"] == 2
    assert schedule["input_boundary"]["llm_calls"] == 0
    assert schedule["input_boundary"]["ontology_service_calls"] == 0
    assert schedule["automatic_retries"] == 0


def test_acquisition_and_shadow_orders_are_counterbalanced(tmp_path: Path) -> None:
    schedule = _compile(tmp_path).to_dict()
    acquisition = schedule["acquisition_runs"]
    shadow = schedule["shadow_runs"]

    proof = schedule["balance_proof"]
    assert proof["passed"] is True
    assert proof["acquisition"]["strategy_order_counts"] == {"ab": 5, "ba": 5}
    assert proof["shadow"]["passed"] is True
    assert len({item["run_sha256"] for item in acquisition + shadow}) == 100

    task_ids = {item["semantic_task_id"] for item in acquisition}
    assert len(task_ids) == 10
    for task_id in task_ids:
        acquired = [item for item in acquisition if item["semantic_task_id"] == task_id]
        assert {item["physical_strategy"] for item in acquired} == {
            "parallel_hash_join",
            "risk_first_bind_join",
        }
        evaluated = [item for item in shadow if item["semantic_task_id"] == task_id]
        for strategy in ("parallel_hash_join", "risk_first_bind_join"):
            strategy_runs = [
                item for item in evaluated if item["physical_strategy"] == strategy
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
    changed["acquisition"]["schedule_seed"] = (
        "m15-f2c12-dual-profile-acquisition-v2"
    )
    with pytest.raises(M15CurrentQueryProfileBaselineError, match="acquisition"):
        compile_m15_current_query_profile_baseline_schedule(
            workload=_workload(tmp_path / "changed"), protocol=changed
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["input_boundary"].__setitem__(
                "training_memory_allowed", True
            ),
            "input boundary",
        ),
        (
            lambda value: value["acquisition"].__setitem__(
                "answer_rows_selection_input", True
            ),
            "acquisition",
        ),
        (
            lambda value: value["execution"].__setitem__("automatic_retries", 1),
            "execution",
        ),
        (
            lambda value: value["expected_counts"].__setitem__(
                "total_backend_calls", 218
            ),
            "compiled profile counts",
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
    with pytest.raises(M15CurrentQueryProfileBaselineError, match=message):
        compile_m15_current_query_profile_baseline_schedule(
            workload=_workload(tmp_path), protocol=protocol
        )


def test_protocol_input_is_not_mutated(tmp_path: Path) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    before = copy.deepcopy(protocol)
    compile_m15_current_query_profile_baseline_schedule(
        workload=_workload(tmp_path), protocol=protocol
    )
    assert protocol == before
