"""Execute the F2C exact parameterized task stream on black-box backends."""

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
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_PARAMETERIZED_STREAM_SCHEMA_VERSION = "m15-f2c4-live-parameterized-stream-v1"
TASK_STREAM_SCHEMA_VERSION = "m15-f2c4-exact-task-stream-v1"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")


@dataclass(frozen=True)
class M15LiveParameterizedStreamRecord:
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


def build_m15_parameterized_task_stream(
    workload: M15ParameterizedWorkloadBundle | str | Path,
) -> dict[str, Any]:
    """Freeze one deterministic seed-then-held-out exact task stream."""

    bundle = load_m15_parameterized_workload_bundle(
        workload.root
        if isinstance(workload, M15ParameterizedWorkloadBundle)
        else workload
    )
    tasks = []
    for index, record in enumerate(bundle.manifest["instances"], start=1):
        tasks.append(
            {
                "sequence_index": index,
                "task_id": f"m15-f2c4-task-{index:02d}",
                "query_id": record["query_id"],
                "split_role": record["split_role"],
                "family_compatibility_sha256": bundle.manifest[
                    "family_compatibility_sha256"
                ],
                "query_instance_sha256": record["query_instance_sha256"],
                "semantic_deviation": 0,
                "strategies": list(_STRATEGIES),
            }
        )
    return {
        "schema_version": TASK_STREAM_SCHEMA_VERSION,
        "workload_id": bundle.spec.workload_id,
        "bundle_content_sha256": bundle.manifest["bundle_content_sha256"],
        "family_compatibility_sha256": bundle.manifest[
            "family_compatibility_sha256"
        ],
        "task_count": len(tasks),
        "task_order": "declared_seed_then_heldout_instance",
        "tasks": tasks,
        "automatic_retries": 0,
        "paper_result": False,
    }


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


def run_m15_live_parameterized_stream(
    *,
    workload_bundle: M15ParameterizedWorkloadBundle | str | Path,
    clients: Mapping[str, BackendClient],
    output_root: str | Path,
    run_id: str = "parameterized-stream-run",
    repo_root: str | Path | None = None,
) -> M15LiveParameterizedStreamRecord:
    """Run both exact plans for all six instances; never select via an oracle."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    bundle = load_m15_parameterized_workload_bundle(
        workload_bundle.root
        if isinstance(workload_bundle, M15ParameterizedWorkloadBundle)
        else workload_bundle
    )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    if set(clients) != {"neo4j", "fuseki"}:
        raise ValueError(
            "parameterized stream requires exactly neo4j and fuseki clients"
        )
    destination = Path(output_root)
    if not destination.is_absolute():
        destination = root / destination
    run_root = destination.resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_PARAMETERIZED_STREAM_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    stream = build_m15_parameterized_task_stream(bundle)
    _write_json(run_root / "task_stream.json", stream)
    health: dict[str, Any] = {}
    all_events: dict[str, list[dict[str, Any]]] = {}
    results: dict[str, dict[str, Any]] = {}
    checks: dict[str, bool] = {}
    error: str | None = None
    try:
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

        for task in stream["tasks"]:
            query_id = task["query_id"]
            instance = load_m15_parameterized_instance(bundle, query_id)
            candidates = build_m15_parameterized_plan_candidates(
                bundle,
                query_id=query_id,
            )
            candidate_payload = {
                "semantic_equivalence_key": candidates[0].semantic_equivalence_key,
                "plans": [candidate.plan.to_dict() for candidate in candidates],
            }
            _write_json(
                run_root / "tasks" / query_id / "candidate_plans.json",
                candidate_payload,
            )
            checks[f"{query_id}:two_strategies"] = (
                tuple(
                    candidate.plan.metadata["physical_strategy"]
                    for candidate in candidates
                )
                == _STRATEGIES
            )
            checks[f"{query_id}:same_semantics"] = (
                len(
                    {
                        candidate.semantic_equivalence_key
                        for candidate in candidates
                    }
                )
                == 1
            )
            query_results: dict[str, Any] = {}
            for candidate in candidates:
                strategy = str(candidate.plan.metadata["physical_strategy"])
                events: list[dict[str, Any]] = []
                scheduler = FederatedScheduler(_backend_tool(clients, events))
                result = scheduler.execute(
                    candidate.plan,
                    goal_id=task["task_id"],
                )
                for sequence, event in enumerate(events, start=1):
                    event["sequence"] = sequence
                    event["query_id"] = query_id
                    event["physical_strategy"] = strategy
                all_events[f"{query_id}:{strategy}"] = events
                payload = result.to_dict()
                query_results[strategy] = payload
                _write_json(
                    run_root / "tasks" / query_id / f"{strategy}.json",
                    payload,
                )
                checks[f"{query_id}:{strategy}:success"] = result.success
                checks[f"{query_id}:{strategy}:exact_answer"] = (
                    result.final_rows == tuple(instance["final_oracle"])
                )
                checks[f"{query_id}:{strategy}:two_remote_calls"] = (
                    result.total_remote_calls == 2
                )
                checks[f"{query_id}:{strategy}:two_tool_events"] = (
                    len(events) == 2
                    and all(event["operation"] == "execute" for event in events)
                )
                if not result.success:
                    raise RuntimeError(
                        f"query '{query_id}' strategy '{strategy}' failed"
                    )
                if not checks[f"{query_id}:{strategy}:exact_answer"]:
                    raise RuntimeError(
                        f"query '{query_id}' strategy '{strategy}' returned "
                        "a non-oracle answer"
                    )
            results[query_id] = query_results
        checks["all_declared_tasks_executed_once"] = (
            list(results) == [task["query_id"] for task in stream["tasks"]]
        )
        checks["all_plans_zero_semantic_deviation"] = all(
            plan["metadata"]["semantic_deviation"] == 0
            for query_id in results
            for plan in json.loads(
                (
                    run_root / "tasks" / query_id / "candidate_plans.json"
                ).read_text(encoding="utf-8")
            )["plans"]
        )
        validation = {"passed": all(checks.values()), "checks": checks}
        _write_json(run_root / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("live parameterized stream validation failed")
    except Exception as exc:  # Preserve the first external failure; never retry.
        error = str(exc)
        if not (run_root / "health.json").exists():
            _write_json(run_root / "health.json", health)

    _write_json(
        run_root / "backend_invocations.json",
        {
            "events_by_task_and_strategy": all_events,
            "total_tool_invocations": sum(len(items) for items in all_events.values()),
            "automatic_retries": 0,
        },
    )
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_PARAMETERIZED_STREAM_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    strategy_results = [
        result for query_results in results.values() for result in query_results.values()
    ]
    _write_json(
        manifest_path,
        {
            "schema_version": LIVE_PARAMETERIZED_STREAM_SCHEMA_VERSION,
            "run_id": run_id,
            "dataset_id": f"m15_f2c:{bundle.spec.workload_id}",
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
                f"bundle:{bundle.spec.workload_id}/manifest.json": _sha256_file(
                    bundle.root / "manifest.json"
                )
            },
            "workload_bundle": dict(bundle.manifest),
            "task_stream": stream,
            "backend_health": health,
            "summary": {
                "query_instance_count": len(results),
                "strategy_run_count": len(strategy_results),
                "total_remote_calls": sum(
                    result["total_remote_calls"] for result in strategy_results
                ),
                "total_bytes_moved": sum(
                    result["total_bytes_moved"] for result in strategy_results
                ),
                "exact_answer_count": sum(
                    value
                    for key, value in checks.items()
                    if key.endswith(":exact_answer")
                ),
            },
            "validation": {
                "passed": bool(checks) and all(checks.values()),
                "checks": checks,
            },
            "evidence_class": "live_parameterized_exact_plan_bridge_engineering_gate",
            "answer_oracle_used_for_plan_construction": False,
            "memory_enabled": False,
            "llm_calls_made": 0,
            "ontology_calls_made": 0,
            "automatic_retries": 0,
            "paper_result": False,
            "artifacts": sorted(path.name for path in run_root.iterdir()),
        },
    )
    return M15LiveParameterizedStreamRecord(
        run_id=run_id,
        run_root=run_root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
