"""Execute the frozen F2C10D option-A family-memory development pilot.

Training measurements are completed and admitted before family memory is
frozen.  Held-out predictions and semantic frontiers are then sealed before
the first held-out oracle access or backend call.  Online selected-plan calls
and post-selection shadow calls are persisted and accounted separately.
"""

from __future__ import annotations

import hashlib
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
from xgap.experiments.m15_direct_family_pilot import (
    M15DirectFamilyPilotSchedule,
    compile_m15_direct_family_pilot_schedule,
)
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectFamilyPredictionSuite,
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticCandidateSet,
    build_m15_variable_direct_semantic_candidate_set,
    select_m15_direct_semantic_frontier,
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


LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION = (
    "m15-f2c10d-live-direct-family-pilot-v1"
)
DIRECT_FAMILY_PILOT_SELECTION_SEAL_SCHEMA_VERSION = (
    "m15-f2c10d-direct-family-pilot-selection-seal-v1"
)
DIRECT_FAMILY_PILOT_ANALYSIS_SCHEMA_VERSION = (
    "m15-f2c10d-direct-family-pilot-analysis-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")


@dataclass(frozen=True)
class M15LiveDirectFamilyPilotRecord:
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _within_count_range(value: int, expected: Mapping[str, Any]) -> bool:
    return int(expected["minimum"]) <= value <= int(expected["maximum"])


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
    result: dict[str, Any] = {}
    for candidates in candidate_sets.values():
        for plan_id, plan in candidates.plans.items():
            if plan_id in result:
                raise ValueError("direct-family pilot plan IDs are not unique")
            result[plan_id] = plan
    return result


def _execute_scheduled_plan(
    *,
    scheduler: FederatedScheduler,
    plan: Any,
    record: Mapping[str, Any],
    events: list[dict[str, Any]],
    goal_id: str,
) -> Any:
    first_event = len(events)
    result = scheduler.execute(plan, goal_id=goal_id)
    new_events = events[first_event:]
    for index, event in enumerate(new_events, start=1):
        event["pilot_phase"] = record["phase"]
        event["pilot_run_id"] = record.get("run_id") or record.get("slot_id")
        event["phase_call_index"] = index
        event["semantic_task_id"] = record["semantic_task_id"]
        event["base_query_id"] = record["base_query_id"]
        event["query_id"] = record["query_id"]
        event["semantic_class_id"] = record["semantic_class_id"]
        event["plan_id"] = record["plan_id"]
        event["physical_strategy"] = record["physical_strategy"]
    return result


def _training_observations(
    schedule: M15DirectFamilyPilotSchedule,
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


def _persist_selection(
    *,
    root: Path,
    schedule: M15DirectFamilyPilotSchedule,
    training_results: Mapping[str, Mapping[str, Any]],
    raw_observations: Sequence[Mapping[str, Any]],
    memory: Mapping[str, Any],
    suite: M15DirectFamilyPredictionSuite,
    events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    selection_root = root / "selection"
    _write_json(selection_root / "pilot_schedule.json", schedule.to_dict())
    _write_json(
        selection_root / "training_observations.json",
        {"observations": list(raw_observations)},
    )
    _write_json(selection_root / "training_memory_view.json", memory)
    _write_json(selection_root / "prediction_suite.json", suite.to_dict())
    frontiers: dict[str, dict[str, Any]] = {}
    query_records: list[dict[str, Any]] = []
    for query_id in sorted(suite.sources):
        query_root = selection_root / "queries" / query_id
        candidates = suite.candidate_sets[query_id]
        source = suite.sources[query_id]
        snapshot = source.to_snapshot(candidates)
        frontier = select_m15_direct_semantic_frontier(candidates, snapshot)
        artifacts = {
            "candidate_set.json": candidates.to_dict(),
            "prediction_source.json": source.to_dict(),
            "estimate_snapshot.json": snapshot.to_dict(),
            "semantic_frontier.json": frontier.to_dict(),
        }
        for filename, payload in artifacts.items():
            _write_json(query_root / filename, payload)
        frontiers[query_id] = frontier.to_dict()
        query_records.append(
            {
                "base_query_id": query_id,
                "candidate_set_sha256": candidates.candidate_set_hash,
                "prediction_source_sha256": source.source_hash,
                "estimate_snapshot_sha256": snapshot.snapshot_hash,
                "frontier_sha256": frontier.payload["frontier_sha256"],
                "returned_semantic_plan_count": frontier.payload["counts"][
                    "returned_semantic_plans"
                ],
            }
        )
    returned_count = sum(
        item["returned_semantic_plan_count"] for item in query_records
    )
    expected_returned = schedule.payload["counts"]["online_selected_plan_runs"]
    cardinality = schedule.payload["selection_boundary"]["online_cardinality"]
    maximum_per_query = int(cardinality["maximum_per_query"])
    if not _within_count_range(returned_count, expected_returned):
        raise RuntimeError("measured family-memory frontier is outside online bounds")
    if any(
        not 1 <= int(item["returned_semantic_plan_count"]) <= maximum_per_query
        for item in query_records
    ):
        raise RuntimeError("per-query semantic frontier is outside online bounds")
    selection_files = sorted(selection_root.rglob("*.json"))
    training_files = sorted((root / "training" / "runs").glob("*.json"))
    body = {
        "schema_version": DIRECT_FAMILY_PILOT_SELECTION_SEAL_SCHEMA_VERSION,
        "schedule_sha256": schedule.schedule_hash,
        "selection_files_sha256": {
            str(path.relative_to(root)): _sha256_file(path)
            for path in selection_files
        },
        "training_evidence_files_sha256": {
            str(path.relative_to(root)): _sha256_file(path)
            for path in training_files
        },
        "training_memory_view_sha256": memory["training_memory_view_sha256"],
        "prediction_suite_sha256": suite.payload["prediction_suite_sha256"],
        "query_frontiers": query_records,
        "online_cardinality": dict(cardinality),
        "returned_semantic_plan_count": returned_count,
        "sealed_before_heldout_oracle_access": True,
        "training_backend_calls_before_seal": len(events),
        "online_backend_calls_before_seal": 0,
        "shadow_backend_calls_before_seal": 0,
        "current_query_profile_calls": 0,
        "heldout_answer_oracle_fields": [],
        "training_oracle_use": "postexecution_exact_admission_only",
        "post_execution_measurements_used_for_selection": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    seal = {**body, "selection_seal_sha256": content_hash(body)}
    _write_json(root / "selection_seal.json", seal)
    return seal, frontiers


def _dominates(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    left = (
        float(first["semantic_deviation"]),
        float(first["observed_median_elapsed_ms"]),
        float(first["observed_median_total_bytes_moved"]),
    )
    right = (
        float(second["semantic_deviation"]),
        float(second["observed_median_elapsed_ms"]),
        float(second["observed_median_total_bytes_moved"]),
    )
    return all(a <= b for a, b in zip(left, right, strict=True)) and any(
        a < b for a, b in zip(left, right, strict=True)
    )


def _relative_gain(reference: float, candidate: float) -> float:
    if reference == 0:
        return 0.0 if candidate == 0 else -math.inf
    return (reference - candidate) / reference


def _observed_returned_classes(
    *,
    candidates: M15DirectSemanticCandidateSet,
    observations: Mapping[str, Mapping[str, float]],
) -> tuple[list[str], list[dict[str, Any]]]:
    payload = candidates.payload
    classes = {
        item["semantic_class_id"]: item for item in payload["semantic_classes"]
    }
    physical: list[dict[str, Any]] = []
    for class_id in sorted(classes):
        plans = [
            item
            for item in payload["physical_candidates"]
            if item["semantic_class_id"] == class_id
        ]
        enriched = [
            {
                **dict(item),
                "semantic_deviation": classes[class_id]["semantic_deviation"],
                "observed_median_elapsed_ms": observations[item["plan_id"]][
                    "median_elapsed_ms"
                ],
                "observed_median_total_bytes_moved": observations[item["plan_id"]][
                    "median_total_bytes_moved"
                ],
            }
            for item in plans
        ]
        physical.append(
            min(
                enriched,
                key=lambda item: (
                    item["observed_median_elapsed_ms"],
                    item["observed_median_total_bytes_moved"],
                    item["plan_id"],
                ),
            )
        )
    pareto = [
        item
        for item in physical
        if not any(
            _dominates(other, item)
            for other in physical
            if other["semantic_class_id"] != item["semantic_class_id"]
        )
    ]
    policy = payload["frontier_policy"]
    epsilon: list[dict[str, Any]] = []
    for item in pareto:
        remove = False
        for reference in pareto:
            if reference["semantic_deviation"] >= item["semantic_deviation"]:
                continue
            latency_gain = _relative_gain(
                float(reference["observed_median_elapsed_ms"]),
                float(item["observed_median_elapsed_ms"]),
            )
            bytes_gain = _relative_gain(
                float(reference["observed_median_total_bytes_moved"]),
                float(item["observed_median_total_bytes_moved"]),
            )
            if (
                latency_gain < float(policy["minimum_latency_gain_ratio"])
                and bytes_gain < float(policy["minimum_resource_gain_ratio"])
            ):
                remove = True
                break
        if not remove:
            epsilon.append(item)
    if not epsilon:
        raise RuntimeError("observed semantic frontier removed every class")

    maximum = int(policy["max_representatives"])
    selected: list[dict[str, Any]] = []
    for key in (
        lambda item: (
            item["semantic_deviation"],
            item["observed_median_elapsed_ms"],
            item["observed_median_total_bytes_moved"],
            item["plan_id"],
        ),
        lambda item: (
            item["observed_median_elapsed_ms"],
            item["observed_median_total_bytes_moved"],
            item["semantic_deviation"],
            item["plan_id"],
        ),
        lambda item: (
            item["observed_median_total_bytes_moved"],
            item["observed_median_elapsed_ms"],
            item["semantic_deviation"],
            item["plan_id"],
        ),
    ):
        candidate = min(epsilon, key=key)
        if candidate["semantic_class_id"] not in {
            value["semantic_class_id"] for value in selected
        }:
            selected.append(candidate)
    # K is four and the current direct classes are at most six.  If the three
    # deterministic extremes do not fill K, maximize minimum normalized
    # Euclidean distance exactly as the online selector does.
    fields = (
        "semantic_deviation",
        "observed_median_elapsed_ms",
        "observed_median_total_bytes_moved",
    )
    bounds = {
        field: (
            min(float(item[field]) for item in epsilon),
            max(float(item[field]) for item in epsilon),
        )
        for field in fields
    }
    vectors = {
        item["semantic_class_id"]: tuple(
            0.0
            if bounds[field][0] == bounds[field][1]
            else (float(item[field]) - bounds[field][0])
            / (bounds[field][1] - bounds[field][0])
            for field in fields
        )
        for item in epsilon
    }
    while len(selected) < maximum:
        remaining = [
            item
            for item in epsilon
            if item["semantic_class_id"]
            not in {value["semantic_class_id"] for value in selected}
        ]
        if not remaining:
            break
        selected.append(
            min(
                remaining,
                key=lambda item: (
                    -min(
                        math.sqrt(
                            sum(
                                (left - right) ** 2
                                for left, right in zip(
                                    vectors[item["semantic_class_id"]],
                                    vectors[chosen["semantic_class_id"]],
                                    strict=True,
                                )
                            )
                        )
                        for chosen in selected
                    ),
                    item["plan_id"],
                ),
            )
        )
    return [item["semantic_class_id"] for item in selected], physical


def _error_summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "mae": sum(abs(value) for value in values) / len(values),
        "median_absolute_error": float(statistics.median(abs(value) for value in values)),
        "rmse": math.sqrt(sum(value * value for value in values) / len(values)),
    }


def analyze_m15_direct_family_pilot(
    *,
    suite: M15DirectFamilyPredictionSuite,
    frontiers: Mapping[str, Mapping[str, Any]],
    shadow_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute the predeclared development diagnostics after all shadow runs."""

    runs_by_plan: dict[str, list[Mapping[str, Any]]] = {}
    for result in shadow_results.values():
        runs_by_plan.setdefault(str(result["plan_id"]), []).append(result)
    predictions = {
        item["plan_id"]: item
        for source in suite.sources.values()
        for item in source.payload["predictions"]
    }
    if set(runs_by_plan) != set(predictions) or any(
        len(runs) != 4 for runs in runs_by_plan.values()
    ):
        raise RuntimeError("shadow results do not cover all held-out plans four times")
    observations: dict[str, dict[str, float]] = {}
    per_plan: list[dict[str, Any]] = []
    for plan_id in sorted(predictions):
        runs = runs_by_plan[plan_id]
        observed_latency = float(statistics.median(item["elapsed_ms"] for item in runs))
        observed_bytes = float(
            statistics.median(item["total_bytes_moved"] for item in runs)
        )
        observations[plan_id] = {
            "median_elapsed_ms": observed_latency,
            "median_total_bytes_moved": observed_bytes,
        }
        prediction = predictions[plan_id]
        per_plan.append(
            {
                "plan_id": plan_id,
                "semantic_class_id": prediction["semantic_class_id"],
                "physical_strategy": prediction["physical_strategy"],
                "predicted_latency_ms": prediction["estimated_latency_ms"],
                "observed_median_latency_ms": observed_latency,
                "latency_error_ms": prediction["estimated_latency_ms"] - observed_latency,
                "predicted_total_bytes_moved": prediction[
                    "estimated_total_bytes_moved"
                ],
                "observed_median_total_bytes_moved": observed_bytes,
                "bytes_error": prediction["estimated_total_bytes_moved"] - observed_bytes,
            }
        )
    latency_errors = [float(item["latency_error_ms"]) for item in per_plan]
    byte_errors = [float(item["bytes_error"]) for item in per_plan]

    class_records: list[dict[str, Any]] = []
    frontier_records: list[dict[str, Any]] = []
    for query_id in sorted(suite.candidate_sets):
        candidates = suite.candidate_sets[query_id]
        predicted = frontiers[query_id]
        predicted_representatives = {
            item["semantic_class_id"]: item
            for item in predicted["physical_representatives"]
        }
        observed_classes, observed_representatives = _observed_returned_classes(
            candidates=candidates,
            observations=observations,
        )
        observed_by_class = {
            item["semantic_class_id"]: item for item in observed_representatives
        }
        for class_id in sorted(predicted_representatives):
            predicted_plan = predicted_representatives[class_id]
            observed_plan = observed_by_class[class_id]
            selected_observed = observations[predicted_plan["plan_id"]]
            best_observed = observations[observed_plan["plan_id"]]
            class_records.append(
                {
                    "base_query_id": query_id,
                    "semantic_class_id": class_id,
                    "predicted_plan_id": predicted_plan["plan_id"],
                    "observed_winner_plan_id": observed_plan["plan_id"],
                    "winner_correct": predicted_plan["plan_id"]
                    == observed_plan["plan_id"],
                    "latency_regret_ms": selected_observed["median_elapsed_ms"]
                    - best_observed["median_elapsed_ms"],
                    "bytes_regret": selected_observed["median_total_bytes_moved"]
                    - best_observed["median_total_bytes_moved"],
                }
            )
        predicted_classes = [
            item["semantic_class_id"] for item in predicted["returned_semantic_plans"]
        ]
        intersection = sorted(set(predicted_classes) & set(observed_classes))
        union = sorted(set(predicted_classes) | set(observed_classes))
        frontier_records.append(
            {
                "base_query_id": query_id,
                "predicted_class_ids": predicted_classes,
                "observed_class_ids": observed_classes,
                "intersection_class_ids": intersection,
                "union_class_ids": union,
                "jaccard": len(intersection) / len(union),
            }
        )
    winner_count = sum(item["winner_correct"] for item in class_records)
    body = {
        "schema_version": DIRECT_FAMILY_PILOT_ANALYSIS_SCHEMA_VERSION,
        "per_plan_aggregation": "median_over_four_shadow_repetitions",
        "prediction_error": {
            "plan_count": len(per_plan),
            "latency_ms": _error_summary(latency_errors),
            "total_bytes_moved": _error_summary(byte_errors),
            "per_plan": per_plan,
        },
        "physical_winner_accuracy": {
            "semantic_class_count": len(class_records),
            "correct_count": winner_count,
            "accuracy": winner_count / len(class_records),
            "per_class": class_records,
        },
        "latency_regret_ms": _error_summary(
            [float(item["latency_regret_ms"]) for item in class_records]
        ),
        "bytes_regret": _error_summary(
            [float(item["bytes_regret"]) for item in class_records]
        ),
        "predicted_observed_frontier_overlap": {
            "per_query": frontier_records,
            "mean_jaccard": sum(item["jaccard"] for item in frontier_records)
            / len(frontier_records),
        },
        "current_query_profile_calls": 0,
        "shadow_used_for_selection": False,
        "confirmatory_statistics": False,
        "paper_result": False,
    }
    return {**body, "analysis_sha256": content_hash(body)}


def run_m15_live_direct_family_pilot(
    *,
    direct_workload: M15DirectSemanticWorkloadBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    protocol: Mapping[str, Any] | str | Path,
    predictor_policy: Mapping[str, Any] | str | Path,
    clients: Mapping[str, BackendClient],
    runtime_compatibility_sha256: str,
    output_root: str | Path,
    run_id: str = "direct-family-pilot-run",
    repo_root: str | Path | None = None,
) -> M15LiveDirectFamilyPilotRecord:
    """Run the bounded option-A development pilot once, without retry."""

    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError("direct family pilot requires neo4j and fuseki clients")
    if not re.fullmatch(r"[0-9a-f]{64}", runtime_compatibility_sha256):
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
            "schema_version": LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    error: str | None = None
    health: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    training_results: dict[str, dict[str, Any]] = {}
    online_results: dict[str, dict[str, Any]] = {}
    shadow_results: dict[str, dict[str, Any]] = {}
    checks: dict[str, bool] = {}
    selection_seal: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    memory_payload: dict[str, Any] | None = None
    suite: M15DirectFamilyPredictionSuite | None = None
    schedule: M15DirectFamilyPilotSchedule | None = None
    try:
        schedule = compile_m15_direct_family_pilot_schedule(
            workload=direct_workload,
            protocol=protocol,
            predictor_policy=predictor_policy,
        )
        _write_json(run_root / "pilot_schedule.json", schedule.to_dict())
        for backend_id in ("neo4j", "fuseki"):
            timeout = getattr(clients[backend_id], "timeout_seconds", 60.0)
            if float(timeout) != 60.0:
                raise ValueError("backend timeout must be exactly 60 seconds")
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        if not all(item["ok"] for item in health.values()):
            raise RuntimeError("direct family pilot backend healthcheck failed")

        candidates_by_query = _candidate_sets(
            direct_workload=direct_workload,
            base_bundle=base_bundle,
            catalog=catalog,
            mapping=mapping,
        )
        plans = _plan_index(candidates_by_query)
        scheduler = FederatedScheduler(_backend_tool(clients, events))

        for record in schedule.payload["training_runs"]:
            result = _execute_scheduled_plan(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:{record['run_id']}",
            )
            expected = load_m15_parameterized_instance(
                direct_workload.workload_bundle, record["query_id"]
            )["final_oracle"]
            exact = list(result.final_rows) == expected
            payload = {
                **dict(record),
                "success": result.success,
                "exact_answer": exact,
                "elapsed_ms": result.elapsed_ms,
                "total_bytes_moved": result.total_bytes_moved,
                "total_remote_calls": result.total_remote_calls,
                "runtime_result": result.to_dict(),
            }
            training_results[record["run_id"]] = payload
            _write_json(run_root / "training" / "runs" / f"{record['run_id']}.json", payload)
            if not result.success or not exact:
                raise RuntimeError(f"training plan failed: {record['run_id']}")

        raw_observations = _training_observations(schedule, training_results)
        _write_json(
            run_root / "training" / "training_observations.json",
            {"observations": raw_observations},
        )
        memory = build_m15_direct_training_memory_view(
            workload=direct_workload,
            raw_observations=raw_observations,
            runtime_compatibility_sha256=runtime_compatibility_sha256,
            policy=predictor_policy,
            measurement_source_kind="native_counterbalanced_development_pilot",
        )
        memory_payload = memory.to_dict()
        _write_json(run_root / "training" / "training_memory_view.json", memory_payload)
        suite = build_m15_direct_family_prediction_suite(
            workload=direct_workload,
            base_bundle=base_bundle,
            catalog=catalog,
            mapping=mapping,
            memory=memory,
            policy=predictor_policy,
        )
        selection_seal, frontiers = _persist_selection(
            root=run_root,
            schedule=schedule,
            training_results=training_results,
            raw_observations=raw_observations,
            memory=memory_payload,
            suite=suite,
            events=events,
        )

        online_records: list[dict[str, Any]] = []
        for query_id in sorted(frontiers):
            for selected in frontiers[query_id]["returned_semantic_plans"]:
                online_records.append(
                    {
                        "slot_id": schedule.payload["online_execution_slots"][
                            len(online_records)
                        ]["slot_id"],
                        "phase": "online_selected_execution",
                        "semantic_task_id": next(
                            item["semantic_task_id"]
                            for item in direct_workload.heldout_selection_view[
                                "semantic_tasks"
                            ]
                            if item["semantic_class_id"]
                            == selected["semantic_class_id"]
                        ),
                        "base_query_id": query_id,
                        "query_id": selected["query_id"],
                        "semantic_class_id": selected["semantic_class_id"],
                        "plan_id": selected["plan_id"],
                        "physical_strategy": selected["physical_strategy"],
                        "selection_rank": selected["selection_rank"],
                    }
                )
        if not _within_count_range(
            len(online_records),
            schedule.payload["counts"]["online_selected_plan_runs"],
        ):
            raise RuntimeError("online selection count changed after seal")
        for record in online_records:
            result = _execute_scheduled_plan(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:{record['slot_id']}",
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
            online_results[record["slot_id"]] = payload
            _write_json(run_root / "online" / f"{record['slot_id']}.json", payload)
            if not payload["success"] or not payload["exact_answer"]:
                raise RuntimeError(f"online selected plan failed: {record['slot_id']}")

        for record in schedule.payload["shadow_runs"]:
            result = _execute_scheduled_plan(
                scheduler=scheduler,
                plan=plans[record["plan_id"]],
                record=record,
                events=events,
                goal_id=f"{run_id}:{record['run_id']}",
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
            shadow_results[record["run_id"]] = payload
            _write_json(run_root / "shadow" / "runs" / f"{record['run_id']}.json", payload)
            if not payload["success"] or not payload["exact_answer"]:
                raise RuntimeError(f"shadow plan failed: {record['run_id']}")

        analysis = analyze_m15_direct_family_pilot(
            suite=suite,
            frontiers=frontiers,
            shadow_results=shadow_results,
        )
        _write_json(run_root / "analysis.json", analysis)
        phase_counts = {
            phase: sum(event.get("pilot_phase") == phase for event in events)
            for phase in (
                "training_measurement",
                "online_selected_execution",
                "postselection_shadow_evaluation",
            )
        }
        expected_counts = schedule.payload["counts"]
        actual_total_plan_runs = (
            len(training_results) + len(online_results) + len(shadow_results)
        )
        checks = {
            "training_plan_run_count": len(training_results) == 144,
            "training_backend_call_count": phase_counts["training_measurement"] == 288,
            "training_memory_frozen_after_complete_measurement": memory_payload[
                "training_physical_plan_count"
            ]
            == 36
            and all(item["repetition_count"] == 4 for item in memory_payload["observations"]),
            "selection_sealed_before_heldout_execution": selection_seal[
                "sealed_before_heldout_oracle_access"
            ]
            is True,
            "zero_current_query_profiles": selection_seal[
                "current_query_profile_calls"
            ]
            == 0,
            "online_plan_run_count": _within_count_range(
                len(online_results), expected_counts["online_selected_plan_runs"]
            ),
            "online_backend_call_count": phase_counts["online_selected_execution"]
            == 2 * len(online_results),
            "shadow_plan_run_count": len(shadow_results) == 80,
            "shadow_backend_call_count": phase_counts[
                "postselection_shadow_evaluation"
            ]
            == 160,
            "total_plan_run_count": _within_count_range(
                actual_total_plan_runs, expected_counts["total_plan_runs"]
            ),
            "total_backend_call_count": _within_count_range(
                len(events), expected_counts["total_backend_calls"]
            )
            and len(events) == 2 * actual_total_plan_runs,
            "all_answers_exact": all(
                item["exact_answer"]
                for values in (training_results, online_results, shadow_results)
                for item in values.values()
            ),
            "analysis_complete": set(analysis)
            >= {
                "prediction_error",
                "physical_winner_accuracy",
                "latency_regret_ms",
                "bytes_regret",
                "predicted_observed_frontier_overlap",
            },
            "automatic_retries_zero": True,
            "paper_result_false": analysis["paper_result"] is False,
        }
        _write_json(run_root / "validation.json", {"passed": all(checks.values()), "checks": checks})
        if not all(checks.values()):
            raise RuntimeError("direct family pilot validation failed")
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
            "schema_version": LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    summary = {
        "training_plan_runs": len(training_results),
        "online_selected_plan_runs": len(online_results),
        "evaluation_shadow_plan_runs": len(shadow_results),
        "total_plan_runs": len(training_results) + len(online_results) + len(shadow_results),
        "training_backend_calls": sum(
            event.get("pilot_phase") == "training_measurement" for event in events
        ),
        "online_backend_calls": sum(
            event.get("pilot_phase") == "online_selected_execution" for event in events
        ),
        "evaluation_shadow_backend_calls": sum(
            event.get("pilot_phase") == "postselection_shadow_evaluation"
            for event in events
        ),
        "total_backend_calls": len(events),
        "current_query_profile_calls": 0,
    }
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION,
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
            "selection_seal_sha256": (
                selection_seal["selection_seal_sha256"] if selection_seal else None
            ),
            "training_memory_view_sha256": (
                memory_payload["training_memory_view_sha256"]
                if memory_payload
                else None
            ),
            "prediction_suite_sha256": (
                suite.payload["prediction_suite_sha256"] if suite else None
            ),
            "analysis_sha256": analysis["analysis_sha256"] if analysis else None,
            "summary": summary,
            "validation": {
                "passed": success and bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "selection_sealed_before_heldout_execution": bool(selection_seal),
            "training_oracle_use": "postexecution_exact_admission_only",
            "heldout_oracle_use": "postselection_postexecution_validation_only",
            "shadow_influenced_selection": False,
            "current_query_observation_operations": [],
            "automatic_retries": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "confirmatory_statistics": False,
            "development_pilot_only": True,
            "paper_result": False,
            "paper_blockers": [
                "six_query_development_population_only",
                "single_native_campaign_only",
                "confirmatory_statistics_disabled",
                "paper_scale_30_to_50_query_workload_not_frozen",
            ],
            "artifacts": sorted(
                str(path.relative_to(run_root))
                for path in run_root.rglob("*")
                if path.is_file()
            ),
        },
    )
    return M15LiveDirectFamilyPilotRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
