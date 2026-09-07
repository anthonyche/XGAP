"""Read-only reconstruction audit for a live FinBench family campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_family_campaign import (
    build_finbench_family_campaign_schedule,
)
from xgap.experiments.m15_finbench_family_memory import (
    build_finbench_training_memory,
    predict_finbench_heldout_plans,
)
from xgap.experiments.m15_finbench_federation import canonicalize_finbench_rows
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
    load_finbench_primary_workload,
)
from xgap.experiments.m15_live_finbench_family_campaign import (
    FINBENCH_CORRECTNESS_ADMISSION_SCHEMA_VERSION,
    FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
    FINBENCH_FAMILY_CAMPAIGN_ANALYSIS_SCHEMA_VERSION,
    FINBENCH_FAMILY_SELECTION_SEAL_SCHEMA_VERSION,
    FINBENCH_PROFILE_SELECTION_SEAL_SCHEMA_VERSION,
    LIVE_FINBENCH_FAMILY_CAMPAIGN_SCHEMA_VERSION,
    _candidate_catalog,
    _family_selection,
    _profile_selection,
    _training_observations,
    analyze_finbench_family_campaign,
)


FINBENCH_FAMILY_CAMPAIGN_AUDIT_SCHEMA_VERSION = (
    "m15-finbench-family-campaign-evidence-audit-v1"
)
FINBENCH_FAMILY_CAMPAIGN_SERVICE_RUN_SCHEMA_VERSION = (
    "m15-finbench-native-live-family-campaign-service-run-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class FinBenchFamilyCampaignEvidenceCheck:
    check_id: str
    passed: bool
    expected: Any
    observed: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "expected": _json_safe(self.expected),
            "observed": _json_safe(self.observed),
        }


@dataclass(frozen=True)
class FinBenchFamilyCampaignEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[FinBenchFamilyCampaignEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(check.check_id for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FINBENCH_FAMILY_CAMPAIGN_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [check.to_dict() for check in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


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


def _read(path: Path) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        return None, "missing_or_nonregular"
    try:
        return json.loads(path.read_text(encoding="utf-8")), "ok"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{exc}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _read_result_set(
    root: Path,
    records: Sequence[Mapping[str, Any]],
    *,
    directory: str,
    identity_field: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    result: dict[str, dict[str, Any]] = {}
    states: list[str] = []
    for record in records:
        identity = str(record[identity_field])
        value, state = _read(root / directory / f"{identity}.json")
        states.append(state)
        if isinstance(value, Mapping):
            result[identity] = dict(value)
    return result, states


def audit_m15_finbench_family_campaign(
    *,
    run_root: str | Path,
    expected_commit: str,
    protocol: str | Path,
    family_memory_policy: str | Path,
) -> FinBenchFamilyCampaignEvidenceAudit:
    """Reconstruct selections, oracle comparisons, and analysis without writes."""

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
    live = service / "finbench-family-campaign-run"
    workload_root = root / "finbench-primary-workload"
    paths = {
        "outer_status": root / "run_status.json",
        "service_status": service / "run_status.json",
        "service_manifest": service / "run_manifest.json",
        "status": live / "run_status.json",
        "manifest": live / "run_manifest.json",
        "schedule": live / "campaign_schedule.json",
        "candidate_catalog": live / "candidate_catalog.json",
        "admission": live / "correctness_admission.json",
        "correctness_audit": live / "correctness_audit_snapshot.json",
        "correctness_manifest": live / "correctness_manifest_snapshot.json",
        "training_observations": live / "training/training_observations.json",
        "training_equivalence": live / "training/training_equivalence.json",
        "memory": live / "training/training_memory.json",
        "suite": live / "family/prediction_suite.json",
        "family_seal": live / "family_selection_seal.json",
        "profile_seal": live / "profile_selection_seal.json",
        "events": live / "backend_invocations.json",
        "oracle_validation": live / "oracle_validation.json",
        "analysis": live / "analysis.json",
        "validation": live / "validation.json",
        "loads": live / "load_reports.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for name, path in paths.items():
        loaded[name], states[name] = _read(path)
    checks: list[FinBenchFamilyCampaignEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            FinBenchFamilyCampaignEvidenceCheck(
                check_id=check_id,
                passed=expected == observed,
                expected=expected,
                observed=observed,
            )
        )

    for name, state in states.items():
        check(f"artifact.{name}", "ok", state)
    check("artifact.workload", True, workload_root.is_dir())
    outer = _mapping(loaded["outer_status"])
    service_status = _mapping(loaded["service_status"])
    service_manifest = _mapping(loaded["service_manifest"])
    status = _mapping(loaded["status"])
    manifest = _mapping(loaded["manifest"])
    schedule = _mapping(loaded["schedule"])
    catalog = _mapping(loaded["candidate_catalog"])
    admission = _mapping(loaded["admission"])
    correctness_audit = _mapping(loaded["correctness_audit"])
    correctness_manifest = _mapping(loaded["correctness_manifest"])
    observations_payload = _mapping(loaded["training_observations"])
    equivalence_payload = _mapping(loaded["training_equivalence"])
    memory = _mapping(loaded["memory"])
    suite = _mapping(loaded["suite"])
    family_seal = _mapping(loaded["family_seal"])
    profile_seal = _mapping(loaded["profile_seal"])
    events_payload = _mapping(loaded["events"])
    oracle_validation = _mapping(loaded["oracle_validation"])
    analysis = _mapping(loaded["analysis"])
    validation = _mapping(loaded["validation"])
    loads = _mapping(loaded["loads"])

    check("outer.status", "success", outer.get("status"))
    check("outer.exit_code", 0, outer.get("exit_code"))
    check("outer.commit", expected_commit, outer.get("git_commit"))
    check("outer.mode", "finbench_family_campaign", outer.get("workload_mode"))
    check("outer.runtime_removed", True, outer.get("runtime_removed"))
    check("service.status", "success", service_status.get("status"))
    check(
        "service.schema",
        FINBENCH_FAMILY_CAMPAIGN_SERVICE_RUN_SCHEMA_VERSION,
        service_manifest.get("schema_version"),
    )
    check("service.manifest_status", "success", service_manifest.get("status"))
    check("live.schema", LIVE_FINBENCH_FAMILY_CAMPAIGN_SCHEMA_VERSION, status.get("schema_version"))
    check("live.status", "success", status.get("status"))
    check("manifest.schema", LIVE_FINBENCH_FAMILY_CAMPAIGN_SCHEMA_VERSION, manifest.get("schema_version"))
    check("manifest.status", "success", manifest.get("status"))
    check("manifest.commit", expected_commit, _mapping(manifest.get("git")).get("commit"))
    check("manifest.clean", True, _mapping(manifest.get("git")).get("clean"))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    check("manifest.automatic_retries", 0, manifest.get("automatic_retries"))

    public: Mapping[str, Any] = {}
    compiled_schedule: Mapping[str, Any] = {}
    compiled_catalog: Mapping[str, Any] = {}
    plans: Mapping[tuple[str, str], Any] = {}
    try:
        public = load_finbench_primary_public_workload(workload_root)
        built_schedule = build_finbench_family_campaign_schedule(
            workload_root=workload_root,
            protocol=protocol,
            family_memory_policy=family_memory_policy,
        )
        compiled_schedule = built_schedule.to_dict()
        compiled_catalog, plans = _candidate_catalog(
            workload_root,
            [dict(item) for item in public["public_instances"]["instances"]],
        )
        check("reconstruction.preflight", True, True)
    except Exception as exc:
        check("reconstruction.preflight", "success", f"error:{exc}")
    check("schedule.exact", compiled_schedule, schedule)
    check("catalog.exact", compiled_catalog, catalog)
    check("manifest.schedule_hash", schedule.get("schedule_sha256"), manifest.get("schedule_sha256"))
    check("manifest.catalog_hash", catalog.get("candidate_catalog_sha256"), manifest.get("candidate_catalog_sha256"))

    admission_body = {key: value for key, value in admission.items() if key != "admission_sha256"}
    check("admission.schema", FINBENCH_CORRECTNESS_ADMISSION_SCHEMA_VERSION, admission.get("schema_version"))
    check("admission.hash", content_hash(admission_body), admission.get("admission_sha256"))
    check("admission.audit_schema", FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION, correctness_audit.get("schema_version"))
    check("admission.audit_success", True, correctness_audit.get("success"))
    check("admission.audit_failures", [], correctness_audit.get("failed_check_ids"))
    check("admission.audit_nonmutating", False, correctness_audit.get("run_tree_mutated"))
    check("admission.audit_content_hash", admission.get("audit_content_sha256"), content_hash(correctness_audit))
    check("admission.manifest_content_hash", admission.get("producer_manifest_content_sha256"), content_hash(correctness_manifest))
    correctness_summary = _mapping(correctness_manifest.get("summary"))
    check("admission.correctness_all_exact", True, correctness_summary.get("all_plans_exact"))
    check("admission.correctness_equivalent", True, correctness_summary.get("all_physical_pairs_equivalent"))
    check("admission.workload", _mapping(public.get("manifest")).get("workload_sha256"), admission.get("workload_sha256"))

    training_results, training_states = _read_result_set(
        live,
        schedule.get("training_runs", []),
        directory="training/runs",
        identity_field="run_id",
    )
    acquisition_results, acquisition_states = _read_result_set(
        live,
        schedule.get("profile_acquisition_runs", []),
        directory="profile/acquisition/runs",
        identity_field="run_id",
    )
    selected_results, selected_states = _read_result_set(
        live,
        schedule.get("paired_selected_execution_slots", []),
        directory="selected/runs",
        identity_field="slot_id",
    )
    shadow_results, shadow_states = _read_result_set(
        live,
        schedule.get("evaluation_shadow_runs", []),
        directory="shadow/runs",
        identity_field="run_id",
    )
    check("runs.training_artifacts", True, bool(training_states) and all(item == "ok" for item in training_states))
    check("runs.acquisition_artifacts", True, bool(acquisition_states) and all(item == "ok" for item in acquisition_states))
    check("runs.selected_artifacts", True, bool(selected_states) and all(item == "ok" for item in selected_states))
    check("runs.shadow_artifacts", True, bool(shadow_states) and all(item == "ok" for item in shadow_states))
    check("runs.training_count", 128, len(training_results))
    check("runs.acquisition_count", 40, len(acquisition_results))
    check("runs.selected_count", 40, len(selected_results))
    check("runs.shadow_count", 160, len(shadow_results))
    all_results = [
        *training_results.values(),
        *acquisition_results.values(),
        *selected_results.values(),
        *shadow_results.values(),
    ]
    check("runs.success", True, bool(all_results) and all(item.get("success") is True for item in all_results))
    check("runs.remote_calls", True, bool(all_results) and all(item.get("total_remote_calls") == 2 for item in all_results))

    rebuilt_memory: Mapping[str, Any] = {}
    rebuilt_suite: Mapping[str, Any] = {}
    rebuilt_family_seal: Mapping[str, Any] = {}
    rebuilt_profile_seal: Mapping[str, Any] = {}
    rebuilt_analysis: Mapping[str, Any] = {}
    try:
        rebuilt_observations, rebuilt_equivalence = _training_observations(
            schedule=build_finbench_family_campaign_schedule(
                workload_root=workload_root,
                protocol=protocol,
                family_memory_policy=family_memory_policy,
            ),
            results=training_results,
            correctness_admission=admission,
        )
        check("training.observations_exact", {"observations": rebuilt_observations}, observations_payload)
        check("training.equivalence_exact", {"pairs": rebuilt_equivalence, "all_pairs_equivalent": True}, equivalence_payload)
        memory_record = build_finbench_training_memory(
            workload_root=workload_root,
            raw_observations=rebuilt_observations,
            policy=family_memory_policy,
            measurement_source_id=str(memory.get("measurement_source_id")),
        )
        rebuilt_memory = memory_record.to_dict()
        check("training.memory_exact", rebuilt_memory, memory)
        suite_record = predict_finbench_heldout_plans(
            workload_root=workload_root,
            memory=memory_record,
            policy=family_memory_policy,
        )
        rebuilt_suite = suite_record.to_dict()
        check("family.prediction_suite_exact", rebuilt_suite, suite)
        rebuilt_family_seal = _family_selection(
            schedule=build_finbench_family_campaign_schedule(
                workload_root=workload_root,
                protocol=protocol,
                family_memory_policy=family_memory_policy,
            ),
            suite=suite_record,
            plans=plans,
            event_count=256,
        )
        check("family.selection_seal_exact", rebuilt_family_seal, family_seal)
        rebuilt_profile_seal = _profile_selection(
            schedule=build_finbench_family_campaign_schedule(
                workload_root=workload_root,
                protocol=protocol,
                family_memory_policy=family_memory_policy,
            ),
            acquisition=acquisition_results,
            family_seal=rebuilt_family_seal,
            event_count=336,
        )
        check("profile.selection_seal_exact", rebuilt_profile_seal, profile_seal)
        rebuilt_analysis = analyze_finbench_family_campaign(
            public_workload=public,
            memory=rebuilt_memory,
            prediction_suite=rebuilt_suite,
            family_seal=rebuilt_family_seal,
            profile_seal=rebuilt_profile_seal,
            acquisition_results=acquisition_results,
            selected_results=selected_results,
            shadow_results=shadow_results,
        )
        check("analysis.exact", rebuilt_analysis, analysis)
    except Exception as exc:
        check("reconstruction.execution", "success", f"error:{exc}")

    events = events_payload.get("events")
    check("events.list", True, isinstance(events, list))
    check("events.count", 736, len(events) if isinstance(events, list) else None)
    check("events.retries", 0, events_payload.get("automatic_retries"))
    if isinstance(events, list):
        phases = {
            phase: sum(
                isinstance(item, Mapping) and item.get("phase") == phase
                for item in events
            )
            for phase in (
                "training_measurement",
                "current_query_profile_acquisition",
                "paired_selected_execution",
                "postselection_shadow_evaluation",
            )
        }
        check(
            "events.phase_counts",
            {
                "training_measurement": 256,
                "current_query_profile_acquisition": 80,
                "paired_selected_execution": 80,
                "postselection_shadow_evaluation": 320,
            },
            phases,
        )

    try:
        full = load_finbench_primary_workload(workload_root)
        oracles = full["sealed_oracles"]["queries"]
        comparisons = []
        for phase, values in (
            ("training_measurement", training_results),
            ("current_query_profile_acquisition", acquisition_results),
            ("paired_selected_execution", selected_results),
            ("postselection_shadow_evaluation", shadow_results),
        ):
            for identity, result in sorted(values.items()):
                query_id = str(result["query_id"])
                family_id = str(result["family_id"])
                observed = canonicalize_finbench_rows(
                    family_id, result["runtime_result"]["final_rows"]
                )
                expected = canonicalize_finbench_rows(
                    family_id, oracles[query_id]["final_rows"]
                )
                comparisons.append(
                    {
                        "phase": phase,
                        "scheduled_identity": identity,
                        "query_id": query_id,
                        "plan_id": result["plan_id"],
                        "exact_answer": observed == expected,
                        "observed_rows_sha256": content_hash(observed),
                        "expected_rows_sha256": content_hash(expected),
                    }
                )
        expected_oracle = {
            "opened_after_all_plan_runs": True,
            "backend_calls_before_open": 736,
            "selection_fields_used": [],
            "comparison_count": len(comparisons),
            "all_answers_exact": all(item["exact_answer"] for item in comparisons),
            "comparisons": comparisons,
        }
        check("oracle.validation_exact", expected_oracle, oracle_validation)
    except Exception as exc:
        check("oracle.reconstruction", "success", f"error:{exc}")

    check("analysis.schema", FINBENCH_FAMILY_CAMPAIGN_ANALYSIS_SCHEMA_VERSION, analysis.get("schema_version"))
    check("analysis.paper_result", False, analysis.get("paper_result"))
    check("validation.passed", True, validation.get("passed"))
    check("loads.backends", {"neo4j", "fuseki"}, set(loads))
    check("loads.success", True, set(loads) == {"neo4j", "fuseki"} and all(_mapping(item).get("success") is True for item in loads.values()))
    check("manifest.memory_hash", memory.get("training_memory_sha256"), manifest.get("training_memory_sha256"))
    check("manifest.suite_hash", suite.get("prediction_suite_sha256"), manifest.get("prediction_suite_sha256"))
    check("manifest.family_seal_hash", family_seal.get("selection_seal_sha256"), manifest.get("family_selection_seal_sha256"))
    check("manifest.profile_seal_hash", profile_seal.get("selection_seal_sha256"), manifest.get("profile_selection_seal_sha256"))
    check("manifest.analysis_hash", analysis.get("analysis_sha256"), manifest.get("analysis_sha256"))
    check("manifest.zero_profile", 0, _mapping(manifest.get("summary")).get("family_memory_current_query_profile_calls"))
    check("manifest.total_runs", 368, _mapping(manifest.get("summary")).get("total_plan_runs"))
    check("manifest.total_calls", 736, _mapping(manifest.get("summary")).get("total_backend_calls"))
    check("manifest.oracle_after_runs", True, _mapping(manifest.get("oracle_boundary")).get("content_parsed_after_all_plan_runs"))
    check("manifest.oracle_selection", False, _mapping(manifest.get("oracle_boundary")).get("used_for_selection"))

    after = _tree_digest(root)
    mutated = before != after
    check("audit.run_tree_unchanged", False, mutated)
    passed = all(item.passed for item in checks)
    return FinBenchFamilyCampaignEvidenceAudit(
        success=passed and not mutated,
        run_root=root,
        expected_commit=expected_commit,
        checks=tuple(checks),
        run_tree_mutated=mutated,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--protocol",
        default="experiments/configs/m15_finbench_family_campaign_dev_v1.json",
    )
    parser.add_argument(
        "--family-memory-policy",
        default="experiments/configs/m15_finbench_family_memory_policy_v1.json",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    run_root = Path(args.run_root).resolve()
    output = Path(args.output).resolve()
    if output == run_root or run_root in output.parents:
        print(
            json.dumps(
                {"status": "failed", "error": "output must be outside run_root"},
                sort_keys=True,
            )
        )
        return 2
    if output.exists() or output.is_symlink():
        print(
            json.dumps(
                {"status": "failed", "error": "output already exists"},
                sort_keys=True,
            )
        )
        return 2
    try:
        audit = audit_m15_finbench_family_campaign(
            run_root=run_root,
            expected_commit=args.expected_commit,
            protocol=args.protocol,
            family_memory_policy=args.family_memory_policy,
        )
        _write_json(output, audit.to_dict())
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
