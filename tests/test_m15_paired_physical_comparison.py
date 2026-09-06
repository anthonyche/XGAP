from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_current_query_profile_baseline import (
    compile_m15_current_query_profile_baseline_schedule,
)
from xgap.experiments.m15_direct_family_pilot import (
    compile_m15_direct_family_pilot_schedule,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_paired_physical_comparison import (
    PAIRED_PHYSICAL_SCHEDULE_SCHEMA_VERSION,
    M15PairedPhysicalComparisonError,
    compile_m15_paired_physical_comparison_schedule,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
PROTOCOL = CONFIGS / "m15_f2c13_paired_physical_comparison_dev.json"
FAMILY_PROTOCOL = CONFIGS / "m15_f2c10d_family_memory_pilot_dev.json"
PREDICTOR = CONFIGS / "m15_f2c10_family_memory_predictor_dev.json"
PROFILE_PROTOCOL = CONFIGS / "m15_f2c12_current_query_profile_baseline_dev.json"


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


def _compile(tmp_path: Path, protocol=PROTOCOL):
    return compile_m15_paired_physical_comparison_schedule(
        workload=_workload(tmp_path),
        protocol=protocol,
        family_protocol=FAMILY_PROTOCOL,
        predictor_policy=PREDICTOR,
        profile_protocol=PROFILE_PROTOCOL,
    )


def test_schedule_freezes_same_allocation_paired_counts(tmp_path: Path) -> None:
    schedule = _compile(tmp_path).to_dict()

    assert schedule["schema_version"] == PAIRED_PHYSICAL_SCHEDULE_SCHEMA_VERSION
    assert schedule["counts"] == {
        "training_plan_runs": 144,
        "profile_acquisition_plan_runs": 20,
        "paired_selected_plan_runs": 20,
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 264,
        "training_backend_calls": 288,
        "profile_acquisition_backend_calls": 40,
        "paired_selected_backend_calls": 40,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 528,
    }
    assert len(schedule["training_runs"]) == 144
    assert len(schedule["family_memory_selection_slots"]) == 10
    assert len(schedule["profile_acquisition_runs"]) == 20
    assert len(schedule["profile_selection_slots"]) == 10
    assert len(schedule["paired_selected_execution_slots"]) == 20
    assert len(schedule["shadow_runs"]) == 80
    assert schedule["external_calls_made"] == 0
    assert schedule["contains_measurements"] is False
    assert schedule["live_execution_authorized"] is False
    assert schedule["paper_result"] is False


def test_family_seal_precedes_profile_and_both_are_result_blind(
    tmp_path: Path,
) -> None:
    schedule = _compile(tmp_path).to_dict()
    boundary = schedule["selection_boundaries"]

    assert boundary["family_memory_input"] == "sealed_training_family_memory_only"
    assert (
        boundary["family_selection_sealed_before_current_query_profile_acquisition"]
        is True
    )
    assert boundary["profile_input"] == "sealed_current_query_profile_costs_only"
    assert boundary["answer_oracle_opened_before_both_selection_seals"] is False
    assert boundary["selected_or_shadow_measurements_used_for_selection"] is False
    assert schedule["input_boundary"] == {
        "family_memory_current_query_profile_operations_per_task": 0,
        "profile_method_current_query_profile_operations_per_task": 2,
        "current_query_sample_operations_per_task": 0,
        "current_query_explain_operations_per_task": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "cross_method_selection_leakage_allowed": False,
    }
    assert all(
        slot["current_query_profile_operations"] == 0
        for slot in schedule["family_memory_selection_slots"]
    )


def test_selected_execution_is_task_paired_and_counterbalanced(
    tmp_path: Path,
) -> None:
    schedule = _compile(tmp_path).to_dict()
    slots = schedule["paired_selected_execution_slots"]
    proof = schedule["balance_proof"]["selected_method_order"]

    assert proof == {
        "task_count": 10,
        "method_order_counts": {
            "family_memory_then_profile": 5,
            "profile_then_family_memory": 5,
        },
        "each_task_has_both_methods": True,
        "passed": True,
    }
    task_ids = {slot["semantic_task_id"] for slot in slots}
    assert len(task_ids) == 10
    for task_id in task_ids:
        selected = [slot for slot in slots if slot["semantic_task_id"] == task_id]
        assert len(selected) == 2
        assert {slot["method_id"] for slot in selected} == {
            "family_memory",
            "current_query_dual_profile",
        }
        assert all(slot["execute_even_if_methods_choose_same_plan"] for slot in selected)
    assert len({slot["slot_sha256"] for slot in slots}) == 20


def test_source_training_acquisition_and_shadow_schedules_are_reused_exactly(
    tmp_path: Path,
) -> None:
    workload = _workload(tmp_path)
    paired = compile_m15_paired_physical_comparison_schedule(
        workload=workload,
        protocol=PROTOCOL,
        family_protocol=FAMILY_PROTOCOL,
        predictor_policy=PREDICTOR,
        profile_protocol=PROFILE_PROTOCOL,
    ).to_dict()
    family = compile_m15_direct_family_pilot_schedule(
        workload=workload,
        protocol=FAMILY_PROTOCOL,
        predictor_policy=PREDICTOR,
    ).to_dict()
    profile = compile_m15_current_query_profile_baseline_schedule(
        workload=workload,
        protocol=PROFILE_PROTOCOL,
    ).to_dict()

    assert paired["training_runs"] == family["training_runs"]
    assert paired["profile_acquisition_runs"] == profile["acquisition_runs"]
    assert paired["profile_selection_slots"] == profile["selection_slots"]
    assert paired["shadow_runs"] == profile["shadow_runs"]
    assert paired["source_schedule_hashes"] == {
        "family_memory": family["schedule_sha256"],
        "current_query_dual_profile": profile["schedule_sha256"],
    }
    assert paired["source_contracts"] == {
        "family_protocol_sha256": family["protocol_sha256"],
        "family_predictor_sha256": family["predictor_policy_sha256"],
        "profile_protocol_sha256": profile["protocol_sha256"],
    }


def test_source_protocol_drift_fails_even_when_composed_counts_match(
    tmp_path: Path,
) -> None:
    family_protocol = json.loads(FAMILY_PROTOCOL.read_text(encoding="utf-8"))
    family_protocol["selection"]["online_cardinality"] = {
        "mode": "exact_total",
        "minimum_total": 4,
        "maximum_total": 4,
        "maximum_per_query": 4,
    }
    family_protocol["expected_counts"].update(
        {
            "online_selected_plan_runs": {"minimum": 4, "maximum": 4},
            "total_plan_runs": {"minimum": 228, "maximum": 228},
            "total_backend_calls": {"minimum": 456, "maximum": 456},
        }
    )

    with pytest.raises(M15PairedPhysicalComparisonError, match="source contract"):
        compile_m15_paired_physical_comparison_schedule(
            workload=_workload(tmp_path),
            protocol=PROTOCOL,
            family_protocol=family_protocol,
            predictor_policy=PREDICTOR,
            profile_protocol=PROFILE_PROTOCOL,
        )


def test_cost_scopes_and_claim_boundary_are_explicit(tmp_path: Path) -> None:
    schedule = _compile(tmp_path).to_dict()

    assert schedule["cost_accounting"] == {
        "historical_training_cost_reported_separately": True,
        "profile_acquisition_cost_reported_separately": True,
        "selected_execution_cost_reported_per_method": True,
        "shadow_cost_excluded_from_method_cost": True,
        "training_cost_not_silently_amortized": True,
        "count_based_training_break_even_future_tasks": 72,
        "lifecycle_break_even_descriptive_only": True,
    }
    assert schedule["claim_boundary"] == {
        "physical_selection_within_semantic_class_only": True,
        "semantic_frontier_quality_claim": False,
        "development_protocol_only": True,
        "confirmatory_statistics": False,
        "live_execution_authorized": False,
        "paper_result": False,
    }


def test_schedule_is_deterministic_and_input_is_not_mutated(tmp_path: Path) -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    before = copy.deepcopy(protocol)
    first = _compile(tmp_path / "first", protocol).to_dict()
    second = _compile(tmp_path / "second", protocol).to_dict()

    assert first == second
    assert protocol == before


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["selection_boundaries"].__setitem__(
                "family_selection_sealed_before_current_query_profile_acquisition",
                False,
            ),
            "selection boundaries",
        ),
        (
            lambda value: value["input_boundary"].__setitem__(
                "family_memory_current_query_profile_operations_per_task", 1
            ),
            "input boundary",
        ),
        (
            lambda value: value["execution"].__setitem__("automatic_retries", 1),
            "execution",
        ),
        (
            lambda value: value["expected_counts"].__setitem__(
                "total_backend_calls", 526
            ),
            "expected counts",
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
    with pytest.raises(M15PairedPhysicalComparisonError, match=message):
        _compile(tmp_path, protocol)
