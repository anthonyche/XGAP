"""Read-only audit for an F2C4 native parameterized-stream run."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.m15_live_parameterized_stream import (
    LIVE_PARAMETERIZED_STREAM_SCHEMA_VERSION,
    TASK_STREAM_SCHEMA_VERSION,
)
from xgap.experiments.m15_native_services import (
    PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION,
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


PARAMETERIZED_AUDIT_SCHEMA_VERSION = "m15-f2c4-native-evidence-audit-v1"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")


def _jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class ParameterizedEvidenceCheck:
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
class M15ParameterizedNativeEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[ParameterizedEvidenceCheck, ...]

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PARAMETERIZED_AUDIT_SCHEMA_VERSION,
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


def audit_m15_parameterized_native_run(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15ParameterizedNativeEvidenceAudit:
    """Audit the complete F2C4 artifact graph without changing the run tree."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    run = selected.resolve()
    if not run.is_dir():
        raise ValueError("run_root must be a real directory")

    service_root = run / "native-service-run"
    fixture_root = service_root / "parameterized-fixture-load"
    stream_root = service_root / "parameterized-stream-run"
    bundle_root = run / "parameterized-workload-bundle"
    paths = {
        "outer_status": run / "run_status.json",
        "environment": run / "environment.txt",
        "workload_generation": run / "workload_generation.json",
        "service_status": service_root / "run_status.json",
        "service_manifest": service_root / "run_manifest.json",
        "health": service_root / "service_health.json",
        "shutdown": service_root / "service_shutdown.json",
        "fixture_status": fixture_root / "run_status.json",
        "fixture_manifest": fixture_root / "run_manifest.json",
        "fixture_verification": fixture_root / "verification.json",
        "fixture_load_reports": fixture_root / "load_reports.json",
        "stream_status": stream_root / "run_status.json",
        "stream_manifest": stream_root / "run_manifest.json",
        "task_stream": stream_root / "task_stream.json",
        "stream_validation": stream_root / "validation.json",
        "stream_invocations": stream_root / "backend_invocations.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        else:
            loaded[key], states[key] = _read_json(path)

    checks: list[ParameterizedEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            ParameterizedEvidenceCheck(
                check_id,
                observed == expected,
                expected,
                observed,
            )
        )

    for key in paths:
        check(f"artifact.{key}", "ok", states[key])

    bundle = None
    try:
        bundle = load_m15_parameterized_workload_bundle(bundle_root)
        check("bundle.integrity", True, True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        check("bundle.integrity", True, f"invalid:{exc}")

    outer = _dict(loaded.get("outer_status"))
    environment = _dict(loaded.get("environment"))
    generation = _dict(loaded.get("workload_generation"))
    service_status = _dict(loaded.get("service_status"))
    service = _dict(loaded.get("service_manifest"))
    health = _list(loaded.get("health"))
    shutdown = _list(loaded.get("shutdown"))
    fixture_status = _dict(loaded.get("fixture_status"))
    fixture = _dict(loaded.get("fixture_manifest"))
    fixture_verification = _dict(loaded.get("fixture_verification"))
    fixture_loads = _dict(loaded.get("fixture_load_reports"))
    stream_status = _dict(loaded.get("stream_status"))
    stream = _dict(loaded.get("stream_manifest"))
    task_stream = _dict(loaded.get("task_stream"))
    stream_validation = _dict(loaded.get("stream_validation"))
    invocations = _dict(loaded.get("stream_invocations"))
    bundle_manifest = dict(bundle.manifest) if bundle is not None else None

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check("outer.workload_mode", "parameterized_stream", outer.get("workload_mode"))
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))
    check(
        "environment.run_version",
        "m15-f2c4-native-live-parameterized-stream-services-v1",
        environment.get("run_version"),
    )
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check(
        "environment.workload_mode",
        "parameterized_stream",
        environment.get("workload_mode"),
    )
    check("environment.loopback_only", "true", environment.get("loopback_only"))
    check("environment.automatic_retries", "0", environment.get("automatic_retries"))

    check("generation.status", "success", generation.get("status"))
    check(
        "generation.root",
        str(bundle.root) if bundle is not None else None,
        generation.get("root"),
    )
    if bundle is not None:
        for key, value in bundle.manifest.items():
            check(f"generation.manifest.{key}", value, generation.get(key))

    check(
        "service.schema",
        PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION,
        service.get("schema_version"),
    )
    check("service_status.status", "success", service_status.get("status"))
    check("service.status", "success", service.get("status"))
    check("service.error", None, service.get("error"))
    check("service.workload_mode", "parameterized_stream", service.get("workload_mode"))
    check("service.workload_bundle", None, service.get("workload_bundle"))
    check(
        "service.parameterized_bundle",
        bundle_manifest,
        service.get("parameterized_workload_bundle"),
    )
    check("service.automatic_retries", 0, service.get("automatic_retries"))
    check("service.restarts", 0, service.get("service_restarts"))
    check("service.public_ports", False, service.get("public_ports"))
    check("service.credentials", False, service.get("credentials_persisted"))
    check(
        "health.success",
        True,
        len(health) == 2
        and [str(_dict(item).get("service_id")) for item in health]
        == ["neo4j", "fuseki"]
        and all(_dict(item).get("success") is True for item in health),
    )
    check(
        "shutdown.clean_reverse_order",
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
    check("fixture.bundle", bundle_manifest, fixture.get("workload_bundle"))
    check(
        "fixture.loads",
        True,
        set(fixture_loads) == {"neo4j", "fuseki"}
        and all(_dict(item).get("success") is True for item in fixture_loads.values()),
    )
    fixture_summary = _dict(fixture.get("verification"))
    check("fixture.query_count", 6, fixture_summary.get("query_instance_count"))
    check("fixture.backend_query_count", 12, fixture_summary.get("backend_query_count"))
    check("fixture.verification_passed", True, fixture_summary.get("passed"))
    check(
        "fixture.verification_checks",
        True,
        len(_dict(fixture_summary.get("checks"))) == 24
        and all(_dict(fixture_summary.get("checks")).values()),
    )
    check(
        "fixture.verification_file",
        True,
        _exact_validation(fixture_verification.get("validation")),
    )
    check("fixture.automatic_retries", 0, fixture.get("automatic_retries"))
    check("fixture.git_commit", expected_commit, _dict(fixture.get("git")).get("commit"))
    check("fixture.git_clean", True, _dict(fixture.get("git")).get("clean"))

    check(
        "stream.schema",
        LIVE_PARAMETERIZED_STREAM_SCHEMA_VERSION,
        stream.get("schema_version"),
    )
    check("stream_status.status", "success", stream_status.get("status"))
    check("stream.status", "success", stream.get("status"))
    check("stream.error", None, stream.get("error"))
    check("stream.bundle", bundle_manifest, stream.get("workload_bundle"))
    check("stream.task_stream_file", task_stream, stream.get("task_stream"))
    check("stream.validation", True, _exact_validation(stream.get("validation")))
    check("stream.validation_file", stream_validation, stream.get("validation"))
    check("stream.oracle_plan_construction", False, stream.get("answer_oracle_used_for_plan_construction"))
    check("stream.memory", False, stream.get("memory_enabled"))
    check("stream.llm_calls", 0, stream.get("llm_calls_made"))
    check("stream.ontology_calls", 0, stream.get("ontology_calls_made"))
    check("stream.automatic_retries", 0, stream.get("automatic_retries"))
    check("stream.paper_result", False, stream.get("paper_result"))
    check("stream.git_commit", expected_commit, _dict(stream.get("git")).get("commit"))
    check("stream.git_clean", True, _dict(stream.get("git")).get("clean"))
    check("task_stream.schema", TASK_STREAM_SCHEMA_VERSION, task_stream.get("schema_version"))
    check("task_stream.count", 6, task_stream.get("task_count"))
    check("task_stream.automatic_retries", 0, task_stream.get("automatic_retries"))

    summary = _dict(stream.get("summary"))
    check("stream.summary.instances", 6, summary.get("query_instance_count"))
    check("stream.summary.strategy_runs", 12, summary.get("strategy_run_count"))
    check("stream.summary.exact_answers", 12, summary.get("exact_answer_count"))
    check("stream.summary.remote_calls", 24, summary.get("total_remote_calls"))
    moved = summary.get("total_bytes_moved")
    check("stream.summary.positive_bytes", True, isinstance(moved, int) and moved > 0)

    phases = _dict(invocations.get("events_by_task_and_strategy"))
    check("invocations.phase_count", 12, len(phases))
    check("invocations.total", 24, invocations.get("total_tool_invocations"))
    check("invocations.automatic_retries", 0, invocations.get("automatic_retries"))
    all_events = [
        _dict(event) for events in phases.values() for event in _list(events)
    ]
    check(
        "invocations.all_successful_execute",
        True,
        len(all_events) == 24
        and all(
            event.get("status") == "success"
            and event.get("operation") == "execute"
            for event in all_events
        ),
    )

    tasks = _list(task_stream.get("tasks"))
    check(
        "task_stream.order",
        list(range(1, 7)),
        [_dict(task).get("sequence_index") for task in tasks],
    )
    check(
        "task_stream.split_roles",
        ["seed", "seed", "seed", "seed", "heldout_instance", "heldout_instance"],
        [_dict(task).get("split_role") for task in tasks],
    )
    if bundle is not None:
        expected_query_ids = list(bundle.instance_ids())
        check(
            "task_stream.query_ids",
            expected_query_ids,
            [_dict(task).get("query_id") for task in tasks],
        )
        for task in tasks:
            task = _dict(task)
            query_id = str(task.get("query_id"))
            instance = load_m15_parameterized_instance(bundle, query_id)
            expected_rows = instance["final_oracle"]
            candidate_path = stream_root / "tasks" / query_id / "candidate_plans.json"
            candidate_data, candidate_state = _read_json(candidate_path)
            check(f"task.{query_id}.candidate_artifact", "ok", candidate_state)
            candidates = _dict(candidate_data)
            plans = [_dict(item) for item in _list(candidates.get("plans"))]
            expected_key = (
                f"{bundle.manifest['family_compatibility_sha256']}:"
                f"{instance['record']['query_instance_sha256']}:exact"
            )
            check(
                f"task.{query_id}.semantic_key",
                expected_key,
                candidates.get("semantic_equivalence_key"),
            )
            check(
                f"task.{query_id}.strategies",
                list(_STRATEGIES),
                [_dict(plan.get("metadata")).get("physical_strategy") for plan in plans],
            )
            check(
                f"task.{query_id}.zero_deviation",
                True,
                len(plans) == 2
                and all(
                    _dict(plan.get("metadata")).get("semantic_deviation") == 0
                    for plan in plans
                ),
            )
            for strategy in _STRATEGIES:
                result_path = stream_root / "tasks" / query_id / f"{strategy}.json"
                result_data, result_state = _read_json(result_path)
                check(
                    f"task.{query_id}.{strategy}.artifact",
                    "ok",
                    result_state,
                )
                result = _dict(result_data)
                check(f"task.{query_id}.{strategy}.success", True, result.get("success"))
                check(
                    f"task.{query_id}.{strategy}.exact_rows",
                    expected_rows,
                    result.get("final_rows"),
                )
                check(
                    f"task.{query_id}.{strategy}.remote_calls",
                    2,
                    result.get("total_remote_calls"),
                )

    return M15ParameterizedNativeEvidenceAudit(
        success=all(item.passed for item in checks),
        run_root=run,
        expected_commit=expected_commit,
        checks=tuple(checks),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        audit = audit_m15_parameterized_native_run(
            run_root=args.run_root,
            expected_commit=args.expected_commit,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    payload = json.dumps(audit.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
