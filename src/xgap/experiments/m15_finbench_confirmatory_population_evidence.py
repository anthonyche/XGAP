"""Independently reconstruct a FinBench confirmatory population registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
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
)
from xgap.experiments.m15_finbench_confirmatory_population_job import (
    FINBENCH_CONFIRMATORY_POPULATION_JOB_SCHEMA_VERSION,
    FINBENCH_CONFIRMATORY_POPULATION_MANIFEST_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_workload import load_finbench_query_data


FINBENCH_CONFIRMATORY_POPULATION_AUDIT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-population-evidence-audit-v1"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class FinBenchConfirmatoryPopulationEvidenceCheck:
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
class FinBenchConfirmatoryPopulationEvidenceAudit:
    success: bool
    run_root: Path
    expected_commit: str
    checks: tuple[FinBenchConfirmatoryPopulationEvidenceCheck, ...]
    run_tree_mutated: bool

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(check.check_id for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FINBENCH_CONFIRMATORY_POPULATION_AUDIT_SCHEMA_VERSION,
            "success": self.success,
            "run_root": str(self.run_root),
            "expected_commit": self.expected_commit,
            "check_count": len(self.checks),
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [check.to_dict() for check in self.checks],
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


def _without_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _json_object(path: Path, *, name: str) -> dict[str, Any]:
    value, state = _read_json(path)
    if state != "ok" or not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a regular JSON object")
    return dict(value)


def audit_finbench_confirmatory_population(
    *,
    run_root: str | Path,
    archive: str | Path,
    expected_commit: str,
    lock_path: str | Path = SF0_1_LOCK_PATH,
    design_path: str | Path = DEFAULT_DESIGN_PATH,
) -> FinBenchConfirmatoryPopulationEvidenceAudit:
    if _COMMIT.fullmatch(expected_commit) is None:
        raise ValueError("expected_commit must be a full lowercase Git commit")
    selected = Path(run_root)
    if selected.is_symlink():
        raise ValueError("run_root must not be a symbolic link")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("run_root must be a real directory")
    selected_archive = Path(archive)
    if selected_archive.is_symlink():
        raise ValueError("archive must not be a symbolic link")
    archive_path = selected_archive.resolve()
    if not archive_path.is_file():
        raise ValueError("archive must be a regular non-symbolic-link file")
    before = _tree_digest(root)
    status_value, status_state = _read_json(root / "run_status.json")
    manifest_value, manifest_state = _read_json(root / "run_manifest.json")
    registry_value, registry_state = _read_json(root / "population_registry.json")
    status = _mapping(status_value)
    manifest = _mapping(manifest_value)
    registry = _mapping(registry_value)
    checks: list[FinBenchConfirmatoryPopulationEvidenceCheck] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        checks.append(
            FinBenchConfirmatoryPopulationEvidenceCheck(
                check_id, expected == observed, expected, observed
            )
        )

    check("artifact.status", "ok", status_state)
    check("artifact.manifest", "ok", manifest_state)
    check("artifact.registry", "ok", registry_state)
    check(
        "status.schema",
        FINBENCH_CONFIRMATORY_POPULATION_JOB_SCHEMA_VERSION,
        status.get("schema_version"),
    )
    check("status.status", "success", status.get("status"))
    check("status.exit_code", 0, status.get("exit_code"))
    check("status.commit", expected_commit, status.get("git_commit"))
    check(
        "status.mode",
        "finbench_confirmatory_population",
        status.get("workload_mode"),
    )
    check("status.paper_result", False, status.get("paper_result"))
    check(
        "manifest.schema",
        FINBENCH_CONFIRMATORY_POPULATION_MANIFEST_SCHEMA_VERSION,
        manifest.get("schema_version"),
    )
    check("manifest.status", "success", manifest.get("status"))
    check(
        "manifest.commit",
        expected_commit,
        _mapping(manifest.get("git")).get("commit"),
    )
    check("manifest.clean", True, _mapping(manifest.get("git")).get("clean"))
    check(
        "manifest.hash",
        content_hash(_without_hash(manifest, "manifest_sha256")),
        manifest.get("manifest_sha256"),
    )
    check("manifest.retry", 0, manifest.get("automatic_retries"))
    check(
        "manifest.author_choice",
        None,
        manifest.get("author_selected_population_option_id"),
    )
    check(
        "manifest.authorized",
        False,
        manifest.get("confirmatory_run_authorized"),
    )
    check("manifest.paper_result", False, manifest.get("paper_result"))
    calls = _mapping(manifest.get("external_call_counts"))
    check(
        "manifest.zero_calls",
        {
            "backend_calls": 0,
            "current_query_profile_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        },
        dict(calls),
    )

    try:
        lock = load_finbench_artifact_lock(lock_path)
        lock_value = _json_object(Path(lock_path), name="FinBench source lock")
        design_value = _json_object(
            Path(design_path), name="population design"
        )
        source = _mapping(manifest.get("source"))
        output = _mapping(manifest.get("output"))
        actual_archive_sha256 = _file_sha256(archive_path)
        check(
            "source.archive_sha256",
            lock.artifact.digest_value,
            actual_archive_sha256,
        )
        check(
            "manifest.source_archive_sha256",
            actual_archive_sha256,
            source.get("archive_sha256"),
        )
        check(
            "manifest.source_artifact_id",
            lock.artifact.artifact_id,
            source.get("artifact_id"),
        )
        check(
            "manifest.lock_hash",
            content_hash(lock_value),
            source.get("lock_content_sha256"),
        )
        check(
            "manifest.design_hash",
            content_hash(design_value),
            source.get("design_content_sha256"),
        )
        check(
            "manifest.registry_path",
            str((root / "population_registry.json").resolve()),
            output.get("registry_path"),
        )
        data = load_finbench_query_data(archive_path, lock)
        reconstructed = compile_finbench_confirmatory_population_registry(
            data,
            source_artifact_id=lock.artifact.artifact_id,
            source_archive_sha256=lock.artifact.digest_value,
            design=design_path,
        ).to_dict()
        check("registry.reconstruction", reconstructed, dict(registry))
        check(
            "registry.file_sha256",
            _file_sha256(root / "population_registry.json"),
            output.get("registry_file_sha256"),
        )
        check(
            "registry.identity",
            reconstructed.get("registry_sha256"),
            output.get("registry_sha256"),
        )
    except Exception as exc:
        check("registry.reconstruction", "success", f"error:{exc}")

    after = _tree_digest(root)
    mutated = before != after
    check("audit.run_tree_unchanged", False, mutated)
    passed = all(item.passed for item in checks)
    return FinBenchConfirmatoryPopulationEvidenceAudit(
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
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--lock", default=str(SF0_1_LOCK_PATH))
    parser.add_argument("--design", default=str(DEFAULT_DESIGN_PATH))
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    run_root = Path(args.run_root).resolve()
    output = Path(args.output).resolve()
    if output == run_root or run_root in output.parents:
        print(
            json.dumps(
                {"status": "failed", "error": "output must be outside run_root"}
            )
        )
        return 2
    try:
        audit = audit_finbench_confirmatory_population(
            run_root=run_root,
            archive=args.archive,
            expected_commit=args.expected_commit,
            lock_path=args.lock,
            design_path=args.design,
        )
        _write_json(output, audit.to_dict())
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    return 0 if audit.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
