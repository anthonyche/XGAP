"""Select and execute the F2C9 direct semantic frontier on live backends.

The selector consumes only a sealed development prediction source.  It builds
the complete direct candidate set and frontier before opening answer oracles,
then executes exactly the returned plans in rank order.  This is a mechanism
gate, not a performance or semantic-utility experiment.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_direct_semantic_estimates import (
    M15DirectEstimateSource,
    bind_m15_direct_estimate_snapshot,
    load_m15_direct_estimate_source,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticCandidateSet,
    M15DirectSemanticFrontier,
    M15PreexecutionEstimateSnapshot,
    build_m15_direct_semantic_candidate_set,
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    M15PredicateMappingSpec,
    M15PredicateOverlayBundle,
    load_m15_predicate_overlay_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
)
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION = (
    "m15-f2c9b-live-direct-semantic-frontier-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_EXPECTED_RETURNED_CHANGED_SLOTS = [
    [],
    ["risk-level", "transfer-predicate"],
    ["risk-level"],
]


@dataclass(frozen=True)
class M15LiveDirectSemanticFrontierRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    result_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "result_path": str(self.result_path),
            "error": self.error,
        }


@dataclass(frozen=True)
class M15PreparedDirectSemanticFrontier:
    """Oracle-free selection state that may be sealed before service startup."""

    candidate_set: M15DirectSemanticCandidateSet
    estimate_source: M15DirectEstimateSource
    estimate_snapshot: M15PreexecutionEstimateSnapshot
    frontier: M15DirectSemanticFrontier

    def artifacts(self) -> dict[str, dict[str, Any]]:
        return {
            "candidate_set.json": self.candidate_set.to_dict(),
            "estimate_source.json": self.estimate_source.to_dict(),
            "estimate_snapshot.json": self.estimate_snapshot.to_dict(),
            "semantic_frontier.json": self.frontier.to_dict(),
        }


def prepare_m15_direct_semantic_frontier(
    *,
    predicate_overlay: M15PredicateOverlayBundle | str | Path,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    estimate_source: str | Path,
) -> M15PreparedDirectSemanticFrontier:
    """Build the complete frontier without opening an oracle or backend."""

    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    overlay = load_m15_predicate_overlay_bundle(
        predicate_overlay.root
        if isinstance(predicate_overlay, M15PredicateOverlayBundle)
        else predicate_overlay,
        base_bundle=selected_base,
        catalog=catalog,
        mapping=mapping,
    )
    estimates = load_m15_direct_estimate_source(estimate_source)
    candidate_set = build_m15_direct_semantic_candidate_set(
        predicate_overlay=overlay,
        base_bundle=selected_base,
        catalog=catalog,
        mapping=mapping,
    )
    estimate_snapshot = bind_m15_direct_estimate_snapshot(
        candidate_set,
        estimates,
    )
    frontier = select_m15_direct_semantic_frontier(
        candidate_set,
        estimate_snapshot,
    )
    return M15PreparedDirectSemanticFrontier(
        candidate_set=candidate_set,
        estimate_source=estimates,
        estimate_snapshot=estimate_snapshot,
        frontier=frontier,
    )


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
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
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


def _backend_tool(
    clients: Mapping[str, BackendClient],
    events: list[dict[str, Any]],
) -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            RecordingBackendPlugin(
                NativeBackendPlugin(backend_id, clients[backend_id]),
                events,
            )
        )
    return BackendInvokeTool(plugins)


def run_m15_live_direct_semantic_frontier(
    *,
    predicate_overlay: M15PredicateOverlayBundle | str | Path,
    base_bundle: M15ParameterizedWorkloadBundle | str | Path,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    estimate_source: str | Path,
    clients: Mapping[str, BackendClient],
    output_root: str | Path,
    run_id: str = "direct-semantic-frontier-run",
    repo_root: str | Path | None = None,
    prepared_frontier: M15PreparedDirectSemanticFrontier | None = None,
) -> M15LiveDirectSemanticFrontierRecord:
    """Seal the direct frontier, then execute exactly its returned plans."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    selected_base = (
        base_bundle
        if isinstance(base_bundle, M15ParameterizedWorkloadBundle)
        else load_m15_parameterized_workload_bundle(base_bundle)
    )
    overlay = load_m15_predicate_overlay_bundle(
        predicate_overlay.root
        if isinstance(predicate_overlay, M15PredicateOverlayBundle)
        else predicate_overlay,
        base_bundle=selected_base,
        catalog=catalog,
        mapping=mapping,
    )
    estimate_path = Path(estimate_source)
    expected_prepared = prepare_m15_direct_semantic_frontier(
        predicate_overlay=overlay,
        base_bundle=selected_base,
        catalog=catalog,
        mapping=mapping,
        estimate_source=estimate_path,
    )
    prepared = prepared_frontier or expected_prepared
    if prepared.artifacts() != expected_prepared.artifacts():
        raise ValueError(
            "prepared direct semantic frontier differs from verified inputs"
        )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError(
            "direct semantic frontier requires exactly neo4j and fuseki clients"
        )
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    result_path = run_root / "semantic_results.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    health: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    results: list[dict[str, Any]] = []
    candidate_payload: dict[str, Any] | None = None
    estimate_payload: dict[str, Any] | None = None
    snapshot_payload: dict[str, Any] | None = None
    frontier_payload: dict[str, Any] | None = None
    error: str | None = None
    try:
        # In native mode this decision object was already sealed and persisted
        # before service startup.  The pure reconstruction above only proves
        # that the supplied seal still matches the static input artifacts.
        candidate_set = prepared.candidate_set
        estimates = prepared.estimate_source
        estimate_snapshot = prepared.estimate_snapshot
        frontier = prepared.frontier
        candidate_payload = candidate_set.to_dict()
        estimate_payload = estimates.to_dict()
        snapshot_payload = estimate_snapshot.to_dict()
        frontier_payload = frontier.to_dict()
        _write_json(run_root / "candidate_set.json", candidate_payload)
        _write_json(run_root / "estimate_source.json", estimate_payload)
        _write_json(run_root / "estimate_snapshot.json", snapshot_payload)
        _write_json(run_root / "semantic_frontier.json", frontier_payload)

        for backend_id in ("neo4j", "fuseki"):
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        unavailable = [
            backend_id for backend_id, status in health.items() if not status["ok"]
        ]
        if unavailable:
            raise RuntimeError(
                f"backend healthcheck failed: {', '.join(unavailable)}"
            )

        scheduler = FederatedScheduler(_backend_tool(clients, events))
        for selected in frontier_payload["returned_semantic_plans"]:
            plan = candidate_set.plans[selected["plan_id"]]
            # Oracles become reachable only after the frontier is sealed.
            instance = load_m15_parameterized_instance(
                overlay.workload_bundle,
                selected["query_id"],
            )
            result = scheduler.execute(
                plan,
                goal_id=f"{run_id}:execute:{selected['semantic_class_id']}",
            )
            final_rows = [dict(row) for row in result.final_rows]
            results.append(
                {
                    "selection_rank": selected["selection_rank"],
                    "semantic_class_id": selected["semantic_class_id"],
                    "query_id": selected["query_id"],
                    "plan_id": selected["plan_id"],
                    "physical_strategy": selected["physical_strategy"],
                    "semantic_deviation": selected["semantic_deviation"],
                    "changed_slot_ids": list(selected["changed_slot_ids"]),
                    "estimated_latency_ms": selected["estimated_latency_ms"],
                    "estimated_resource_cost_units": selected[
                        "estimated_resource_cost_units"
                    ],
                    "expected_final_row_count": len(instance["final_oracle"]),
                    "exact_oracle_answer": final_rows == instance["final_oracle"],
                    "runtime_result": result.to_dict(),
                }
            )
            if not result.success:
                raise RuntimeError(
                    "live direct semantic frontier execution failed for "
                    f"{selected['semantic_class_id']}"
                )
        _write_json(result_path, {"results": results})
        runtime_results = [item["runtime_result"] for item in results]
        returned = frontier_payload["returned_semantic_plans"]
        checks = {
            "twelve_declared_classes": frontier_payload["counts"][
                "declared_semantic_classes"
            ]
            == 12,
            "four_direct_classes": frontier_payload["counts"][
                "executable_direct_semantic_classes"
            ]
            == 4,
            "eight_multihop_classes_unavailable": frontier_payload["counts"][
                "unavailable_semantic_classes"
            ]
            == 8,
            "eight_physical_candidates": frontier_payload["counts"][
                "physical_candidates"
            ]
            == 8,
            "four_physical_representatives": frontier_payload["counts"][
                "physical_representatives"
            ]
            == 4,
            "four_pareto_plans": frontier_payload["counts"][
                "pareto_semantic_plans"
            ]
            == 4,
            "three_returned_plans": len(returned) == 3,
            "exact_semantics_first": returned[0]["semantic_deviation"] == 0,
            "expected_changed_slot_order": [
                item["changed_slot_ids"] for item in returned
            ]
            == _EXPECTED_RETURNED_CHANGED_SLOTS,
            "all_runtime_success": all(
                item["success"] for item in runtime_results
            ),
            "all_exact_oracle_answers": all(
                item["exact_oracle_answer"] for item in results
            ),
            "selected_plans_only_executed": [
                item["plan_id"] for item in results
            ]
            == [item["plan_id"] for item in returned],
            "exact_remote_call_count": sum(
                item["total_remote_calls"] for item in runtime_results
            )
            == 6,
            "exact_tool_event_count": len(events) == 6,
            "three_calls_per_backend": len(events) == 6
            and [item["backend_id"] for item in events].count("neo4j") == 3
            and [item["backend_id"] for item in events].count("fuseki") == 3,
            "all_calls_are_execute": all(
                item["operation"] == "execute" for item in events
            ),
            "oracle_free_selection": snapshot_payload["answer_oracle_fields"]
            == []
            and snapshot_payload["post_execution_measurements_used"] is False,
            "controlled_predictions_only": estimate_payload["evidence_kind"]
            == "controlled_preexecution_fixture",
            "no_automatic_retry": len(events) == 2 * len(runtime_results)
            and all(
                item["total_remote_calls"] == 2 for item in runtime_results
            ),
        }
        _write_json(
            run_root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if not all(checks.values()):
            raise RuntimeError("live direct semantic frontier validation failed")
    except Exception as exc:  # Preserve first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)
        if not result_path.exists():
            _write_json(result_path, {"results": results})

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
            "schema_version": LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    runtime_results = [item["runtime_result"] for item in results]
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "git": _git_state(root),
            "environment": {
                "hostname": platform.node(),
                "python": sys.version,
                "platform": platform.platform(),
            },
            "input_sha256": {
                "base_bundle_manifest": _sha256_file(
                    selected_base.root / "manifest.json"
                ),
                "predicate_overlay_manifest": _sha256_file(
                    overlay.root / "overlay_manifest.json"
                ),
                "estimate_source_file": _sha256_file(estimate_path),
            },
            "base_workload_bundle": dict(selected_base.manifest),
            "predicate_overlay": dict(overlay.manifest),
            "predicate_mapping": overlay.mapping.to_dict(),
            "estimate_source": estimate_payload,
            "candidate_set_sha256": (
                candidate_payload["candidate_set_sha256"]
                if candidate_payload is not None
                else None
            ),
            "estimate_snapshot_sha256": (
                snapshot_payload["estimate_snapshot_sha256"]
                if snapshot_payload is not None
                else None
            ),
            "frontier_sha256": (
                frontier_payload["frontier_sha256"]
                if frontier_payload is not None
                else None
            ),
            "summary": (
                {
                    "declared_semantic_class_count": 12,
                    "executable_direct_semantic_class_count": 4,
                    "unavailable_multihop_semantic_class_count": 8,
                    "physical_candidate_count": 8,
                    "physical_representative_count": 4,
                    "pareto_semantic_plan_count": 4,
                    "epsilon_frontier_semantic_plan_count": 3,
                    "returned_semantic_plan_count": len(results),
                    "physical_plan_run_count": len(results),
                    "total_remote_calls": sum(
                        item["total_remote_calls"] for item in runtime_results
                    ),
                    "total_bytes_moved": sum(
                        item["total_bytes_moved"] for item in runtime_results
                    ),
                    "final_row_counts": [
                        len(item["final_rows"]) for item in runtime_results
                    ],
                }
                if frontier_payload is not None
                else None
            ),
            "validation": {
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "evidence_class": "live_direct_semantic_frontier_mechanism_gate",
            "selection_sealed_before_oracle_access": frontier_payload is not None,
            "answer_oracle_used_for_selection": False,
            "answer_oracle_used_for_post_execution_validation": bool(results),
            "costs_are_controlled_predictions_not_observations": True,
            "blocked_multihop_classes_executed": False,
            "memory_enabled": False,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "automatic_retries": 0,
            "paper_result": False,
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return M15LiveDirectSemanticFrontierRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        result_path=result_path,
        error=error,
    )
