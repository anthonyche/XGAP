"""Run a development-only FinBench federated correctness gate on live backends."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.backends.protocol import BackendClient
from xgap.experiments.m15_finbench_federation import (
    build_finbench_plan_candidates,
    canonicalize_finbench_rows,
)
from xgap.experiments.m15_finbench_partition import (
    load_finbench_source_partition,
    validate_finbench_source_identity,
)
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
    load_finbench_primary_workload,
)
from xgap.experiments.m15_fixture_loader import BackendFixtureLoader
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


LIVE_CORRECTNESS_SCHEMA_VERSION = "m15-finbench-live-correctness-v1"
PLAN_CATALOG_SCHEMA_VERSION = "m15-finbench-live-plan-catalog-v1"
VALIDATION_SCHEMA_VERSION = "m15-finbench-live-correctness-validation-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")


@dataclass(frozen=True)
class FinBenchCorrectnessRecord:
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


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
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


def _selected_instances(
    public: Mapping[str, Any], query_ids: Sequence[str] | None
) -> list[dict[str, Any]]:
    raw = public.get("instances")
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise ValueError("FinBench public instance list is invalid")
    instances = [dict(item) for item in raw]
    if query_ids is None:
        return instances
    selected_ids = list(query_ids)
    if (
        not selected_ids
        or len(selected_ids) != len(set(selected_ids))
        or any(not isinstance(item, str) or not _SAFE_ID.fullmatch(item) for item in selected_ids)
    ):
        raise ValueError("FinBench query selection must contain unique safe IDs")
    by_id = {str(item["query_id"]): item for item in instances}
    missing = sorted(set(selected_ids) - set(by_id))
    if missing:
        raise ValueError(f"unknown FinBench query IDs: {', '.join(missing)}")
    return [by_id[query_id] for query_id in selected_ids]


def run_m15_live_finbench_correctness(
    *,
    workload_root: str | Path,
    partition_root: str | Path,
    clients: Mapping[str, BackendClient],
    loaders: Mapping[str, BackendFixtureLoader],
    output_root: str | Path,
    run_id: str = "finbench-correctness-run",
    repo_root: str | Path | None = None,
    query_ids: Sequence[str] | None = None,
    source_identity_mode: str = "partition",
) -> FinBenchCorrectnessRecord:
    """Load one split snapshot and validate both plans for each selected query."""

    if not _SAFE_ID.fullmatch(run_id):
        raise ValueError("FinBench correctness run_id is unsafe")
    if set(clients) != {"neo4j", "fuseki"} or set(loaders) != {"neo4j", "fuseki"}:
        raise ValueError("FinBench correctness requires exact Neo4j and Fuseki adapters")
    public_workload = load_finbench_primary_public_workload(workload_root)
    partition = load_finbench_source_partition(partition_root)
    manifest = public_workload["manifest"]
    source_archive_sha256 = validate_finbench_source_identity(
        manifest, partition, source_identity_mode=source_identity_mode
    )
    instances = _selected_instances(public_workload["public_instances"], query_ids)
    plan_entries: list[dict[str, Any]] = []
    candidates_by_plan: dict[str, Any] = {}
    for instance in instances:
        for candidate in build_finbench_plan_candidates(
            workload_root, query_id=str(instance["query_id"])
        ):
            plan = candidate.plan
            if plan.plan_id in candidates_by_plan:
                raise ValueError("FinBench correctness plan IDs are not unique")
            candidates_by_plan[plan.plan_id] = candidate
            plan_entries.append(
                {
                    "query_id": instance["query_id"],
                    "family_id": instance["family_id"],
                    "split_role": instance["split_role"],
                    "semantic_equivalence_key": candidate.semantic_equivalence_key,
                    "physical_strategy": plan.metadata["physical_strategy"],
                    "plan": plan.to_dict(),
                }
            )
    plan_catalog: dict[str, Any] = {
        "schema_version": PLAN_CATALOG_SCHEMA_VERSION,
        "population_id": manifest["population_id"],
        "workload_sha256": manifest["workload_sha256"],
        "source_partition_sha256": partition["partition_sha256"],
        "source_identity_mode": source_identity_mode,
        "source_archive_sha256": source_archive_sha256,
        "query_count": len(instances),
        "plan_count": len(plan_entries),
        "plans": plan_entries,
        "sealed_before_fixture_load": True,
        "answer_oracle_bytes_hashed_for_identity": True,
        "answer_oracle_content_parsed": False,
        "backend_calls_before_seal": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    plan_catalog["plan_catalog_sha256"] = _canonical_sha256(plan_catalog)

    # Finish every fallible preflight step before creating a durable run tree. A
    # created run directory therefore always contains a terminal status, even if
    # the public workload or plan compiler rejects its input.
    destination = Path(output_root).resolve() / run_id
    destination.mkdir(parents=True, exist_ok=False)
    status_path = destination / "run_status.json"
    manifest_path = destination / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": LIVE_CORRECTNESS_SCHEMA_VERSION,
            "status": "running",
            "started_at": started_at,
        },
    )
    _write_json(destination / "plan_catalog.json", plan_catalog)

    load_reports: dict[str, Any] = {}
    execution_results: list[dict[str, Any]] = []
    validation: dict[str, Any] | None = None
    error: str | None = None
    oracle_content_parsed = False
    backend_calls_before_oracle = 0
    execution_started = time.perf_counter()
    try:
        partition_path = Path(partition_root).resolve()
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
        for backend_id, filename in (
            ("neo4j", neo4j_filename),
            ("fuseki", "load_fuseki.ttl"),
        ):
            report = loaders[backend_id].load(partition_path / filename)
            load_reports[backend_id] = report.to_dict()
            if not report.success:
                raise RuntimeError(
                    f"FinBench {backend_id} fixture load failed: {report.error}"
                )
        _write_json(destination / "load_reports.json", load_reports)

        plugins = BackendPluginRegistry()
        for backend_id in ("neo4j", "fuseki"):
            plugins.register(NativeBackendPlugin(backend_id, clients[backend_id]))
        scheduler = FederatedScheduler(BackendInvokeTool(plugins))
        for entry in plan_entries:
            candidate = candidates_by_plan[str(entry["plan"]["plan_id"])]
            result = scheduler.execute(
                candidate.plan,
                goal_id=f"finbench-correctness:{candidate.plan.plan_id}",
            )
            backend_calls_before_oracle += result.total_remote_calls
            execution_results.append(
                {
                    "query_id": entry["query_id"],
                    "family_id": entry["family_id"],
                    "split_role": entry["split_role"],
                    "plan_id": candidate.plan.plan_id,
                    "physical_strategy": entry["physical_strategy"],
                    "success": result.success,
                    "elapsed_ms": result.elapsed_ms,
                    "total_remote_calls": result.total_remote_calls,
                    "total_bytes_moved": result.total_bytes_moved,
                    "runtime_result": result.to_dict(),
                }
            )
            if not result.success:
                raise RuntimeError(
                    f"FinBench federated plan failed: {candidate.plan.plan_id}"
                )
        _write_json(destination / "execution_results.json", {"results": execution_results})

        oracle_workload = load_finbench_primary_workload(workload_root)
        oracle_content_parsed = True
        oracle_queries = oracle_workload["sealed_oracles"]["queries"]
        comparisons: list[dict[str, Any]] = []
        answers_by_query: dict[str, list[list[dict[str, Any]]]] = {}
        for result in execution_results:
            family_id = str(result["family_id"])
            query_id = str(result["query_id"])
            actual = canonicalize_finbench_rows(
                family_id, result["runtime_result"]["final_rows"]
            )
            oracle = oracle_queries.get(query_id)
            if not isinstance(oracle, Mapping) or not isinstance(
                oracle.get("final_rows"), list
            ):
                raise ValueError(f"FinBench oracle is invalid: {query_id}")
            expected = canonicalize_finbench_rows(family_id, oracle["final_rows"])
            exact = actual == expected
            comparisons.append(
                {
                    "query_id": query_id,
                    "family_id": family_id,
                    "plan_id": result["plan_id"],
                    "physical_strategy": result["physical_strategy"],
                    "exact": exact,
                    "actual_row_count": len(actual),
                    "expected_row_count": len(expected),
                }
            )
            answers_by_query.setdefault(query_id, []).append(actual)
        paired_equivalence = {
            query_id: len(answers) == 2 and answers[0] == answers[1]
            for query_id, answers in answers_by_query.items()
        }
        all_exact = all(item["exact"] for item in comparisons)
        all_equivalent = all(paired_equivalence.values())
        expected_backend_calls = len(plan_entries) * 2
        validation = {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "passed": (
                all_exact
                and all_equivalent
                and backend_calls_before_oracle == expected_backend_calls
            ),
            "all_plans_exact": all_exact,
            "all_physical_pairs_equivalent": all_equivalent,
            "paired_equivalence": paired_equivalence,
            "comparisons": comparisons,
            "expected_backend_calls": expected_backend_calls,
            "observed_backend_calls": backend_calls_before_oracle,
            "answer_oracle_content_parsed_after_all_plan_runs": True,
            "answer_oracle_fields_used_for_selection": False,
            "automatic_retries": 0,
            "paper_result": False,
        }
        validation["validation_sha256"] = _canonical_sha256(validation)
        _write_json(destination / "validation.json", validation)
        if not validation["passed"]:
            raise RuntimeError("FinBench live correctness validation failed")
    except Exception as exc:
        error = str(exc)
        if load_reports:
            _write_json(destination / "load_reports.json", load_reports)
        if execution_results:
            _write_json(
                destination / "execution_results.json", {"results": execution_results}
            )

    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": LIVE_CORRECTNESS_SCHEMA_VERSION,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    repository = Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[3]
    run_manifest: dict[str, Any] = {
        "schema_version": LIVE_CORRECTNESS_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "success" if success else "failed",
        "error": error,
        "started_at": started_at,
        "ended_at": ended_at,
        "execution_elapsed_ms": (time.perf_counter() - execution_started) * 1000,
        "git": _git_state(repository),
        "population_id": manifest["population_id"],
        "workload_sha256": manifest["workload_sha256"],
        "source_partition_sha256": partition["partition_sha256"],
        "source_identity_mode": source_identity_mode,
        "source_archive_sha256": source_archive_sha256,
        "plan_catalog_sha256": plan_catalog["plan_catalog_sha256"],
        "query_ids": [item["query_id"] for item in instances],
        "summary": {
            "query_count": len(instances),
            "family_counts": {
                family_id: sum(item["family_id"] == family_id for item in instances)
                for family_id in sorted({str(item["family_id"]) for item in instances})
            },
            "physical_plan_run_count": len(execution_results),
            "backend_calls": backend_calls_before_oracle,
            "all_plans_exact": validation.get("all_plans_exact") if validation else False,
            "all_physical_pairs_equivalent": (
                validation.get("all_physical_pairs_equivalent") if validation else False
            ),
        },
        "oracle_boundary": {
            "bytes_hashed_for_identity_before_execution": True,
            "content_parsed": oracle_content_parsed,
            "content_parsed_after_all_plan_runs": bool(
                validation
                and validation[
                    "answer_oracle_content_parsed_after_all_plan_runs"
                ]
            ),
            "backend_calls_before_open": backend_calls_before_oracle,
            "used_for_selection": False,
        },
        "automatic_retries": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "development_correctness_gate_only": True,
        "paper_result": False,
    }
    run_manifest["manifest_sha256"] = _canonical_sha256(run_manifest)
    _write_json(manifest_path, run_manifest)
    return FinBenchCorrectnessRecord(
        run_id=run_id,
        run_root=destination,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )
