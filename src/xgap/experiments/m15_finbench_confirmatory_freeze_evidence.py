"""Independently reconstruct the author-approved FinBench freeze gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_artifacts import SF0_1_LOCK_PATH
from xgap.experiments.m15_finbench_confirmatory_freeze_job import (
    FINBENCH_CONFIRMATORY_FREEZE_JOB_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION,
    _artifact_files,
)
from xgap.experiments.m15_finbench_confirmatory_population_evidence import (
    audit_finbench_confirmatory_population,
)
from xgap.experiments.m15_finbench_confirmatory_schedule import (
    build_finbench_confirmatory_schedule,
)
from xgap.experiments.m15_finbench_confirmatory_workload import (
    DEFAULT_FAMILY_CONTRACT_PATH,
    build_finbench_confirmatory_population_approval,
    build_finbench_confirmatory_workload,
)
from xgap.experiments.m15_finbench_paper_protocol import (
    DEFAULT_AUTHOR_SELECTION_PATH,
    DEFAULT_PROTOCOL_PATH,
)


FINBENCH_CONFIRMATORY_FREEZE_AUDIT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-freeze-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class FinBenchConfirmatoryFreezeCheck:
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
class FinBenchConfirmatoryFreezeAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[FinBenchConfirmatoryFreezeCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FINBENCH_CONFIRMATORY_FREEZE_AUDIT_SCHEMA_VERSION,
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


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _file_sha256(path: Path) -> str:
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


def _directory_files(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"artifact tree contains a symbolic link: {path}")
        if path.is_file():
            result[str(path.relative_to(root))] = _file_sha256(path)
    return result


def audit_finbench_confirmatory_freeze(
    *,
    run_root: str | Path,
    archive: str | Path,
    population_run_root: str | Path,
    population_audit: str | Path,
    population_expected_commit: str,
    expected_commit: str,
    lock_path: str | Path = SF0_1_LOCK_PATH,
    protocol: str | Path = DEFAULT_PROTOCOL_PATH,
    author_selection: str | Path = DEFAULT_AUTHOR_SELECTION_PATH,
    family_contract: str | Path = DEFAULT_FAMILY_CONTRACT_PATH,
) -> FinBenchConfirmatoryFreezeAudit:
    if _COMMIT.fullmatch(expected_commit) is None or _COMMIT.fullmatch(
        population_expected_commit
    ) is None:
        raise ValueError("expected commits must be full lowercase Git commits")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("run_root must be a real directory")
    before = _tree_digest(root)
    status_value, status_state = _read_json(root / "run_status.json")
    manifest_value, manifest_state = _read_json(root / "run_manifest.json")
    selection_value, selection_state = _read_json(
        root / "author_selection_snapshot.json"
    )
    approval_value, approval_state = _read_json(root / "population_approval.json")
    schedule_value, schedule_state = _read_json(root / "measurement_schedule.json")
    workload_value, workload_state = _read_json(
        root / "confirmatory-workload/workload_manifest.json"
    )
    status = _mapping(status_value)
    manifest = _mapping(manifest_value)
    selection = _mapping(selection_value)
    approval = _mapping(approval_value)
    schedule = _mapping(schedule_value)
    workload = _mapping(workload_value)
    checks: list[FinBenchConfirmatoryFreezeCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            FinBenchConfirmatoryFreezeCheck(
                check_id=check_id,
                passed=expected == observed,
                expected=expected,
                observed=observed,
            )
        )

    check("artifact.status", "ok", status_state)
    check("artifact.manifest", "ok", manifest_state)
    check("artifact.selection", "ok", selection_state)
    check("artifact.approval", "ok", approval_state)
    check("artifact.schedule", "ok", schedule_state)
    check("artifact.workload", "ok", workload_state)
    check("status.schema", FINBENCH_CONFIRMATORY_FREEZE_JOB_SCHEMA_VERSION, status.get("schema_version"))
    check("status.status", "success", status.get("status"))
    check("status.exit_code", 0, status.get("exit_code"))
    check("status.commit", expected_commit, status.get("git_commit"))
    check("status.mode", "finbench_confirmatory_freeze", status.get("workload_mode"))
    check("status.execution_authority", False, status.get("confirmatory_execution_authorized"))
    check("status.paper_result", False, status.get("paper_result"))
    check("manifest.schema", FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION, manifest.get("schema_version"))
    check("manifest.status", "success", manifest.get("status"))
    check("manifest.commit", expected_commit, _mapping(manifest.get("git")).get("commit"))
    check("manifest.clean", True, _mapping(manifest.get("git")).get("clean"))
    check(
        "manifest.hash",
        content_hash({key: value for key, value in manifest.items() if key != "manifest_sha256"}),
        manifest.get("manifest_sha256"),
    )
    check("manifest.zero_calls", {
        "backend_calls": 0,
        "current_query_profile_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
    }, dict(_mapping(manifest.get("external_call_counts"))))
    check("manifest.execution_authority", False, manifest.get("confirmatory_execution_authorized"))
    check("manifest.retry", 0, manifest.get("automatic_retries"))
    check("manifest.paper_result", False, manifest.get("paper_result"))
    check("schedule.execution_authority", False, schedule.get("confirmatory_execution_authorized"))
    check("schedule.plan_runs", 1888, _mapping(schedule.get("expected_counts")).get("total_plan_runs"))
    check("schedule.backend_calls", 3776, _mapping(schedule.get("expected_counts")).get("total_backend_calls"))
    check("schedule.inferential_queries", 32, _mapping(schedule.get("expected_counts")).get("inferential_query_count"))
    check("workload.population", "m15-finbench-confirmatory-48-v1", workload.get("population_id"))
    check("workload.instance_count", 48, workload.get("instance_count"))
    check("workload.execution_authority", False, workload.get("confirmatory_execution_authorized"))

    try:
        saved_population_audit, saved_state = _read_json(Path(population_audit))
        check("population.audit_artifact", "ok", saved_state)
        rebuilt_population_audit = audit_finbench_confirmatory_population(
            run_root=population_run_root,
            archive=archive,
            expected_commit=population_expected_commit,
            lock_path=lock_path,
        ).to_dict()
        check("population.audit_replay", saved_population_audit, rebuilt_population_audit)
        registry_value, registry_state = _read_json(
            Path(population_run_root).resolve() / "population_registry.json"
        )
        check("population.registry_artifact", "ok", registry_state)
        registry = dict(_mapping(registry_value))
        source_selection_value, source_selection_state = _read_json(Path(author_selection))
        check("source.author_selection", "ok", source_selection_state)
        check("author_selection.snapshot", source_selection_value, dict(selection))
        rebuilt_approval = build_finbench_confirmatory_population_approval(
            registry,
            selected_population_option_id="m15-finbench-confirmatory-48-v1",
            approval_id="m15-finbench-confirmatory-option-a-approval-v1",
            authority_source_id=str(selection.get("authority_source_id")),
        )
        check("population.approval_reconstruction", rebuilt_approval, dict(approval))
        with tempfile.TemporaryDirectory(prefix="xgap-confirmatory-freeze-audit-") as temporary:
            rebuilt_root = Path(temporary) / "confirmatory-workload"
            rebuilt_workload = build_finbench_confirmatory_workload(
                archive_path=archive,
                population_registry=registry,
                population_approval=rebuilt_approval,
                output_root=rebuilt_root,
                lock_path=lock_path,
                family_contract=family_contract,
            )
            check("workload.manifest_reconstruction", rebuilt_workload, dict(workload))
            check(
                "workload.file_reconstruction",
                _directory_files(root / "confirmatory-workload"),
                _directory_files(rebuilt_root),
            )
            rebuilt_schedule = build_finbench_confirmatory_schedule(
                workload_root=rebuilt_root,
                protocol=protocol,
                author_selection=source_selection_value,
            ).to_dict()
            check("schedule.reconstruction", rebuilt_schedule, dict(schedule))
        check("manifest.artifact_files", _artifact_files(root), dict(_mapping(manifest.get("artifact_files"))))
        check("manifest.selection_hash", selection.get("selection_sha256"), manifest.get("author_selection_sha256"))
        check("manifest.approval_hash", approval.get("approval_sha256"), manifest.get("population_approval_sha256"))
        check("manifest.workload_hash", workload.get("workload_sha256"), manifest.get("workload_sha256"))
        check("manifest.schedule_hash", schedule.get("schedule_sha256"), manifest.get("schedule_sha256"))
    except Exception as exc:
        check("independent.reconstruction", "success", f"error:{type(exc).__name__}:{exc}")

    after = _tree_digest(root)
    mutated = before != after
    check("audit.run_tree_unchanged", False, mutated)
    passed = all(item.passed for item in checks)
    return FinBenchConfirmatoryFreezeAudit(
        success=passed and not mutated,
        run_root=root,
        expected_commit=expected_commit,
        checks=tuple(checks),
        run_tree_mutated=mutated,
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"audit output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--population-run-root", required=True)
    parser.add_argument("--population-audit", required=True)
    parser.add_argument("--population-expected-commit", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--lock", default=str(SF0_1_LOCK_PATH))
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--author-selection", default=str(DEFAULT_AUTHOR_SELECTION_PATH))
    parser.add_argument("--family-contract", default=str(DEFAULT_FAMILY_CONTRACT_PATH))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    run_root = Path(arguments.run_root).resolve()
    output = Path(arguments.output).resolve()
    if output == run_root or run_root in output.parents:
        print(json.dumps({"status": "failed", "error": "output must be outside run_root"}))
        return 2
    try:
        audit = audit_finbench_confirmatory_freeze(
            run_root=run_root,
            archive=arguments.archive,
            population_run_root=arguments.population_run_root,
            population_audit=arguments.population_audit,
            population_expected_commit=arguments.population_expected_commit,
            expected_commit=arguments.expected_commit,
            lock_path=arguments.lock,
            protocol=arguments.protocol,
            author_selection=arguments.author_selection,
            family_contract=arguments.family_contract,
        )
        _write_json(output, audit.to_dict())
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
