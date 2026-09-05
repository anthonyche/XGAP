"""Read-only integrity audit for one completed M15 native-service run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_fixture_loader import RUN_SCHEMA_VERSION as FIXTURE_SCHEMA
from xgap.experiments.m15_live_adaptive import (
    MODEL_SCHEMA_VERSION as ADAPTIVE_MODEL_SCHEMA,
    RUN_SCHEMA_VERSION as ADAPTIVE_SCHEMA,
    SOURCE_PATHS as ADAPTIVE_SOURCE_PATHS,
)
from xgap.experiments.m15_live_federated import RUN_SCHEMA_VERSION as LIVE_SCHEMA
from xgap.experiments.m15_native_artifacts import (
    DEFAULT_LOCK_PATH,
    NativeRuntimeLock,
    load_native_runtime_lock,
    parse_java_major,
)
from xgap.experiments.m15_native_runtime import STAGING_SCHEMA_VERSION
from xgap.experiments.m15_native_services import (
    ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
    LOCAL_FILESYSTEM_TYPES,
    SERVICE_PLAN_SCHEMA_VERSION,
    SERVICE_RUN_SCHEMA_VERSION,
    WORKLOAD_MODES,
)


AUDIT_SCHEMA_VERSION = "m15-b2d-native-evidence-audit-v1"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class EvidenceCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": _jsonable(self.expected),
            "observed": _jsonable(self.observed),
        }


@dataclass(frozen=True)
class NativeEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[EvidenceCheck, ...]

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": False,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> tuple[dict[str, Any] | list[Any] | None, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"
    if not isinstance(parsed, (dict, list)):
        return None, "json_root_is_not_object_or_array"
    return parsed, "ok"


def _read_environment(path: Path) -> tuple[dict[str, str] | None, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"invalid_text:{exc}"
    for line in lines:
        if "=" not in line:
            return None, f"invalid_line:{line}"
        key, value = line.split("=", 1)
        if not key or key in values:
            return None, f"duplicate_or_empty_key:{key}"
        values[key] = value
    return values, "ok"


def _read_text(path: Path) -> tuple[str | None, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        return None, "missing_empty_or_nonregular"
    try:
        return path.read_text(encoding="utf-8"), "ok"
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"invalid_text:{exc}"


def _dict(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _loopback_port(url: object) -> int | None:
    if not isinstance(url, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            return None
        return parsed.port
    except ValueError:
        return None


def _validation_is_exact(value: object) -> bool:
    validation = _dict(value)
    checks = validation.get("checks")
    return (
        validation.get("passed") is True
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(item is True for item in checks.values())
    )


def _backend_health_is_exact(value: object) -> bool:
    health = _dict(value)
    return set(health) == {"neo4j", "fuseki"} and all(
        _dict(item).get("ok") is True for item in health.values()
    )


def _load_reports_are_exact(value: object) -> bool:
    reports = _dict(value)
    return set(reports) == {"neo4j", "fuseki"} and all(
        _dict(item).get("success") is True for item in reports.values()
    )


def audit_m15_native_run(
    *,
    run_root: str | Path,
    expected_commit: str,
    repo_root: str | Path | None = None,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    workload_mode: str = "vertical_slice",
) -> NativeEvidenceAudit:
    """Audit cross-artifact invariants without changing the completed run tree."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    if workload_mode not in WORKLOAD_MODES:
        raise ValueError(f"unsupported M15 workload mode '{workload_mode}'")
    selected_run = Path(run_root)
    if selected_run.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    run = selected_run.resolve()
    if not run.is_dir():
        raise ValueError("run_root must be a real directory")
    repo = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    selected_lock = Path(lock_path)
    if not selected_lock.is_absolute():
        selected_lock = repo / selected_lock
    selected_lock = selected_lock.resolve()
    lock: NativeRuntimeLock = load_native_runtime_lock(selected_lock)
    lock_sha256 = _sha256_file(selected_lock)

    paths: dict[str, Path] = {
        "outer_status": run / "run_status.json",
        "environment": run / "environment.txt",
        "runtime_mount": run / "runtime_mount.txt",
        "java_version": run / "java_version.txt",
        "runtime_lock": run / "runtime_lock.json",
        "staging": run / "runtime_staging.json",
        "service_manifest": run / "native-service-run" / "run_manifest.json",
        "service_plan": run / "native-service-run" / "service_plan.json",
        "neo4j_config": run / "native-service-run" / "neo4j.conf",
        "health": run / "native-service-run" / "service_health.json",
        "shutdown": run / "native-service-run" / "service_shutdown.json",
        "fixture": run / "native-service-run" / "fixture-load" / "run_manifest.json",
        "neo4j_log": run / "native-service-run" / "service_logs" / "neo4j.log",
        "fuseki_log": run / "native-service-run" / "service_logs" / "fuseki.log",
    }
    if workload_mode == "vertical_slice":
        paths.update(
            {
                "live": (
                    run
                    / "native-service-run"
                    / "federated-run"
                    / "run_manifest.json"
                ),
                "result": (
                    run / "native-service-run" / "federated-run" / "result.json"
                ),
            }
        )
    else:
        adaptive_root = run / "native-service-run" / "adaptive-run"
        paths.update(
            {
                "adaptive": adaptive_root / "run_manifest.json",
                "adaptive_status": adaptive_root / "run_status.json",
                "adaptive_result": adaptive_root / "adaptive_result.json",
                "adaptive_validation": adaptive_root / "validation.json",
                "observation_collection": adaptive_root / "observation_collection.json",
                "observation_requests": adaptive_root / "observation_requests.json",
                "backend_invocations": adaptive_root / "backend_invocations.json",
                "snapshot_before": adaptive_root / "snapshot_before.json",
                "snapshot_after": adaptive_root / "snapshot_after.json",
                "cost_model": adaptive_root / "cost_model.json",
                "plan_memory": adaptive_root / "plan_memory.jsonl",
                "semantic_program": adaptive_root / "semantic_program.json",
                "candidate_plans": adaptive_root / "candidate_plans.json",
                "probe_plan": adaptive_root / "probe_plan.json",
            }
        )
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        elif key in {
            "runtime_mount",
            "java_version",
            "neo4j_config",
            "plan_memory",
        }:
            loaded[key], states[key] = _read_text(path)
        elif key.endswith("_log"):
            states[key] = (
                "ok"
                if path.is_file() and not path.is_symlink() and path.stat().st_size > 0
                else "missing_empty_or_nonregular"
            )
        else:
            loaded[key], states[key] = _read_json(path)

    checks: list[EvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(EvidenceCheck(check_id, observed == expected, expected, observed))

    for key in paths:
        check(f"artifact.{key}", "ok", states[key])

    outer = _dict(loaded.get("outer_status"))
    environment = _dict(loaded.get("environment"))
    staging = _dict(loaded.get("staging"))
    service_manifest = _dict(loaded.get("service_manifest"))
    plan = _dict(loaded.get("service_plan"))
    fixture = _dict(loaded.get("fixture"))
    health = _list(loaded.get("health"))
    shutdown = _list(loaded.get("shutdown"))

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))

    expected_run_version = (
        "m15-d2-native-adaptive-services-v1"
        if workload_mode == "adaptive"
        else "m15-b2d-native-services-v1"
    )
    check("environment.run_version", expected_run_version, environment.get("run_version"))
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check("environment.java_module", "Java/17.0.6", environment.get("java_module"))
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))
    if workload_mode == "adaptive":
        check("environment.workload_mode", "adaptive", environment.get("workload_mode"))
    filesystem_type = str(environment.get("runtime_filesystem_type", "")).lower()
    check("environment.local_filesystem", True, filesystem_type in LOCAL_FILESYSTEM_TYPES)
    runtime_mount = loaded.get("runtime_mount")
    check(
        "environment.mount_records_filesystem",
        True,
        isinstance(runtime_mount, str)
        and (
            filesystem_type in runtime_mount.lower()
            or "findmnt_unavailable=true" in runtime_mount
        ),
    )
    java_version = loaded.get("java_version")
    try:
        recorded_java_major = (
            parse_java_major(java_version) if isinstance(java_version, str) else None
        )
    except ValueError:
        recorded_java_major = None
    check("environment.java_major", 17, recorded_java_major)

    check("staging.schema", STAGING_SCHEMA_VERSION, staging.get("schema_version"))
    check("staging.status", "success", staging.get("status"))
    check("staging.lock_sha256", lock_sha256, staging.get("lock_sha256"))
    runtime_lock_digest = (
        _sha256_file(paths["runtime_lock"])
        if states["runtime_lock"] == "ok"
        else None
    )
    check("runtime_lock.snapshot_sha256", lock_sha256, runtime_lock_digest)
    check("staging.automatic_retries", 0, staging.get("automatic_retries"))
    staged = _list(staging.get("staged_artifacts"))
    staged_by_product = {
        str(_dict(item).get("product")): _dict(item) for item in staged
    }
    check("staging.products", {"neo4j", "fuseki"}, set(staged_by_product))
    for artifact in lock.artifacts:
        staged_item = staged_by_product.get(artifact.product, {})
        inspection = _dict(staged_item.get("inspection"))
        check(
            f"staging.{artifact.product}.archive_size",
            artifact.size_bytes,
            inspection.get("archive_size_bytes"),
        )
        check(
            f"staging.{artifact.product}.digest_algorithm",
            artifact.digest_algorithm,
            inspection.get("digest_algorithm"),
        )
        check(
            f"staging.{artifact.product}.digest",
            artifact.digest_value,
            inspection.get("digest_value"),
        )

    expected_service_schema = (
        ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION
        if workload_mode == "adaptive"
        else SERVICE_RUN_SCHEMA_VERSION
    )
    check("service.schema", expected_service_schema, service_manifest.get("schema_version"))
    check("service.status", "success", service_manifest.get("status"))
    check("service.error", None, service_manifest.get("error"))
    check("service.automatic_retries", 0, service_manifest.get("automatic_retries"))
    check("service.restarts", 0, service_manifest.get("service_restarts"))
    check("service.public_ports", False, service_manifest.get("public_ports"))
    check("service.credentials", False, service_manifest.get("credentials_persisted"))
    if workload_mode == "adaptive":
        check("outer.workload_mode", "adaptive", outer.get("workload_mode"))
        check("service.workload_mode", "adaptive", service_manifest.get("workload_mode"))

    check("plan.schema", SERVICE_PLAN_SCHEMA_VERSION, plan.get("schema_version"))
    check("plan.runtime_lock_sha256", lock_sha256, plan.get("runtime_lock_sha256"))
    staging_digest = (
        _sha256_file(paths["staging"]) if states["staging"] == "ok" else None
    )
    check("plan.staging_manifest_sha256", staging_digest, plan.get("staging_manifest_sha256"))
    check("plan.java_major", 17, _dict(plan.get("java")).get("major"))
    check("plan.filesystem_type", filesystem_type, plan.get("filesystem_type"))
    check("plan.public_ports", False, plan.get("public_ports"))
    check("plan.automatic_retries", 0, plan.get("automatic_retries"))
    check("plan.credentials", False, plan.get("credentials_persisted"))
    check("service.plan_matches_file", plan, service_manifest.get("service_plan"))
    check("service.health_matches_file", health, service_manifest.get("health"))
    check("service.shutdown_matches_file", shutdown, service_manifest.get("shutdown"))

    allocation_id = environment.get("slurm_job_id")
    check("allocation.outer_environment", allocation_id, outer.get("slurm_job_id"))
    check("allocation.service_manifest", allocation_id, service_manifest.get("allocation_id"))
    check("allocation.plan", allocation_id, plan.get("allocation_id"))
    runtime_root = environment.get("runtime_root")
    check("runtime.staging", runtime_root, staging.get("runtime_root"))
    check("runtime.service", runtime_root, service_manifest.get("runtime_root"))
    check("runtime.plan", runtime_root, plan.get("runtime_root"))

    services = _list(plan.get("services"))
    services_by_id = {
        str(_dict(item).get("service_id")): _dict(item) for item in services
    }
    check("plan.service_ids", {"neo4j", "fuseki"}, set(services_by_id))
    neo4j = services_by_id.get("neo4j", {})
    fuseki = services_by_id.get("fuseki", {})
    check("plan.neo4j_version", "5.26.30", neo4j.get("version"))
    check("plan.fuseki_version", "5.6.0", fuseki.get("version"))
    check("plan.neo4j_command", "console", (_list(neo4j.get("command")) or [None])[-1])
    fuseki_tail = _list(fuseki.get("command"))[1:]
    fuseki_expected = [
        "--localhost",
        "--ping",
        "--port",
        str(_loopback_port(fuseki.get("health_url"))),
        "--update",
        "--mem",
        "/xgap",
    ]
    check("plan.fuseki_command", fuseki_expected, fuseki_tail)
    neo4j_http_port = _loopback_port(plan.get("neo4j_http_url"))
    fuseki_http_port = _loopback_port(plan.get("fuseki_url"))
    check(
        "plan.neo4j_health_endpoint",
        neo4j_http_port,
        _loopback_port(neo4j.get("health_url")),
    )
    check(
        "plan.fuseki_health_endpoint",
        fuseki_http_port,
        _loopback_port(fuseki.get("health_url")),
    )
    ports = {
        neo4j_http_port,
        fuseki_http_port,
        _loopback_port(fuseki.get("health_url")),
    }
    check("plan.loopback_http_ports", 2, len({item for item in ports if item is not None}))
    neo4j_config = loaded.get("neo4j_config")
    config_values: dict[str, str] = {}
    if isinstance(neo4j_config, str):
        for line in neo4j_config.splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config_values[key] = value
    check("plan.neo4j_auth_disabled", "false", config_values.get("dbms.security.auth_enabled"))
    check(
        "plan.neo4j_http_loopback",
        f"127.0.0.1:{neo4j_http_port}",
        config_values.get("server.http.listen_address"),
    )
    directory_values = [
        value for key, value in config_values.items() if key.startswith("server.directories.")
    ]
    check(
        "plan.neo4j_directories_runtime_scoped",
        True,
        bool(directory_values)
        and all(
            str(value).startswith(str(runtime_root) + "/") for value in directory_values
        ),
    )

    check(
        "health.services",
        ["neo4j", "fuseki"],
        [str(_dict(item).get("service_id")) for item in health],
    )
    check(
        "health.all_success",
        True,
        len(health) == 2
        and all(
            _dict(item).get("success") is True
            and isinstance(_dict(item).get("attempts"), int)
            and _dict(item).get("attempts", 0) >= 1
            for item in health
        ),
    )
    check(
        "shutdown.reverse_order",
        ["fuseki", "neo4j"],
        [str(_dict(item).get("service_id")) for item in shutdown],
    )
    check(
        "shutdown.all_clean",
        True,
        len(shutdown) == 2
        and all(
            _dict(item).get("success") is True
            and _dict(item).get("initial_exit_code") is None
            and _dict(item).get("final_exit_code") is not None
            for item in shutdown
        ),
    )

    check("fixture.schema", FIXTURE_SCHEMA, fixture.get("schema_version"))
    check("fixture.status", "success", fixture.get("status"))
    check("fixture.validation", True, _validation_is_exact(fixture.get("validation")))
    check(
        "fixture.health_before",
        True,
        _backend_health_is_exact(fixture.get("health_before")),
    )
    check(
        "fixture.health_after",
        True,
        _backend_health_is_exact(fixture.get("health_after")),
    )
    check("fixture.load_reports", True, _load_reports_are_exact(fixture.get("load_reports")))
    check("fixture.automatic_retries", 0, fixture.get("automatic_retries"))
    check("fixture.git_commit", expected_commit, _dict(fixture.get("git")).get("commit"))
    check("fixture.git_clean", True, _dict(fixture.get("git")).get("clean"))

    expected_result = json.loads(
        (repo / "examples" / "m15_split_financial_risk" / "expected_result.json").read_text(
            encoding="utf-8"
        )
    )
    if workload_mode == "vertical_slice":
        live = _dict(loaded.get("live"))
        result = _dict(loaded.get("result"))
        check("live.schema", LIVE_SCHEMA, live.get("schema_version"))
        check("live.status", "success", live.get("status"))
        check("live.validation", True, _validation_is_exact(live.get("validation")))
        check(
            "live.backend_health",
            True,
            _backend_health_is_exact(live.get("backend_health")),
        )
        check("live.no_llm", True, live.get("no_llm"))
        check("live.no_ontology", True, live.get("no_ontology"))
        check("live.automatic_retries", 0, live.get("automatic_retries"))
        check("live.git_commit", expected_commit, _dict(live.get("git")).get("commit"))
        check("live.git_clean", True, _dict(live.get("git")).get("clean"))

        check("result.success", True, result.get("success"))
        check("result.exact_rows", expected_result, result.get("final_rows"))
        check("result.remote_calls", 2, result.get("total_remote_calls"))
        moved = result.get("total_bytes_moved")
        check("result.positive_bytes", True, isinstance(moved, int) and moved > 0)
    else:
        adaptive = _dict(loaded.get("adaptive"))
        adaptive_status = _dict(loaded.get("adaptive_status"))
        adaptive_result = _dict(loaded.get("adaptive_result"))
        adaptive_validation = _dict(loaded.get("adaptive_validation"))
        collection = _dict(loaded.get("observation_collection"))
        invocations = _dict(loaded.get("backend_invocations"))
        snapshot_before = _dict(loaded.get("snapshot_before"))
        snapshot_after = _dict(loaded.get("snapshot_after"))
        cost_model = _dict(loaded.get("cost_model"))
        semantic_program = _dict(loaded.get("semantic_program"))
        candidate_plans = _dict(loaded.get("candidate_plans"))
        probe_plan = _dict(loaded.get("probe_plan"))
        observation_requests = _list(loaded.get("observation_requests"))

        check("adaptive.schema", ADAPTIVE_SCHEMA, adaptive.get("schema_version"))
        check("adaptive.status", "success", adaptive.get("status"))
        check("adaptive.error", None, adaptive.get("error"))
        check("adaptive_status.schema", ADAPTIVE_SCHEMA, adaptive_status.get("schema_version"))
        check("adaptive_status.status", "success", adaptive_status.get("status"))
        check("adaptive_status.error", None, adaptive_status.get("error"))
        check(
            "adaptive_status.run_id",
            adaptive.get("run_id"),
            adaptive_status.get("run_id"),
        )
        check(
            "adaptive.validation",
            True,
            _validation_is_exact(adaptive.get("validation")),
        )
        check(
            "adaptive.validation_matches_file",
            adaptive_validation,
            adaptive.get("validation"),
        )
        check(
            "adaptive.backend_health",
            True,
            _backend_health_is_exact(adaptive.get("backend_health")),
        )
        check("adaptive.no_llm", True, adaptive.get("no_llm"))
        check("adaptive.no_ontology", True, adaptive.get("no_ontology"))
        check("adaptive.paper_result", False, adaptive.get("paper_result"))
        check(
            "adaptive.evidence_class",
            "live_backend_development_gate",
            adaptive.get("evidence_class"),
        )
        check("adaptive.automatic_retries", 0, adaptive.get("automatic_retries"))
        check(
            "adaptive.git_commit",
            expected_commit,
            _dict(adaptive.get("git")).get("commit"),
        )
        check("adaptive.git_clean", True, _dict(adaptive.get("git")).get("clean"))
        check("adaptive.memory_before", True, adaptive.get("memory_before_reopened"))
        check("adaptive.memory_after", True, adaptive.get("memory_after_reopened"))
        expected_hashes = {
            str(path): _sha256_file(repo / path) for path in ADAPTIVE_SOURCE_PATHS
        }
        check("adaptive.input_sha256", expected_hashes, adaptive.get("input_sha256"))
        expected_artifacts = {
            "adaptive_result.json",
            "backend_invocations.json",
            "candidate_plans.json",
            "cost_model.json",
            "health.json",
            "observation_collection.json",
            "observation_requests.json",
            "plan_memory.jsonl",
            "probe_plan.json",
            "run_manifest.json",
            "run_status.json",
            "semantic_program.json",
            "snapshot_after.json",
            "snapshot_before.json",
            "validation.json",
        }
        check(
            "adaptive.artifacts",
            expected_artifacts,
            set(_list(adaptive.get("artifacts"))),
        )

        summary = _dict(adaptive.get("adaptive_summary"))
        check("adaptive.summary_success", True, summary.get("success"))
        check("adaptive.summary_remote_calls", 2, summary.get("total_remote_calls"))
        check(
            "adaptive.summary_replan_count",
            True,
            isinstance(summary.get("replan_count"), int)
            and not isinstance(summary.get("replan_count"), bool)
            and summary.get("replan_count") in {0, 1},
        )
        valid_plan_ids = {"m15-parallel-hash", "m15-risk-first-bind"}
        check(
            "adaptive.summary_initial_plan",
            True,
            summary.get("initial_plan_id") in valid_plan_ids,
        )
        check(
            "adaptive.summary_executed_plan",
            True,
            summary.get("executed_plan_id") in valid_plan_ids,
        )

        check("adaptive_result.success", True, adaptive_result.get("success"))
        check("adaptive_result.error", None, adaptive_result.get("error"))
        check(
            "adaptive_result.exact_rows",
            expected_result,
            _dict(adaptive_result.get("final_run")).get("final_rows"),
        )
        check(
            "adaptive_result.remote_calls",
            2,
            adaptive_result.get("total_remote_calls"),
        )
        check(
            "adaptive_result.reused_prefix",
            ["align-risk", "exchange-risk", "high-risk"],
            adaptive_result.get("reused_node_ids"),
        )
        check(
            "adaptive_result.replan_count",
            True,
            isinstance(adaptive_result.get("replan_count"), int)
            and not isinstance(adaptive_result.get("replan_count"), bool)
            and adaptive_result.get("replan_count") in {0, 1},
        )

        check("collection.success", True, collection.get("success"))
        check("collection.error", None, collection.get("error"))
        check("collection.calls", 3, collection.get("attempted_calls"))
        check("collection.automatic_retries", 0, collection.get("automatic_retries"))
        collection_results = _list(collection.get("tool_results"))
        check(
            "collection.all_success",
            True,
            len(collection_results) == 3
            and all(_dict(item).get("status") == "success" for item in collection_results),
        )
        check(
            "collection.snapshot_matches_file",
            snapshot_before,
            collection.get("snapshot"),
        )
        expected_requests = [
            (
                "profile-neo4j-full",
                "neo4j-recent-transfers-full",
                "neo4j",
                "profile",
                {"query_id": "recent-transfers-full"},
            ),
            (
                "profile-neo4j-bound",
                "neo4j-recent-transfers-bound",
                "neo4j",
                "profile",
                {"query_id": "recent-transfers-bound"},
            ),
            (
                "profile-fuseki-risk",
                "fuseki-high-risk",
                "fuseki",
                "profile",
                {"query_id": "high-risk"},
            ),
        ]
        observed_requests = [
            (
                _dict(item).get("call_id"),
                _dict(item).get("observation_key"),
                _dict(item).get("backend_id"),
                _dict(item).get("operation"),
                _dict(item).get("payload"),
            )
            for item in observation_requests
        ]
        check("collection.requests", expected_requests, observed_requests)
        check(
            "collection.requests_match_file",
            observation_requests,
            collection.get("requests"),
        )

        events = _list(invocations.get("events"))
        check("invocations.total", 5, invocations.get("total_tool_invocations"))
        check("invocations.automatic_retries", 0, invocations.get("automatic_retries"))
        check(
            "invocations.sequence",
            ["profile", "profile", "profile", "execute", "execute"],
            [str(_dict(event).get("operation")) for event in events],
        )
        profile_backends = [
            str(_dict(event).get("backend_id")) for event in events[:3]
        ]
        check(
            "invocations.profile_backends",
            ["neo4j", "neo4j", "fuseki"],
            profile_backends,
        )
        check(
            "invocations.profile_modes",
            ["backend_native", "backend_native", "wall_clock_execute"],
            [str(_dict(event).get("observation_mode")) for event in events[:3]],
        )
        check(
            "invocations.profile_artifacts",
            [
                "m15-split-neo4j",
                "m15-split-neo4j-bound",
                "m15-split-fuseki",
            ],
            [str(_dict(event).get("artifact_id")) for event in events[:3]],
        )
        execute_events = [
            _dict(event)
            for event in events
            if _dict(event).get("operation") == "execute"
        ]
        check(
            "invocations.execute_backends",
            {"neo4j": 1, "fuseki": 1},
            {
                backend_id: sum(
                    event.get("backend_id") == backend_id for event in execute_events
                )
                for backend_id in ("neo4j", "fuseki")
            },
        )
        fuseki_execute_artifacts = [
            event.get("artifact_id")
            for event in execute_events
            if event.get("backend_id") == "fuseki"
        ]
        neo4j_execute_artifacts = [
            event.get("artifact_id")
            for event in execute_events
            if event.get("backend_id") == "neo4j"
        ]
        check(
            "invocations.fuseki_execute_artifact",
            ["m15-split-fuseki"],
            fuseki_execute_artifacts,
        )
        check(
            "invocations.neo4j_execute_artifact",
            True,
            len(neo4j_execute_artifacts) == 1
            and neo4j_execute_artifacts[0]
            in {"m15-split-neo4j", "m15-split-neo4j-bound"},
        )
        check(
            "invocations.all_success",
            True,
            len(events) == 5
            and all(_dict(event).get("status") == "success" for event in events),
        )

        check("snapshot.before_version", "profile-task-0", snapshot_before.get("version"))
        check("snapshot.after_version", "query-task-1", snapshot_after.get("version"))
        check(
            "snapshot.identity_stable",
            snapshot_before.get("snapshot_id"),
            snapshot_after.get("snapshot_id"),
        )
        check("snapshot.before_estimates", 3, len(_list(snapshot_before.get("estimates"))))
        check("snapshot.after_estimates", 3, len(_list(snapshot_after.get("estimates"))))
        check(
            "snapshot.before_observation_keys",
            {
                "neo4j-recent-transfers-full",
                "neo4j-recent-transfers-bound",
                "fuseki-high-risk",
            },
            {
                _dict(item).get("observation_key")
                for item in _list(snapshot_before.get("estimates"))
            },
        )

        check("cost_model.schema", ADAPTIVE_MODEL_SCHEMA, cost_model.get("schema_version"))
        check("cost_model.calibrated", False, cost_model.get("calibrated"))
        check("cost_model.paper_result", False, cost_model.get("paper_result"))
        check("cost_model.bandwidth", 1000.0, cost_model.get("bandwidth_bytes_per_ms"))
        check("cost_model.exchange_fixed", 0.5, cost_model.get("exchange_fixed_ms"))
        check("cost_model.coordinator_row", 0.001, cost_model.get("coordinator_row_ms"))
        check(
            "semantic_program.id",
            "m15-split-financial-risk-exact",
            semantic_program.get("program_id"),
        )
        check(
            "candidate_plans.semantic_equivalence",
            "m15:recent-alice-transfers-to-high-risk-company:exact:v1",
            candidate_plans.get("semantic_equivalence_key"),
        )
        candidate_ids = {
            _dict(item).get("plan_id") for item in _list(candidate_plans.get("plans"))
        }
        check(
            "candidate_plans.ids",
            {"m15-parallel-hash", "m15-risk-first-bind"},
            candidate_ids,
        )
        check("probe_plan.remote_budget", 1, probe_plan.get("max_remote_calls"))
        check(
            "probe_plan.nodes",
            ["high-risk", "align-risk", "exchange-risk"],
            [_dict(item).get("node_id") for item in _list(probe_plan.get("nodes"))],
        )
        memory_text = loaded.get("plan_memory")
        memory_records: list[Any] = []
        if isinstance(memory_text, str):
            try:
                memory_records = [
                    json.loads(line) for line in memory_text.splitlines() if line
                ]
            except json.JSONDecodeError:
                memory_records = []
        check("memory.record_count", 2, len(memory_records))
        check(
            "memory.versions",
            ["profile-task-0", "query-task-1"],
            [_dict(item).get("version") for item in memory_records],
        )

    return NativeEvidenceAudit(
        success=all(item.passed for item in checks),
        run_root=run,
        expected_commit=expected_commit,
        checks=tuple(checks),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--output")
    parser.add_argument(
        "--workload-mode",
        choices=sorted(WORKLOAD_MODES),
        default="vertical_slice",
    )
    args = parser.parse_args(argv)
    try:
        audit = audit_m15_native_run(
            run_root=args.run_root,
            expected_commit=args.expected_commit,
            repo_root=args.repo_root,
            workload_mode=args.workload_mode,
        )
        payload = audit.to_dict()
        if args.output:
            output = Path(args.output).resolve()
            run = Path(args.run_root).resolve()
            if output == run or run in output.parents:
                raise ValueError("audit output must be outside the completed run tree")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
