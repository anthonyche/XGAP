"""Pinned FinBench artifact acquisition and snapshot inspection.

This module is deliberately upstream of dataset partitioning and query
execution. It downloads at most once, verifies an exact public archive, and
streams allowlisted snapshot CSV members without extracting the archive.
It does not start Neo4j or Fuseki, generate native queries, inspect an answer
oracle, or authorize a paper experiment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Mapping, Sequence


LOCK_SCHEMA_VERSION = "m15-finbench-artifact-lock-v1"
INSPECTION_SCHEMA_VERSION = "m15-finbench-snapshot-inspection-v1"
DEFAULT_LOCK_PATH = Path("experiments/artifacts/m15_finbench_v010_sources.json")
_APPROVED_HOST = "datasets.ldbcouncil.org"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class FinBenchArtifactSpec:
    artifact_id: str
    benchmark: str
    version: str
    scale_factor: str
    filename: str
    url: str
    size_bytes: int
    digest_value: str
    archive_root: str
    source_page: str
    specification_repository: str
    specification_ref: str
    specification_commit: str
    claim_boundary: str
    redistribution_terms_status: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FinBenchArtifactSpec":
        digest = value.get("digest")
        if not isinstance(digest, Mapping) or digest.get("algorithm") != "sha256":
            raise ValueError("FinBench artifact digest must use sha256")
        size = value.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int):
            raise ValueError("FinBench artifact size_bytes must be an integer")
        spec = cls(
            artifact_id=str(value.get("artifact_id", "")),
            benchmark=str(value.get("benchmark", "")),
            version=str(value.get("version", "")),
            scale_factor=str(value.get("scale_factor", "")),
            filename=str(value.get("filename", "")),
            url=str(value.get("url", "")),
            size_bytes=size,
            digest_value=str(digest.get("value", "")).lower(),
            archive_root=str(value.get("archive_root", "")),
            source_page=str(value.get("source_page", "")),
            specification_repository=str(value.get("specification_repository", "")),
            specification_ref=str(value.get("specification_ref", "")),
            specification_commit=str(value.get("specification_commit", "")),
            claim_boundary=str(value.get("claim_boundary", "")),
            redistribution_terms_status=str(
                value.get("redistribution_terms_status", "")
            ),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        required = {
            "artifact_id": self.artifact_id,
            "benchmark": self.benchmark,
            "version": self.version,
            "scale_factor": self.scale_factor,
            "filename": self.filename,
            "url": self.url,
            "archive_root": self.archive_root,
            "source_page": self.source_page,
            "specification_repository": self.specification_repository,
            "specification_ref": self.specification_ref,
            "specification_commit": self.specification_commit,
            "claim_boundary": self.claim_boundary,
            "redistribution_terms_status": self.redistribution_terms_status,
        }
        missing = [name for name, item in required.items() if not item]
        if missing:
            raise ValueError(
                "FinBench artifact fields must be non-empty: " + ", ".join(missing)
            )
        if self.benchmark != "LDBC FinBench" or self.version != "v0.1.0":
            raise ValueError("FinBench artifact must pin LDBC FinBench v0.1.0")
        if self.size_bytes <= 0:
            raise ValueError("FinBench artifact size_bytes must be positive")
        if self.filename != Path(self.filename).name or not self.filename.endswith(
            ".tar.gz"
        ):
            raise ValueError("FinBench artifact filename must be a safe tar.gz basename")
        if (
            not self.archive_root
            or self.archive_root != PurePosixPath(self.archive_root).name
            or self.archive_root in {".", ".."}
        ):
            raise ValueError("FinBench archive_root must be a safe basename")
        if _HEX_64.fullmatch(self.digest_value) is None:
            raise ValueError("FinBench artifact sha256 is invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", self.specification_commit):
            raise ValueError("FinBench specification commit must be a full Git SHA")
        parsed = urllib.parse.urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != _APPROVED_HOST
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("FinBench artifact URL is not the approved official URL")
        for field_name, url in (
            ("source_page", self.source_page),
            ("specification_repository", self.specification_repository),
        ):
            source = urllib.parse.urlsplit(url)
            if source.scheme != "https" or source.hostname is None:
                raise ValueError(f"FinBench {field_name} must be HTTPS")


@dataclass(frozen=True)
class SnapshotTableSpec:
    table_id: str
    member: str
    columns: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotTableSpec":
        columns = value.get("columns")
        if not isinstance(columns, list) or not columns:
            raise ValueError("FinBench snapshot table columns must be a non-empty list")
        spec = cls(
            table_id=str(value.get("table_id", "")),
            member=str(value.get("member", "")),
            columns=tuple(str(item) for item in columns),
        )
        if not spec.table_id or not spec.member or any(not item for item in spec.columns):
            raise ValueError("FinBench snapshot table fields must be non-empty")
        path = PurePosixPath(spec.member)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".csv":
            raise ValueError("FinBench snapshot member must be a safe CSV path")
        if len(set(spec.columns)) != len(spec.columns):
            raise ValueError("FinBench snapshot columns must be unique")
        return spec


@dataclass(frozen=True)
class FinBenchArtifactLock:
    artifact: FinBenchArtifactSpec
    snapshot_tables: tuple[SnapshotTableSpec, ...]


@dataclass(frozen=True)
class ArchiveVerification:
    success: bool
    status: str
    expected_size_bytes: int
    actual_size_bytes: int | None
    expected_sha256: str
    actual_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "expected_size_bytes": self.expected_size_bytes,
            "actual_size_bytes": self.actual_size_bytes,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
        }


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_finbench_artifact_lock(path: str | Path) -> FinBenchArtifactLock:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise ValueError(f"FinBench lock schema must be {LOCK_SCHEMA_VERSION}")
    if value.get("paper_result") is not False:
        raise ValueError("FinBench artifact lock must remain paper_result=false")
    artifact = value.get("artifact")
    tables = value.get("snapshot_tables")
    if not isinstance(artifact, Mapping):
        raise ValueError("FinBench lock artifact must be an object")
    if not isinstance(tables, list) or not tables:
        raise ValueError("FinBench lock snapshot_tables must be a non-empty list")
    parsed_tables = tuple(
        SnapshotTableSpec.from_dict(item)
        for item in tables
        if isinstance(item, Mapping)
    )
    if len(parsed_tables) != len(tables):
        raise ValueError("Every FinBench snapshot table must be an object")
    if len({item.table_id for item in parsed_tables}) != len(parsed_tables):
        raise ValueError("FinBench snapshot table IDs must be unique")
    if len({item.member for item in parsed_tables}) != len(parsed_tables):
        raise ValueError("FinBench snapshot members must be unique")
    parsed_artifact = FinBenchArtifactSpec.from_dict(artifact)
    prefix = parsed_artifact.archive_root + "/snapshot/"
    if any(not item.member.startswith(prefix) for item in parsed_tables):
        raise ValueError("FinBench snapshot members must match the archive root")
    return FinBenchArtifactLock(parsed_artifact, parsed_tables)


def verify_finbench_archive(
    path: str | Path, spec: FinBenchArtifactSpec
) -> ArchiveVerification:
    archive = Path(path)
    if archive.is_symlink():
        return ArchiveVerification(
            False,
            "symbolic_link_rejected",
            spec.size_bytes,
            None,
            spec.digest_value,
            None,
        )
    if not archive.is_file():
        return ArchiveVerification(
            False, "missing", spec.size_bytes, None, spec.digest_value, None
        )
    size = archive.stat().st_size
    if size != spec.size_bytes:
        return ArchiveVerification(
            False, "size_mismatch", spec.size_bytes, size, spec.digest_value, None
        )
    digest = _file_sha256(archive)
    if digest != spec.digest_value:
        return ArchiveVerification(
            False,
            "digest_mismatch",
            spec.size_bytes,
            size,
            spec.digest_value,
            digest,
        )
    return ArchiveVerification(
        True, "verified", spec.size_bytes, size, spec.digest_value, digest
    )


def validate_finbench_tar_inventory(
    handle: tarfile.TarFile, archive_root: str
) -> dict[str, tarfile.TarInfo]:
    inventory: dict[str, tarfile.TarInfo] = {}
    for member in handle.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"Unsafe FinBench archive member: {member.name}")
        if path.parts[0] != archive_root:
            raise ValueError(f"FinBench archive member has unexpected root: {member.name}")
        if member.name in inventory:
            raise ValueError(f"Duplicate FinBench archive member: {member.name}")
        if member.issym() or member.islnk():
            raise ValueError(f"FinBench archive links are forbidden: {member.name}")
        if not member.isdir() and not member.isfile():
            raise ValueError(f"Unsupported FinBench archive member: {member.name}")
        inventory[member.name] = member
    return inventory


def inspect_finbench_snapshot(
    archive_path: str | Path, lock: FinBenchArtifactLock
) -> dict[str, Any]:
    verification = verify_finbench_archive(archive_path, lock.artifact)
    if not verification.success:
        raise ValueError(f"FinBench archive verification failed: {verification.status}")
    tables: list[dict[str, Any]] = []
    with tarfile.open(Path(archive_path), mode="r:gz") as handle:
        inventory = validate_finbench_tar_inventory(handle, lock.artifact.archive_root)
        for table in lock.snapshot_tables:
            member = inventory.get(table.member)
            if member is None or not member.isfile():
                raise ValueError(f"Required FinBench snapshot member is missing: {table.member}")
            stream = handle.extractfile(member)
            if stream is None:
                raise ValueError(f"Cannot read FinBench snapshot member: {table.member}")
            with io.TextIOWrapper(stream, encoding="utf-8", newline="") as text_stream:
                reader = csv.reader(text_stream, delimiter="|")
                try:
                    header = tuple(next(reader))
                except StopIteration as exc:
                    raise ValueError(
                        f"FinBench snapshot member is empty: {table.member}"
                    ) from exc
                if header != table.columns:
                    raise ValueError(f"FinBench snapshot header drift: {table.member}")
                row_count = 0
                for row_number, row in enumerate(reader, start=2):
                    if len(row) != len(header):
                        raise ValueError(
                            f"FinBench row width drift: {table.member}:{row_number}"
                        )
                    row_count += 1
            tables.append(
                {
                    "table_id": table.table_id,
                    "member": table.member,
                    "columns": list(table.columns),
                    "row_count": row_count,
                    "uncompressed_size_bytes": member.size,
                }
            )
    report: dict[str, Any] = {
        "schema_version": INSPECTION_SCHEMA_VERSION,
        "artifact_id": lock.artifact.artifact_id,
        "benchmark": lock.artifact.benchmark,
        "version": lock.artifact.version,
        "scale_factor": lock.artifact.scale_factor,
        "archive_filename": lock.artifact.filename,
        "archive_verification": verification.to_dict(),
        "table_count": len(tables),
        "total_snapshot_rows": sum(item["row_count"] for item in tables),
        "tables": tables,
        "claim_boundary": lock.artifact.claim_boundary,
        "backend_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "paper_result": False,
    }
    report["inspection_sha256"] = _canonical_sha256(report)
    return report


def fetch_finbench_archive(
    lock: FinBenchArtifactLock,
    cache_root: str | Path,
    *,
    opener: Callable[..., BinaryIO] = urllib.request.urlopen,
    timeout_seconds: float = 300.0,
) -> tuple[Path, dict[str, Any]]:
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / lock.artifact.filename
    existing = verify_finbench_archive(destination, lock.artifact)
    if existing.success:
        return destination, {
            "status": "reused_verified_cache",
            "download_attempts": 0,
            "bytes_downloaded": 0,
            "verification": existing.to_dict(),
        }
    if destination.exists() or destination.is_symlink():
        raise ValueError(
            f"Conflicting FinBench cache entry is not overwritten: {destination}"
        )

    temporary: Path | None = None
    bytes_downloaded = 0
    try:
        with tempfile.NamedTemporaryFile(
            prefix=lock.artifact.filename + ".",
            suffix=".partial",
            dir=root,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            with opener(lock.artifact.url, timeout=timeout_seconds) as response:
                final_url = str(response.geturl())
                parsed = urllib.parse.urlsplit(final_url)
                if parsed.scheme != "https" or parsed.hostname != _APPROVED_HOST:
                    raise ValueError("FinBench download redirected to an unapproved host")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    bytes_downloaded += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        verification = verify_finbench_archive(temporary, lock.artifact)
        if not verification.success:
            raise ValueError(
                f"Downloaded FinBench archive failed verification: {verification.status}"
            )
        os.replace(temporary, destination)
        temporary = None
        return destination, {
            "status": "downloaded_and_verified",
            "download_attempts": 1,
            "bytes_downloaded": bytes_downloaded,
            "verification": verification.to_dict(),
        }
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    temporary = destination.with_name(destination.name + f".partial-{os.getpid()}")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Output already exists: {destination}")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "prepare"):
        child = subparsers.add_parser(command)
        child.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
        child.add_argument("--output", required=True)
        if command == "inspect":
            child.add_argument("--archive", required=True)
        else:
            child.add_argument("--cache-root", required=True)
            child.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lock = load_finbench_artifact_lock(args.lock)
        fetch_record: dict[str, Any] | None = None
        if args.command == "inspect":
            archive = Path(args.archive)
        else:
            archive, fetch_record = fetch_finbench_archive(
                lock, args.cache_root, timeout_seconds=args.timeout_seconds
            )
        report = inspect_finbench_snapshot(archive, lock)
        if fetch_record is not None:
            report["fetch"] = fetch_record
            report["inspection_sha256"] = _canonical_sha256(
                {key: value for key, value in report.items() if key != "inspection_sha256"}
            )
        _write_json(args.output, report)
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
