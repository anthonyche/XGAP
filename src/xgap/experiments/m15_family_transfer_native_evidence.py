"""Read-only audit for an F2C5 native family-transfer run."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.agent import MemoryRecord, MemoryScope
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_family_memory import (
    FAMILY_TRANSFER_MODEL_VERSION,
    build_m15_family_memory_context,
    build_m15_family_query_features,
)
from xgap.experiments.m15_live_family_transfer import (
    FAMILY_TRANSFER_METHOD_NAMESPACE,
    FAMILY_TRANSFER_TASK_STREAM_SCHEMA_VERSION,
    LIVE_FAMILY_TRANSFER_SCHEMA_VERSION,
    build_m15_family_transfer_task_stream,
)
from xgap.experiments.m15_native_services import (
    FAMILY_RUNTIME_COMPATIBILITY_SCHEMA_VERSION,
    FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION,
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


FAMILY_TRANSFER_AUDIT_SCHEMA_VERSION = (
    "m15-f2c5-native-family-transfer-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")
_MEMORY_KEY_PREFIX = "m15-f2c5-family-plan-observation"


def _jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class FamilyTransferEvidenceCheck:
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
class M15FamilyTransferNativeEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[FamilyTransferEvidenceCheck, ...]

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_TRANSFER_AUDIT_SCHEMA_VERSION,
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


def _read_memory(path: Path) -> tuple[list[dict[str, Any]], str]:
    if path.is_symlink() or not path.is_file():
        return [], "missing_or_nonregular"
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or any(not line.strip() for line in lines):
            return [], "empty_file_or_line"
        for line in lines:
            value = json.loads(line)
            if not isinstance(value, dict):
                return [], "line_is_not_object"
            records.append(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], f"invalid_jsonl:{exc}"
    return records, "ok"


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


def _runtime_identity(service_plan: Mapping[str, Any]) -> dict[str, Any]:
    services = sorted(
        (
            {
                "service_id": item.get("service_id"),
                "product": item.get("product"),
                "version": item.get("version"),
            }
            for item in (_dict(raw) for raw in _list(service_plan.get("services")))
        ),
        key=lambda item: str(item["service_id"]),
    )
    java = _dict(service_plan.get("java"))
    identity = {
        "schema_version": FAMILY_RUNTIME_COMPATIBILITY_SCHEMA_VERSION,
        "allocation_id": service_plan.get("allocation_id"),
        "filesystem_type": service_plan.get("filesystem_type"),
        "java_major": java.get("major"),
        "runtime_lock_sha256": service_plan.get("runtime_lock_sha256"),
        "staging_manifest_sha256": service_plan.get(
            "staging_manifest_sha256"
        ),
        "services": services,
        "reuse_scope": "same_native_service_allocation_only",
    }
    return {**identity, "runtime_compatibility_sha256": content_hash(identity)}


def _valid_content_hash(value: Mapping[str, Any], hash_field: str) -> bool:
    observed = value.get(hash_field)
    identity = {key: item for key, item in value.items() if key != hash_field}
    return isinstance(observed, str) and observed == content_hash(identity)


def audit_m15_family_transfer_native_run(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15FamilyTransferNativeEvidenceAudit:
    """Audit native family transfer, including its frozen memory boundary."""

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
    transfer_root = service_root / "family-transfer-run"
    bundle_root = run / "parameterized-workload-bundle"
    paths = {
        "outer_status": run / "run_status.json",
        "environment": run / "environment.txt",
        "workload_generation": run / "workload_generation.json",
        "service_status": service_root / "run_status.json",
        "service_manifest": service_root / "run_manifest.json",
        "health": service_root / "service_health.json",
        "shutdown": service_root / "service_shutdown.json",
        "runtime_compatibility": (
            service_root / "family_runtime_compatibility.json"
        ),
        "fixture_status": fixture_root / "run_status.json",
        "fixture_manifest": fixture_root / "run_manifest.json",
        "fixture_verification": fixture_root / "verification.json",
        "fixture_load_reports": fixture_root / "load_reports.json",
        "transfer_status": transfer_root / "run_status.json",
        "transfer_manifest": transfer_root / "run_manifest.json",
        "task_stream": transfer_root / "task_stream.json",
        "memory_context": transfer_root / "memory_context.json",
        "frozen_memory_view": transfer_root / "frozen_memory_view.json",
        "transfer_validation": transfer_root / "validation.json",
        "transfer_invocations": transfer_root / "backend_invocations.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        if key == "environment":
            loaded[key], states[key] = _read_environment(path)
        else:
            loaded[key], states[key] = _read_json(path)
    raw_memory, memory_state = _read_memory(
        transfer_root / "family_memory.jsonl"
    )

    checks: list[FamilyTransferEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            FamilyTransferEvidenceCheck(
                check_id,
                observed == expected,
                expected,
                observed,
            )
        )

    for key in paths:
        check(f"artifact.{key}", "ok", states[key])
    check("artifact.family_memory", "ok", memory_state)

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
    service_plan = _dict(service.get("service_plan"))
    health = _list(loaded.get("health"))
    shutdown = _list(loaded.get("shutdown"))
    runtime_compatibility = _dict(loaded.get("runtime_compatibility"))
    fixture_status = _dict(loaded.get("fixture_status"))
    fixture = _dict(loaded.get("fixture_manifest"))
    fixture_verification = _dict(loaded.get("fixture_verification"))
    fixture_loads = _dict(loaded.get("fixture_load_reports"))
    transfer_status = _dict(loaded.get("transfer_status"))
    transfer = _dict(loaded.get("transfer_manifest"))
    task_stream = _dict(loaded.get("task_stream"))
    memory_context = _dict(loaded.get("memory_context"))
    memory_view = _dict(loaded.get("frozen_memory_view"))
    transfer_validation = _dict(loaded.get("transfer_validation"))
    invocations = _dict(loaded.get("transfer_invocations"))
    bundle_manifest = dict(bundle.manifest) if bundle is not None else None

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.git_commit", expected_commit, outer.get("git_commit"))
    check(
        "outer.workload_mode",
        "parameterized_family_transfer",
        outer.get("workload_mode"),
    )
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("outer.cleanup_error", None, outer.get("cleanup_error"))
    check(
        "environment.run_version",
        "m15-f2c5-native-live-family-transfer-services-v1",
        environment.get("run_version"),
    )
    check("environment.git_commit", expected_commit, environment.get("git_commit"))
    check(
        "environment.slurm_job_id",
        outer.get("slurm_job_id"),
        environment.get("slurm_job_id"),
    )
    check(
        "environment.workload_mode",
        "parameterized_family_transfer",
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
        FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION,
        service.get("schema_version"),
    )
    check("service_status.status", "success", service_status.get("status"))
    check("service.status", "success", service.get("status"))
    check("service.error", None, service.get("error"))
    check(
        "service.workload_mode",
        "parameterized_family_transfer",
        service.get("workload_mode"),
    )
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
        "service.allocation",
        outer.get("slurm_job_id"),
        service_plan.get("allocation_id"),
    )
    check(
        "service.filesystem",
        environment.get("runtime_filesystem_type"),
        service_plan.get("filesystem_type"),
    )
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

    expected_runtime = _runtime_identity(service_plan)
    check("runtime_compatibility.identity", expected_runtime, runtime_compatibility)
    check(
        "runtime_compatibility.hash",
        True,
        _valid_content_hash(
            runtime_compatibility,
            "runtime_compatibility_sha256",
        ),
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
        "transfer.schema",
        LIVE_FAMILY_TRANSFER_SCHEMA_VERSION,
        transfer.get("schema_version"),
    )
    check("transfer_status.status", "success", transfer_status.get("status"))
    check("transfer.status", "success", transfer.get("status"))
    check("transfer.error", None, transfer.get("error"))
    check("transfer.bundle", bundle_manifest, transfer.get("workload_bundle"))
    check("transfer.task_stream_file", task_stream, transfer.get("task_stream"))
    check("transfer.memory_context_file", memory_context, transfer.get("memory_context"))
    check("transfer.memory_view_file", memory_view, transfer.get("frozen_memory_view"))
    check("transfer.validation", True, _exact_validation(transfer.get("validation")))
    check("transfer.validation_file", transfer_validation, transfer.get("validation"))
    check("transfer.oracle_selection", False, transfer.get("answer_oracle_used_for_feature_or_selection"))
    check("transfer.oracle_validation", True, transfer.get("answer_oracle_used_for_post_execution_validation"))
    check("transfer.memory_enabled", True, transfer.get("memory_enabled"))
    check("transfer.memory_scope", "same_method_same_family_same_runtime", transfer.get("memory_transfer_scope"))
    check("transfer.cross_family", False, transfer.get("cross_family_transfer_enabled"))
    check("transfer.shadow_enabled", True, transfer.get("evaluation_shadow_enabled"))
    check("transfer.shadow_influence", False, transfer.get("evaluation_shadow_influenced_selection"))
    check("transfer.automatic_retries", 0, transfer.get("automatic_retries"))
    check("transfer.llm_calls", 0, transfer.get("llm_calls_made"))
    check("transfer.ontology_calls", 0, transfer.get("ontology_calls_made"))
    check("transfer.paper_result", False, transfer.get("paper_result"))
    check("transfer.git_commit", expected_commit, _dict(transfer.get("git")).get("commit"))
    check("transfer.git_clean", True, _dict(transfer.get("git")).get("clean"))
    check(
        "transfer.evidence_class",
        "live_family_local_transfer_development_gate",
        transfer.get("evidence_class"),
    )

    expected_context = None
    expected_context_object = None
    expected_stream = None
    if bundle is not None:
        expected_stream = build_m15_family_transfer_task_stream(bundle)
        expected_context_object = build_m15_family_memory_context(
            bundle,
            method_namespace=FAMILY_TRANSFER_METHOD_NAMESPACE,
            runtime_compatibility_sha256=expected_runtime[
                "runtime_compatibility_sha256"
            ],
        )
        expected_context = expected_context_object.to_dict()
    check(
        "task_stream.schema",
        FAMILY_TRANSFER_TASK_STREAM_SCHEMA_VERSION,
        task_stream.get("schema_version"),
    )
    check("task_stream.rebuilt", expected_stream, task_stream)
    check(
        "task_stream.method_namespace",
        FAMILY_TRANSFER_METHOD_NAMESPACE,
        task_stream.get("method_namespace"),
    )
    check("memory_context.rebuilt", expected_context, memory_context)
    check(
        "memory_context.runtime",
        runtime_compatibility.get("runtime_compatibility_sha256"),
        memory_context.get("runtime_compatibility_sha256"),
    )

    tasks = [_dict(item) for item in _list(task_stream.get("tasks"))]
    seed_tasks = [item for item in tasks if item.get("split_role") == "seed"]
    heldout_tasks = [
        item for item in tasks if item.get("split_role") == "heldout_instance"
    ]
    seed_ids = [str(item.get("task_id")) for item in seed_tasks]
    check("task_stream.order", list(range(1, 7)), [item.get("sequence_index") for item in tasks])
    check("task_stream.seed_count", 4, len(seed_tasks))
    check("task_stream.heldout_count", 2, len(heldout_tasks))
    check(
        "task_stream.frozen_predecessors",
        True,
        all(
            _dict(task.get("memory")).get("eligible_predecessor_task_ids")
            == seed_ids
            for task in heldout_tasks
        ),
    )

    parsed_records: list[MemoryRecord] = []
    for index, raw_record in enumerate(raw_memory, start=1):
        try:
            record = MemoryRecord.from_dict(raw_record)
            parsed_records.append(record)
            valid = True
        except ValueError:
            record = None
            valid = False
        check(f"memory.record.{index}.typed", True, valid)
        if record is None:
            continue
        value = _dict(record.value)
        task_id = seed_ids[index - 1] if index <= len(seed_ids) else None
        check(f"memory.record.{index}.scope", MemoryScope.EXECUTION, record.scope)
        check(
            f"memory.record.{index}.key",
            (
                f"{_MEMORY_KEY_PREFIX}/{memory_context.get('method_namespace')}/"
                f"{memory_context.get('context_sha256')}/{task_id}"
            ),
            record.key,
        )
        check(f"memory.record.{index}.task", task_id, value.get("task_id"))
        check(f"memory.record.{index}.split", "seed", value.get("split_role"))
        check(f"memory.record.{index}.exact", True, value.get("exact_answer"))
        check(f"memory.record.{index}.success", True, value.get("execution_success"))
        check(f"memory.record.{index}.no_rows", False, value.get("answer_rows_stored"))
        check(f"memory.record.{index}.hash", True, _valid_content_hash(value, "observation_sha256"))
        check(f"memory.record.{index}.version", value.get("observation_sha256"), record.version)
        check(
            f"memory.record.{index}.source",
            f"{task_id}/post-execution-exact-validation",
            record.source,
        )
        check(f"memory.record.{index}.confidence", 1.0, record.confidence)
        check(f"memory.record.{index}.expiry", None, record.expires_at)
        check(
            f"memory.record.{index}.no_answer_payload",
            False,
            "final_rows" in json.dumps(raw_record, sort_keys=True),
        )
    check("memory.record_count", 4, len(parsed_records))

    memory_values = [_dict(item.value) for item in parsed_records]
    view_identity = {
        key: value
        for key, value in memory_view.items()
        if key not in {"view_sha256", "observations"}
    }
    check("memory_view.hash", True, memory_view.get("view_sha256") == content_hash(view_identity))
    check("memory_view.context", memory_context.get("context_sha256"), memory_view.get("context_sha256"))
    check("memory_view.eligible", seed_ids, memory_view.get("eligible_task_ids"))
    check(
        "memory_view.current_sequence",
        heldout_tasks[0].get("sequence_index") if heldout_tasks else None,
        memory_view.get("current_sequence_index"),
    )
    check("memory_view.observations", memory_values, memory_view.get("observations"))
    check("memory_view.no_current_write", False, memory_view.get("writes_visible_from_current_task"))

    seed_results = _dict(transfer.get("seed_results"))
    heldout_results = _dict(transfer.get("heldout_results"))
    if bundle is not None:
        for task in seed_tasks:
            query_id = str(task.get("query_id"))
            expected_rows = load_m15_parameterized_instance(bundle, query_id)["final_oracle"]
            result_summary = _dict(seed_results.get(query_id))
            check(f"seed.{query_id}.task", task, result_summary.get("task"))
            assert expected_context_object is not None
            expected_features = build_m15_family_query_features(
                bundle,
                query_id=query_id,
                context=expected_context_object,
            ).to_dict()
            check(f"seed.{query_id}.features", expected_features, result_summary.get("features"))
            for strategy in _STRATEGIES:
                result_data, result_state = _read_json(
                    transfer_root / "tasks" / query_id / f"seed-{strategy}.json"
                )
                result = _dict(result_data)
                check(f"seed.{query_id}.{strategy}.artifact", "ok", result_state)
                check(f"seed.{query_id}.{strategy}.success", True, result.get("success"))
                check(f"seed.{query_id}.{strategy}.exact_rows", expected_rows, result.get("final_rows"))
                check(f"seed.{query_id}.{strategy}.remote_calls", 2, result.get("total_remote_calls"))
                observation = next(
                    (
                        value
                        for value in memory_values
                        if value.get("task_id") == task.get("task_id")
                    ),
                    {},
                )
                memory_outcome = next(
                    (
                        _dict(item)
                        for item in _list(observation.get("outcomes"))
                        if _dict(item).get("strategy_id") == strategy
                    ),
                    {},
                )
                expected_outcome = {
                    "strategy_id": strategy,
                    "plan_id": result.get("plan_id"),
                    "elapsed_ms": result.get("elapsed_ms"),
                    "total_bytes_moved": result.get("total_bytes_moved"),
                    "total_remote_calls": result.get("total_remote_calls"),
                }
                check(
                    f"seed.{query_id}.{strategy}.memory_outcome",
                    expected_outcome,
                    memory_outcome,
                )

        for task in heldout_tasks:
            query_id = str(task.get("query_id"))
            expected_rows = load_m15_parameterized_instance(bundle, query_id)["final_oracle"]
            heldout = _dict(heldout_results.get(query_id))
            selection_data, selection_state = _read_json(
                transfer_root / "tasks" / query_id / "selection.json"
            )
            selected_data, selected_state = _read_json(
                transfer_root / "tasks" / query_id / "selected_run.json"
            )
            selection = _dict(selection_data)
            selected_result = _dict(selected_data)
            check(f"heldout.{query_id}.selection_artifact", "ok", selection_state)
            check(f"heldout.{query_id}.selected_artifact", "ok", selected_state)
            check(f"heldout.{query_id}.selection_file", selection, heldout.get("selection"))
            check(f"heldout.{query_id}.selected_file", selected_result, heldout.get("selected_run"))
            check(f"heldout.{query_id}.selection_hash", True, _valid_content_hash(selection, "selection_sha256"))
            check(f"heldout.{query_id}.oracle_inputs", [], selection.get("oracle_inputs"))
            check(
                f"heldout.{query_id}.model_version",
                FAMILY_TRANSFER_MODEL_VERSION,
                selection.get("model_version"),
            )
            check(
                f"heldout.{query_id}.selection_mode",
                "family_local_knn",
                selection.get("selection_mode"),
            )
            check(f"heldout.{query_id}.memory_view", memory_view.get("view_sha256"), selection.get("memory_view_sha256"))
            check(f"heldout.{query_id}.exact_rows", expected_rows, selected_result.get("final_rows"))
            check(f"heldout.{query_id}.success", True, selected_result.get("success"))
            check(f"heldout.{query_id}.remote_calls", 2, selected_result.get("total_remote_calls"))
            check(f"heldout.{query_id}.no_write", False, heldout.get("memory_write_after_evaluation"))
            check(f"heldout.{query_id}.shadow_influence", False, heldout.get("evaluation_shadow_influenced_selection"))
            shadows = _dict(heldout.get("evaluation_shadow_runs"))
            check(f"heldout.{query_id}.shadow_count", 1, len(shadows))
            for strategy, shadow_value in shadows.items():
                shadow_data, shadow_state = _read_json(
                    transfer_root / "tasks" / query_id / f"shadow-{strategy}.json"
                )
                shadow = _dict(shadow_data)
                check(f"heldout.{query_id}.shadow_artifact", "ok", shadow_state)
                check(f"heldout.{query_id}.shadow_file", shadow, shadow_value)
                check(f"heldout.{query_id}.shadow_success", True, shadow.get("success"))
                check(f"heldout.{query_id}.shadow_exact", expected_rows, shadow.get("final_rows"))

    summary = _dict(transfer.get("summary"))
    expected_summary = {
        "seed_task_count": 4,
        "heldout_task_count": 2,
        "memory_commit_count": 4,
        "seed_plan_runs": 8,
        "heldout_online_plan_runs": 2,
        "evaluation_shadow_plan_runs": 2,
        "online_remote_calls": 4,
        "calibration_remote_calls": 16,
        "evaluation_shadow_remote_calls": 4,
        "observed_selection_count": 2,
    }
    for key, value in expected_summary.items():
        check(f"summary.{key}", value, summary.get(key))
    selected_winners = summary.get("selected_observed_winner_count")
    check("summary.selected_winner_range", True, isinstance(selected_winners, int) and 0 <= selected_winners <= 2)

    events_by_execution = _dict(invocations.get("events_by_execution"))
    all_events = [
        _dict(event)
        for events in events_by_execution.values()
        for event in _list(events)
    ]
    check("invocations.execution_count", 12, len(events_by_execution))
    check("invocations.total", 24, invocations.get("total_tool_invocations"))
    check("invocations.automatic_retries", 0, invocations.get("automatic_retries"))
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
    roles = [event.get("execution_role") for event in all_events]
    check("invocations.calibration_calls", 16, roles.count("memory_seed_measurement"))
    check("invocations.online_calls", 4, roles.count("online_selected_plan"))
    check("invocations.shadow_calls", 4, roles.count("evaluation_shadow_after_selection"))

    return M15FamilyTransferNativeEvidenceAudit(
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
        audit = audit_m15_family_transfer_native_run(
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
