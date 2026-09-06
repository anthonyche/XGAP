"""Freeze the F2C12 current-query profiling baseline without making calls.

The protocol is a strong black-box comparison for family memory: for every
held-out semantic class it measures both complete federated physical plans
once, seals a latency-first choice, executes that choice once, and only then
runs counterbalanced evaluation shadows.  This module compiles identities and
budgets; it never opens an answer oracle or invokes a backend.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)


CURRENT_QUERY_PROFILE_PROTOCOL_SCHEMA_VERSION = (
    "m15-f2c12-current-query-profile-baseline-protocol-v1"
)
CURRENT_QUERY_PROFILE_SCHEDULE_SCHEMA_VERSION = (
    "m15-f2c12-current-query-profile-baseline-schedule-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")
_PHASE_ORDER = (
    "candidate_seal",
    "current_query_profile_acquisition",
    "physical_selection_seal",
    "selected_plan_execution",
    "postselection_shadow_evaluation",
    "analysis",
)


class M15CurrentQueryProfileBaselineError(ValueError):
    """Raised when the frozen F2C12 protocol or workload binding drifts."""


@dataclass(frozen=True)
class M15CurrentQueryProfileBaselineSchedule:
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
        raise M15CurrentQueryProfileBaselineError(
            "profile baseline protocol must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15CurrentQueryProfileBaselineError(
            "profile baseline protocol must contain an object"
        )
    return dict(payload)


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15CurrentQueryProfileBaselineError(
            f"{name} is not a safe identifier"
        )
    return value


def _validate_protocol(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    protocol = _json_object(value)
    if set(protocol) != {
        "schema_version",
        "protocol_id",
        "development_population_id",
        "method_id",
        "phase_order",
        "scope",
        "acquisition",
        "selection",
        "online",
        "shadow",
        "cost_accounting",
        "execution",
        "analysis",
        "input_boundary",
        "expected_counts",
        "claim_boundary",
        "paper_result",
    }:
        raise M15CurrentQueryProfileBaselineError("profile protocol fields changed")
    if protocol["schema_version"] != CURRENT_QUERY_PROFILE_PROTOCOL_SCHEMA_VERSION:
        raise M15CurrentQueryProfileBaselineError("profile protocol is unsupported")
    if tuple(protocol["phase_order"]) != _PHASE_ORDER:
        raise M15CurrentQueryProfileBaselineError("profile phase order changed")
    _safe_id(protocol["protocol_id"], name="protocol_id")
    _safe_id(protocol["development_population_id"], name="population_id")
    if protocol["method_id"] != "current_query_dual_profile":
        raise M15CurrentQueryProfileBaselineError("profile method changed")

    expected = {
        "scope": {
            "heldout_base_query_count": 2,
            "heldout_semantic_task_count": 10,
            "physical_candidates_per_task": 2,
            "physical_plan_count": 20,
        },
        "acquisition": {
            "operation": "profile",
            "measurement_implementation": (
                "full_federated_plan_execution_labeled_profile"
            ),
            "repetitions_per_candidate": 1,
            "task_order": "sha256_seeded",
            "strategy_order": "per_task_ab_ba_counterbalanced",
            "schedule_seed": "m15-f2c12-dual-profile-acquisition-v1",
            "selection_fields": [
                "elapsed_ms",
                "total_bytes_moved",
                "plan_id",
            ],
            "answer_rows_selection_input": False,
        },
        "selection": {
            "scope": "within_one_semantic_class",
            "order": [
                "profile_elapsed_ms",
                "profile_total_bytes_moved",
                "plan_id",
            ],
            "selected_plans_per_task": 1,
            "seal_before_selected_execution": True,
            "fallback_allowed": False,
        },
        "online": {
            "repetitions_per_selected_plan": 1,
            "selection_input": False,
            "memory_writes_allowed": False,
        },
        "shadow": {
            "physical_plan_count": 20,
            "repetitions_per_plan": 4,
            "starts_after_selection_seal": True,
            "selection_input": False,
            "memory_writes_allowed": False,
            "task_order": "sha256_seeded_per_block",
            "strategy_order": "per_task_alternating_ab_ba_counterbalanced",
            "schedule_seed": "m15-f2c12-dual-profile-shadow-v1",
        },
        "cost_accounting": {
            "method_latency": (
                "sum_acquisition_elapsed_ms_plus_selected_execution_elapsed_ms"
            ),
            "method_bytes": "sum_acquisition_bytes_plus_selected_execution_bytes",
            "shadow_cost_excluded_from_method_cost": True,
            "acquisition_cost_reported_separately": True,
        },
        "execution": {
            "backend_timeout_seconds": 60,
            "slurm_timeout_minutes": 30,
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
                "acquisition_latency_ms",
                "acquisition_bytes",
                "end_to_end_latency_ms",
                "end_to_end_bytes",
            ],
            "confirmatory_statistics": False,
        },
        "input_boundary": {
            "training_memory_allowed": False,
            "family_memory_predictions_allowed": False,
            "current_query_profile_operations_per_task": 2,
            "current_query_sample_operations_per_task": 0,
            "current_query_explain_operations_per_task": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
            "answer_oracle_opened_before_selection_seal": False,
            "online_or_shadow_measurements_used_for_selection": False,
        },
        "claim_boundary": {
            "development_protocol_only": True,
            "live_execution_authorized": False,
            "comparison_with_prior_allocation_authorized": False,
            "paper_result": False,
        },
    }
    for field, frozen in expected.items():
        if protocol[field] != frozen:
            raise M15CurrentQueryProfileBaselineError(
                f"profile {field.replace('_', ' ')} changed"
            )
    if protocol["paper_result"] is not False:
        raise M15CurrentQueryProfileBaselineError(
            "development profile protocol cannot be a paper result"
        )
    return protocol


def _task_map(view: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = view.get("semantic_tasks")
    if not isinstance(tasks, list):
        raise M15CurrentQueryProfileBaselineError("held-out task list is invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in tasks:
        if not isinstance(item, Mapping):
            raise M15CurrentQueryProfileBaselineError("held-out task is invalid")
        task = copy.deepcopy(dict(item))
        task_id = _safe_id(task.get("semantic_task_id"), name="semantic_task_id")
        candidates = task.get("physical_candidates")
        if task_id in result or not isinstance(candidates, list):
            raise M15CurrentQueryProfileBaselineError(
                "held-out task identity or candidates are invalid"
            )
        if any(not isinstance(candidate, Mapping) for candidate in candidates):
            raise M15CurrentQueryProfileBaselineError(
                "held-out physical candidate is invalid"
            )
        strategies = tuple(
            candidate.get("physical_strategy") for candidate in candidates
        )
        if len(candidates) != 2 or set(strategies) != set(_STRATEGIES):
            raise M15CurrentQueryProfileBaselineError(
                "each semantic task requires both physical strategies"
            )
        result[task_id] = task
    return result


def _ordered_task_ids(task_ids: Sequence[str], *, seed: str) -> list[str]:
    return sorted(
        task_ids,
        key=lambda task_id: (
            hashlib.sha256(f"{seed}:{task_id}".encode("utf-8")).hexdigest(),
            task_id,
        ),
    )


def _candidate(task: Mapping[str, Any], strategy: str) -> Mapping[str, Any]:
    matches = [
        item
        for item in task["physical_candidates"]
        if item["physical_strategy"] == strategy
    ]
    if len(matches) != 1:
        raise M15CurrentQueryProfileBaselineError("candidate strategy is ambiguous")
    return matches[0]


def _run_record(
    *,
    phase: str,
    task: Mapping[str, Any],
    strategy: str,
    task_position: int,
    strategy_position: int,
    block_index: int,
) -> dict[str, Any]:
    candidate = _candidate(task, strategy)
    body = {
        "phase": phase,
        "block_index": block_index,
        "task_position": task_position,
        "strategy_order_position": strategy_position,
        "base_query_id": task["base_query_id"],
        "semantic_task_id": task["semantic_task_id"],
        "semantic_class_id": task["semantic_class_id"],
        "plan_id": candidate["plan_id"],
        "physical_strategy": strategy,
        "semantic_deviation": task["semantic_deviation"],
    }
    return {**body, "run_sha256": content_hash(body)}


def _acquisition_runs(
    tasks: Mapping[str, Mapping[str, Any]], *, seed: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ordered = _ordered_task_ids(tuple(tasks), seed=seed)
    runs: list[dict[str, Any]] = []
    orders: dict[str, list[str]] = {}
    for task_position, task_id in enumerate(ordered, start=1):
        strategies = (
            _STRATEGIES
            if task_position % 2
            else tuple(reversed(_STRATEGIES))
        )
        orders[task_id] = list(strategies)
        for strategy_position, strategy in enumerate(strategies, start=1):
            runs.append(
                _run_record(
                    phase="current_query_profile_acquisition",
                    task=tasks[task_id],
                    strategy=strategy,
                    task_position=task_position,
                    strategy_position=strategy_position,
                    block_index=1,
                )
            )
    counts = {"ab": 0, "ba": 0}
    for order in orders.values():
        counts["ab" if order == list(_STRATEGIES) else "ba"] += 1
    proof = {
        "task_count": len(tasks),
        "strategy_order_counts": counts,
        "each_task_has_both_strategies": all(
            set(order) == set(_STRATEGIES) for order in orders.values()
        ),
        "passed": counts == {"ab": 5, "ba": 5},
    }
    return runs, proof


def _shadow_runs(
    tasks: Mapping[str, Mapping[str, Any]], *, seed: str, repetitions: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    strategy_rank = {
        task_id: index
        for index, task_id in enumerate(
            _ordered_task_ids(tuple(tasks), seed=f"{seed}:strategy-order")
        )
    }
    positions: dict[str, dict[str, list[int]]] = {
        task_id: {strategy: [] for strategy in _STRATEGIES} for task_id in tasks
    }
    for block in range(1, repetitions + 1):
        ordered = _ordered_task_ids(tuple(tasks), seed=f"{seed}:block:{block}")
        for task_position, task_id in enumerate(ordered, start=1):
            # Task order may change per block, but each task's AB/BA sequence
            # must be anchored independently so every strategy occupies each
            # position exactly twice across four repetitions.
            parity = (strategy_rank[task_id] + block) % 2
            strategies = _STRATEGIES if parity == 0 else tuple(reversed(_STRATEGIES))
            for strategy_position, strategy in enumerate(strategies, start=1):
                positions[task_id][strategy].append(strategy_position)
                runs.append(
                    _run_record(
                        phase="postselection_shadow_evaluation",
                        task=tasks[task_id],
                        strategy=strategy,
                        task_position=task_position,
                        strategy_position=strategy_position,
                        block_index=block,
                    )
                )
    passed = all(
        sorted(values) == [1, 1, 2, 2]
        for task in positions.values()
        for values in task.values()
    )
    return runs, {
        "repetitions_per_plan": repetitions,
        "per_task_strategy_positions": positions,
        "passed": passed,
    }


def compile_m15_current_query_profile_baseline_schedule(
    *,
    workload: M15DirectSemanticWorkloadBundle,
    protocol: Mapping[str, Any] | str | Path,
) -> M15CurrentQueryProfileBaselineSchedule:
    """Bind the result-blind F2C12 protocol to the held-out direct workload."""

    selected = _validate_protocol(protocol)
    tasks = _task_map(workload.heldout_selection_view)
    scope = selected["scope"]
    if (
        len(workload.heldout_selection_view.get("base_query_ids", []))
        != scope["heldout_base_query_count"]
        or len(tasks) != scope["heldout_semantic_task_count"]
        or sum(len(item["physical_candidates"]) for item in tasks.values())
        != scope["physical_plan_count"]
    ):
        raise M15CurrentQueryProfileBaselineError(
            "profile protocol does not match the held-out workload"
        )

    acquisition_runs, acquisition_proof = _acquisition_runs(
        tasks, seed=selected["acquisition"]["schedule_seed"]
    )
    shadow_runs, shadow_proof = _shadow_runs(
        tasks,
        seed=selected["shadow"]["schedule_seed"],
        repetitions=selected["shadow"]["repetitions_per_plan"],
    )
    selection_slots = []
    execution_slots = []
    for index, task_id in enumerate(sorted(tasks), start=1):
        task = tasks[task_id]
        candidates = sorted(
            task["physical_candidates"], key=lambda item: item["plan_id"]
        )
        selection_body = {
            "slot_id": f"profile-select-{index:02d}",
            "semantic_task_id": task_id,
            "semantic_class_id": task["semantic_class_id"],
            "candidate_plan_ids": [item["plan_id"] for item in candidates],
            "selection_order": copy.deepcopy(selected["selection"]["order"]),
            "selection_input": "sealed_current_query_profile_costs_only",
        }
        selection_slots.append(
            {**selection_body, "slot_sha256": content_hash(selection_body)}
        )
        execution_body = {
            "slot_id": f"profile-selected-execute-{index:02d}",
            "phase": "selected_plan_execution",
            "semantic_task_id": task_id,
            "semantic_class_id": task["semantic_class_id"],
            "plan_binding": "resolved_from_sealed_profile_selection",
        }
        execution_slots.append(
            {**execution_body, "slot_sha256": content_hash(execution_body)}
        )

    calls_per_plan = selected["execution"]["remote_calls_per_plan"]
    counts = {
        "acquisition_plan_runs": len(acquisition_runs),
        "selected_plan_runs": len(execution_slots),
        "evaluation_shadow_plan_runs": len(shadow_runs),
        "total_plan_runs": (
            len(acquisition_runs) + len(execution_slots) + len(shadow_runs)
        ),
        "acquisition_backend_calls": len(acquisition_runs) * calls_per_plan,
        "selected_plan_backend_calls": len(execution_slots) * calls_per_plan,
        "evaluation_shadow_backend_calls": len(shadow_runs) * calls_per_plan,
        "total_backend_calls": (
            len(acquisition_runs) + len(execution_slots) + len(shadow_runs)
        )
        * calls_per_plan,
    }
    if counts != selected["expected_counts"]:
        raise M15CurrentQueryProfileBaselineError(
            "compiled profile counts do not match the frozen protocol"
        )
    if not acquisition_proof["passed"] or not shadow_proof["passed"]:
        raise M15CurrentQueryProfileBaselineError(
            "profile schedule counterbalance proof failed"
        )

    body = {
        "schema_version": CURRENT_QUERY_PROFILE_SCHEDULE_SCHEMA_VERSION,
        "protocol_id": selected["protocol_id"],
        "protocol_sha256": content_hash(selected),
        "development_population_id": selected["development_population_id"],
        "method_id": selected["method_id"],
        "direct_semantic_workload_sha256": workload.manifest["manifest_sha256"],
        "heldout_selection_view_sha256": workload.heldout_selection_view[
            "selection_view_sha256"
        ],
        "phase_order": list(_PHASE_ORDER),
        "acquisition_runs": acquisition_runs,
        "selection_slots": selection_slots,
        "selected_execution_slots": execution_slots,
        "shadow_runs": shadow_runs,
        "counts": counts,
        "balance_proof": {
            "acquisition": acquisition_proof,
            "shadow": shadow_proof,
            "passed": True,
        },
        "selection_boundary": {
            "candidate_set_sealed_before_profile_calls": True,
            "profile_costs_sealed_before_selected_execution": True,
            "selection_fields": copy.deepcopy(
                selected["acquisition"]["selection_fields"]
            ),
            "answer_rows_selection_input": False,
            "answer_oracle_opened_before_selection_seal": False,
            "online_or_shadow_measurements_used_for_selection": False,
            "selection_scope": "within_one_semantic_class",
        },
        "cost_accounting": copy.deepcopy(selected["cost_accounting"]),
        "execution_protocol": copy.deepcopy(selected["execution"]),
        "analysis_protocol": copy.deepcopy(selected["analysis"]),
        "input_boundary": copy.deepcopy(selected["input_boundary"]),
        "external_calls_made": 0,
        "contains_measurements": False,
        "automatic_retries": 0,
        "live_execution_authorized": False,
        "paper_result": False,
    }
    payload = {**body, "schedule_sha256": content_hash(body)}
    return M15CurrentQueryProfileBaselineSchedule(payload)
