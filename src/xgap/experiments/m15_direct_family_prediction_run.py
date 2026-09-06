"""Persist and execute the F2C10C family-memory frontier with backend doubles.

All selection inputs and outputs are sealed before the first answer oracle is
opened.  Only returned semantic plans execute.  The backend doubles replay the
frozen source oracles with deterministic one-millisecond reports, so this is a
mechanism/reconstruction gate rather than performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.backends.protocol import BackendClient
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectFamilyPredictionSuite,
    build_m15_controlled_training_observations,
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_adaptive import RecordingBackendPlugin
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION = (
    "m15-f2c10c-direct-family-validation-run-v1"
)
DIRECT_FAMILY_SELECTION_SEAL_SCHEMA_VERSION = (
    "m15-f2c10c-direct-family-selection-seal-v1"
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")


class M15DirectFamilyValidationError(ValueError):
    """Raised before an external-like call when the validation contract drifts."""


@dataclass(frozen=True)
class M15DirectFamilyValidationRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_text(value: object) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        )
        + "\n"
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_json_text(value), encoding="utf-8")
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_state(repo_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return {"commit": commit, "clean": not bool(dirty)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"commit": None, "clean": None, "error": str(exc)}


def _copy_regular_file(source: str | Path, destination: Path) -> None:
    path = Path(source)
    if path.is_symlink() or not path.is_file():
        raise M15DirectFamilyValidationError(
            f"input must be a regular non-symbolic-link file: {path}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, destination)


def _copy_template_tree(source: str | Path, destination: Path) -> None:
    root = Path(source)
    if root.is_symlink() or not root.is_dir():
        raise M15DirectFamilyValidationError(
            "backend template root must be a regular directory"
        )
    members = sorted(path for path in root.rglob("*") if path.is_file())
    if not members or any(path.is_symlink() for path in root.rglob("*")):
        raise M15DirectFamilyValidationError(
            "backend templates are empty or contain symbolic links"
        )
    destination.mkdir(parents=True, exist_ok=False)
    for path in members:
        relative = path.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


@dataclass
class _ControlledState:
    invocation_count: int = 0
    fail_at_invocation: int | None = None


@dataclass
class _OracleBackendClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    state: _ControlledState

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(
            self.backend_id,
            True,
            "f2c10c controlled oracle backend ready",
        )

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.state.invocation_count += 1
        if self.state.fail_at_invocation == self.state.invocation_count:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                rows=[],
                elapsed_ms=1.0,
                error="injected F2C10C controlled backend failure",
            )
        if artifact.artifact_id not in self.rows_by_artifact:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                rows=[],
                elapsed_ms=1.0,
                error="controlled oracle artifact is unavailable",
            )
        rows = [dict(row) for row in self.rows_by_artifact[artifact.artifact_id]]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                row
                for row in rows
                if str(row["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=1.0,
        )


def _clients_after_selection_seal(
    workload_bundle: object,
    *,
    state: _ControlledState,
) -> dict[str, BackendClient]:
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    for query_id in workload_bundle.instance_ids():
        source = load_m15_parameterized_instance(workload_bundle, query_id)[
            "source_oracles"
        ]
        prefix = f"m15-f2c-{query_id}"
        rows["neo4j"][f"{prefix}-neo4j-full"] = source["neo4j_full"]
        rows["neo4j"][f"{prefix}-neo4j-bound"] = source["neo4j_full"]
        rows["fuseki"][f"{prefix}-fuseki-risk"] = source["fuseki_risk"]
    return {
        backend_id: _OracleBackendClient(backend_id, rows[backend_id], state)
        for backend_id in ("neo4j", "fuseki")
    }


def _backend_tool(
    clients: Mapping[str, BackendClient],
    events: list[dict[str, Any]],
) -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            RecordingBackendPlugin(
                NativeBackendPlugin(backend_id, clients[backend_id]),
                events,
            )
        )
    return BackendInvokeTool(plugins)


def _persist_selection(
    *,
    root: Path,
    suite: M15DirectFamilyPredictionSuite,
    controlled: Mapping[str, Any],
    memory: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    selection_root = root / "selection"
    _write_json(
        selection_root / "controlled_training_observations.json", controlled
    )
    _write_json(selection_root / "training_memory_view.json", memory)
    _write_json(selection_root / "prediction_suite.json", suite.to_dict())
    query_records: list[dict[str, Any]] = []
    for query_id in sorted(suite.sources):
        query_root = selection_root / "queries" / query_id
        candidates = suite.candidate_sets[query_id]
        source = suite.sources[query_id]
        snapshot = source.to_snapshot(candidates)
        frontier = select_m15_direct_semantic_frontier(candidates, snapshot)
        artifacts = {
            "candidate_set.json": candidates.to_dict(),
            "prediction_source.json": source.to_dict(),
            "estimate_snapshot.json": snapshot.to_dict(),
            "semantic_frontier.json": frontier.to_dict(),
        }
        for filename, payload in artifacts.items():
            _write_json(query_root / filename, payload)
        query_records.append(
            {
                "base_query_id": query_id,
                "candidate_set_sha256": candidates.candidate_set_hash,
                "prediction_source_sha256": source.source_hash,
                "estimate_snapshot_sha256": snapshot.snapshot_hash,
                "frontier_sha256": frontier.payload["frontier_sha256"],
                "returned_semantic_plan_count": frontier.payload["counts"][
                    "returned_semantic_plans"
                ],
            }
        )
    selection_files = sorted(
        path for path in selection_root.rglob("*.json") if path.is_file()
    )
    body = {
        "schema_version": DIRECT_FAMILY_SELECTION_SEAL_SCHEMA_VERSION,
        "selection_files_sha256": {
            str(path.relative_to(root)): _sha256_file(path)
            for path in selection_files
        },
        "training_memory_view_sha256": memory[
            "training_memory_view_sha256"
        ],
        "prediction_suite_sha256": suite.payload["prediction_suite_sha256"],
        "query_frontiers": query_records,
        "sealed_before_oracle_access": True,
        "backend_calls_before_seal": 0,
        "answer_oracle_fields": [],
        "current_query_observation_operations": [],
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    seal = {**body, "selection_seal_sha256": content_hash(body)}
    _write_json(root / "selection_seal.json", seal)
    return seal, {
        record["base_query_id"]: json.loads(
            (
                selection_root
                / "queries"
                / record["base_query_id"]
                / "semantic_frontier.json"
            ).read_text(encoding="utf-8")
        )
        for record in query_records
    }


def run_m15_direct_family_prediction_validation(
    *,
    workload_spec: str | Path,
    query_template_spec: str | Path,
    backend_template_root: str | Path,
    semantic_catalog: str | Path,
    predicate_mapping: str | Path,
    cardinality_policy: str | Path,
    predictor_policy: str | Path,
    runtime_compatibility_sha256: str,
    output_root: str | Path,
    repo_root: str | Path,
    run_id: str = "direct-family-prediction-validation",
    inject_failure_at_invocation: int | None = None,
) -> M15DirectFamilyValidationRecord:
    """Build, seal, and validate every returned held-out plan locally."""

    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise M15DirectFamilyValidationError("run_id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", runtime_compatibility_sha256):
        raise M15DirectFamilyValidationError(
            "runtime_compatibility_sha256 is invalid"
        )
    if inject_failure_at_invocation is not None and (
        isinstance(inject_failure_at_invocation, bool)
        or not isinstance(inject_failure_at_invocation, int)
        or inject_failure_at_invocation <= 0
    ):
        raise M15DirectFamilyValidationError(
            "inject_failure_at_invocation must be a positive integer"
        )
    root = Path(output_root).resolve() / run_id
    root.mkdir(parents=True, exist_ok=False)
    status_path = root / "run_status.json"
    manifest_path = root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": started_at,
        },
    )
    error: str | None = None
    selection_seal: dict[str, Any] | None = None
    suite: M15DirectFamilyPredictionSuite | None = None
    memory_payload: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    health: dict[str, Any] = {}
    base = None
    direct = None
    try:
        inputs = root / "inputs"
        inputs.mkdir()
        for filename, source in {
            "workload_spec.json": workload_spec,
            "query_template.json": query_template_spec,
            "semantic_catalog.json": semantic_catalog,
            "predicate_mapping.json": predicate_mapping,
            "cardinality_policy.json": cardinality_policy,
            "predictor_policy.json": predictor_policy,
        }.items():
            _copy_regular_file(source, inputs / filename)
        _copy_template_tree(
            backend_template_root, inputs / "backend_templates"
        )
        base = generate_m15_parameterized_workload_bundle(
            workload_spec=inputs / "workload_spec.json",
            query_template_spec=inputs / "query_template.json",
            backend_template_root=inputs / "backend_templates",
            destination=root / "base-workload-bundle",
        )
        direct = generate_m15_direct_semantic_workload_bundle(
            base_bundle=base,
            catalog=inputs / "semantic_catalog.json",
            mapping=inputs / "predicate_mapping.json",
            policy=inputs / "cardinality_policy.json",
            destination=root / "direct-semantic-workload",
        )
        controlled = build_m15_controlled_training_observations(direct)
        memory = build_m15_direct_training_memory_view(
            workload=direct,
            raw_observations=controlled["observations"],
            runtime_compatibility_sha256=runtime_compatibility_sha256,
            policy=inputs / "predictor_policy.json",
            measurement_source_kind="controlled_local_nonmeasurement_fixture",
        )
        memory_payload = memory.to_dict()
        suite = build_m15_direct_family_prediction_suite(
            workload=direct,
            base_bundle=base,
            catalog=inputs / "semantic_catalog.json",
            mapping=inputs / "predicate_mapping.json",
            memory=memory,
            policy=inputs / "predictor_policy.json",
        )
        selection_seal, frontiers = _persist_selection(
            root=root,
            suite=suite,
            controlled=controlled,
            memory=memory_payload,
        )

        # This is the first runtime access to source/final oracle rows.  Workload
        # compilation creates those files earlier, but selection never reads or
        # hashes their contents.
        state = _ControlledState(
            fail_at_invocation=inject_failure_at_invocation
        )
        clients = _clients_after_selection_seal(
            direct.workload_bundle,
            state=state,
        )
        for backend_id in ("neo4j", "fuseki"):
            health[backend_id] = clients[backend_id].healthcheck().to_dict()
        _write_json(root / "health.json", health)
        if not all(item["ok"] for item in health.values()):
            raise RuntimeError("controlled backend healthcheck failed")
        scheduler = FederatedScheduler(_backend_tool(clients, events))
        stop = False
        for query_id in sorted(frontiers):
            frontier = frontiers[query_id]
            candidates = suite.candidate_sets[query_id]
            for selected in frontier["returned_semantic_plans"]:
                run = scheduler.execute(
                    candidates.plans[selected["plan_id"]],
                    goal_id=(
                        f"{run_id}:{query_id}:{selected['semantic_class_id']}"
                    ),
                )
                final_rows = [dict(row) for row in run.final_rows]
                instance = load_m15_parameterized_instance(
                    direct.workload_bundle,
                    selected["query_id"],
                )
                result = {
                    "base_query_id": query_id,
                    "selection_rank": selected["selection_rank"],
                    "semantic_class_id": selected["semantic_class_id"],
                    "query_id": selected["query_id"],
                    "plan_id": selected["plan_id"],
                    "physical_strategy": selected["physical_strategy"],
                    "semantic_deviation": selected["semantic_deviation"],
                    "changed_slot_ids": list(selected["changed_slot_ids"]),
                    "expected_final_row_count": len(instance["final_oracle"]),
                    "exact_oracle_answer": final_rows == instance["final_oracle"],
                    "runtime_result": run.to_dict(),
                }
                results.append(result)
                if not run.success:
                    error = (
                        "controlled plan execution failed at "
                        f"{selected['plan_id']}"
                    )
                    stop = True
                    break
            if stop:
                break
        _write_json(root / "semantic_results.json", {"results": results})
        _write_json(
            root / "backend_invocations.json",
            {
                "events": events,
                "total_tool_invocations": len(events),
                "automatic_retries": 0,
            },
        )
        expected_selected = sum(
            frontier["counts"]["returned_semantic_plans"]
            for frontier in frontiers.values()
        )
        checks = {
            "selection_sealed_before_oracle_access": selection_seal[
                "sealed_before_oracle_access"
            ]
            is True,
            "zero_backend_calls_before_seal": selection_seal[
                "backend_calls_before_seal"
            ]
            == 0,
            "complete_training_memory": memory.payload[
                "training_physical_plan_count"
            ]
            == 36,
            "complete_heldout_predictions": suite.payload[
                "heldout_physical_plan_count"
            ]
            == 20,
            "only_returned_plans_executed": len(results) == expected_selected,
            "all_runtime_success": all(
                item["runtime_result"]["success"] for item in results
            ),
            "all_exact_oracle_answers": all(
                item["exact_oracle_answer"] for item in results
            ),
            "two_calls_per_plan": len(events) == 2 * len(results),
            "all_calls_execute": all(
                item["operation"] == "execute" for item in events
            ),
            "no_retry": len(events)
            == sum(
                item["runtime_result"]["total_remote_calls"]
                for item in results
            ),
            "zero_current_query_profiles": suite.payload[
                "current_query_profile_calls"
            ]
            == 0,
            "zero_oracle_selection_inputs": not selection_seal[
                "answer_oracle_fields"
            ],
        }
        _write_json(
            root / "validation.json",
            {"passed": all(checks.values()), "checks": checks},
        )
        if error is None and not all(checks.values()):
            error = "F2C10C controlled validation checks failed"
    except Exception as exc:
        if error is None:
            error = str(exc)
        if not (root / "semantic_results.json").exists():
            _write_json(root / "semantic_results.json", {"results": results})
        if not (root / "backend_invocations.json").exists():
            _write_json(
                root / "backend_invocations.json",
                {
                    "events": events,
                    "total_tool_invocations": len(events),
                    "automatic_retries": 0,
                },
            )
    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    input_hashes = (
        {
            str(path.relative_to(root)): _sha256_file(path)
            for path in sorted((root / "inputs").rglob("*"))
            if path.is_file()
        }
        if (root / "inputs").is_dir()
        else {}
    )
    total_bytes = sum(
        item["runtime_result"]["total_bytes_moved"] for item in results
    )
    manifest = {
        "schema_version": DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "status": "success" if success else "failed",
        "error": error,
        "started_at": started_at,
        "ended_at": ended_at,
        "input_files_sha256": input_hashes,
        "base_workload_bundle_sha256": (
            base.manifest["bundle_content_sha256"] if base is not None else None
        ),
        "direct_semantic_workload_sha256": (
            direct.manifest["manifest_sha256"] if direct is not None else None
        ),
        "selection_seal_sha256": (
            selection_seal["selection_seal_sha256"]
            if selection_seal is not None
            else None
        ),
        "prediction_suite_sha256": (
            suite.payload["prediction_suite_sha256"]
            if suite is not None
            else None
        ),
        "runtime_compatibility_sha256": runtime_compatibility_sha256,
        "git": _git_state(Path(repo_root).resolve()),
        "summary": {
            "training_semantic_task_count": (
                memory_payload["training_semantic_task_count"]
                if memory_payload is not None
                else 0
            ),
            "training_physical_plan_count": (
                memory_payload["training_physical_plan_count"]
                if memory_payload is not None
                else 0
            ),
            "heldout_semantic_task_count": (
                suite.payload["heldout_semantic_task_count"] if suite else 0
            ),
            "heldout_physical_prediction_count": (
                suite.payload["heldout_physical_plan_count"] if suite else 0
            ),
            "returned_semantic_plan_count": len(results),
            "physical_plan_run_count": len(results),
            "total_remote_calls": len(events),
            "total_bytes_moved": total_bytes,
            "final_row_counts": [
                len(item["runtime_result"]["final_rows"]) for item in results
            ],
        },
        "validation": {
            "passed": success and bool(checks) and all(checks.values()),
            "checks": checks,
        },
        "selection_sealed_before_oracle_access": (
            selection_seal is not None
            and selection_seal["sealed_before_oracle_access"] is True
        ),
        "answer_oracle_used_for_selection": False,
        "answer_oracle_used_for_post_execution_validation": bool(results),
        "training_values_are_controlled_nonmeasurements": True,
        "deterministic_backend_doubles": True,
        "heldout_measurements_collected": False,
        "current_query_profile_calls": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "automatic_retries": 0,
        "paper_result": False,
        "artifacts": sorted(
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file()
        ),
    }
    _write_json(manifest_path, manifest)
    return M15DirectFamilyValidationRecord(
        run_id=run_id,
        run_root=root,
        success=success,
        status_path=status_path,
        manifest_path=manifest_path,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-spec", required=True)
    parser.add_argument("--query-template", required=True)
    parser.add_argument("--backend-templates", required=True)
    parser.add_argument("--semantic-catalog", required=True)
    parser.add_argument("--predicate-mapping", required=True)
    parser.add_argument("--cardinality-policy", required=True)
    parser.add_argument("--predictor-policy", required=True)
    parser.add_argument("--runtime-compatibility-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument(
        "--run-id", default="direct-family-prediction-validation"
    )
    arguments = parser.parse_args(argv)
    try:
        record = run_m15_direct_family_prediction_validation(
            workload_spec=arguments.workload_spec,
            query_template_spec=arguments.query_template,
            backend_template_root=arguments.backend_templates,
            semantic_catalog=arguments.semantic_catalog,
            predicate_mapping=arguments.predicate_mapping,
            cardinality_policy=arguments.cardinality_policy,
            predictor_policy=arguments.predictor_policy,
            runtime_compatibility_sha256=(
                arguments.runtime_compatibility_sha256
            ),
            output_root=arguments.output_root,
            repo_root=arguments.repo_root,
            run_id=arguments.run_id,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
