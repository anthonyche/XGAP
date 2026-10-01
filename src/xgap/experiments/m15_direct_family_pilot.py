"""Freeze the F2C10D family-memory development-pilot schedule.

This module is deliberately side-effect free.  It binds the author-selected
development protocol to the verified F2C10 direct semantic workload and emits
every training and post-selection shadow run in deterministic order.  Online
run slots are resolved only after the measured family-memory prediction and
semantic-frontier artifacts have been sealed.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)


DIRECT_FAMILY_PILOT_PROTOCOL_SCHEMA_VERSION = (
    "m15-f2c10d-direct-family-pilot-protocol-v1"
)
DIRECT_FAMILY_PILOT_SCHEDULE_SCHEMA_VERSION = (
    "m15-f2c10d-direct-family-pilot-schedule-v1"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")
_PHASE_ORDER = (
    "training_measurement",
    "family_memory_freeze",
    "heldout_prediction",
    "selection_seal",
    "online_selected_execution",
    "postselection_shadow_evaluation",
    "analysis",
)
_METRICS = (
    "prediction_error",
    "physical_winner_accuracy",
    "latency_regret",
    "bytes_regret",
    "predicted_observed_frontier_overlap",
)


class M15DirectFamilyPilotError(ValueError):
    """Raised when the frozen pilot or its workload binding drifts."""


@dataclass(frozen=True)
class M15DirectFamilyPilotSchedule:
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
        raise M15DirectFamilyPilotError(
            "pilot protocol must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15DirectFamilyPilotError("pilot protocol must be an object")
    return dict(payload)


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise M15DirectFamilyPilotError(f"{name} must be a positive integer")
    return value


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15DirectFamilyPilotError(f"{name} is not a safe identifier")
    return value


def _validate_protocol(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    protocol = _json_object(value)
    fields = {
        "schema_version",
        "protocol_id",
        "development_population_id",
        "phase_order",
        "training",
        "selection",
        "online",
        "shadow",
        "execution",
        "analysis",
        "expected_counts",
        "claim_boundary",
        "paper_result",
    }
    if set(protocol) != fields:
        raise M15DirectFamilyPilotError(
            "pilot protocol fields do not match the frozen contract"
        )
    if protocol["schema_version"] != DIRECT_FAMILY_PILOT_PROTOCOL_SCHEMA_VERSION:
        raise M15DirectFamilyPilotError("pilot protocol schema is unsupported")
    _safe_id(protocol["protocol_id"], name="protocol_id")
    _safe_id(
        protocol["development_population_id"],
        name="development_population_id",
    )
    if tuple(protocol["phase_order"]) != _PHASE_ORDER:
        raise M15DirectFamilyPilotError("pilot phase order changed")

    training = protocol["training"]
    if not isinstance(training, Mapping) or set(training) != {
        "semantic_task_count",
        "physical_plan_count",
        "repetitions_per_plan",
        "task_order",
        "strategy_order",
        "schedule_seed",
    }:
        raise M15DirectFamilyPilotError("training protocol fields are invalid")
    if (
        training["semantic_task_count"] != 18
        or training["physical_plan_count"] != 36
        or training["repetitions_per_plan"] != 4
        or training["task_order"] != "sha256_seeded_per_block"
        or training["strategy_order"]
        != "per_task_alternating_ab_ba_counterbalanced"
    ):
        raise M15DirectFamilyPilotError("training protocol is not option A")
    _safe_id(training["schedule_seed"], name="training schedule seed")

    selection = protocol["selection"]
    if not isinstance(selection, Mapping) or set(selection) != {
        "predictor",
        "heldout_semantic_task_count",
        "heldout_physical_plan_count",
        "online_cardinality",
        "current_query_observation_operations",
        "seal_before_oracle_and_execution",
        "post_execution_measurements_used",
    }:
        raise M15DirectFamilyPilotError("selection protocol fields are invalid")
    selection_without_cardinality = {
        key: item for key, item in selection.items() if key != "online_cardinality"
    }
    if selection_without_cardinality != {
        "predictor": "strategy_conditioned_family_memory",
        "heldout_semantic_task_count": 10,
        "heldout_physical_plan_count": 20,
        "current_query_observation_operations": [],
        "seal_before_oracle_and_execution": True,
        "post_execution_measurements_used": False,
    }:
        raise M15DirectFamilyPilotError("selection protocol is not option A")
    cardinality = selection["online_cardinality"]
    if not isinstance(cardinality, Mapping) or set(cardinality) != {
        "mode",
        "minimum_total",
        "maximum_total",
        "maximum_per_query",
    }:
        raise M15DirectFamilyPilotError("online cardinality fields are invalid")
    if cardinality["mode"] not in {"exact_total", "per_query_frontier"}:
        raise M15DirectFamilyPilotError("online cardinality mode is invalid")
    minimum_online = _positive_int(
        cardinality["minimum_total"], name="minimum online plans"
    )
    maximum_online = _positive_int(
        cardinality["maximum_total"], name="maximum online plans"
    )
    _positive_int(
        cardinality["maximum_per_query"], name="maximum plans per query"
    )
    if minimum_online > maximum_online:
        raise M15DirectFamilyPilotError("online cardinality range is reversed")
    if cardinality["mode"] == "exact_total" and minimum_online != maximum_online:
        raise M15DirectFamilyPilotError("exact online cardinality must be singular")

    online = protocol["online"]
    if not isinstance(online, Mapping) or online != {
        "repetitions_per_returned_plan": 1,
        "execution_role": "online_selected_plan",
        "selection_input": False,
        "memory_writes_allowed": False,
    }:
        raise M15DirectFamilyPilotError("online protocol is not option A")

    shadow = protocol["shadow"]
    if not isinstance(shadow, Mapping) or set(shadow) != {
        "semantic_task_count",
        "physical_plan_count",
        "repetitions_per_plan",
        "starts_after_selection_seal",
        "selection_input",
        "memory_writes_allowed",
        "task_order",
        "strategy_order",
        "schedule_seed",
    }:
        raise M15DirectFamilyPilotError("shadow protocol fields are invalid")
    if (
        shadow["semantic_task_count"] != 10
        or shadow["physical_plan_count"] != 20
        or shadow["repetitions_per_plan"] != 4
        or shadow["starts_after_selection_seal"] is not True
        or shadow["selection_input"] is not False
        or shadow["memory_writes_allowed"] is not False
        or shadow["task_order"] != "sha256_seeded_per_block"
        or shadow["strategy_order"]
        != "per_task_alternating_ab_ba_counterbalanced"
    ):
        raise M15DirectFamilyPilotError("shadow protocol is not option A")
    _safe_id(shadow["schedule_seed"], name="shadow schedule seed")

    execution = protocol["execution"]
    if not isinstance(execution, Mapping) or execution != {
        "backend_timeout_seconds": 60,
        "slurm_timeout_minutes": 45,
        "remote_calls_per_plan": 2,
        "failure_policy": "stop_on_first_failure",
        "automatic_retries": 0,
    }:
        raise M15DirectFamilyPilotError("execution protocol is not option A")

    analysis = protocol["analysis"]
    if not isinstance(analysis, Mapping) or analysis != {
        "per_plan_aggregation": "median_over_four_shadow_repetitions",
        "physical_winner_tie_break": [
            "median_elapsed_ms",
            "median_total_bytes_moved",
            "plan_id",
        ],
        "frontier_observed_costs": "per_plan_shadow_medians",
        "metrics": list(_METRICS),
        "confirmatory_statistics": False,
    }:
        raise M15DirectFamilyPilotError("analysis protocol is not option A")

    counts = protocol["expected_counts"]
    if not isinstance(counts, Mapping) or set(counts) != {
        "training_plan_runs",
        "online_selected_plan_runs",
        "evaluation_shadow_plan_runs",
        "total_plan_runs",
        "total_backend_calls",
    }:
        raise M15DirectFamilyPilotError("expected option-A count fields changed")
    for name in (
        "online_selected_plan_runs",
        "total_plan_runs",
        "total_backend_calls",
    ):
        value = counts[name]
        if not isinstance(value, Mapping) or set(value) != {
            "minimum",
            "maximum",
        }:
            raise M15DirectFamilyPilotError(f"{name} range is invalid")
        minimum = _positive_int(value["minimum"], name=f"{name} minimum")
        maximum = _positive_int(value["maximum"], name=f"{name} maximum")
        if minimum > maximum:
            raise M15DirectFamilyPilotError(f"{name} range is reversed")
    if counts["training_plan_runs"] != 144 or counts[
        "evaluation_shadow_plan_runs"
    ] != 80:
        raise M15DirectFamilyPilotError("fixed option-A counts changed")
    if counts["online_selected_plan_runs"] != {
        "minimum": minimum_online,
        "maximum": maximum_online,
    }:
        raise M15DirectFamilyPilotError(
            "online count range does not match cardinality policy"
        )
    expected_total = {
        "minimum": 144 + minimum_online + 80,
        "maximum": 144 + maximum_online + 80,
    }
    expected_calls = {
        "minimum": 2 * expected_total["minimum"],
        "maximum": 2 * expected_total["maximum"],
    }
    if counts["total_plan_runs"] != expected_total:
        raise M15DirectFamilyPilotError("total plan range is inconsistent")
    if counts["total_backend_calls"] != expected_calls:
        raise M15DirectFamilyPilotError("backend-call range is inconsistent")
    boundary = protocol["claim_boundary"]
    if not isinstance(boundary, Mapping) or boundary != {
        "development_pilot_only": True,
        "paper_scale_query_count": "30_to_50_after_pilot_validation",
        "paper_result": False,
    }:
        raise M15DirectFamilyPilotError("pilot claim boundary changed")
    if protocol["paper_result"] is not False:
        raise M15DirectFamilyPilotError("development pilot cannot be a paper result")
    return protocol


def _task_map(view: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = view.get("semantic_tasks")
    if not isinstance(tasks, list):
        raise M15DirectFamilyPilotError("semantic task view is invalid")
    result = {str(item["semantic_task_id"]): copy.deepcopy(dict(item)) for item in tasks}
    if len(result) != len(tasks):
        raise M15DirectFamilyPilotError("semantic task IDs are not unique")
    for task in result.values():
        candidates = task.get("physical_candidates")
        if not isinstance(candidates, list) or len(candidates) != 2:
            raise M15DirectFamilyPilotError(
                "each semantic task must expose two physical plans"
            )
        if tuple(sorted(item["physical_strategy"] for item in candidates)) != _STRATEGIES:
            raise M15DirectFamilyPilotError("physical strategy set changed")
    return result


def _ordered_task_ids(
    tasks: Mapping[str, Mapping[str, Any]], *, seed: str, block_index: int
) -> list[str]:
    return sorted(
        tasks,
        key=lambda task_id: (
            content_hash(
                {
                    "seed": seed,
                    "block_index": block_index,
                    "semantic_task_id": task_id,
                }
            ),
            task_id,
        ),
    )


def _phase_runs(
    *,
    phase: str,
    tasks: Mapping[str, Mapping[str, Any]],
    repetitions: int,
    seed: str,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    stable_task_ids = sorted(tasks)
    task_offsets = {task_id: index % 2 for index, task_id in enumerate(stable_task_ids)}
    for block_index in range(1, repetitions + 1):
        for task_order_position, task_id in enumerate(
            _ordered_task_ids(tasks, seed=seed, block_index=block_index),
            start=1,
        ):
            task = tasks[task_id]
            by_strategy = {
                str(item["physical_strategy"]): dict(item)
                for item in task["physical_candidates"]
            }
            strategies: Sequence[str] = _STRATEGIES
            if (task_offsets[task_id] + block_index) % 2:
                strategies = tuple(reversed(strategies))
            for strategy_position, strategy in enumerate(strategies, start=1):
                candidate = by_strategy[strategy]
                identity = {
                    "phase": phase,
                    "block_index": block_index,
                    "task_order_position": task_order_position,
                    "strategy_order_position": strategy_position,
                    "semantic_task_id": task_id,
                    "base_query_id": task["base_query_id"],
                    "query_id": task["executable_query_id"],
                    "semantic_class_id": task["semantic_class_id"],
                    "plan_id": candidate["plan_id"],
                    "physical_strategy": strategy,
                }
                runs.append(
                    {
                        "run_id": (
                            f"{phase}-b{block_index:02d}-"
                            f"t{task_order_position:02d}-p{strategy_position}"
                        ),
                        **identity,
                        "run_sha256": content_hash(identity),
                    }
                )
    return runs


def _balance_proof(
    runs: Sequence[Mapping[str, Any]],
    tasks: Mapping[str, Mapping[str, Any]],
    repetitions: int,
) -> dict[str, Any]:
    per_task: dict[str, Any] = {}
    for task_id in sorted(tasks):
        selected = [item for item in runs if item["semantic_task_id"] == task_id]
        strategy_counts = {
            strategy: sum(item["physical_strategy"] == strategy for item in selected)
            for strategy in _STRATEGIES
        }
        position_counts = {
            strategy: {
                str(position): sum(
                    item["physical_strategy"] == strategy
                    and item["strategy_order_position"] == position
                    for item in selected
                )
                for position in (1, 2)
            }
            for strategy in _STRATEGIES
        }
        per_task[task_id] = {
            "strategy_run_counts": strategy_counts,
            "strategy_position_counts": position_counts,
            "balanced": (
                set(strategy_counts.values()) == {repetitions}
                and all(
                    set(counts.values()) == {repetitions // 2}
                    for counts in position_counts.values()
                )
            ),
        }
    return {
        "repetitions_per_plan": repetitions,
        "even_repetition_count": repetitions % 2 == 0,
        "every_task_plan_covered_once_per_block": all(
            sum(
                item["semantic_task_id"] == task_id
                and item["block_index"] == block
                for item in runs
            )
            == 2
            for task_id in tasks
            for block in range(1, repetitions + 1)
        ),
        "per_task": per_task,
        "passed": all(item["balanced"] for item in per_task.values()),
    }


def compile_m15_direct_family_pilot_schedule(
    *,
    workload: M15DirectSemanticWorkloadBundle,
    protocol: Mapping[str, Any] | str | Path,
    predictor_policy: Mapping[str, Any] | str | Path,
) -> M15DirectFamilyPilotSchedule:
    """Bind option A to the exact F2C10 workload without making any calls."""

    selected = _validate_protocol(protocol)
    predictor = _json_object(predictor_policy)
    if predictor.get("current_query_observation_operations") != []:
        raise M15DirectFamilyPilotError(
            "predictor policy permits current-query observations"
        )
    if predictor.get("automatic_retries") != 0 or predictor.get("paper_result") is not False:
        raise M15DirectFamilyPilotError("predictor claim or retry boundary changed")

    training_tasks = _task_map(workload.training_selection_view)
    heldout_tasks = _task_map(workload.heldout_selection_view)
    training = selected["training"]
    selection = selected["selection"]
    shadow = selected["shadow"]
    if (
        len(training_tasks) != training["semantic_task_count"]
        or sum(len(item["physical_candidates"]) for item in training_tasks.values())
        != training["physical_plan_count"]
        or len(heldout_tasks) != selection["heldout_semantic_task_count"]
        or sum(len(item["physical_candidates"]) for item in heldout_tasks.values())
        != selection["heldout_physical_plan_count"]
    ):
        raise M15DirectFamilyPilotError(
            "pilot protocol does not match the direct workload population"
        )
    if set(training_tasks).intersection(heldout_tasks):
        raise M15DirectFamilyPilotError("training and held-out tasks overlap")

    training_runs = _phase_runs(
        phase="training_measurement",
        tasks=training_tasks,
        repetitions=training["repetitions_per_plan"],
        seed=training["schedule_seed"],
    )
    shadow_runs = _phase_runs(
        phase="postselection_shadow_evaluation",
        tasks=heldout_tasks,
        repetitions=shadow["repetitions_per_plan"],
        seed=shadow["schedule_seed"],
    )
    cardinality = selection["online_cardinality"]
    minimum_online = int(cardinality["minimum_total"])
    maximum_online = int(cardinality["maximum_total"])
    if cardinality["mode"] == "per_query_frontier":
        query_count = len(workload.heldout_selection_view["base_query_ids"])
        max_per_query = int(cardinality["maximum_per_query"])
        if (minimum_online, maximum_online) != (
            query_count,
            query_count * max_per_query,
        ):
            raise M15DirectFamilyPilotError(
                "per-query frontier bounds do not match query count and K"
            )
    online_slots = [
        {
            "slot_id": f"online-selected-{index:02d}",
            "phase": "online_selected_execution",
            "selection_binding": "resolved_from_sealed_semantic_frontiers",
            "execution_role": selected["online"]["execution_role"],
        }
        for index in range(1, maximum_online + 1)
    ]
    training_proof = _balance_proof(
        training_runs, training_tasks, training["repetitions_per_plan"]
    )
    shadow_proof = _balance_proof(
        shadow_runs, heldout_tasks, shadow["repetitions_per_plan"]
    )
    computed_counts = {
        "training_plan_runs": len(training_runs),
        "online_selected_plan_runs": {
            "minimum": minimum_online,
            "maximum": maximum_online,
        },
        "evaluation_shadow_plan_runs": len(shadow_runs),
        "total_plan_runs": {
            "minimum": len(training_runs) + minimum_online + len(shadow_runs),
            "maximum": len(training_runs) + maximum_online + len(shadow_runs),
        },
        "total_backend_calls": {
            "minimum": (
                len(training_runs) + minimum_online + len(shadow_runs)
            )
            * selected["execution"]["remote_calls_per_plan"],
            "maximum": (
                len(training_runs) + maximum_online + len(shadow_runs)
            )
            * selected["execution"]["remote_calls_per_plan"],
        },
    }
    if computed_counts != selected["expected_counts"]:
        raise M15DirectFamilyPilotError("compiled option-A counts do not match")
    if not training_proof["passed"] or not shadow_proof["passed"]:
        raise M15DirectFamilyPilotError("counterbalance proof failed")

    body = {
        "schema_version": DIRECT_FAMILY_PILOT_SCHEDULE_SCHEMA_VERSION,
        "protocol_id": selected["protocol_id"],
        "protocol_sha256": content_hash(selected),
        "development_population_id": selected["development_population_id"],
        "direct_semantic_workload_sha256": workload.manifest["manifest_sha256"],
        "training_selection_view_sha256": workload.training_selection_view[
            "selection_view_sha256"
        ],
        "heldout_selection_view_sha256": workload.heldout_selection_view[
            "selection_view_sha256"
        ],
        "predictor_policy_sha256": content_hash(predictor),
        "phase_order": list(_PHASE_ORDER),
        "training_runs": training_runs,
        "online_execution_slots": online_slots,
        "shadow_runs": shadow_runs,
        "counts": computed_counts,
        "balance_proof": {
            "training": training_proof,
            "shadow": shadow_proof,
            "passed": True,
        },
        "selection_boundary": {
            "current_query_observation_operations": [],
            "selection_sealed_before_online_and_shadow": True,
            "heldout_evaluation_records_opened_only_after_selection": True,
            "training_oracles_used_only_for_postexecution_admission": True,
            "shadow_is_selection_input": False,
            "online_and_shadow_accounted_separately": True,
            "online_cardinality": copy.deepcopy(dict(cardinality)),
        },
        "execution_protocol": copy.deepcopy(dict(selected["execution"])),
        "analysis_protocol": copy.deepcopy(dict(selected["analysis"])),
        "external_calls_made": 0,
        "contains_measurements": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    payload = {**body, "schedule_sha256": content_hash(body)}
    return M15DirectFamilyPilotSchedule(payload)
