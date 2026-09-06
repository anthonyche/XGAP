"""Read-only reconstruction audit for one native F2C10D development pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_pilot import (
    compile_m15_direct_family_pilot_schedule,
)
from xgap.experiments.m15_direct_family_prediction import (
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_direct_semantic_workload import (
    load_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_direct_family_pilot import (
    DIRECT_FAMILY_PILOT_ANALYSIS_SCHEMA_VERSION,
    DIRECT_FAMILY_PILOT_SELECTION_SEAL_SCHEMA_VERSION,
    LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION,
    _training_observations,
    analyze_m15_direct_family_pilot,
)
from xgap.experiments.m15_native_services import (
    DIRECT_FAMILY_PILOT_PREFLIGHT_SCHEMA_VERSION,
    DIRECT_FAMILY_PILOT_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)


DIRECT_FAMILY_PILOT_AUDIT_SCHEMA_VERSION = (
    "m15-f2c10d-direct-family-pilot-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class DirectFamilyPilotEvidenceCheck:
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
class M15DirectFamilyPilotEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[DirectFamilyPilotEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DIRECT_FAMILY_PILOT_AUDIT_SCHEMA_VERSION,
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _exact_validation(value: object) -> bool:
    validation = _dict(value)
    checks = validation.get("checks")
    return (
        validation.get("passed") is True
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(item is True for item in checks.values())
    )


def _file_map(root: Path, pattern: str) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for path in sorted(root.glob(pattern)):
        value, state = _read_json(path)
        if state == "ok" and isinstance(value, Mapping):
            records[path.stem] = value
    return records


def audit_m15_direct_family_pilot(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15DirectFamilyPilotEvidenceAudit:
    """Rebuild the schedule, memory, predictions, frontiers, and analysis."""

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
    live = service / "direct-family-pilot-run"
    inputs = {
        "base": root / "direct-family-base-workload-bundle",
        "direct": root / "direct-semantic-workload-bundle",
        "catalog": root / "semantic_catalog.json",
        "mapping": root / "predicate_mapping.json",
        "protocol": root / "direct_family_pilot_protocol.json",
        "predictor": root / "direct_family_predictor_policy.json",
    }
    paths = {
        "outer_status": root / "run_status.json",
        "service_status": service / "run_status.json",
        "service_manifest": service / "run_manifest.json",
        "preflight_schedule": (
            service / "direct-family-pilot-preflight/pilot_schedule.json"
        ),
        "preflight_manifest": (
            service / "direct-family-pilot-preflight/preflight_manifest.json"
        ),
        "status": live / "run_status.json",
        "manifest": live / "run_manifest.json",
        "schedule": live / "pilot_schedule.json",
        "selection_schedule": live / "selection/pilot_schedule.json",
        "selection_seal": live / "selection_seal.json",
        "training_observations": live / "training/training_observations.json",
        "training_memory": live / "training/training_memory_view.json",
        "selection_training_observations": (
            live / "selection/training_observations.json"
        ),
        "selection_training_memory": live / "selection/training_memory_view.json",
        "prediction_suite": live / "selection/prediction_suite.json",
        "analysis": live / "analysis.json",
        "validation": live / "validation.json",
        "invocations": live / "backend_invocations.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for name, path in paths.items():
        loaded[name], states[name] = _read_json(path)

    checks: list[DirectFamilyPilotEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            DirectFamilyPilotEvidenceCheck(
                check_id=check_id,
                passed=observed == expected,
                expected=expected,
                observed=observed,
            )
        )

    for name, state in states.items():
        check(f"artifact.{name}", "ok", state)
    for name, path in inputs.items():
        check(f"input.{name}", True, path.is_dir() if name in {"base", "direct"} else path.is_file())

    outer_status = _dict(loaded.get("outer_status"))
    service_status = _dict(loaded.get("service_status"))
    service_manifest = _dict(loaded.get("service_manifest"))
    status = _dict(loaded.get("status"))
    manifest = _dict(loaded.get("manifest"))
    schedule_payload = _dict(loaded.get("schedule"))
    seal = _dict(loaded.get("selection_seal"))
    validation = _dict(loaded.get("validation"))
    invocations = _dict(loaded.get("invocations"))

    check("outer.status", "success", outer_status.get("status"))
    check("outer.exit_code", 0, outer_status.get("exit_code"))
    check("outer.commit", expected_commit, outer_status.get("git_commit"))
    check("outer.workload_mode", "direct_family_pilot", outer_status.get("workload_mode"))
    check("outer.runtime_removed", True, outer_status.get("runtime_removed"))
    check("service.status", "success", service_status.get("status"))
    check("service.schema", DIRECT_FAMILY_PILOT_SERVICE_RUN_SCHEMA_VERSION, service_status.get("schema_version"))
    check("service.manifest_schema", DIRECT_FAMILY_PILOT_SERVICE_RUN_SCHEMA_VERSION, service_manifest.get("schema_version"))
    check("service.manifest_status", "success", service_manifest.get("status"))
    check("live.schema", LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION, status.get("schema_version"))
    check("live.status", "success", status.get("status"))
    check("live.error", None, status.get("error"))
    check("manifest.commit", expected_commit, _dict(manifest.get("git")).get("commit"))
    check("manifest.clean", True, _dict(manifest.get("git")).get("clean"))
    check("manifest.validation", True, _exact_validation(manifest.get("validation")))
    check("validation.exact", True, _exact_validation(validation))

    direct = None
    schedule = None
    memory = None
    suite = None
    expected_frontiers: dict[str, dict[str, Any]] = {}
    training_results = _file_map(live / "training/runs", "*.json")
    online_results = _file_map(live / "online", "*.json")
    shadow_results = _file_map(live / "shadow/runs", "*.json")
    try:
        direct = load_m15_direct_semantic_workload_bundle(
            inputs["direct"],
            base_bundle=inputs["base"],
            catalog=inputs["catalog"],
            mapping=inputs["mapping"],
        )
        schedule = compile_m15_direct_family_pilot_schedule(
            workload=direct,
            protocol=inputs["protocol"],
            predictor_policy=inputs["predictor"],
        )
        expected_observations = _training_observations(schedule, training_results)
        memory = build_m15_direct_training_memory_view(
            workload=direct,
            raw_observations=expected_observations,
            runtime_compatibility_sha256=str(
                manifest.get("runtime_compatibility_sha256")
            ),
            policy=inputs["predictor"],
            measurement_source_kind=(
                "native_counterbalanced_development_pilot"
            ),
        )
        suite = build_m15_direct_family_prediction_suite(
            workload=direct,
            base_bundle=inputs["base"],
            catalog=inputs["catalog"],
            mapping=inputs["mapping"],
            memory=memory,
            policy=inputs["predictor"],
        )
        for query_id in sorted(suite.sources):
            candidates = suite.candidate_sets[query_id]
            snapshot = suite.sources[query_id].to_snapshot(candidates)
            expected_frontiers[query_id] = select_m15_direct_semantic_frontier(
                candidates, snapshot
            ).to_dict()
        check("reconstruction.integrity", True, True)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        check("reconstruction.integrity", True, f"invalid:{exc}")
        expected_observations = []

    if schedule is not None:
        check("schedule.exact", schedule.to_dict(), schedule_payload)
        check("schedule.selection_copy", schedule.to_dict(), loaded.get("selection_schedule"))
        check("preflight.schedule", schedule.to_dict(), loaded.get("preflight_schedule"))
        preflight = _dict(loaded.get("preflight_manifest"))
        check("preflight.schema", DIRECT_FAMILY_PILOT_PREFLIGHT_SCHEMA_VERSION, preflight.get("schema_version"))
        check("preflight.sealed", True, preflight.get("sealed_before_service_start"))
        check("preflight.schedule_hash", schedule.schedule_hash, preflight.get("schedule_sha256"))
        check("preflight.cardinality", schedule.payload["selection_boundary"]["online_cardinality"], preflight.get("online_cardinality"))
        check("preflight.counts", schedule.payload["counts"], preflight.get("expected_counts"))
        check("preflight.calls", 0, preflight.get("backend_calls_before_seal"))
        check("preflight.retries", 0, preflight.get("automatic_retries"))
        check("preflight.paper_result", False, preflight.get("paper_result"))
        check("schedule.training_count", 144, len(training_results))
        check("schedule.shadow_count", 80, len(shadow_results))
        online_range = schedule.payload["counts"]["online_selected_plan_runs"]
        check(
            "schedule.online_range",
            True,
            int(online_range["minimum"]) <= len(online_results) <= int(online_range["maximum"]),
        )

    if direct is not None and schedule is not None:
        for phase, records, results in (
            ("training", schedule.payload["training_runs"], training_results),
            ("shadow", schedule.payload["shadow_runs"], shadow_results),
        ):
            for record in records:
                result = _dict(results.get(str(record["run_id"])))
                prefix = f"{phase}.{record['run_id']}"
                check(f"{prefix}.plan", record["plan_id"], result.get("plan_id"))
                check(f"{prefix}.success", True, result.get("success"))
                check(f"{prefix}.exact", True, result.get("exact_answer"))
                check(f"{prefix}.calls", 2, result.get("total_remote_calls"))
                try:
                    oracle = load_m15_parameterized_instance(
                        direct.workload_bundle, str(record["query_id"])
                    )["final_oracle"]
                    check(
                        f"{prefix}.rows",
                        oracle,
                        _dict(result.get("runtime_result")).get("final_rows"),
                    )
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    check(f"{prefix}.rows", "valid", f"invalid:{exc}")

        selected_expected: list[dict[str, Any]] = []
        for query_id in sorted(expected_frontiers):
            frontier = expected_frontiers[query_id]
            candidates = suite.candidate_sets[query_id] if suite is not None else None
            source = suite.sources[query_id] if suite is not None else None
            if candidates is not None and source is not None:
                query_root = live / "selection/queries" / query_id
                expected_artifacts = {
                    "candidate_set.json": candidates.to_dict(),
                    "prediction_source.json": source.to_dict(),
                    "estimate_snapshot.json": source.to_snapshot(candidates).to_dict(),
                    "semantic_frontier.json": frontier,
                }
                for filename, expected in expected_artifacts.items():
                    observed, state = _read_json(query_root / filename)
                    check(f"selection.{query_id}.{filename}.state", "ok", state)
                    check(f"selection.{query_id}.{filename}.exact", expected, observed)
            selected_expected.extend(
                {"base_query_id": query_id, **dict(item)}
                for item in frontier["returned_semantic_plans"]
            )
        ordered_online = [online_results[key] for key in sorted(online_results)]
        check("online.selected_count", len(selected_expected), len(ordered_online))
        for index, selected_plan in enumerate(selected_expected):
            result = _dict(ordered_online[index]) if index < len(ordered_online) else {}
            prefix = f"online.{index + 1}"
            for field in (
                "base_query_id",
                "query_id",
                "semantic_class_id",
                "plan_id",
                "physical_strategy",
                "selection_rank",
            ):
                check(f"{prefix}.{field}", selected_plan[field], result.get(field))
            check(f"{prefix}.success", True, result.get("success"))
            check(f"{prefix}.exact", True, result.get("exact_answer"))
            check(f"{prefix}.calls", 2, result.get("total_remote_calls"))
            try:
                oracle = load_m15_parameterized_instance(
                    direct.workload_bundle, str(selected_plan["query_id"])
                )["final_oracle"]
                check(
                    f"{prefix}.rows",
                    oracle,
                    _dict(result.get("runtime_result")).get("final_rows"),
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                check(f"{prefix}.rows", "valid", f"invalid:{exc}")

    observed_training = _dict(loaded.get("training_observations"))
    observed_selection_training = _dict(
        loaded.get("selection_training_observations")
    )
    check("training_observations.exact", expected_observations, observed_training.get("observations"))
    check("training_observations.selection_copy", observed_training, observed_selection_training)
    if memory is not None:
        memory_payload = memory.to_dict()
        check("memory.exact", memory_payload, loaded.get("training_memory"))
        check("memory.selection_copy", memory_payload, loaded.get("selection_training_memory"))
    if suite is not None:
        check("prediction_suite.exact", suite.to_dict(), loaded.get("prediction_suite"))
        expected_analysis = analyze_m15_direct_family_pilot(
            suite=suite,
            frontiers=expected_frontiers,
            shadow_results=shadow_results,
        )
        check("analysis.schema", DIRECT_FAMILY_PILOT_ANALYSIS_SCHEMA_VERSION, _dict(loaded.get("analysis")).get("schema_version"))
        check("analysis.exact", expected_analysis, loaded.get("analysis"))

    check("seal.schema", DIRECT_FAMILY_PILOT_SELECTION_SEAL_SCHEMA_VERSION, seal.get("schema_version"))
    seal_body = {key: value for key, value in seal.items() if key != "selection_seal_sha256"}
    check("seal.hash", content_hash(seal_body), seal.get("selection_seal_sha256"))
    selection_hashes = {
        str(path.relative_to(live)): _sha256_file(path)
        for path in sorted((live / "selection").rglob("*.json"))
        if path.is_file() and not path.is_symlink()
    }
    training_hashes = {
        str(path.relative_to(live)): _sha256_file(path)
        for path in sorted((live / "training/runs").glob("*.json"))
        if path.is_file() and not path.is_symlink()
    }
    check("seal.selection_hashes", selection_hashes, seal.get("selection_files_sha256"))
    check("seal.training_hashes", training_hashes, seal.get("training_evidence_files_sha256"))
    check("seal.before_heldout", True, seal.get("sealed_before_heldout_oracle_access"))
    check("seal.training_calls", 288, seal.get("training_backend_calls_before_seal"))
    check("seal.online_calls", 0, seal.get("online_backend_calls_before_seal"))
    check("seal.shadow_calls", 0, seal.get("shadow_backend_calls_before_seal"))
    check("seal.profile_calls", 0, seal.get("current_query_profile_calls"))
    check("seal.retries", 0, seal.get("automatic_retries"))

    events = _list(invocations.get("events"))
    online_calls = 2 * len(online_results)
    expected_phases = (
        ["training_measurement"] * 288
        + ["online_selected_execution"] * online_calls
        + ["postselection_shadow_evaluation"] * 160
    )
    check("calls.count", len(expected_phases), len(events))
    check("calls.reported_count", len(events), invocations.get("total_tool_invocations"))
    check("calls.phase_order", expected_phases, [_dict(item).get("pilot_phase") for item in events])
    check("calls.execute_only", True, all(_dict(item).get("operation") == "execute" for item in events))
    check("calls.retries", 0, invocations.get("automatic_retries"))
    check("manifest.summary", {
        "training_plan_runs": 144,
        "online_selected_plan_runs": len(online_results),
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 224 + len(online_results),
        "training_backend_calls": 288,
        "online_backend_calls": online_calls,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 448 + online_calls,
        "current_query_profile_calls": 0,
    }, manifest.get("summary"))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    check("manifest.retries", 0, manifest.get("automatic_retries"))
    check("manifest.profile_operations", [], manifest.get("current_query_observation_operations"))

    after = _tree_digest(root)
    mutated = before != after
    check("run_tree.unchanged", False, mutated)
    return M15DirectFamilyPilotEvidenceAudit(
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
        audit = audit_m15_direct_family_pilot(
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
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
