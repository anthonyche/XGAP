"""Read-only reconstruction audit for one native F2C9B frontier run."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_direct_semantic_estimates import (
    bind_m15_direct_estimate_snapshot,
    load_m15_direct_estimate_source,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    build_m15_direct_semantic_candidate_set,
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_live_direct_semantic_frontier import (
    LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION,
)
from xgap.experiments.m15_native_services import (
    DIRECT_SEMANTIC_FRONTIER_PREFLIGHT_SCHEMA_VERSION,
    DIRECT_SEMANTIC_FRONTIER_SERVICE_RUN_SCHEMA_VERSION,
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
from xgap.experiments.m15_predicate_overlay import (
    M15PredicateMappingSpec,
    load_m15_predicate_overlay_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    load_m15_semantic_relaxation_catalog,
)


DIRECT_FRONTIER_AUDIT_SCHEMA_VERSION = (
    "m15-f2c9b-native-direct-semantic-frontier-evidence-audit-v1"
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
class DirectFrontierEvidenceCheck:
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
class M15DirectFrontierNativeEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[DirectFrontierEvidenceCheck, ...]

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DIRECT_FRONTIER_AUDIT_SCHEMA_VERSION,
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


def audit_m15_direct_frontier_native_run(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15DirectFrontierNativeEvidenceAudit:
    """Rebuild every F2C9B selection artifact without mutating the run tree."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    run = selected.resolve()
    if not run.is_dir():
        raise ValueError("run_root must be a real directory")

    service_root = run / "native-service-run"
    fixture_root = service_root / "frontier-fixture-load"
    live_root = service_root / "direct-semantic-frontier-run"
    base_root = run / "semantic-base-workload-bundle"
    overlay_root = run / "predicate-overlay"
    catalog_path = run / "semantic_catalog.json"
    mapping_path = run / "predicate_mapping.json"
    estimate_path = run / "direct_frontier_estimates.json"
    # The native service seals the frontier inside its own evidence root before
    # starting either backend.  Keep the auditor aligned with that production
    # layout; looking under the outer Slurm run root makes a valid preflight
    # appear missing and was masked by the original synthetic audit fixture.
    preflight_root = service_root / "direct-frontier-preflight"
    paths = {
        "outer_status": run / "run_status.json",
        "environment": run / "environment.txt",
        "base_generation": run / "semantic_base_generation.json",
        "overlay_generation": run / "predicate_overlay_generation.json",
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
        "candidate_set": live_root / "candidate_set.json",
        "estimate_source": live_root / "estimate_source.json",
        "estimate_snapshot": live_root / "estimate_snapshot.json",
        "semantic_frontier": live_root / "semantic_frontier.json",
        "semantic_results": live_root / "semantic_results.json",
        "live_validation": live_root / "validation.json",
        "live_invocations": live_root / "backend_invocations.json",
        "semantic_catalog": catalog_path,
        "predicate_mapping": mapping_path,
        "direct_frontier_estimates": estimate_path,
        "preflight_manifest": preflight_root / "preflight_manifest.json",
        "preflight_candidate_set": preflight_root / "candidate_set.json",
        "preflight_estimate_source": preflight_root / "estimate_source.json",
        "preflight_estimate_snapshot": preflight_root / "estimate_snapshot.json",
        "preflight_semantic_frontier": preflight_root / "semantic_frontier.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        else:
            loaded[key], states[key] = _read_json(path)

    checks: list[DirectFrontierEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            DirectFrontierEvidenceCheck(
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
    mapping = None
    overlay = None
    estimate_source = None
    expected_candidates = None
    expected_snapshot = None
    expected_frontier = None
    expected_instances: dict[str, dict[str, Any]] = {}
    try:
        base = load_m15_parameterized_workload_bundle(base_root)
        catalog = load_m15_semantic_relaxation_catalog(catalog_path)
        mapping = M15PredicateMappingSpec.from_json(mapping_path)
        overlay = load_m15_predicate_overlay_bundle(
            overlay_root,
            base_bundle=base,
            catalog=catalog,
            mapping=mapping,
        )
        estimate_source = load_m15_direct_estimate_source(estimate_path)
        expected_candidates = build_m15_direct_semantic_candidate_set(
            predicate_overlay=overlay,
            base_bundle=base,
            catalog=catalog,
            mapping=mapping,
        )
        expected_snapshot = bind_m15_direct_estimate_snapshot(
            expected_candidates,
            estimate_source,
        )
        expected_frontier = select_m15_direct_semantic_frontier(
            expected_candidates,
            expected_snapshot,
        )
        expected_instances = {
            item["query_id"]: load_m15_parameterized_instance(
                overlay.workload_bundle,
                item["query_id"],
            )
            for item in expected_frontier.to_dict()["returned_semantic_plans"]
        }
        check("frontier_chain.integrity", True, True)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        check("frontier_chain.integrity", True, f"invalid:{exc}")

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
    candidates = _dict(loaded.get("candidate_set"))
    source = _dict(loaded.get("estimate_source"))
    snapshot = _dict(loaded.get("estimate_snapshot"))
    frontier = _dict(loaded.get("semantic_frontier"))
    results = _list(_dict(loaded.get("semantic_results")).get("results"))
    validation = _dict(loaded.get("live_validation"))
    invocations = _dict(loaded.get("live_invocations"))
    preflight_manifest = _dict(loaded.get("preflight_manifest"))
    preflight_candidates = _dict(loaded.get("preflight_candidate_set"))
    preflight_source = _dict(loaded.get("preflight_estimate_source"))
    preflight_snapshot = _dict(loaded.get("preflight_estimate_snapshot"))
    preflight_frontier = _dict(loaded.get("preflight_semantic_frontier"))

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check("outer.workload_mode", "semantic_direct_frontier", outer.get("workload_mode"))
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))
    check(
        "environment.run_version",
        "m15-f2c9b-native-live-direct-semantic-frontier-services-v1",
        environment.get("run_version"),
    )
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check(
        "environment.workload_mode",
        "semantic_direct_frontier",
        environment.get("workload_mode"),
    )
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))

    if base is not None:
        check("base_generation.status", "success", base_generation.get("status"))
        check("base_generation.root", str(base.root), base_generation.get("root"))
        for key, value in base.manifest.items():
            check(f"base_generation.manifest.{key}", value, base_generation.get(key))
    if overlay is not None:
        check("overlay_generation.status", "success", overlay_generation.get("status"))
        check("overlay_generation.root", str(overlay.root), overlay_generation.get("root"))
        for key, value in overlay.manifest.items():
            check(f"overlay_generation.manifest.{key}", value, overlay_generation.get(key))

    check(
        "service.schema",
        DIRECT_SEMANTIC_FRONTIER_SERVICE_RUN_SCHEMA_VERSION,
        service.get("schema_version"),
    )
    check("service_status.status", "success", service_status.get("status"))
    check("service.status", "success", service.get("status"))
    check("service.error", None, service.get("error"))
    check("service.workload_mode", "semantic_direct_frontier", service.get("workload_mode"))
    check("service.workload_bundle", None, service.get("workload_bundle"))
    check("service.parameterized_bundle", None, service.get("parameterized_workload_bundle"))
    check(
        "service.semantic_base",
        dict(base.manifest) if base is not None else None,
        service.get("semantic_base_workload_bundle"),
    )
    check("service.risk_overlay", None, service.get("semantic_overlay"))
    check(
        "service.predicate_overlay",
        dict(overlay.manifest) if overlay is not None else None,
        service.get("predicate_overlay"),
    )
    check(
        "service.predicate_mapping",
        mapping.to_dict() if mapping is not None else None,
        service.get("predicate_mapping"),
    )
    check(
        "service.estimate_source",
        estimate_source.to_dict() if estimate_source is not None else None,
        service.get("direct_frontier_estimates"),
    )
    check(
        "service.direct_frontier_preflight",
        preflight_manifest,
        service.get("direct_frontier_preflight"),
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

    check("fixture.schema", PARAMETERIZED_FIXTURE_SCHEMA_VERSION, fixture.get("schema_version"))
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
    check("fixture.query_count", expected_query_count, fixture_summary.get("query_instance_count"))
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

    expected_candidate_payload = (
        expected_candidates.to_dict() if expected_candidates is not None else None
    )
    expected_source_payload = (
        estimate_source.to_dict() if estimate_source is not None else None
    )
    expected_snapshot_payload = (
        expected_snapshot.to_dict() if expected_snapshot is not None else None
    )
    expected_frontier_payload = (
        expected_frontier.to_dict() if expected_frontier is not None else None
    )
    check("candidate_set.exact", expected_candidate_payload, candidates)
    check("estimate_source.exact", expected_source_payload, source)
    check("estimate_snapshot.exact", expected_snapshot_payload, snapshot)
    check("semantic_frontier.exact", expected_frontier_payload, frontier)
    check(
        "preflight.schema",
        DIRECT_SEMANTIC_FRONTIER_PREFLIGHT_SCHEMA_VERSION,
        preflight_manifest.get("schema_version"),
    )
    check(
        "preflight.sealed_before_service_start",
        True,
        preflight_manifest.get("sealed_before_service_start"),
    )
    check(
        "preflight.backend_calls_before_seal",
        0,
        preflight_manifest.get("backend_calls_before_seal"),
    )
    check(
        "preflight.answer_oracle_fields",
        [],
        preflight_manifest.get("answer_oracle_fields"),
    )
    check(
        "preflight.postexecution",
        False,
        preflight_manifest.get("post_execution_measurements_used"),
    )
    check("preflight.candidate_set", expected_candidate_payload, preflight_candidates)
    check("preflight.estimate_source", expected_source_payload, preflight_source)
    check(
        "preflight.estimate_snapshot",
        expected_snapshot_payload,
        preflight_snapshot,
    )
    check(
        "preflight.semantic_frontier",
        expected_frontier_payload,
        preflight_frontier,
    )
    check(
        "preflight.candidate_hash",
        candidates.get("candidate_set_sha256"),
        preflight_manifest.get("candidate_set_sha256"),
    )
    check(
        "preflight.source_hash",
        source.get("estimate_source_sha256"),
        preflight_manifest.get("estimate_source_sha256"),
    )
    check(
        "preflight.snapshot_hash",
        snapshot.get("estimate_snapshot_sha256"),
        preflight_manifest.get("estimate_snapshot_sha256"),
    )
    check(
        "preflight.frontier_hash",
        frontier.get("frontier_sha256"),
        preflight_manifest.get("frontier_sha256"),
    )
    check(
        "preflight.live_artifacts_identical",
        True,
        preflight_candidates == candidates
        and preflight_source == source
        and preflight_snapshot == snapshot
        and preflight_frontier == frontier,
    )
    check("candidate_set.no_oracle", False, "final_oracle" in json.dumps(candidates, sort_keys=True))
    check("snapshot.oracle_fields", [], snapshot.get("answer_oracle_fields"))
    check("snapshot.postexecution", False, snapshot.get("post_execution_measurements_used"))
    check("frontier.blocked_returned", False, _dict(frontier.get("claim_boundary")).get("blocked_multihop_classes_returned"))

    check("live.schema", LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION, live.get("schema_version"))
    check("live_status.status", "success", live_status.get("status"))
    check("live.status", "success", live.get("status"))
    check("live.error", None, live.get("error"))
    check("live.git_commit", expected_commit, _dict(live.get("git")).get("commit"))
    check("live.git_clean", True, _dict(live.get("git")).get("clean"))
    check("live.candidate_hash", candidates.get("candidate_set_sha256"), live.get("candidate_set_sha256"))
    check("live.snapshot_hash", snapshot.get("estimate_snapshot_sha256"), live.get("estimate_snapshot_sha256"))
    check("live.frontier_hash", frontier.get("frontier_sha256"), live.get("frontier_sha256"))
    expected_returned = _list(
        _dict(expected_frontier_payload).get("returned_semantic_plans")
    )
    check("results.count", len(expected_returned), len(results))
    for index, expected_selected in enumerate(expected_returned):
        result = _dict(results[index]) if index < len(results) else {}
        runtime = _dict(result.get("runtime_result"))
        query_id = str(expected_selected["query_id"])
        instance = expected_instances.get(query_id)
        prefix = f"result.{index}"
        for field in (
            "selection_rank",
            "semantic_class_id",
            "query_id",
            "plan_id",
            "physical_strategy",
            "semantic_deviation",
            "changed_slot_ids",
            "estimated_latency_ms",
            "estimated_resource_cost_units",
        ):
            check(f"{prefix}.{field}", expected_selected[field], result.get(field))
        check(f"{prefix}.exact_marker", True, result.get("exact_oracle_answer"))
        check(f"{prefix}.runtime_success", True, runtime.get("success"))
        check(f"{prefix}.remote_calls", 2, runtime.get("total_remote_calls"))
        check(
            f"{prefix}.exact_rows",
            instance["final_oracle"] if instance is not None else None,
            runtime.get("final_rows"),
        )
        check(
            f"{prefix}.row_count",
            len(instance["final_oracle"]) if instance is not None else None,
            result.get("expected_final_row_count"),
        )

    check("live.validation", True, _exact_validation(validation))
    check("live.manifest_validation", True, _exact_validation(live.get("validation")))
    summary = _dict(live.get("summary"))
    check("summary.declared_classes", 12, summary.get("declared_semantic_class_count"))
    check("summary.direct_classes", 4, summary.get("executable_direct_semantic_class_count"))
    check("summary.unavailable_classes", 8, summary.get("unavailable_multihop_semantic_class_count"))
    check("summary.physical_candidates", 8, summary.get("physical_candidate_count"))
    check("summary.physical_representatives", 4, summary.get("physical_representative_count"))
    check("summary.pareto", 4, summary.get("pareto_semantic_plan_count"))
    check("summary.epsilon", 3, summary.get("epsilon_frontier_semantic_plan_count"))
    check("summary.returned", 3, summary.get("returned_semantic_plan_count"))
    check("summary.physical_runs", 3, summary.get("physical_plan_run_count"))
    check("summary.remote_calls", 6, summary.get("total_remote_calls"))
    check("summary.final_rows", [11, 9, 11], summary.get("final_row_counts"))

    events = _list(invocations.get("events"))
    check("invocations.count", 6, invocations.get("total_tool_invocations"))
    check("invocations.events", 6, len(events))
    check(
        "invocations.backends",
        ["fuseki", "neo4j", "fuseki", "neo4j", "fuseki", "neo4j"],
        [str(_dict(item).get("backend_id")) for item in events],
    )
    check(
        "invocations.operations",
        ["execute"] * 6,
        [str(_dict(item).get("operation")) for item in events],
    )
    expected_artifact_ids: list[str] = []
    for selected_plan in expected_returned:
        query_id = selected_plan["query_id"]
        expected_artifact_ids.extend(
            [
                f"m15-f2c-{query_id}-fuseki-risk",
                f"m15-f2c-{query_id}-neo4j-bound",
            ]
        )
    check(
        "invocations.artifacts",
        expected_artifact_ids,
        [str(_dict(item).get("artifact_id")) for item in events],
    )
    check("invocations.automatic_retries", 0, invocations.get("automatic_retries"))
    check("live.selection_sealed", True, live.get("selection_sealed_before_oracle_access"))
    check("live.oracle_not_used", False, live.get("answer_oracle_used_for_selection"))
    check("live.oracle_posthoc", True, live.get("answer_oracle_used_for_post_execution_validation"))
    check("live.predictions_only", True, live.get("costs_are_controlled_predictions_not_observations"))
    check("live.multihop_not_executed", False, live.get("blocked_multihop_classes_executed"))
    check("live.memory_disabled", False, live.get("memory_enabled"))
    check("live.llm_calls", 0, live.get("llm_calls_made"))
    check("live.ontology_calls", 0, live.get("ontology_calls_made"))
    check("live.automatic_retries", 0, live.get("automatic_retries"))
    check("live.paper_result", False, live.get("paper_result"))
    runtime_root = service.get("runtime_root")
    check(
        "runtime.cleaned",
        True,
        isinstance(runtime_root, str) and not Path(runtime_root).exists(),
    )

    success = bool(checks) and all(item.passed for item in checks)
    return M15DirectFrontierNativeEvidenceAudit(
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
        audit = audit_m15_direct_frontier_native_run(
            run_root=arguments.run_root,
            expected_commit=arguments.expected_commit,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
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
