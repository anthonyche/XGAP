"""Deterministic paired matrix for M15 memory and replanning methods."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.agent import JsonlMemoryStore
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
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    load_m15_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import (
    PlanObservationCollector,
    PlanSnapshotMemory,
    ProbeObservation,
)
from xgap.tools import (
    BackendInvokeTool,
    BackendPluginRegistry,
    CatalogBackendPlugin,
)


MATRIX_SCHEMA_VERSION = "m15-f1-controlled-method-matrix-v1"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_METHOD_ORDER = (
    M15Method.STATIC_PARALLEL_HASH,
    M15Method.STATIC_RISK_FIRST_BIND,
    M15Method.NO_MEMORY,
    M15Method.NO_PROFILE_PROBE,
    M15Method.NO_REPLAN,
    M15Method.FULL_AGENT,
)


@dataclass
class ControlledBundleClient:
    """Exact bundle oracle with declared synthetic backend latency."""

    backend_id: str
    rows: list[dict[str, object]]
    elapsed_by_artifact: Mapping[str, float]
    artifact_calls: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "controlled bundle client ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_calls.append(artifact.artifact_id)
        rows = [dict(row) for row in self.rows]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                row
                for row in rows
                if str(row["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=float(self.elapsed_by_artifact.get(artifact.artifact_id, 2.0)),
            metadata={
                "transport": "controlled-bundle-oracle",
                "paper_result": False,
            },
        )

    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        return self.execute(artifact)


@dataclass(frozen=True)
class M15MethodMatrixRecord:
    run_id: str
    run_root: Path
    success: bool
    manifest_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _latencies(bundle: M15WorkloadBundle, *, stale: bool) -> dict[str, float]:
    workload_id = bundle.spec.workload_id
    return {
        f"m15-f0-{workload_id}-neo4j-full": 100.0,
        f"m15-f0-{workload_id}-neo4j-bound": 10.0,
        f"m15-f0-{workload_id}-fuseki-risk": 1000.0 if stale else 2.0,
    }


def _tool(
    bundle: M15WorkloadBundle,
    latencies: Mapping[str, float],
) -> tuple[BackendInvokeTool, list[dict[str, Any]]]:
    catalogs = build_m15_scaled_observation_catalogs(bundle)
    events: list[dict[str, Any]] = []
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        client = ControlledBundleClient(
            backend_id,
            bundle.expected_source_rows[backend_id],
            latencies,
        )
        plugins.register(
            RecordingBackendPlugin(
                CatalogBackendPlugin(backend_id, client, catalogs[backend_id]),
                events,
            )
        )
    return BackendInvokeTool(plugins), events


def run_m15_controlled_method_matrix(
    *,
    workload_bundle: M15WorkloadBundle | str | Path,
    output_root: str | Path = "runs",
    run_id: str | None = None,
) -> M15MethodMatrixRecord:
    """Run one paired stale-to-current control across all declared methods."""

    bundle = load_m15_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15WorkloadBundle)
        else workload_bundle
    )
    selected_run_id = run_id or f"m15-f1-controlled-matrix-{_now_slug()}"
    if not _SAFE_RUN_ID.fullmatch(selected_run_id):
        raise ValueError("run_id contains unsupported characters")
    destination = Path(output_root).resolve() / selected_run_id
    destination.mkdir(parents=True, exist_ok=False)
    manifest_path = destination / "run_manifest.json"
    started_at = _now()

    bandwidth = 1_000_000_000.0
    exchange = 0.0
    coordinator = 0.0
    candidates = build_m15_scaled_plan_candidates(bundle)
    requests = build_m15_scaled_observation_requests(bundle)
    probe_plan = build_m15_scaled_probe_plan(bundle)
    context = build_m15_scaled_plan_memory_context(
        bundle,
        bandwidth_bytes_per_ms=bandwidth,
        exchange_fixed_ms=exchange,
        coordinator_row_ms=coordinator,
    )
    _write_json(destination / "memory_context.json", context.to_dict())
    _write_json(
        destination / "method_policies.json",
        [M15_METHOD_POLICIES[method].to_dict() for method in _METHOD_ORDER],
    )

    error: str | None = None
    results: dict[str, M15MethodTaskResult] = {}
    all_events: dict[str, list[dict[str, Any]]] = {}
    calibration = None
    seed_memory_writes = 0
    try:
        calibration_tool, calibration_events = _tool(
            bundle,
            _latencies(bundle, stale=True),
        )
        calibration = PlanObservationCollector(calibration_tool).collect(
            requests,
            snapshot_id=context.snapshot_id,
            version=f"calibration-{selected_run_id}",
            bandwidth_bytes_per_ms=bandwidth,
            exchange_fixed_ms=exchange,
            coordinator_row_ms=coordinator,
            goal_id=f"{selected_run_id}:calibration",
        )
        all_events["calibration"] = calibration_events
        _write_json(destination / "calibration.json", calibration.to_dict())
        if not calibration.success or calibration.snapshot is None:
            raise RuntimeError(calibration.error or "controlled calibration failed")

        for method in _METHOD_ORDER:
            memory = None
            if M15_METHOD_POLICIES[method].read_memory:
                memory_path = destination / "memory" / f"{method.value}.jsonl"
                memory = PlanSnapshotMemory(JsonlMemoryStore(memory_path))
                memory.put(
                    calibration.snapshot,
                    source=f"{selected_run_id}/common-frozen-calibration",
                )
                seed_memory_writes += 1
            tool, events = _tool(bundle, _latencies(bundle, stale=False))
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
                backend_tool=tool,
                expected_rows=tuple(bundle.expected_rows),
                bandwidth_bytes_per_ms=bandwidth,
                exchange_fixed_ms=exchange,
                coordinator_row_ms=coordinator,
                memory=memory,
            )
            results[method.value] = result
            all_events[method.value] = events
            _write_json(
                destination / "methods" / f"{method.value}.json",
                result.to_dict(),
            )
            if not result.success:
                raise RuntimeError(
                    f"method '{method.value}' failed: {result.error}"
                )

        expected_ids = {
            str(candidate.plan.metadata["physical_strategy"]): candidate.plan.plan_id
            for candidate in candidates
        }
        checks = {
            "all_methods_present": set(results) == {item.value for item in _METHOD_ORDER},
            "all_answers_exact": all(item.exact_answer for item in results.values()),
            "calibration_exactly_three_profiles": calibration.attempted_calls == 3,
            "no_memory_profiles_each_task": (
                results[M15Method.NO_MEMORY.value].planning_profile_calls == 3
            ),
            "warm_agent_skips_profiles": (
                results[M15Method.FULL_AGENT.value].planning_profile_calls == 0
            ),
            "no_profile_probe_has_no_current_observation": (
                results[M15Method.NO_PROFILE_PROBE.value].planning_profile_calls == 0
                and results[M15Method.NO_PROFILE_PROBE.value].probe_remote_calls == 0
            ),
            "no_replan_observes_but_keeps_initial": (
                results[M15Method.NO_REPLAN.value].probe_remote_calls == 1
                and results[M15Method.NO_REPLAN.value].replan_count == 0
                and results[M15Method.NO_REPLAN.value].executed_plan_id
                == results[M15Method.NO_REPLAN.value].initial_plan_id
            ),
            "full_agent_replans_once": (
                results[M15Method.FULL_AGENT.value].probe_remote_calls == 1
                and results[M15Method.FULL_AGENT.value].replan_count == 1
                and results[M15Method.FULL_AGENT.value].executed_plan_id
                == expected_ids["risk_first_bind_join"]
            ),
            "static_plans_are_distinct": (
                results[M15Method.STATIC_PARALLEL_HASH.value].executed_plan_id
                == expected_ids["parallel_hash_join"]
                and results[M15Method.STATIC_RISK_FIRST_BIND.value].executed_plan_id
                == expected_ids["risk_first_bind_join"]
            ),
            "all_tasks_use_two_query_calls": all(
                item.query_remote_calls == 2 for item in results.values()
            ),
            "tool_events_match_task_accounting": all(
                len(all_events[method]) == result.total_backend_calls
                and sum(
                    event["operation"] == "profile"
                    for event in all_events[method]
                )
                == result.planning_profile_calls
                and sum(
                    event["operation"] == "execute"
                    for event in all_events[method]
                )
                == result.query_remote_calls
                for method, result in results.items()
            ),
            "zero_llm_and_ontology_calls": True,
        }
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(destination / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("controlled method-matrix validation failed")
    except Exception as exc:
        error = str(exc)

    _write_json(
        destination / "backend_invocations.json",
        {
            "events_by_phase": all_events,
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    manifest = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "run_id": selected_run_id,
        "status": "success" if error is None else "failed",
        "error": error,
        "started_at": started_at,
        "ended_at": ended_at,
        "workload_id": bundle.spec.workload_id,
        "workload_manifest": dict(bundle.manifest),
        "memory_context": context.to_dict(),
        "calibration": calibration.to_dict() if calibration is not None else None,
        "calibration_accounting": {
            "included_in_method_metrics": False,
            "reason": "common frozen pre-task calibration shared by warm methods",
            "seed_memory_writes": seed_memory_writes,
        },
        "controlled_transition": {
            "calibration_latency_ms": _latencies(bundle, stale=True),
            "task_latency_ms": _latencies(bundle, stale=False),
            "changed_factor": "fuseki risk-query latency",
        },
        "methods": {
            method: result.to_dict() for method, result in results.items()
        },
        "automatic_retries": 0,
        "paper_result": False,
        "evidence_class": "controlled_method_mechanism_sanity_check",
    }
    _write_json(manifest_path, manifest)
    _write_json(
        destination / "run_status.json",
        {
            "schema_version": MATRIX_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if error is None else "failed",
            "error": error,
        },
    )
    return M15MethodMatrixRecord(
        run_id=selected_run_id,
        run_root=destination,
        success=error is None,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-bundle", required=True)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_RUN_M15_METHOD_MATRIX") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": "set XGAP_RUN_M15_METHOD_MATRIX=1 to run the matrix",
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = run_m15_controlled_method_matrix(
            workload_bundle=args.workload_bundle,
            output_root=args.output_root,
            run_id=args.run_id,
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
