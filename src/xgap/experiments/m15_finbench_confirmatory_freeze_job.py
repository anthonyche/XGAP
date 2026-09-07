"""Freeze the author-selected FinBench workload and measurement schedule.

This CPU-only gate replays the accepted result-blind population audit, binds
the author's Option-A selection to the exact population registry, materializes
the 48-query public workload and sealed oracle, and freezes all measurement
slots.  It performs no backend, profile, model, or ontology call and does not
authorize confirmatory execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_artifacts import SF0_1_LOCK_PATH
from xgap.experiments.m15_finbench_confirmatory_population_evidence import (
    FINBENCH_CONFIRMATORY_POPULATION_AUDIT_SCHEMA_VERSION,
    audit_finbench_confirmatory_population,
)
from xgap.experiments.m15_finbench_confirmatory_schedule import (
    build_finbench_confirmatory_schedule,
    write_finbench_confirmatory_schedule,
)
from xgap.experiments.m15_finbench_confirmatory_workload import (
    DEFAULT_FAMILY_CONTRACT_PATH,
    build_finbench_confirmatory_population_approval,
    build_finbench_confirmatory_workload,
)
from xgap.experiments.m15_finbench_paper_protocol import (
    DEFAULT_AUTHOR_SELECTION_PATH,
    DEFAULT_PROTOCOL_PATH,
    apply_finbench_paper_protocol_author_selection,
)


FINBENCH_CONFIRMATORY_FREEZE_JOB_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-freeze-job-v1"
)
FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-freeze-manifest-v1"
)
_OPTION_ID = "m15-finbench-confirmatory-48-v1"
_PROTOCOL_VALUE = "48_answer_independent_crossfit"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} must be a regular non-symbolic-link file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must contain a JSON object")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _git_state(repo: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "clean": porcelain == ""}


def _artifact_files(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"freeze output contains a symbolic link: {path}")
        if path.is_file() and path.name not in {"run_manifest.json", "run_status.json"}:
            result[str(path.relative_to(root))] = {
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
    return result


def run_finbench_confirmatory_freeze_job(
    *,
    repo_root: str | Path,
    archive: str | Path,
    population_run_root: str | Path,
    population_audit: str | Path,
    population_expected_commit: str,
    output_root: str | Path,
    slurm_job_id: str,
    lock_path: str | Path = SF0_1_LOCK_PATH,
    protocol: str | Path = DEFAULT_PROTOCOL_PATH,
    author_selection: str | Path = DEFAULT_AUTHOR_SELECTION_PATH,
    family_contract: str | Path = DEFAULT_FAMILY_CONTRACT_PATH,
) -> dict[str, Any]:
    selected_output = Path(output_root)
    if selected_output.is_symlink():
        raise ValueError("run root must not be a symbolic link")
    root = selected_output.resolve()
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"run root exists: {root}")
    root.mkdir(parents=True)
    status_path = root / "run_status.json"
    started_at = _utc_now()
    try:
        repo = Path(repo_root).resolve()
        archive_path = Path(archive)
        source_run = Path(population_run_root)
        audit_path = Path(population_audit)
        if (
            not (repo / "pyproject.toml").is_file()
            or archive_path.is_symlink()
            or not archive_path.is_file()
            or source_run.is_symlink()
            or not source_run.is_dir()
        ):
            raise ValueError("freeze inputs are missing, unsafe, or not an XGAP checkout")
        git = _git_state(repo)
        if git["clean"] is not True:
            raise ValueError("confirmatory freeze requires a clean Git checkout")
        saved_audit = _read_json(audit_path, name="population audit")
        rebuilt_audit = audit_finbench_confirmatory_population(
            run_root=source_run,
            archive=archive_path,
            expected_commit=population_expected_commit,
            lock_path=lock_path,
        ).to_dict()
        if saved_audit != rebuilt_audit or (
            saved_audit.get("schema_version")
            != FINBENCH_CONFIRMATORY_POPULATION_AUDIT_SCHEMA_VERSION
            or saved_audit.get("success") is not True
            or saved_audit.get("failed_check_ids") != []
            or saved_audit.get("run_tree_mutated") is not False
        ):
            raise ValueError("population audit failed independent replay")
        registry_path = source_run.resolve() / "population_registry.json"
        registry = _read_json(registry_path, name="population registry")
        selection = _read_json(Path(author_selection), name="author selection")
        approved_protocol = apply_finbench_paper_protocol_author_selection(
            protocol, selection
        )
        choices = {
            str(item["decision_id"]): str(item["selected_value"])
            for item in approved_protocol["author_decisions"]
        }
        if choices.get("confirmatory_population") != _PROTOCOL_VALUE:
            raise ValueError("author selection is not the 48-query population")
        approval = build_finbench_confirmatory_population_approval(
            registry,
            selected_population_option_id=_OPTION_ID,
            approval_id="m15-finbench-confirmatory-option-a-approval-v1",
            authority_source_id=str(selection["authority_source_id"]),
        )
        _write_json(root / "author_selection_snapshot.json", selection)
        _write_json(root / "population_approval.json", approval)
        workload_root = root / "confirmatory-workload"
        workload_manifest = build_finbench_confirmatory_workload(
            archive_path=archive_path,
            population_registry=registry,
            population_approval=approval,
            output_root=workload_root,
            lock_path=lock_path,
            family_contract=family_contract,
        )
        schedule = build_finbench_confirmatory_schedule(
            workload_root=workload_root,
            protocol=protocol,
            author_selection=selection,
        )
        schedule_path = root / "measurement_schedule.json"
        write_finbench_confirmatory_schedule(schedule, schedule_path)
        artifacts = _artifact_files(root)
        manifest_body: dict[str, Any] = {
            "schema_version": FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION,
            "status": "success",
            "started_at": started_at,
            "ended_at": _utc_now(),
            "slurm_job_id": str(slurm_job_id),
            "git": git,
            "population_source": {
                "run_root": str(source_run.resolve()),
                "expected_commit": population_expected_commit,
                "registry_sha256": registry["registry_sha256"],
                "audit_file_sha256": _file_sha256(audit_path.resolve()),
                "audit_content_sha256": content_hash(saved_audit),
                "audit_independently_replayed": True,
            },
            "author_selection_sha256": selection["selection_sha256"],
            "population_approval_sha256": approval["approval_sha256"],
            "workload_sha256": workload_manifest["workload_sha256"],
            "schedule_sha256": schedule.schedule_hash,
            "expected_counts": schedule.payload["expected_counts"],
            "artifact_files": artifacts,
            "external_call_counts": {
                "backend_calls": 0,
                "current_query_profile_calls": 0,
                "llm_calls": 0,
                "ontology_service_calls": 0,
            },
            "confirmatory_workload_compilation_authorized": True,
            "confirmatory_execution_authorized": False,
            "automatic_retries": 0,
            "paper_result": False,
        }
        manifest = {**manifest_body, "manifest_sha256": content_hash(manifest_body)}
        _write_json(root / "run_manifest.json", manifest)
        _write_json(
            status_path,
            {
                "schema_version": FINBENCH_CONFIRMATORY_FREEZE_JOB_SCHEMA_VERSION,
                "status": "success",
                "exit_code": 0,
                "git_commit": git["commit"],
                "slurm_job_id": str(slurm_job_id),
                "workload_mode": "finbench_confirmatory_freeze",
                "confirmatory_execution_authorized": False,
                "paper_result": False,
            },
        )
        return manifest
    except Exception as exc:
        if not status_path.exists():
            _write_json(
                status_path,
                {
                    "schema_version": FINBENCH_CONFIRMATORY_FREEZE_JOB_SCHEMA_VERSION,
                    "status": "failed",
                    "exit_code": 1,
                    "slurm_job_id": str(slurm_job_id),
                    "workload_mode": "finbench_confirmatory_freeze",
                    "error": f"{type(exc).__name__}: {exc}",
                    "confirmatory_execution_authorized": False,
                    "paper_result": False,
                },
            )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--population-run-root", required=True)
    parser.add_argument("--population-audit", required=True)
    parser.add_argument("--population-expected-commit", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--slurm-job-id", default="manual")
    parser.add_argument("--lock", default=str(SF0_1_LOCK_PATH))
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--author-selection", default=str(DEFAULT_AUTHOR_SELECTION_PATH))
    parser.add_argument("--family-contract", default=str(DEFAULT_FAMILY_CONTRACT_PATH))
    arguments = parser.parse_args(argv)
    try:
        manifest = run_finbench_confirmatory_freeze_job(
            repo_root=arguments.repo_root,
            archive=arguments.archive,
            population_run_root=arguments.population_run_root,
            population_audit=arguments.population_audit,
            population_expected_commit=arguments.population_expected_commit,
            output_root=arguments.output_root,
            slurm_job_id=arguments.slurm_job_id,
            lock_path=arguments.lock,
            protocol=arguments.protocol,
            author_selection=arguments.author_selection,
            family_contract=arguments.family_contract,
        )
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
