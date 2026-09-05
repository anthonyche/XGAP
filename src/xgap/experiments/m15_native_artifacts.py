"""Pinned, single-attempt artifact supply for M15 native graph services.

This module prepares immutable archives outside query execution.  It does not
extract archives, start services, choose ports, or make an artifact available
to the agent as a query-time tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


LOCK_SCHEMA_VERSION = "m15-native-runtime-lock-v1"
RUN_SCHEMA_VERSION = "m15-b2b-native-artifact-preparation-v1"
DEFAULT_LOCK_PATH = Path("services/m15-native-runtime.lock.json")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HEX = re.compile(r"^[0-9a-f]+$")
_DIGEST_LENGTHS = {"sha256": 64, "sha512": 128}
_OFFICIAL_DOWNLOAD_HOSTS = {
    "neo4j": frozenset({"dist.neo4j.org"}),
    "fuseki": frozenset({"archive.apache.org"}),
}


@dataclass(frozen=True)
class NativeArtifactSpec:
    artifact_id: str
    product: str
    edition: str
    version: str
    filename: str
    url: str
    size_bytes: int
    digest_algorithm: str
    digest_value: str
    archive_format: str
    extract_root: str
    source_page: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NativeArtifactSpec":
        digest = value.get("digest")
        if not isinstance(digest, Mapping):
            raise ValueError("native artifact digest must be an object")
        size = value.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int):
            raise ValueError("native artifact size_bytes must be an integer")
        artifact = cls(
            artifact_id=str(value.get("artifact_id", "")),
            product=str(value.get("product", "")),
            edition=str(value.get("edition", "")),
            version=str(value.get("version", "")),
            filename=str(value.get("filename", "")),
            url=str(value.get("url", "")),
            size_bytes=size,
            digest_algorithm=str(digest.get("algorithm", "")).lower(),
            digest_value=str(digest.get("value", "")).lower(),
            archive_format=str(value.get("archive_format", "")),
            extract_root=str(value.get("extract_root", "")),
            source_page=str(value.get("source_page", "")),
        )
        artifact.validate()
        return artifact

    def validate(self) -> None:
        required = {
            "artifact_id": self.artifact_id,
            "product": self.product,
            "edition": self.edition,
            "version": self.version,
            "filename": self.filename,
            "url": self.url,
            "extract_root": self.extract_root,
            "source_page": self.source_page,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "native artifact fields must be non-empty: " + ", ".join(missing)
            )
        if self.product not in _OFFICIAL_DOWNLOAD_HOSTS:
            raise ValueError(f"unsupported native artifact product: {self.product}")
        if self.size_bytes <= 0:
            raise ValueError("native artifact size_bytes must be positive")
        if self.archive_format != "tar.gz":
            raise ValueError("M15 native artifacts must use tar.gz archives")
        if Path(self.filename).name != self.filename or self.filename in {".", ".."}:
            raise ValueError("native artifact filename must be a safe basename")
        if Path(self.extract_root).name != self.extract_root or self.extract_root in {
            ".",
            "..",
        }:
            raise ValueError("native artifact extract_root must be a safe basename")
        expected_length = _DIGEST_LENGTHS.get(self.digest_algorithm)
        if expected_length is None:
            raise ValueError("native artifact digest must use sha256 or sha512")
        if (
            len(self.digest_value) != expected_length
            or _HEX.fullmatch(self.digest_value) is None
        ):
            raise ValueError("native artifact digest has invalid length or encoding")
        parsed = urllib.parse.urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _OFFICIAL_DOWNLOAD_HOSTS[self.product]
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                f"native artifact URL is not an approved official URL: {self.url}"
            )
        source = urllib.parse.urlsplit(self.source_page)
        if source.scheme != "https" or source.hostname is None:
            raise ValueError("native artifact source_page must be HTTPS")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "product": self.product,
            "edition": self.edition,
            "version": self.version,
            "filename": self.filename,
            "url": self.url,
            "size_bytes": self.size_bytes,
            "digest": {
                "algorithm": self.digest_algorithm,
                "value": self.digest_value,
            },
            "archive_format": self.archive_format,
            "extract_root": self.extract_root,
            "source_page": self.source_page,
        }


@dataclass(frozen=True)
class NativeRuntimeLock:
    java_minimum_major: int
    java_preferred_module: str
    java_selection_reason: str
    network_policy: str
    runtime_storage_policy: str
    frozen_at_utc: str
    artifacts: tuple[NativeArtifactSpec, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NativeRuntimeLock":
        if value.get("schema_version") != LOCK_SCHEMA_VERSION:
            raise ValueError(
                f"native runtime lock schema must be {LOCK_SCHEMA_VERSION}"
            )
        java = value.get("java")
        artifacts = value.get("artifacts")
        if not isinstance(java, Mapping):
            raise ValueError("native runtime lock java must be an object")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("native runtime lock artifacts must be a non-empty list")
        minimum = java.get("minimum_major")
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum <= 0:
            raise ValueError("native runtime minimum Java major must be positive")
        parsed = tuple(
            NativeArtifactSpec.from_dict(item)
            for item in artifacts
            if isinstance(item, Mapping)
        )
        if len(parsed) != len(artifacts):
            raise ValueError("every native runtime artifact must be an object")
        identifiers = [item.artifact_id for item in parsed]
        filenames = [item.filename for item in parsed]
        products = [item.product for item in parsed]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("native runtime artifact IDs must be unique")
        if len(set(filenames)) != len(filenames):
            raise ValueError("native runtime artifact filenames must be unique")
        if set(products) != {"neo4j", "fuseki"} or len(products) != 2:
            raise ValueError("M15 native runtime must lock exactly Neo4j and Fuseki")
        lock = cls(
            java_minimum_major=minimum,
            java_preferred_module=str(java.get("preferred_module", "")),
            java_selection_reason=str(java.get("selection_reason", "")),
            network_policy=str(value.get("network_policy", "")),
            runtime_storage_policy=str(value.get("runtime_storage_policy", "")),
            frozen_at_utc=str(value.get("frozen_at_utc", "")),
            artifacts=parsed,
        )
        if not all(
            (
                lock.java_preferred_module,
                lock.java_selection_reason,
                lock.network_policy,
                lock.runtime_storage_policy,
                lock.frozen_at_utc,
            )
        ):
            raise ValueError("native runtime lock metadata must be non-empty")
        return lock

    def artifact(self, artifact_id: str) -> NativeArtifactSpec:
        for artifact in self.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise KeyError(artifact_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LOCK_SCHEMA_VERSION,
            "frozen_at_utc": self.frozen_at_utc,
            "java": {
                "minimum_major": self.java_minimum_major,
                "preferred_module": self.java_preferred_module,
                "selection_reason": self.java_selection_reason,
            },
            "network_policy": self.network_policy,
            "runtime_storage_policy": self.runtime_storage_policy,
            "artifacts": [item.to_dict() for item in self.artifacts],
        }


@dataclass(frozen=True)
class ArtifactVerification:
    success: bool
    status: str
    path: Path
    expected_size_bytes: int
    actual_size_bytes: int | None
    digest_algorithm: str
    expected_digest: str
    actual_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "path": str(self.path),
            "expected_size_bytes": self.expected_size_bytes,
            "actual_size_bytes": self.actual_size_bytes,
            "digest_algorithm": self.digest_algorithm,
            "expected_digest": self.expected_digest,
            "actual_digest": self.actual_digest,
        }


@dataclass(frozen=True)
class ArtifactFetchRecord:
    artifact_id: str
    success: bool
    status: str
    destination: Path
    download_attempts: int
    bytes_downloaded: int
    elapsed_ms: float
    verification: ArtifactVerification
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "success": self.success,
            "status": self.status,
            "destination": str(self.destination),
            "download_attempts": self.download_attempts,
            "bytes_downloaded": self.bytes_downloaded,
            "elapsed_ms": self.elapsed_ms,
            "verification": self.verification.to_dict(),
            "error": self.error,
        }


@dataclass(frozen=True)
class NativeArtifactPreparationRecord:
    run_id: str
    run_root: Path
    success: bool
    status_path: Path
    manifest_path: Path
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_root": str(self.run_root),
            "success": self.success,
            "status_path": str(self.status_path),
            "manifest_path": str(self.manifest_path),
            "error": self.error,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
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


def load_native_runtime_lock(path: str | Path) -> NativeRuntimeLock:
    parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise ValueError("native runtime lock must contain a JSON object")
    return NativeRuntimeLock.from_dict(parsed)


def parse_java_major(version_output: str) -> int:
    """Parse both legacy ``1.8`` and modern Java version strings."""

    match = re.search(r'version\s+"([^"]+)"', version_output)
    if match is None:
        raise ValueError("Java version output does not contain a quoted version")
    components = match.group(1).split(".")
    try:
        major = int(components[1] if components[0] == "1" else components[0])
    except (IndexError, ValueError) as exc:
        raise ValueError("Java version output has an invalid major version") from exc
    if major <= 0:
        raise ValueError("Java major version must be positive")
    return major


def verify_native_artifact(
    path: str | Path,
    artifact: NativeArtifactSpec,
) -> ArtifactVerification:
    selected = Path(path)
    if selected.is_symlink():
        return ArtifactVerification(
            False,
            "symbolic_link_rejected",
            selected,
            artifact.size_bytes,
            None,
            artifact.digest_algorithm,
            artifact.digest_value,
            None,
        )
    if not selected.exists():
        return ArtifactVerification(
            False,
            "missing",
            selected,
            artifact.size_bytes,
            None,
            artifact.digest_algorithm,
            artifact.digest_value,
            None,
        )
    if not selected.is_file():
        return ArtifactVerification(
            False,
            "not_a_regular_file",
            selected,
            artifact.size_bytes,
            None,
            artifact.digest_algorithm,
            artifact.digest_value,
            None,
        )
    actual_size = selected.stat().st_size
    if actual_size != artifact.size_bytes:
        return ArtifactVerification(
            False,
            "size_mismatch",
            selected,
            artifact.size_bytes,
            actual_size,
            artifact.digest_algorithm,
            artifact.digest_value,
            None,
        )
    actual_digest = _file_digest(selected, artifact.digest_algorithm)
    success = actual_digest == artifact.digest_value
    return ArtifactVerification(
        success,
        "verified" if success else "digest_mismatch",
        selected,
        artifact.size_bytes,
        actual_size,
        artifact.digest_algorithm,
        artifact.digest_value,
        actual_digest,
    )


def fetch_native_artifact(
    artifact: NativeArtifactSpec,
    cache_root: str | Path,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout_seconds: float = 1800.0,
) -> ArtifactFetchRecord:
    """Reuse or fetch one exact archive, with one network attempt and no retry."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    started = time.perf_counter()
    cache = Path(cache_root).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / artifact.filename
    existing = verify_native_artifact(destination, artifact)
    if existing.success:
        return ArtifactFetchRecord(
            artifact.artifact_id,
            True,
            "verified_cache_reused",
            destination,
            0,
            0,
            (time.perf_counter() - started) * 1000,
            existing,
        )
    if destination.exists() or destination.is_symlink():
        return ArtifactFetchRecord(
            artifact.artifact_id,
            False,
            "cache_conflict",
            destination,
            0,
            0,
            (time.perf_counter() - started) * 1000,
            existing,
            "existing cache entry does not match the frozen artifact",
        )

    partial_path: Path | None = None
    downloaded = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{artifact.filename}.",
            suffix=".partial",
            dir=cache,
            delete=False,
        ) as partial:
            partial_path = Path(partial.name)
            with opener(artifact.url, timeout=timeout_seconds) as response:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    partial.write(block)
                    downloaded += len(block)
                    if downloaded > artifact.size_bytes:
                        raise ValueError("download exceeded frozen size")
            partial.flush()
            os.fsync(partial.fileno())
        verification = verify_native_artifact(partial_path, artifact)
        if not verification.success:
            return ArtifactFetchRecord(
                artifact.artifact_id,
                False,
                "download_verification_failed",
                destination,
                1,
                downloaded,
                (time.perf_counter() - started) * 1000,
                verification,
                "download did not match the frozen size and digest",
            )
        try:
            os.link(partial_path, destination)
        except FileExistsError:
            raced = verify_native_artifact(destination, artifact)
            return ArtifactFetchRecord(
                artifact.artifact_id,
                raced.success,
                "verified_cache_reused_after_race" if raced.success else "cache_conflict",
                destination,
                1,
                downloaded,
                (time.perf_counter() - started) * 1000,
                raced,
                None if raced.success else "concurrent cache entry is invalid",
            )
        except OSError as exc:
            return ArtifactFetchRecord(
                artifact.artifact_id,
                False,
                "publication_failed",
                destination,
                1,
                downloaded,
                (time.perf_counter() - started) * 1000,
                verification,
                str(exc),
            )
        published = verify_native_artifact(destination, artifact)
        if not published.success:
            try:
                destination.unlink()
            except OSError:
                pass
        return ArtifactFetchRecord(
            artifact.artifact_id,
            published.success,
            "downloaded_and_verified" if published.success else "publication_failed",
            destination,
            1,
            downloaded,
            (time.perf_counter() - started) * 1000,
            published,
            None if published.success else "published cache entry failed verification",
        )
    except Exception as exc:  # Preserve the one external attempt as evidence.
        missing = verify_native_artifact(destination, artifact)
        return ArtifactFetchRecord(
            artifact.artifact_id,
            False,
            "download_failed",
            destination,
            1,
            downloaded,
            (time.perf_counter() - started) * 1000,
            missing,
            str(exc),
        )
    finally:
        if partial_path is not None:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                pass


def prepare_m15_native_artifacts(
    *,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    cache_root: str | Path,
    output_root: str | Path = "runs",
    run_id: str | None = None,
    repo_root: str | Path | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout_seconds: float = 1800.0,
) -> NativeArtifactPreparationRecord:
    """Prepare all locked archives sequentially and persist a complete outcome."""

    root = Path(repo_root).resolve() if repo_root is not None else _repo_root()
    selected_run_id = run_id or f"m15-native-artifacts-{_now_slug()}"
    if _SAFE_RUN_ID.fullmatch(selected_run_id) is None:
        raise ValueError("run_id contains unsupported characters")
    destination_root = Path(output_root)
    if not destination_root.is_absolute():
        destination_root = root / destination_root
    run_root = destination_root.resolve() / selected_run_id
    run_root.mkdir(parents=True, exist_ok=False)
    status_path = run_root / "run_status.json"
    manifest_path = run_root / "run_manifest.json"
    started_at = _now()
    _write_json(
        status_path,
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "running",
            "started_at": started_at,
        },
    )

    selected_lock_path = Path(lock_path)
    if not selected_lock_path.is_absolute():
        selected_lock_path = root / selected_lock_path
    selected_lock_path = selected_lock_path.resolve()
    fetches: list[ArtifactFetchRecord] = []
    lock: NativeRuntimeLock | None = None
    lock_sha256: str | None = None
    error: str | None = None
    try:
        lock_sha256 = _file_digest(selected_lock_path, "sha256")
        lock = load_native_runtime_lock(selected_lock_path)
        (run_root / "runtime_lock.json").write_bytes(selected_lock_path.read_bytes())
        for artifact in lock.artifacts:
            record = fetch_native_artifact(
                artifact,
                cache_root,
                opener=opener,
                timeout_seconds=timeout_seconds,
            )
            fetches.append(record)
            _write_json(
                run_root / "artifact_fetches.json",
                [item.to_dict() for item in fetches],
            )
            if not record.success:
                raise RuntimeError(
                    f"{artifact.artifact_id} preparation failed: {record.error}"
                )
    except Exception as exc:  # Persist configuration and external failures.
        error = str(exc)
        if not (run_root / "artifact_fetches.json").exists():
            _write_json(run_root / "artifact_fetches.json", [])

    ended_at = _now()
    success = error is None
    _write_json(
        status_path,
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    _write_json(
        manifest_path,
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "status": "success" if success else "failed",
            "error": error,
            "started_at": started_at,
            "ended_at": ended_at,
            "git": _git_state(root),
            "environment": {
                "hostname": platform.node(),
                "python": sys.version,
                "platform": platform.platform(),
            },
            "lock_path": str(selected_lock_path),
            "lock_sha256": lock_sha256,
            "lock": lock.to_dict() if lock is not None else None,
            "cache_root": str(Path(cache_root).resolve()),
            "fetches": [item.to_dict() for item in fetches],
            "download_attempts": sum(item.download_attempts for item in fetches),
            "automatic_retries": 0,
            "archives_extracted": False,
            "services_started": False,
            "credentials_persisted": False,
            "artifacts": sorted(
                {
                    *(path.name for path in run_root.iterdir()),
                    manifest_path.name,
                }
            ),
        },
    )
    return NativeArtifactPreparationRecord(
        selected_run_id,
        run_root,
        success,
        status_path,
        manifest_path,
        error,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--run-id")
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    args = parser.parse_args(argv)
    if os.environ.get("XGAP_PREPARE_M15_NATIVE_ARTIFACTS") != "1":
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": (
                        "set XGAP_PREPARE_M15_NATIVE_ARTIFACTS=1 to permit "
                        "the two pinned archive downloads"
                    ),
                },
                sort_keys=True,
            )
        )
        return 3
    try:
        record = prepare_m15_native_artifacts(
            lock_path=args.lock,
            cache_root=args.cache_root,
            output_root=args.output_root,
            run_id=args.run_id,
            timeout_seconds=args.timeout_seconds,
        )
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return 0 if record.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
