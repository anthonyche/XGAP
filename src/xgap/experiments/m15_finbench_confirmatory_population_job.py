"""Run the result-blind FinBench population compiler as one sealed job."""

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
from xgap.experiments.m15_finbench_artifacts import (
    SF0_1_LOCK_PATH,
    load_finbench_artifact_lock,
)
from xgap.experiments.m15_finbench_confirmatory_population import (
    DEFAULT_DESIGN_PATH,
    compile_finbench_confirmatory_population_registry,
    write_finbench_confirmatory_population_registry,
)
from xgap.experiments.m15_finbench_workload import load_finbench_query_data


FINBENCH_CONFIRMATORY_POPULATION_JOB_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-population-job-v1"
)
FINBENCH_CONFIRMATORY_POPULATION_MANIFEST_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-population-run-manifest-v1"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} must be a regular non-symbolic-link file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output exists: {path}")
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


def _git_state(repo_root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    porcelain = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "clean": porcelain == ""}


def run_finbench_confirmatory_population_job(
    *,
    repo_root: str | Path,
    archive: str | Path,
    lock_path: str | Path,
    design_path: str | Path,
    output_root: str | Path,
    slurm_job_id: str,
) -> dict[str, Any]:
    selected_root = Path(output_root)
    if selected_root.is_symlink():
        raise ValueError("run root must not be a symbolic link")
    root = selected_root.resolve()
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"run root exists: {root}")
    root.mkdir(parents=True)
    started_at = _utc_now()
    status_path = root / "run_status.json"
    try:
        repo = Path(repo_root).resolve()
        selected_archive = Path(archive)
        if selected_archive.is_symlink():
            raise ValueError("archive must not be a symbolic link")
        archive_path = selected_archive.resolve()
        lock_file = Path(lock_path).resolve()
        design_file = Path(design_path).resolve()
        if not (repo / "pyproject.toml").is_file():
            raise ValueError("repo_root is not an XGAP checkout")
        if not archive_path.is_file():
            raise ValueError("archive must be a regular non-symbolic-link file")
        git = _git_state(repo)
        if git["clean"] is not True:
            raise ValueError("population job requires a clean Git checkout")
        lock = load_finbench_artifact_lock(lock_file)
        data = load_finbench_query_data(archive_path, lock)
        registry = compile_finbench_confirmatory_population_registry(
            data,
            source_artifact_id=lock.artifact.artifact_id,
            source_archive_sha256=lock.artifact.digest_value,
            design=design_file,
        )
        registry_path = root / "population_registry.json"
        write_finbench_confirmatory_population_registry(registry, registry_path)
        design = _json_object(design_file, name="population design")
        lock_value = _json_object(lock_file, name="FinBench source lock")
        manifest_body: dict[str, Any] = {
            "schema_version": (
                FINBENCH_CONFIRMATORY_POPULATION_MANIFEST_SCHEMA_VERSION
            ),
            "status": "success",
            "started_at": started_at,
            "ended_at": _utc_now(),
            "slurm_job_id": str(slurm_job_id),
            "git": git,
            "source": {
                "archive_path": str(archive_path),
                "archive_sha256": _file_sha256(archive_path),
                "artifact_id": lock.artifact.artifact_id,
                "lock_path": str(lock_file),
                "lock_content_sha256": content_hash(lock_value),
                "design_path": str(design_file),
                "design_content_sha256": content_hash(design),
            },
            "output": {
                "registry_path": str(registry_path),
                "registry_file_sha256": _file_sha256(registry_path),
                "registry_sha256": registry.to_dict()["registry_sha256"],
            },
            "external_call_counts": {
                "backend_calls": 0,
                "current_query_profile_calls": 0,
                "llm_calls": 0,
                "ontology_service_calls": 0,
            },
            "automatic_retries": 0,
            "author_selected_population_option_id": None,
            "confirmatory_run_authorized": False,
            "paper_result": False,
        }
        manifest = {
            **manifest_body,
            "manifest_sha256": content_hash(manifest_body),
        }
        _write_json(root / "run_manifest.json", manifest)
        _write_json(
            status_path,
            {
                "schema_version": (
                    FINBENCH_CONFIRMATORY_POPULATION_JOB_SCHEMA_VERSION
                ),
                "status": "success",
                "exit_code": 0,
                "git_commit": git["commit"],
                "slurm_job_id": str(slurm_job_id),
                "workload_mode": "finbench_confirmatory_population",
                "paper_result": False,
            },
        )
        return manifest
    except Exception as exc:
        if not status_path.exists():
            _write_json(
                status_path,
                {
                    "schema_version": (
                        FINBENCH_CONFIRMATORY_POPULATION_JOB_SCHEMA_VERSION
                    ),
                    "status": "failed",
                    "exit_code": 1,
                    "slurm_job_id": str(slurm_job_id),
                    "workload_mode": "finbench_confirmatory_population",
                    "error": f"{type(exc).__name__}: {exc}",
                    "paper_result": False,
                },
            )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--lock", default=str(SF0_1_LOCK_PATH))
    parser.add_argument("--design", default=str(DEFAULT_DESIGN_PATH))
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--slurm-job-id", default="manual")
    args = parser.parse_args(argv)
    try:
        manifest = run_finbench_confirmatory_population_job(
            repo_root=args.repo_root,
            archive=args.archive,
            lock_path=args.lock,
            design_path=args.design,
            output_root=args.output_root,
            slurm_job_id=args.slurm_job_id,
        )
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
