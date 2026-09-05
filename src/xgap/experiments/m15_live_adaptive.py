"""Artifact-first M15 live observation and adaptive federation gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.agent import JsonlMemoryStore
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_live_federated import (
    DATASET_PATH,
    EXPECTED_PATH,
    EXPECTED_SOURCE_PATH,
    build_m15_observation_catalogs,
    build_m15_plan_candidates,
    build_m15_semantic_program,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime import (
    AdaptiveFederatedExecutor,
    FederatedExecutionPlan,
    FederatedScheduler,
    PlanObservationCollector,
    PlanObservationRequest,
    PlanSnapshotMemory,
    ProbeObservation,
    ReplanPolicy,
)
from xgap.tools import (
    BackendInvokeTool,
    BackendOperation,
    BackendPlugin,
    BackendPluginRegistry,
    CatalogBackendPlugin,
    ToolContext,
    ToolResult,
)


RUN_SCHEMA_VERSION = "m15-d2-live-adaptive-run-v1"
MODEL_SCHEMA_VERSION = "m15-d2-fixed-cost-model-v1"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SOURCE_PATHS = (
    DATASET_PATH,
    Path("examples/m15_split_financial_risk/query_recent_transfers.cypher"),
    Path("examples/m15_split_financial_risk/query_recent_transfers_bound.cypher"),
    Path("examples/m15_split_financial_risk/query_high_risk.rq"),
    EXPECTED_SOURCE_PATH,
    EXPECTED_PATH,
)


@dataclass(frozen=True)
class M15AdaptiveRunRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    adaptive_result_path: Path | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "adaptive_result_path": (
                str(self.adaptive_result_path) if self.adaptive_result_path else None
            ),
            "error": self.error,
        }


@dataclass
class RecordingBackendPlugin:
    """Record bounded tool invocations without storing query text or secrets."""

    delegate: BackendPlugin
    events: list[dict[str, Any]]

    @property
    def backend_id(self) -> str:
        return self.delegate.backend_id

    @property
    def supported_operations(self) -> frozenset[BackendOperation]:
        return self.delegate.supported_operations

    def invoke(
        self,
        operation: BackendOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        started = time.perf_counter()
        try:
            result = self.delegate.invoke(operation, payload, context)
        except Exception as exc:
            self._record(
                operation,
                payload,
                context,
                started=started,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self._record(
            operation,
            payload,
            context,
            started=started,
            status=result.status.value,
            error=result.error,
            result=result,
        )
        return result

    def _record(
        self,
        operation: BackendOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
        *,
        started: float,
        status: str,
        error: str | None,
        result: ToolResult | None = None,
    ) -> None:
        value = (
            result.value
            if result is not None and isinstance(result.value, Mapping)
            else {}
        )
        artifact = payload.get("artifact")
        artifact_id = (
            artifact.get("artifact_id") if isinstance(artifact, Mapping) else None
        )
        if artifact_id is None:
            artifact_id = value.get("artifact_id")
        self.events.append(
            {
                "sequence": len(self.events) + 1,
                "goal_id": context.goal_id,
                "step": context.step,
                "call_id": context.call_id,
                "backend_id": self.backend_id,
                "operation": operation.value,
                "artifact_id": artifact_id,
                "query_id": payload.get("query_id"),
                "sample_id": payload.get("sample_id"),
                "status": status,
                "error": error,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
                "tool_metrics": dict(result.metrics) if result is not None else {},
                "catalog_id": value.get("catalog_id"),
                "catalog_version": value.get("catalog_version"),
                "observation_mode": value.get("observation_mode"),
            }
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_path(repo_root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (repo_root / candidate).resolve()
    )
    if resolved != repo_root and repo_root not in resolved.parents:
        raise ValueError(f"experiment path escapes repository: {value}")
    return resolved


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
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


def _default_clients(repo_root: Path) -> dict[str, BackendClient]:
    descriptors = repo_root / "descriptors" / "backends"
    return {
        "neo4j": Neo4jClient(
            BackendDescriptor.from_yaml(descriptors / "neo4j.yaml")
        ),
        "fuseki": FusekiClient(
            BackendDescriptor.from_yaml(descriptors / "fuseki.yaml")
        ),
    }


def build_m15_observation_requests() -> tuple[PlanObservationRequest, ...]:
    """Declare the three registered estimates needed by both plan candidates."""

    return (
        PlanObservationRequest(
            "profile-neo4j-full",
            "neo4j-recent-transfers-full",
            "neo4j",
            BackendOperation.PROFILE,
            {"query_id": "recent-transfers-full"},
        ),
        PlanObservationRequest(
            "profile-neo4j-bound",
            "neo4j-recent-transfers-bound",
            "neo4j",
            BackendOperation.PROFILE,
            {"query_id": "recent-transfers-bound"},
        ),
        PlanObservationRequest(
            "profile-fuseki-risk",
            "fuseki-high-risk",
            "fuseki",
            BackendOperation.PROFILE,
            {"query_id": "high-risk"},
        ),
    )


def build_m15_probe_plan(repo_root: str | Path | None = None) -> FederatedExecutionPlan:
    """Build the declared exact common prefix used by adaptive continuation."""

    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    candidates = build_m15_plan_candidates(root)
    nodes = {node.node_id: node for node in candidates[0].plan.nodes}
    return FederatedExecutionPlan(
        plan_id="m15-live-risk-probe-prefix",
        nodes=(nodes["high-risk"], nodes["align-risk"], nodes["exchange-risk"]),
        roots=("exchange-risk",),
        max_remote_calls=1,
        max_parallelism=1,
        metadata={
            "execution_phase": "adaptive_probe",
            "evidence_class": "live_backend_development_gate",
        },
    )


def _expected_rows(repo_root: Path) -> list[dict[str, Any]]:
    payload = json.loads(_repo_path(repo_root, EXPECTED_PATH).read_text("utf-8"))
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError("expected result must be a JSON list of objects")
    return [dict(row) for row in payload]


def _expected_source_rows(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(
        _repo_path(repo_root, EXPECTED_SOURCE_PATH).read_text("utf-8")
    )
    if not isinstance(payload, dict):
        raise ValueError("expected source results must be a JSON object")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for backend_id in ("neo4j", "fuseki"):
        rows = payload.get(backend_id)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"expected source rows for {backend_id} must be objects")
        normalized[backend_id] = [dict(row) for row in rows]
    return normalized


def _observation_rows(result: ToolResult) -> list[dict[str, Any]] | None:
    value = result.value if isinstance(result.value, Mapping) else None
    observation = value.get("observation") if isinstance(value, Mapping) else None
    rows = observation.get("rows") if isinstance(observation, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        return None
    return [dict(row) for row in rows]


def run_m15_live_adaptive(
    *,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    bandwidth_bytes_per_ms: float = 1000.0,
    exchange_fixed_ms: float = 0.5,
    coordinator_row_ms: float = 0.001,
) -> M15AdaptiveRunRecord:
    """Profile registered queries once, persist memory, and run one live query."""

    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    selected_run_id = run_id or f"m15-live-adaptive-{_now_slug()}"
    if not _SAFE_RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id contains unsupported characters")
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / selected_run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    adaptive_path = run_root / "adaptive_result.json"
    started_at = _now()

    candidates = build_m15_plan_candidates(root)
    probe_plan = build_m15_probe_plan(root)
    requests = build_m15_observation_requests()
    model_config = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "bandwidth_bytes_per_ms": bandwidth_bytes_per_ms,
        "exchange_fixed_ms": exchange_fixed_ms,
        "coordinator_row_ms": coordinator_row_ms,
        "parameter_source": "fixed_development_configuration",
        "calibrated": False,
        "paper_result": False,
    }
    _write_json(run_root / "semantic_program.json", build_m15_semantic_program().to_dict())
    _write_json(
        run_root / "candidate_plans.json",
        {
            "semantic_equivalence_key": candidates[0].semantic_equivalence_key,
            "plans": [candidate.plan.to_dict() for candidate in candidates],
        },
    )
    _write_json(run_root / "probe_plan.json", probe_plan.to_dict())
    _write_json(
        run_root / "observation_requests.json",
        [request.to_dict() for request in requests],
    )
    _write_json(run_root / "cost_model.json", model_config)

    selected_clients = dict(clients) if clients is not None else _default_clients(root)
    events: list[dict[str, Any]] = []
    health: dict[str, Any] = {}
    collection = None
    adaptive = None
    validation: dict[str, Any] | None = None
    memory_before_reopened = False
    memory_after_reopened = False
    error: str | None = None
    try:
        if set(selected_clients) != {"neo4j", "fuseki"}:
            raise ValueError("live adaptive run requires exactly neo4j and fuseki clients")
        for backend_id in ("neo4j", "fuseki"):
            status = selected_clients[backend_id].healthcheck()
            health[backend_id] = status.to_dict()
        _write_json(run_root / "health.json", health)
        unavailable = [key for key, value in health.items() if not value["ok"]]
        if unavailable:
            raise RuntimeError(f"backend healthcheck failed: {', '.join(unavailable)}")

        catalogs = build_m15_observation_catalogs(root)
        plugins = BackendPluginRegistry()
        for backend_id in ("neo4j", "fuseki"):
            plugins.register(
                RecordingBackendPlugin(
                    CatalogBackendPlugin(
                        backend_id,
                        selected_clients[backend_id],
                        catalogs[backend_id],
                    ),
                    events,
                )
            )
        backend_tool = BackendInvokeTool(plugins)
        collection = PlanObservationCollector(backend_tool).collect(
            requests,
            snapshot_id="m15-live-adaptive",
            version="profile-task-0",
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
            goal_id=f"{selected_run_id}:collect-observations",
        )
        _write_json(run_root / "observation_collection.json", collection.to_dict())
        if not collection.success or collection.snapshot is None:
            raise RuntimeError(collection.error or "plan observation collection failed")
        _write_json(run_root / "snapshot_before.json", collection.snapshot.to_dict())

        memory_path = run_root / "plan_memory.jsonl"
        memory = PlanSnapshotMemory(JsonlMemoryStore(memory_path))
        memory.put(collection.snapshot, source="registered-live-profile")
        reopened_before = PlanSnapshotMemory(JsonlMemoryStore(memory_path)).latest(
            collection.snapshot.snapshot_id
        )
        memory_before_reopened = reopened_before == collection.snapshot
        if not memory_before_reopened or reopened_before is None:
            raise RuntimeError("profile snapshot did not survive memory reopen")

        adaptive = AdaptiveFederatedExecutor(
            FederatedScheduler(backend_tool)
        ).execute(
            candidates,
            reopened_before,
            probe_plan=probe_plan,
            observations=(ProbeObservation("high-risk", "fuseki-high-risk"),),
            updated_version="query-task-1",
            observation_source=f"{selected_run_id}/runtime-probe/high-risk",
            policy=ReplanPolicy(max_replans=1),
            goal_id=f"{selected_run_id}:adaptive-query",
        )
        _write_json(adaptive_path, adaptive.to_dict())
        if adaptive.snapshot_after.version != reopened_before.version:
            memory.put(adaptive.snapshot_after, source="live-runtime-probe")
        reopened_after = PlanSnapshotMemory(JsonlMemoryStore(memory_path)).latest(
            adaptive.snapshot_after.snapshot_id
        )
        memory_after_reopened = reopened_after == adaptive.snapshot_after
        _write_json(run_root / "snapshot_after.json", adaptive.snapshot_after.to_dict())
        if not adaptive.success:
            raise RuntimeError(adaptive.error or "adaptive continuation failed")

        expected = _expected_rows(root)
        expected_sources = _expected_source_rows(root)
        execute_events = [event for event in events if event["operation"] == "execute"]
        profile_events = [event for event in events if event["operation"] == "profile"]
        full_rows = _observation_rows(collection.tool_results[0])
        risk_rows = _observation_rows(collection.tool_results[2])
        final_rows = (
            [dict(row) for row in adaptive.final_run.final_rows]
            if adaptive.final_run is not None
            else None
        )
        checks = {
            "observation_collection_success": collection.success,
            "exact_observation_call_count": collection.attempted_calls == 3,
            "exact_profile_event_count": len(profile_events) == 3,
            "profile_snapshot_reopened": memory_before_reopened,
            "adaptive_runtime_success": adaptive.success,
            "exact_expected_answer": final_rows == expected,
            "exact_neo4j_full_profile_rows": full_rows == expected_sources["neo4j"],
            "exact_fuseki_profile_rows": risk_rows == expected_sources["fuseki"],
            "exact_query_remote_call_count": adaptive.total_remote_calls == 2,
            "exact_execute_event_count": len(execute_events) == 2,
            "one_fuseki_query_execute": sum(
                event["backend_id"] == "fuseki" for event in execute_events
            )
            == 1,
            "one_neo4j_query_execute": sum(
                event["backend_id"] == "neo4j" for event in execute_events
            )
            == 1,
            "bounded_replan_count": adaptive.replan_count in {0, 1},
            "updated_snapshot_reopened": memory_after_reopened,
        }
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live adaptive acceptance checks failed")
    except Exception as exc:  # Persist the first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)
        if collection is not None and not (run_root / "observation_collection.json").exists():
            _write_json(run_root / "observation_collection.json", collection.to_dict())
        if adaptive is not None and not adaptive_path.exists():
            _write_json(adaptive_path, adaptive.to_dict())

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
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    source_hashes = {
        str(path): _sha256_file(_repo_path(root, path)) for path in SOURCE_PATHS
    }
    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": selected_run_id,
        "dataset_id": "m15_split_financial_risk",
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
        "input_sha256": source_hashes,
        "cost_model": model_config,
        "backend_health": health,
        "observation_collection": collection.to_dict() if collection else None,
        "adaptive_summary": (
            {
                "success": adaptive.success,
                "initial_plan_id": adaptive.initial_selection.selected_plan_id,
                "post_probe_plan_id": (
                    adaptive.selection_after_probe.selected_plan_id
                    if adaptive.selection_after_probe is not None
                    else None
                ),
                "executed_plan_id": adaptive.selected_plan_id,
                "replan_count": adaptive.replan_count,
                "replan_reasons": list(adaptive.replan_reasons),
                "total_remote_calls": adaptive.total_remote_calls,
                "elapsed_ms": adaptive.elapsed_ms,
            }
            if adaptive is not None
            else None
        ),
        "memory_before_reopened": memory_before_reopened,
        "memory_after_reopened": memory_after_reopened,
        "validation": validation,
        "artifacts": sorted(
            {
                *(path.name for path in run_root.iterdir() if path.is_file()),
                manifest_path.name,
            }
        ),
        "evidence_class": "live_backend_development_gate",
        "paper_result": False,
        "no_llm": True,
        "no_ontology": True,
        "automatic_retries": 0,
    }
    _write_json(manifest_path, manifest)
    return M15AdaptiveRunRecord(
        run_id=selected_run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        adaptive_result_path=adaptive_path if adaptive_path.exists() else None,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--repo-root")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_ADAPTIVE") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_RUN_M15_ADAPTIVE=1 after both M15 fixtures "
                        "are loaded"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_live_adaptive(
            output_root=args.output_root,
            run_id=args.run_id,
            repo_root=args.repo_root,
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
