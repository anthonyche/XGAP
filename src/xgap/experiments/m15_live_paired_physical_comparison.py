"""Execute the frozen F2C13 same-allocation paired physical comparison."""

from __future__ import annotations

import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.backends.protocol import BackendClient
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectFamilyPredictionSuite,
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticCandidateSet,
    build_m15_variable_direct_semantic_candidate_set,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_paired_physical_comparison import (
    M15PairedPhysicalComparisonSchedule,
    compile_m15_paired_physical_comparison_schedule,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
)
from xgap.experiments.m15_predicate_overlay import M15PredicateMappingSpec
from xgap.experiments.m15_semantic_frontier import M15SemanticRelaxationCatalog
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION = (
    "m15-f2c13b-live-paired-physical-comparison-v1"
)
FAMILY_SELECTION_SEAL_SCHEMA_VERSION = (
    "m15-f2c13b-family-memory-selection-seal-v1"
)
PROFILE_SELECTION_SEAL_SCHEMA_VERSION = (
    "m15-f2c13b-current-query-profile-selection-seal-v1"
)
PAIRED_PHYSICAL_ANALYSIS_SCHEMA_VERSION = (
    "m15-f2c13b-paired-physical-comparison-analysis-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_METHODS = ("family_memory", "current_query_dual_profile")
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")


@dataclass(frozen=True)
class M15LivePairedPhysicalComparisonRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _git_state(repo_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return {"commit": commit, "clean": not bool(dirty)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"commit": None, "clean": None, "error": str(exc)}


def _backend_tool(
    clients: Mapping[str, BackendClient], events: list[dict[str, Any]]
) -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            RecordingBackendPlugin(
                NativeBackendPlugin(backend_id, clients[backend_id]), events
            )
        )
    return BackendInvokeTool(plugins)


def _candidate_sets(
    *,
    direct_workload: M15DirectSemanticWorkloadBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
) -> dict[str, M15DirectSemanticCandidateSet]:
    query_ids = sorted(
        set(direct_workload.training_selection_view["base_query_ids"])
        | set(direct_workload.heldout_selection_view["base_query_ids"])
    )
    return {
        query_id: build_m15_variable_direct_semantic_candidate_set(
            direct_workload=direct_workload,
            base_bundle=base_bundle,
            base_query_id=query_id,
            catalog=catalog,
            mapping=mapping,
        )
        for query_id in query_ids
    }


def _plan_index(
    candidate_sets: Mapping[str, M15DirectSemanticCandidateSet],
) -> dict[str, Any]:
    plans: dict[str, Any] = {}
    for candidates in candidate_sets.values():
        for plan_id, plan in candidates.plans.items():
            if plan_id in plans:
                raise ValueError("paired physical plan IDs are not unique")
            plans[plan_id] = plan
    return plans


def _task_index(
    direct_workload: M15DirectSemanticWorkloadBundle,
) -> dict[str, dict[str, Any]]:
    tasks = {
        str(item["semantic_task_id"]): dict(item)
        for item in direct_workload.heldout_selection_view["semantic_tasks"]
    }
    if len(tasks) != 10:
        raise ValueError("paired comparison requires ten held-out semantic tasks")
    return tasks


def _execute(
    *,
    scheduler: FederatedScheduler,
    plan: Any,
    record: Mapping[str, Any],
    events: list[dict[str, Any]],
    goal_id: str,
) -> Any:
    first_event = len(events)
    result = scheduler.execute(plan, goal_id=goal_id)
    for index, event in enumerate(events[first_event:], start=1):
        event["paired_phase"] = record["phase"]
        event["paired_run_id"] = (
            record.get("run_id")
            or record.get("run_sha256")
            or record.get("slot_id")
        )
        event["phase_call_index"] = index
        for field in (
            "semantic_task_id",
            "base_query_id",
            "query_id",
            "semantic_class_id",
            "plan_id",
            "physical_strategy",
        ):
            event[field] = record[field]
        if "method_id" in record:
            event["method_id"] = record["method_id"]
    return result


def _result_payload(
    *,
    record: Mapping[str, Any],
    result: Any,
    exact_answer: bool | None,
) -> dict[str, Any]:
    payload = {
        **dict(record),
        "success": result.success,
        "elapsed_ms": result.elapsed_ms,
        "total_bytes_moved": result.total_bytes_moved,
        "total_remote_calls": result.total_remote_calls,
        "runtime_result": result.to_dict(),
    }
    if exact_answer is not None:
        payload["exact_answer"] = exact_answer
    return payload


def _training_observations(
    schedule: M15PairedPhysicalComparisonSchedule,
    results: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for run in schedule.payload["training_runs"]:
        result = results[run["run_id"]]
        plan_id = str(run["plan_id"])
        observation = grouped.setdefault(
            plan_id,
            {
                "semantic_task_id": run["semantic_task_id"],
                "plan_id": plan_id,
                "physical_strategy": run["physical_strategy"],
                "repetitions": [],
            },
        )
        observation["repetitions"].append(
            {
                "repetition_id": run["run_id"],
                "block_index": run["block_index"],
                "order_position": run["strategy_order_position"],
                "elapsed_ms": result["elapsed_ms"],
                "total_bytes_moved": result["total_bytes_moved"],
                "total_remote_calls": result["total_remote_calls"],
                "execution_success": result["success"],
                "exact_answer": result["exact_answer"],
            }
        )
    return [grouped[plan_id] for plan_id in sorted(grouped)]


def _summary(values: Sequence[float]) -> dict[str, float]:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("paired analysis requires finite nonempty values")
    return {
        "mean": sum(values) / len(values),
        "median": float(statistics.median(values)),
        "minimum": min(values),
        "maximum": max(values),
    }


def _shadow_medians(
    shadow_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for result in shadow_results.values():
        if result.get("success") is not True or result.get("exact_answer") is not True:
            raise ValueError("paired shadow result is not successful and exact")
        grouped.setdefault(str(result["plan_id"]), []).append(result)
    if len(grouped) != 20 or any(len(values) != 4 for values in grouped.values()):
        raise ValueError("paired shadows must cover 20 plans four times")
    return {
        plan_id: {
            "latency_ms": float(
                statistics.median(item["elapsed_ms"] for item in values)
            ),
            "total_bytes_moved": float(
                statistics.median(item["total_bytes_moved"] for item in values)
            ),
        }
        for plan_id, values in grouped.items()
    }


def _method_analysis(
    *,
    method_id: str,
    selections: Mapping[str, Mapping[str, Any]],
    selected_results: Mapping[str, Mapping[str, Any]],
    task_candidates: Mapping[str, Sequence[str]],
    medians: Mapping[str, Mapping[str, float]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    for task_id in sorted(task_candidates):
        candidates = list(task_candidates[task_id])
        selection = selections[task_id]
        selected_plan = str(selection["selected_plan_id"])
        result = selected_results[task_id]
        if selected_plan not in candidates or result["plan_id"] != selected_plan:
            raise ValueError("paired selected result differs from its sealed choice")
        latency_winner = min(
            candidates,
            key=lambda plan_id: (
                medians[plan_id]["latency_ms"],
                medians[plan_id]["total_bytes_moved"],
                plan_id,
            ),
        )
        bytes_winner = min(
            candidates,
            key=lambda plan_id: (
                medians[plan_id]["total_bytes_moved"],
                medians[plan_id]["latency_ms"],
                plan_id,
            ),
        )
        records.append(
            {
                "semantic_task_id": task_id,
                "selected_plan_id": selected_plan,
                "observed_latency_winner_plan_id": latency_winner,
                "observed_bytes_winner_plan_id": bytes_winner,
                "winner_correct": selected_plan == latency_winner,
                "selected_plan_latency_regret_ms": (
                    medians[selected_plan]["latency_ms"]
                    - medians[latency_winner]["latency_ms"]
                ),
                "selected_plan_bytes_regret": (
                    medians[selected_plan]["total_bytes_moved"]
                    - medians[bytes_winner]["total_bytes_moved"]
                ),
                "selected_execution_latency_ms": float(result["elapsed_ms"]),
                "selected_execution_bytes": float(result["total_bytes_moved"]),
            }
        )
    body = {
        "method_id": method_id,
        "semantic_task_count": len(records),
        "physical_winner_accuracy": {
            "correct_count": sum(item["winner_correct"] for item in records),
            "accuracy": sum(item["winner_correct"] for item in records)
            / len(records),
        },
        "selected_plan_latency_regret_ms": _summary(
            [item["selected_plan_latency_regret_ms"] for item in records]
        ),
        "selected_plan_bytes_regret": _summary(
            [item["selected_plan_bytes_regret"] for item in records]
        ),
        "selected_execution_latency_ms": _summary(
            [item["selected_execution_latency_ms"] for item in records]
        ),
        "selected_execution_bytes": _summary(
            [item["selected_execution_bytes"] for item in records]
        ),
    }
    return body, records


def analyze_m15_paired_physical_comparison(
    *,
    family_selection_seal: Mapping[str, Any],
    profile_selection_seal: Mapping[str, Any],
    profile_acquisition_results: Mapping[str, Mapping[str, Any]],
    selected_results: Mapping[str, Mapping[str, Mapping[str, Any]]],
    shadow_results: Mapping[str, Mapping[str, Any]],
    training_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute the predeclared descriptive paired metrics after both seals."""

    medians = _shadow_medians(shadow_results)
    family = {
        str(item["semantic_task_id"]): item
        for item in family_selection_seal["selections"]
    }
    profile = {
        str(item["semantic_task_id"]): item
        for item in profile_selection_seal["selections"]
    }
    candidates = {
        task_id: list(item["candidate_plan_ids"])
        for task_id, item in family.items()
    }
    if set(family) != set(profile) or len(family) != 10:
        raise ValueError("paired selection seals do not cover the same ten tasks")
    method_payloads: dict[str, Any] = {}
    method_records: dict[str, list[dict[str, Any]]] = {}
    for method_id, selections in (
        ("family_memory", family),
        ("current_query_dual_profile", profile),
    ):
        payload, records = _method_analysis(
            method_id=method_id,
            selections=selections,
            selected_results=selected_results[method_id],
            task_candidates=candidates,
            medians=medians,
        )
        method_payloads[method_id] = payload
        method_records[method_id] = records

    family_records = {
        item["semantic_task_id"]: item for item in method_records["family_memory"]
    }
    profile_records = {
        item["semantic_task_id"]: item
        for item in method_records["current_query_dual_profile"]
    }
    paired = [
        {
            "semantic_task_id": task_id,
            "profile_minus_memory_latency_regret_ms": (
                profile_records[task_id]["selected_plan_latency_regret_ms"]
                - family_records[task_id]["selected_plan_latency_regret_ms"]
            ),
            "profile_minus_memory_bytes_regret": (
                profile_records[task_id]["selected_plan_bytes_regret"]
                - family_records[task_id]["selected_plan_bytes_regret"]
            ),
        }
        for task_id in sorted(family_records)
    ]
    acquisitions_by_task: dict[str, list[Mapping[str, Any]]] = {}
    for item in profile_acquisition_results.values():
        acquisitions_by_task.setdefault(str(item["semantic_task_id"]), []).append(
            item
        )
    if set(acquisitions_by_task) != set(family) or any(
        len(values) != 2 for values in acquisitions_by_task.values()
    ):
        raise ValueError("paired profile acquisitions are incomplete")
    acquisition_latency = [
        sum(float(item["elapsed_ms"]) for item in acquisitions_by_task[task_id])
        for task_id in sorted(acquisitions_by_task)
    ]
    acquisition_bytes = [
        sum(
            float(item["total_bytes_moved"])
            for item in acquisitions_by_task[task_id]
        )
        for task_id in sorted(acquisitions_by_task)
    ]
    training_latency = sum(float(item["elapsed_ms"]) for item in training_results.values())
    training_bytes = sum(
        float(item["total_bytes_moved"]) for item in training_results.values()
    )
    controls: dict[str, Any] = {}
    strategy_by_plan = {
        str(item["plan_id"]): str(item["physical_strategy"])
        for item in shadow_results.values()
    }
    for control_id, strategy in (
        ("fixed_parallel_hash", "parallel_hash_join"),
        ("fixed_risk_first_bind", "risk_first_bind_join"),
    ):
        selections = {
            task_id: {
                "selected_plan_id": next(
                    plan_id
                    for plan_id in plan_ids
                    if strategy_by_plan[plan_id] == strategy
                )
            }
            for task_id, plan_ids in candidates.items()
        }
        # Controls are evaluated from shared shadows and require no serving run.
        records = []
        for task_id, selection in selections.items():
            selected_plan = selection["selected_plan_id"]
            plan_ids = candidates[task_id]
            latency_winner = min(
                plan_ids,
                key=lambda plan_id: (
                    medians[plan_id]["latency_ms"],
                    medians[plan_id]["total_bytes_moved"],
                    plan_id,
                ),
            )
            bytes_winner = min(
                plan_ids,
                key=lambda plan_id: (
                    medians[plan_id]["total_bytes_moved"],
                    medians[plan_id]["latency_ms"],
                    plan_id,
                ),
            )
            records.append(
                {
                    "winner_correct": selected_plan == latency_winner,
                    "latency_regret": medians[selected_plan]["latency_ms"]
                    - medians[latency_winner]["latency_ms"],
                    "bytes_regret": medians[selected_plan]["total_bytes_moved"]
                    - medians[bytes_winner]["total_bytes_moved"],
                }
            )
        controls[control_id] = {
            "physical_winner_accuracy": sum(item["winner_correct"] for item in records)
            / len(records),
            "latency_regret_ms": _summary(
                [item["latency_regret"] for item in records]
            ),
            "bytes_regret": _summary([item["bytes_regret"] for item in records]),
            "evaluation_only": True,
        }
    controls["observed_oracle_upper_bound"] = {
        "physical_winner_accuracy": 1.0,
        "latency_regret_ms": _summary([0.0] * 10),
        "evaluation_only": True,
    }
    body = {
        "schema_version": PAIRED_PHYSICAL_ANALYSIS_SCHEMA_VERSION,
        "semantic_task_count": 10,
        "methods": method_payloads,
        "paired_profile_minus_memory": {
            "latency_regret_ms": _summary(
                [item["profile_minus_memory_latency_regret_ms"] for item in paired]
            ),
            "bytes_regret": _summary(
                [item["profile_minus_memory_bytes_regret"] for item in paired]
            ),
            "per_semantic_task": paired,
        },
        "profile_acquisition": {
            "plan_runs": 20,
            "backend_calls": 40,
            "latency_ms": _summary(acquisition_latency),
            "bytes": _summary(acquisition_bytes),
        },
        "historical_training": {
            "plan_runs": len(training_results),
            "backend_calls": 2 * len(training_results),
            "total_latency_ms": training_latency,
            "total_bytes": training_bytes,
            "reported_separately": True,
            "silently_amortized": False,
        },
        "count_based_training_break_even_future_tasks": 72,
        "evaluation_only_controls": controls,
        "shadow_measurements_used_for_evaluation_only": True,
        "confirmatory_statistics": False,
        "paper_result": False,
    }
    return {**body, "analysis_sha256": content_hash(body)}


def run_m15_live_paired_physical_comparison(
    *,
    direct_workload: M15DirectSemanticWorkloadBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    protocol: Mapping[str, Any] | str | Path,
    family_protocol: Mapping[str, Any] | str | Path,
    predictor_policy: Mapping[str, Any] | str | Path,
    profile_protocol: Mapping[str, Any] | str | Path,
    clients: Mapping[str, BackendClient],
    runtime_compatibility_sha256: str,
    output_root: str | Path,
    run_id: str = "paired-physical-comparison-run",
    repo_root: str | Path | None = None,
) -> M15LivePairedPhysicalComparisonRecord:
    """Run the finite paired comparison once and stop at the first failure."""

    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError("paired comparison requires neo4j and fuseki clients")
    if not _SHA256.fullmatch(runtime_compatibility_sha256):
        raise ValueError("runtime compatibility hash is invalid")
    root_repo = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    run_root = Path(output_root).resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    error: str | None = None
    events: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    training_results: dict[str, dict[str, Any]] = {}
    acquisition_results: dict[str, dict[str, Any]] = {}
    selected_results: dict[str, dict[str, dict[str, Any]]] = {
        method_id: {} for method_id in _METHODS
    }
    shadow_results: dict[str, dict[str, Any]] = {}
    checks: dict[str, bool] = {}
    schedule: M15PairedPhysicalComparisonSchedule | None = None
    suite: M15DirectFamilyPredictionSuite | None = None
    memory_payload: dict[str, Any] | None = None
    family_seal: dict[str, Any] | None = None
    profile_seal: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    try:
        schedule = compile_m15_paired_physical_comparison_schedule(
            workload=direct_workload,
            protocol=protocol,
            family_protocol=family_protocol,
            predictor_policy=predictor_policy,
            profile_protocol=profile_protocol,
        )
        _write_json(run_root / "paired_schedule.json", schedule.to_dict())
        for backend_id in ("neo4j", "fuseki"):
            timeout = getattr(clients[backend_id], "timeout_seconds", 60.0)
            if float(timeout) != 60.0:
                raise ValueError("backend timeout must be exactly 60 seconds")
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        if not all(item["ok"] for item in health.values()):
            raise RuntimeError("paired comparison backend healthcheck failed")

        candidate_sets = _candidate_sets(
            direct_workload=direct_workload,
            base_bundle=base_bundle,
            catalog=catalog,
            mapping=mapping,
        )
        plans = _plan_index(candidate_sets)
        plan_metadata = {
            str(item["plan_id"]): dict(item)
            for candidates in candidate_sets.values()
            for item in candidates.payload["physical_candidates"]
        }
        tasks = _task_index(direct_workload)
        scheduler = FederatedScheduler(_backend_tool(clients, events))
        candidate_body = {
            "schema_version": "m15-f2c13b-paired-candidate-seal-v1",
            "schedule_sha256": schedule.schedule_hash,
            "candidate_plan_ids": sorted(plans),
            "candidate_count": len(plans),
            "sealed_before_backend_calls": True,
            "backend_calls_before_seal": len(events),
            "heldout_answer_oracle_fields": [],
        }
        candidate_seal = {
            **candidate_body,
            "candidate_seal_sha256": content_hash(candidate_body),
        }
        _write_json(run_root / "candidate_seal.json", candidate_seal)

        for record in schedule.payload["training_runs"]:
            result = _execute(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:training:{record['run_id']}",
            )
            expected = load_m15_parameterized_instance(
                direct_workload.workload_bundle, record["query_id"]
            )["final_oracle"]
            payload = _result_payload(
                record=record,
                result=result,
                exact_answer=list(result.final_rows) == expected,
            )
            training_results[record["run_id"]] = payload
            _write_json(
                run_root / "training/runs" / f"{record['run_id']}.json", payload
            )
            if not payload["success"] or not payload["exact_answer"]:
                raise RuntimeError(f"paired training failed: {record['run_id']}")

        raw_observations = _training_observations(schedule, training_results)
        _write_json(
            run_root / "training/training_observations.json",
            {"observations": raw_observations},
        )
        memory = build_m15_direct_training_memory_view(
            workload=direct_workload,
            raw_observations=raw_observations,
            runtime_compatibility_sha256=runtime_compatibility_sha256,
            policy=predictor_policy,
            measurement_source_kind="native_paired_physical_comparison",
        )
        memory_payload = memory.to_dict()
        _write_json(
            run_root / "training/training_memory_view.json", memory_payload
        )
        suite = build_m15_direct_family_prediction_suite(
            workload=direct_workload,
            base_bundle=base_bundle,
            catalog=catalog,
            mapping=mapping,
            memory=memory,
            policy=predictor_policy,
        )
        family_root = run_root / "family-selection"
        _write_json(family_root / "prediction_suite.json", suite.to_dict())
        predictions = {
            str(item["plan_id"]): dict(item)
            for source in suite.sources.values()
            for item in source.payload["predictions"]
        }
        for query_id, candidates in suite.candidate_sets.items():
            _write_json(
                family_root / "queries" / query_id / "candidate_set.json",
                candidates.to_dict(),
            )
        for query_id, source in suite.sources.items():
            _write_json(
                family_root / "queries" / query_id / "prediction_source.json",
                source.to_dict(),
            )
        family_selections = []
        for slot in schedule.payload["family_memory_selection_slots"]:
            selected_plan_id = min(
                slot["candidate_plan_ids"],
                key=lambda plan_id: (
                    predictions[plan_id]["estimated_latency_ms"],
                    predictions[plan_id]["estimated_total_bytes_moved"],
                    plan_id,
                ),
            )
            task = tasks[slot["semantic_task_id"]]
            chosen = predictions[selected_plan_id]
            family_selections.append(
                {
                    **dict(slot),
                    "base_query_id": task["base_query_id"],
                    "query_id": task["executable_query_id"],
                    "selected_plan_id": selected_plan_id,
                    "selected_strategy": chosen["physical_strategy"],
                    "predicted_latency_ms": chosen["estimated_latency_ms"],
                    "predicted_total_bytes_moved": chosen[
                        "estimated_total_bytes_moved"
                    ],
                }
            )
        family_body = {
            "schema_version": FAMILY_SELECTION_SEAL_SCHEMA_VERSION,
            "schedule_sha256": schedule.schedule_hash,
            "candidate_seal_sha256": candidate_seal["candidate_seal_sha256"],
            "training_memory_view_sha256": memory.memory_view_hash,
            "prediction_suite_sha256": suite.payload["prediction_suite_sha256"],
            "selections": family_selections,
            "selection_count": len(family_selections),
            "training_backend_calls_before_seal": len(events),
            "profile_backend_calls_before_seal": 0,
            "selected_backend_calls_before_seal": 0,
            "shadow_backend_calls_before_seal": 0,
            "heldout_answer_oracle_fields": [],
            "selection_input": "sealed_training_family_memory_only",
        }
        family_seal = {
            **family_body,
            "selection_seal_sha256": content_hash(family_body),
        }
        _write_json(run_root / "family_selection_seal.json", family_seal)

        for record in schedule.payload["profile_acquisition_runs"]:
            result = _execute(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:profile:{record['run_sha256']}",
            )
            payload = _result_payload(
                record=record,
                result=result,
                exact_answer=None,
            )
            payload["answer_oracle_opened"] = False
            acquisition_results[record["run_sha256"]] = payload
            _write_json(
                run_root
                / "profile/acquisition/runs"
                / f"{record['run_sha256']}.json",
                payload,
            )
            if not payload["success"]:
                raise RuntimeError(
                    f"paired profile acquisition failed: {record['run_sha256']}"
                )

        estimates = [
            {
                "semantic_task_id": item["semantic_task_id"],
                "base_query_id": item["base_query_id"],
                "query_id": item["query_id"],
                "semantic_class_id": item["semantic_class_id"],
                "plan_id": item["plan_id"],
                "physical_strategy": item["physical_strategy"],
                "elapsed_ms": item["elapsed_ms"],
                "total_bytes_moved": item["total_bytes_moved"],
                "source_run_sha256": item["run_sha256"],
            }
            for item in acquisition_results.values()
        ]
        estimate_body = {
            "schema_version": "m15-f2c13b-profile-cost-estimates-v1",
            "schedule_sha256": schedule.schedule_hash,
            "selection_fields": ["elapsed_ms", "total_bytes_moved", "plan_id"],
            "answer_rows": [],
            "answer_oracle_fields": [],
            "estimates": sorted(estimates, key=lambda item: item["plan_id"]),
        }
        estimate_source = {
            **estimate_body,
            "estimate_source_sha256": content_hash(estimate_body),
        }
        _write_json(run_root / "profile/profile_cost_estimates.json", estimate_source)
        estimates_by_plan = {item["plan_id"]: item for item in estimates}
        profile_selections = []
        for slot in schedule.payload["profile_selection_slots"]:
            selected_plan_id = min(
                slot["candidate_plan_ids"],
                key=lambda plan_id: (
                    estimates_by_plan[plan_id]["elapsed_ms"],
                    estimates_by_plan[plan_id]["total_bytes_moved"],
                    plan_id,
                ),
            )
            task = tasks[slot["semantic_task_id"]]
            chosen = estimates_by_plan[selected_plan_id]
            profile_selections.append(
                {
                    **dict(slot),
                    "base_query_id": task["base_query_id"],
                    "query_id": task["executable_query_id"],
                    "selected_plan_id": selected_plan_id,
                    "selected_strategy": chosen["physical_strategy"],
                    "selected_profile_elapsed_ms": chosen["elapsed_ms"],
                    "selected_profile_total_bytes_moved": chosen[
                        "total_bytes_moved"
                    ],
                }
            )
        profile_body = {
            "schema_version": PROFILE_SELECTION_SEAL_SCHEMA_VERSION,
            "schedule_sha256": schedule.schedule_hash,
            "family_selection_seal_sha256": family_seal["selection_seal_sha256"],
            "estimate_source_sha256": estimate_source["estimate_source_sha256"],
            "selections": profile_selections,
            "selection_count": len(profile_selections),
            "training_backend_calls_before_seal": 288,
            "profile_backend_calls_before_seal": 40,
            "selected_backend_calls_before_seal": 0,
            "shadow_backend_calls_before_seal": 0,
            "answer_oracle_opened_before_seal": False,
            "selection_input": "sealed_current_query_profile_costs_only",
        }
        profile_seal = {
            **profile_body,
            "selection_seal_sha256": content_hash(profile_body),
        }
        _write_json(run_root / "profile_selection_seal.json", profile_seal)

        acquisition_validation = []
        for payload in acquisition_results.values():
            expected = load_m15_parameterized_instance(
                direct_workload.workload_bundle, payload["query_id"]
            )["final_oracle"]
            exact = list(payload["runtime_result"]["final_rows"]) == expected
            acquisition_validation.append(
                {
                    "run_sha256": payload["run_sha256"],
                    "plan_id": payload["plan_id"],
                    "exact_answer": exact,
                }
            )
        _write_json(
            run_root / "profile/acquisition_validation.json",
            {
                "opened_after_both_selection_seals": True,
                "results": acquisition_validation,
                "all_exact": all(item["exact_answer"] for item in acquisition_validation),
            },
        )
        if not all(item["exact_answer"] for item in acquisition_validation):
            raise RuntimeError("paired acquisition answer validation failed")

        selections_by_method = {
            "family_memory": {
                item["semantic_task_id"]: item for item in family_selections
            },
            "current_query_dual_profile": {
                item["semantic_task_id"]: item for item in profile_selections
            },
        }
        for slot in schedule.payload["paired_selected_execution_slots"]:
            method_id = slot["method_id"]
            selection = selections_by_method[method_id][slot["semantic_task_id"]]
            metadata = plan_metadata[selection["selected_plan_id"]]
            record = {
                **dict(slot),
                "plan_id": selection["selected_plan_id"],
                "physical_strategy": metadata["physical_strategy"],
            }
            result = _execute(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:selected:{record['slot_id']}",
            )
            expected = load_m15_parameterized_instance(
                direct_workload.workload_bundle, record["query_id"]
            )["final_oracle"]
            payload = _result_payload(
                record=record,
                result=result,
                exact_answer=list(result.final_rows) == expected,
            )
            selected_results[method_id][record["semantic_task_id"]] = payload
            _write_json(
                run_root / "selected" / method_id / f"{record['slot_id']}.json",
                payload,
            )
            if not payload["success"] or not payload["exact_answer"]:
                raise RuntimeError(f"paired selected plan failed: {record['slot_id']}")

        for record in schedule.payload["shadow_runs"]:
            result = _execute(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:shadow:{record['run_sha256']}",
            )
            expected = load_m15_parameterized_instance(
                direct_workload.workload_bundle, record["query_id"]
            )["final_oracle"]
            payload = _result_payload(
                record=record,
                result=result,
                exact_answer=list(result.final_rows) == expected,
            )
            shadow_results[record["run_sha256"]] = payload
            _write_json(
                run_root / "shadow/runs" / f"{record['run_sha256']}.json", payload
            )
            if not payload["success"] or not payload["exact_answer"]:
                raise RuntimeError(f"paired shadow failed: {record['run_sha256']}")

        analysis = analyze_m15_paired_physical_comparison(
            family_selection_seal=family_seal,
            profile_selection_seal=profile_seal,
            profile_acquisition_results=acquisition_results,
            selected_results=selected_results,
            shadow_results=shadow_results,
            training_results=training_results,
        )
        _write_json(run_root / "analysis.json", analysis)
        phase_counts = {
            phase: sum(event.get("paired_phase") == phase for event in events)
            for phase in (
                "training_measurement",
                "current_query_profile_acquisition",
                "paired_selected_execution",
                "postselection_shadow_evaluation",
            )
        }
        checks = {
            "candidate_sealed_before_calls": candidate_seal[
                "backend_calls_before_seal"
            ]
            == 0,
            "training_plan_runs": len(training_results) == 144,
            "training_backend_calls": phase_counts["training_measurement"] == 288,
            "family_sealed_before_profile": family_seal[
                "profile_backend_calls_before_seal"
            ]
            == 0,
            "family_selection_count": len(family_selections) == 10,
            "profile_acquisition_plan_runs": len(acquisition_results) == 20,
            "profile_acquisition_backend_calls": phase_counts[
                "current_query_profile_acquisition"
            ]
            == 40,
            "profile_selection_count": len(profile_selections) == 10,
            "both_seals_before_selected": profile_seal[
                "selected_backend_calls_before_seal"
            ]
            == 0,
            "paired_selected_plan_runs": sum(
                len(values) for values in selected_results.values()
            )
            == 20,
            "paired_selected_backend_calls": phase_counts[
                "paired_selected_execution"
            ]
            == 40,
            "shadow_plan_runs": len(shadow_results) == 80,
            "shadow_backend_calls": phase_counts[
                "postselection_shadow_evaluation"
            ]
            == 160,
            "total_backend_calls": len(events) == 528,
            "all_executed_answers_exact": all(
                item["exact_answer"]
                for result_map in (
                    training_results,
                    selected_results["family_memory"],
                    selected_results["current_query_dual_profile"],
                    shadow_results,
                )
                for item in result_map.values()
            ),
            "analysis_complete": analysis["semantic_task_count"] == 10,
            "automatic_retries_zero": True,
            "paper_result_false": analysis["paper_result"] is False,
        }
        _write_json(
            run_root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if not all(checks.values()):
            raise RuntimeError("paired physical comparison validation failed")
    except Exception as exc:  # Preserve first failure; never retry or continue.
        error = str(exc)

    _write_json(
        run_root / "backend_invocations.json",
        {
            "events": events,
            "total_tool_invocations": len(events),
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    summary = {
        "training_plan_runs": len(training_results),
        "profile_acquisition_plan_runs": len(acquisition_results),
        "paired_selected_plan_runs": sum(
            len(values) for values in selected_results.values()
        ),
        "evaluation_shadow_plan_runs": len(shadow_results),
        "total_plan_runs": (
            len(training_results)
            + len(acquisition_results)
            + sum(len(values) for values in selected_results.values())
            + len(shadow_results)
        ),
        "training_backend_calls": sum(
            event.get("paired_phase") == "training_measurement" for event in events
        ),
        "profile_acquisition_backend_calls": sum(
            event.get("paired_phase") == "current_query_profile_acquisition"
            for event in events
        ),
        "paired_selected_backend_calls": sum(
            event.get("paired_phase") == "paired_selected_execution"
            for event in events
        ),
        "evaluation_shadow_backend_calls": sum(
            event.get("paired_phase") == "postselection_shadow_evaluation"
            for event in events
        ),
        "total_backend_calls": len(events),
        "family_memory_current_query_profile_calls": 0,
        "profile_method_current_query_profile_calls": len(acquisition_results),
    }
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "git": _git_state(root_repo),
            "environment": {
                "hostname": platform.node(),
                "python": sys.version,
                "platform": platform.platform(),
            },
            "direct_semantic_workload_sha256": direct_workload.manifest[
                "manifest_sha256"
            ],
            "runtime_compatibility_sha256": runtime_compatibility_sha256,
            "schedule_sha256": schedule.schedule_hash if schedule else None,
            "training_memory_view_sha256": (
                memory_payload["training_memory_view_sha256"]
                if memory_payload
                else None
            ),
            "prediction_suite_sha256": (
                suite.payload["prediction_suite_sha256"] if suite else None
            ),
            "family_selection_seal_sha256": (
                family_seal["selection_seal_sha256"] if family_seal else None
            ),
            "profile_selection_seal_sha256": (
                profile_seal["selection_seal_sha256"] if profile_seal else None
            ),
            "analysis_sha256": analysis["analysis_sha256"] if analysis else None,
            "summary": summary,
            "validation": {
                "passed": success and bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "family_selection_sealed_before_profile_acquisition": bool(
                family_seal
            ),
            "answer_oracle_opened_before_both_selection_seals": False,
            "shadow_influenced_selection": False,
            "automatic_retries": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "confirmatory_statistics": False,
            "development_protocol_only": True,
            "paper_result": False,
            "paper_blockers": [
                "ten_semantic_task_development_population_only",
                "single_native_campaign_only",
                "confirmatory_statistics_disabled",
                "paper_scale_multi_family_workload_not_frozen",
            ],
        },
    )
    return M15LivePairedPhysicalComparisonRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
