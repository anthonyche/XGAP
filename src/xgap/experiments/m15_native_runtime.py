"""Safe allocation-local staging for pinned M15 native service archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from xgap.experiments.m15_native_artifacts import (
    DEFAULT_LOCK_PATH,
    NativeArtifactSpec,
    NativeRuntimeLock,
    load_native_runtime_lock,
    verify_native_artifact,
)


STAGING_SCHEMA_VERSION = "m15-b2c-native-runtime-staging-v1"
MAX_ARCHIVE_MEMBERS = 100_000
MAX_UNPACKED_SIZE_MULTIPLIER = 16


@dataclass(frozen=True)
class ArchiveInspection:
    artifact_id: str
    member_count: int
    regular_file_count: int
    directory_count: int
    total_regular_file_bytes: int
    expected_root: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "member_count": self.member_count,
            "regular_file_count": self.regular_file_count,
            "directory_count": self.directory_count,
            "total_regular_file_bytes": self.total_regular_file_bytes,
            "expected_root": self.expected_root,
        }


@dataclass(frozen=True)
class StagedArtifact:
    artifact_id: str
    product: str
    version: str
    source_archive: Path
    runtime_path: Path
    inspection: ArchiveInspection
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "product": self.product,
            "version": self.version,
            "source_archive": str(self.source_archive),
            "runtime_path": str(self.runtime_path),
            "inspection": self.inspection.to_dict(),
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True)
class NativeRuntimeStagingRecord:
    success: bool
    runtime_root: Path
    artifacts: tuple[StagedArtifact, ...]
    manifest_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "runtime_root": str(self.runtime_root),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member_path(name: str, expected_root: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise ValueError("archive member path is empty or contains a backslash")
    path = PurePosixPath(name)
    parts = path.parts
    if path.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe archive member path: {name}")
    if parts[0] != expected_root:
        raise ValueError(
            f"archive member is outside expected root {expected_root}: {name}"
        )
    return path


def inspect_native_archive(
    archive_path: str | Path,
    artifact: NativeArtifactSpec,
) -> ArchiveInspection:
    """Validate an exact tar layout without writing any member."""

    archive = Path(archive_path)
    verification = verify_native_artifact(archive, artifact)
    if not verification.success:
        raise ValueError(
            f"{artifact.artifact_id} archive is not verified: {verification.status}"
        )
    member_count = 0
    file_count = 0
    directory_count = 0
    total_bytes = 0
    seen: set[PurePosixPath] = set()
    with tarfile.open(archive, mode="r:gz") as handle:
        for member in handle:
            member_count += 1
            if member_count > MAX_ARCHIVE_MEMBERS:
                raise ValueError("archive exceeds the bounded member count")
            path = _safe_member_path(member.name, artifact.extract_root)
            if path in seen:
                raise ValueError(f"archive contains duplicate member: {member.name}")
            seen.add(path)
            if member.isdir():
                directory_count += 1
            elif member.isfile():
                if member.size < 0:
                    raise ValueError(f"archive member has a negative size: {member.name}")
                file_count += 1
                total_bytes += member.size
                if total_bytes > artifact.size_bytes * MAX_UNPACKED_SIZE_MULTIPLIER:
                    raise ValueError("archive exceeds the bounded unpacked size")
            else:
                raise ValueError(
                    "archive contains a link or special member: " + member.name
                )
    if member_count == 0 or file_count == 0:
        raise ValueError("archive must contain at least one regular file")
    if PurePosixPath(artifact.extract_root) not in seen:
        raise ValueError("archive does not contain its declared root member")
    return ArchiveInspection(
        artifact_id=artifact.artifact_id,
        member_count=member_count,
        regular_file_count=file_count,
        directory_count=directory_count,
        total_regular_file_bytes=total_bytes,
        expected_root=artifact.extract_root,
    )


def _create_directory(path: Path, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode & 0o777 or 0o700)


def _create_regular_file(
    handle: tarfile.TarFile,
    member: tarfile.TarInfo,
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(destination, flags, 0o600)
    try:
        source = handle.extractfile(member)
        if source is None:
            raise ValueError(f"unable to read archive member: {member.name}")
        with source, os.fdopen(descriptor, "wb", closefd=True) as output:
            descriptor = -1
            shutil.copyfileobj(source, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        destination.chmod(member.mode & 0o777 or 0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def stage_native_artifact(
    archive_path: str | Path,
    artifact: NativeArtifactSpec,
    runtime_root: str | Path,
) -> StagedArtifact:
    """Extract one verified archive through a private directory and rename."""

    started = time.perf_counter()
    archive = Path(archive_path).resolve()
    runtime = Path(runtime_root).resolve()
    if not runtime.is_dir() or runtime.is_symlink():
        raise ValueError("runtime_root must be an existing real directory")
    final_root = runtime / artifact.extract_root
    if final_root.exists() or final_root.is_symlink():
        raise FileExistsError(f"runtime artifact path already exists: {final_root}")
    inspection = inspect_native_archive(archive, artifact)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".xgap-stage-{artifact.artifact_id}-", dir=runtime)
    )
    try:
        with tarfile.open(archive, mode="r:gz") as handle:
            directories: list[tuple[Path, int]] = []
            for member in handle:
                relative = _safe_member_path(member.name, artifact.extract_root)
                destination = temporary.joinpath(*relative.parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    directories.append((destination, member.mode))
                elif member.isfile():
                    _create_regular_file(handle, member, destination)
                else:
                    raise ValueError(
                        "archive contains a link or special member: " + member.name
                    )
            for directory, mode in reversed(directories):
                _create_directory(directory, mode)
        extracted_root = temporary / artifact.extract_root
        if not extracted_root.is_dir() or extracted_root.is_symlink():
            raise ValueError("archive did not produce the declared directory root")
        extracted_root.rename(final_root)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return StagedArtifact(
        artifact_id=artifact.artifact_id,
        product=artifact.product,
        version=artifact.version,
        source_archive=archive,
        runtime_path=final_root,
        inspection=inspection,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def _validate_empty_runtime_root(runtime_root: Path) -> None:
    if not runtime_root.is_absolute():
        raise ValueError("runtime_root must be absolute")
    if runtime_root.is_symlink():
        raise ValueError("runtime_root must not be a symbolic link")
    if not runtime_root.is_dir():
        raise ValueError("runtime_root must be an existing directory")
    if any(runtime_root.iterdir()):
        raise ValueError("runtime_root must be empty and job-owned")
    if not os.access(runtime_root, os.W_OK | os.X_OK):
        raise ValueError("runtime_root must be writable and searchable")


def stage_m15_native_runtime(
    *,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    cache_root: str | Path,
    runtime_root: str | Path,
    manifest_path: str | Path,
) -> NativeRuntimeStagingRecord:
    """Stage both locked services and persist success or first failure."""

    lock_file = Path(lock_path).resolve()
    cache = Path(cache_root).resolve()
    runtime = Path(runtime_root)
    manifest = Path(manifest_path).resolve()
    _validate_empty_runtime_root(runtime)
    runtime = runtime.resolve()
    if manifest == runtime or runtime in manifest.parents:
        raise ValueError("staging manifest must be outside ephemeral runtime_root")
    started_at = _now()
    staged: list[StagedArtifact] = []
    lock: NativeRuntimeLock | None = None
    error: str | None = None
    try:
        lock = load_native_runtime_lock(lock_file)
        for artifact in lock.artifacts:
            archive = cache / artifact.filename
            staged.append(stage_native_artifact(archive, artifact, runtime))
    except Exception as exc:  # Persist the exact first staging failure.
        error = str(exc)
    ended_at = _now()
    success = error is None
    payload = {
        "schema_version": STAGING_SCHEMA_VERSION,
        "status": "success" if success else "failed",
        "error": error,
        "started_at": started_at,
        "ended_at": ended_at,
        "runtime_root": str(runtime),
        "runtime_storage_required": "allocation_local_non_network_filesystem",
        "lock_path": str(lock_file),
        "lock_sha256": _sha256_file(lock_file),
        "java_minimum_major": lock.java_minimum_major if lock is not None else None,
        "java_preferred_module": (
            lock.java_preferred_module if lock is not None else None
        ),
        "staged_artifacts": [item.to_dict() for item in staged],
        "archives_mutated": False,
        "archive_links_allowed": False,
        "automatic_retries": 0,
    }
    _write_json(manifest, payload)
    return NativeRuntimeStagingRecord(
        success=success,
        runtime_root=runtime,
        artifacts=tuple(staged),
        manifest_path=manifest,
        error=error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_STAGE_M15_NATIVE_RUNTIME") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_STAGE_M15_NATIVE_RUNTIME=1 inside a dedicated "
                        "allocation"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    record = stage_m15_native_runtime(
        lock_path=args.lock,
        cache_root=args.cache_root,
        runtime_root=args.runtime_root,
        manifest_path=args.manifest,
    )
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
