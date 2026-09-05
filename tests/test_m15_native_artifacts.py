from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_native_artifacts import (
    LOCK_SCHEMA_VERSION,
    NativeArtifactSpec,
    fetch_native_artifact,
    load_native_runtime_lock,
    main,
    parse_java_major,
    prepare_m15_native_artifacts,
    verify_native_artifact,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "services" / "m15-native-runtime.lock.json"


class FakeResponse:
    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _artifact(
    *,
    product: str = "neo4j",
    payload: bytes = b"locked archive",
    digest_value: str | None = None,
) -> NativeArtifactSpec:
    algorithm = "sha256" if product == "neo4j" else "sha512"
    filename = f"{product}-test.tar.gz"
    host = "dist.neo4j.org" if product == "neo4j" else "archive.apache.org"
    return NativeArtifactSpec.from_dict(
        {
            "artifact_id": product,
            "product": product,
            "edition": "test",
            "version": "1.0",
            "filename": filename,
            "url": f"https://{host}/{filename}",
            "size_bytes": len(payload),
            "digest": {
                "algorithm": algorithm,
                "value": digest_value or hashlib.new(algorithm, payload).hexdigest(),
            },
            "archive_format": "tar.gz",
            "extract_root": f"{product}-test",
            "source_page": f"https://{host}/",
        }
    )


def _write_lock(path: Path, neo4j_payload: bytes, fuseki_payload: bytes) -> None:
    artifacts = [
        _artifact(product="neo4j", payload=neo4j_payload).to_dict(),
        _artifact(product="fuseki", payload=fuseki_payload).to_dict(),
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": LOCK_SCHEMA_VERSION,
                "frozen_at_utc": "2026-09-05T00:00:00Z",
                "java": {
                    "minimum_major": 17,
                    "preferred_module": "Java/17.0.6",
                    "selection_reason": "test",
                },
                "network_policy": "one attempt",
                "runtime_storage_policy": "node local",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )


def test_frozen_lock_selects_common_java_17_runtime_and_exact_archives() -> None:
    lock = load_native_runtime_lock(LOCK_PATH)

    assert lock.java_minimum_major == 17
    assert lock.java_preferred_module == "Java/17.0.6"
    assert [item.product for item in lock.artifacts] == ["neo4j", "fuseki"]
    neo4j = lock.artifact("neo4j-community")
    fuseki = lock.artifact("apache-jena-fuseki")
    assert (neo4j.version, neo4j.size_bytes, neo4j.digest_algorithm) == (
        "5.26.30",
        162360826,
        "sha256",
    )
    assert neo4j.digest_value == (
        "f22934e3f7c1ddae743d91243f38aa492f007471c6a2bdbdc882fe2b3e1e4bdd"
    )
    assert (fuseki.version, fuseki.size_bytes, fuseki.digest_algorithm) == (
        "5.6.0",
        50290245,
        "sha512",
    )
    assert fuseki.digest_value == (
        "53dfe13cdd5f6387a0c62917e275fde2cd2e2f2052bfe7515384934f24915228"
        "b8512a2dd2b50b7060cc300c976254349d991fcea239484cae48e0a59d67cd54"
    )


@pytest.mark.parametrize(
    ("version_output", "expected"),
    [
        ('openjdk version "1.8.0_402"\n', 8),
        ('openjdk version "17.0.6" 2023-01-17\n', 17),
        ('java version "21.0.8" 2026-07-15 LTS\n', 21),
    ],
)
def test_java_major_parser_handles_legacy_and_modern_versions(
    version_output: str,
    expected: int,
) -> None:
    assert parse_java_major(version_output) == expected


def test_java_major_parser_rejects_unstructured_output() -> None:
    with pytest.raises(ValueError, match="quoted version"):
        parse_java_major("java command not found")


def test_native_probe_checks_java_major_and_preparation_is_download_only() -> None:
    probe = (
        REPO_ROOT / "scripts" / "slurm" / "probe_m15_native_services.sbatch"
    ).read_text(encoding="utf-8")
    preparation = (
        REPO_ROOT / "scripts" / "slurm" / "prepare_m15_native_artifacts.sbatch"
    ).read_text(encoding="utf-8")

    assert "probe_version=m15-b2-native-v2" in probe
    assert "MINIMUM_JAVA_MAJOR=17" in probe
    assert "Java/17.0.6" in probe
    assert "JAVA_COMPATIBLE" in probe
    assert 'if [[ "$JAVA_COMPATIBLE" == true' in probe
    assert "XGAP_PREPARE_M15_NATIVE_ARTIFACTS=1" in preparation
    assert "automatic_retries=0" in preparation
    assert "archives_extracted=false" in preparation
    assert "services_started=false" in preparation
    assert "neo4j start" not in preparation
    assert "fuseki-server" not in preparation


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("url", "http://dist.neo4j.org/test.tar.gz", "official URL"),
        ("url", "https://example.test/test.tar.gz", "official URL"),
        ("filename", "../test.tar.gz", "safe basename"),
        ("size_bytes", 0, "positive"),
    ],
)
def test_artifact_spec_rejects_unsafe_or_unfrozen_fields(
    field: str,
    value: object,
    match: str,
) -> None:
    raw = _artifact().to_dict()
    raw[field] = value

    with pytest.raises(ValueError, match=match):
        NativeArtifactSpec.from_dict(raw)


def test_verifier_distinguishes_missing_size_digest_and_symlink(
    tmp_path: Path,
) -> None:
    payload = b"exact"
    artifact = _artifact(payload=payload)
    archive = tmp_path / artifact.filename

    assert verify_native_artifact(archive, artifact).status == "missing"
    archive.write_bytes(b"shorter or longer")
    assert verify_native_artifact(archive, artifact).status == "size_mismatch"
    archive.write_bytes(b"wrong")
    assert verify_native_artifact(archive, artifact).status == "digest_mismatch"
    archive.unlink()
    target = tmp_path / "target"
    target.write_bytes(payload)
    archive.symlink_to(target)
    assert verify_native_artifact(archive, artifact).status == "symbolic_link_rejected"


def test_fetch_downloads_once_publishes_exact_file_and_cleans_partial(
    tmp_path: Path,
) -> None:
    payload = b"exact archive payload"
    artifact = _artifact(payload=payload)
    calls: list[tuple[str, float]] = []

    def opener(url: str, timeout: float) -> FakeResponse:
        calls.append((url, timeout))
        return FakeResponse(payload)

    result = fetch_native_artifact(
        artifact,
        tmp_path,
        opener=opener,
        timeout_seconds=7,
    )

    assert result.success
    assert result.status == "downloaded_and_verified"
    assert result.download_attempts == 1
    assert result.bytes_downloaded == len(payload)
    assert result.destination.read_bytes() == payload
    assert calls == [(artifact.url, 7)]
    assert list(tmp_path.glob("*.partial")) == []


def test_fetch_reuses_verified_cache_without_network(tmp_path: Path) -> None:
    payload = b"exact archive payload"
    artifact = _artifact(payload=payload)
    (tmp_path / artifact.filename).write_bytes(payload)

    def opener(*args: object, **kwargs: object) -> FakeResponse:
        raise AssertionError("network must not be called for a verified cache")

    result = fetch_native_artifact(artifact, tmp_path, opener=opener)

    assert result.success
    assert result.status == "verified_cache_reused"
    assert result.download_attempts == 0
    assert result.bytes_downloaded == 0


def test_fetch_refuses_conflicting_cache_without_overwrite_or_network(
    tmp_path: Path,
) -> None:
    payload = b"exact archive payload"
    artifact = _artifact(payload=payload)
    destination = tmp_path / artifact.filename
    destination.write_bytes(b"conflict")

    def opener(*args: object, **kwargs: object) -> FakeResponse:
        raise AssertionError("network must not be called for a cache conflict")

    result = fetch_native_artifact(artifact, tmp_path, opener=opener)

    assert not result.success
    assert result.status == "cache_conflict"
    assert result.download_attempts == 0
    assert destination.read_bytes() == b"conflict"


def test_fetch_discards_invalid_download_without_retry_or_final_file(
    tmp_path: Path,
) -> None:
    payload = b"expected"
    artifact = _artifact(payload=payload)
    calls = 0

    def opener(url: str, timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(b"invalid!")

    result = fetch_native_artifact(artifact, tmp_path, opener=opener)

    assert not result.success
    assert result.status == "download_verification_failed"
    assert result.download_attempts == 1
    assert calls == 1
    assert not (tmp_path / artifact.filename).exists()
    assert list(tmp_path.iterdir()) == []


def test_preparation_persists_success_and_reuses_cache_on_independent_run(
    tmp_path: Path,
) -> None:
    neo4j_payload = b"neo4j"
    fuseki_payload = b"fuseki"
    lock_path = tmp_path / "runtime.lock.json"
    cache = tmp_path / "cache"
    output = tmp_path / "runs"
    _write_lock(lock_path, neo4j_payload, fuseki_payload)
    payloads = {
        "https://dist.neo4j.org/neo4j-test.tar.gz": neo4j_payload,
        "https://archive.apache.org/fuseki-test.tar.gz": fuseki_payload,
    }
    calls: list[str] = []

    def opener(url: str, timeout: float) -> FakeResponse:
        calls.append(url)
        return FakeResponse(payloads[url])

    first = prepare_m15_native_artifacts(
        lock_path=lock_path,
        cache_root=cache,
        output_root=output,
        run_id="first",
        repo_root=REPO_ROOT,
        opener=opener,
    )
    second = prepare_m15_native_artifacts(
        lock_path=lock_path,
        cache_root=cache,
        output_root=output,
        run_id="second",
        repo_root=REPO_ROOT,
        opener=opener,
    )

    assert first.success and second.success
    assert len(calls) == 2
    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert first_manifest["download_attempts"] == 2
    assert second_manifest["download_attempts"] == 0
    assert first_manifest["automatic_retries"] == 0
    assert first_manifest["archives_extracted"] is False
    assert first_manifest["services_started"] is False
    assert first_manifest["credentials_persisted"] is False
    assert [item["status"] for item in second_manifest["fetches"]] == [
        "verified_cache_reused",
        "verified_cache_reused",
    ]
    assert (first.run_root / "runtime_lock.json").read_bytes() == lock_path.read_bytes()


def test_preparation_stops_after_first_failed_artifact_and_preserves_evidence(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "runtime.lock.json"
    _write_lock(lock_path, b"neo4j", b"fuseki")
    calls: list[str] = []

    def opener(url: str, timeout: float) -> FakeResponse:
        calls.append(url)
        return FakeResponse(b"wrong")

    record = prepare_m15_native_artifacts(
        lock_path=lock_path,
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "runs",
        run_id="failed",
        repo_root=REPO_ROOT,
        opener=opener,
    )

    assert not record.success
    assert len(calls) == 1
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert manifest["download_attempts"] == 1
    assert len(manifest["fetches"]) == 1
    assert manifest["fetches"][0]["status"] == "download_verification_failed"


def test_preparation_run_directory_is_immutable(tmp_path: Path) -> None:
    lock_path = tmp_path / "runtime.lock.json"
    _write_lock(lock_path, b"neo4j", b"fuseki")
    (tmp_path / "runs" / "existing").mkdir(parents=True)

    with pytest.raises(FileExistsError):
        prepare_m15_native_artifacts(
            lock_path=lock_path,
            cache_root=tmp_path / "cache",
            output_root=tmp_path / "runs",
            run_id="existing",
            repo_root=REPO_ROOT,
        )


def test_cli_is_fail_closed_before_any_download(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_PREPARE_M15_NATIVE_ARTIFACTS", raising=False)

    code = main(["--cache-root", "/unused"])

    assert code == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
