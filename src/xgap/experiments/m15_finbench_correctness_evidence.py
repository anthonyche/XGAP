"""Read-only reconstruction audit for one native FinBench correctness gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_finbench_federation import (
    build_finbench_plan_candidates,
    canonicalize_finbench_rows,
)
from xgap.experiments.m15_finbench_partition import (
    PARTITION_SCHEMA_VERSION,
    load_finbench_source_partition,
    validate_finbench_source_identity,
)
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
    load_finbench_primary_workload,
)
from xgap.experiments.m15_live_finbench_correctness import (
    LIVE_CORRECTNESS_SCHEMA_VERSION,
    PLAN_CATALOG_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
)
from xgap.experiments.m15_native_services import (
    FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION,
)


FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION = (
    "m15-finbench-live-correctness-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _json_safe_check_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_check_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_check_value(item) for item in value]
    return value


@dataclass(frozen=True)
class FinBenchCorrectnessEvidenceCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": _json_safe_check_value(self.expected),
            "observed": _json_safe_check_value(self.observed),
        }


@dataclass(frozen=True)
class M15FinBenchCorrectnessEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[FinBenchCorrectnessEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(check.check_id for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [check.to_dict() for check in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
        }


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


def _read_json(path: Path) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"run tree contains a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _without_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _resolve_declared_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return None


def audit_m15_finbench_correctness(
    *, run_root: str | Path, expected_commit: str
) -> M15FinBenchCorrectnessEvidenceAudit:
    """Recompile every plan and answer comparison without mutating the run."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("run_root must be a real directory")
    before = _tree_digest(root)
    service = root / "native-service-run"
    live = service / "finbench-correctness-run"
    workload_root = root / "finbench-primary-workload"
    partition_root = root / "finbench-source-partition"
    paths = {
        "outer_status": root / "run_status.json",
        "service_status": service / "run_status.json",
        "service_manifest": service / "run_manifest.json",
        "status": live / "run_status.json",
        "manifest": live / "run_manifest.json",
        "plan_catalog": live / "plan_catalog.json",
        "load_reports": live / "load_reports.json",
        "execution_results": live / "execution_results.json",
        "validation": live / "validation.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for name, path in paths.items():
        loaded[name], states[name] = _read_json(path)

    checks: list[FinBenchCorrectnessEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            FinBenchCorrectnessEvidenceCheck(
                check_id=check_id,
                passed=expected == observed,
                expected=expected,
                observed=observed,
            )
        )

    for name, state in states.items():
        check(f"artifact.{name}", "ok", state)
    check("artifact.workload_root", True, workload_root.is_dir())
    check("artifact.partition_root", True, partition_root.is_dir())

    outer = _mapping(loaded.get("outer_status"))
    service_status = _mapping(loaded.get("service_status"))
    service_manifest = _mapping(loaded.get("service_manifest"))
    status = _mapping(loaded.get("status"))
    manifest = _mapping(loaded.get("manifest"))
    catalog = _mapping(loaded.get("plan_catalog"))
    load_reports = _mapping(loaded.get("load_reports"))
    execution_payload = _mapping(loaded.get("execution_results"))
    validation = _mapping(loaded.get("validation"))

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.commit", expected_commit, outer.get("git_commit"))
    check("outer.mode", "finbench_correctness", outer.get("workload_mode"))
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("service.status", "success", service_status.get("status"))
    check(
        "service.status_schema",
        FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION,
        service_status.get("schema_version"),
    )
    check(
        "service.schema",
        FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION,
        service_manifest.get("schema_version"),
    )
    check("service.manifest_status", "success", service_manifest.get("status"))
    service_input = _mapping(service_manifest.get("finbench_correctness"))
    check(
        "service.workload_path",
        workload_root,
        _resolve_declared_path(service_input.get("workload")),
    )
    check(
        "service.partition_path",
        partition_root,
        _resolve_declared_path(service_input.get("partition")),
    )
    check("live.schema", LIVE_CORRECTNESS_SCHEMA_VERSION, status.get("schema_version"))
    check("live.status", "success", status.get("status"))
    check("live.error", None, status.get("error"))
    check("manifest.schema", LIVE_CORRECTNESS_SCHEMA_VERSION, manifest.get("schema_version"))
    check("manifest.status", "success", manifest.get("status"))
    check("manifest.error", None, manifest.get("error"))
    check("manifest.commit", expected_commit, _mapping(manifest.get("git")).get("commit"))
    check("manifest.clean", True, _mapping(manifest.get("git")).get("clean"))
    check("manifest.retry", 0, manifest.get("automatic_retries"))
    check("manifest.llm_calls", 0, manifest.get("llm_calls"))
    check("manifest.ontology_calls", 0, manifest.get("ontology_service_calls"))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    check(
        "manifest.hash",
        manifest.get("manifest_sha256"),
        _canonical_sha256(_without_hash(manifest, "manifest_sha256")),
    )
    check("catalog.schema", PLAN_CATALOG_SCHEMA_VERSION, catalog.get("schema_version"))
    check("catalog.sealed", True, catalog.get("sealed_before_fixture_load"))
    check("catalog.oracle_hash_only", True, catalog.get("answer_oracle_bytes_hashed_for_identity"))
    check("catalog.oracle_not_parsed", False, catalog.get("answer_oracle_content_parsed"))
    check("catalog.backend_calls_before_seal", 0, catalog.get("backend_calls_before_seal"))
    check("catalog.retry", 0, catalog.get("automatic_retries"))
    check("catalog.paper_result", False, catalog.get("paper_result"))
    check(
        "catalog.hash",
        catalog.get("plan_catalog_sha256"),
        _canonical_sha256(_without_hash(catalog, "plan_catalog_sha256")),
    )
    check("manifest.catalog_hash", catalog.get("plan_catalog_sha256"), manifest.get("plan_catalog_sha256"))

    public: Mapping[str, Any] = {}
    partition: Mapping[str, Any] = {}
    oracle_queries: Mapping[str, Any] = {}
    expected_entries: list[dict[str, Any]] = []
    try:
        public = load_finbench_primary_public_workload(workload_root)
        partition = load_finbench_source_partition(partition_root)
        # Missing mode is the legacy partition-pinned contract, not an opt-in
        # to the more permissive archive identity used by original48 workpacks.
        identity_mode = manifest.get("source_identity_mode", "partition")
        if catalog.get("source_identity_mode", "partition") != identity_mode:
            raise ValueError("FinBench catalog and manifest identity modes differ")
        if service_input.get("source_identity_mode", "partition") != identity_mode:
            raise ValueError("FinBench service and manifest identity modes differ")
        archive_sha256 = validate_finbench_source_identity(
            _mapping(public.get("manifest")), partition,
            source_identity_mode=identity_mode,
        )
        for label, record in (("manifest", manifest), ("catalog", catalog)):
            if identity_mode == "source_archive" or "source_archive_sha256" in record:
                check(f"identity.{label}.archive", archive_sha256, record.get("source_archive_sha256"))
        query_ids = manifest.get("query_ids")
        if not isinstance(query_ids, list) or any(
            not isinstance(query_id, str) for query_id in query_ids
        ):
            raise ValueError("manifest query_ids are invalid")
        instances = _list(_mapping(public.get("public_instances")).get("instances"))
        by_id = {
            str(instance.get("query_id")): instance
            for instance in instances
            if isinstance(instance, Mapping)
        }
        if len(query_ids) != len(set(query_ids)) or set(query_ids) - set(by_id):
            raise ValueError("manifest query set is invalid")
        for query_id in query_ids:
            instance = _mapping(by_id[query_id])
            for candidate in build_finbench_plan_candidates(
                workload_root, query_id=query_id
            ):
                expected_entries.append(
                    {
                        "query_id": instance.get("query_id"),
                        "family_id": instance.get("family_id"),
                        "split_role": instance.get("split_role"),
                        "semantic_equivalence_key": candidate.semantic_equivalence_key,
                        "physical_strategy": candidate.plan.metadata[
                            "physical_strategy"
                        ],
                        "plan": candidate.plan.to_dict(),
                    }
                )
        oracle_queries = _mapping(
            load_finbench_primary_workload(workload_root)
            .get("sealed_oracles", {})
            .get("queries")
        )
        check("reconstruction.success", True, True)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        check("reconstruction.success", True, f"{type(exc).__name__}:{exc}")

    public_manifest = _mapping(public.get("manifest"))
    check("identity.population", public_manifest.get("population_id"), manifest.get("population_id"))
    check("identity.workload", public_manifest.get("workload_sha256"), manifest.get("workload_sha256"))
    check("identity.partition", partition.get("partition_sha256"), manifest.get("source_partition_sha256"))
    check("identity.catalog.partition", partition.get("partition_sha256"), catalog.get("source_partition_sha256"))
    check("catalog.query_count", len(_list(manifest.get("query_ids"))), catalog.get("query_count"))
    check("catalog.plan_count", len(expected_entries), catalog.get("plan_count"))
    check("catalog.plans", expected_entries, catalog.get("plans"))

    check("load.backend_set", ["fuseki", "neo4j"], sorted(load_reports))
    for backend_id in ("neo4j", "fuseki"):
        report = _mapping(load_reports.get(backend_id))
        check(f"load.{backend_id}.backend_id", backend_id, report.get("backend_id"))
        check(f"load.{backend_id}.success", True, report.get("success"))
        check(f"load.{backend_id}.error", None, report.get("error"))
    if partition.get("schema_version") == PARTITION_SCHEMA_VERSION:
        neo4j_load = _mapping(partition.get("neo4j_load"))
        neo4j_report = _mapping(load_reports.get("neo4j"))
        neo4j_metadata = _mapping(neo4j_report.get("metadata"))
        check(
            "load.neo4j.parameterized_format",
            "parameterized_jsonl_batches_v1",
            neo4j_load.get("format"),
        )
        check(
            "load.neo4j.parameterized_strategy",
            "streamed_parameterized_jsonl_batches",
            neo4j_metadata.get("strategy"),
        )
        check("load.neo4j.retry", 0, neo4j_metadata.get("automatic_retries"))
        check(
            "load.neo4j.mutation_semantics",
            "create_into_empty_job_owned_database",
            neo4j_metadata.get("mutation_semantics"),
        )
        expected_profile = (
            "finbench_sf0_1"
            if partition.get("scale_factor") == "0.1"
            else "development"
        )
        service_plan = _mapping(service_manifest.get("service_plan"))
        resource_profile = _mapping(service_plan.get("neo4j_resource_profile"))
        check(
            "service.neo4j_resource_profile",
            expected_profile,
            resource_profile.get("profile_id"),
        )

    executions = _list(execution_payload.get("results"))
    expected_plan_ids = [entry["plan"]["plan_id"] for entry in expected_entries]
    observed_plan_ids = [
        result.get("plan_id") if isinstance(result, Mapping) else None
        for result in executions
    ]
    check("execution.count", len(expected_plan_ids), len(executions))
    check("execution.plan_order", expected_plan_ids, observed_plan_ids)
    check(
        "execution.unique_plans",
        len(observed_plan_ids),
        len({_canonical_sha256(plan_id) for plan_id in observed_plan_ids}),
    )
    comparisons: list[dict[str, Any]] = []
    answers_by_query: dict[str, list[list[dict[str, Any]]]] = {}
    observed_backend_calls = 0
    for index, raw in enumerate(executions):
        result = _mapping(raw)
        plan_id = str(result.get("plan_id", f"index-{index}"))
        runtime_result = _mapping(result.get("runtime_result"))
        check(f"execution.{plan_id}.success", True, result.get("success"))
        check(f"execution.{plan_id}.runtime_success", True, runtime_result.get("success"))
        check(f"execution.{plan_id}.remote_calls", 2, result.get("total_remote_calls"))
        check(
            f"execution.{plan_id}.runtime_remote_calls",
            result.get("total_remote_calls"),
            runtime_result.get("total_remote_calls"),
        )
        calls = result.get("total_remote_calls")
        if isinstance(calls, int) and not isinstance(calls, bool):
            observed_backend_calls += calls
        family_id = result.get("family_id")
        query_id = result.get("query_id")
        try:
            oracle = _mapping(oracle_queries.get(query_id))
            actual = canonicalize_finbench_rows(
                str(family_id), _list(runtime_result.get("final_rows"))
            )
            expected = canonicalize_finbench_rows(
                str(family_id), _list(oracle.get("final_rows"))
            )
            exact = actual == expected
            comparisons.append(
                {
                    "query_id": query_id,
                    "family_id": family_id,
                    "plan_id": result.get("plan_id"),
                    "physical_strategy": result.get("physical_strategy"),
                    "exact": exact,
                    "actual_row_count": len(actual),
                    "expected_row_count": len(expected),
                }
            )
            answers_by_query.setdefault(str(query_id), []).append(actual)
        except (TypeError, ValueError) as exc:
            check(f"execution.{plan_id}.answer_reconstruction", True, str(exc))
    paired = {
        query_id: len(answers) == 2 and answers[0] == answers[1]
        for query_id, answers in answers_by_query.items()
    }
    expected_validation: dict[str, Any] = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "passed": (
            bool(comparisons)
            and all(item["exact"] for item in comparisons)
            and all(paired.values())
            and observed_backend_calls == len(expected_entries) * 2
        ),
        "all_plans_exact": bool(comparisons)
        and all(item["exact"] for item in comparisons),
        "all_physical_pairs_equivalent": bool(paired) and all(paired.values()),
        "paired_equivalence": paired,
        "comparisons": comparisons,
        "expected_backend_calls": len(expected_entries) * 2,
        "observed_backend_calls": observed_backend_calls,
        "answer_oracle_content_parsed_after_all_plan_runs": True,
        "answer_oracle_fields_used_for_selection": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    expected_validation["validation_sha256"] = _canonical_sha256(expected_validation)
    check("validation.exact", expected_validation, validation)
    check("validation.passed", True, validation.get("passed"))
    oracle_boundary = _mapping(manifest.get("oracle_boundary"))
    check("oracle.identity_hash_only", True, oracle_boundary.get("bytes_hashed_for_identity_before_execution"))
    check("oracle.content_parsed", True, oracle_boundary.get("content_parsed"))
    check("oracle.parsed_after_runs", True, oracle_boundary.get("content_parsed_after_all_plan_runs"))
    check("oracle.calls_before_parse", observed_backend_calls, oracle_boundary.get("backend_calls_before_open"))
    check("oracle.used_for_selection", False, oracle_boundary.get("used_for_selection"))
    summary = _mapping(manifest.get("summary"))
    check("summary.query_count", len(_list(manifest.get("query_ids"))), summary.get("query_count"))
    expected_family_counts: dict[str, int] = {}
    for query_id in _list(manifest.get("query_ids")):
        for instance in _list(_mapping(public.get("public_instances")).get("instances")):
            if isinstance(instance, Mapping) and instance.get("query_id") == query_id:
                family_id = str(instance.get("family_id"))
                expected_family_counts[family_id] = expected_family_counts.get(family_id, 0) + 1
                break
    check("summary.family_counts", expected_family_counts, summary.get("family_counts"))
    check("summary.plan_runs", len(executions), summary.get("physical_plan_run_count"))
    check("summary.backend_calls", observed_backend_calls, summary.get("backend_calls"))
    check("summary.all_exact", True, summary.get("all_plans_exact"))
    check("summary.all_equivalent", True, summary.get("all_physical_pairs_equivalent"))

    after = _tree_digest(root)
    mutated = before != after
    check("run_tree.unchanged", before, after)
    success = all(item.passed for item in checks) and not mutated
    return M15FinBenchCorrectnessEvidenceAudit(
        success=success,
        run_root=root,
        expected_commit=expected_commit,
        checks=tuple(checks),
        run_tree_mutated=mutated,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    run_root = Path(args.run_root).resolve()
    output = Path(args.output).resolve()
    if output == run_root or run_root in output.parents:
        print(json.dumps({"status": "failed", "error": "output must be outside run_root"}))
        return 2
    if output.exists() or output.is_symlink():
        print(json.dumps({"status": "failed", "error": "output already exists"}))
        return 2
    try:
        audit = audit_m15_finbench_correctness(
            run_root=run_root, expected_commit=args.expected_commit
        )
        _write_json(output, audit.to_dict())
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
