"""Execute one sealed M15-E4 bridge plan against live black-box backends.

The bridge is reconstructed before any query execution.  Only physical plans
attached to capability-complete semantic classes are executed; unavailable
classes remain evidence and never reach a backend.
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
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
    generate_m15_direct_semantic_workload_bundle,
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_executable_family_registry import (
    compile_m15_executable_family_registry_file,
)
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    M15ResolutionExecutionBridgePlan,
    compile_m15_resolution_execution_bridge_files,
)
from xgap.runtime import FederatedScheduler, RuntimeNodeKind
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_RESOLUTION_EXECUTION_BRIDGE_SCHEMA_VERSION = (
    "m15-e4b-live-resolution-execution-bridge-v1"
)
RESOLUTION_EXECUTION_BRIDGE_PREFLIGHT_SCHEMA_VERSION = (
    "m15-e4b-resolution-execution-bridge-preflight-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class M15PreparedResolutionExecutionBridge:
    bridge: M15ResolutionExecutionBridgePlan
    workload: M15DirectSemanticWorkloadBundle
    base_workload: M15ParameterizedWorkloadBundle
    semantic_catalog_path: Path
    predicate_mapping_path: Path

    def reload_workload(self) -> M15DirectSemanticWorkloadBundle:
        return load_m15_direct_semantic_workload_bundle(
            self.workload.root,
            base_bundle=self.base_workload,
            catalog=self.semantic_catalog_path,
            mapping=self.predicate_mapping_path,
        )


@dataclass(frozen=True)
class M15LiveResolutionExecutionBridgeRecord:
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


def prepare_m15_resolution_execution_bridge(
    *,
    resolution_run_path: str | Path,
    bridge_spec_path: str | Path,
    workload_destination: str | Path,
    repo_root: str | Path,
) -> M15PreparedResolutionExecutionBridge:
    """Seal the bridge, then materialize its independently verified fixture."""

    root = Path(repo_root).resolve()
    bridge = compile_m15_resolution_execution_bridge_files(
        resolution_run_path=resolution_run_path,
        bridge_spec_path=bridge_spec_path,
        repo_root=root,
    )
    payload = bridge.to_dict()
    registry_relative = payload["source_artifacts"][
        "executable_family_registry"
    ]["path"]
    registry_path = root / registry_relative
    registry = compile_m15_executable_family_registry_file(
        registry_path,
        repo_root=root,
    ).to_dict()
    family_id = payload["executable_family"]["family_id"]
    packages = [item for item in registry["families"] if item["family_id"] == family_id]
    if len(packages) != 1:
        raise ValueError("bridge family no longer identifies one registry package")
    sources = packages[0]["source_bindings"]
    source_paths = {
        role: root / record["path"] for role, record in sources.items()
    }
    destination = Path(workload_destination)
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=source_paths["workload_spec"],
        query_template_spec=source_paths["query_template"],
        backend_template_root=source_paths["neo4j_full_template"].parent,
        destination=destination / "base",
    )
    workload = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=source_paths["semantic_catalog"],
        mapping=source_paths["predicate_mapping"],
        policy=source_paths["semantic_workload_policy"],
        destination=destination / "direct",
    )
    task_ids = {
        str(item["executable_query_id"])
        for view in (
            workload.training_selection_view,
            workload.heldout_selection_view,
        )
        for item in view["semantic_tasks"]
    }
    plan_query_ids = {
        str(item["query_id"]) for item in payload["physical_candidates"]
    }
    if not plan_query_ids or not plan_query_ids <= task_ids:
        raise ValueError("bridge physical candidates are not present in the workload")
    return M15PreparedResolutionExecutionBridge(
        bridge=bridge,
        workload=workload,
        base_workload=base,
        semantic_catalog_path=source_paths["semantic_catalog"],
        predicate_mapping_path=source_paths["predicate_mapping"],
    )


def run_m15_live_resolution_execution_bridge(
    *,
    resolution_run_path: str | Path,
    bridge_spec_path: str | Path,
    prepared: M15PreparedResolutionExecutionBridge,
    clients: Mapping[str, BackendClient],
    output_root: str | Path,
    run_id: str = "resolution-execution-bridge-run",
    repo_root: str | Path | None = None,
) -> M15LiveResolutionExecutionBridgeRecord:
    """Execute all and only the bridge's capability-complete candidates."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError("live bridge requires exactly neo4j and fuseki clients")
    expected = compile_m15_resolution_execution_bridge_files(
        resolution_run_path=resolution_run_path,
        bridge_spec_path=bridge_spec_path,
        repo_root=root,
    )
    if prepared.bridge.to_dict() != expected.to_dict() or {
        key: value.to_dict() for key, value in prepared.bridge.plans.items()
    } != {key: value.to_dict() for key, value in expected.plans.items()}:
        raise ValueError("prepared bridge differs from verified inputs")
    reloaded_workload = prepared.reload_workload()
    if reloaded_workload.to_dict() != prepared.workload.to_dict():
        raise ValueError("prepared bridge workload differs from verified inputs")

    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    result_path = run_root / "execution_results.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_RESOLUTION_EXECUTION_BRIDGE_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    bridge_payload = prepared.bridge.to_dict()
    _write_json(run_root / "bridge_plan.json", bridge_payload)
    events: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    answer_oracle_opened = False
    error: str | None = None
    try:
        for backend_id in ("neo4j", "fuseki"):
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        unavailable = [key for key, value in health.items() if not value["ok"]]
        if unavailable:
            raise RuntimeError("backend healthcheck failed: " + ", ".join(unavailable))

        candidates = bridge_payload["physical_candidates"]
        scheduler = FederatedScheduler(_backend_tool(clients, events))
        for candidate in candidates:
            plan_id = str(candidate["plan_id"])
            runtime_plan = prepared.bridge.plans[plan_id]
            runtime_result = scheduler.execute(
                runtime_plan,
                goal_id=f"{run_id}:execute:{plan_id}",
            )
            result = {
                "plan_id": plan_id,
                "semantic_class_id": candidate["semantic_class_id"],
                "query_id": candidate["query_id"],
                "physical_strategy": candidate["physical_strategy"],
                "expected_final_row_count": None,
                "exact_oracle_answer": None,
                "runtime_result": runtime_result.to_dict(),
            }
            results.append(result)
            if not runtime_result.success:
                raise RuntimeError(f"live bridge execution failed for {plan_id}")

        # All physical choices and executions are complete before any answer
        # oracle is opened.  Oracles validate outcomes only; they cannot affect
        # semantic availability, plan construction, or execution order.
        instances = {
            query_id: load_m15_parameterized_instance(
                prepared.workload.workload_bundle,
                query_id,
            )
            for query_id in {str(item["query_id"]) for item in candidates}
        }
        answer_oracle_opened = True
        for result in results:
            oracle = instances[str(result["query_id"])]["final_oracle"]
            final_rows = result["runtime_result"]["final_rows"]
            result["expected_final_row_count"] = len(oracle)
            result["exact_oracle_answer"] = final_rows == oracle
        _write_json(result_path, {"results": results})

        executed_ids = [item["plan_id"] for item in results]
        expected_ids = [item["plan_id"] for item in candidates]
        unavailable_class_ids = {
            str(item["semantic_class_id"])
            for item in bridge_payload["semantic_classes"]
            if item["availability"] == "unavailable"
        }
        strategies_by_class: dict[str, set[str]] = {}
        for item in results:
            strategies_by_class.setdefault(item["semantic_class_id"], set()).add(
                item["physical_strategy"]
            )
        upper_bounds = []
        for runtime_plan in prepared.bridge.plans.values():
            for node in runtime_plan.nodes:
                if node.parameters.get("backend_id") == "neo4j" and node.kind in {
                    RuntimeNodeKind.REMOTE_QUERY,
                    RuntimeNodeKind.REMOTE_BIND_QUERY,
                }:
                    upper_bounds.append(
                        node.parameters["artifact"]["parameters"].get(
                            "occurred_on_lt"
                        )
                    )
        runtime_results = [item["runtime_result"] for item in results]
        checks = {
            "six_interpretations_preserved": bridge_payload["counts"] == {
                "raw_interpretations": 6,
                "semantic_equivalence_classes": 6,
                "executable_semantic_classes": 2,
                "unavailable_semantic_classes": 4,
                "physical_candidates": 4,
            },
            "exact_candidate_set_executed": executed_ids == expected_ids,
            "unavailable_classes_not_executed": all(
                str(item["semantic_class_id"]) not in unavailable_class_ids
                for item in results
            ),
            "two_strategies_per_executable_class": len(strategies_by_class) == 2
            and all(
                values == {"parallel_hash_join", "risk_first_bind_join"}
                for values in strategies_by_class.values()
            ),
            "hard_upper_bound_present": upper_bounds == ["2026-09-01"] * 4,
            "all_runtime_success": all(item["success"] for item in runtime_results),
            "all_exact_oracle_answers": all(
                item["exact_oracle_answer"] for item in results
            ),
            "two_calls_per_plan": all(
                item["total_remote_calls"] == 2 for item in runtime_results
            ),
            "exact_tool_event_count": len(events) == 8,
            "four_calls_per_backend": len(events) == 8
            and [item["backend_id"] for item in events].count("neo4j") == 4
            and [item["backend_id"] for item in events].count("fuseki") == 4,
            "execute_calls_only": all(
                item["operation"] == "execute" for item in events
            ),
            "no_automatic_retry": len(events) == 2 * len(results),
        }
        _write_json(
            run_root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if not all(checks.values()):
            raise RuntimeError("live resolution-execution bridge validation failed")
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
            "schema_version": LIVE_RESOLUTION_EXECUTION_BRIDGE_SCHEMA_VERSION,
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
            "schema_version": LIVE_RESOLUTION_EXECUTION_BRIDGE_SCHEMA_VERSION,
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
                "resolution_run": _sha256_file(Path(resolution_run_path)),
                "bridge_spec": _sha256_file(Path(bridge_spec_path)),
                "workload_manifest": _sha256_file(
                    prepared.workload.root / "manifest.json"
                ),
            },
            "bridge_plan_sha256": bridge_payload["bridge_plan_sha256"],
            "summary": {
                "raw_interpretation_count": 6,
                "semantic_class_count": 6,
                "executable_semantic_class_count": 2,
                "unavailable_semantic_class_count": 4,
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
            },
            "validation": {
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "evidence_class": "live_resolution_execution_bridge_mechanism_gate",
            "bridge_verified_before_execution": True,
            "answer_oracle_used_for_selection": False,
            "answer_oracle_opened_after_all_executions": answer_oracle_opened,
            "answer_oracle_used_for_post_execution_validation": (
                answer_oracle_opened
            ),
            "unavailable_semantic_classes_executed": False,
            "current_query_profile_calls": 0,
            "llm_calls_made": 0,
            "ontology_service_calls_made": 0,
            "automatic_retries": 0,
            "paper_result": False,
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return M15LiveResolutionExecutionBridgeRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        result_path=result_path,
        error=error,
    )
