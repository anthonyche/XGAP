"""Freeze the result-blind F2C13 paired physical-selection protocol.

The compiler combines the previously frozen family-memory training schedule
with the current-query dual-profile acquisition and shadow schedules.  It
binds both primary methods to the same held-out semantic tasks and one future
allocation, but performs no backend calls and opens no answer oracle.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_current_query_profile_baseline import (
    compile_m15_current_query_profile_baseline_schedule,
)
from xgap.experiments.m15_direct_family_pilot import (
    compile_m15_direct_family_pilot_schedule,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)


PAIRED_PHYSICAL_PROTOCOL_SCHEMA_VERSION = (
    "m15-f2c13-paired-physical-comparison-protocol-v1"
)
PAIRED_PHYSICAL_SCHEDULE_SCHEMA_VERSION = (
    "m15-f2c13-paired-physical-comparison-schedule-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_METHODS = ("family_memory", "current_query_dual_profile")
_CONTROLS = (
    "fixed_parallel_hash",
    "fixed_risk_first_bind",
    "observed_oracle_upper_bound",
)
_PHASE_ORDER = (
    "schedule_seal",
    "training_measurement",
    "family_memory_selection_seal",
    "current_query_profile_acquisition",
    "current_query_profile_selection_seal",
    "paired_selected_execution",
    "postselection_shadow_evaluation",
    "analysis",
)
_RESEARCH_QUESTION = (
    "Within one allocation and one held-out semantic task, how does sealed "
    "family-memory physical selection with zero current-query profiling compare "
    "with dual-current-query profiling when acquisition, training, serving, and "
    "evaluation costs are reported separately?"
)


class M15PairedPhysicalComparisonError(ValueError):
    """Raised when the paired protocol or a source schedule drifts."""


@dataclass(frozen=True)
class M15PairedPhysicalComparisonSchedule:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def schedule_hash(self) -> str:
        return str(self.payload["schedule_sha256"])


def _json_object(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise M15PairedPhysicalComparisonError(
            "paired protocol must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15PairedPhysicalComparisonError("paired protocol must be an object")
    return dict(payload)


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15PairedPhysicalComparisonError(f"{name} is not a safe identifier")
    return value


def _validate_protocol(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    protocol = _json_object(value)
    fields = {
        "schema_version",
        "protocol_id",
        "development_population_id",
        "research_question",
        "source_contracts",
        "phase_order",
        "methods",
        "scope",
        "selection_boundaries",
        "selected_execution",
        "cost_accounting",
        "execution",
        "analysis",
        "input_boundary",
        "expected_counts",
        "claim_boundary",
        "paper_result",
    }
    if set(protocol) != fields:
        raise M15PairedPhysicalComparisonError("paired protocol fields changed")
    if protocol["schema_version"] != PAIRED_PHYSICAL_PROTOCOL_SCHEMA_VERSION:
        raise M15PairedPhysicalComparisonError("paired protocol is unsupported")
    _safe_id(protocol["protocol_id"], name="protocol_id")
    _safe_id(protocol["development_population_id"], name="population_id")
    if protocol["research_question"] != _RESEARCH_QUESTION:
        raise M15PairedPhysicalComparisonError("research question changed")
    if tuple(protocol["phase_order"]) != _PHASE_ORDER:
        raise M15PairedPhysicalComparisonError("paired phase order changed")

    frozen = {
        "source_contracts": {
            "family_protocol_sha256": (
                "b30cf4ee308adf4cae04b07a23e12480839c7ac33651e6403dc0befa1517e2fa"
            ),
            "family_predictor_sha256": (
                "ee4c4ab09aaf86d06784a928e0a52ffa99d6de53f233440a3573976e96baf89b"
            ),
            "profile_protocol_sha256": (
                "fe6c64f82fd6588f257f4bdd496c6a6ce67c6ca4b085f4aba42f89da3b0dc496"
            ),
        },
        "methods": {
            "primary": list(_METHODS),
            "evaluation_only_controls": list(_CONTROLS),
        },
        "scope": {
            "training_semantic_task_count": 18,
            "training_physical_plan_count": 36,
            "training_repetitions_per_plan": 4,
            "heldout_base_query_count": 2,
            "heldout_semantic_task_count": 10,
            "heldout_physical_plan_count": 20,
            "shadow_repetitions_per_plan": 4,
        },
        "selection_boundaries": {
            "family_memory_input": "sealed_training_family_memory_only",
            "family_selection_sealed_before_current_query_profile_acquisition": True,
            "profile_input": "sealed_current_query_profile_costs_only",
            "profile_selection_sealed_before_selected_execution": True,
            "answer_oracle_opened_before_both_selection_seals": False,
            "selected_or_shadow_measurements_used_for_selection": False,
            "selection_scope": "within_one_semantic_class",
        },
        "selected_execution": {
            "methods": list(_METHODS),
            "repetitions_per_method_task": 1,
            "task_order": "sha256_seeded",
            "method_order": "per_task_ab_ba_counterbalanced",
            "schedule_seed": "m15-f2c13-paired-selected-execution-v1",
            "execute_duplicate_choice_per_method": True,
        },
        "cost_accounting": {
            "historical_training_cost_reported_separately": True,
            "profile_acquisition_cost_reported_separately": True,
            "selected_execution_cost_reported_per_method": True,
            "shadow_cost_excluded_from_method_cost": True,
            "training_cost_not_silently_amortized": True,
            "count_based_training_break_even_future_tasks": 72,
            "lifecycle_break_even_descriptive_only": True,
        },
        "execution": {
            "backend_timeout_seconds": 60,
            "slurm_timeout_minutes": 45,
            "remote_calls_per_plan": 2,
            "failure_policy": "stop_on_first_failure",
            "automatic_retries": 0,
        },
        "analysis": {
            "per_plan_aggregation": "median_over_four_shadow_repetitions",
            "observed_physical_winner_order": [
                "median_elapsed_ms",
                "median_total_bytes_moved",
                "plan_id",
            ],
            "metrics": [
                "physical_winner_accuracy",
                "selected_plan_latency_regret_ms",
                "selected_plan_bytes_regret",
                "paired_profile_minus_memory_latency_regret_ms",
                "paired_profile_minus_memory_bytes_regret",
                "current_query_acquisition_latency_ms",
                "current_query_acquisition_bytes",
                "selected_execution_latency_ms",
                "selected_execution_bytes",
                "historical_training_latency_ms",
                "historical_training_bytes",
                "count_based_training_break_even_future_tasks",
            ],
            "paired_unit": "heldout_semantic_task",
            "confirmatory_statistics": False,
        },
        "input_boundary": {
            "family_memory_current_query_profile_operations_per_task": 0,
            "profile_method_current_query_profile_operations_per_task": 2,
            "current_query_sample_operations_per_task": 0,
            "current_query_explain_operations_per_task": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
            "cross_method_selection_leakage_allowed": False,
        },
        "expected_counts": {
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
        },
        "claim_boundary": {
            "physical_selection_within_semantic_class_only": True,
            "semantic_frontier_quality_claim": False,
            "development_protocol_only": True,
            "confirmatory_statistics": False,
            "live_execution_authorized": False,
            "paper_result": False,
        },
    }
    for field, expected in frozen.items():
        if protocol[field] != expected:
            raise M15PairedPhysicalComparisonError(
                f"paired {field.replace('_', ' ')} changed"
            )
    if protocol["paper_result"] is not False:
        raise M15PairedPhysicalComparisonError(
            "development paired protocol cannot be a paper result"
        )
    return protocol


def _heldout_tasks(
    workload: M15DirectSemanticWorkloadBundle,
) -> dict[str, dict[str, Any]]:
    raw = workload.heldout_selection_view.get("semantic_tasks")
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise M15PairedPhysicalComparisonError("held-out semantic tasks are invalid")
    tasks = {
        str(item["semantic_task_id"]): copy.deepcopy(dict(item)) for item in raw
    }
    if len(tasks) != len(raw):
        raise M15PairedPhysicalComparisonError("held-out task IDs are not unique")
    return tasks


def _family_selection_slots(
    tasks: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for index, task_id in enumerate(sorted(tasks), start=1):
        task = tasks[task_id]
        candidates = sorted(
            task["physical_candidates"], key=lambda item: item["plan_id"]
        )
        body = {
            "slot_id": f"family-memory-select-{index:02d}",
            "semantic_task_id": task_id,
            "semantic_class_id": task["semantic_class_id"],
            "candidate_plan_ids": [item["plan_id"] for item in candidates],
            "selection_input": "sealed_training_family_memory_only",
            "current_query_profile_operations": 0,
        }
        slots.append({**body, "slot_sha256": content_hash(body)})
    return slots


def _ordered_tasks(tasks: Mapping[str, Mapping[str, Any]], seed: str) -> list[str]:
    return sorted(
        tasks,
        key=lambda task_id: (
            hashlib.sha256(f"{seed}:{task_id}".encode("utf-8")).hexdigest(),
            task_id,
        ),
    )


def _paired_execution_slots(
    tasks: Mapping[str, Mapping[str, Any]], *, seed: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    orders: dict[str, list[str]] = {}
    for task_position, task_id in enumerate(_ordered_tasks(tasks, seed), start=1):
        task = tasks[task_id]
        methods = _METHODS if task_position % 2 else tuple(reversed(_METHODS))
        orders[task_id] = list(methods)
        for method_position, method_id in enumerate(methods, start=1):
            binding = (
                "resolved_from_sealed_family_memory_selection"
                if method_id == "family_memory"
                else "resolved_from_sealed_current_query_profile_selection"
            )
            body = {
                "slot_id": f"paired-selected-t{task_position:02d}-m{method_position}",
                "phase": "paired_selected_execution",
                "task_order_position": task_position,
                "method_order_position": method_position,
                "base_query_id": task["base_query_id"],
                "query_id": task["executable_query_id"],
                "semantic_task_id": task_id,
                "semantic_class_id": task["semantic_class_id"],
                "method_id": method_id,
                "plan_binding": binding,
                "execute_even_if_methods_choose_same_plan": True,
            }
            slots.append({**body, "slot_sha256": content_hash(body)})
    memory_profile = sum(order == list(_METHODS) for order in orders.values())
    profile_memory = len(orders) - memory_profile
    proof = {
        "task_count": len(tasks),
        "method_order_counts": {
            "family_memory_then_profile": memory_profile,
            "profile_then_family_memory": profile_memory,
        },
        "each_task_has_both_methods": all(
            set(order) == set(_METHODS) for order in orders.values()
        ),
        "passed": memory_profile == profile_memory == 5,
    }
    return slots, proof


def compile_m15_paired_physical_comparison_schedule(
    *,
    workload: M15DirectSemanticWorkloadBundle,
    protocol: Mapping[str, Any] | str | Path,
    family_protocol: Mapping[str, Any] | str | Path,
    predictor_policy: Mapping[str, Any] | str | Path,
    profile_protocol: Mapping[str, Any] | str | Path,
) -> M15PairedPhysicalComparisonSchedule:
    """Compose a same-allocation paired schedule without making calls."""

    selected = _validate_protocol(protocol)
    family = compile_m15_direct_family_pilot_schedule(
        workload=workload,
        protocol=family_protocol,
        predictor_policy=predictor_policy,
    ).to_dict()
    profile = compile_m15_current_query_profile_baseline_schedule(
        workload=workload,
        protocol=profile_protocol,
    ).to_dict()
    if (
        family["development_population_id"] != selected["development_population_id"]
        or profile["development_population_id"] != selected["development_population_id"]
        or family["direct_semantic_workload_sha256"]
        != profile["direct_semantic_workload_sha256"]
        or family["heldout_selection_view_sha256"]
        != profile["heldout_selection_view_sha256"]
    ):
        raise M15PairedPhysicalComparisonError("source schedule population drifted")
    actual_source_contracts = {
        "family_protocol_sha256": family["protocol_sha256"],
        "family_predictor_sha256": family["predictor_policy_sha256"],
        "profile_protocol_sha256": profile["protocol_sha256"],
    }
    if actual_source_contracts != selected["source_contracts"]:
        raise M15PairedPhysicalComparisonError("source contract hash drifted")

    tasks = _heldout_tasks(workload)
    family_slots = _family_selection_slots(tasks)
    paired_slots, method_proof = _paired_execution_slots(
        tasks,
        seed=selected["selected_execution"]["schedule_seed"],
    )
    training_runs = copy.deepcopy(family["training_runs"])
    acquisition_runs = copy.deepcopy(profile["acquisition_runs"])
    profile_slots = copy.deepcopy(profile["selection_slots"])
    shadow_runs = copy.deepcopy(profile["shadow_runs"])
    calls = selected["execution"]["remote_calls_per_plan"]
    counts = {
        "training_plan_runs": len(training_runs),
        "profile_acquisition_plan_runs": len(acquisition_runs),
        "paired_selected_plan_runs": len(paired_slots),
        "evaluation_shadow_plan_runs": len(shadow_runs),
        "total_plan_runs": (
            len(training_runs)
            + len(acquisition_runs)
            + len(paired_slots)
            + len(shadow_runs)
        ),
        "training_backend_calls": len(training_runs) * calls,
        "profile_acquisition_backend_calls": len(acquisition_runs) * calls,
        "paired_selected_backend_calls": len(paired_slots) * calls,
        "evaluation_shadow_backend_calls": len(shadow_runs) * calls,
        "total_backend_calls": (
            len(training_runs)
            + len(acquisition_runs)
            + len(paired_slots)
            + len(shadow_runs)
        )
        * calls,
    }
    if counts != selected["expected_counts"]:
        raise M15PairedPhysicalComparisonError("compiled paired counts changed")
    if not method_proof["passed"]:
        raise M15PairedPhysicalComparisonError("paired method counterbalance failed")

    body = {
        "schema_version": PAIRED_PHYSICAL_SCHEDULE_SCHEMA_VERSION,
        "protocol_id": selected["protocol_id"],
        "protocol_sha256": content_hash(selected),
        "development_population_id": selected["development_population_id"],
        "research_question": selected["research_question"],
        "direct_semantic_workload_sha256": family["direct_semantic_workload_sha256"],
        "training_selection_view_sha256": family["training_selection_view_sha256"],
        "heldout_selection_view_sha256": family["heldout_selection_view_sha256"],
        "predictor_policy_sha256": family["predictor_policy_sha256"],
        "source_schedule_hashes": {
            "family_memory": family["schedule_sha256"],
            "current_query_dual_profile": profile["schedule_sha256"],
        },
        "source_contracts": actual_source_contracts,
        "phase_order": list(_PHASE_ORDER),
        "training_runs": training_runs,
        "family_memory_selection_slots": family_slots,
        "profile_acquisition_runs": acquisition_runs,
        "profile_selection_slots": profile_slots,
        "paired_selected_execution_slots": paired_slots,
        "shadow_runs": shadow_runs,
        "counts": counts,
        "balance_proof": {
            "training": copy.deepcopy(family["balance_proof"]["training"]),
            "profile_acquisition": copy.deepcopy(profile["balance_proof"]["acquisition"]),
            "selected_method_order": method_proof,
            "shadow": copy.deepcopy(profile["balance_proof"]["shadow"]),
            "passed": True,
        },
        "selection_boundaries": copy.deepcopy(selected["selection_boundaries"]),
        "cost_accounting": copy.deepcopy(selected["cost_accounting"]),
        "execution_protocol": copy.deepcopy(selected["execution"]),
        "analysis_protocol": copy.deepcopy(selected["analysis"]),
        "input_boundary": copy.deepcopy(selected["input_boundary"]),
        "claim_boundary": copy.deepcopy(selected["claim_boundary"]),
        "external_calls_made": 0,
        "contains_measurements": False,
        "automatic_retries": 0,
        "live_execution_authorized": False,
        "paper_result": False,
    }
    return M15PairedPhysicalComparisonSchedule(
        {**body, "schedule_sha256": content_hash(body)}
    )
