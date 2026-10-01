"""Read-only reconstruction audit for one controlled F2C10C validation run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    build_m15_controlled_training_observations,
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_family_prediction_run import (
    DIRECT_FAMILY_SELECTION_SEAL_SCHEMA_VERSION,
    DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


DIRECT_FAMILY_VALIDATION_AUDIT_SCHEMA_VERSION = (
    "m15-f2c10c-direct-family-validation-evidence-audit-v1"
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
class DirectFamilyValidationEvidenceCheck:
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
class M15DirectFamilyValidationEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[DirectFamilyValidationEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DIRECT_FAMILY_VALIDATION_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [item.to_dict() for item in self.checks],
            "run_tree_mutated": self.run_tree_mutated,
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


def _selection_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha256_file(path)
        for path in sorted((root / "selection").rglob("*.json"))
        if path.is_file() and not path.is_symlink()
    }


def audit_m15_direct_family_prediction_validation(
    *,
    run_root: str | Path,
    expected_commit: str,
) -> M15DirectFamilyValidationEvidenceAudit:
    """Rebuild the family memory, predictions, and frontiers read-only."""

    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    run = selected.resolve()
    if not run.is_dir():
        raise ValueError("run_root must be a real directory")
    before = _tree_digest(run)

    paths = {
        "status": run / "run_status.json",
        "manifest": run / "run_manifest.json",
        "selection_seal": run / "selection_seal.json",
        "controlled_training": (
            run / "selection/controlled_training_observations.json"
        ),
        "training_memory": run / "selection/training_memory_view.json",
        "prediction_suite": run / "selection/prediction_suite.json",
        "semantic_results": run / "semantic_results.json",
        "backend_invocations": run / "backend_invocations.json",
        "validation": run / "validation.json",
        "health": run / "health.json",
    }
    loaded: dict[str, Any] = {}
    states: dict[str, str] = {}
    for key, path in paths.items():
        loaded[key], states[key] = _read_json(path)

    checks: list[DirectFamilyValidationEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            DirectFamilyValidationEvidenceCheck(
                check_id,
                observed == expected,
                expected,
                observed,
            )
        )

    for key in paths:
        check(f"artifact.{key}", "ok", states[key])

    expected_base = None
    expected_direct = None
    expected_controlled: dict[str, Any] | None = None
    expected_memory = None
    expected_suite = None
    expected_frontiers: dict[str, dict[str, Any]] = {}
    expected_instances: dict[str, dict[str, Any]] = {}
    try:
        inputs = run / "inputs"
        with tempfile.TemporaryDirectory(prefix="xgap-f2c10c-audit-") as temp:
            scratch = Path(temp)
            expected_base = generate_m15_parameterized_workload_bundle(
                workload_spec=inputs / "workload_spec.json",
                query_template_spec=inputs / "query_template.json",
                backend_template_root=inputs / "backend_templates",
                destination=scratch / "base",
            )
            expected_direct = generate_m15_direct_semantic_workload_bundle(
                base_bundle=expected_base,
                catalog=inputs / "semantic_catalog.json",
                mapping=inputs / "predicate_mapping.json",
                policy=inputs / "cardinality_policy.json",
                destination=scratch / "direct",
            )
            expected_controlled = build_m15_controlled_training_observations(
                expected_direct
            )
            manifest = _dict(loaded.get("manifest"))
            expected_memory = build_m15_direct_training_memory_view(
                workload=expected_direct,
                raw_observations=expected_controlled["observations"],
                runtime_compatibility_sha256=str(
                    manifest.get("runtime_compatibility_sha256")
                ),
                policy=inputs / "predictor_policy.json",
                measurement_source_kind=(
                    "controlled_local_nonmeasurement_fixture"
                ),
            )
            expected_suite = build_m15_direct_family_prediction_suite(
                workload=expected_direct,
                base_bundle=expected_base,
                catalog=inputs / "semantic_catalog.json",
                mapping=inputs / "predicate_mapping.json",
                memory=expected_memory,
                policy=inputs / "predictor_policy.json",
            )
            for query_id in sorted(expected_suite.sources):
                candidates = expected_suite.candidate_sets[query_id]
                snapshot = expected_suite.sources[query_id].to_snapshot(
                    candidates
                )
                expected_frontiers[query_id] = (
                    select_m15_direct_semantic_frontier(
                        candidates, snapshot
                    ).to_dict()
                )
                for selected_plan in expected_frontiers[query_id][
                    "returned_semantic_plans"
                ]:
                    selected_query_id = str(selected_plan["query_id"])
                    expected_instances[selected_query_id] = (
                        load_m15_parameterized_instance(
                            expected_direct.workload_bundle,
                            selected_query_id,
                        )
                    )
        check("reconstruction.integrity", True, True)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        check("reconstruction.integrity", True, f"invalid:{exc}")

    status = _dict(loaded.get("status"))
    manifest = _dict(loaded.get("manifest"))
    seal = _dict(loaded.get("selection_seal"))
    controlled = _dict(loaded.get("controlled_training"))
    memory = _dict(loaded.get("training_memory"))
    suite = _dict(loaded.get("prediction_suite"))
    results = _list(_dict(loaded.get("semantic_results")).get("results"))
    invocations = _dict(loaded.get("backend_invocations"))
    validation = _dict(loaded.get("validation"))
    health = _dict(loaded.get("health"))

    check("status.schema", DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION, status.get("schema_version"))
    check("status.status", "success", status.get("status"))
    check("status.error", None, status.get("error"))
    check("manifest.schema", DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION, manifest.get("schema_version"))
    check("manifest.status", "success", manifest.get("status"))
    check("manifest.error", None, manifest.get("error"))
    check("manifest.git_commit", expected_commit, _dict(manifest.get("git")).get("commit"))
    check("manifest.git_clean", True, _dict(manifest.get("git")).get("clean"))
    check("manifest.validation", True, _exact_validation(manifest.get("validation")))
    check("validation.exact", True, _exact_validation(validation))
    check("health.backends", {"neo4j", "fuseki"}, set(health))
    check("health.ok", True, bool(health) and all(_dict(item).get("ok") is True for item in health.values()))

    if expected_base is not None:
        check("base.hash", expected_base.manifest["bundle_content_sha256"], manifest.get("base_workload_bundle_sha256"))
    if expected_direct is not None:
        check("direct.hash", expected_direct.manifest["manifest_sha256"], manifest.get("direct_semantic_workload_sha256"))
    if expected_controlled is not None:
        check("controlled_training.exact", expected_controlled, controlled)
    if expected_memory is not None:
        expected_memory_payload = expected_memory.to_dict()
        check("training_memory.exact", expected_memory_payload, memory)
        check("training_memory.count", 36, memory.get("training_physical_plan_count"))
        check("training_memory.heldout_ids", [], memory.get("heldout_task_ids_observed"))
        check("training_memory.oracle_inputs", [], memory.get("oracle_inputs"))
    if expected_suite is not None:
        expected_suite_payload = expected_suite.to_dict()
        check("prediction_suite.exact", expected_suite_payload, suite)
        check("prediction_suite.heldout_plans", 20, suite.get("heldout_physical_plan_count"))
        check("prediction_suite.profile_calls", 0, suite.get("current_query_profile_calls"))
        check("prediction_suite.oracle_inputs", [], suite.get("oracle_inputs"))

    check("seal.schema", DIRECT_FAMILY_SELECTION_SEAL_SCHEMA_VERSION, seal.get("schema_version"))
    seal_body = {key: value for key, value in seal.items() if key != "selection_seal_sha256"}
    check("seal.content_hash", content_hash(seal_body), seal.get("selection_seal_sha256"))
    check("seal.file_hashes", _selection_hashes(run), seal.get("selection_files_sha256"))
    check("seal.before_oracle", True, seal.get("sealed_before_oracle_access"))
    check("seal.backend_calls", 0, seal.get("backend_calls_before_seal"))
    check("seal.oracle_fields", [], seal.get("answer_oracle_fields"))
    check("seal.current_query_operations", [], seal.get("current_query_observation_operations"))
    check("seal.postexecution", False, seal.get("post_execution_measurements_used"))
    check("seal.automatic_retries", 0, seal.get("automatic_retries"))
    check("manifest.seal_hash", seal.get("selection_seal_sha256"), manifest.get("selection_seal_sha256"))
    check("manifest.profile_calls", 0, manifest.get("current_query_profile_calls"))
    check("manifest.selection_oracle", False, manifest.get("answer_oracle_used_for_selection"))
    check("manifest.heldout_measurements", False, manifest.get("heldout_measurements_collected"))
    check("manifest.automatic_retries", 0, manifest.get("automatic_retries"))
    check("manifest.paper_result", False, manifest.get("paper_result"))

    expected_selected: list[dict[str, Any]] = []
    if expected_suite is not None:
        expected_query_records: list[dict[str, Any]] = []
        for query_id in sorted(expected_suite.sources):
            candidates = expected_suite.candidate_sets[query_id]
            source = expected_suite.sources[query_id]
            snapshot = source.to_snapshot(candidates)
            frontier = expected_frontiers[query_id]
            query_root = run / "selection" / "queries" / query_id
            query_artifacts = {
                "candidate_set.json": candidates.to_dict(),
                "prediction_source.json": source.to_dict(),
                "estimate_snapshot.json": snapshot.to_dict(),
                "semantic_frontier.json": frontier,
            }
            for filename, expected in query_artifacts.items():
                observed, state = _read_json(query_root / filename)
                check(f"query.{query_id}.{filename}.state", "ok", state)
                check(f"query.{query_id}.{filename}.exact", expected, observed)
            expected_query_records.append(
                {
                    "base_query_id": query_id,
                    "candidate_set_sha256": candidates.candidate_set_hash,
                    "prediction_source_sha256": source.source_hash,
                    "estimate_snapshot_sha256": snapshot.snapshot_hash,
                    "frontier_sha256": frontier["frontier_sha256"],
                    "returned_semantic_plan_count": frontier["counts"][
                        "returned_semantic_plans"
                    ],
                }
            )
            expected_selected.extend(
                {"base_query_id": query_id, **dict(item)}
                for item in frontier["returned_semantic_plans"]
            )
        check("seal.query_frontiers", expected_query_records, seal.get("query_frontiers"))

    check("results.count", len(expected_selected), len(results))
    expected_calls: list[tuple[str, str]] = []
    for index, selected_plan in enumerate(expected_selected):
        result = _dict(results[index]) if index < len(results) else {}
        prefix = f"result.{index}"
        for field in (
            "base_query_id",
            "selection_rank",
            "semantic_class_id",
            "query_id",
            "plan_id",
            "physical_strategy",
            "semantic_deviation",
            "changed_slot_ids",
        ):
            check(f"{prefix}.{field}", selected_plan[field], result.get(field))
        runtime = _dict(result.get("runtime_result"))
        check(f"{prefix}.success", True, runtime.get("success"))
        check(f"{prefix}.remote_calls", 2, runtime.get("total_remote_calls"))
        instance = expected_instances.get(str(selected_plan["query_id"]))
        if instance is not None:
            check(f"{prefix}.rows", instance["final_oracle"], runtime.get("final_rows"))
            check(f"{prefix}.exact_marker", True, result.get("exact_oracle_answer"))
            check(f"{prefix}.row_count", len(instance["final_oracle"]), result.get("expected_final_row_count"))
        if expected_suite is not None:
            plan = expected_suite.candidate_sets[
                selected_plan["base_query_id"]
            ].plans[selected_plan["plan_id"]]
            for node in plan.nodes:
                backend_id = node.parameters.get("backend_id")
                artifact = node.parameters.get("artifact")
                if backend_id and isinstance(artifact, Mapping):
                    expected_calls.append((str(backend_id), str(artifact["artifact_id"])))

    events = _list(invocations.get("events"))
    observed_calls = [
        (str(_dict(item).get("backend_id")), str(_dict(item).get("artifact_id")))
        for item in events
    ]
    check("invocations.count", 2 * len(expected_selected), invocations.get("total_tool_invocations"))
    check("invocations.event_count", 2 * len(expected_selected), len(events))
    check("invocations.execute_only", True, all(_dict(item).get("operation") == "execute" for item in events))
    check("invocations.selected_only", Counter(expected_calls), Counter(observed_calls))
    check("invocations.automatic_retries", 0, invocations.get("automatic_retries"))

    summary = _dict(manifest.get("summary"))
    check("summary.training_tasks", 18, summary.get("training_semantic_task_count"))
    check("summary.training_plans", 36, summary.get("training_physical_plan_count"))
    check("summary.heldout_tasks", 10, summary.get("heldout_semantic_task_count"))
    check("summary.heldout_predictions", 20, summary.get("heldout_physical_prediction_count"))
    check("summary.returned", len(expected_selected), summary.get("returned_semantic_plan_count"))
    check("summary.plan_runs", len(results), summary.get("physical_plan_run_count"))
    check("summary.remote_calls", len(events), summary.get("total_remote_calls"))
    check("summary.bytes", sum(_dict(item.get("runtime_result")).get("total_bytes_moved", 0) for item in results), summary.get("total_bytes_moved"))
    check("summary.row_counts", [len(_list(_dict(item.get("runtime_result")).get("final_rows"))) for item in results], summary.get("final_row_counts"))

    after = _tree_digest(run)
    mutated = before != after
    check("run_tree.unchanged", False, mutated)
    success = bool(checks) and all(item.passed for item in checks)
    return M15DirectFamilyValidationEvidenceAudit(
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
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)
    try:
        audit = audit_m15_direct_family_prediction_validation(
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
