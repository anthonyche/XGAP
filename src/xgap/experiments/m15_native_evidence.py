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
from xgap.experiments.m15_live_federated import RUN_SCHEMA_VERSION as LIVE_SCHEMA
from xgap.experiments.m15_native_artifacts import (
    DEFAULT_LOCK_PATH,
    NativeRuntimeLock,
    load_native_runtime_lock,
    parse_java_major,
)
from xgap.experiments.m15_native_runtime import STAGING_SCHEMA_VERSION
from xgap.experiments.m15_native_services import (
    LOCAL_FILESYSTEM_TYPES,
    SERVICE_PLAN_SCHEMA_VERSION,
    SERVICE_RUN_SCHEMA_VERSION,
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
) -> NativeEvidenceAudit:
    """Audit cross-artifact invariants without changing the completed run tree."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
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

    paths = {
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
        "live": run / "native-service-run" / "federated-run" / "run_manifest.json",
        "result": run / "native-service-run" / "federated-run" / "result.json",
        "neo4j_log": run / "native-service-run" / "service_logs" / "neo4j.log",
        "fuseki_log": run / "native-service-run" / "service_logs" / "fuseki.log",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        elif key in {"runtime_mount", "java_version", "neo4j_config"}:
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
    live = _dict(loaded.get("live"))
    result = _dict(loaded.get("result"))
    health = _list(loaded.get("health"))
    shutdown = _list(loaded.get("shutdown"))

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))

    check("environment.run_version", "m15-b2d-native-services-v1", environment.get("run_version"))
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check("environment.java_module", "Java/17.0.6", environment.get("java_module"))
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))
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

    check("service.schema", SERVICE_RUN_SCHEMA_VERSION, service_manifest.get("schema_version"))
    check("service.status", "success", service_manifest.get("status"))
    check("service.error", None, service_manifest.get("error"))
    check("service.automatic_retries", 0, service_manifest.get("automatic_retries"))
    check("service.restarts", 0, service_manifest.get("service_restarts"))
    check("service.public_ports", False, service_manifest.get("public_ports"))
    check("service.credentials", False, service_manifest.get("credentials_persisted"))

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

    check("live.schema", LIVE_SCHEMA, live.get("schema_version"))
    check("live.status", "success", live.get("status"))
    check("live.validation", True, _validation_is_exact(live.get("validation")))
    check("live.backend_health", True, _backend_health_is_exact(live.get("backend_health")))
    check("live.no_llm", True, live.get("no_llm"))
    check("live.no_ontology", True, live.get("no_ontology"))
    check("live.automatic_retries", 0, live.get("automatic_retries"))
    check("live.git_commit", expected_commit, _dict(live.get("git")).get("commit"))
    check("live.git_clean", True, _dict(live.get("git")).get("clean"))

    expected_result = json.loads(
        (repo / "examples" / "m15_split_financial_risk" / "expected_result.json").read_text(
            encoding="utf-8"
        )
    )
    check("result.success", True, result.get("success"))
    check("result.exact_rows", expected_result, result.get("final_rows"))
    check("result.remote_calls", 2, result.get("total_remote_calls"))
    moved = result.get("total_bytes_moved")
    check("result.positive_bytes", True, isinstance(moved, int) and moved > 0)

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
    args = parser.parse_args(argv)
    try:
        audit = audit_m15_native_run(
            run_root=args.run_root,
            expected_commit=args.expected_commit,
            repo_root=args.repo_root,
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
