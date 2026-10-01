"""Read-only reconstruction audit for one F2C12B profiling baseline run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_current_query_profile_baseline import (
    CURRENT_QUERY_PROFILE_SCHEDULE_SCHEMA_VERSION,
    compile_m15_current_query_profile_baseline_schedule,
)
from xgap.experiments.m15_direct_semantic_workload import (
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_current_query_profile_baseline import (
    CURRENT_QUERY_PROFILE_ANALYSIS_SCHEMA_VERSION,
    CURRENT_QUERY_PROFILE_SELECTION_SEAL_SCHEMA_VERSION,
    LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION,
    analyze_m15_current_query_profile_baseline,
)
from xgap.experiments.m15_native_services import (
    CURRENT_QUERY_PROFILE_PREFLIGHT_SCHEMA_VERSION,
    CURRENT_QUERY_PROFILE_SERVICE_RUN_SCHEMA_VERSION,
)


CURRENT_QUERY_PROFILE_BASELINE_AUDIT_SCHEMA_VERSION = (
    "m15-f2c12b-current-query-profile-baseline-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PHASES = (
    "current_query_profile_acquisition",
    "selected_plan_execution",
    "postselection_shadow_evaluation",
)


@dataclass(frozen=True)
class CurrentQueryProfileEvidenceCheck:
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
class M15CurrentQueryProfileBaselineEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[CurrentQueryProfileEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CURRENT_QUERY_PROFILE_BASELINE_AUDIT_SCHEMA_VERSION,
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
    result: dict[str, Mapping[str, Any]] = {}
    for path in sorted(root.glob(pattern)):
        value, state = _read_json(path)
        if state == "ok" and isinstance(value, Mapping):
            result[path.stem] = value
    return result


def _exact_validation(value: object) -> bool:
    validation = _dict(value)
    checks = validation.get("checks")
    return (
        validation.get("passed") is True
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(item is True for item in checks.values())
    )


def _without_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def audit_m15_current_query_profile_baseline(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15CurrentQueryProfileBaselineEvidenceAudit:
    """Rebuild selection and analysis from sealed run artifacts without writes."""

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
    nested_live = service / "current-query-profile-baseline-run"
    live = nested_live if nested_live.is_dir() else root
    native_outer = live != root

    paths = {
        "status": live / "run_status.json",
        "manifest": live / "run_manifest.json",
        "schedule": live / "profile_schedule.json",
        "candidate_seal": live / "candidate_seal.json",
        "estimate_source": live / "profile_cost_estimates.json",
        "selection_seal": live / "selection_seal.json",
        "acquisition_validation": live / "acquisition_validation.json",
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
                    service
                    / "current-query-profile-preflight/profile_schedule.json"
                ),
                "preflight_manifest": (
                    service
                    / "current-query-profile-preflight/preflight_manifest.json"
                ),
            }
        )
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for name, path in paths.items():
        loaded[name], states[name] = _read_json(path)

    checks: list[CurrentQueryProfileEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            CurrentQueryProfileEvidenceCheck(
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
    estimate_source = _dict(loaded.get("estimate_source"))
    selection_seal = _dict(loaded.get("selection_seal"))
    acquisition_validation = _dict(loaded.get("acquisition_validation"))
    validation = _dict(loaded.get("validation"))
    invocations = _dict(loaded.get("invocations"))

    check("status.schema", LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION, status.get("schema_version"))
    check("status.success", "success", status.get("status"))
    check("status.error", None, status.get("error"))
    check("manifest.schema", LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION, manifest.get("schema_version"))
    check("manifest.status", "success", manifest.get("status"))
    check("manifest.commit", expected_commit, _dict(manifest.get("git")).get("commit"))
    check("manifest.clean", True, _dict(manifest.get("git")).get("clean"))
    check("manifest.validation", True, _exact_validation(manifest.get("validation")))
    check("validation.exact", True, _exact_validation(validation))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    check("manifest.retries", 0, manifest.get("automatic_retries"))
    check("manifest.memory", False, manifest.get("training_memory_used"))
    check("manifest.llm_calls", 0, manifest.get("llm_calls_made"))
    check("manifest.ontology_calls", 0, manifest.get("ontology_service_calls_made"))
    check("manifest.profile_semantics", "full_federated_plan_execution_labeled_profile", manifest.get("profile_operation_semantics"))

    if native_outer:
        outer_status = _dict(loaded.get("outer_status"))
        service_status = _dict(loaded.get("service_status"))
        service_manifest = _dict(loaded.get("service_manifest"))
        preflight = _dict(loaded.get("preflight_manifest"))
        check("outer.status", "success", outer_status.get("status"))
        check("outer.exit_code", 0, outer_status.get("exit_code"))
        check("outer.commit", expected_commit, outer_status.get("git_commit"))
        check("outer.workload_mode", "current_query_profile_baseline", outer_status.get("workload_mode"))
        check("outer.runtime_removed", True, outer_status.get("runtime_removed"))
        check("service.status", "success", service_status.get("status"))
        check("service.schema", CURRENT_QUERY_PROFILE_SERVICE_RUN_SCHEMA_VERSION, service_status.get("schema_version"))
        check("service.manifest_schema", CURRENT_QUERY_PROFILE_SERVICE_RUN_SCHEMA_VERSION, service_manifest.get("schema_version"))
        check("service.manifest_status", "success", service_manifest.get("status"))
        check("preflight.schema", CURRENT_QUERY_PROFILE_PREFLIGHT_SCHEMA_VERSION, preflight.get("schema_version"))
        check("preflight.sealed", True, preflight.get("sealed_before_service_start"))
        check("preflight.calls", 0, preflight.get("backend_calls_before_seal"))
        check("preflight.oracle_closed", False, preflight.get("answer_oracle_opened_before_seal"))
        check("preflight.retries", 0, preflight.get("automatic_retries"))
        check("preflight.paper_result", False, preflight.get("paper_result"))

        input_paths = {
            "base": root / "direct-family-base-workload-bundle",
            "direct": root / "direct-semantic-workload-bundle",
            "catalog": root / "semantic_catalog.json",
            "mapping": root / "predicate_mapping.json",
            "protocol": root / "current_query_profile_protocol.json",
        }
        for name, path in input_paths.items():
            check(
                f"input.{name}",
                True,
                path.is_dir() if name in {"base", "direct"} else path.is_file(),
            )
        try:
            direct = load_m15_direct_semantic_workload_bundle(
                input_paths["direct"],
                base_bundle=input_paths["base"],
                catalog=input_paths["catalog"],
                mapping=input_paths["mapping"],
            )
            reconstructed_schedule = (
                compile_m15_current_query_profile_baseline_schedule(
                    workload=direct,
                    protocol=input_paths["protocol"],
                ).to_dict()
            )
            check("schedule.source_reconstruction", reconstructed_schedule, schedule)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            check("schedule.source_reconstruction", "valid", f"invalid:{exc}")

    check("schedule.schema", CURRENT_QUERY_PROFILE_SCHEDULE_SCHEMA_VERSION, schedule.get("schema_version"))
    check("schedule.hash", content_hash(_without_hash(schedule, "schedule_sha256")), schedule.get("schedule_sha256"))
    check("schedule.manifest_hash", schedule.get("schedule_sha256"), manifest.get("schedule_sha256"))
    if native_outer:
        check("preflight.schedule_exact", schedule, loaded.get("preflight_schedule"))
        check("preflight.schedule_hash", schedule.get("schedule_sha256"), _dict(loaded.get("preflight_manifest")).get("schedule_sha256"))
        check("preflight.counts", schedule.get("counts"), _dict(loaded.get("preflight_manifest")).get("expected_counts"))
    check("schedule.paper_result", False, schedule.get("paper_result"))
    check("schedule.live_authorized", False, schedule.get("live_execution_authorized"))
    check("schedule.external_calls", 0, schedule.get("external_calls_made"))
    expected_counts = {
        "acquisition_plan_runs": 20,
        "selected_plan_runs": 10,
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 110,
        "acquisition_backend_calls": 40,
        "selected_plan_backend_calls": 20,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 220,
    }
    check("schedule.counts", expected_counts, schedule.get("counts"))

    acquisition_schedule = _list(schedule.get("acquisition_runs"))
    selection_slots = _list(schedule.get("selection_slots"))
    selected_slots = _list(schedule.get("selected_execution_slots"))
    shadow_schedule = _list(schedule.get("shadow_runs"))
    check("schedule.acquisition_count", 20, len(acquisition_schedule))
    check("schedule.selection_count", 10, len(selection_slots))
    check("schedule.selected_count", 10, len(selected_slots))
    check("schedule.shadow_count", 80, len(shadow_schedule))
    for phase, records, identity_field in (
        ("acquisition", acquisition_schedule, "run_sha256"),
        ("selection", selection_slots, "slot_sha256"),
        ("selected", selected_slots, "slot_sha256"),
        ("shadow", shadow_schedule, "run_sha256"),
    ):
        for index, value in enumerate(records, start=1):
            record = _dict(value)
            check(
                f"schedule.{phase}.{index}.hash",
                content_hash(_without_hash(record, identity_field)),
                record.get(identity_field),
            )

    acquisitions = _file_map(live / "acquisition/runs", "*.json")
    selected_results = _file_map(live / "selected", "*.json")
    shadows = _file_map(live / "shadow/runs", "*.json")
    check("results.acquisition_count", 20, len(acquisitions))
    check("results.selected_count", 10, len(selected_results))
    check("results.shadow_count", 80, len(shadows))

    for phase, records, results, key_field in (
        ("acquisition", acquisition_schedule, acquisitions, "run_sha256"),
        ("shadow", shadow_schedule, shadows, "run_sha256"),
    ):
        for record_value in records:
            record = _dict(record_value)
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

    estimate_body = _without_hash(estimate_source, "estimate_source_sha256")
    check("estimate.hash", content_hash(estimate_body), estimate_source.get("estimate_source_sha256"))
    check("estimate.schedule", schedule.get("schedule_sha256"), estimate_source.get("schedule_sha256"))
    check("estimate.fields", ["elapsed_ms", "total_bytes_moved", "plan_id"], estimate_source.get("selection_fields"))
    check("estimate.answer_rows", [], estimate_source.get("answer_rows"))
    check("estimate.oracle_fields", [], estimate_source.get("answer_oracle_fields"))
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
    check("estimate.reconstruction", expected_estimates, estimate_source.get("estimates"))

    estimates_by_plan = {
        str(item.get("plan_id")): item
        for item in _list(estimate_source.get("estimates"))
        if isinstance(item, Mapping)
    }
    expected_selections: list[dict[str, Any]] = []
    for value in selection_slots:
        slot = _dict(value)
        candidates = [str(item) for item in _list(slot.get("candidate_plan_ids"))]
        try:
            plan_id = min(
                candidates,
                key=lambda item: (
                    estimates_by_plan[item]["elapsed_ms"],
                    estimates_by_plan[item]["total_bytes_moved"],
                    item,
                ),
            )
            estimate = estimates_by_plan[plan_id]
            expected_selections.append(
                {
                    **dict(slot),
                    "base_query_id": estimate["base_query_id"],
                    "query_id": estimate["query_id"],
                    "selected_plan_id": plan_id,
                    "selected_strategy": estimate["physical_strategy"],
                    "selected_profile_elapsed_ms": estimate["elapsed_ms"],
                    "selected_profile_total_bytes_moved": estimate[
                        "total_bytes_moved"
                    ],
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            check(f"selection.{slot.get('slot_id')}.reconstructable", True, f"invalid:{exc}")

    selection_body = _without_hash(selection_seal, "selection_seal_sha256")
    check("selection.schema", CURRENT_QUERY_PROFILE_SELECTION_SEAL_SCHEMA_VERSION, selection_seal.get("schema_version"))
    check("selection.hash", content_hash(selection_body), selection_seal.get("selection_seal_sha256"))
    check("selection.reconstruction", expected_selections, selection_seal.get("selections"))
    check("selection.candidate_seal", candidate_seal.get("candidate_seal_sha256"), selection_seal.get("candidate_seal_sha256"))
    check("selection.estimate_source", estimate_source.get("estimate_source_sha256"), selection_seal.get("estimate_source_sha256"))
    check("selection.profile_calls_before_seal", 40, selection_seal.get("profile_backend_calls_before_seal"))
    check("selection.selected_calls_before_seal", 0, selection_seal.get("selected_execution_backend_calls_before_seal"))
    check("selection.shadow_calls_before_seal", 0, selection_seal.get("shadow_backend_calls_before_seal"))
    check("selection.oracle_closed", False, selection_seal.get("answer_oracle_opened_before_seal"))
    check("selection.result_blind", False, selection_seal.get("answer_rows_selection_input"))

    candidate_body = _without_hash(candidate_seal, "candidate_seal_sha256")
    expected_plan_ids = sorted(str(item.get("plan_id")) for item in acquisition_schedule)
    check("candidate.hash", content_hash(candidate_body), candidate_seal.get("candidate_seal_sha256"))
    check("candidate.plan_ids", expected_plan_ids, candidate_seal.get("candidate_plan_ids"))
    check("candidate.count", 20, candidate_seal.get("candidate_count"))
    check("candidate.calls_before_seal", 0, candidate_seal.get("backend_calls_before_seal"))

    selected_by_task = {
        str(item.get("semantic_task_id")): item for item in selected_results.values()
    }
    for slot_value in selected_slots:
        slot = _dict(slot_value)
        task_id = str(slot.get("semantic_task_id"))
        result = _dict(selected_by_task.get(task_id))
        selection = next(
            (
                item
                for item in expected_selections
                if item.get("semantic_task_id") == task_id
            ),
            {},
        )
        prefix = f"selected.{slot.get('slot_id')}"
        check(f"{prefix}.slot", slot.get("slot_id"), result.get("slot_id"))
        check(f"{prefix}.plan", selection.get("selected_plan_id"), result.get("plan_id"))
        check(f"{prefix}.strategy", selection.get("selected_strategy"), result.get("physical_strategy"))
        check(f"{prefix}.success", True, result.get("success"))
        check(f"{prefix}.exact", True, result.get("exact_answer"))
        check(f"{prefix}.calls", 2, result.get("total_remote_calls"))

    validation_results = _list(acquisition_validation.get("results"))
    check("acquisition_validation.after_seal", True, acquisition_validation.get("opened_after_selection_seal"))
    check("acquisition_validation.all_exact", True, acquisition_validation.get("all_exact"))
    check("acquisition_validation.count", 20, len(validation_results))
    check("acquisition_validation.results", True, all(_dict(item).get("exact_answer") is True for item in validation_results))

    expected_analysis: Mapping[str, Any] | None = None
    try:
        expected_analysis = analyze_m15_current_query_profile_baseline(
            selection_seal=selection_seal,
            acquisition_results=acquisitions,
            selected_results=selected_results,
            shadow_results=shadows,
        )
        check("reconstruction.success", True, True)
    except (KeyError, TypeError, ValueError) as exc:
        check("reconstruction.success", True, f"invalid:{exc}")
    analysis = _dict(loaded.get("analysis"))
    check("analysis.schema", CURRENT_QUERY_PROFILE_ANALYSIS_SCHEMA_VERSION, analysis.get("schema_version"))
    if expected_analysis is not None:
        check("analysis.exact", expected_analysis, analysis)
    check("analysis.hash", content_hash(_without_hash(analysis, "analysis_sha256")), analysis.get("analysis_sha256"))

    events = [_dict(item) for item in _list(invocations.get("events"))]
    expected_phases = (
        [_PHASES[0]] * 40 + [_PHASES[1]] * 20 + [_PHASES[2]] * 160
    )
    check("calls.count", 220, len(events))
    check("calls.reported", len(events), invocations.get("total_tool_invocations"))
    check("calls.phase_order", expected_phases, [item.get("profile_baseline_phase") for item in events])
    check("calls.execute_only", True, all(item.get("operation") == "execute" for item in events))
    check("calls.retries", 0, invocations.get("automatic_retries"))
    check("manifest.summary", expected_counts, manifest.get("summary"))
    check("manifest.selection_hash", selection_seal.get("selection_seal_sha256"), manifest.get("selection_seal_sha256"))
    check("manifest.analysis_hash", analysis.get("analysis_sha256"), manifest.get("analysis_sha256"))

    after = _tree_digest(root)
    mutated = before != after
    check("run_tree.unchanged", False, mutated)
    return M15CurrentQueryProfileBaselineEvidenceAudit(
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
        audit = audit_m15_current_query_profile_baseline(
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
