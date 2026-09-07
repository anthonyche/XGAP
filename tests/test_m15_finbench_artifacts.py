from __future__ import annotations

import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

import pytest

from xgap.experiments.m15_finbench_artifacts import (
    DEFAULT_LOCK_PATH,
    LOCK_SCHEMA_VERSION,
    SF0_1_LOCK_PATH,
    FinBenchArtifactSpec,
    FinBenchArtifactLock,
    SnapshotTableSpec,
    fetch_finbench_archive,
    inspect_finbench_snapshot,
    load_finbench_artifact_lock,
    main,
    verify_finbench_archive,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = io.BytesIO(payload)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.payload.read(size)

    def geturl(self) -> str:
        return "https://datasets.ldbcouncil.org/finbench/sf0.01.tar.gz"


def _archive_bytes(
    table: SnapshotTableSpec, *, unsafe_member: tarfile.TarInfo | None = None
) -> bytes:
    output = io.BytesIO()
    payload = ("|".join(table.columns) + "\n" + "|".join("x" for _ in table.columns) + "\n").encode()
    with tarfile.open(fileobj=output, mode="w:gz") as handle:
        root = tarfile.TarInfo("sf0.01")
        root.type = tarfile.DIRTYPE
        handle.addfile(root)
        member = tarfile.TarInfo(table.member)
        member.size = len(payload)
        handle.addfile(member, io.BytesIO(payload))
        if unsafe_member is not None:
            handle.addfile(unsafe_member)
    return output.getvalue()


def _lock(payload: bytes) -> FinBenchArtifactLock:
    table = SnapshotTableSpec(
        table_id="person",
        member="sf0.01/snapshot/Person.csv",
        columns=("personId", "personName"),
    )
    artifact = FinBenchArtifactSpec.from_dict(
        {
            "artifact_id": "test-finbench",
            "benchmark": "LDBC FinBench",
            "version": "v0.1.0",
            "scale_factor": "0.01",
            "filename": "sf0.01.tar.gz",
            "url": "https://datasets.ldbcouncil.org/finbench/sf0.01.tar.gz",
            "size_bytes": len(payload),
            "digest": {
                "algorithm": "sha256",
                "value": hashlib.sha256(payload).hexdigest(),
            },
            "archive_root": "sf0.01",
            "source_page": "https://ldbcouncil.org/benchmarks/finbench/datasets/",
            "specification_repository": "https://github.com/ldbc/ldbc_finbench_docs",
            "specification_ref": "v0.1.0",
            "specification_commit": "d3ec7036bf6919df8cd3eeaa3a986048e779ea02",
            "claim_boundary": "test_only",
            "redistribution_terms_status": "verify",
        }
    )
    return FinBenchArtifactLock(artifact, (table,))


def test_committed_lock_pins_official_sf001_archive() -> None:
    lock = load_finbench_artifact_lock(REPO_ROOT / DEFAULT_LOCK_PATH)
    assert lock.artifact.version == "v0.1.0"
    assert lock.artifact.size_bytes == 6516867
    assert lock.artifact.digest_value == (
        "888c8fbe06b68cc48de9f07fde8c0fd3295618fc41af13ae1aa216aaec1e0430"
    )
    assert len(lock.snapshot_tables) == 18
    assert {table.table_id for table in lock.snapshot_tables} == {
        "person",
        "account",
        "company",
        "medium",
        "person_own_account",
        "company_own_account",
        "account_transfer_account",
        "medium_sign_in_account",
        "person_guarantee_person",
        "person_apply_loan",
        "loan_deposit_account",
        "company_apply_loan",
        "loan",
        "account_withdraw_account",
        "account_repay_loan",
        "company_invest_company",
        "company_guarantee_company",
        "person_invest_company",
    }


def test_committed_scale_gate_lock_pins_official_sf01_archive() -> None:
    baseline = load_finbench_artifact_lock(REPO_ROOT / DEFAULT_LOCK_PATH)
    lock = load_finbench_artifact_lock(REPO_ROOT / SF0_1_LOCK_PATH)

    assert lock.artifact.artifact_id == "ldbc-finbench-v0.1.0-sf0.1"
    assert lock.artifact.scale_factor == "0.1"
    assert lock.artifact.filename == "sf0.1.tar.gz"
    assert lock.artifact.url == (
        "https://datasets.ldbcouncil.org/finbench/sf0.1.tar.gz"
    )
    assert lock.artifact.size_bytes == 66710298
    assert lock.artifact.digest_value == (
        "f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60"
    )
    assert lock.artifact.archive_root == "sf0.1"
    assert len(lock.snapshot_tables) == 18
    assert {table.table_id for table in lock.snapshot_tables} == {
        table.table_id for table in baseline.snapshot_tables
    }
    assert all(
        table.member.startswith("sf0.1/snapshot/")
        for table in lock.snapshot_tables
    )


def test_inspection_streams_allowlisted_table_without_extraction(tmp_path: Path) -> None:
    table = SnapshotTableSpec(
        table_id="person",
        member="sf0.01/snapshot/Person.csv",
        columns=("personId", "personName"),
    )
    payload = _archive_bytes(table)
    lock = _lock(payload)
    archive = tmp_path / lock.artifact.filename
    archive.write_bytes(payload)

    report = inspect_finbench_snapshot(archive, lock)

    assert report["table_count"] == 1
    assert report["total_snapshot_rows"] == 1
    assert report["tables"][0]["row_count"] == 1
    assert report["backend_calls"] == 0
    assert report["paper_result"] is False
    assert len(report["inspection_sha256"]) == 64
    assert list(tmp_path.iterdir()) == [archive]


def test_inspection_rejects_archive_links(tmp_path: Path) -> None:
    table = SnapshotTableSpec(
        table_id="person",
        member="sf0.01/snapshot/Person.csv",
        columns=("personId", "personName"),
    )
    link = tarfile.TarInfo("sf0.01/snapshot/link.csv")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    payload = _archive_bytes(table, unsafe_member=link)
    lock = _lock(payload)
    archive = tmp_path / lock.artifact.filename
    archive.write_bytes(payload)

    with pytest.raises(ValueError, match="links are forbidden"):
        inspect_finbench_snapshot(archive, lock)


def test_verification_distinguishes_missing_size_digest_and_symlink(tmp_path: Path) -> None:
    table = SnapshotTableSpec(
        table_id="person",
        member="sf0.01/snapshot/Person.csv",
        columns=("personId", "personName"),
    )
    payload = _archive_bytes(table)
    lock = _lock(payload)
    archive = tmp_path / lock.artifact.filename

    assert verify_finbench_archive(archive, lock.artifact).status == "missing"
    archive.write_bytes(b"short")
    assert verify_finbench_archive(archive, lock.artifact).status == "size_mismatch"
    archive.write_bytes(b"x" * len(payload))
    assert verify_finbench_archive(archive, lock.artifact).status == "digest_mismatch"
    archive.unlink()
    target = tmp_path / "target"
    target.write_bytes(payload)
    archive.symlink_to(target)
    assert verify_finbench_archive(archive, lock.artifact).status == "symbolic_link_rejected"


def test_fetch_is_single_attempt_and_reuses_verified_cache(tmp_path: Path) -> None:
    table = SnapshotTableSpec(
        table_id="person",
        member="sf0.01/snapshot/Person.csv",
        columns=("personId", "personName"),
    )
    payload = _archive_bytes(table)
    lock = _lock(payload)
    calls: list[tuple[urllib.request.Request, float]] = []

    def opener(request: urllib.request.Request, timeout: float) -> FakeResponse:
        calls.append((request, timeout))
        return FakeResponse(payload)

    archive, first = fetch_finbench_archive(
        lock, tmp_path, opener=opener, timeout_seconds=7
    )
    reused, second = fetch_finbench_archive(
        lock,
        tmp_path,
        opener=lambda *_args, **_kwargs: pytest.fail("network should not be used"),
    )

    assert archive == reused
    assert first["status"] == "downloaded_and_verified"
    assert first["download_attempts"] == 1
    assert second["status"] == "reused_verified_cache"
    assert second["download_attempts"] == 0
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == lock.artifact.url
    assert request.get_method() == "GET"
    assert request.headers["User-agent"] == (
        "XGAP/0.1 verified-research-artifact-fetch"
    )
    assert request.headers["Accept-encoding"] == "identity"
    assert timeout == 7
    assert list(tmp_path.glob("*.partial")) == []


def test_cli_inspect_refuses_to_overwrite_output(tmp_path: Path) -> None:
    table = SnapshotTableSpec(
        table_id="person",
        member="sf0.01/snapshot/Person.csv",
        columns=("personId", "personName"),
    )
    payload = _archive_bytes(table)
    lock = _lock(payload)
    archive = tmp_path / "sf0.01.tar.gz"
    archive.write_bytes(payload)
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": LOCK_SCHEMA_VERSION,
                "artifact": {
                    "artifact_id": lock.artifact.artifact_id,
                    "benchmark": lock.artifact.benchmark,
                    "version": lock.artifact.version,
                    "scale_factor": lock.artifact.scale_factor,
                    "filename": lock.artifact.filename,
                    "url": lock.artifact.url,
                    "size_bytes": lock.artifact.size_bytes,
                    "digest": {
                        "algorithm": "sha256",
                        "value": lock.artifact.digest_value,
                    },
                    "archive_root": lock.artifact.archive_root,
                    "source_page": lock.artifact.source_page,
                    "specification_repository": lock.artifact.specification_repository,
                    "specification_ref": lock.artifact.specification_ref,
                    "specification_commit": lock.artifact.specification_commit,
                    "claim_boundary": lock.artifact.claim_boundary,
                    "redistribution_terms_status": lock.artifact.redistribution_terms_status,
                },
                "snapshot_tables": [
                    {
                        "table_id": table.table_id,
                        "member": table.member,
                        "columns": list(table.columns),
                    }
                ],
                "paper_result": False,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "inspection.json"

    assert main(["inspect", "--lock", str(lock_path), "--archive", str(archive), "--output", str(output)]) == 0
    assert main(["inspect", "--lock", str(lock_path), "--archive", str(archive), "--output", str(output)]) == 1
