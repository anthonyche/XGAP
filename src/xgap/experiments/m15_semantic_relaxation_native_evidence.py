"""Read-only audit for one native F2C7B2 semantic-relaxation run."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_live_semantic_relaxation import (
    FIXED_PHYSICAL_STRATEGY,
    LIVE_SEMANTIC_RELAXATION_SCHEMA_VERSION,
    SEMANTIC_RISK_EXECUTION_CONTRACT_VERSION,
    build_m15_semantic_risk_execution_plan,
)
from xgap.experiments.m15_native_services import (
    SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION,
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
from xgap.experiments.m15_semantic_frontier import (
    load_m15_semantic_relaxation_catalog,
)
from xgap.experiments.m15_semantic_overlay import (
    load_m15_semantic_overlay_bundle,
)


SEMANTIC_RELAXATION_AUDIT_SCHEMA_VERSION = (
    "m15-f2c7b2-native-semantic-relaxation-evidence-audit-v1"
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
class SemanticRelaxationEvidenceCheck:
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
class M15SemanticRelaxationNativeEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[SemanticRelaxationEvidenceCheck, ...]

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SEMANTIC_RELAXATION_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": False,
        }


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


def audit_m15_semantic_relaxation_native_run(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15SemanticRelaxationNativeEvidenceAudit:
    """Audit the complete F2C7B2 artifact graph without changing it."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    run = selected.resolve()
    if not run.is_dir():
        raise ValueError("run_root must be a real directory")

    service_root = run / "native-service-run"
    fixture_root = service_root / "semantic-fixture-load"
    live_root = service_root / "semantic-risk-relaxation-run"
    base_root = run / "semantic-base-workload-bundle"
    overlay_root = run / "semantic-overlay"
    catalog_path = run / "semantic_catalog.json"
    paths = {
        "outer_status": run / "run_status.json",
        "environment": run / "environment.txt",
        "base_generation": run / "semantic_base_generation.json",
        "overlay_generation": run / "semantic_overlay_generation.json",
        "service_status": service_root / "run_status.json",
        "service_manifest": service_root / "run_manifest.json",
        "service_health": service_root / "service_health.json",
        "service_shutdown": service_root / "service_shutdown.json",
        "fixture_status": fixture_root / "run_status.json",
        "fixture_manifest": fixture_root / "run_manifest.json",
        "fixture_verification": fixture_root / "verification.json",
        "fixture_loads": fixture_root / "load_reports.json",
        "live_status": live_root / "run_status.json",
        "live_manifest": live_root / "run_manifest.json",
        "execution_contract": live_root / "execution_contract.json",
        "semantic_plan": live_root / "semantic_plan.json",
        "semantic_result": live_root / "semantic_result.json",
        "live_validation": live_root / "validation.json",
        "live_invocations": live_root / "backend_invocations.json",
        "semantic_catalog": catalog_path,
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        else:
            loaded[key], states[key] = _read_json(path)

    checks: list[SemanticRelaxationEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            SemanticRelaxationEvidenceCheck(
                check_id,
                observed == expected,
                expected,
                observed,
            )
        )

    for key in paths:
        check(f"artifact.{key}", "ok", states[key])

    base = None
    catalog = None
    overlay = None
    expected_plan = None
    expected_contract = None
    expected_instance = None
    try:
        base = load_m15_parameterized_workload_bundle(base_root)
        catalog = load_m15_semantic_relaxation_catalog(catalog_path)
        overlay = load_m15_semantic_overlay_bundle(
            overlay_root,
            base_bundle=base,
            catalog=catalog,
        )
        expected_plan, expected_contract = build_m15_semantic_risk_execution_plan(
            overlay=overlay,
            base_bundle=base,
        )
        expected_instance = load_m15_parameterized_instance(
            overlay.workload_bundle,
            expected_contract["query_id"],
        )
        check("semantic_chain.integrity", True, True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        check("semantic_chain.integrity", True, f"invalid:{exc}")

    outer = _dict(loaded.get("outer_status"))
    environment = _dict(loaded.get("environment"))
    base_generation = _dict(loaded.get("base_generation"))
    overlay_generation = _dict(loaded.get("overlay_generation"))
    service_status = _dict(loaded.get("service_status"))
    service = _dict(loaded.get("service_manifest"))
    health = _list(loaded.get("service_health"))
    shutdown = _list(loaded.get("service_shutdown"))
    fixture_status = _dict(loaded.get("fixture_status"))
    fixture = _dict(loaded.get("fixture_manifest"))
    fixture_verification = _dict(loaded.get("fixture_verification"))
    fixture_loads = _dict(loaded.get("fixture_loads"))
    live_status = _dict(loaded.get("live_status"))
    live = _dict(loaded.get("live_manifest"))
    execution_contract = _dict(loaded.get("execution_contract"))
    semantic_plan = _dict(loaded.get("semantic_plan"))
    result = _dict(loaded.get("semantic_result"))
    validation = _dict(loaded.get("live_validation"))
    invocations = _dict(loaded.get("live_invocations"))

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check(
        "outer.workload_mode",
        "semantic_risk_relaxation",
        outer.get("workload_mode"),
    )
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))
    check(
        "environment.run_version",
        "m15-f2c7b2-native-live-semantic-risk-relaxation-services-v1",
        environment.get("run_version"),
    )
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check(
        "environment.workload_mode",
        "semantic_risk_relaxation",
        environment.get("workload_mode"),
    )
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))

    if base is not None:
        check("base_generation.status", "success", base_generation.get("status"))
        check("base_generation.root", str(base.root), base_generation.get("root"))
        for key, value in base.manifest.items():
            check(
                f"base_generation.manifest.{key}",
                value,
                base_generation.get(key),
            )
    if overlay is not None:
        check(
            "overlay_generation.status",
            "success",
            overlay_generation.get("status"),
        )
        check(
            "overlay_generation.root",
            str(overlay.root),
            overlay_generation.get("root"),
        )
        for key, value in overlay.manifest.items():
            check(
                f"overlay_generation.manifest.{key}",
                value,
                overlay_generation.get(key),
            )

    check(
        "service.schema",
        SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION,
        service.get("schema_version"),
    )
    check("service_status.status", "success", service_status.get("status"))
    check("service.status", "success", service.get("status"))
    check("service.error", None, service.get("error"))
    check(
        "service.workload_mode",
        "semantic_risk_relaxation",
        service.get("workload_mode"),
    )
    check("service.workload_bundle", None, service.get("workload_bundle"))
    check(
        "service.parameterized_bundle",
        None,
        service.get("parameterized_workload_bundle"),
    )
    check(
        "service.semantic_base",
        dict(base.manifest) if base is not None else None,
        service.get("semantic_base_workload_bundle"),
    )
    check(
        "service.semantic_overlay",
        dict(overlay.manifest) if overlay is not None else None,
        service.get("semantic_overlay"),
    )
    check("service.automatic_retries", 0, service.get("automatic_retries"))
    check("service.restarts", 0, service.get("service_restarts"))
    check("service.public_ports", False, service.get("public_ports"))
    check("service.credentials", False, service.get("credentials_persisted"))
    check(
        "service.health",
        True,
        len(health) == 2
        and [str(_dict(item).get("service_id")) for item in health]
        == ["neo4j", "fuseki"]
        and all(_dict(item).get("success") is True for item in health),
    )
    check(
        "service.shutdown",
        True,
        len(shutdown) == 2
        and [str(_dict(item).get("service_id")) for item in shutdown]
        == ["fuseki", "neo4j"]
        and all(_dict(item).get("success") is True for item in shutdown),
    )

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
        dict(overlay.workload_bundle.manifest) if overlay is not None else None,
        fixture.get("workload_bundle"),
    )
    check(
        "fixture.loads",
        True,
        set(fixture_loads) == {"neo4j", "fuseki"}
        and all(_dict(item).get("success") is True for item in fixture_loads.values()),
    )
    fixture_summary = _dict(fixture.get("verification"))
    expected_query_count = (
        len(overlay.workload_bundle.instance_ids()) if overlay is not None else None
    )
    check(
        "fixture.query_count",
        expected_query_count,
        fixture_summary.get("query_instance_count"),
    )
    check(
        "fixture.backend_query_count",
        expected_query_count * 2 if expected_query_count is not None else None,
        fixture_summary.get("backend_query_count"),
    )
    check("fixture.verification", True, _exact_validation(fixture_verification.get("validation")))
    check("fixture.validation_passed", True, fixture_summary.get("passed"))
    check("fixture.automatic_retries", 0, fixture.get("automatic_retries"))
    check("fixture.git_commit", expected_commit, _dict(fixture.get("git")).get("commit"))
    check("fixture.git_clean", True, _dict(fixture.get("git")).get("clean"))

    check(
        "live.schema",
        LIVE_SEMANTIC_RELAXATION_SCHEMA_VERSION,
        live.get("schema_version"),
    )
    check("live_status.status", "success", live_status.get("status"))
    check("live.status", "success", live.get("status"))
    check("live.error", None, live.get("error"))
    check("live.git_commit", expected_commit, _dict(live.get("git")).get("commit"))
    check("live.git_clean", True, _dict(live.get("git")).get("clean"))
    check(
        "live.overlay",
        dict(overlay.manifest) if overlay is not None else None,
        live.get("semantic_overlay"),
    )
    check(
        "execution_contract.schema",
        SEMANTIC_RISK_EXECUTION_CONTRACT_VERSION,
        execution_contract.get("schema_version"),
    )
    check("execution_contract", expected_contract, execution_contract)
    check(
        "semantic_plan",
        expected_plan.to_dict() if expected_plan is not None else None,
        semantic_plan,
    )
    check("live.selected_plan", semantic_plan, live.get("selected_plan"))
    check(
        "live.execution_contract",
        execution_contract,
        live.get("execution_contract"),
    )
    check("result.success", True, result.get("success"))
    check("result.plan_id", semantic_plan.get("plan_id"), result.get("plan_id"))
    check("result.remote_calls", 2, result.get("total_remote_calls"))
    check(
        "result.exact_rows",
        expected_instance["final_oracle"] if expected_instance is not None else None,
        result.get("final_rows"),
    )
    check(
        "result.risk_medium",
        True,
        bool(_list(result.get("final_rows")))
        and {row.get("risk") for row in _list(result.get("final_rows")) if isinstance(row, Mapping)}
        == {"MEDIUM"},
    )
    check("live.validation", True, _exact_validation(validation))
    check("live.manifest_validation", True, _exact_validation(live.get("validation")))
    events = _list(invocations.get("events"))
    check("invocations.count", 2, invocations.get("total_tool_invocations"))
    check("invocations.events", 2, len(events))
    check(
        "invocations.backends",
        ["fuseki", "neo4j"],
        [str(_dict(item).get("backend_id")) for item in events],
    )
    check(
        "invocations.operations",
        ["execute", "execute"],
        [str(_dict(item).get("operation")) for item in events],
    )
    expected_query_id = (
        expected_contract.get("query_id") if expected_contract is not None else None
    )
    expected_artifact_ids = (
        [
            f"m15-f2c-{expected_query_id}-fuseki-risk",
            f"m15-f2c-{expected_query_id}-neo4j-bound",
        ]
        if expected_query_id is not None
        else None
    )
    check(
        "invocations.artifacts",
        expected_artifact_ids,
        [str(_dict(item).get("artifact_id")) for item in events],
    )
    check("invocations.automatic_retries", 0, invocations.get("automatic_retries"))
    check(
        "plan.fixed_strategy",
        FIXED_PHYSICAL_STRATEGY,
        _dict(semantic_plan.get("metadata")).get("physical_strategy"),
    )
    check(
        "plan.positive_semantic_deviation",
        True,
        isinstance(_dict(semantic_plan.get("metadata")).get("semantic_deviation"), (int, float))
        and _dict(semantic_plan.get("metadata")).get("semantic_deviation") > 0,
    )
    serialized_plan = json.dumps(semantic_plan, sort_keys=True)
    check("plan.contains_no_oracle", False, "final_oracle" in serialized_plan)
    check(
        "live.oracle_not_used_for_selection",
        False,
        live.get("answer_oracle_used_for_plan_construction_or_selection"),
    )
    check("live.oracle_used_posthoc", True, live.get("answer_oracle_used_for_post_execution_validation"))
    check("live.no_physical_comparison", False, live.get("physical_strategy_comparison_enabled"))
    check("live.memory_disabled", False, live.get("memory_enabled"))
    check("live.llm_calls", 0, live.get("llm_calls_made"))
    check("live.ontology_calls", 0, live.get("ontology_calls_made"))
    check("live.automatic_retries", 0, live.get("automatic_retries"))
    check("live.paper_result", False, live.get("paper_result"))

    success = bool(checks) and all(item.passed for item in checks)
    return M15SemanticRelaxationNativeEvidenceAudit(
        success=success,
        run_root=run,
        expected_commit=expected_commit,
        checks=tuple(checks),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    try:
        audit = audit_m15_semantic_relaxation_native_run(
            run_root=arguments.run_root,
            expected_commit=arguments.expected_commit,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    payload = audit.to_dict()
    if arguments.output:
        output = Path(arguments.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            print(
                json.dumps(
                    {
                        "status": "configuration_error",
                        "error": f"audit output exists: {output}",
                    }
                )
            )
            return 2
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
