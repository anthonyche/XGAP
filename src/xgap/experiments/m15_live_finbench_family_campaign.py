"""Run the frozen FinBench family-memory comparison on live black-box backends.

The producer is deliberately strict about phase order.  It compiles every
candidate and every result-blind run before fixture loading, admits training
measurements only through an independently audited correctness gate, seals the
zero-profile family selection before current-query profiling, and opens the
answer oracle only after all 368 scheduled plan runs have finished.
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
from xgap.experiments.m15_finbench_family_campaign import (
    FinBenchFamilyCampaignSchedule,
    build_finbench_family_campaign_schedule,
)
from xgap.experiments.m15_finbench_family_memory import (
    FinBenchPredictionSuite,
    build_finbench_training_memory,
    predict_finbench_heldout_plans,
)
from xgap.experiments.m15_finbench_federation import (
    build_finbench_plan_candidates,
    canonicalize_finbench_rows,
)
from xgap.experiments.m15_finbench_partition import load_finbench_source_partition
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
    load_finbench_primary_workload,
)
from xgap.experiments.m15_fixture_loader import BackendFixtureLoader
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_FINBENCH_FAMILY_CAMPAIGN_SCHEMA_VERSION = (
    "m15-finbench-live-family-campaign-v1"
)
FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION = (
    "m15-finbench-live-correctness-evidence-audit-v1"
)
FINBENCH_CORRECTNESS_ADMISSION_SCHEMA_VERSION = (
    "m15-finbench-correctness-admission-v1"
)
FINBENCH_CANDIDATE_CATALOG_SCHEMA_VERSION = (
    "m15-finbench-family-campaign-candidate-catalog-v1"
)
FINBENCH_FAMILY_SELECTION_SEAL_SCHEMA_VERSION = (
    "m15-finbench-family-selection-seal-v1"
)
FINBENCH_PROFILE_SELECTION_SEAL_SCHEMA_VERSION = (
    "m15-finbench-profile-selection-seal-v1"
)
FINBENCH_FAMILY_CAMPAIGN_ANALYSIS_SCHEMA_VERSION = (
    "m15-finbench-family-campaign-analysis-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_METHODS = (
    "family_memory_zero_profile",
    "predeclared_family_fallback",
    "family_global_no_instance_features",
    "fixed_route_a",
    "fixed_route_b",
    "current_query_dual_profile",
    "observed_oracle_upper_bound",
)


@dataclass(frozen=True)
class FinBenchLiveFamilyCampaignRecord:
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


def _read_json(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} must be a regular non-symbolic-link JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must contain a JSON object")
    return dict(value)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _correctness_admission(
    *,
    workload_sha256: str,
    correctness_run_root: str | Path,
    correctness_audit: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    supplied_run_root = Path(correctness_run_root)
    supplied_audit_path = Path(correctness_audit)
    if supplied_run_root.is_symlink() or not supplied_run_root.is_dir():
        raise ValueError("correctness run root must be a real directory")
    if supplied_audit_path.is_symlink() or not supplied_audit_path.is_file():
        raise ValueError("correctness audit must be a regular non-symbolic-link file")
    run_root = supplied_run_root.resolve()
    audit_path = supplied_audit_path.resolve()
    audit = _read_json(audit_path, name="FinBench correctness audit")
    outer = _read_json(run_root / "run_status.json", name="correctness run status")
    manifest_path = (
        run_root
        / "native-service-run"
        / "finbench-correctness-run"
        / "run_manifest.json"
    )
    manifest = _read_json(manifest_path, name="correctness producer manifest")
    expected_commit = audit.get("expected_commit")
    summary = manifest.get("summary")
    oracle = manifest.get("oracle_boundary")
    if (
        audit.get("schema_version") != FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION
        or audit.get("success") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("run_tree_mutated") is not False
        or not isinstance(expected_commit, str)
        or _COMMIT.fullmatch(expected_commit) is None
        or outer.get("status") != "success"
        or outer.get("git_commit") != expected_commit
        or outer.get("workload_mode") != "finbench_correctness"
        or manifest.get("status") != "success"
        or manifest.get("workload_sha256") != workload_sha256
        or not isinstance(summary, Mapping)
        or summary.get("query_count") != 36
        or summary.get("physical_plan_run_count") != 72
        or summary.get("backend_calls") != 144
        or summary.get("all_plans_exact") is not True
        or summary.get("all_physical_pairs_equivalent") is not True
        or not isinstance(oracle, Mapping)
        or oracle.get("content_parsed_after_all_plan_runs") is not True
        or oracle.get("used_for_selection") is not False
        or manifest.get("automatic_retries") != 0
        or manifest.get("paper_result") is not False
    ):
        raise ValueError("FinBench correctness evidence is not admissible")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CORRECTNESS_ADMISSION_SCHEMA_VERSION,
        "workload_sha256": workload_sha256,
        "producer_commit": expected_commit,
        "producer_run_id": run_root.name,
        "producer_manifest_sha256": _file_sha256(manifest_path),
        "producer_manifest_content_sha256": content_hash(manifest),
        "audit_sha256": _file_sha256(audit_path),
        "audit_content_sha256": content_hash(audit),
        "audit_check_count": audit.get("check_count"),
        "query_count": 36,
        "physical_plan_run_count": 72,
        "all_plans_exact": True,
        "all_physical_pairs_equivalent": True,
        "oracle_opened_after_all_correctness_runs": True,
        "used_only_for_training_exactness_admission": True,
        "answer_rows_copied": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["admission_sha256"] = content_hash(body)
    return body, audit, manifest


def _candidate_catalog(
    workload_root: str | Path,
    instances: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[tuple[str, str], Any]]:
    by_key: dict[tuple[str, str], Any] = {}
    entries: list[dict[str, Any]] = []
    for instance in sorted(instances, key=lambda item: str(item["query_id"])):
        query_id = str(instance["query_id"])
        for candidate in build_finbench_plan_candidates(
            workload_root, query_id=query_id
        ):
            strategy = str(candidate.plan.metadata["physical_strategy"])
            key = (query_id, strategy)
            if key in by_key:
                raise ValueError("FinBench campaign plan identity is duplicated")
            by_key[key] = candidate.plan
            entries.append(
                {
                    "query_id": query_id,
                    "family_id": instance["family_id"],
                    "split_role": instance["split_role"],
                    "physical_strategy": strategy,
                    "semantic_equivalence_key": candidate.semantic_equivalence_key,
                    "plan": candidate.plan.to_dict(),
                }
            )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CANDIDATE_CATALOG_SCHEMA_VERSION,
        "query_count": len(instances),
        "plan_count": len(entries),
        "plans": entries,
        "sealed_before_fixture_load": True,
        "backend_calls_before_seal": 0,
        "answer_oracle_content_parsed": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["candidate_catalog_sha256"] = content_hash(body)
    return body, by_key


def _scheduler(clients: Mapping[str, BackendClient]) -> FederatedScheduler:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(NativeBackendPlugin(backend_id, clients[backend_id]))
    return FederatedScheduler(BackendInvokeTool(plugins))


def _execute(
    *,
    scheduler: FederatedScheduler,
    plan: Any,
    record: Mapping[str, Any],
    events: list[dict[str, Any]],
    goal_id: str,
) -> dict[str, Any]:
    result = scheduler.execute(plan, goal_id=goal_id)
    identity = record.get("run_id") or record.get("slot_id")
    call_index = 0
    for node in result.node_results:
        for _ in range(node.remote_calls):
            call_index += 1
            events.append(
                {
                    "phase": record["phase"],
                    "scheduled_identity": identity,
                    "query_id": record["query_id"],
                    "family_id": record["family_id"],
                    "physical_strategy": record["physical_strategy"],
                    "method_id": record.get("method_id"),
                    "phase_call_index": call_index,
                    "backend_id": node.metadata.get("backend_id"),
                    "runtime_node_id": node.node_id,
                    "operation": "execute",
                }
            )
    payload = {
        **dict(record),
        "plan_id": plan.plan_id,
        "success": result.success,
        "elapsed_ms": result.elapsed_ms,
        "total_bytes_moved": result.total_bytes_moved,
        "total_remote_calls": result.total_remote_calls,
        "runtime_result": result.to_dict(),
        "answer_oracle_opened": False,
    }
    if not result.success or result.total_remote_calls != 2:
        raise RuntimeError(f"FinBench campaign plan failed: {identity}")
    return payload


def _training_observations(
    *,
    schedule: FinBenchFamilyCampaignSchedule,
    results: Mapping[str, Mapping[str, Any]],
    correctness_admission: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    pair_rows: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in schedule.payload["training_runs"]:
        result = results[str(record["run_id"])]
        key = (str(record["query_id"]), str(record["physical_strategy"]))
        item = grouped.setdefault(
            key,
            {
                "query_id": record["query_id"],
                "family_id": record["family_id"],
                "physical_strategy": record["physical_strategy"],
                "repetitions": [],
            },
        )
        rows = canonicalize_finbench_rows(
            str(record["family_id"]), result["runtime_result"]["final_rows"]
        )
        rows_hash = content_hash(rows)
        pair_rows.setdefault(
            (str(record["query_id"]), int(record["block_index"])), []
        ).append(
            {
                "physical_strategy": record["physical_strategy"],
                "canonical_rows_sha256": rows_hash,
            }
        )
        item["repetitions"].append(
            {
                "repetition_id": record["run_id"],
                "block_index": record["block_index"],
                "order_position": record["order_position"],
                "elapsed_ms": result["elapsed_ms"],
                "total_bytes_moved": result["total_bytes_moved"],
                "total_remote_calls": result["total_remote_calls"],
                "execution_success": result["success"],
                "exact_answer": correctness_admission["all_plans_exact"],
            }
        )
    equivalence = []
    for (query_id, block), rows in sorted(pair_rows.items()):
        equivalent = len(rows) == 2 and len(
            {item["canonical_rows_sha256"] for item in rows}
        ) == 1
        equivalence.append(
            {
                "query_id": query_id,
                "block_index": block,
                "strategies": rows,
                "physical_pair_equivalent": equivalent,
            }
        )
    if len(grouped) != 32 or len(equivalence) != 64 or not all(
        item["physical_pair_equivalent"] for item in equivalence
    ):
        raise RuntimeError("training physical-plan equivalence validation failed")
    return [grouped[key] for key in sorted(grouped)], equivalence


def _family_selection(
    *,
    schedule: FinBenchFamilyCampaignSchedule,
    suite: FinBenchPredictionSuite,
    plans: Mapping[tuple[str, str], Any],
    event_count: int,
) -> dict[str, Any]:
    predictions = []
    for raw in suite.payload["predictions"]:
        item = dict(raw)
        query_id = str(item["query_id"])
        strategy = str(item["selected_physical_strategy"])
        item["selected_plan_id"] = plans[(query_id, strategy)].plan_id
        item["candidate_plan_ids"] = sorted(
            plan.plan_id for (candidate_query, _), plan in plans.items()
            if candidate_query == query_id
        )
        predictions.append(item)
    body: dict[str, Any] = {
        "schema_version": FINBENCH_FAMILY_SELECTION_SEAL_SCHEMA_VERSION,
        "schedule_sha256": schedule.schedule_hash,
        "training_memory_sha256": suite.payload["training_memory_sha256"],
        "prediction_suite_sha256": suite.prediction_hash,
        "selections": predictions,
        "selection_count": len(predictions),
        "backend_calls_before_seal": event_count,
        "current_query_profile_calls_before_seal": 0,
        "heldout_answer_oracle_fields": [],
        "selection_input": "sealed_training_family_memory_only",
        "postexecution_measurements_used": False,
    }
    body["selection_seal_sha256"] = content_hash(body)
    return body


def _profile_selection(
    *,
    schedule: FinBenchFamilyCampaignSchedule,
    acquisition: Mapping[str, Mapping[str, Any]],
    family_seal: Mapping[str, Any],
    event_count: int,
) -> dict[str, Any]:
    by_query: dict[str, list[Mapping[str, Any]]] = {}
    for result in acquisition.values():
        by_query.setdefault(str(result["query_id"]), []).append(result)
    selections = []
    for query_id in sorted(by_query):
        values = by_query[query_id]
        if len(values) != 2:
            raise RuntimeError("profile acquisition coverage changed")
        chosen = min(
            values,
            key=lambda item: (
                float(item["elapsed_ms"]),
                int(item["total_bytes_moved"]),
                str(item["physical_strategy"]),
            ),
        )
        selections.append(
            {
                "query_id": query_id,
                "family_id": chosen["family_id"],
                "split_role": chosen["split_role"],
                "candidate_plan_ids": sorted(item["plan_id"] for item in values),
                "selected_plan_id": chosen["plan_id"],
                "selected_physical_strategy": chosen["physical_strategy"],
                "selected_profile_elapsed_ms": chosen["elapsed_ms"],
                "selected_profile_total_bytes_moved": chosen["total_bytes_moved"],
                "source_run_id": chosen["run_id"],
            }
        )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_PROFILE_SELECTION_SEAL_SCHEMA_VERSION,
        "schedule_sha256": schedule.schedule_hash,
        "family_selection_seal_sha256": family_seal["selection_seal_sha256"],
        "selections": selections,
        "selection_count": len(selections),
        "backend_calls_before_seal": event_count,
        "profile_acquisition_plan_runs": len(acquisition),
        "answer_oracle_opened_before_seal": False,
        "selection_input": "sealed_current_query_profile_costs_only",
    }
    body["selection_seal_sha256"] = content_hash(body)
    return body


def _summary(values: Sequence[float]) -> dict[str, float]:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("analysis requires finite nonempty values")
    return {
        "mean": sum(values) / len(values),
        "median": float(statistics.median(values)),
        "minimum": min(values),
        "maximum": max(values),
    }


def _shadow_medians(
    shadow: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, float]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in shadow.values():
        grouped.setdefault(
            (str(item["query_id"]), str(item["physical_strategy"])), []
        ).append(item)
    if len(grouped) != 40 or any(len(values) != 4 for values in grouped.values()):
        raise ValueError("shadow evaluation must cover 40 plans four times")
    return {
        key: {
            "elapsed_ms": float(statistics.median(item["elapsed_ms"] for item in values)),
            "total_bytes_moved": float(
                statistics.median(item["total_bytes_moved"] for item in values)
            ),
        }
        for key, values in grouped.items()
    }


def _pareto(strategies: Sequence[str], costs: Mapping[str, Mapping[str, float]]) -> list[str]:
    return sorted(
        candidate
        for candidate in strategies
        if not any(
            other != candidate
            and costs[other]["elapsed_ms"] <= costs[candidate]["elapsed_ms"]
            and costs[other]["total_bytes_moved"]
            <= costs[candidate]["total_bytes_moved"]
            and (
                costs[other]["elapsed_ms"] < costs[candidate]["elapsed_ms"]
                or costs[other]["total_bytes_moved"]
                < costs[candidate]["total_bytes_moved"]
            )
            for other in strategies
        )
    )


def analyze_finbench_family_campaign(
    *,
    public_workload: Mapping[str, Any],
    memory: Mapping[str, Any],
    prediction_suite: Mapping[str, Any],
    family_seal: Mapping[str, Any],
    profile_seal: Mapping[str, Any],
    acquisition_results: Mapping[str, Mapping[str, Any]],
    selected_results: Mapping[str, Mapping[str, Any]],
    shadow_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute the frozen descriptive comparison after all selection seals."""

    instances = {
        str(item["query_id"]): dict(item)
        for item in public_workload["public_instances"]["instances"]
    }
    families = {
        str(item["family_id"]): dict(item)
        for item in public_workload["family_contracts"]["families"]
    }
    heldout = sorted(
        query_id for query_id, item in instances.items()
        if item["split_role"] in {"heldout_instance", "heldout_family"}
    )
    medians = _shadow_medians(shadow_results)
    family_choices = {
        str(item["query_id"]): str(item["selected_physical_strategy"])
        for item in family_seal["selections"]
    }
    profile_choices = {
        str(item["query_id"]): str(item["selected_physical_strategy"])
        for item in profile_seal["selections"]
    }
    prediction_by_query = {
        str(item["query_id"]): dict(item)
        for item in prediction_suite["predictions"]
    }
    training_by_family: dict[str, dict[str, list[float]]] = {}
    for observation in memory["observations"]:
        training_by_family.setdefault(str(observation["family_id"]), {}).setdefault(
            str(observation["physical_strategy"]), []
        ).append(float(observation["median_elapsed_ms"]))
    global_choices = {
        family_id: min(
            by_strategy,
            key=lambda strategy: (
                statistics.median(by_strategy[strategy]), strategy
            ),
        )
        for family_id, by_strategy in training_by_family.items()
    }
    for family_id, family in families.items():
        if family_id not in global_choices:
            global_choices[family_id] = str(family["cold_start_fallback"])

    selected_by_query_method = {
        (str(item["query_id"]), str(item["method_id"])): item
        for item in selected_results.values()
    }
    acquisition_by_query: dict[str, list[Mapping[str, Any]]] = {}
    for item in acquisition_results.values():
        acquisition_by_query.setdefault(str(item["query_id"]), []).append(item)

    strategy_choices: dict[str, dict[str, str]] = {
        "family_global_no_instance_features": {
            query_id: global_choices[str(instances[query_id]["family_id"])]
            for query_id in heldout
        },
        "fixed_route_a": {
            query_id: str(
                families[str(instances[query_id]["family_id"])]["physical_strategies"][0]
            )
            for query_id in heldout
        },
        "fixed_route_b": {
            query_id: str(
                families[str(instances[query_id]["family_id"])]["physical_strategies"][1]
            )
            for query_id in heldout
        },
        "current_query_dual_profile": profile_choices,
    }
    method_rows: dict[str, list[dict[str, Any]]] = {method: [] for method in _METHODS}
    for query_id in heldout:
        instance = instances[query_id]
        family_id = str(instance["family_id"])
        strategies = [str(item) for item in families[family_id]["physical_strategies"]]
        costs = {strategy: medians[(query_id, strategy)] for strategy in strategies}
        latency_winner = min(
            strategies,
            key=lambda strategy: (
                costs[strategy]["elapsed_ms"],
                costs[strategy]["total_bytes_moved"],
                strategy,
            ),
        )
        bytes_winner = min(
            strategies,
            key=lambda strategy: (
                costs[strategy]["total_bytes_moved"],
                costs[strategy]["elapsed_ms"],
                strategy,
            ),
        )
        primary_method = (
            "family_memory_zero_profile"
            if instance["split_role"] == "heldout_instance"
            else "predeclared_family_fallback"
        )
        all_choices = {
            primary_method: family_choices[query_id],
            **{method: choices[query_id] for method, choices in strategy_choices.items()},
            "observed_oracle_upper_bound": latency_winner,
        }
        for method_id, strategy in all_choices.items():
            serving = selected_by_query_method.get((query_id, method_id))
            acquisition_latency = sum(
                float(item["elapsed_ms"])
                for item in acquisition_by_query.get(query_id, [])
            ) if method_id == "current_query_dual_profile" else 0.0
            acquisition_bytes = sum(
                float(item["total_bytes_moved"])
                for item in acquisition_by_query.get(query_id, [])
            ) if method_id == "current_query_dual_profile" else 0.0
            serving_latency = (
                float(serving["elapsed_ms"])
                if serving is not None
                else costs[strategy]["elapsed_ms"]
            )
            serving_bytes = (
                float(serving["total_bytes_moved"])
                if serving is not None
                else costs[strategy]["total_bytes_moved"]
            )
            method_rows[method_id].append(
                {
                    "query_id": query_id,
                    "family_id": family_id,
                    "evaluation_stratum": (
                        "heldout_instance"
                        if instance["split_role"] == "heldout_instance"
                        else "heldout_family_cold_start"
                    ),
                    "selected_physical_strategy": strategy,
                    "observed_latency_winner": latency_winner,
                    "observed_bytes_winner": bytes_winner,
                    "winner_correct": strategy == latency_winner,
                    "latency_regret_ms": costs[strategy]["elapsed_ms"]
                    - costs[latency_winner]["elapsed_ms"],
                    "bytes_regret": costs[strategy]["total_bytes_moved"]
                    - costs[bytes_winner]["total_bytes_moved"],
                    "selection_and_serving_latency_ms": acquisition_latency
                    + serving_latency,
                    "selection_and_serving_bytes": acquisition_bytes + serving_bytes,
                    "serving_measurement_source": (
                        "paired_selected_execution"
                        if serving is not None
                        else "shadow_median_derived_baseline"
                    ),
                }
            )

    method_metrics: dict[str, Any] = {}
    for method_id, rows in method_rows.items():
        if not rows:
            continue
        method_metrics[method_id] = {
            "query_count": len(rows),
            "physical_winner_accuracy": {
                "correct_count": sum(item["winner_correct"] for item in rows),
                "accuracy": sum(item["winner_correct"] for item in rows) / len(rows),
            },
            "latency_regret_ms": _summary(
                [float(item["latency_regret_ms"]) for item in rows]
            ),
            "bytes_regret": _summary([float(item["bytes_regret"]) for item in rows]),
            "selection_and_serving_end_to_end_cost": {
                "latency_ms": _summary(
                    [float(item["selection_and_serving_latency_ms"]) for item in rows]
                ),
                "bytes": _summary(
                    [float(item["selection_and_serving_bytes"]) for item in rows]
                ),
            },
        }

    prediction_errors: list[dict[str, Any]] = []
    frontier_rows: list[dict[str, Any]] = []
    for query_id, prediction in prediction_by_query.items():
        if prediction["evaluation_stratum"] != "heldout_instance":
            continue
        family_id = str(prediction["family_id"])
        strategies = [str(item) for item in families[family_id]["physical_strategies"]]
        costs = {strategy: medians[(query_id, strategy)] for strategy in strategies}
        for estimate in prediction["strategy_predictions"]:
            strategy = str(estimate["physical_strategy"])
            prediction_errors.append(
                {
                    "query_id": query_id,
                    "physical_strategy": strategy,
                    "latency_error_ms": float(estimate["predicted_elapsed_ms"])
                    - costs[strategy]["elapsed_ms"],
                    "bytes_error": float(estimate["predicted_total_bytes_moved"])
                    - costs[strategy]["total_bytes_moved"],
                }
            )
        predicted = set(prediction["predicted_physical_frontier"])
        observed = set(_pareto(strategies, costs))
        union = predicted | observed
        frontier_rows.append(
            {
                "query_id": query_id,
                "predicted": sorted(predicted),
                "observed": sorted(observed),
                "jaccard": len(predicted & observed) / len(union),
            }
        )
    latency_abs = [abs(float(item["latency_error_ms"])) for item in prediction_errors]
    bytes_abs = [abs(float(item["bytes_error"])) for item in prediction_errors]
    body: dict[str, Any] = {
        "schema_version": FINBENCH_FAMILY_CAMPAIGN_ANALYSIS_SCHEMA_VERSION,
        "known_family_and_cold_start_reported_separately": True,
        "method_metrics": method_metrics,
        "method_records": method_rows,
        "prediction_error": {
            "known_family_plan_count": len(prediction_errors),
            "latency_absolute_error_ms": _summary(latency_abs),
            "bytes_absolute_error": _summary(bytes_abs),
            "records": prediction_errors,
        },
        "predicted_observed_frontier_overlap": {
            "known_family_query_count": len(frontier_rows),
            "mean_jaccard": sum(item["jaccard"] for item in frontier_rows)
            / len(frontier_rows),
            "per_query": frontier_rows,
        },
        "confirmatory_statistics": False,
        "paper_result": False,
    }
    body["analysis_sha256"] = content_hash(body)
    return body


def run_m15_live_finbench_family_campaign(
    *,
    workload_root: str | Path,
    partition_root: str | Path,
    correctness_run_root: str | Path,
    correctness_audit: str | Path,
    clients: Mapping[str, BackendClient],
    loaders: Mapping[str, BackendFixtureLoader],
    output_root: str | Path,
    protocol: Mapping[str, Any] | str | Path,
    family_memory_policy: Mapping[str, Any] | str | Path,
    run_id: str = "finbench-family-campaign-run",
    repo_root: str | Path | None = None,
) -> FinBenchLiveFamilyCampaignRecord:
    """Execute one no-retry, development-only FinBench family campaign."""

    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("FinBench family campaign run_id is unsafe")
    if set(clients) != {"neo4j", "fuseki"} or set(loaders) != {"neo4j", "fuseki"}:
        raise ValueError("FinBench family campaign requires exact backend adapters")
    root_repo = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    public = load_finbench_primary_public_workload(workload_root)
    partition = load_finbench_source_partition(partition_root)
    workload_manifest = public["manifest"]
    if workload_manifest["source_partition_sha256"] != partition["partition_sha256"]:
        raise ValueError("FinBench workload and source partition identities differ")
    instances = [dict(item) for item in public["public_instances"]["instances"]]
    schedule = build_finbench_family_campaign_schedule(
        workload_root=workload_root,
        protocol=protocol,
        family_memory_policy=family_memory_policy,
    )
    catalog, plans = _candidate_catalog(workload_root, instances)
    admission, audit_snapshot, correctness_manifest_snapshot = _correctness_admission(
        workload_sha256=str(workload_manifest["workload_sha256"]),
        correctness_run_root=correctness_run_root,
        correctness_audit=correctness_audit,
    )
    destination = Path(output_root).resolve() / run_id
    destination.mkdir(parents=True, exist_ok=False)
    status_path = destination / "run_status.json"
    manifest_path = destination / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_FINBENCH_FAMILY_CAMPAIGN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    _write_json(destination / "campaign_schedule.json", schedule.to_dict())
    _write_json(destination / "candidate_catalog.json", catalog)
    _write_json(destination / "correctness_admission.json", admission)
    _write_json(destination / "correctness_audit_snapshot.json", audit_snapshot)
    _write_json(
        destination / "correctness_manifest_snapshot.json",
        correctness_manifest_snapshot,
    )

    events: list[dict[str, Any]] = []
    load_reports: dict[str, Any] = {}
    training_results: dict[str, dict[str, Any]] = {}
    acquisition_results: dict[str, dict[str, Any]] = {}
    selected_results: dict[str, dict[str, Any]] = {}
    shadow_results: dict[str, dict[str, Any]] = {}
    health: dict[str, Any] = {}
    memory_payload: dict[str, Any] | None = None
    suite_payload: dict[str, Any] | None = None
    family_seal: dict[str, Any] | None = None
    profile_seal: dict[str, Any] | None = None
    oracle_validation: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    checks: dict[str, bool] = {}
    error: str | None = None
    try:
        for backend_id in ("neo4j", "fuseki"):
            if float(getattr(clients[backend_id], "timeout_seconds", 60.0)) != 60.0:
                raise ValueError("backend timeout must be exactly 60 seconds")
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(destination / "health.json", health)
        if not all(item["ok"] for item in health.values()):
            raise RuntimeError("FinBench campaign backend healthcheck failed")

        partition_path = Path(partition_root).resolve()
        neo4j_load = partition.get("neo4j_load")
        neo4j_filename = (
            neo4j_load.get("filename")
            if isinstance(neo4j_load, Mapping)
            else "load_neo4j.cypher"
        )
        for backend_id, filename in (
            ("neo4j", str(neo4j_filename)),
            ("fuseki", "load_fuseki.ttl"),
        ):
            report = loaders[backend_id].load(partition_path / filename)
            load_reports[backend_id] = report.to_dict()
            if not report.success:
                raise RuntimeError(
                    f"FinBench {backend_id} fixture load failed: {report.error}"
                )
        _write_json(destination / "load_reports.json", load_reports)
        scheduler = _scheduler(clients)

        for record in schedule.payload["training_runs"]:
            plan = plans[(str(record["query_id"]), str(record["physical_strategy"]))]
            payload = _execute(
                scheduler=scheduler,
                plan=plan,
                record=record,
                events=events,
                goal_id=f"{run_id}:training:{record['run_id']}",
            )
            training_results[str(record["run_id"])] = payload
            _write_json(
                destination / "training/runs" / f"{record['run_id']}.json",
                payload,
            )

        observations, equivalence = _training_observations(
            schedule=schedule,
            results=training_results,
            correctness_admission=admission,
        )
        _write_json(
            destination / "training/training_equivalence.json",
            {"pairs": equivalence, "all_pairs_equivalent": True},
        )
        _write_json(
            destination / "training/training_observations.json",
            {"observations": observations},
        )
        memory = build_finbench_training_memory(
            workload_root=workload_root,
            raw_observations=observations,
            policy=family_memory_policy,
            measurement_source_id=f"{run_id}:correctness-admitted-training",
        )
        memory_payload = memory.to_dict()
        _write_json(destination / "training/training_memory.json", memory_payload)
        suite = predict_finbench_heldout_plans(
            workload_root=workload_root,
            memory=memory,
            policy=family_memory_policy,
        )
        suite_payload = suite.to_dict()
        _write_json(destination / "family/prediction_suite.json", suite_payload)
        family_seal = _family_selection(
            schedule=schedule,
            suite=suite,
            plans=plans,
            event_count=len(events),
        )
        _write_json(destination / "family_selection_seal.json", family_seal)

        for record in schedule.payload["profile_acquisition_runs"]:
            plan = plans[(str(record["query_id"]), str(record["physical_strategy"]))]
            payload = _execute(
                scheduler=scheduler,
                plan=plan,
                record=record,
                events=events,
                goal_id=f"{run_id}:profile:{record['run_id']}",
            )
            acquisition_results[str(record["run_id"])] = payload
            _write_json(
                destination / "profile/acquisition/runs" / f"{record['run_id']}.json",
                payload,
            )
        profile_seal = _profile_selection(
            schedule=schedule,
            acquisition=acquisition_results,
            family_seal=family_seal,
            event_count=len(events),
        )
        _write_json(destination / "profile_selection_seal.json", profile_seal)

        family_by_query = {
            str(item["query_id"]): item for item in family_seal["selections"]
        }
        profile_by_query = {
            str(item["query_id"]): item for item in profile_seal["selections"]
        }
        for slot in schedule.payload["paired_selected_execution_slots"]:
            query_id = str(slot["query_id"])
            selection = (
                profile_by_query[query_id]
                if slot["method_id"] == "current_query_dual_profile"
                else family_by_query[query_id]
            )
            strategy = str(selection["selected_physical_strategy"])
            record = {**dict(slot), "physical_strategy": strategy}
            payload = _execute(
                scheduler=scheduler,
                plan=plans[(query_id, strategy)],
                record=record,
                events=events,
                goal_id=f"{run_id}:selected:{slot['slot_id']}",
            )
            selected_results[str(slot["slot_id"])] = payload
            _write_json(
                destination / "selected/runs" / f"{slot['slot_id']}.json",
                payload,
            )

        for record in schedule.payload["evaluation_shadow_runs"]:
            plan = plans[(str(record["query_id"]), str(record["physical_strategy"]))]
            payload = _execute(
                scheduler=scheduler,
                plan=plan,
                record=record,
                events=events,
                goal_id=f"{run_id}:shadow:{record['run_id']}",
            )
            shadow_results[str(record["run_id"])] = payload
            _write_json(
                destination / "shadow/runs" / f"{record['run_id']}.json",
                payload,
            )

        if len(events) != 736:
            raise RuntimeError("FinBench campaign backend call count changed")
        full = load_finbench_primary_workload(workload_root)
        oracle_queries = full["sealed_oracles"]["queries"]
        comparisons = []
        for phase, values in (
            ("training_measurement", training_results),
            ("current_query_profile_acquisition", acquisition_results),
            ("paired_selected_execution", selected_results),
            ("postselection_shadow_evaluation", shadow_results),
        ):
            for identity, result in sorted(values.items()):
                query_id = str(result["query_id"])
                family_id = str(result["family_id"])
                expected = canonicalize_finbench_rows(
                    family_id, oracle_queries[query_id]["final_rows"]
                )
                observed = canonicalize_finbench_rows(
                    family_id, result["runtime_result"]["final_rows"]
                )
                comparisons.append(
                    {
                        "phase": phase,
                        "scheduled_identity": identity,
                        "query_id": query_id,
                        "plan_id": result["plan_id"],
                        "exact_answer": observed == expected,
                        "observed_rows_sha256": content_hash(observed),
                        "expected_rows_sha256": content_hash(expected),
                    }
                )
        oracle_validation = {
            "opened_after_all_plan_runs": True,
            "backend_calls_before_open": len(events),
            "selection_fields_used": [],
            "comparison_count": len(comparisons),
            "all_answers_exact": all(item["exact_answer"] for item in comparisons),
            "comparisons": comparisons,
        }
        _write_json(destination / "oracle_validation.json", oracle_validation)
        if not oracle_validation["all_answers_exact"]:
            raise RuntimeError("FinBench campaign answer validation failed")

        analysis = analyze_finbench_family_campaign(
            public_workload=public,
            memory=memory_payload,
            prediction_suite=suite_payload,
            family_seal=family_seal,
            profile_seal=profile_seal,
            acquisition_results=acquisition_results,
            selected_results=selected_results,
            shadow_results=shadow_results,
        )
        _write_json(destination / "analysis.json", analysis)
        counts = {
            "training_plan_runs": len(training_results),
            "profile_acquisition_plan_runs": len(acquisition_results),
            "paired_selected_plan_runs": len(selected_results),
            "evaluation_shadow_plan_runs": len(shadow_results),
            "total_plan_runs": sum(
                len(values)
                for values in (
                    training_results,
                    acquisition_results,
                    selected_results,
                    shadow_results,
                )
            ),
            "total_backend_calls": len(events),
        }
        checks = {
            "counts_match_frozen_schedule": counts == schedule.payload["expected_counts"],
            "correctness_admission_valid": admission["all_plans_exact"] is True,
            "candidate_catalog_sealed_before_load": catalog["backend_calls_before_seal"] == 0,
            "family_selection_zero_current_query_profiles": family_seal[
                "current_query_profile_calls_before_seal"
            ] == 0,
            "family_selection_sealed_before_profile": family_seal[
                "backend_calls_before_seal"
            ] == 256,
            "profile_selection_sealed_before_serving": profile_seal[
                "backend_calls_before_seal"
            ] == 336,
            "oracle_opened_after_all_runs": oracle_validation[
                "backend_calls_before_open"
            ] == 736,
            "all_answers_exact": oracle_validation["all_answers_exact"] is True,
            "analysis_methods_complete": set(analysis["method_metrics"]) == set(_METHODS),
            "automatic_retries_zero": True,
            "paper_result_false": analysis["paper_result"] is False,
        }
        _write_json(
            destination / "validation.json",
            {"passed": all(checks.values()), "checks": checks, "counts": counts},
        )
        if not all(checks.values()):
            raise RuntimeError("FinBench family campaign validation failed")
    except Exception as exc:  # Preserve the first failure and never retry.
        error = str(exc)

    _write_json(
        destination / "backend_invocations.json",
        {
            "events": events,
            "total_tool_invocations": len(events),
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    success = error is None
    summary = {
        "training_plan_runs": len(training_results),
        "profile_acquisition_plan_runs": len(acquisition_results),
        "paired_selected_plan_runs": len(selected_results),
        "evaluation_shadow_plan_runs": len(shadow_results),
        "total_plan_runs": (
            len(training_results)
            + len(acquisition_results)
            + len(selected_results)
            + len(shadow_results)
        ),
        "total_backend_calls": len(events),
        "family_memory_current_query_profile_calls": 0,
        "profile_method_current_query_profile_plan_runs": len(acquisition_results),
    }
    _write_json(
        status_path,
        {
            "schema_version": LIVE_FINBENCH_FAMILY_CAMPAIGN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_FINBENCH_FAMILY_CAMPAIGN_SCHEMA_VERSION,
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
            "workload_sha256": workload_manifest["workload_sha256"],
            "source_partition_sha256": partition["partition_sha256"],
            "schedule_sha256": schedule.schedule_hash,
            "candidate_catalog_sha256": catalog["candidate_catalog_sha256"],
            "correctness_admission_sha256": admission["admission_sha256"],
            "training_memory_sha256": (
                memory_payload["training_memory_sha256"] if memory_payload else None
            ),
            "prediction_suite_sha256": (
                suite_payload["prediction_suite_sha256"] if suite_payload else None
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
            "oracle_boundary": {
                "content_parsed": oracle_validation is not None,
                "content_parsed_after_all_plan_runs": bool(
                    oracle_validation
                    and oracle_validation["backend_calls_before_open"] == 736
                ),
                "used_for_selection": False,
            },
            "family_selection_sealed_before_profile_acquisition": bool(family_seal),
            "both_selection_seals_before_serving": bool(family_seal and profile_seal),
            "shadow_influenced_selection": False,
            "automatic_retries": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "confirmatory_statistics": False,
            "development_campaign_only": True,
            "paper_result": False,
        },
    )
    return FinBenchLiveFamilyCampaignRecord(
        run_id=run_id,
        run_root=destination,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
