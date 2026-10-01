"""Execute one authorized FinBench confirmatory measurement-block attempt.

The worker is intentionally phase-local.  It receives an already resolved and
hash-bound block attempt, compiles its native plans before fixture loading,
loads fresh job-owned Neo4j and Fuseki services once, and executes only the
frozen identities in their predeclared order.  It never opens answer oracles.
Successful rows are retained for the post-measurement oracle gate; query
timeouts remain valid method outcomes and are never converted into retries.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from xgap.backends.protocol import BackendClient
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_execution import (
    validate_finbench_confirmatory_block_execution_envelope,
)
from xgap.experiments.m15_finbench_federation import (
    build_finbench_plan_candidates,
    canonicalize_finbench_rows,
)
from xgap.experiments.m15_finbench_partition import load_finbench_source_partition
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
)
from xgap.experiments.m15_fixture_loader import BackendFixtureLoader
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


FINBENCH_CONFIRMATORY_LIVE_BLOCK_SCHEMA_VERSION = (
    "m15-finbench-live-confirmatory-block-v1"
)
FINBENCH_CONFIRMATORY_RAW_MEASUREMENTS_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-raw-measurements-v1"
)
_CONFIRMATORY_TIMEOUT_POLICY = {
    "method_timeout_seconds": 60.0,
    "transport_timeout_seconds": 65.0,
    "neo4j": {
        "setting": "db.transaction.timeout",
        "value": "60s",
        "monitor_check_interval": "1s",
    },
    "fuseki": {
        "setting": "arq:queryTimeout",
        "value_milliseconds": 60_000,
        "configuration": "FUSEKI_BASE/config.ttl",
    },
    "timeout_is_method_outcome": True,
    "automatic_retries": 0,
}


@dataclass(frozen=True)
class FinBenchConfirmatoryBlockRecord:
    attempt_id: str
    run_root: Path
    success: bool
    replacement_eligible: bool
    status_path: Path
    manifest_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "replacement_eligible": self.replacement_eligible,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _git_state(repo_root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "clean": porcelain == ""}


def _is_timeout(runtime_result: Mapping[str, Any]) -> bool:
    if runtime_result.get("success") is not False:
        return False
    nodes = runtime_result.get("node_results")
    if not isinstance(nodes, list):
        return False
    errors = [
        str(item.get("error", "")).lower()
        for item in nodes
        if isinstance(item, Mapping) and item.get("error")
    ]
    return any("timed out" in error or "timeout" in error for error in errors)


def _load_fixtures(
    *,
    partition_root: Path,
    partition: Mapping[str, Any],
    loaders: Mapping[str, BackendFixtureLoader],
) -> dict[str, Any]:
    neo4j_contract = partition.get("neo4j_load")
    neo4j_filename = (
        neo4j_contract.get("filename")
        if isinstance(neo4j_contract, Mapping)
        else "load_neo4j.cypher"
    )
    if neo4j_filename not in {
        "load_neo4j.cypher",
        "load_neo4j_batches.jsonl",
    }:
        raise ValueError("FinBench Neo4j load filename is unsupported")
    reports: dict[str, Any] = {}
    for backend_id, filename in (
        ("neo4j", neo4j_filename),
        ("fuseki", "load_fuseki.ttl"),
    ):
        report = loaders[backend_id].load(partition_root / str(filename))
        reports[backend_id] = report.to_dict()
        if not report.success:
            raise RuntimeError(
                f"FinBench {backend_id} fixture load failed: {report.error}"
            )
    return reports


def run_m15_live_finbench_confirmatory_block(
    *,
    execution_context: Mapping[str, Any],
    workload_root: str | Path,
    partition_root: str | Path,
    clients: Mapping[str, BackendClient],
    loaders: Mapping[str, BackendFixtureLoader],
    output_root: str | Path,
    query_timeout_policy: Mapping[str, Any],
    repo_root: str | Path | None = None,
) -> FinBenchConfirmatoryBlockRecord:
    """Run one block attempt and retain raw, result-blind measurements."""

    context = validate_finbench_confirmatory_block_execution_envelope(
        execution_context
    )
    timeout_policy = dict(query_timeout_policy)
    if timeout_policy != _CONFIRMATORY_TIMEOUT_POLICY:
        raise ValueError("confirmatory query timeout policy changed")
    attempt = context["block_attempt"]
    if set(clients) != {"neo4j", "fuseki"} or set(loaders) != {
        "neo4j",
        "fuseki",
    }:
        raise ValueError("confirmatory block requires exact Neo4j and Fuseki adapters")
    partition_path = Path(partition_root).resolve()
    partition = load_finbench_source_partition(partition_path)
    source_archive = partition.get("source_archive")
    if not isinstance(source_archive, Mapping) or source_archive.get("sha256") is None:
        raise ValueError("FinBench source partition identity is missing")
    workload = load_finbench_primary_public_workload(workload_root)
    workload_manifest = workload["manifest"]
    if (
        workload_manifest.get("workload_sha256") != attempt["workload_sha256"]
        or workload_manifest.get("source_archive_sha256")
        != source_archive.get("sha256")
    ):
        raise ValueError("FinBench workload and source partition identities disagree")
    repository = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    git = _git_state(repository)
    if git["clean"] is not True or git["commit"] != attempt["runner_commit"]:
        raise ValueError("confirmatory block requires its exact clean runner commit")

    candidate_cache: dict[str, dict[str, Any]] = {}
    plan_catalog: list[dict[str, Any]] = []
    for item in attempt["measurements"]:
        query_id = str(item["query_id"])
        if query_id not in candidate_cache:
            candidates = build_finbench_plan_candidates(
                workload_root, query_id=query_id
            )
            by_strategy = {
                str(candidate.plan.metadata["physical_strategy"]): candidate
                for candidate in candidates
            }
            if len(candidates) != 2 or len(by_strategy) != 2:
                raise ValueError("FinBench physical candidate pair changed")
            candidate_cache[query_id] = by_strategy
        strategy = str(item["physical_strategy"])
        candidate = candidate_cache[query_id].get(strategy)
        if candidate is None:
            raise ValueError("resolved physical strategy is not executable")
        if candidate.plan.metadata.get("workload_sha256") != attempt["workload_sha256"]:
            raise ValueError("compiled plan workload identity changed")
        plan_catalog.append(
            {
                "scheduled_identity": item["scheduled_identity"],
                "query_id": query_id,
                "family_id": item["family_id"],
                "physical_strategy": strategy,
                "plan": candidate.plan.to_dict(),
            }
        )

    preflight: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_LIVE_BLOCK_SCHEMA_VERSION,
        "attempt": attempt,
        "execution_context_sha256": context["execution_context_sha256"],
        "execution_request_sha256": attempt["execution_request_sha256"],
        "execution_authority_sha256": attempt["execution_authority_sha256"],
        "git": git,
        "source_partition_sha256": partition["partition_sha256"],
        "plan_catalog": plan_catalog,
        "query_timeout_policy": timeout_policy,
        "query_timeout_policy_sha256": content_hash(timeout_policy),
        "plan_catalog_sealed_before_fixture_load": True,
        "backend_calls_before_seal": 0,
        "oracle_content_parsed": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    preflight["preflight_sha256"] = content_hash(preflight)

    destination = Path(output_root).resolve() / str(attempt["attempt_id"])
    destination.mkdir(parents=True, exist_ok=False)
    status_path = destination / "run_status.json"
    manifest_path = destination / "run_manifest.json"
    started_at = _now()
    _write_json(destination / "preflight.json", preflight)

    raw_measurements: list[dict[str, Any]] = []
    load_reports: dict[str, Any] = {}
    error: str | None = None
    failure_category: str | None = None
    try:
        load_reports = _load_fixtures(
            partition_root=partition_path,
            partition=partition,
            loaders=loaders,
        )
        _write_json(destination / "load_reports.json", load_reports)
        plugins = BackendPluginRegistry()
        for backend_id in ("neo4j", "fuseki"):
            plugins.register(NativeBackendPlugin(backend_id, clients[backend_id]))
        scheduler = FederatedScheduler(BackendInvokeTool(plugins))
        for item in attempt["measurements"]:
            query_id = str(item["query_id"])
            strategy = str(item["physical_strategy"])
            candidate = candidate_cache[query_id][strategy]
            result = scheduler.execute(
                candidate.plan,
                goal_id=(
                    f"finbench-confirmatory:{attempt['attempt_id']}:"
                    f"{item['scheduled_identity']}"
                ),
            )
            runtime = result.to_dict()
            if result.success:
                canonical_rows = canonicalize_finbench_rows(
                    str(item["family_id"]), result.final_rows
                )
                outcome = "success"
                elapsed_ms = float(result.elapsed_ms)
                moved: int | None = result.total_bytes_moved
            elif _is_timeout(runtime):
                canonical_rows = []
                outcome = "query_timeout"
                elapsed_ms = max(60_000.0, float(result.elapsed_ms))
                moved = None
            else:
                failure_category = "backend_or_plan_failure"
                raise RuntimeError(
                    "non-timeout federated plan failure: "
                    f"{candidate.plan.plan_id}"
                )
            raw_measurements.append(
                {
                    "scheduled_identity": item["scheduled_identity"],
                    "attempt_id": attempt["attempt_id"],
                    "query_id": query_id,
                    "family_id": item["family_id"],
                    "method_id": item["method_id"],
                    "physical_strategy": strategy,
                    "outcome": outcome,
                    "elapsed_ms": elapsed_ms,
                    "total_bytes_moved": moved,
                    "total_remote_calls": result.total_remote_calls,
                    "canonical_rows": canonical_rows,
                    "canonical_rows_sha256": content_hash(canonical_rows),
                    "runtime_result": runtime,
                    "oracle_opened": False,
                    "exact_answer": None,
                }
            )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if failure_category is None:
            failure_category = "infrastructure_failure"

    raw_body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_RAW_MEASUREMENTS_SCHEMA_VERSION,
        "attempt_id": attempt["attempt_id"],
        "measurement_block_id": attempt["measurement_block_id"],
        "measurements": raw_measurements,
        "measurement_count": len(raw_measurements),
        "query_timeout_count": sum(
            item["outcome"] == "query_timeout" for item in raw_measurements
        ),
        "oracle_opened": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    raw_body["raw_measurements_sha256"] = content_hash(raw_body)
    _write_json(destination / "raw_measurements.json", raw_body)
    if load_reports and not (destination / "load_reports.json").exists():
        _write_json(destination / "load_reports.json", load_reports)

    complete = error is None and len(raw_measurements) == len(attempt["measurements"])
    replacement_eligible = (
        error is not None
        and failure_category == "infrastructure_failure"
        and len(raw_measurements) == 0
    )
    attempt_status = (
        "completed"
        if complete
        else "infrastructure_failed"
        if replacement_eligible
        else "partial_measurement_failure"
    )
    attempt_record = {
        "attempt_id": attempt["attempt_id"],
        "measurement_block_id": attempt["measurement_block_id"],
        "attempt_index": attempt["attempt_index"],
        "status": attempt_status,
        "valid_measurement_count": len(raw_measurements),
        "replacement_of_attempt_id": attempt["replacement_of_attempt_id"],
        "failure_category": None if complete else failure_category,
    }
    _write_json(destination / "attempt_record.json", attempt_record)
    ended_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": FINBENCH_CONFIRMATORY_LIVE_BLOCK_SCHEMA_VERSION,
            "status": "success" if complete else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "replacement_eligible": replacement_eligible,
            "automatic_retries": 0,
        },
    )
    manifest_body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_LIVE_BLOCK_SCHEMA_VERSION,
        "status": "success" if complete else "failed",
        "error": error,
        "started_at": started_at,
        "ended_at": ended_at,
        "git": git,
        "attempt_id": attempt["attempt_id"],
        "block_attempt_sha256": attempt["block_attempt_sha256"],
        "execution_context_sha256": context["execution_context_sha256"],
        "execution_request_sha256": attempt["execution_request_sha256"],
        "execution_authority_sha256": attempt["execution_authority_sha256"],
        "measurement_block_id": attempt["measurement_block_id"],
        "phase": attempt["phase"],
        "source_partition_sha256": partition["partition_sha256"],
        "preflight_sha256": preflight["preflight_sha256"],
        "query_timeout_policy_sha256": preflight[
            "query_timeout_policy_sha256"
        ],
        "raw_measurements_sha256": raw_body["raw_measurements_sha256"],
        "attempt_record": attempt_record,
        "expected_plan_run_count": len(attempt["measurements"]),
        "observed_method_outcome_count": len(raw_measurements),
        "observed_backend_calls": sum(
            item["total_remote_calls"] for item in raw_measurements
        ),
        "query_timeout_count": raw_body["query_timeout_count"],
        "oracle_content_parsed": False,
        "replacement_eligible": replacement_eligible,
        "automatic_retries": 0,
        "paper_result": False,
    }
    manifest_body["manifest_sha256"] = content_hash(manifest_body)
    _write_json(manifest_path, manifest_body)
    return FinBenchConfirmatoryBlockRecord(
        attempt_id=str(attempt["attempt_id"]),
        run_root=destination,
        success=complete,
        replacement_eligible=replacement_eligible,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
