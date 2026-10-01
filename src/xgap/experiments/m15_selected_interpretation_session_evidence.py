"""Independent read-only audit for one native M15-E5D selected session."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    compile_m15_clarification_transport_session,
)
from xgap.experiments.m15_direct_family_prediction import (
    load_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_workload import (
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_executable_family_registry import (
    compile_m15_executable_family_registry_file,
)
from xgap.experiments.m15_live_resolution_execution_bridge import (
    M15PreparedResolutionExecutionBridge,
)
from xgap.experiments.m15_live_selected_interpretation_session import (
    LIVE_SELECTED_SESSION_SCHEMA_VERSION,
    SELECTED_SESSION_PREFLIGHT_SCHEMA_VERSION,
    M15PreparedSelectedInterpretationSession,
    build_m15_selected_session_preflight,
)
from xgap.experiments.m15_native_services import (
    SELECTED_INTERPRETATION_SESSION_SERVICE_RUN_SCHEMA_VERSION,
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
from xgap.runtime import FEDERATED_EXECUTION_TOOL, RuntimeNodeKind


SELECTED_INTERPRETATION_SESSION_AUDIT_SCHEMA_VERSION = (
    "m15-e5d-native-selected-interpretation-session-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class M15SelectedInterpretationSessionEvidenceCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class M15SelectedInterpretationSessionEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[M15SelectedInterpretationSessionEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": (
                SELECTED_INTERPRETATION_SESSION_AUDIT_SCHEMA_VERSION
            ),
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


def _read_json(path: Path) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"
    return value, "ok"


def _read_environment(path: Path) -> tuple[dict[str, str] | None, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                return None, f"invalid_line:{line}"
            key, value = line.split("=", 1)
            if not key or key in result:
                return None, f"duplicate_or_empty_key:{key}"
            result[key] = value
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"invalid_text:{exc}"
    return result, "ok"


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


def _exact_validation(value: object) -> bool:
    validation = _dict(value)
    checks = validation.get("checks")
    return (
        validation.get("passed") is True
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(item is True for item in checks.values())
    )


def _loopback_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        return (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _neo4j_loopback_configuration(value: object) -> bool:
    if not isinstance(value, str):
        return False
    settings: dict[str, str] = {}
    for line in value.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, item = line.split("=", 1)
        settings[key] = item
    expected_keys = (
        "server.default_listen_address",
        "server.default_advertised_address",
        "server.bolt.listen_address",
        "server.bolt.advertised_address",
        "server.http.listen_address",
        "server.http.advertised_address",
    )
    return all(
        key in settings
        and (
            settings[key] == "127.0.0.1"
            or settings[key].startswith("127.0.0.1:")
        )
        for key in expected_keys
    )


def audit_m15_selected_interpretation_session_run(
    *,
    run_root: str | Path,
    expected_commit: str,
    repo_root: str | Path | None = None,
) -> M15SelectedInterpretationSessionEvidenceAudit:
    """Reconstruct E5D and audit it without writing below ``run_root``."""

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
    preflight_root = service_root / "selected-interpretation-session-preflight"
    fixture_root = service_root / "resolution-execution-fixture-load"
    live_root = service_root / "selected-interpretation-session-run"
    input_root = run / "selected-session-inputs"
    paths = {
        "outer_status": run / "run_status.json",
        "environment": run / "environment.txt",
        "resolution_run": run / "resolution_run.json",
        "bridge_spec": run / "resolution_bridge_spec.json",
        "service_status": service_root / "run_status.json",
        "service_manifest": service_root / "run_manifest.json",
        "service_plan": service_root / "service_plan.json",
        "neo4j_config": service_root / "neo4j.conf",
        "service_health": service_root / "service_health.json",
        "service_shutdown": service_root / "service_shutdown.json",
        "preflight_manifest": preflight_root / "preflight_manifest.json",
        "preflight_session": preflight_root / "clarification_session.json",
        "preflight_events": preflight_root / "authority_events.json",
        "preflight_handoff": preflight_root / "execution_handoff.json",
        "training_memory": input_root / "training_memory_view.json",
        "predictor_policy": input_root / "predictor_policy.json",
        "interpretation_policy": input_root / "interpretation_policy.json",
        "ontology": input_root / "ontology.json",
        "relaxation_policy": input_root / "relaxation_policy.json",
        "transport_policy": input_root / "transport_policy.json",
        "live_policy": input_root / "live_policy.json",
        "fixture_status": fixture_root / "run_status.json",
        "fixture_manifest": fixture_root / "run_manifest.json",
        "fixture_loads": fixture_root / "load_reports.json",
        "fixture_verification": fixture_root / "verification.json",
        "live_status": live_root / "run_status.json",
        "live_manifest": live_root / "run_manifest.json",
        "live_session": live_root / "clarification_session.json",
        "live_events": live_root / "authority_events.json",
        "live_handoff": live_root / "execution_handoff.json",
        "live_health": live_root / "health.json",
        "live_goal_spec": live_root / "goal_spec.json",
        "live_planned": live_root / "planned_execution.json",
        "live_goal_state": live_root / "goal_state.json",
        "live_memory": live_root / "execution_memory.json",
        "live_results": live_root / "execution_results.json",
        "live_validation": live_root / "validation.json",
        "live_invocations": live_root / "backend_invocations.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        elif key == "neo4j_config":
            loaded[key], states[key] = _read_text(path)
        else:
            loaded[key], states[key] = _read_json(path)

    checks: list[M15SelectedInterpretationSessionEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            M15SelectedInterpretationSessionEvidenceCheck(
                check_id=check_id,
                passed=observed == expected,
                expected=expected,
                observed=observed,
            )
        )

    for key in paths:
        check(f"artifact.{key}", "ok", states[key])

    preflight = _dict(loaded.get("preflight_manifest"))
    bridge = None
    workload = None
    memory = None
    reconstructed = None
    expected_preflight = None
    reconstruction_error = None
    try:
        bridge = compile_m15_resolution_execution_bridge_files(
            resolution_run_path=paths["resolution_run"],
            bridge_spec_path=paths["bridge_spec"],
            repo_root=repo,
        )
        bridge_payload = bridge.to_dict()
        source_artifacts = bridge_payload["source_artifacts"]
        registry = compile_m15_executable_family_registry_file(
            repo / source_artifacts["executable_family_registry"]["path"],
            repo_root=repo,
        ).to_dict()
        family = next(
            item
            for item in registry["families"]
            if item["family_id"] == bridge_payload["executable_family"]["family_id"]
        )
        bindings = family["source_bindings"]
        base = load_m15_parameterized_workload_bundle(
            preflight_root / "workload/base"
        )
        workload = load_m15_direct_semantic_workload_bundle(
            preflight_root / "workload/direct",
            base_bundle=base,
            catalog=repo / bindings["semantic_catalog"]["path"],
            mapping=repo / bindings["predicate_mapping"]["path"],
        )
        memory = load_m15_direct_training_memory_view(
            paths["training_memory"],
            workload=workload,
            expected_memory_view_sha256=preflight.get(
                "training_memory_view_sha256"
            ),
        )
        events = _list(loaded.get("preflight_events"))
        reconstructed = compile_m15_clarification_transport_session(
            session_id=_dict(loaded.get("preflight_session")).get("session_id"),
            bridge=bridge,
            workload=workload,
            memory=memory,
            predictor_policy=paths["predictor_policy"],
            interpretation_policy=paths["interpretation_policy"],
            ontology_path=paths["ontology"],
            relaxation_policy=paths["relaxation_policy"],
            transport_policy=paths["transport_policy"],
            authority_events=events,
        )
        prepared_bridge = M15PreparedResolutionExecutionBridge(
            bridge=bridge,
            workload=workload,
            base_workload=base,
            semantic_catalog_path=repo / bindings["semantic_catalog"]["path"],
            predicate_mapping_path=repo / bindings["predicate_mapping"]["path"],
        )
        prepared = M15PreparedSelectedInterpretationSession(
            resolution_bridge=prepared_bridge,
            memory=memory,
            clarification_session=reconstructed,
            source_paths={
                key: paths[key]
                for key in (
                    "training_memory",
                    "predictor_policy",
                    "interpretation_policy",
                    "ontology",
                    "relaxation_policy",
                    "transport_policy",
                    "live_policy",
                )
            },
            expected_memory_view_sha256=memory.memory_view_hash,
        )
        expected_preflight = build_m15_selected_session_preflight(prepared)
    except Exception as exc:
        reconstruction_error = f"{type(exc).__name__}: {exc}"
    check("reconstruction.error", None, reconstruction_error)

    outer = _dict(loaded.get("outer_status"))
    environment = _dict(loaded.get("environment"))
    service_status = _dict(loaded.get("service_status"))
    service = _dict(loaded.get("service_manifest"))
    service_plan = _dict(loaded.get("service_plan"))
    neo4j_config = loaded.get("neo4j_config")
    service_health = _list(loaded.get("service_health"))
    service_shutdown = _list(loaded.get("service_shutdown"))
    preflight_session = _dict(loaded.get("preflight_session"))
    preflight_handoff = _dict(loaded.get("preflight_handoff"))
    fixture_status = _dict(loaded.get("fixture_status"))
    fixture = _dict(loaded.get("fixture_manifest"))
    fixture_loads = _dict(loaded.get("fixture_loads"))
    fixture_verification = _dict(loaded.get("fixture_verification"))
    live_status = _dict(loaded.get("live_status"))
    live = _dict(loaded.get("live_manifest"))
    live_session = _dict(loaded.get("live_session"))
    live_handoff = _dict(loaded.get("live_handoff"))
    live_health = _dict(loaded.get("live_health"))
    goal_spec = _dict(loaded.get("live_goal_spec"))
    planned = _dict(loaded.get("live_planned"))
    goal_state = _dict(loaded.get("live_goal_state"))
    execution_memory = _list(loaded.get("live_memory"))
    results = _list(_dict(loaded.get("live_results")).get("results"))
    validation = _dict(loaded.get("live_validation"))
    invocations = _dict(loaded.get("live_invocations"))
    expected_session = reconstructed.to_dict() if reconstructed is not None else None
    expected_handoff = (
        reconstructed.execution_handoff.to_dict()
        if reconstructed is not None
        and reconstructed.execution_handoff is not None
        else None
    )
    selected_ids = (
        list(expected_handoff["selected_plan_ids"])
        if expected_handoff is not None
        else []
    )

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check(
        "outer.workload_mode",
        "selected_interpretation_session",
        outer.get("workload_mode"),
    )
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))
    check(
        "environment.run_version",
        "m15-e5d-native-live-selected-interpretation-session-services-v1",
        environment.get("run_version"),
    )
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))
    check(
        "service.schema",
        SELECTED_INTERPRETATION_SESSION_SERVICE_RUN_SCHEMA_VERSION,
        service.get("schema_version"),
    )
    check("service_status.status", "success", service_status.get("status"))
    check("service.status", "success", service.get("status"))
    check("service.error", None, service.get("error"))
    check("service.automatic_retries", 0, service.get("automatic_retries"))
    check("service.restarts", 0, service.get("service_restarts"))
    check("service.public_ports", False, service.get("public_ports"))
    check("service.credentials", False, service.get("credentials_persisted"))
    check(
        "service.health",
        True,
        len(service_health) == 2
        and all(_dict(item).get("success") is True for item in service_health),
    )
    check(
        "service.shutdown",
        True,
        len(service_shutdown) == 2
        and all(_dict(item).get("success") is True for item in service_shutdown),
    )
    planned_services = {
        str(_dict(item).get("service_id")): _dict(item)
        for item in _list(service_plan.get("services"))
    }
    fuseki_command = _list(planned_services.get("fuseki", {}).get("command"))
    plan_is_loopback_only = (
        service_plan.get("public_ports") is False
        and set(planned_services) == {"neo4j", "fuseki"}
        and all(
            _loopback_url(url)
            for url in (
                service_plan.get("neo4j_http_url"),
                service_plan.get("fuseki_url"),
                planned_services["neo4j"].get("health_url"),
                planned_services["fuseki"].get("health_url"),
            )
        )
        and "--localhost" in fuseki_command
        and _neo4j_loopback_configuration(neo4j_config)
    )
    check("service.plan.loopback_only", True, plan_is_loopback_only)
    check(
        "preflight.schema",
        SELECTED_SESSION_PREFLIGHT_SCHEMA_VERSION,
        preflight.get("schema_version"),
    )
    check("preflight.exact", expected_preflight, dict(preflight))
    check("service.preflight_exact", dict(preflight), service.get(
        "selected_interpretation_session_preflight"
    ))
    check("preflight.session_exact", expected_session, dict(preflight_session))
    check("preflight.handoff_exact", expected_handoff, dict(preflight_handoff))
    check("preflight.sealed", True, preflight.get("sealed_before_service_start"))
    check("preflight.backend_calls", 0, preflight.get("backend_calls_before_seal"))
    check("preflight.profile_calls", 0, preflight.get("current_query_profile_calls"))
    check("preflight.no_retries", 0, preflight.get("automatic_retries"))
    check("preflight.paper_result", False, preflight.get("paper_result"))

    check("fixture.schema", PARAMETERIZED_FIXTURE_SCHEMA_VERSION, fixture.get("schema_version"))
    check("fixture_status.status", "success", fixture_status.get("status"))
    check("fixture.status", "success", fixture.get("status"))
    check("fixture.error", None, fixture.get("error"))
    check(
        "fixture.loads",
        True,
        set(fixture_loads) == {"neo4j", "fuseki"}
        and all(_dict(item).get("success") is True for item in fixture_loads.values()),
    )
    check("fixture.verification", True, _exact_validation(fixture_verification.get("validation")))
    check("fixture.automatic_retries", 0, fixture.get("automatic_retries"))
    check("fixture.git_commit", expected_commit, _dict(fixture.get("git")).get("commit"))
    check("fixture.git_clean", True, _dict(fixture.get("git")).get("clean"))

    check("live.schema", LIVE_SELECTED_SESSION_SCHEMA_VERSION, live.get("schema_version"))
    check("live_status.status", "success", live_status.get("status"))
    check("live.status", "success", live.get("status"))
    check("live.error", None, live.get("error"))
    check("live.git_commit", expected_commit, _dict(live.get("git")).get("commit"))
    check("live.git_clean", True, _dict(live.get("git")).get("clean"))
    check("live.session_exact", expected_session, dict(live_session))
    check("live.handoff_exact", expected_handoff, dict(live_handoff))
    check("live.events_exact", preflight_session.get("authority_events"), loaded.get("live_events"))
    check("live.validation", True, _exact_validation(validation))
    check("live.manifest_validation", True, _exact_validation(live.get("validation")))
    check(
        "live.health",
        True,
        set(live_health) == {"neo4j", "fuseki"}
        and all(_dict(item).get("ok") is True for item in live_health.values()),
    )
    check("goal.allowed_tools", [FEDERATED_EXECUTION_TOOL], goal_spec.get("allowed_tools"))
    check("goal.max_tool_calls", len(selected_ids), goal_spec.get("max_tool_calls"))
    check("goal.status", "succeeded", goal_state.get("status"))
    check("goal.tool_calls", len(selected_ids), goal_state.get("tool_calls"))
    check("planned.plan_ids", selected_ids, planned.get("selected_plan_ids"))
    check("planned.arguments_absent", False, planned.get("plan_arguments_persisted"))
    check("memory.count", len(selected_ids), len(execution_memory))
    check(
        "memory.runtime_tool_only",
        True,
        all(_dict(item).get("source") == FEDERATED_EXECUTION_TOOL for item in execution_memory),
    )
    check("results.plan_order", selected_ids, [str(_dict(item).get("plan_id")) for item in results])
    descriptor_by_id = {
        str(item["plan_id"]): item
        for item in _list(_dict(expected_handoff).get("selected_plans"))
        if isinstance(item, Mapping) and "plan_id" in item
    }
    for index, plan_id in enumerate(selected_ids):
        result = _dict(results[index]) if index < len(results) else {}
        runtime = _dict(result.get("runtime_result"))
        descriptor = _dict(descriptor_by_id.get(plan_id))
        instance = (
            load_m15_parameterized_instance(workload.workload_bundle, descriptor["query_id"])
            if workload is not None and descriptor.get("query_id")
            else None
        )
        oracle = instance.get("final_oracle") if instance is not None else None
        prefix = f"result.{index}"
        check(f"{prefix}.query_id", descriptor.get("query_id"), result.get("query_id"))
        check(f"{prefix}.strategy", descriptor.get("physical_strategy"), result.get("physical_strategy"))
        check(f"{prefix}.runtime_success", True, runtime.get("success"))
        check(f"{prefix}.remote_calls", 2, runtime.get("total_remote_calls"))
        check(f"{prefix}.exact_marker", True, result.get("exact_oracle_answer"))
        check(f"{prefix}.exact_rows", oracle, runtime.get("final_rows"))

    events = _list(invocations.get("events"))
    check("invocations.count", 2 * len(selected_ids), invocations.get("total_tool_invocations"))
    check("invocations.events", 2 * len(selected_ids), len(events))
    check("invocations.operations", ["execute"] * len(events), [_dict(item).get("operation") for item in events])
    check("invocations.status", ["success"] * len(events), [_dict(item).get("status") for item in events])
    check("invocations.no_retries", 0, invocations.get("automatic_retries"))
    check("live.selected_ids", selected_ids, live.get("selected_plan_ids"))
    check("live.profile_calls", 0, live.get("current_query_profile_calls"))
    check("live.llm_calls", 0, live.get("llm_calls_made"))
    check("live.ontology_calls", 0, live.get("ontology_service_calls_made"))
    check("live.no_retries", 0, live.get("automatic_retries"))
    check("live.paper_result", False, live.get("paper_result"))
    check(
        "control_plane.no_native_query_text",
        True,
        " MATCH " not in json.dumps({"session": live_session, "handoff": live_handoff})
        and "SELECT " not in json.dumps({"session": live_session, "handoff": live_handoff}),
    )
    hard_upper_bounds: list[str | None] = []
    if reconstructed is not None and reconstructed.execution_handoff is not None:
        for plan in reconstructed.execution_handoff.plans.values():
            for node in plan.nodes:
                if node.kind in {RuntimeNodeKind.REMOTE_QUERY, RuntimeNodeKind.REMOTE_BIND_QUERY} and node.parameters.get("backend_id") == "neo4j":
                    hard_upper_bounds.append(
                        _dict(_dict(node.parameters.get("artifact")).get("parameters")).get("occurred_on_lt")
                    )
    check("plans.hard_upper_bound", ["2026-09-01"] * len(selected_ids), hard_upper_bounds)
    check(
        "runtime.cleaned",
        True,
        isinstance(service.get("runtime_root"), str)
        and not Path(service["runtime_root"]).exists(),
    )
    after = _tree_snapshot(run)
    mutated = before != after
    check("audit.run_tree_unchanged", False, mutated)
    success = bool(checks) and all(item.passed for item in checks)
    return M15SelectedInterpretationSessionEvidenceAudit(
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
        audit = audit_m15_selected_interpretation_session_run(
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
