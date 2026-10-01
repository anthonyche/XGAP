"""Execute the frozen F2C12 current-query profiling development baseline."""

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
from xgap.experiments.m15_current_query_profile_baseline import (
    M15CurrentQueryProfileBaselineSchedule,
    compile_m15_current_query_profile_baseline_schedule,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticCandidateSet,
    build_m15_variable_direct_semantic_candidate_set,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
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


LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION = (
    "m15-f2c12b-live-current-query-profile-baseline-v1"
)
CURRENT_QUERY_PROFILE_SELECTION_SEAL_SCHEMA_VERSION = (
    "m15-f2c12b-current-query-profile-selection-seal-v1"
)
CURRENT_QUERY_PROFILE_ANALYSIS_SCHEMA_VERSION = (
    "m15-f2c12b-current-query-profile-analysis-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")


@dataclass(frozen=True)
class M15LiveCurrentQueryProfileBaselineRecord:
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


def _json_text(value: object) -> str:
    return json.dumps(
        value,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_json_text(value), encoding="utf-8")
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
    query_ids = sorted(direct_workload.heldout_selection_view["base_query_ids"])
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
    result: dict[str, Any] = {}
    for candidates in candidate_sets.values():
        for plan_id, plan in candidates.plans.items():
            if plan_id in result:
                raise ValueError("profile-baseline plan IDs are not unique")
            result[plan_id] = plan
    return result


def _task_index(workload: M15DirectSemanticWorkloadBundle) -> dict[str, dict[str, Any]]:
    tasks = {
        str(item["semantic_task_id"]): dict(item)
        for item in workload.heldout_selection_view["semantic_tasks"]
    }
    if len(tasks) != 10:
        raise ValueError("profile baseline requires ten held-out semantic tasks")
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
        event["profile_baseline_phase"] = record["phase"]
        event["profile_baseline_run_id"] = record.get("run_sha256") or record.get(
            "slot_id"
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
    return result


def _summary(values: Sequence[float]) -> dict[str, float]:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("profile analysis requires finite nonempty values")
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
            raise ValueError("profile shadow result is not successful and exact")
        grouped.setdefault(str(result["plan_id"]), []).append(result)
    if len(grouped) != 20 or any(len(items) != 4 for items in grouped.values()):
        raise ValueError("profile shadows do not cover 20 plans four times")
    return {
        plan_id: {
            "latency_ms": float(
                statistics.median(item["elapsed_ms"] for item in items)
            ),
            "total_bytes_moved": float(
                statistics.median(item["total_bytes_moved"] for item in items)
            ),
        }
        for plan_id, items in grouped.items()
    }


def analyze_m15_current_query_profile_baseline(
    *,
    selection_seal: Mapping[str, Any],
    acquisition_results: Mapping[str, Mapping[str, Any]],
    selected_results: Mapping[str, Mapping[str, Any]],
    shadow_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate the sealed profile choices without changing them."""

    medians = _shadow_medians(shadow_results)
    acquisitions_by_task: dict[str, list[Mapping[str, Any]]] = {}
    for item in acquisition_results.values():
        acquisitions_by_task.setdefault(str(item["semantic_task_id"]), []).append(item)
    selected_by_task = {
        str(item["semantic_task_id"]): item for item in selected_results.values()
    }
    records: list[dict[str, Any]] = []
    for selection in selection_seal["selections"]:
        task_id = str(selection["semantic_task_id"])
        candidates = list(selection["candidate_plan_ids"])
        if len(candidates) != 2 or len(acquisitions_by_task.get(task_id, [])) != 2:
            raise ValueError("profile analysis task coverage changed")
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
        selected_plan = str(selection["selected_plan_id"])
        selected_result = selected_by_task[task_id]
        if selected_result["plan_id"] != selected_plan:
            raise ValueError("selected execution differs from sealed profile choice")
        acquisition_latency = sum(
            float(item["elapsed_ms"]) for item in acquisitions_by_task[task_id]
        )
        acquisition_bytes = sum(
            float(item["total_bytes_moved"])
            for item in acquisitions_by_task[task_id]
        )
        records.append(
            {
                "semantic_task_id": task_id,
                "base_query_id": selection["base_query_id"],
                "semantic_class_id": selection["semantic_class_id"],
                "selected_plan_id": selected_plan,
                "selected_strategy": selection["selected_strategy"],
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
                "acquisition_latency_ms": acquisition_latency,
                "acquisition_bytes": acquisition_bytes,
                "selected_execution_latency_ms": float(
                    selected_result["elapsed_ms"]
                ),
                "selected_execution_bytes": float(
                    selected_result["total_bytes_moved"]
                ),
                "end_to_end_latency_ms": (
                    acquisition_latency + float(selected_result["elapsed_ms"])
                ),
                "end_to_end_bytes": (
                    acquisition_bytes
                    + float(selected_result["total_bytes_moved"])
                ),
            }
        )
    if len(records) != 10:
        raise ValueError("profile analysis requires ten semantic tasks")
    body = {
        "schema_version": CURRENT_QUERY_PROFILE_ANALYSIS_SCHEMA_VERSION,
        "method_id": "current_query_dual_profile",
        "semantic_task_count": 10,
        "physical_winner_accuracy": {
            "correct_count": sum(item["winner_correct"] for item in records),
            "accuracy": sum(item["winner_correct"] for item in records) / 10,
        },
        "selected_plan_latency_regret_ms": _summary(
            [item["selected_plan_latency_regret_ms"] for item in records]
        ),
        "selected_plan_bytes_regret": _summary(
            [item["selected_plan_bytes_regret"] for item in records]
        ),
        "acquisition_latency_ms": _summary(
            [item["acquisition_latency_ms"] for item in records]
        ),
        "acquisition_bytes": _summary(
            [item["acquisition_bytes"] for item in records]
        ),
        "end_to_end_latency_ms": _summary(
            [item["end_to_end_latency_ms"] for item in records]
        ),
        "end_to_end_bytes": _summary(
            [item["end_to_end_bytes"] for item in records]
        ),
        "per_semantic_task": records,
        "selection_source": "sealed_current_query_profile_costs_only",
        "shadow_measurements_used_for_evaluation_only": True,
        "current_query_profile_operations": 20,
        "current_query_profile_backend_calls": 40,
        "training_memory_used": False,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "confirmatory_statistics": False,
        "paper_result": False,
    }
    return {**body, "analysis_sha256": content_hash(body)}


def run_m15_live_current_query_profile_baseline(
    *,
    direct_workload: M15DirectSemanticWorkloadBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    protocol: Mapping[str, Any] | str | Path,
    clients: Mapping[str, BackendClient],
    output_root: str | Path,
    run_id: str = "current-query-profile-baseline-run",
    repo_root: str | Path | None = None,
) -> M15LiveCurrentQueryProfileBaselineRecord:
    """Run the finite development baseline once, stopping on first failure."""

    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError("profile baseline requires neo4j and fuseki clients")
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
            "schema_version": LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    error: str | None = None
    events: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    acquisition_results: dict[str, dict[str, Any]] = {}
    selected_results: dict[str, dict[str, Any]] = {}
    shadow_results: dict[str, dict[str, Any]] = {}
    selection_seal: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    schedule: M15CurrentQueryProfileBaselineSchedule | None = None
    checks: dict[str, bool] = {}
    try:
        schedule = compile_m15_current_query_profile_baseline_schedule(
            workload=direct_workload, protocol=protocol
        )
        _write_json(run_root / "profile_schedule.json", schedule.to_dict())
        for backend_id in ("neo4j", "fuseki"):
            timeout = getattr(clients[backend_id], "timeout_seconds", 60.0)
            if float(timeout) != 60.0:
                raise ValueError("backend timeout must be exactly 60 seconds")
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        if not all(item["ok"] for item in health.values()):
            raise RuntimeError("profile baseline backend healthcheck failed")

        candidates = _candidate_sets(
            direct_workload=direct_workload,
            base_bundle=base_bundle,
            catalog=catalog,
            mapping=mapping,
        )
        plans = _plan_index(candidates)
        tasks = _task_index(direct_workload)
        scheduler = FederatedScheduler(_backend_tool(clients, events))
        candidate_seal_body = {
            "schema_version": "m15-f2c12b-profile-candidate-seal-v1",
            "schedule_sha256": schedule.schedule_hash,
            "candidate_plan_ids": sorted(plans),
            "candidate_count": len(plans),
            "sealed_before_profile_calls": True,
            "backend_calls_before_seal": len(events),
            "answer_oracle_fields": [],
        }
        candidate_seal = {
            **candidate_seal_body,
            "candidate_seal_sha256": content_hash(candidate_seal_body),
        }
        _write_json(run_root / "candidate_seal.json", candidate_seal)

        for record in schedule.payload["acquisition_runs"]:
            result = _execute(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:profile:{record['run_sha256']}",
            )
            payload = {
                **dict(record),
                "success": result.success,
                "elapsed_ms": result.elapsed_ms,
                "total_bytes_moved": result.total_bytes_moved,
                "total_remote_calls": result.total_remote_calls,
                "runtime_result": result.to_dict(),
                "answer_oracle_opened": False,
            }
            acquisition_results[record["run_sha256"]] = payload
            _write_json(
                run_root / "acquisition" / "runs" / f"{record['run_sha256']}.json",
                payload,
            )
            if not result.success:
                raise RuntimeError(
                    f"profile acquisition failed: {record['run_sha256']}"
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
            "schema_version": "m15-f2c12b-profile-cost-estimates-v1",
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
        _write_json(run_root / "profile_cost_estimates.json", estimate_source)

        selections: list[dict[str, Any]] = []
        estimates_by_plan = {item["plan_id"]: item for item in estimates}
        for slot in schedule.payload["selection_slots"]:
            selected_plan_id = min(
                slot["candidate_plan_ids"],
                key=lambda plan_id: (
                    estimates_by_plan[plan_id]["elapsed_ms"],
                    estimates_by_plan[plan_id]["total_bytes_moved"],
                    plan_id,
                ),
            )
            task = tasks[slot["semantic_task_id"]]
            selected_estimate = estimates_by_plan[selected_plan_id]
            selections.append(
                {
                    **dict(slot),
                    "base_query_id": task["base_query_id"],
                    "query_id": selected_estimate["query_id"],
                    "selected_plan_id": selected_plan_id,
                    "selected_strategy": selected_estimate["physical_strategy"],
                    "selected_profile_elapsed_ms": selected_estimate["elapsed_ms"],
                    "selected_profile_total_bytes_moved": selected_estimate[
                        "total_bytes_moved"
                    ],
                }
            )
        seal_body = {
            "schema_version": CURRENT_QUERY_PROFILE_SELECTION_SEAL_SCHEMA_VERSION,
            "schedule_sha256": schedule.schedule_hash,
            "candidate_seal_sha256": candidate_seal["candidate_seal_sha256"],
            "estimate_source_sha256": estimate_source["estimate_source_sha256"],
            "selections": selections,
            "selection_count": len(selections),
            "profile_backend_calls_before_seal": len(events),
            "selected_execution_backend_calls_before_seal": 0,
            "shadow_backend_calls_before_seal": 0,
            "answer_oracle_opened_before_seal": False,
            "selection_input_fields": [
                "elapsed_ms",
                "total_bytes_moved",
                "plan_id",
            ],
            "answer_rows_selection_input": False,
        }
        selection_seal = {
            **seal_body,
            "selection_seal_sha256": content_hash(seal_body),
        }
        _write_json(run_root / "selection_seal.json", selection_seal)

        acquisition_validation: list[dict[str, Any]] = []
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
            run_root / "acquisition_validation.json",
            {
                "opened_after_selection_seal": True,
                "results": acquisition_validation,
                "all_exact": all(item["exact_answer"] for item in acquisition_validation),
            },
        )
        if not all(item["exact_answer"] for item in acquisition_validation):
            raise RuntimeError("profile acquisition answer validation failed")

        selections_by_task = {
            item["semantic_task_id"]: item for item in selections
        }
        for slot in schedule.payload["selected_execution_slots"]:
            selection = selections_by_task[slot["semantic_task_id"]]
            record = {
                **dict(slot),
                "base_query_id": selection["base_query_id"],
                "query_id": selection["query_id"],
                "plan_id": selection["selected_plan_id"],
                "physical_strategy": selection["selected_strategy"],
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
            payload = {
                **record,
                "success": result.success,
                "exact_answer": list(result.final_rows) == expected,
                "elapsed_ms": result.elapsed_ms,
                "total_bytes_moved": result.total_bytes_moved,
                "total_remote_calls": result.total_remote_calls,
                "runtime_result": result.to_dict(),
            }
            selected_results[slot["slot_id"]] = payload
            _write_json(run_root / "selected" / f"{slot['slot_id']}.json", payload)
            if not payload["success"] or not payload["exact_answer"]:
                raise RuntimeError(f"selected profile plan failed: {slot['slot_id']}")

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
            payload = {
                **dict(record),
                "success": result.success,
                "exact_answer": list(result.final_rows) == expected,
                "elapsed_ms": result.elapsed_ms,
                "total_bytes_moved": result.total_bytes_moved,
                "total_remote_calls": result.total_remote_calls,
                "runtime_result": result.to_dict(),
            }
            shadow_results[record["run_sha256"]] = payload
            _write_json(
                run_root / "shadow" / "runs" / f"{record['run_sha256']}.json",
                payload,
            )
            if not payload["success"] or not payload["exact_answer"]:
                raise RuntimeError(f"profile shadow failed: {record['run_sha256']}")

        analysis = analyze_m15_current_query_profile_baseline(
            selection_seal=selection_seal,
            acquisition_results=acquisition_results,
            selected_results=selected_results,
            shadow_results=shadow_results,
        )
        _write_json(run_root / "analysis.json", analysis)
        phase_counts = {
            phase: sum(
                event.get("profile_baseline_phase") == phase for event in events
            )
            for phase in (
                "current_query_profile_acquisition",
                "selected_plan_execution",
                "postselection_shadow_evaluation",
            )
        }
        checks = {
            "candidate_sealed_before_calls": candidate_seal[
                "backend_calls_before_seal"
            ]
            == 0,
            "acquisition_plan_count": len(acquisition_results) == 20,
            "acquisition_backend_call_count": phase_counts[
                "current_query_profile_acquisition"
            ]
            == 40,
            "selection_sealed_before_oracle": selection_seal[
                "answer_oracle_opened_before_seal"
            ]
            is False,
            "selection_is_cost_only": selection_seal[
                "answer_rows_selection_input"
            ]
            is False,
            "selected_plan_count": len(selected_results) == 10,
            "selected_backend_call_count": phase_counts["selected_plan_execution"]
            == 20,
            "shadow_plan_count": len(shadow_results) == 80,
            "shadow_backend_call_count": phase_counts[
                "postselection_shadow_evaluation"
            ]
            == 160,
            "total_backend_call_count": len(events) == 220,
            "analysis_complete": analysis["semantic_task_count"] == 10,
            "automatic_retries_zero": True,
            "paper_result_false": analysis["paper_result"] is False,
        }
        _write_json(
            run_root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if not all(checks.values()):
            raise RuntimeError("current-query profile baseline validation failed")
    except Exception as exc:  # Preserve the first failure; never retry.
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
            "schema_version": LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    summary = {
        "acquisition_plan_runs": len(acquisition_results),
        "selected_plan_runs": len(selected_results),
        "evaluation_shadow_plan_runs": len(shadow_results),
        "total_plan_runs": (
            len(acquisition_results) + len(selected_results) + len(shadow_results)
        ),
        "acquisition_backend_calls": sum(
            event.get("profile_baseline_phase")
            == "current_query_profile_acquisition"
            for event in events
        ),
        "selected_plan_backend_calls": sum(
            event.get("profile_baseline_phase") == "selected_plan_execution"
            for event in events
        ),
        "evaluation_shadow_backend_calls": sum(
            event.get("profile_baseline_phase")
            == "postselection_shadow_evaluation"
            for event in events
        ),
        "total_backend_calls": len(events),
    }
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION,
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
            "schedule_sha256": schedule.schedule_hash if schedule else None,
            "selection_seal_sha256": (
                selection_seal["selection_seal_sha256"]
                if selection_seal
                else None
            ),
            "analysis_sha256": analysis["analysis_sha256"] if analysis else None,
            "summary": summary,
            "validation": {
                "passed": success and bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "profile_operation_semantics": (
                "full_federated_plan_execution_labeled_profile"
            ),
            "selection_input": "sealed_profile_costs_only",
            "answer_oracle_opened_before_selection_seal": False,
            "shadow_influenced_selection": False,
            "training_memory_used": False,
            "automatic_retries": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "confirmatory_statistics": False,
            "development_protocol_only": True,
            "paper_result": False,
            "paper_blockers": [
                "ten_semantic_task_development_population_only",
                "single_native_campaign_only",
                "cross_allocation_comparison_forbidden",
                "confirmatory_statistics_disabled",
            ],
        },
    )
    return M15LiveCurrentQueryProfileBaselineRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
