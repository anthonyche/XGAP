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
from xgap.experiments.m15_live_method_matrix import (
    CAMPAIGN_BINDING_SCHEMA_VERSION,
    LIVE_MATRIX_COST_MODEL_VERSION,
    LIVE_MATRIX_SCHEMA_VERSION,
    QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION,
)
from xgap.experiments.m15_campaign import compile_m15_campaign_file
from xgap.experiments.m15_live_campaign_session import (
    LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION,
    SUPPORTED_QUERY_ID as CAMPAIGN_SUPPORTED_QUERY_ID,
)
from xgap.experiments.m15_live_query_bound_session import (
    LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION,
    prepare_m15_live_query_bound_session,
)
from xgap.experiments.m15_method_policy import (
    METHOD_POLICY_SCHEMA_VERSION,
    M15_METHOD_POLICIES,
    M15Method,
)
from xgap.experiments.m15_query_bound_campaign import (
    compile_m15_query_bound_campaign_file,
)
from xgap.experiments.m15_native_artifacts import (
    DEFAULT_LOCK_PATH,
    NativeRuntimeLock,
    load_native_runtime_lock,
    parse_java_major,
)
from xgap.experiments.m15_native_runtime import STAGING_SCHEMA_VERSION
from xgap.experiments.m15_native_services import (
    ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
    CAMPAIGN_SESSION_SERVICE_RUN_SCHEMA_VERSION,
    LOCAL_FILESYSTEM_TYPES,
    METHOD_MATRIX_SERVICE_RUN_SCHEMA_VERSION,
    QUERY_BOUND_SESSION_SERVICE_RUN_SCHEMA_VERSION,
    SCALED_ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
    SERVICE_PLAN_SCHEMA_VERSION,
    SERVICE_RUN_SCHEMA_VERSION,
    WORKLOAD_MODES,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    M15WorkloadSpec,
    load_m15_workload_bundle,
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
    adaptive_mode = workload_mode in {
        "adaptive",
        "scaled_adaptive",
        "scaled_method_matrix",
        "scaled_campaign_session",
        "scaled_query_bound_session",
    }
    campaign_session_mode = workload_mode == "scaled_campaign_session"
    query_bound_session_mode = workload_mode == "scaled_query_bound_session"
    bound_session_mode = campaign_session_mode or query_bound_session_mode
    method_matrix_mode = workload_mode in {
        "scaled_method_matrix",
        "scaled_campaign_session",
        "scaled_query_bound_session",
    }
    scaled_mode = workload_mode in {
        "scaled_adaptive",
        "scaled_method_matrix",
        "scaled_campaign_session",
        "scaled_query_bound_session",
    }
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
    elif method_matrix_mode:
        sequence_root = run / "native-service-run"
        if campaign_session_mode:
            sequence_root = sequence_root / "campaign-session-run"
            paths.update(
                {
                    "campaign": sequence_root / "run_manifest.json",
                    "campaign_status": sequence_root / "run_status.json",
                    "campaign_validation": sequence_root / "validation.json",
                    "campaign_plan": sequence_root / "campaign_plan.json",
                    "campaign_session_plan": sequence_root / "session_plan.json",
                    "campaign_binding": sequence_root / "campaign_binding.json",
                }
            )
        elif query_bound_session_mode:
            sequence_root = sequence_root / "query-bound-session-run"
            paths.update(
                {
                    "query_bound": sequence_root / "run_manifest.json",
                    "query_bound_status": sequence_root / "run_status.json",
                    "query_bound_validation": sequence_root / "validation.json",
                    "query_bound_plan": sequence_root
                    / "query_bound_campaign_plan.json",
                    "query_bound_session_plan": sequence_root
                    / "session_plan.json",
                    "query_bound_binding": sequence_root
                    / "campaign_binding.json",
                    "query_bound_contract": sequence_root
                    / "query_contracts"
                    / f"{CAMPAIGN_SUPPORTED_QUERY_ID}.json",
                }
            )
        matrix_root = sequence_root / "method-matrix-run"
        paths.update(
            {
                "matrix": matrix_root / "run_manifest.json",
                "matrix_status": matrix_root / "run_status.json",
                "matrix_validation": matrix_root / "validation.json",
                "matrix_calibration": matrix_root / "calibration.json",
                "matrix_calibration_snapshot": matrix_root / "calibration_snapshot.json",
                "matrix_observation_requests": matrix_root
                / "observation_requests.json",
                "matrix_invocations": matrix_root / "backend_invocations.json",
                "matrix_cost_model": matrix_root / "cost_model.json",
                "matrix_memory_context": matrix_root / "memory_context.json",
                "matrix_method_policies": matrix_root / "method_policies.json",
                "matrix_semantic_program": matrix_root / "semantic_program.json",
                "matrix_candidate_plans": matrix_root / "candidate_plans.json",
                "matrix_probe_plan": matrix_root / "probe_plan.json",
                **(
                    {"matrix_campaign_binding": matrix_root / "campaign_binding.json"}
                    if bound_session_mode
                    else {}
                ),
                "matrix_static_parallel": matrix_root
                / "methods"
                / "static_parallel_hash.json",
                "matrix_static_bind": matrix_root
                / "methods"
                / "static_risk_first_bind.json",
                "matrix_no_memory": matrix_root / "methods" / "no_memory.json",
                "matrix_no_profile_probe": matrix_root
                / "methods"
                / "no_profile_probe.json",
                "matrix_no_replan": matrix_root / "methods" / "no_replan.json",
                "matrix_full_agent": matrix_root / "methods" / "full_agent.json",
                "matrix_memory_no_profile_probe": matrix_root
                / "memory"
                / "no_profile_probe.jsonl",
                "matrix_memory_no_replan": matrix_root
                / "memory"
                / "no_replan.jsonl",
                "matrix_memory_full_agent": matrix_root
                / "memory"
                / "full_agent.jsonl",
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
    if scaled_mode:
        paths.update(
            {
                "workload_generation": run / "workload_generation.json",
                "workload_manifest": run / "workload-bundle" / "manifest.json",
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
            "matrix_memory_no_profile_probe",
            "matrix_memory_no_replan",
            "matrix_memory_full_agent",
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

    scaled_bundle: M15WorkloadBundle | None = None
    if scaled_mode:
        try:
            scaled_bundle = load_m15_workload_bundle(run / "workload-bundle")
            check("workload_bundle.integrity", True, True)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            check("workload_bundle.integrity", True, f"invalid:{exc}")

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

    expected_run_version = {
        "vertical_slice": "m15-b2d-native-services-v1",
        "adaptive": "m15-d2-native-adaptive-services-v1",
        "scaled_adaptive": "m15-f0-native-scaled-adaptive-services-v1",
        "scaled_method_matrix": "m15-f1-native-live-method-matrix-services-v1",
        "scaled_campaign_session": (
            "m15-f2-native-live-campaign-session-services-v1"
        ),
        "scaled_query_bound_session": (
            "m15-f2b-native-live-query-bound-session-services-v1"
        ),
    }[workload_mode]
    check("environment.run_version", expected_run_version, environment.get("run_version"))
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check("environment.java_module", "Java/17.0.6", environment.get("java_module"))
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))
    if adaptive_mode:
        check(
            "environment.workload_mode",
            workload_mode,
            environment.get("workload_mode"),
        )
    if scaled_mode:
        profile = environment.get("workload_profile")
        check(
            "environment.workload_profile",
            True,
            profile in {"selective", "broad_hot"},
        )
        profile_config = {
            "selective": repo / "experiments/configs/m15_f0_selective.json",
            "broad_hot": repo / "experiments/configs/m15_f0_broad_hot.json",
        }.get(str(profile))
        try:
            expected_scaled_spec = (
                M15WorkloadSpec.from_json(profile_config)
                if profile_config is not None
                else None
            )
        except (OSError, ValueError, json.JSONDecodeError):
            expected_scaled_spec = None
        check(
            "workload_bundle.profile_spec",
            expected_scaled_spec.to_dict() if expected_scaled_spec else None,
            scaled_bundle.spec.to_dict() if scaled_bundle else None,
        )
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

    expected_service_schema = {
        "vertical_slice": SERVICE_RUN_SCHEMA_VERSION,
        "adaptive": ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_adaptive": SCALED_ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_method_matrix": METHOD_MATRIX_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_campaign_session": CAMPAIGN_SESSION_SERVICE_RUN_SCHEMA_VERSION,
        "scaled_query_bound_session": (
            QUERY_BOUND_SESSION_SERVICE_RUN_SCHEMA_VERSION
        ),
    }[workload_mode]
    check("service.schema", expected_service_schema, service_manifest.get("schema_version"))
    check("service.status", "success", service_manifest.get("status"))
    check("service.error", None, service_manifest.get("error"))
    check("service.automatic_retries", 0, service_manifest.get("automatic_retries"))
    check("service.restarts", 0, service_manifest.get("service_restarts"))
    check("service.public_ports", False, service_manifest.get("public_ports"))
    check("service.credentials", False, service_manifest.get("credentials_persisted"))
    if adaptive_mode:
        check("outer.workload_mode", workload_mode, outer.get("workload_mode"))
        check(
            "service.workload_mode",
            workload_mode,
            service_manifest.get("workload_mode"),
        )
    if scaled_mode:
        bundle_manifest = dict(scaled_bundle.manifest) if scaled_bundle else None
        check(
            "service.workload_bundle",
            bundle_manifest,
            service_manifest.get("workload_bundle"),
        )

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

    if scaled_mode:
        bundle_manifest = dict(scaled_bundle.manifest) if scaled_bundle else None
        generation = _dict(loaded.get("workload_generation"))
        check("workload_generation.status", "success", generation.get("status"))
        check(
            "workload_generation.root",
            str(scaled_bundle.root) if scaled_bundle else None,
            generation.get("root"),
        )
        check(
            "workload_generation.spec",
            scaled_bundle.spec.to_dict() if scaled_bundle else None,
            generation.get("spec"),
        )
        check(
            "workload_generation.manifest",
            bundle_manifest,
            generation.get("manifest"),
        )
        check("fixture.workload_bundle", bundle_manifest, fixture.get("workload_bundle"))
        scaled_dataset_id = (
            f"m15_f0:{scaled_bundle.spec.workload_id}" if scaled_bundle else None
        )
        check("fixture.dataset_id", scaled_dataset_id, fixture.get("dataset_id"))

    expected_result = (
        [dict(row) for row in scaled_bundle.expected_rows]
        if scaled_bundle is not None
        else json.loads(
            (
                repo
                / "examples"
                / "m15_split_financial_risk"
                / "expected_result.json"
            ).read_text(encoding="utf-8")
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
    elif method_matrix_mode:
        campaign = _dict(loaded.get("campaign"))
        campaign_status = _dict(loaded.get("campaign_status"))
        campaign_validation = _dict(loaded.get("campaign_validation"))
        campaign_plan = _dict(loaded.get("campaign_plan"))
        campaign_session_plan = _dict(loaded.get("campaign_session_plan"))
        campaign_binding = _dict(loaded.get("campaign_binding"))
        matrix_campaign_binding = _dict(loaded.get("matrix_campaign_binding"))
        query_bound = _dict(loaded.get("query_bound"))
        query_bound_status = _dict(loaded.get("query_bound_status"))
        query_bound_validation = _dict(loaded.get("query_bound_validation"))
        query_bound_plan = _dict(loaded.get("query_bound_plan"))
        query_bound_session_plan = _dict(
            loaded.get("query_bound_session_plan")
        )
        query_bound_binding = _dict(loaded.get("query_bound_binding"))
        query_bound_contract = _dict(loaded.get("query_bound_contract"))
        matrix = _dict(loaded.get("matrix"))
        matrix_status = _dict(loaded.get("matrix_status"))
        matrix_validation = _dict(loaded.get("matrix_validation"))
        calibration = _dict(loaded.get("matrix_calibration"))
        calibration_snapshot = _dict(loaded.get("matrix_calibration_snapshot"))
        observation_requests = _list(loaded.get("matrix_observation_requests"))
        invocations = _dict(loaded.get("matrix_invocations"))
        cost_model = _dict(loaded.get("matrix_cost_model"))
        memory_context = _dict(loaded.get("matrix_memory_context"))
        method_policies = _list(loaded.get("matrix_method_policies"))
        semantic_program = _dict(loaded.get("matrix_semantic_program"))
        candidate_plans = _dict(loaded.get("matrix_candidate_plans"))
        probe_plan = _dict(loaded.get("matrix_probe_plan"))

        workload_id = scaled_bundle.spec.workload_id if scaled_bundle else None
        dataset_id = f"m15_f0:{workload_id}" if workload_id else None
        expected_hashes = (
            {
                **{
                    f"bundle:{workload_id}/{name}": digest
                    for name, digest in scaled_bundle.source_hashes.items()
                },
                f"bundle:{workload_id}/manifest.json": _sha256_file(
                    scaled_bundle.root / "manifest.json"
                ),
            }
            if scaled_bundle is not None
            else {}
        )
        canonical_method_order = (
            M15Method.STATIC_PARALLEL_HASH,
            M15Method.STATIC_RISK_FIRST_BIND,
            M15Method.NO_MEMORY,
            M15Method.NO_PROFILE_PROBE,
            M15Method.NO_REPLAN,
            M15Method.FULL_AGENT,
        )
        method_order = canonical_method_order
        expected_campaign_plan: dict[str, Any] = {}
        expected_campaign_session: dict[str, Any] = {}
        expected_campaign_binding: dict[str, Any] = {}
        expected_query_contract: dict[str, Any] = {}
        if campaign_session_mode:
            try:
                expected_campaign_plan = compile_m15_campaign_file(
                    repo / "experiments/configs/m15_f2_campaign_dev.json",
                    repo_root=repo,
                ).to_dict()
                matches = [
                    dict(item)
                    for item in _list(expected_campaign_plan.get("sessions"))
                    if _dict(item).get("session_id") == campaign.get("session_id")
                ]
                expected_campaign_session = matches[0] if len(matches) == 1 else {}
                observed_order = _list(expected_campaign_session.get("method_order"))
                parsed_order = tuple(M15Method(str(item)) for item in observed_order)
                if (
                    len(parsed_order) != len(canonical_method_order)
                    or set(parsed_order) != set(canonical_method_order)
                ):
                    raise ValueError("campaign method order is not complete")
                method_order = parsed_order
                expected_streams = {
                    str(_dict(item).get("method")): _dict(item)
                    for item in _list(
                        expected_campaign_session.get("method_streams")
                    )
                }
                expected_campaign_binding = {
                    "schema_version": CAMPAIGN_BINDING_SCHEMA_VERSION,
                    "campaign_id": expected_campaign_plan["campaign_id"],
                    "campaign_spec_sha256": expected_campaign_plan[
                        "campaign_spec_sha256"
                    ],
                    "schedule_sha256": expected_campaign_plan["schedule_sha256"],
                    "session_id": expected_campaign_session["session_id"],
                    "workload_label": expected_campaign_session["workload_label"],
                    "workload_id": expected_campaign_session["workload_id"],
                    "block_index": expected_campaign_session["block_index"],
                    "sequence_index": expected_campaign_session["sequence_index"],
                    "query_ids": [CAMPAIGN_SUPPORTED_QUERY_ID],
                    "method_order": observed_order,
                    "method_task_ids": {
                        method.value: _list(
                            expected_streams[method.value].get("measured_run_ids")
                        )[0]
                        for method in method_order
                    },
                    "memory_namespaces": {
                        method.value: expected_streams[method.value].get(
                            "memory_namespace"
                        )
                        for method in method_order
                    },
                }
                campaign_plan_valid: object = True
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                campaign_plan_valid = f"invalid:{exc}"
            check("campaign.plan_recompiles", True, campaign_plan_valid)
            check(
                "campaign.plan_file",
                expected_campaign_plan,
                campaign_plan,
            )
            check(
                "campaign.session_file",
                expected_campaign_session,
                campaign_session_plan,
            )
            check(
                "campaign.binding_file",
                expected_campaign_binding,
                campaign_binding,
            )
            check(
                "campaign.matrix_binding_file",
                expected_campaign_binding,
                matrix_campaign_binding,
            )
            check(
                "campaign.schema",
                LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION,
                campaign.get("schema_version"),
            )
            check("campaign.status", "success", campaign.get("status"))
            check("campaign.error", None, campaign.get("error"))
            check("campaign.paper_result", False, campaign.get("paper_result"))
            check("campaign.automatic_retries", 0, campaign.get("automatic_retries"))
            check("campaign.llm_calls", 0, campaign.get("llm_calls"))
            check("campaign.ontology_calls", 0, campaign.get("ontology_calls"))
            check(
                "campaign.evidence_class",
                "development_campaign_session_engineering_gate",
                campaign.get("evidence_class"),
            )
            check(
                "campaign.validation",
                True,
                _validation_is_exact(campaign.get("validation")),
            )
            check(
                "campaign.validation_file",
                campaign_validation,
                campaign.get("validation"),
            )
            check(
                "campaign.spec_hash",
                expected_campaign_plan.get("campaign_spec_sha256"),
                campaign.get("campaign_spec_sha256"),
            )
            check(
                "campaign.schedule_hash",
                expected_campaign_plan.get("schedule_sha256"),
                campaign.get("schedule_sha256"),
            )
            check(
                "campaign.session_id",
                expected_campaign_session.get("session_id"),
                campaign.get("session_id"),
            )
            check(
                "campaign.method_order",
                expected_campaign_session.get("method_order"),
                campaign.get("method_order"),
            )
            check(
                "campaign.query_ids",
                [CAMPAIGN_SUPPORTED_QUERY_ID],
                campaign.get("query_ids"),
            )
            check(
                "campaign.workload_input",
                next(
                    (
                        dict(item)
                        for item in _list(
                            expected_campaign_plan.get("workload_inputs")
                        )
                        if _dict(item).get("label")
                        == expected_campaign_session.get("workload_label")
                    ),
                    None,
                ),
                campaign.get("workload_input"),
            )
            check(
                "campaign.workload_bundle",
                dict(scaled_bundle.manifest) if scaled_bundle else None,
                campaign.get("workload_bundle"),
            )
            check(
                "campaign.artifacts",
                {
                    "campaign_binding.json",
                    "campaign_plan.json",
                    "method-matrix-run",
                    "run_manifest.json",
                    "run_status.json",
                    "session_plan.json",
                    "validation.json",
                },
                set(_list(campaign.get("artifacts"))),
            )
            check(
                "campaign_status.schema",
                LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION,
                campaign_status.get("schema_version"),
            )
            check("campaign_status.status", "success", campaign_status.get("status"))
            check("campaign_status.error", None, campaign_status.get("error"))
            check(
                "campaign_status.run_id",
                campaign.get("run_id"),
                campaign_status.get("run_id"),
            )
            service_campaign = _dict(service_manifest.get("campaign_session"))
            check(
                "service.campaign_session_id",
                expected_campaign_session.get("session_id"),
                service_campaign.get("session_id"),
            )
            check(
                "service.campaign_spec_hash",
                expected_campaign_plan.get("campaign_spec_sha256"),
                service_campaign.get("expected_campaign_spec_sha256"),
            )
            check(
                "service.campaign_schedule_hash",
                expected_campaign_plan.get("schedule_sha256"),
                service_campaign.get("expected_schedule_sha256"),
            )
            config_value = service_campaign.get("campaign_config")
            check(
                "service.campaign_config",
                True,
                isinstance(config_value, str)
                and config_value.endswith(
                    "/experiments/configs/m15_f2_campaign_dev.json"
                ),
            )
        elif query_bound_session_mode:
            try:
                registry_path = (
                    repo
                    / "experiments/configs/m15_f2_query_bound_campaign_dev.json"
                )
                compiled_query_plan = compile_m15_query_bound_campaign_file(
                    registry_path,
                    repo_root=repo,
                ).to_dict()
                if scaled_bundle is None:
                    raise ValueError("verified workload bundle is unavailable")
                preparation = prepare_m15_live_query_bound_session(
                    query_bound_registry=registry_path,
                    session_id=str(query_bound.get("session_id")),
                    expected_registry_spec_sha256=compiled_query_plan[
                        "registry_spec_sha256"
                    ],
                    expected_query_bound_schedule_sha256=compiled_query_plan[
                        "query_bound_schedule_sha256"
                    ],
                    workload_bundle=scaled_bundle,
                    repo_root=repo,
                )
                expected_campaign_plan = dict(preparation.plan)
                expected_campaign_session = dict(preparation.session)
                expected_campaign_binding = dict(preparation.binding)
                expected_query_contract = preparation.query_contracts[
                    CAMPAIGN_SUPPORTED_QUERY_ID
                ].to_dict()
                observed_order = _list(
                    expected_campaign_session.get("method_order")
                )
                parsed_order = tuple(
                    M15Method(str(item)) for item in observed_order
                )
                if (
                    len(parsed_order) != len(canonical_method_order)
                    or set(parsed_order) != set(canonical_method_order)
                ):
                    raise ValueError("query-bound method order is not complete")
                method_order = parsed_order
                query_bound_plan_valid: object = True
            except (
                KeyError,
                OSError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                query_bound_plan_valid = f"invalid:{exc}"
            check("query_bound.plan_recompiles", True, query_bound_plan_valid)
            check(
                "query_bound.plan_file",
                expected_campaign_plan,
                query_bound_plan,
            )
            check(
                "query_bound.session_file",
                expected_campaign_session,
                query_bound_session_plan,
            )
            check(
                "query_bound.binding_file",
                expected_campaign_binding,
                query_bound_binding,
            )
            check(
                "query_bound.matrix_binding_file",
                expected_campaign_binding,
                matrix_campaign_binding,
            )
            check(
                "query_bound.contract_file",
                expected_query_contract,
                query_bound_contract,
            )
            check(
                "query_bound.schema",
                LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION,
                query_bound.get("schema_version"),
            )
            check("query_bound.status", "success", query_bound.get("status"))
            check("query_bound.error", None, query_bound.get("error"))
            check("query_bound.paper_result", False, query_bound.get("paper_result"))
            check(
                "query_bound.automatic_retries",
                0,
                query_bound.get("automatic_retries"),
            )
            check("query_bound.llm_calls", 0, query_bound.get("llm_calls"))
            check(
                "query_bound.ontology_calls",
                0,
                query_bound.get("ontology_calls"),
            )
            check(
                "query_bound.evidence_class",
                "development_live_query_bound_session_gate",
                query_bound.get("evidence_class"),
            )
            check(
                "query_bound.validation",
                True,
                _validation_is_exact(query_bound.get("validation")),
            )
            check(
                "query_bound.validation_file",
                query_bound_validation,
                query_bound.get("validation"),
            )
            check(
                "query_bound.registry_id",
                expected_campaign_plan.get("registry_id"),
                query_bound.get("registry_id"),
            )
            check(
                "query_bound.registry_spec_hash",
                expected_campaign_plan.get("registry_spec_sha256"),
                query_bound.get("registry_spec_sha256"),
            )
            check(
                "query_bound.query_binding_hash",
                expected_campaign_plan.get("query_binding_sha256"),
                query_bound.get("query_binding_sha256"),
            )
            check(
                "query_bound.schedule_hash",
                expected_campaign_plan.get("query_bound_schedule_sha256"),
                query_bound.get("query_bound_schedule_sha256"),
            )
            check(
                "query_bound.session_id",
                expected_campaign_session.get("session_id"),
                query_bound.get("session_id"),
            )
            check(
                "query_bound.method_order",
                expected_campaign_session.get("method_order"),
                query_bound.get("method_order"),
            )
            check(
                "query_bound.workload_bundle",
                dict(scaled_bundle.manifest) if scaled_bundle else None,
                query_bound.get("workload_bundle"),
            )
            check(
                "query_bound.contract_identity",
                {
                    CAMPAIGN_SUPPORTED_QUERY_ID: {
                        "query_contract_sha256": expected_query_contract.get(
                            "query_contract_sha256"
                        ),
                        "artifact": (
                            "query_contracts/"
                            f"{CAMPAIGN_SUPPORTED_QUERY_ID}.json"
                        ),
                    }
                },
                query_bound.get("query_contracts"),
            )
            check(
                "query_bound.artifacts",
                {
                    "campaign_binding.json",
                    "method-matrix-run",
                    "query_bound_campaign_plan.json",
                    "query_contracts",
                    "run_manifest.json",
                    "run_status.json",
                    "session_plan.json",
                    "validation.json",
                },
                set(_list(query_bound.get("artifacts"))),
            )
            check(
                "query_bound_status.schema",
                LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION,
                query_bound_status.get("schema_version"),
            )
            check(
                "query_bound_status.status",
                "success",
                query_bound_status.get("status"),
            )
            check(
                "query_bound_status.error",
                None,
                query_bound_status.get("error"),
            )
            check(
                "query_bound_status.run_id",
                query_bound.get("run_id"),
                query_bound_status.get("run_id"),
            )
            service_query_bound = _dict(
                service_manifest.get("query_bound_session")
            )
            check(
                "service.query_bound_session_id",
                expected_campaign_session.get("session_id"),
                service_query_bound.get("session_id"),
            )
            check(
                "service.query_bound_registry_hash",
                expected_campaign_plan.get("registry_spec_sha256"),
                service_query_bound.get("expected_registry_spec_sha256"),
            )
            check(
                "service.query_bound_schedule_hash",
                expected_campaign_plan.get("query_bound_schedule_sha256"),
                service_query_bound.get(
                    "expected_query_bound_schedule_sha256"
                ),
            )
            registry_value = service_query_bound.get("query_bound_registry")
            check(
                "service.query_bound_registry",
                True,
                isinstance(registry_value, str)
                and registry_value.endswith(
                    "/experiments/configs/m15_f2_query_bound_campaign_dev.json"
                ),
            )
        result_keys = {
            M15Method.STATIC_PARALLEL_HASH: "matrix_static_parallel",
            M15Method.STATIC_RISK_FIRST_BIND: "matrix_static_bind",
            M15Method.NO_MEMORY: "matrix_no_memory",
            M15Method.NO_PROFILE_PROBE: "matrix_no_profile_probe",
            M15Method.NO_REPLAN: "matrix_no_replan",
            M15Method.FULL_AGENT: "matrix_full_agent",
        }
        results = {
            method: _dict(loaded.get(result_keys[method])) for method in method_order
        }

        check("matrix.schema", LIVE_MATRIX_SCHEMA_VERSION, matrix.get("schema_version"))
        check("matrix.status", "success", matrix.get("status"))
        check("matrix.error", None, matrix.get("error"))
        check("matrix.dataset_id", dataset_id, matrix.get("dataset_id"))
        check(
            "matrix.workload_bundle",
            dict(scaled_bundle.manifest) if scaled_bundle else None,
            matrix.get("workload_bundle"),
        )
        check("matrix.input_sha256", expected_hashes, matrix.get("input_sha256"))
        check("fixture.input_sha256", expected_hashes, fixture.get("input_sha256"))
        check("matrix.git_commit", expected_commit, _dict(matrix.get("git")).get("commit"))
        check("matrix.git_clean", True, _dict(matrix.get("git")).get("clean"))
        check("matrix.backend_health", True, _backend_health_is_exact(matrix.get("backend_health")))
        check("matrix.no_llm", True, matrix.get("no_llm"))
        check("matrix.no_ontology", True, matrix.get("no_ontology"))
        check("matrix.automatic_retries", 0, matrix.get("automatic_retries"))
        check("matrix.paper_result", False, matrix.get("paper_result"))
        check(
            "matrix.evidence_class",
            (
                "live_backend_query_bound_session_engineering_gate"
                if query_bound_session_mode
                else (
                    "live_backend_campaign_session_engineering_gate"
                    if campaign_session_mode
                    else "live_backend_method_mechanism_engineering_gate"
                )
            ),
            matrix.get("evidence_class"),
        )
        check(
            "matrix.order_policy",
            (
                "williams_campaign_sequence"
                if bound_session_mode
                else "fixed_engineering_gate_not_counterbalanced"
            ),
            matrix.get("order_policy"),
        )
        check(
            "matrix.cache_state",
            (
                "shared_unflushed_within_sequence_counterbalanced_by_campaign"
                if bound_session_mode
                else "shared_unknown_not_reset_between_methods"
            ),
            matrix.get("cache_state"),
        )
        check(
            "matrix.method_order",
            [method.value for method in method_order],
            matrix.get("method_order"),
        )
        check("matrix.validation", True, _validation_is_exact(matrix.get("validation")))
        check(
            "matrix.validation_matches_file",
            matrix_validation,
            matrix.get("validation"),
        )
        check("matrix_status.schema", LIVE_MATRIX_SCHEMA_VERSION, matrix_status.get("schema_version"))
        check("matrix_status.status", "success", matrix_status.get("status"))
        check("matrix_status.error", None, matrix_status.get("error"))
        check("matrix_status.run_id", matrix.get("run_id"), matrix_status.get("run_id"))
        expected_artifacts = {
            "backend_invocations.json",
            "calibration.json",
            "calibration_snapshot.json",
            "candidate_plans.json",
            "cost_model.json",
            "health.json",
            "memory",
            "memory_context.json",
            "method_policies.json",
            "methods",
            "observation_requests.json",
            "probe_plan.json",
            "run_manifest.json",
            "run_status.json",
            "semantic_program.json",
            "validation.json",
        }
        if bound_session_mode:
            expected_artifacts.add("campaign_binding.json")
        check("matrix.artifacts", expected_artifacts, set(_list(matrix.get("artifacts"))))
        check(
            "matrix.campaign_binding",
            expected_campaign_binding if bound_session_mode else None,
            matrix.get("campaign_binding"),
        )
        execution_namespaces = _dict(matrix.get("execution_namespaces"))
        expected_task_ids = (
            _dict(expected_campaign_binding.get("method_task_ids"))
            if bound_session_mode
            else {
                method.value: f"{matrix.get('run_id')}.{method.value}"
                for method in method_order
            }
        )
        expected_memory_namespaces = (
            _dict(expected_campaign_binding.get("memory_namespaces"))
            if bound_session_mode
            else expected_task_ids
        )
        check(
            "matrix.execution_task_ids",
            expected_task_ids,
            execution_namespaces.get("task_ids"),
        )
        check(
            "matrix.execution_memory_namespaces",
            expected_memory_namespaces,
            execution_namespaces.get("logical_memory_namespaces"),
        )
        check(
            "matrix.execution_memory_storage_scope",
            "method_file_within_unique_run_root",
            execution_namespaces.get("memory_storage_scope"),
        )

        check("matrix.cost_model.schema", LIVE_MATRIX_COST_MODEL_VERSION, cost_model.get("schema_version"))
        check("matrix.cost_model.calibrated", False, cost_model.get("calibrated"))
        check("matrix.cost_model.paper_result", False, cost_model.get("paper_result"))
        check("matrix.cost_model.bandwidth", 1000.0, cost_model.get("bandwidth_bytes_per_ms"))
        check("matrix.cost_model.exchange_fixed", 0.5, cost_model.get("exchange_fixed_ms"))
        check("matrix.cost_model.coordinator_row", 0.001, cost_model.get("coordinator_row_ms"))
        check("matrix.cost_model_matches_manifest", cost_model, matrix.get("cost_model"))

        observation_prefix = f"m15-f0:{workload_id}"
        expected_requests = [
            (
                "profile-neo4j-full",
                f"{observation_prefix}:neo4j-full",
                "neo4j",
                "profile",
                {"query_id": "recent-transfers-full"},
            ),
            (
                "profile-neo4j-bound",
                f"{observation_prefix}:neo4j-bound",
                "neo4j",
                "profile",
                {"query_id": "recent-transfers-bound"},
            ),
            (
                "profile-fuseki-risk",
                f"{observation_prefix}:fuseki-risk",
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
        check("matrix.requests", expected_requests, observed_requests)
        check("matrix.calibration.success", True, calibration.get("success"))
        check("matrix.calibration.error", None, calibration.get("error"))
        check("matrix.calibration.calls", 3, calibration.get("attempted_calls"))
        check("matrix.calibration.automatic_retries", 0, calibration.get("automatic_retries"))
        check("matrix.calibration.requests", observation_requests, calibration.get("requests"))
        check("matrix.calibration.snapshot_file", calibration_snapshot, calibration.get("snapshot"))
        check("matrix.calibration.manifest", calibration, matrix.get("calibration"))
        calibration_results = _list(calibration.get("tool_results"))
        check(
            "matrix.calibration.all_success",
            True,
            len(calibration_results) == 3
            and all(_dict(item).get("status") == "success" for item in calibration_results),
        )
        accounting = _dict(matrix.get("calibration_accounting"))
        check("matrix.calibration.excluded", False, accounting.get("included_in_method_metrics"))
        check("matrix.calibration.seed_writes", 3, accounting.get("seed_memory_writes"))

        expected_semantic_key = (
            f"m15-f0:{workload_id}:exact:{scaled_bundle.manifest['spec_sha256']}"
            if scaled_bundle is not None
            else None
        )
        valid_plan_ids = {
            f"m15-f0-{workload_id}-parallel-hash",
            f"m15-f0-{workload_id}-risk-first-bind",
        }
        check("matrix.semantic_program.id", f"m15-f0-{workload_id}-exact", semantic_program.get("program_id"))
        check("matrix.candidates.semantic_key", expected_semantic_key, candidate_plans.get("semantic_equivalence_key"))
        check(
            "matrix.candidates.plan_ids",
            valid_plan_ids,
            {
                _dict(item).get("plan_id")
                for item in _list(candidate_plans.get("plans"))
            },
        )
        check("matrix.probe.remote_budget", 1, probe_plan.get("max_remote_calls"))
        check(
            "matrix.probe.nodes",
            ["high-risk", "align-risk", "exchange-risk"],
            [_dict(item).get("node_id") for item in _list(probe_plan.get("nodes"))],
        )
        check("matrix.memory_context_manifest", memory_context, matrix.get("memory_context"))
        check("matrix.memory_context.semantic_key", expected_semantic_key, memory_context.get("semantic_equivalence_key"))
        context_fingerprint = memory_context.get("fingerprint")
        check(
            "matrix.memory_context.fingerprint",
            True,
            isinstance(context_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", context_fingerprint) is not None,
        )
        check(
            "matrix.method_policies",
            [M15_METHOD_POLICIES[method].to_dict() for method in method_order],
            method_policies,
        )

        manifest_results = _dict(matrix.get("methods"))
        check("matrix.method_set", {method.value for method in method_order}, set(manifest_results))
        expected_calls = {
            M15Method.STATIC_PARALLEL_HASH: 2,
            M15Method.STATIC_RISK_FIRST_BIND: 2,
            M15Method.NO_MEMORY: 5,
            M15Method.NO_PROFILE_PROBE: 2,
            M15Method.NO_REPLAN: 2,
            M15Method.FULL_AGENT: 2,
        }
        expected_profiles = {method: 0 for method in method_order}
        expected_profiles[M15Method.NO_MEMORY] = 3
        expected_probes = {method: 0 for method in method_order}
        expected_probes[M15Method.NO_REPLAN] = 1
        expected_probes[M15Method.FULL_AGENT] = 1
        for method in method_order:
            result = results[method]
            prefix = f"matrix.method.{method.value}"
            check(f"{prefix}.matches_manifest", result, manifest_results.get(method.value))
            check(f"{prefix}.schema", METHOD_POLICY_SCHEMA_VERSION, result.get("schema_version"))
            check(f"{prefix}.policy", M15_METHOD_POLICIES[method].to_dict(), result.get("policy"))
            check(
                f"{prefix}.task_id",
                expected_task_ids.get(method.value),
                result.get("task_id"),
            )
            check(f"{prefix}.success", True, result.get("success"))
            check(f"{prefix}.error", None, result.get("error"))
            check(f"{prefix}.exact_answer", True, result.get("exact_answer"))
            check(f"{prefix}.rows", expected_result, result.get("final_rows"))
            check(f"{prefix}.context", context_fingerprint, result.get("context_fingerprint"))
            check(f"{prefix}.total_calls", expected_calls[method], result.get("total_backend_calls"))
            check(f"{prefix}.profile_calls", expected_profiles[method], result.get("planning_profile_calls"))
            check(f"{prefix}.probe_calls", expected_probes[method], result.get("probe_remote_calls"))
            check(f"{prefix}.query_calls", 2, result.get("query_remote_calls"))
            check(f"{prefix}.automatic_retries", 0, result.get("automatic_retries"))
            check(f"{prefix}.llm_calls", 0, result.get("llm_calls"))
            check(f"{prefix}.ontology_calls", 0, result.get("ontology_calls"))
            check(f"{prefix}.paper_result", False, result.get("paper_result"))
            check(f"{prefix}.plan_valid", True, result.get("executed_plan_id") in valid_plan_ids)
        check(
            "matrix.method.static_parallel.plan",
            f"m15-f0-{workload_id}-parallel-hash",
            results[M15Method.STATIC_PARALLEL_HASH].get("executed_plan_id"),
        )
        check(
            "matrix.method.static_bind.plan",
            f"m15-f0-{workload_id}-risk-first-bind",
            results[M15Method.STATIC_RISK_FIRST_BIND].get("executed_plan_id"),
        )
        no_replan = results[M15Method.NO_REPLAN]
        check("matrix.method.no_replan.count", 0, no_replan.get("replan_count"))
        check("matrix.method.no_replan.plan_stable", no_replan.get("initial_plan_id"), no_replan.get("executed_plan_id"))
        full_agent = results[M15Method.FULL_AGENT]
        check(
            "matrix.method.full_agent.replan_bounded",
            True,
            isinstance(full_agent.get("replan_count"), int)
            and not isinstance(full_agent.get("replan_count"), bool)
            and full_agent.get("replan_count") in {0, 1},
        )

        phases = _dict(invocations.get("events_by_phase"))
        expected_phases = {"calibration", *(method.value for method in method_order)}
        check("matrix.invocations.phases", expected_phases, set(phases))
        check("matrix.invocations.total", 18, invocations.get("total_tool_invocations"))
        check("matrix.invocations.automatic_retries", 0, invocations.get("automatic_retries"))
        all_events = [
            _dict(event)
            for phase in expected_phases
            for event in _list(phases.get(phase))
        ]
        check(
            "matrix.invocations.all_success",
            True,
            len(all_events) == 18
            and all(event.get("status") == "success" for event in all_events),
        )
        calibration_events = [_dict(item) for item in _list(phases.get("calibration"))]
        check(
            "matrix.invocations.calibration_sequence",
            ["profile", "profile", "profile"],
            [event.get("operation") for event in calibration_events],
        )
        check(
            "matrix.invocations.calibration_modes",
            ["backend_native", "backend_native", "wall_clock_execute"],
            [event.get("observation_mode") for event in calibration_events],
        )
        for method in method_order:
            phase_events = [_dict(item) for item in _list(phases.get(method.value))]
            result = results[method]
            check(
                f"matrix.invocations.{method.value}.count",
                result.get("total_backend_calls"),
                len(phase_events),
            )
            check(
                f"matrix.invocations.{method.value}.profiles",
                result.get("planning_profile_calls"),
                sum(event.get("operation") == "profile" for event in phase_events),
            )
            check(
                f"matrix.invocations.{method.value}.executes",
                result.get("query_remote_calls"),
                sum(event.get("operation") == "execute" for event in phase_events),
            )

        memory_paths = {
            M15Method.NO_PROFILE_PROBE: "matrix_memory_no_profile_probe",
            M15Method.NO_REPLAN: "matrix_memory_no_replan",
            M15Method.FULL_AGENT: "matrix_memory_full_agent",
        }
        expected_memory_counts = {
            M15Method.NO_PROFILE_PROBE: 1,
            M15Method.NO_REPLAN: 2,
            M15Method.FULL_AGENT: 2,
        }
        for method, key in memory_paths.items():
            memory_records: list[Any] = []
            memory_text = loaded.get(key)
            if isinstance(memory_text, str):
                try:
                    memory_records = [
                        json.loads(line) for line in memory_text.splitlines() if line
                    ]
                except json.JSONDecodeError:
                    memory_records = []
            check(
                f"matrix.memory.{method.value}.count",
                expected_memory_counts[method],
                len(memory_records),
            )
            check(
                f"matrix.memory.{method.value}.snapshot_identity",
                True,
                bool(memory_records)
                and all(
                    _dict(_dict(item).get("value")).get("snapshot_id")
                    == memory_context.get("snapshot_id")
                    for item in memory_records
                ),
            )
            check(
                f"matrix.memory.{method.value}.seed_version",
                f"calibration-{matrix.get('run_id')}",
                _dict(memory_records[0]).get("version") if memory_records else None,
            )
            check(
                f"matrix.memory.{method.value}.seed_snapshot",
                calibration_snapshot,
                _dict(_dict(memory_records[0]).get("value"))
                if memory_records
                else None,
            )
            check(
                f"matrix.memory.{method.value}.keys",
                True,
                bool(memory_records)
                and all(
                    _dict(item).get("key")
                    == (
                        "federated-plan-snapshot/"
                        f"{memory_context.get('snapshot_id')}/"
                        f"{_dict(item).get('version')}"
                    )
                    for item in memory_records
                ),
            )
            expected_last_snapshot = (
                results[method].get("snapshot_after")
                if results[method].get("memory_writes")
                else results[method].get("snapshot_before")
            )
            check(
                f"matrix.memory.{method.value}.last_snapshot",
                expected_last_snapshot,
                _dict(_dict(memory_records[-1]).get("value"))
                if memory_records
                else None,
            )
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
        if scaled_mode:
            scaled_dataset_id = (
                f"m15_f0:{scaled_bundle.spec.workload_id}" if scaled_bundle else None
            )
            check("adaptive.dataset_id", scaled_dataset_id, adaptive.get("dataset_id"))
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
        scaled_workload_id = (
            scaled_bundle.spec.workload_id if scaled_bundle is not None else None
        )
        expected_evidence_class = (
            "deterministic_scaled_live_backend_development_gate"
            if scaled_mode
            else "live_backend_development_gate"
        )
        check(
            "adaptive.evidence_class",
            expected_evidence_class,
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
        if scaled_bundle is not None:
            expected_hashes = {
                f"bundle:{scaled_workload_id}/{name}": digest
                for name, digest in scaled_bundle.source_hashes.items()
            }
            expected_hashes[
                f"bundle:{scaled_workload_id}/manifest.json"
            ] = _sha256_file(scaled_bundle.root / "manifest.json")
            check(
                "adaptive.workload_bundle",
                dict(scaled_bundle.manifest),
                adaptive.get("workload_bundle"),
            )
            check("fixture.input_sha256", expected_hashes, fixture.get("input_sha256"))
        else:
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
        valid_plan_ids = (
            {
                f"m15-f0-{scaled_workload_id}-parallel-hash",
                f"m15-f0-{scaled_workload_id}-risk-first-bind",
            }
            if scaled_mode
            else {"m15-parallel-hash", "m15-risk-first-bind"}
        )
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
        observation_prefix = f"m15-f0:{scaled_workload_id}" if scaled_mode else None
        expected_requests = [
            (
                "profile-neo4j-full",
                (
                    f"{observation_prefix}:neo4j-full"
                    if scaled_mode
                    else "neo4j-recent-transfers-full"
                ),
                "neo4j",
                "profile",
                {"query_id": "recent-transfers-full"},
            ),
            (
                "profile-neo4j-bound",
                (
                    f"{observation_prefix}:neo4j-bound"
                    if scaled_mode
                    else "neo4j-recent-transfers-bound"
                ),
                "neo4j",
                "profile",
                {"query_id": "recent-transfers-bound"},
            ),
            (
                "profile-fuseki-risk",
                (
                    f"{observation_prefix}:fuseki-risk"
                    if scaled_mode
                    else "fuseki-high-risk"
                ),
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
        expected_profile_artifacts = (
            [
                f"m15-f0-{scaled_workload_id}-neo4j-full",
                f"m15-f0-{scaled_workload_id}-neo4j-bound",
                f"m15-f0-{scaled_workload_id}-fuseki-risk",
            ]
            if scaled_mode
            else [
                "m15-split-neo4j",
                "m15-split-neo4j-bound",
                "m15-split-fuseki",
            ]
        )
        check(
            "invocations.profile_artifacts",
            expected_profile_artifacts,
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
            [
                (
                    f"m15-f0-{scaled_workload_id}-fuseki-risk"
                    if scaled_mode
                    else "m15-split-fuseki"
                )
            ],
            fuseki_execute_artifacts,
        )
        check(
            "invocations.neo4j_execute_artifact",
            True,
            len(neo4j_execute_artifacts) == 1
            and neo4j_execute_artifacts[0]
            in (
                {
                    f"m15-f0-{scaled_workload_id}-neo4j-full",
                    f"m15-f0-{scaled_workload_id}-neo4j-bound",
                }
                if scaled_mode
                else {"m15-split-neo4j", "m15-split-neo4j-bound"}
            ),
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
        expected_observation_keys = (
            {
                f"{observation_prefix}:neo4j-full",
                f"{observation_prefix}:neo4j-bound",
                f"{observation_prefix}:fuseki-risk",
            }
            if scaled_mode
            else {
                "neo4j-recent-transfers-full",
                "neo4j-recent-transfers-bound",
                "fuseki-high-risk",
            }
        )
        check(
            "snapshot.before_observation_keys",
            expected_observation_keys,
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
        expected_program_id = (
            f"m15-f0-{scaled_workload_id}-exact"
            if scaled_mode
            else "m15-split-financial-risk-exact"
        )
        check(
            "semantic_program.id",
            expected_program_id,
            semantic_program.get("program_id"),
        )
        expected_semantic_key = (
            f"m15-f0:{scaled_workload_id}:exact:{scaled_bundle.manifest['spec_sha256']}"
            if scaled_bundle is not None
            else "m15:recent-alice-transfers-to-high-risk-company:exact:v1"
        )
        check(
            "candidate_plans.semantic_equivalence",
            expected_semantic_key,
            candidate_plans.get("semantic_equivalence_key"),
        )
        candidate_ids = {
            _dict(item).get("plan_id") for item in _list(candidate_plans.get("plans"))
        }
        check(
            "candidate_plans.ids",
            valid_plan_ids,
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
