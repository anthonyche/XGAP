from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from xgap.experiments.m15_native_artifacts import LOCK_SCHEMA_VERSION, NativeArtifactSpec
from xgap.experiments.m15_native_runtime import (
    inspect_native_archive,
    main,
    stage_m15_native_runtime,
    stage_native_artifact,
)


def _write_archive(
    path: Path,
    root: str,
    files: dict[str, tuple[bytes, int]],
    *,
    extra_members: tuple[tarfile.TarInfo, ...] = (),
) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        root_info = tarfile.TarInfo(root)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        archive.addfile(root_info)
        for relative, (payload, mode) in files.items():
            info = tarfile.TarInfo(f"{root}/{relative}")
            info.size = len(payload)
            info.mode = mode
            archive.addfile(info, io.BytesIO(payload))
        for member in extra_members:
            archive.addfile(member)


def _artifact(product: str, archive: Path, root: str) -> NativeArtifactSpec:
    algorithm = "sha256" if product == "neo4j" else "sha512"
    digest = hashlib.new(algorithm, archive.read_bytes()).hexdigest()
    host = "dist.neo4j.org" if product == "neo4j" else "archive.apache.org"
    return NativeArtifactSpec.from_dict(
        {
            "artifact_id": product,
            "product": product,
            "edition": "test",
            "version": "1.0",
            "filename": archive.name,
            "url": f"https://{host}/{archive.name}",
            "size_bytes": archive.stat().st_size,
            "digest": {"algorithm": algorithm, "value": digest},
            "archive_format": "tar.gz",
            "extract_root": root,
            "source_page": f"https://{host}/",
        }
    )


def _runtime_fixture(tmp_path: Path) -> tuple[Path, Path]:
    cache = tmp_path / "cache"
    cache.mkdir()
    neo4j_archive = cache / "neo4j-test.tar.gz"
    fuseki_archive = cache / "fuseki-test.tar.gz"
    _write_archive(
        neo4j_archive,
        "neo4j-test",
        {"bin/neo4j": (b"#!/bin/sh\n", 0o755), "conf/neo4j.conf": (b"", 0o644)},
    )
    _write_archive(
        fuseki_archive,
        "fuseki-test",
        {"fuseki-server": (b"#!/bin/sh\n", 0o755), "README": (b"test\n", 0o644)},
    )
    artifacts = [
        _artifact("neo4j", neo4j_archive, "neo4j-test").to_dict(),
        _artifact("fuseki", fuseki_archive, "fuseki-test").to_dict(),
    ]
    lock = tmp_path / "runtime.lock.json"
    lock.write_text(
        json.dumps(
            {
                "schema_version": LOCK_SCHEMA_VERSION,
                "frozen_at_utc": "2026-09-05T00:00:00Z",
                "java": {
                    "minimum_major": 17,
                    "preferred_module": "Java/17.0.6",
                    "selection_reason": "test",
                },
                "network_policy": "verified cache",
                "runtime_storage_policy": "allocation local",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return cache, lock


def test_inspection_and_staging_preserve_only_regular_files_and_modes(
    tmp_path: Path,
) -> None:
    cache, lock_path = _runtime_fixture(tmp_path)
    raw = json.loads(lock_path.read_text(encoding="utf-8"))
    artifact = NativeArtifactSpec.from_dict(raw["artifacts"][0])
    archive = cache / artifact.filename
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    inspection = inspect_native_archive(archive, artifact)
    staged = stage_native_artifact(archive, artifact, runtime)

    assert inspection.member_count == 3
    assert inspection.regular_file_count == 2
    assert inspection.directory_count == 1
    assert staged.runtime_path == runtime / "neo4j-test"
    executable = staged.runtime_path / "bin" / "neo4j"
    assert executable.read_bytes() == b"#!/bin/sh\n"
    assert executable.stat().st_mode & 0o111
    assert list(runtime.glob(".xgap-stage-*")) == []


@pytest.mark.parametrize("member_kind", ["traversal", "symlink"])
def test_inspection_rejects_traversal_and_link_members(
    tmp_path: Path,
    member_kind: str,
) -> None:
    archive = tmp_path / "neo4j-test.tar.gz"
    if member_kind == "traversal":
        member = tarfile.TarInfo("neo4j-test/../../escape")
        member.type = tarfile.DIRTYPE
    else:
        member = tarfile.TarInfo("neo4j-test/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
    _write_archive(
        archive,
        "neo4j-test",
        {"bin/neo4j": (b"#!/bin/sh\n", 0o755)},
        extra_members=(member,),
    )
    artifact = _artifact("neo4j", archive, "neo4j-test")

    with pytest.raises(ValueError, match="unsafe|link or special"):
        inspect_native_archive(archive, artifact)


def test_staging_rejects_archive_with_wrong_declared_root(tmp_path: Path) -> None:
    archive = tmp_path / "neo4j-test.tar.gz"
    _write_archive(archive, "different-root", {"file": (b"x", 0o644)})
    artifact = _artifact("neo4j", archive, "neo4j-test")

    with pytest.raises(ValueError, match="outside expected root"):
        inspect_native_archive(archive, artifact)


def test_runtime_staging_persists_exact_two_product_manifest(tmp_path: Path) -> None:
    cache, lock = _runtime_fixture(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    manifest = tmp_path / "evidence" / "staging.json"

    record = stage_m15_native_runtime(
        lock_path=lock,
        cache_root=cache,
        runtime_root=runtime,
        manifest_path=manifest,
    )

    assert record.success
    assert [item.product for item in record.artifacts] == ["neo4j", "fuseki"]
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["runtime_storage_required"] == (
        "allocation_local_non_network_filesystem"
    )
    assert payload["archive_links_allowed"] is False
    assert payload["archives_mutated"] is False
    assert payload["automatic_retries"] == 0
    assert {path.name for path in runtime.iterdir()} == {"neo4j-test", "fuseki-test"}


def test_runtime_staging_records_first_failure_without_fabricating_second(
    tmp_path: Path,
) -> None:
    cache, lock = _runtime_fixture(tmp_path)
    (cache / "neo4j-test.tar.gz").write_bytes(b"corrupt")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    manifest = tmp_path / "staging.json"

    record = stage_m15_native_runtime(
        lock_path=lock,
        cache_root=cache,
        runtime_root=runtime,
        manifest_path=manifest,
    )

    assert not record.success
    assert record.artifacts == ()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["staged_artifacts"] == []
    assert "not verified" in payload["error"]
    assert list(runtime.iterdir()) == []


def test_runtime_root_must_be_absolute_empty_real_and_manifest_external(
    tmp_path: Path,
) -> None:
    cache, lock = _runtime_fixture(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    marker = runtime / "owned-by-user"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="empty and job-owned"):
        stage_m15_native_runtime(
            lock_path=lock,
            cache_root=cache,
            runtime_root=runtime,
            manifest_path=tmp_path / "manifest.json",
        )
    assert marker.read_text(encoding="utf-8") == "keep"

    marker.unlink()
    with pytest.raises(ValueError, match="outside ephemeral"):
        stage_m15_native_runtime(
            lock_path=lock,
            cache_root=cache,
            runtime_root=runtime,
            manifest_path=runtime / "manifest.json",
        )
    assert list(runtime.iterdir()) == []


def test_runtime_cli_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_STAGE_M15_NATIVE_RUNTIME", raising=False)

    code = main(
        [
            "--cache-root",
            str(tmp_path / "cache"),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--manifest",
            str(tmp_path / "manifest.json"),
        ]
    )

    assert code == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
