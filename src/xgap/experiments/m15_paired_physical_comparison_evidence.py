"""Read-only reconstruction audit for one native F2C13B paired run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_workload import (
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_paired_physical_comparison import (
    FAMILY_SELECTION_SEAL_SCHEMA_VERSION,
    LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION,
    PAIRED_PHYSICAL_ANALYSIS_SCHEMA_VERSION,
    PROFILE_SELECTION_SEAL_SCHEMA_VERSION,
    _candidate_sets,
    _task_index,
    _training_observations,
    analyze_m15_paired_physical_comparison,
)
from xgap.experiments.m15_native_services import (
    PAIRED_PHYSICAL_PREFLIGHT_SCHEMA_VERSION,
    PAIRED_PHYSICAL_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_paired_physical_comparison import (
    PAIRED_PHYSICAL_SCHEDULE_SCHEMA_VERSION,
    compile_m15_paired_physical_comparison_schedule,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)


PAIRED_PHYSICAL_AUDIT_SCHEMA_VERSION = (
    "m15-f2c13b-paired-physical-comparison-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PHASES = (
    "training_measurement",
    "current_query_profile_acquisition",
    "paired_selected_execution",
    "postselection_shadow_evaluation",
)


@dataclass(frozen=True)
class PairedPhysicalEvidenceCheck:
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
class M15PairedPhysicalEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[PairedPhysicalEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAIRED_PHYSICAL_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
        }


def _read_json(path: Path) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"


def _dict(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _without_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


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


def _file_map(root: Path, pattern: str) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for path in sorted(root.glob(pattern)):
        value, state = _read_json(path)
        if state == "ok" and isinstance(value, Mapping):
            records[path.stem] = value
    return records


def _exact_validation(value: object) -> bool:
    validation = _dict(value)
    checks = validation.get("checks")
    return (
        validation.get("passed") is True
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(item is True for item in checks.values())
    )


def _record_hash_checks(
    check: Any,
    *,
    phase: str,
    records: Sequence[object],
    identity_field: str,
    excluded_fields: Sequence[str] = (),
) -> None:
    for index, value in enumerate(records, start=1):
        record = _dict(value)
        check(
            f"schedule.{phase}.{index}.hash",
            content_hash(
                {
                    key: item
                    for key, item in record.items()
                    if key != identity_field and key not in excluded_fields
                }
            ),
            record.get(identity_field),
        )


def audit_m15_paired_physical_comparison(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15PairedPhysicalEvidenceAudit:
    """Rebuild schedules, both selections, and all reported paired metrics."""

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
    nested_live = service / "paired-physical-comparison-run"
    live = nested_live if nested_live.is_dir() else root
    native_outer = live != root

    paths = {
        "status": live / "run_status.json",
        "manifest": live / "run_manifest.json",
        "schedule": live / "paired_schedule.json",
        "candidate_seal": live / "candidate_seal.json",
        "training_observations": live / "training/training_observations.json",
        "training_memory": live / "training/training_memory_view.json",
        "prediction_suite": live / "family-selection/prediction_suite.json",
        "family_seal": live / "family_selection_seal.json",
        "estimate_source": live / "profile/profile_cost_estimates.json",
        "profile_seal": live / "profile_selection_seal.json",
        "acquisition_validation": live / "profile/acquisition_validation.json",
        "analysis": live / "analysis.json",
        "validation": live / "validation.json",
        "invocations": live / "backend_invocations.json",
    }
    if native_outer:
        paths.update(
            {
                "outer_status": root / "run_status.json",
                "service_status": service / "run_status.json",
                "service_manifest": service / "run_manifest.json",
                "preflight_schedule": (
                    service / "paired-physical-preflight/paired_schedule.json"
                ),
                "preflight_manifest": (
                    service / "paired-physical-preflight/preflight_manifest.json"
                ),
                "runtime_compatibility": (
                    service / "family_runtime_compatibility.json"
                ),
            }
        )
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for name, path in paths.items():
        loaded[name], states[name] = _read_json(path)

    checks: list[PairedPhysicalEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            PairedPhysicalEvidenceCheck(
                check_id=check_id,
                passed=expected == observed,
                expected=expected,
                observed=observed,
            )
        )

    for name, state in states.items():
        check(f"artifact.{name}", "ok", state)

    status = _dict(loaded.get("status"))
    manifest = _dict(loaded.get("manifest"))
    schedule = _dict(loaded.get("schedule"))
    candidate_seal = _dict(loaded.get("candidate_seal"))
    family_seal = _dict(loaded.get("family_seal"))
    estimate_source = _dict(loaded.get("estimate_source"))
    profile_seal = _dict(loaded.get("profile_seal"))
    analysis = _dict(loaded.get("analysis"))
    validation = _dict(loaded.get("validation"))
    invocations = _dict(loaded.get("invocations"))

    check("status.schema", LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION, status.get("schema_version"))
    check("status.success", "success", status.get("status"))
    check("status.error", None, status.get("error"))
    check("manifest.schema", LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION, manifest.get("schema_version"))
    check("manifest.status", "success", manifest.get("status"))
    check("manifest.commit", expected_commit, _dict(manifest.get("git")).get("commit"))
    check("manifest.clean", True, _dict(manifest.get("git")).get("clean"))
    check("manifest.validation", True, _exact_validation(manifest.get("validation")))
    check("validation.exact", True, _exact_validation(validation))
    check("manifest.retries", 0, manifest.get("automatic_retries"))
    check("manifest.llm_calls", 0, manifest.get("llm_calls_made"))
    check("manifest.ontology_calls", 0, manifest.get("ontology_service_calls_made"))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    check("manifest.confirmatory", False, manifest.get("confirmatory_statistics"))
    check("manifest.shadow_selection", False, manifest.get("shadow_influenced_selection"))

    direct = None
    base_bundle: M15ParameterizedWorkloadBundle | None = None
    predictor: Path | None = None
    if native_outer:
        outer_status = _dict(loaded.get("outer_status"))
        service_status = _dict(loaded.get("service_status"))
        service_manifest = _dict(loaded.get("service_manifest"))
        preflight = _dict(loaded.get("preflight_manifest"))
        check("outer.status", "success", outer_status.get("status"))
        check("outer.exit_code", 0, outer_status.get("exit_code"))
        check("outer.commit", expected_commit, outer_status.get("git_commit"))
        check("outer.mode", "paired_physical_comparison", outer_status.get("workload_mode"))
        check("outer.runtime_removed", True, outer_status.get("runtime_removed"))
        check("service.status", "success", service_status.get("status"))
        check("service.schema", PAIRED_PHYSICAL_SERVICE_RUN_SCHEMA_VERSION, service_status.get("schema_version"))
        check("service.manifest_schema", PAIRED_PHYSICAL_SERVICE_RUN_SCHEMA_VERSION, service_manifest.get("schema_version"))
        check("service.manifest_status", "success", service_manifest.get("status"))
        check("preflight.schema", PAIRED_PHYSICAL_PREFLIGHT_SCHEMA_VERSION, preflight.get("schema_version"))
        check("preflight.sealed", True, preflight.get("sealed_before_service_start"))
        check("preflight.calls", 0, preflight.get("backend_calls_before_seal"))
        check("preflight.oracle_closed", False, preflight.get("answer_oracle_opened_before_seal"))
        check("preflight.retries", 0, preflight.get("automatic_retries"))
        check("preflight.paper_result", False, preflight.get("paper_result"))

        inputs = {
            "base": root / "direct-family-base-workload-bundle",
            "direct": root / "direct-semantic-workload-bundle",
            "catalog": root / "semantic_catalog.json",
            "mapping": root / "predicate_mapping.json",
            "paired": root / "paired_physical_protocol.json",
            "family": root / "direct_family_pilot_protocol.json",
            "predictor": root / "direct_family_predictor_policy.json",
            "profile": root / "current_query_profile_protocol.json",
        }
        for name, path in inputs.items():
            expected = path.is_dir() if name in {"base", "direct"} else path.is_file()
            check(f"input.{name}", True, expected)
        try:
            base_bundle = load_m15_parameterized_workload_bundle(inputs["base"])
            direct = load_m15_direct_semantic_workload_bundle(
                inputs["direct"],
                base_bundle=base_bundle,
                catalog=inputs["catalog"],
                mapping=inputs["mapping"],
            )
            reconstructed = compile_m15_paired_physical_comparison_schedule(
                workload=direct,
                protocol=inputs["paired"],
                family_protocol=inputs["family"],
                predictor_policy=inputs["predictor"],
                profile_protocol=inputs["profile"],
            ).to_dict()
            predictor = inputs["predictor"]
            check("schedule.source_reconstruction", reconstructed, schedule)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            check("schedule.source_reconstruction", "valid", f"invalid:{exc}")

        runtime = _dict(loaded.get("runtime_compatibility"))
        check(
            "runtime.hash",
            content_hash(_without_hash(runtime, "runtime_compatibility_sha256")),
            runtime.get("runtime_compatibility_sha256"),
        )
        check("runtime.scope", "same_native_service_allocation_only", runtime.get("reuse_scope"))
        check("runtime.manifest", runtime.get("runtime_compatibility_sha256"), manifest.get("runtime_compatibility_sha256"))

    check("schedule.schema", PAIRED_PHYSICAL_SCHEDULE_SCHEMA_VERSION, schedule.get("schema_version"))
    check("schedule.hash", content_hash(_without_hash(schedule, "schedule_sha256")), schedule.get("schedule_sha256"))
    check("schedule.manifest_hash", schedule.get("schedule_sha256"), manifest.get("schedule_sha256"))
    if native_outer:
        preflight = _dict(loaded.get("preflight_manifest"))
        check("preflight.schedule_exact", schedule, loaded.get("preflight_schedule"))
        check("preflight.schedule_hash", schedule.get("schedule_sha256"), preflight.get("schedule_sha256"))
        check("preflight.counts", schedule.get("counts"), preflight.get("expected_counts"))
    expected_counts = {
        "training_plan_runs": 144,
        "profile_acquisition_plan_runs": 20,
        "paired_selected_plan_runs": 20,
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 264,
        "training_backend_calls": 288,
        "profile_acquisition_backend_calls": 40,
        "paired_selected_backend_calls": 40,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 528,
    }
    check("schedule.counts", expected_counts, schedule.get("counts"))
    check("schedule.external_calls", 0, schedule.get("external_calls_made"))
    check("schedule.retries", 0, schedule.get("automatic_retries"))
    check("schedule.paper_result", False, schedule.get("paper_result"))

    training_schedule = _list(schedule.get("training_runs"))
    family_slots = _list(schedule.get("family_memory_selection_slots"))
    acquisition_schedule = _list(schedule.get("profile_acquisition_runs"))
    profile_slots = _list(schedule.get("profile_selection_slots"))
    selected_slots = _list(schedule.get("paired_selected_execution_slots"))
    shadow_schedule = _list(schedule.get("shadow_runs"))
    for phase, records, field in (
        ("training", training_schedule, "run_sha256"),
        ("family_selection", family_slots, "slot_sha256"),
        ("profile", acquisition_schedule, "run_sha256"),
        ("profile_selection", profile_slots, "slot_sha256"),
        ("selected", selected_slots, "slot_sha256"),
        ("shadow", shadow_schedule, "run_sha256"),
    ):
        _record_hash_checks(
            check,
            phase=phase,
            records=records,
            identity_field=field,
            excluded_fields=("run_id",) if phase == "training" else (),
        )

    training = _file_map(live / "training/runs", "*.json")
    acquisitions = _file_map(live / "profile/acquisition/runs", "*.json")
    family_selected_files = _file_map(live / "selected/family_memory", "*.json")
    profile_selected_files = _file_map(
        live / "selected/current_query_dual_profile", "*.json"
    )
    shadows = _file_map(live / "shadow/runs", "*.json")
    check("results.training_count", 144, len(training))
    check("results.acquisition_count", 20, len(acquisitions))
    check("results.family_selected_count", 10, len(family_selected_files))
    check("results.profile_selected_count", 10, len(profile_selected_files))
    check("results.shadow_count", 80, len(shadows))

    for phase, records, results, key_field in (
        ("training", training_schedule, training, "run_id"),
        ("acquisition", acquisition_schedule, acquisitions, "run_sha256"),
        ("shadow", shadow_schedule, shadows, "run_sha256"),
    ):
        for value in records:
            record = _dict(value)
            identity = str(record.get(key_field))
            result = _dict(results.get(identity))
            prefix = f"{phase}.{identity}"
            for field in (
                "semantic_task_id",
                "base_query_id",
                "query_id",
                "semantic_class_id",
                "plan_id",
                "physical_strategy",
            ):
                check(f"{prefix}.{field}", record.get(field), result.get(field))
            check(f"{prefix}.success", True, result.get("success"))
            check(f"{prefix}.calls", 2, result.get("total_remote_calls"))
            if phase == "acquisition":
                check(f"{prefix}.oracle_closed", False, result.get("answer_oracle_opened"))
            else:
                check(f"{prefix}.exact", True, result.get("exact_answer"))

    candidate_body = _without_hash(candidate_seal, "candidate_seal_sha256")
    check("candidate.hash", content_hash(candidate_body), candidate_seal.get("candidate_seal_sha256"))
    check("candidate.schedule", schedule.get("schedule_sha256"), candidate_seal.get("schedule_sha256"))
    check("candidate.calls_before_seal", 0, candidate_seal.get("backend_calls_before_seal"))
    check("candidate.oracle_fields", [], candidate_seal.get("heldout_answer_oracle_fields"))

    expected_family_selections: list[dict[str, Any]] = []
    reconstructed_memory: Mapping[str, Any] | None = None
    reconstructed_suite: Mapping[str, Any] | None = None
    if direct is not None and base_bundle is not None and predictor is not None:
        raw_observations = _training_observations(
            compile_m15_paired_physical_comparison_schedule(
                workload=direct,
                protocol=root / "paired_physical_protocol.json",
                family_protocol=root / "direct_family_pilot_protocol.json",
                predictor_policy=predictor,
                profile_protocol=root / "current_query_profile_protocol.json",
            ),
            training,
        )
        check("training.observations", {"observations": raw_observations}, loaded.get("training_observations"))
        runtime_hash = _dict(loaded.get("runtime_compatibility")).get("runtime_compatibility_sha256")
        try:
            memory = build_m15_direct_training_memory_view(
                workload=direct,
                raw_observations=raw_observations,
                runtime_compatibility_sha256=str(runtime_hash),
                policy=predictor,
                measurement_source_kind="native_paired_physical_comparison",
            )
            reconstructed_memory = memory.to_dict()
            check("training.memory_reconstruction", reconstructed_memory, loaded.get("training_memory"))
            suite = build_m15_direct_family_prediction_suite(
                workload=direct,
                base_bundle=base_bundle,
                catalog=root / "semantic_catalog.json",
                mapping=root / "predicate_mapping.json",
                memory=memory,
                policy=predictor,
            )
            reconstructed_suite = suite.to_dict()
            check("family.suite_reconstruction", reconstructed_suite, loaded.get("prediction_suite"))
            tasks = _task_index(direct)
            predictions = {
                str(item["plan_id"]): dict(item)
                for source in suite.sources.values()
                for item in source.payload["predictions"]
            }
            all_expected_sets = _candidate_sets(
                direct_workload=direct,
                base_bundle=base_bundle,
                catalog=root / "semantic_catalog.json",
                mapping=root / "predicate_mapping.json",
            )
            expected_plan_ids = sorted(
                plan_id
                for values in all_expected_sets.values()
                for plan_id in values.plans
            )
            check("candidate.plan_ids", expected_plan_ids, candidate_seal.get("candidate_plan_ids"))
            check("candidate.count", len(expected_plan_ids), candidate_seal.get("candidate_count"))
            for query_id, expected_set in suite.candidate_sets.items():
                candidate, state = _read_json(
                    live / "family-selection/queries" / query_id / "candidate_set.json"
                )
                check(f"family.candidate.{query_id}.artifact", "ok", state)
                check(f"family.candidate.{query_id}.exact", expected_set.to_dict(), candidate)
            for query_id, expected_source in suite.sources.items():
                source, state = _read_json(
                    live / "family-selection/queries" / query_id / "prediction_source.json"
                )
                check(f"family.prediction.{query_id}.artifact", "ok", state)
                check(f"family.prediction.{query_id}.exact", expected_source.to_dict(), source)
            for slot_value in family_slots:
                slot = _dict(slot_value)
                plan_id = min(
                    slot["candidate_plan_ids"],
                    key=lambda item: (
                        predictions[item]["estimated_latency_ms"],
                        predictions[item]["estimated_total_bytes_moved"],
                        item,
                    ),
                )
                task = tasks[str(slot["semantic_task_id"])]
                chosen = predictions[plan_id]
                expected_family_selections.append(
                    {
                        **dict(slot),
                        "base_query_id": task["base_query_id"],
                        "query_id": task["executable_query_id"],
                        "selected_plan_id": plan_id,
                        "selected_strategy": chosen["physical_strategy"],
                        "predicted_latency_ms": chosen["estimated_latency_ms"],
                        "predicted_total_bytes_moved": chosen["estimated_total_bytes_moved"],
                    }
                )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            check("family.reconstruction", "valid", f"invalid:{exc}")

    check("family.schema", FAMILY_SELECTION_SEAL_SCHEMA_VERSION, family_seal.get("schema_version"))
    check("family.hash", content_hash(_without_hash(family_seal, "selection_seal_sha256")), family_seal.get("selection_seal_sha256"))
    check("family.selection_reconstruction", expected_family_selections, family_seal.get("selections"))
    if reconstructed_memory is not None:
        check("family.memory_hash", reconstructed_memory.get("training_memory_view_sha256"), family_seal.get("training_memory_view_sha256"))
    if reconstructed_suite is not None:
        check("family.suite_hash", reconstructed_suite.get("prediction_suite_sha256"), family_seal.get("prediction_suite_sha256"))
    check("family.training_calls", 288, family_seal.get("training_backend_calls_before_seal"))
    check("family.profile_calls", 0, family_seal.get("profile_backend_calls_before_seal"))
    check("family.selected_calls", 0, family_seal.get("selected_backend_calls_before_seal"))
    check("family.shadow_calls", 0, family_seal.get("shadow_backend_calls_before_seal"))
    check("family.oracle_fields", [], family_seal.get("heldout_answer_oracle_fields"))

    expected_estimates = sorted(
        [
            {
                "semantic_task_id": item.get("semantic_task_id"),
                "base_query_id": item.get("base_query_id"),
                "query_id": item.get("query_id"),
                "semantic_class_id": item.get("semantic_class_id"),
                "plan_id": item.get("plan_id"),
                "physical_strategy": item.get("physical_strategy"),
                "elapsed_ms": item.get("elapsed_ms"),
                "total_bytes_moved": item.get("total_bytes_moved"),
                "source_run_sha256": item.get("run_sha256"),
            }
            for item in acquisitions.values()
        ],
        key=lambda item: str(item["plan_id"]),
    )
    check("profile.estimate_hash", content_hash(_without_hash(estimate_source, "estimate_source_sha256")), estimate_source.get("estimate_source_sha256"))
    check("profile.estimate_reconstruction", expected_estimates, estimate_source.get("estimates"))
    estimates_by_plan = {str(item["plan_id"]): item for item in expected_estimates}
    task_by_id = {
        str(item["semantic_task_id"]): item for item in expected_estimates
    }
    expected_profile_selections: list[dict[str, Any]] = []
    for slot_value in profile_slots:
        slot = _dict(slot_value)
        try:
            plan_id = min(
                slot["candidate_plan_ids"],
                key=lambda item: (
                    estimates_by_plan[item]["elapsed_ms"],
                    estimates_by_plan[item]["total_bytes_moved"],
                    item,
                ),
            )
            chosen = estimates_by_plan[plan_id]
            task = task_by_id[str(slot["semantic_task_id"])]
            expected_profile_selections.append(
                {
                    **dict(slot),
                    "base_query_id": task["base_query_id"],
                    "query_id": task["query_id"],
                    "selected_plan_id": plan_id,
                    "selected_strategy": chosen["physical_strategy"],
                    "selected_profile_elapsed_ms": chosen["elapsed_ms"],
                    "selected_profile_total_bytes_moved": chosen["total_bytes_moved"],
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            check(f"profile.selection.{slot.get('slot_id')}", "valid", f"invalid:{exc}")
    check("profile.schema", PROFILE_SELECTION_SEAL_SCHEMA_VERSION, profile_seal.get("schema_version"))
    check("profile.hash", content_hash(_without_hash(profile_seal, "selection_seal_sha256")), profile_seal.get("selection_seal_sha256"))
    check("profile.selection_reconstruction", expected_profile_selections, profile_seal.get("selections"))
    check("profile.family_hash", family_seal.get("selection_seal_sha256"), profile_seal.get("family_selection_seal_sha256"))
    check("profile.estimate_hash_link", estimate_source.get("estimate_source_sha256"), profile_seal.get("estimate_source_sha256"))
    check("profile.training_calls", 288, profile_seal.get("training_backend_calls_before_seal"))
    check("profile.acquisition_calls", 40, profile_seal.get("profile_backend_calls_before_seal"))
    check("profile.selected_calls", 0, profile_seal.get("selected_backend_calls_before_seal"))
    check("profile.shadow_calls", 0, profile_seal.get("shadow_backend_calls_before_seal"))
    check("profile.oracle_closed", False, profile_seal.get("answer_oracle_opened_before_seal"))

    selected_by_method = {
        "family_memory": {
            str(item.get("semantic_task_id")): item
            for item in family_selected_files.values()
        },
        "current_query_dual_profile": {
            str(item.get("semantic_task_id")): item
            for item in profile_selected_files.values()
        },
    }
    sealed_by_method = {
        "family_memory": {
            str(item.get("semantic_task_id")): item
            for item in _list(family_seal.get("selections"))
        },
        "current_query_dual_profile": {
            str(item.get("semantic_task_id")): item
            for item in _list(profile_seal.get("selections"))
        },
    }
    for slot_value in selected_slots:
        slot = _dict(slot_value)
        method = str(slot.get("method_id"))
        task = str(slot.get("semantic_task_id"))
        result = _dict(selected_by_method.get(method, {}).get(task))
        selection = _dict(sealed_by_method.get(method, {}).get(task))
        prefix = f"selected.{slot.get('slot_id')}"
        check(f"{prefix}.slot", slot.get("slot_id"), result.get("slot_id"))
        check(f"{prefix}.method", method, result.get("method_id"))
        check(f"{prefix}.plan", selection.get("selected_plan_id"), result.get("plan_id"))
        check(f"{prefix}.success", True, result.get("success"))
        check(f"{prefix}.exact", True, result.get("exact_answer"))
        check(f"{prefix}.calls", 2, result.get("total_remote_calls"))

    acquisition_validation = _dict(loaded.get("acquisition_validation"))
    check("acquisition_validation.after_seals", True, acquisition_validation.get("opened_after_both_selection_seals"))
    check("acquisition_validation.all_exact", True, acquisition_validation.get("all_exact"))
    check("acquisition_validation.count", 20, len(_list(acquisition_validation.get("results"))))
    check("acquisition_validation.results", True, all(_dict(item).get("exact_answer") is True for item in _list(acquisition_validation.get("results"))))

    try:
        expected_analysis = analyze_m15_paired_physical_comparison(
            family_selection_seal=family_seal,
            profile_selection_seal=profile_seal,
            profile_acquisition_results=acquisitions,
            selected_results=selected_by_method,
            shadow_results=shadows,
            training_results=training,
        )
        check("reconstruction.success", True, True)
        check("analysis.exact", expected_analysis, analysis)
    except (KeyError, TypeError, ValueError) as exc:
        check("reconstruction.success", True, f"invalid:{exc}")
    check("analysis.schema", PAIRED_PHYSICAL_ANALYSIS_SCHEMA_VERSION, analysis.get("schema_version"))
    check("analysis.hash", content_hash(_without_hash(analysis, "analysis_sha256")), analysis.get("analysis_sha256"))

    events = [_dict(item) for item in _list(invocations.get("events"))]
    expected_phase_order = (
        [_PHASES[0]] * 288
        + [_PHASES[1]] * 40
        + [_PHASES[2]] * 40
        + [_PHASES[3]] * 160
    )
    expected_run_order: list[str] = []
    for records, identity in (
        (training_schedule, "run_id"),
        (acquisition_schedule, "run_sha256"),
        (selected_slots, "slot_id"),
        (shadow_schedule, "run_sha256"),
    ):
        for value in records:
            expected_run_order.extend([str(_dict(value).get(identity))] * 2)
    check("calls.count", 528, len(events))
    check("calls.reported", len(events), invocations.get("total_tool_invocations"))
    check("calls.phase_order", expected_phase_order, [item.get("paired_phase") for item in events])
    check("calls.run_order", expected_run_order, [str(item.get("paired_run_id")) for item in events])
    check("calls.execute_only", True, all(item.get("operation") == "execute" for item in events))
    check("calls.retries", 0, invocations.get("automatic_retries"))

    expected_summary = {
        **expected_counts,
        "family_memory_current_query_profile_calls": 0,
        "profile_method_current_query_profile_calls": 20,
    }
    check("manifest.summary", expected_summary, manifest.get("summary"))
    check("manifest.family_hash", family_seal.get("selection_seal_sha256"), manifest.get("family_selection_seal_sha256"))
    check("manifest.profile_hash", profile_seal.get("selection_seal_sha256"), manifest.get("profile_selection_seal_sha256"))
    check("manifest.analysis_hash", analysis.get("analysis_sha256"), manifest.get("analysis_sha256"))

    after = _tree_digest(root)
    mutated = before != after
    check("run_tree.unchanged", False, mutated)
    return M15PairedPhysicalEvidenceAudit(
        success=bool(checks) and all(item.passed for item in checks),
        run_root=root,
        expected_commit=expected_commit,
        checks=tuple(checks),
        run_tree_mutated=mutated,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        audit = audit_m15_paired_physical_comparison(
            run_root=args.run_root,
            expected_commit=args.expected_commit,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    payload = audit.to_dict()
    if args.output:
        output = Path(args.output)
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
