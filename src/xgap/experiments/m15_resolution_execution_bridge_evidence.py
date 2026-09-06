"""Independent read-only audit for one native M15-E4B bridge execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_workload import (
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_executable_family_registry import (
    compile_m15_executable_family_registry_file,
)
from xgap.experiments.m15_live_resolution_execution_bridge import (
    LIVE_RESOLUTION_EXECUTION_BRIDGE_SCHEMA_VERSION,
    RESOLUTION_EXECUTION_BRIDGE_PREFLIGHT_SCHEMA_VERSION,
)
from xgap.experiments.m15_native_services import (
    RESOLUTION_EXECUTION_BRIDGE_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_fixture import (
    PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    load_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    compile_m15_resolution_execution_bridge_files,
)


RESOLUTION_EXECUTION_BRIDGE_AUDIT_SCHEMA_VERSION = (
    "m15-e4b-native-resolution-execution-bridge-evidence-audit-v1"
)
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
class ResolutionExecutionBridgeEvidenceCheck:
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
class M15ResolutionExecutionBridgeEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[ResolutionExecutionBridgeEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESOLUTION_EXECUTION_BRIDGE_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
            "paper_result": False,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            path.stat().st_size,
            _sha256_file(path),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _read_json(path: Path) -> tuple[dict[str, Any] | list[Any] | None, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"
    if not isinstance(value, (dict, list)):
        return None, "json_root_is_not_object_or_array"
    return value, "ok"


def _read_environment(path: Path) -> tuple[dict[str, str] | None, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                return None, f"invalid_line:{line}"
            key, value = line.split("=", 1)
            if not key or key in values:
                return None, f"duplicate_or_empty_key:{key}"
            values[key] = value
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"invalid_text:{exc}"
    return values, "ok"


def _dict(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _exact_validation(value: object) -> bool:
    validation = _dict(value)
    checks = validation.get("checks")
    return (
        validation.get("passed") is True
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(item is True for item in checks.values())
    )


def _nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
    )


def audit_m15_resolution_execution_bridge_run(
    *,
    run_root: str | Path,
    expected_commit: str,
    repo_root: str | Path | None = None,
) -> M15ResolutionExecutionBridgeEvidenceAudit:
    """Reconstruct and audit E4B without writing below ``run_root``."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    run = selected.resolve()
    if not run.is_dir():
        raise ValueError("run_root must be a real directory")
    repo = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )
    before = _tree_snapshot(run)

    service_root = run / "native-service-run"
    preflight_root = service_root / "resolution-execution-bridge-preflight"
    fixture_root = service_root / "resolution-execution-fixture-load"
    live_root = service_root / "resolution-execution-bridge-run"
    resolution_path = run / "resolution_run.json"
    bridge_spec_path = run / "resolution_bridge_spec.json"
    paths = {
        "outer_status": run / "run_status.json",
        "environment": run / "environment.txt",
        "resolution_run": resolution_path,
        "bridge_spec": bridge_spec_path,
        "service_status": service_root / "run_status.json",
        "service_manifest": service_root / "run_manifest.json",
        "service_plan": service_root / "service_plan.json",
        "service_health": service_root / "service_health.json",
        "service_shutdown": service_root / "service_shutdown.json",
        "preflight_manifest": preflight_root / "preflight_manifest.json",
        "preflight_bridge": preflight_root / "bridge_plan.json",
        "fixture_status": fixture_root / "run_status.json",
        "fixture_manifest": fixture_root / "run_manifest.json",
        "fixture_loads": fixture_root / "load_reports.json",
        "fixture_verification": fixture_root / "verification.json",
        "live_status": live_root / "run_status.json",
        "live_manifest": live_root / "run_manifest.json",
        "live_bridge": live_root / "bridge_plan.json",
        "live_health": live_root / "health.json",
        "live_results": live_root / "execution_results.json",
        "live_validation": live_root / "validation.json",
        "live_invocations": live_root / "backend_invocations.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        else:
            loaded[key], states[key] = _read_json(path)

    checks: list[ResolutionExecutionBridgeEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            ResolutionExecutionBridgeEvidenceCheck(
                check_id=check_id,
                passed=observed == expected,
                expected=expected,
                observed=observed,
            )
        )

    for key in paths:
        check(f"artifact.{key}", "ok", states[key])

    bridge = None
    base = None
    workload = None
    instances: dict[str, Mapping[str, Any]] = {}
    try:
        bridge = compile_m15_resolution_execution_bridge_files(
            resolution_run_path=resolution_path,
            bridge_spec_path=bridge_spec_path,
            repo_root=repo,
        )
        bridge_payload = bridge.to_dict()
        source_artifacts = bridge_payload["source_artifacts"]
        base = load_m15_parameterized_workload_bundle(preflight_root / "workload/base")
        # The registry package names the actual catalog and predicate mapping;
        # reload through the same package rather than trusting run metadata.
        registry = compile_m15_executable_family_registry_file(
            repo / source_artifacts["executable_family_registry"]["path"],
            repo_root=repo,
        ).to_dict()
        family_id = bridge_payload["executable_family"]["family_id"]
        family = next(
            item for item in registry["families"] if item["family_id"] == family_id
        )
        bindings = family["source_bindings"]
        workload = load_m15_direct_semantic_workload_bundle(
            preflight_root / "workload/direct",
            base_bundle=base,
            catalog=repo / bindings["semantic_catalog"]["path"],
            mapping=repo / bindings["predicate_mapping"]["path"],
        )
        instances = {
            str(item["query_id"]): load_m15_parameterized_instance(
                workload.workload_bundle,
                str(item["query_id"]),
            )
            for item in bridge_payload["physical_candidates"]
        }
        check("reconstruction.integrity", True, True)
    except (OSError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        check("reconstruction.integrity", True, f"invalid:{exc}")

    outer = _dict(loaded.get("outer_status"))
    environment = _dict(loaded.get("environment"))
    service_status = _dict(loaded.get("service_status"))
    service = _dict(loaded.get("service_manifest"))
    service_plan = _dict(loaded.get("service_plan"))
    service_health = _list(loaded.get("service_health"))
    service_shutdown = _list(loaded.get("service_shutdown"))
    preflight = _dict(loaded.get("preflight_manifest"))
    preflight_bridge = _dict(loaded.get("preflight_bridge"))
    fixture_status = _dict(loaded.get("fixture_status"))
    fixture = _dict(loaded.get("fixture_manifest"))
    fixture_loads = _dict(loaded.get("fixture_loads"))
    fixture_verification = _dict(loaded.get("fixture_verification"))
    live_status = _dict(loaded.get("live_status"))
    live = _dict(loaded.get("live_manifest"))
    live_bridge = _dict(loaded.get("live_bridge"))
    live_health = _dict(loaded.get("live_health"))
    results = _list(_dict(loaded.get("live_results")).get("results"))
    validation = _dict(loaded.get("live_validation"))
    invocations = _dict(loaded.get("live_invocations"))
    bridge_payload = bridge.to_dict() if bridge is not None else {}

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check(
        "outer.workload_mode",
        "resolution_execution_bridge",
        outer.get("workload_mode"),
    )
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))
    check(
        "environment.run_version",
        "m15-e4b-native-live-resolution-execution-bridge-services-v1",
        environment.get("run_version"),
    )
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check(
        "environment.workload_mode",
        "resolution_execution_bridge",
        environment.get("workload_mode"),
    )
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))

    check(
        "service.schema",
        RESOLUTION_EXECUTION_BRIDGE_SERVICE_RUN_SCHEMA_VERSION,
        service.get("schema_version"),
    )
    check("service_status.status", "success", service_status.get("status"))
    check("service.status", "success", service.get("status"))
    check("service.error", None, service.get("error"))
    check(
        "service.workload_mode",
        "resolution_execution_bridge",
        service.get("workload_mode"),
    )
    check("service.automatic_retries", 0, service.get("automatic_retries"))
    check("service.restarts", 0, service.get("service_restarts"))
    check("service.public_ports", False, service.get("public_ports"))
    check("service.credentials", False, service.get("credentials_persisted"))
    check(
        "service.health",
        True,
        len(service_health) == 2
        and [str(_dict(item).get("service_id")) for item in service_health]
        == ["neo4j", "fuseki"]
        and all(_dict(item).get("success") is True for item in service_health),
    )
    check(
        "service.shutdown",
        True,
        len(service_shutdown) == 2
        and [str(_dict(item).get("service_id")) for item in service_shutdown]
        == ["fuseki", "neo4j"]
        and all(_dict(item).get("success") is True for item in service_shutdown),
    )
    check("service.plan.loopback_only", True, service_plan.get("loopback_only"))
    check(
        "service.bridge_inputs",
        {
            "resolution_run": str(resolution_path),
            "bridge_spec": str(bridge_spec_path),
        },
        service.get("resolution_execution_bridge"),
    )

    expected_counts = {
        "raw_interpretations": 6,
        "semantic_equivalence_classes": 6,
        "executable_semantic_classes": 2,
        "unavailable_semantic_classes": 4,
        "physical_candidates": 4,
    }
    check(
        "preflight.schema",
        RESOLUTION_EXECUTION_BRIDGE_PREFLIGHT_SCHEMA_VERSION,
        preflight.get("schema_version"),
    )
    check("preflight.sealed", True, preflight.get("sealed_before_service_start"))
    check(
        "preflight.bridge_first",
        True,
        preflight.get("bridge_sealed_before_workload_generation"),
    )
    check("preflight.backend_calls", 0, preflight.get("backend_calls_before_seal"))
    check(
        "preflight.oracle_not_opened",
        False,
        preflight.get("answer_oracle_opened_before_seal"),
    )
    check("preflight.no_retries", 0, preflight.get("automatic_retries"))
    check("preflight.paper_result", False, preflight.get("paper_result"))
    check("preflight.counts", expected_counts, preflight.get("expected_counts"))
    check(
        "preflight.resolution_hash",
        _sha256_file(resolution_path) if resolution_path.is_file() else None,
        preflight.get("resolution_run_sha256"),
    )
    check(
        "preflight.spec_hash",
        _sha256_file(bridge_spec_path) if bridge_spec_path.is_file() else None,
        preflight.get("bridge_spec_sha256"),
    )
    check(
        "preflight.workload_hash",
        _sha256_file(preflight_root / "workload/direct/manifest.json")
        if (preflight_root / "workload/direct/manifest.json").is_file()
        else None,
        preflight.get("workload_manifest_sha256"),
    )
    check(
        "preflight.self_hash",
        content_hash(
            {key: value for key, value in preflight.items() if key != "preflight_sha256"}
        ),
        preflight.get("preflight_sha256"),
    )
    check("preflight.bridge_exact", bridge_payload, preflight_bridge)
    check("service.preflight_exact", preflight, service.get("resolution_execution_bridge_preflight"))

    check(
        "fixture.schema",
        PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
        fixture.get("schema_version"),
    )
    check("fixture_status.status", "success", fixture_status.get("status"))
    check("fixture.status", "success", fixture.get("status"))
    check("fixture.error", None, fixture.get("error"))
    check(
        "fixture.bundle",
        dict(workload.workload_bundle.manifest) if workload is not None else None,
        fixture.get("workload_bundle"),
    )
    check(
        "fixture.loads",
        True,
        set(fixture_loads) == {"neo4j", "fuseki"}
        and all(_dict(item).get("success") is True for item in fixture_loads.values()),
    )
    check(
        "fixture.verification",
        True,
        _exact_validation(fixture_verification.get("validation")),
    )
    check("fixture.validation_passed", True, _dict(fixture.get("verification")).get("passed"))
    check("fixture.automatic_retries", 0, fixture.get("automatic_retries"))
    check("fixture.git_commit", expected_commit, _dict(fixture.get("git")).get("commit"))
    check("fixture.git_clean", True, _dict(fixture.get("git")).get("clean"))

    check(
        "live.schema",
        LIVE_RESOLUTION_EXECUTION_BRIDGE_SCHEMA_VERSION,
        live.get("schema_version"),
    )
    check("live_status.status", "success", live_status.get("status"))
    check("live.status", "success", live.get("status"))
    check("live.error", None, live.get("error"))
    check("live.git_commit", expected_commit, _dict(live.get("git")).get("commit"))
    check("live.git_clean", True, _dict(live.get("git")).get("clean"))
    check("live.bridge_exact", bridge_payload, live_bridge)
    check("live.validation", True, _exact_validation(validation))
    check("live.manifest_validation", True, _exact_validation(live.get("validation")))
    check(
        "live.health",
        True,
        set(live_health) == {"neo4j", "fuseki"}
        and all(_dict(item).get("ok") is True for item in live_health.values()),
    )
    candidates = _list(bridge_payload.get("physical_candidates"))
    check("results.count", 4, len(results))
    check(
        "results.plan_order",
        [str(item["plan_id"]) for item in candidates],
        [str(_dict(item).get("plan_id")) for item in results],
    )
    for index, candidate in enumerate(candidates):
        result = _dict(results[index]) if index < len(results) else {}
        runtime = _dict(result.get("runtime_result"))
        query_id = str(candidate["query_id"])
        instance = instances.get(query_id)
        oracle = instance.get("final_oracle") if instance is not None else None
        prefix = f"result.{index}"
        check(f"{prefix}.semantic_class", candidate["semantic_class_id"], result.get("semantic_class_id"))
        check(f"{prefix}.query_id", query_id, result.get("query_id"))
        check(f"{prefix}.strategy", candidate["physical_strategy"], result.get("physical_strategy"))
        check(f"{prefix}.exact_marker", True, result.get("exact_oracle_answer"))
        check(f"{prefix}.runtime_success", True, runtime.get("success"))
        check(f"{prefix}.remote_calls", 2, runtime.get("total_remote_calls"))
        check(f"{prefix}.exact_rows", oracle, runtime.get("final_rows"))
        check(
            f"{prefix}.row_count",
            len(oracle) if isinstance(oracle, list) else None,
            result.get("expected_final_row_count"),
        )

    unavailable = {
        str(item["semantic_class_id"])
        for item in _list(bridge_payload.get("semantic_classes"))
        if _dict(item).get("availability") == "unavailable"
    }
    check(
        "results.unavailable_not_executed",
        True,
        all(str(_dict(item).get("semantic_class_id")) not in unavailable for item in results),
    )
    check(
        "bridge.unavailable_have_no_candidates",
        True,
        all(
            _dict(item).get("physical_candidate_ids") == []
            for item in _list(bridge_payload.get("semantic_classes"))
            if _dict(item).get("availability") == "unavailable"
        ),
    )
    hard_upper_bounds = []
    if bridge is not None:
        for plan in bridge.plans.values():
            for node in plan.nodes:
                if node.parameters.get("backend_id") == "neo4j":
                    hard_upper_bounds.append(
                        _dict(_dict(node.parameters.get("artifact")).get("parameters")).get(
                            "occurred_on_lt"
                        )
                    )
    check("plans.hard_upper_bound", ["2026-09-01"] * 4, hard_upper_bounds)
    check(
        "bridge.no_native_text",
        True,
        "MATCH (" not in json.dumps(bridge_payload, sort_keys=True)
        and "SELECT " not in json.dumps(bridge_payload, sort_keys=True),
    )

    summary = _dict(live.get("summary"))
    check("summary.raw_interpretations", 6, summary.get("raw_interpretation_count"))
    check("summary.semantic_classes", 6, summary.get("semantic_class_count"))
    check("summary.executable_classes", 2, summary.get("executable_semantic_class_count"))
    check("summary.unavailable_classes", 4, summary.get("unavailable_semantic_class_count"))
    check("summary.physical_runs", 4, summary.get("physical_plan_run_count"))
    check("summary.remote_calls", 8, summary.get("total_remote_calls"))
    check("live.bridge_verified", True, live.get("bridge_verified_before_execution"))
    check("live.oracle_not_used_for_selection", False, live.get("answer_oracle_used_for_selection"))
    check(
        "live.oracle_opened_after_execution",
        True,
        live.get("answer_oracle_opened_after_all_executions"),
    )
    check("live.oracle_used_posthoc", True, live.get("answer_oracle_used_for_post_execution_validation"))
    check("live.unavailable_executed", False, live.get("unavailable_semantic_classes_executed"))
    check("live.profile_calls", 0, live.get("current_query_profile_calls"))
    check("live.llm_calls", 0, live.get("llm_calls_made"))
    check("live.ontology_calls", 0, live.get("ontology_service_calls_made"))
    check("live.automatic_retries", 0, live.get("automatic_retries"))
    check("live.paper_result", False, live.get("paper_result"))

    events = _list(invocations.get("events"))
    check("invocations.count", 8, invocations.get("total_tool_invocations"))
    check("invocations.events", 8, len(events))
    check("invocations.sequences", list(range(1, 9)), [
        _dict(item).get("sequence") for item in events
    ])
    check("invocations.operations", ["execute"] * 8, [
        _dict(item).get("operation") for item in events
    ])
    check("invocations.statuses", ["success"] * 8, [
        _dict(item).get("status") for item in events
    ])
    check("invocations.backends", {"neo4j": 4, "fuseki": 4}, {
        backend_id: sum(_dict(item).get("backend_id") == backend_id for item in events)
        for backend_id in ("neo4j", "fuseki")
    })
    check(
        "invocations.latencies",
        True,
        all(_nonnegative_number(_dict(item).get("elapsed_ms")) for item in events),
    )
    check(
        "invocations.unique_calls",
        8,
        len({
            (str(_dict(item).get("goal_id")), str(_dict(item).get("call_id")))
            for item in events
        }),
    )
    if bridge is not None:
        for candidate in candidates:
            plan_id = str(candidate["plan_id"])
            goal_id = f"resolution-execution-bridge-run:execute:{plan_id}"
            observed = {
                (
                    str(_dict(item).get("backend_id")),
                    str(_dict(item).get("artifact_id")),
                )
                for item in events
                if _dict(item).get("goal_id") == goal_id
            }
            expected = {
                (
                    str(node.parameters["backend_id"]),
                    str(_dict(node.parameters["artifact"])["artifact_id"]),
                )
                for node in bridge.plans[plan_id].nodes
                if node.parameters.get("backend_id") in {"neo4j", "fuseki"}
            }
            check(f"invocations.plan.{plan_id}", expected, observed)
    check("invocations.automatic_retries", 0, invocations.get("automatic_retries"))

    runtime_root = service.get("runtime_root")
    check(
        "runtime.cleaned",
        True,
        isinstance(runtime_root, str) and not Path(runtime_root).exists(),
    )
    after = _tree_snapshot(run)
    mutated = before != after
    check("audit.run_tree_unchanged", False, mutated)
    success = bool(checks) and all(item.passed for item in checks)
    return M15ResolutionExecutionBridgeEvidenceAudit(
        success=success,
        run_root=run,
        expected_commit=expected_commit,
        checks=tuple(checks),
        run_tree_mutated=mutated,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    try:
        audit = audit_m15_resolution_execution_bridge_run(
            run_root=arguments.run_root,
            expected_commit=arguments.expected_commit,
            repo_root=arguments.repo_root,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    payload = audit.to_dict()
    if arguments.output:
        output = Path(arguments.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            print(json.dumps({"status": "configuration_error", "error": f"audit output exists: {output}"}))
            return 2
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
