"""Offline native-entry wiring for frozen FinBench source-archive identity."""

from __future__ import annotations

from contextlib import nullcontext
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import xgap.experiments.m15_native_services as native_services
from test_m15_native_services import REPO_ROOT, _StableProcess, _staged_runtime


@pytest.mark.parametrize("explicit_mode", [None, "source_archive"])
def test_cli_preserves_identity_and_tiny_subset_through_mocked_native_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    explicit_mode: str | None,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    monkeypatch.setenv("XGAP_RUN_M15_NATIVE_SERVICES", "1")
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: native_services.JavaEvidence("/fake/java", 17, "17"),
    )
    monkeypatch.setattr(
        native_services.LoopbackPortReservations,
        "acquire",
        lambda _count: nullcontext(
            SimpleNamespace(ports=(17474, 17687, 13030), release=lambda _index: None)
        ),
    )
    monkeypatch.setattr(
        native_services,
        "start_service",
        lambda spec: native_services.RunningService(spec, _StableProcess(), io.BytesIO()),
    )
    monkeypatch.setattr(
        native_services,
        "wait_for_service_health",
        lambda service: native_services.HealthObservation(
            service.spec.service_id, True, 1, 1.0, 200
        ),
    )

    def fake_stop(service):
        service.log_handle.close()
        return native_services.ShutdownObservation(
            service.spec.service_id, service.process.pid, None, 0,
            "SIGTERM", False, True,
        )

    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(native_services, "load_finbench_source_partition", lambda _path: {})
    for name in (
        "Neo4jClient", "FusekiClient", "Neo4jCypherFixtureLoader",
        "FusekiGraphStoreFixtureLoader",
    ):
        monkeypatch.setattr(native_services, name, lambda _input: SimpleNamespace())
    observed: list[dict] = []

    def fake_correctness(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(success=True, error=None)

    monkeypatch.setattr(
        native_services, "run_m15_live_finbench_correctness", fake_correctness
    )
    output_root = tmp_path / "runs"
    args = [
        "--runtime-root", str(runtime),
        "--staging-manifest", str(staging),
        "--output-root", str(output_root),
        "--run-id", "source-identity-wiring",
        "--filesystem-type", "xfs",
        "--allocation-id", "offline-test",
        "--repo-root", str(REPO_ROOT),
        "--workload-mode", "finbench_correctness",
        "--finbench-workload", str(tmp_path / "frozen-original-workload"),
        "--finbench-partition", str(tmp_path / "verified-partition"),
        "--finbench-query-id", "original-query-02",
        "--finbench-query-id", "original-query-01",
    ]
    if explicit_mode is not None:
        args.extend(["--finbench-source-identity-mode", explicit_mode])

    assert native_services.main(args) == 0
    assert len(observed) == 1
    expected_mode = explicit_mode or "partition"
    assert observed[0]["source_identity_mode"] == expected_mode
    assert observed[0]["query_ids"] == ["original-query-02", "original-query-01"]
    assert observed[0]["workload_root"] == str(tmp_path / "frozen-original-workload")
    manifest = json.loads(
        (output_root / "source-identity-wiring" / "run_manifest.json").read_text()
    )
    assert manifest["finbench_correctness"] == {
        "workload": str(tmp_path / "frozen-original-workload"),
        "partition": str(tmp_path / "verified-partition"),
        "source_identity_mode": expected_mode,
        "query_ids": ["original-query-02", "original-query-01"],
    }


@pytest.mark.parametrize(
    ("workload_mode", "identity_mode", "message"),
    [
        ("finbench_correctness", None, "unsupported FinBench source identity mode"),
        ("finbench_correctness", "unknown", "unsupported FinBench source identity mode"),
        ("vertical_slice", "source_archive", "accepted only in finbench_correctness"),
        ("finbench_family_campaign", "source_archive", "accepted only in finbench_correctness"),
        ("finbench_confirmatory_block", "source_archive", "accepted only in finbench_correctness"),
    ],
)
def test_invalid_identity_mode_rejects_before_any_service_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workload_mode: str,
    identity_mode: str | None,
    message: str,
) -> None:
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: pytest.fail("invalid mode must precede Java inspection"),
    )
    with pytest.raises(ValueError, match=message):
        native_services.run_m15_native_services(
            runtime_root=tmp_path / "absent-runtime",
            staging_manifest=tmp_path / "absent-staging.json",
            output_root=tmp_path / "runs",
            run_id="invalid-source-mode",
            filesystem_type="xfs",
            allocation_id="offline-test",
            java_command="/fake/java",
            repo_root=REPO_ROOT,
            workload_mode=workload_mode,
            finbench_source_identity_mode=identity_mode,
        )
    assert not (tmp_path / "runs").exists()
