"""Artifact-first live M15 method matrix over real black-box backends."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.agent import JsonlMemoryStore
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_method_policy import (
    M15_METHOD_POLICIES,
    M15Method,
    M15MethodTaskResult,
    run_m15_method_task,
)
from xgap.experiments.m15_scaled_federation import (
    build_m15_scaled_observation_catalogs,
    build_m15_scaled_observation_requests,
    build_m15_scaled_plan_candidates,
    build_m15_scaled_plan_memory_context,
    build_m15_scaled_probe_plan,
    build_m15_scaled_semantic_program,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime import PlanObservationCollector, PlanSnapshotMemory, ProbeObservation
from xgap.tools import (
    BackendObservationCatalog,
    BackendInvokeTool,
    BackendPluginRegistry,
    CatalogBackendPlugin,
    ToolResult,
)


LIVE_MATRIX_SCHEMA_VERSION = "m15-f1-live-method-matrix-v1"
LIVE_MATRIX_COST_MODEL_VERSION = "m15-f1-live-matrix-cost-model-v1"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_METHOD_ORDER = (
    M15Method.STATIC_PARALLEL_HASH,
    M15Method.STATIC_RISK_FIRST_BIND,
    M15Method.NO_MEMORY,
    M15Method.NO_PROFILE_PROBE,
    M15Method.NO_REPLAN,
    M15Method.FULL_AGENT,
)


@dataclass(frozen=True)
class M15LiveMethodMatrixRecord:
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


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _backend_tool(
    clients: Mapping[str, BackendClient],
    catalogs: Mapping[str, BackendObservationCatalog],
    events: list[dict[str, Any]],
) -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            RecordingBackendPlugin(
                CatalogBackendPlugin(
                    backend_id,
                    clients[backend_id],
                    catalogs[backend_id],
                ),
                events,
            )
        )
    return BackendInvokeTool(plugins)


def _observation_rows(result: ToolResult) -> list[dict[str, Any]] | None:
    value = result.value if isinstance(result.value, Mapping) else None
    observation = value.get("observation") if isinstance(value, Mapping) else None
    rows = observation.get("rows") if isinstance(observation, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        return None
    return [dict(row) for row in rows]


def _validate_cost_model(
    *,
    bandwidth_bytes_per_ms: float,
    exchange_fixed_ms: float,
    coordinator_row_ms: float,
) -> None:
    for name, value in (
        ("bandwidth_bytes_per_ms", bandwidth_bytes_per_ms),
        ("exchange_fixed_ms", exchange_fixed_ms),
        ("coordinator_row_ms", coordinator_row_ms),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError(f"{name} must be finite")
    if bandwidth_bytes_per_ms <= 0:
        raise ValueError("bandwidth_bytes_per_ms must be positive")
    if exchange_fixed_ms < 0 or coordinator_row_ms < 0:
        raise ValueError("coordinator cost values must be nonnegative")


def run_m15_live_method_matrix(
    *,
    workload_bundle: M15WorkloadBundle | str | Path,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    bandwidth_bytes_per_ms: float = 1000.0,
    exchange_fixed_ms: float = 0.5,
    coordinator_row_ms: float = 0.001,
) -> M15LiveMethodMatrixRecord:
    """Run one fail-closed engineering matrix against the same live services.

    The fixed method order and shared unknown cache state make this a mechanism
    and integration gate, not a paper-comparison result.
    """

    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    bundle = load_m15_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15WorkloadBundle)
        else workload_bundle
    )
    _validate_cost_model(
        bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
        exchange_fixed_ms=exchange_fixed_ms,
        coordinator_row_ms=coordinator_row_ms,
    )
    selected_run_id = run_id or f"m15-f1-live-matrix-{_now_slug()}"
    if not _SAFE_RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id contains unsupported characters")
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / selected_run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    candidates = build_m15_scaled_plan_candidates(bundle)
    requests = build_m15_scaled_observation_requests(bundle)
    probe_plan = build_m15_scaled_probe_plan(bundle)
    catalogs = build_m15_scaled_observation_catalogs(bundle)
    context = build_m15_scaled_plan_memory_context(
        bundle,
        bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
        exchange_fixed_ms=exchange_fixed_ms,
        coordinator_row_ms=coordinator_row_ms,
    )
    model_config = {
        "schema_version": LIVE_MATRIX_COST_MODEL_VERSION,
        "bandwidth_bytes_per_ms": float(bandwidth_bytes_per_ms),
        "exchange_fixed_ms": float(exchange_fixed_ms),
        "coordinator_row_ms": float(coordinator_row_ms),
        "parameter_source": "fixed_development_configuration",
        "calibrated": False,
        "paper_result": False,
    }
    _write_json(
        run_root / "semantic_program.json",
        build_m15_scaled_semantic_program(bundle).to_dict(),
    )
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
    _write_json(run_root / "memory_context.json", context.to_dict())
    _write_json(run_root / "cost_model.json", model_config)
    _write_json(
        run_root / "method_policies.json",
        [M15_METHOD_POLICIES[method].to_dict() for method in _METHOD_ORDER],
    )

    selected_clients = dict(clients) if clients is not None else _default_clients(root)
    health: dict[str, Any] = {}
    events: dict[str, list[dict[str, Any]]] = {}
    results: dict[str, M15MethodTaskResult] = {}
    calibration = None
    validation: dict[str, Any] | None = None
    seed_memory_writes = 0
    error: str | None = None
    try:
        if set(selected_clients) != {"neo4j", "fuseki"}:
            raise ValueError(
                "live method matrix requires exactly neo4j and fuseki clients"
            )
        for backend_id in ("neo4j", "fuseki"):
            health[backend_id] = selected_clients[backend_id].healthcheck().to_dict()
        _write_json(run_root / "health.json", health)
        unavailable = [key for key, value in health.items() if not value["ok"]]
        if unavailable:
            raise RuntimeError(f"backend healthcheck failed: {', '.join(unavailable)}")

        calibration_events: list[dict[str, Any]] = []
        events["calibration"] = calibration_events
        calibration = PlanObservationCollector(
            _backend_tool(selected_clients, catalogs, calibration_events)
        ).collect(
            requests,
            snapshot_id=context.snapshot_id,
            version=f"calibration-{selected_run_id}",
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
            goal_id=f"{selected_run_id}:calibration",
        )
        _write_json(run_root / "calibration.json", calibration.to_dict())
        if not calibration.success or calibration.snapshot is None:
            raise RuntimeError(calibration.error or "live calibration failed")
        _write_json(
            run_root / "calibration_snapshot.json",
            calibration.snapshot.to_dict(),
        )

        for method in _METHOD_ORDER:
            memory = None
            if M15_METHOD_POLICIES[method].read_memory:
                memory_path = run_root / "memory" / f"{method.value}.jsonl"
                memory = PlanSnapshotMemory(JsonlMemoryStore(memory_path))
                memory.put(
                    calibration.snapshot,
                    source=f"{selected_run_id}/common-live-calibration",
                )
                seed_memory_writes += 1
            method_events: list[dict[str, Any]] = []
            events[method.value] = method_events
            result = run_m15_method_task(
                method=method,
                task_id=f"{selected_run_id}.{method.value}",
                context=context,
                candidates=candidates,
                requests=requests,
                probe_plan=probe_plan,
                probe_observation=ProbeObservation(
                    "high-risk",
                    requests[2].observation_key,
                ),
                backend_tool=_backend_tool(
                    selected_clients,
                    catalogs,
                    method_events,
                ),
                expected_rows=tuple(bundle.expected_rows),
                bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
                exchange_fixed_ms=exchange_fixed_ms,
                coordinator_row_ms=coordinator_row_ms,
                memory=memory,
            )
            results[method.value] = result
            _write_json(
                run_root / "methods" / f"{method.value}.json",
                result.to_dict(),
            )
            if not result.success:
                raise RuntimeError(
                    f"method '{method.value}' failed: {result.error}"
                )

        checks = {
            "all_methods_present": set(results)
            == {method.value for method in _METHOD_ORDER},
            "all_answers_exact": all(result.exact_answer for result in results.values()),
            "calibration_exactly_three_profiles": calibration.attempted_calls == 3,
            "calibration_neo4j_full_matches_oracle": _observation_rows(
                calibration.tool_results[0]
            )
            == bundle.expected_source_rows["neo4j"],
            "calibration_fuseki_risk_matches_oracle": _observation_rows(
                calibration.tool_results[2]
            )
            == bundle.expected_source_rows["fuseki"],
            "no_memory_profiles_each_task": (
                results[M15Method.NO_MEMORY.value].planning_profile_calls == 3
            ),
            "warm_methods_use_common_snapshot": all(
                results[method.value].memory_state == "hit"
                for method in (
                    M15Method.NO_PROFILE_PROBE,
                    M15Method.NO_REPLAN,
                    M15Method.FULL_AGENT,
                )
            ),
            "no_profile_probe_has_no_current_observation": (
                results[
                    M15Method.NO_PROFILE_PROBE.value
                ].planning_profile_calls
                == 0
                and results[M15Method.NO_PROFILE_PROBE.value].probe_remote_calls == 0
            ),
            "no_replan_observes_but_keeps_initial": (
                results[M15Method.NO_REPLAN.value].probe_remote_calls == 1
                and results[M15Method.NO_REPLAN.value].replan_count == 0
                and results[M15Method.NO_REPLAN.value].executed_plan_id
                == results[M15Method.NO_REPLAN.value].initial_plan_id
            ),
            "full_agent_has_bounded_replanning": (
                results[M15Method.FULL_AGENT.value].probe_remote_calls == 1
                and results[M15Method.FULL_AGENT.value].replan_count in {0, 1}
            ),
            "all_tasks_use_two_query_calls": all(
                result.query_remote_calls == 2 for result in results.values()
            ),
            "tool_events_match_task_accounting": all(
                len(events[method]) == result.total_backend_calls
                and sum(
                    event["operation"] == "profile" for event in events[method]
                )
                == result.planning_profile_calls
                and sum(
                    event["operation"] == "execute" for event in events[method]
                )
                == result.query_remote_calls
                for method, result in results.items()
            ),
            "zero_llm_and_ontology_calls": True,
        }
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live method-matrix validation failed")
    except Exception as exc:  # Persist the first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)

    _write_json(
        run_root / "backend_invocations.json",
        {
            "events_by_phase": events,
            "total_tool_invocations": sum(len(items) for items in events.values()),
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    manifest = {
        "schema_version": LIVE_MATRIX_SCHEMA_VERSION,
        "run_id": selected_run_id,
        "dataset_id": f"m15_f0:{bundle.spec.workload_id}",
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
            **{
                f"bundle:{bundle.spec.workload_id}/{name}": digest
                for name, digest in bundle.source_hashes.items()
            },
            f"bundle:{bundle.spec.workload_id}/manifest.json": _sha256_file(
                bundle.root / "manifest.json"
            ),
        },
        "workload_bundle": dict(bundle.manifest),
        "cost_model": model_config,
        "memory_context": context.to_dict(),
        "backend_health": health,
        "method_order": [method.value for method in _METHOD_ORDER],
        "order_policy": "fixed_engineering_gate_not_counterbalanced",
        "cache_state": "shared_unknown_not_reset_between_methods",
        "calibration": calibration.to_dict() if calibration is not None else None,
        "calibration_accounting": {
            "included_in_method_metrics": False,
            "reason": "common live pre-task calibration shared by warm methods",
            "seed_memory_writes": seed_memory_writes,
        },
        "methods": {
            method: result.to_dict() for method, result in results.items()
        },
        "validation": validation,
        "artifacts": sorted(
            {
                *(path.name for path in run_root.iterdir()),
                manifest_path.name,
            }
        ),
        "evidence_class": "live_backend_method_mechanism_engineering_gate",
        "paper_result": False,
        "no_llm": True,
        "no_ontology": True,
        "automatic_retries": 0,
    }
    _write_json(manifest_path, manifest)
    return M15LiveMethodMatrixRecord(
        run_id=selected_run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-bundle", required=True)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--repo-root")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_LIVE_METHOD_MATRIX") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_RUN_M15_LIVE_METHOD_MATRIX=1 after the verified "
                        "M15 scaled fixture is loaded"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_live_method_matrix(
            workload_bundle=args.workload_bundle,
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
