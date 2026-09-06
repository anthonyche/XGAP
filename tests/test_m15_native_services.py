from __future__ import annotations

import io
import hashlib
import json
import signal
import subprocess
import urllib.error
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import xgap.experiments.m15_native_services as native_services

from xgap.experiments.m15_campaign import compile_m15_campaign_file
from xgap.experiments.m15_direct_semantic_estimates import (
    load_m15_direct_estimate_source,
)
from xgap.experiments.m15_query_bound_campaign import (
    compile_m15_query_bound_campaign_file,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    generate_m15_predicate_overlay_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    load_m15_semantic_relaxation_catalog,
)
from xgap.experiments.m15_semantic_overlay import (
    generate_m15_semantic_overlay_bundle,
)
from xgap.experiments.m15_workload import M15WorkloadSpec, generate_m15_workload_bundle
from xgap.experiments.m15_native_runtime import STAGING_SCHEMA_VERSION
from xgap.experiments.m15_native_services import (
    JavaEvidence,
    LoopbackPortReservations,
    RunningService,
    ServiceSpec,
    ShutdownObservation,
    build_m15_family_runtime_compatibility,
    build_native_service_plan,
    inspect_java_runtime,
    main,
    run_m15_native_services,
    stop_service,
    validate_local_filesystem_type,
    wait_for_service_health,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _staged_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    neo4j = runtime / "neo4j-community-5.26.30"
    fuseki = runtime / "apache-jena-fuseki-5.6.0"
    (neo4j / "bin").mkdir(parents=True)
    (neo4j / "conf").mkdir()
    (neo4j / "lib").mkdir()
    (neo4j / "licenses").mkdir()
    (neo4j / "conf" / "server-logs.xml").write_text("<Configuration/>")
    (neo4j / "conf" / "user-logs.xml").write_text("<Configuration/>")
    (neo4j / "conf" / "neo4j.conf").write_text("# source\n")
    fuseki.mkdir(parents=True)
    neo4j_executable = neo4j / "bin" / "neo4j"
    neo4j_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    neo4j_executable.chmod(0o755)
    fuseki_executable = fuseki / "fuseki-server"
    fuseki_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    fuseki_executable.chmod(0o755)
    manifest = tmp_path / "staging.json"
    lock_path = REPO_ROOT / "services" / "m15-native-runtime.lock.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": STAGING_SCHEMA_VERSION,
                "status": "success",
                "runtime_root": str(runtime.resolve()),
                "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                "staged_artifacts": [
                    {"product": "neo4j", "runtime_path": str(neo4j)},
                    {"product": "fuseki", "runtime_path": str(fuseki)},
                ],
            }
        ),
        encoding="utf-8",
    )
    return runtime, manifest


def _service_spec(tmp_path: Path, service_id: str = "neo4j") -> ServiceSpec:
    return ServiceSpec(
        service_id=service_id,
        product=service_id,
        version="test",
        command=("true",),
        working_directory=tmp_path,
        environment={},
        health_url="http://127.0.0.1:12345/health",
        log_path=tmp_path / f"{service_id}.log",
    )


def test_runtime_filesystem_policy_is_explicit_and_fail_closed() -> None:
    assert validate_local_filesystem_type(" XFS ") == "xfs"
    assert validate_local_filesystem_type("tmpfs") == "tmpfs"
    with pytest.raises(ValueError, match="network filesystem"):
        validate_local_filesystem_type("nfs4")
    with pytest.raises(ValueError, match="not allowlisted"):
        validate_local_filesystem_type("mysteryfs")


def test_java_probe_requires_exact_frozen_major() -> None:
    def java17(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 0, stdout="", stderr='openjdk version "17.0.6"\n'
        )

    evidence = inspect_java_runtime("/opt/java/bin/java", runner=java17)
    assert evidence.major == 17
    assert evidence.command == "/opt/java/bin/java"

    def java21(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 0, stdout="", stderr='openjdk version "21.0.2"\n'
        )

    with pytest.raises(ValueError, match="exact Java 17"):
        inspect_java_runtime("java", runner=java21)


def test_service_plan_uses_loopback_dynamic_ports_and_local_state(
    tmp_path: Path,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    evidence = tmp_path / "evidence"
    plan = build_native_service_plan(
        runtime_root=runtime,
        staging_manifest=staging,
        evidence_root=evidence,
        filesystem_type="xfs",
        allocation_id="12345",
        java=JavaEvidence("/opt/java17/bin/java", 17, "openjdk 17.0.6"),
        neo4j_http_port=17474,
        neo4j_bolt_port=17687,
        fuseki_port=13030,
        lock_path=REPO_ROOT / "services" / "m15-native-runtime.lock.json",
    )

    assert plan.neo4j_http_url == "http://127.0.0.1:17474"
    assert plan.fuseki_url == "http://127.0.0.1:13030"
    assert plan.filesystem_type == "xfs"
    neo4j, fuseki = plan.services
    assert neo4j.command[-1] == "console"
    assert neo4j.environment["JAVACMD"] == "/opt/java17/bin/java"
    assert fuseki.command[1:] == (
        "--localhost",
        "--ping",
        "--port",
        "13030",
        "--update",
        "--mem",
        "/xgap",
    )
    assert "--localhost" in fuseki.command
    assert fuseki.environment["JVM_ARGS"] == "-Xms128m -Xmx512m"
    config = (evidence / "neo4j.conf").read_text(encoding="utf-8")
    assert "dbms.security.auth_enabled=false" in config
    assert "server.default_listen_address=127.0.0.1" in config
    assert "server.http.listen_address=127.0.0.1:17474" in config
    assert str(runtime / "xgap-service-state" / "neo4j" / "data") in config
    serialized = json.loads(plan.plan_path.read_text(encoding="utf-8"))
    assert serialized["runtime_lock_sha256"]
    assert serialized["staging_manifest_sha256"] == hashlib.sha256(
        staging.read_bytes()
    ).hexdigest()
    assert serialized["public_ports"] is False
    assert serialized["automatic_retries"] == 0
    assert serialized["credentials_persisted"] is False


def test_family_runtime_compatibility_is_stable_and_allocation_scoped(
    tmp_path: Path,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    plan = build_native_service_plan(
        runtime_root=runtime,
        staging_manifest=staging,
        evidence_root=tmp_path / "evidence",
        filesystem_type="xfs",
        allocation_id="12345",
        java=JavaEvidence("/opt/java17/bin/java", 17, "openjdk 17.0.6"),
        neo4j_http_port=17474,
        neo4j_bolt_port=17687,
        fuseki_port=13030,
        lock_path=REPO_ROOT / "services" / "m15-native-runtime.lock.json",
    )

    first = build_m15_family_runtime_compatibility(plan)
    assert first == build_m15_family_runtime_compatibility(plan)
    assert first["allocation_id"] == "12345"
    assert first["java_major"] == 17
    assert [item["service_id"] for item in first["services"]] == [
        "fuseki",
        "neo4j",
    ]
    assert first["reuse_scope"] == "same_native_service_allocation_only"

    second = build_m15_family_runtime_compatibility(
        replace(plan, allocation_id="12346")
    )
    assert second["runtime_compatibility_sha256"] != first[
        "runtime_compatibility_sha256"
    ]


def test_service_plan_rejects_untrusted_staging_or_allocation(
    tmp_path: Path,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    payload = json.loads(staging.read_text(encoding="utf-8"))
    payload["schema_version"] = "unknown"
    staging.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="staging manifest"):
        build_native_service_plan(
            runtime_root=runtime,
            staging_manifest=staging,
            evidence_root=tmp_path / "evidence",
            filesystem_type="xfs",
            allocation_id="12345",
            java=JavaEvidence("java", 17, "openjdk 17"),
            neo4j_http_port=17474,
            neo4j_bolt_port=17687,
            fuseki_port=13030,
        )

    payload["schema_version"] = STAGING_SCHEMA_VERSION
    staging.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="allocation ID"):
        build_native_service_plan(
            runtime_root=runtime,
            staging_manifest=staging,
            evidence_root=tmp_path / "evidence",
            filesystem_type="xfs",
            allocation_id="manual",
            java=JavaEvidence("java", 17, "openjdk 17"),
            neo4j_http_port=17474,
            neo4j_bolt_port=17687,
            fuseki_port=13030,
        )


def test_loopback_port_reservations_are_unique_and_held() -> None:
    with LoopbackPortReservations.acquire(3) as reservation:
        assert len(set(reservation.ports)) == 3
        for port in reservation.ports:
            with pytest.raises(OSError):
                with __import__("socket").socket() as competing:
                    competing.bind(("127.0.0.1", port))
        first = reservation.ports[0]
        reservation.release(0)
        with __import__("socket").socket() as available:
            available.bind(("127.0.0.1", first))


class _StableProcess:
    pid = 8123

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def test_health_wait_is_bounded_and_does_not_restart(tmp_path: Path) -> None:
    attempts = []

    def probe(spec, timeout):
        attempts.append((spec.service_id, timeout))
        if len(attempts) == 1:
            raise urllib.error.URLError("not ready")
        return 200

    clock = iter([0.0, 0.1, 0.25])
    running = RunningService(
        _service_spec(tmp_path), _StableProcess(), io.BytesIO()
    )
    result = wait_for_service_health(
        running,
        timeout_seconds=2,
        interval_seconds=0.01,
        probe=probe,
        monotonic=lambda: next(clock),
        sleeper=lambda _: None,
    )

    assert result.success
    assert result.attempts == 2
    assert result.http_status == 200
    assert len(attempts) == 2


def test_health_wait_stops_immediately_when_process_exits(tmp_path: Path) -> None:
    class ExitedProcess(_StableProcess):
        def poll(self):
            return 17

    clock = iter([0.0, 0.01])
    running = RunningService(
        _service_spec(tmp_path), ExitedProcess(), io.BytesIO()
    )
    result = wait_for_service_health(
        running,
        probe=lambda *_: pytest.fail("probe must not run"),
        monotonic=lambda: next(clock),
    )

    assert not result.success
    assert result.attempts == 0
    assert result.process_exit_code == 17


def test_shutdown_targets_only_the_started_process_group(tmp_path: Path) -> None:
    signals = []
    process = _StableProcess()
    log = io.BytesIO()
    running = RunningService(_service_spec(tmp_path), process, log)

    result = stop_service(
        running,
        kill_group=lambda pid, selected: signals.append((pid, selected)),
    )

    assert result.success
    assert result.signal_sent == "SIGTERM"
    assert signals == [(8123, signal.SIGTERM)]
    assert log.closed


def test_shutdown_escalation_is_bounded_and_recorded(tmp_path: Path) -> None:
    class StubbornProcess(_StableProcess):
        def __init__(self):
            self.waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("service", timeout)
            return -9

    signals = []
    process = StubbornProcess()
    running = RunningService(_service_spec(tmp_path), process, io.BytesIO())

    result = stop_service(
        running,
        timeout_seconds=0.01,
        kill_group=lambda pid, selected: signals.append((pid, selected)),
    )

    assert result.success
    assert result.escalated_to_kill
    assert result.signal_sent == "SIGKILL"
    assert signals == [(8123, signal.SIGTERM), (8123, signal.SIGKILL)]


def test_native_service_cli_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_RUN_M15_NATIVE_SERVICES", raising=False)
    code = main(
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--staging-manifest",
            str(tmp_path / "staging.json"),
            "--output-root",
            str(tmp_path),
            "--filesystem-type",
            "xfs",
            "--allocation-id",
            "12345",
        ]
    )

    assert code == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"


def test_full_lifecycle_orchestration_records_reverse_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    started: list[str] = []
    stopped: list[str] = []
    executed: list[str] = []

    def fake_start(spec):
        started.append(spec.service_id)
        return RunningService(spec, _StableProcess(), io.BytesIO())

    def fake_health(service):
        return native_services.HealthObservation(
            service.spec.service_id, True, 1, 1.0, 200
        )

    def fake_stop(service):
        stopped.append(service.spec.service_id)
        service.log_handle.close()
        return ShutdownObservation(
            service.spec.service_id,
            service.process.pid,
            None,
            0,
            "SIGTERM",
            False,
            True,
        )

    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: JavaEvidence("/opt/java17/bin/java", 17, "17"),
    )
    monkeypatch.setattr(native_services, "start_service", fake_start)
    monkeypatch.setattr(native_services, "wait_for_service_health", fake_health)
    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(
        native_services,
        "_run_fixture_and_query",
        lambda *_args: executed.append(_args[3]),
    )

    record = run_m15_native_services(
        runtime_root=runtime,
        staging_manifest=staging,
        output_root=tmp_path / "runs",
        run_id="native-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
    )

    assert record.success
    assert started == ["neo4j", "fuseki"]
    assert executed == ["vertical_slice"]
    assert stopped == ["fuseki", "neo4j"]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["service_restarts"] == 0
    assert [item["service_id"] for item in manifest["health"]] == [
        "neo4j",
        "fuseki",
    ]
    assert [item["service_id"] for item in manifest["shutdown"]] == [
        "fuseki",
        "neo4j",
    ]
    assert manifest["workload_mode"] == "vertical_slice"


def test_full_lifecycle_selects_adaptive_workload_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    executed: list[str] = []

    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: JavaEvidence("/opt/java17/bin/java", 17, "17"),
    )
    monkeypatch.setattr(
        native_services,
        "start_service",
        lambda spec: RunningService(spec, _StableProcess(), io.BytesIO()),
    )
    monkeypatch.setattr(
        native_services,
        "wait_for_service_health",
        lambda service: native_services.HealthObservation(
            service.spec.service_id,
            True,
            1,
            1.0,
            200,
        ),
    )

    def fake_stop(service):
        service.log_handle.close()
        return ShutdownObservation(
            service.spec.service_id,
            service.process.pid,
            None,
            0,
            "SIGTERM",
            False,
            True,
        )

    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(
        native_services,
        "_run_fixture_and_query",
        lambda *_args: executed.append(_args[3]),
    )

    record = run_m15_native_services(
        runtime_root=runtime,
        staging_manifest=staging,
        output_root=tmp_path / "runs",
        run_id="native-adaptive-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="adaptive",
    )

    assert record.success
    assert executed == ["adaptive"]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == (
        native_services.ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION
    )
    assert manifest["workload_mode"] == "adaptive"


@pytest.mark.parametrize(
    ("workload_mode", "schema_version"),
    (
        (
            "parameterized_stream",
            native_services.PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION,
        ),
        (
            "parameterized_family_transfer",
            native_services.FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION,
        ),
    ),
)
def test_full_lifecycle_selects_parameterized_mode_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workload_mode: str,
    schema_version: str,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    with pytest.raises(ValueError, match="requires a verified parameterized bundle"):
        run_m15_native_services(
            runtime_root=runtime,
            staging_manifest=staging,
            output_root=tmp_path / "missing-runs",
            run_id="missing-parameterized-bundle",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode=workload_mode,
        )

    bundle = generate_m15_parameterized_workload_bundle(
        workload_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
        ),
        query_template_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=tmp_path / "parameterized-bundle",
    )
    executed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: JavaEvidence("/opt/java17/bin/java", 17, "17"),
    )
    monkeypatch.setattr(
        native_services,
        "start_service",
        lambda spec: RunningService(spec, _StableProcess(), io.BytesIO()),
    )
    monkeypatch.setattr(
        native_services,
        "wait_for_service_health",
        lambda service: native_services.HealthObservation(
            service.spec.service_id,
            True,
            1,
            1.0,
            200,
        ),
    )

    def fake_stop(service):
        service.log_handle.close()
        return ShutdownObservation(
            service.spec.service_id,
            service.process.pid,
            None,
            0,
            "SIGTERM",
            False,
            True,
        )

    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(
        native_services,
        "_run_fixture_and_query",
        lambda *_args: executed.append(
            (_args[3], _args[13].spec.workload_id)
        ),
    )

    record = run_m15_native_services(
        runtime_root=runtime,
        staging_manifest=staging,
        output_root=tmp_path / "runs",
        run_id="native-parameterized-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode=workload_mode,
        parameterized_workload_bundle=bundle,
    )

    assert record.success
    assert executed == [
        (workload_mode, "financial-risk-multi-instance-dev-v1")
    ]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == schema_version
    assert manifest["workload_mode"] == workload_mode
    assert manifest["workload_bundle"] is None
    assert manifest["parameterized_workload_bundle"][
        "bundle_content_sha256"
    ] == bundle.manifest["bundle_content_sha256"]


def test_full_lifecycle_requires_and_records_semantic_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
        ),
        query_template_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=tmp_path / "semantic-base-bundle",
    )
    catalog = load_m15_semantic_relaxation_catalog(
        REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
    )
    overlay = generate_m15_semantic_overlay_bundle(
        base_bundle=base,
        base_query_id="financial-risk-alice-aug-high-v2",
        catalog=catalog,
        destination=tmp_path / "semantic-overlay",
    )
    with pytest.raises(ValueError, match="requires an overlay"):
        run_m15_native_services(
            runtime_root=runtime,
            staging_manifest=staging,
            output_root=tmp_path / "missing-semantic-runs",
            run_id="missing-semantic-inputs",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="semantic_risk_relaxation",
        )

    executed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: JavaEvidence(
            "/opt/java17/bin/java", 17, "17"
        ),
    )
    monkeypatch.setattr(
        native_services,
        "start_service",
        lambda spec: RunningService(spec, _StableProcess(), io.BytesIO()),
    )
    monkeypatch.setattr(
        native_services,
        "wait_for_service_health",
        lambda service: native_services.HealthObservation(
            service.spec.service_id,
            True,
            1,
            1.0,
            200,
        ),
    )

    def fake_stop(service):
        service.log_handle.close()
        return ShutdownObservation(
            service.spec.service_id,
            service.process.pid,
            None,
            0,
            "SIGTERM",
            False,
            True,
        )

    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(
        native_services,
        "_run_fixture_and_query",
        lambda *_args: executed.append(
            (
                _args[3],
                _args[14].manifest["overlay_sha256"],
                _args[15].spec.workload_id,
            )
        ),
    )

    record = run_m15_native_services(
        runtime_root=runtime,
        staging_manifest=staging,
        output_root=tmp_path / "semantic-runs",
        run_id="native-semantic-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="semantic_risk_relaxation",
        semantic_overlay=overlay,
        semantic_base_bundle=base,
        semantic_catalog=catalog,
    )

    assert record.success
    assert executed == [
        (
            "semantic_risk_relaxation",
            overlay.manifest["overlay_sha256"],
            base.spec.workload_id,
        )
    ]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == (
        native_services.SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION
    )
    assert manifest["workload_mode"] == "semantic_risk_relaxation"
    assert manifest["workload_bundle"] is None
    assert manifest["parameterized_workload_bundle"] is None
    assert manifest["semantic_base_workload_bundle"] == base.manifest
    assert manifest["semantic_overlay"] == overlay.manifest


def test_full_lifecycle_requires_and_records_predicate_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
        ),
        query_template_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=tmp_path / "predicate-base-bundle",
    )
    catalog = load_m15_semantic_relaxation_catalog(
        REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
    )
    mapping = REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
    overlay = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id="financial-risk-alice-aug-high-v2",
        catalog=catalog,
        mapping=mapping,
        destination=tmp_path / "predicate-overlay",
    )
    with pytest.raises(ValueError, match="requires a predicate overlay"):
        run_m15_native_services(
            runtime_root=runtime,
            staging_manifest=staging,
            output_root=tmp_path / "missing-predicate-runs",
            run_id="missing-predicate-inputs",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="semantic_predicate_relaxation",
        )

    executed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: JavaEvidence(
            "/opt/java17/bin/java", 17, "17"
        ),
    )
    monkeypatch.setattr(
        native_services,
        "start_service",
        lambda spec: RunningService(spec, _StableProcess(), io.BytesIO()),
    )
    monkeypatch.setattr(
        native_services,
        "wait_for_service_health",
        lambda service: native_services.HealthObservation(
            service.spec.service_id,
            True,
            1,
            1.0,
            200,
        ),
    )

    def fake_stop(service):
        service.log_handle.close()
        return ShutdownObservation(
            service.spec.service_id,
            service.process.pid,
            None,
            0,
            "SIGTERM",
            False,
            True,
        )

    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(
        native_services,
        "_run_fixture_and_query",
        lambda *_args: executed.append(
            (
                _args[3],
                _args[17].manifest["overlay_sha256"],
                _args[18].mapping_id,
            )
        ),
    )

    record = run_m15_native_services(
        runtime_root=runtime,
        staging_manifest=staging,
        output_root=tmp_path / "predicate-runs",
        run_id="native-predicate-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="semantic_predicate_relaxation",
        predicate_overlay=overlay,
        semantic_base_bundle=base,
        semantic_catalog=catalog,
        predicate_mapping=mapping,
    )

    assert record.success
    assert executed == [
        (
            "semantic_predicate_relaxation",
            overlay.manifest["overlay_sha256"],
            overlay.mapping.mapping_id,
        )
    ]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == (
        native_services.PREDICATE_RELAXATION_SERVICE_RUN_SCHEMA_VERSION
    )
    assert manifest["workload_mode"] == "semantic_predicate_relaxation"
    assert manifest["workload_bundle"] is None
    assert manifest["parameterized_workload_bundle"] is None
    assert manifest["semantic_base_workload_bundle"] == base.manifest
    assert manifest["semantic_overlay"] is None
    assert manifest["predicate_overlay"] == overlay.manifest
    assert manifest["predicate_mapping"] == overlay.mapping.to_dict()


def test_predicate_native_mode_revalidates_overlay_at_fixture_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
        ),
        query_template_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=tmp_path / "fixture-predicate-base",
    )
    catalog = load_m15_semantic_relaxation_catalog(
        REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
    )
    mapping = REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
    overlay = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id="financial-risk-alice-aug-high-v2",
        catalog=catalog,
        mapping=mapping,
        destination=tmp_path / "fixture-predicate-overlay",
    )
    observed: dict[str, object] = {}

    def fake_fixture(**kwargs):
        loaded = kwargs["bundle_loader"](kwargs["workload_bundle"].root)
        observed["fixture_bundle_hash"] = loaded.manifest[
            "bundle_content_sha256"
        ]
        observed["fixture_run_id"] = kwargs["run_id"]
        return SimpleNamespace(success=True, error=None)

    def fake_live(**kwargs):
        observed["live_overlay_hash"] = kwargs[
            "predicate_overlay"
        ].manifest["overlay_sha256"]
        observed["live_run_id"] = kwargs["run_id"]
        return SimpleNamespace(success=True, error=None)

    monkeypatch.setattr(native_services, "load_m15_parameterized_fixture", fake_fixture)
    monkeypatch.setattr(
        native_services,
        "run_m15_live_semantic_predicate_relaxation",
        fake_live,
    )
    plan = SimpleNamespace(
        neo4j_http_url="http://127.0.0.1:17474",
        fuseki_url="http://127.0.0.1:13030",
        fuseki_dataset="xgap",
    )

    native_services._run_fixture_and_query(
        plan=plan,
        run_root=tmp_path / "native-predicate-run",
        repo_root=REPO_ROOT,
        workload_mode="semantic_predicate_relaxation",
        semantic_base_bundle=base,
        semantic_catalog=catalog,
        predicate_overlay=overlay,
        predicate_mapping=overlay.mapping,
    )

    assert observed == {
        "fixture_bundle_hash": overlay.workload_bundle.manifest[
            "bundle_content_sha256"
        ],
        "fixture_run_id": "predicate-fixture-load",
        "live_overlay_hash": overlay.manifest["overlay_sha256"],
        "live_run_id": "semantic-predicate-relaxation-run",
    }


def test_full_lifecycle_requires_and_records_direct_frontier_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
        ),
        query_template_spec=(
            REPO_ROOT
            / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=tmp_path / "frontier-base-bundle",
    )
    catalog = load_m15_semantic_relaxation_catalog(
        REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
    )
    mapping = REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
    estimates = (
        REPO_ROOT
        / "experiments/configs/m15_f2c9_direct_frontier_estimates_dev.json"
    )
    overlay = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id="financial-risk-alice-aug-high-v2",
        catalog=catalog,
        mapping=mapping,
        destination=tmp_path / "frontier-overlay",
    )
    with pytest.raises(ValueError, match="requires a predicate overlay"):
        run_m15_native_services(
            runtime_root=runtime,
            staging_manifest=staging,
            output_root=tmp_path / "missing-frontier-runs",
            run_id="missing-frontier-inputs",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="semantic_direct_frontier",
        )

    executed: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: JavaEvidence(
            "/opt/java17/bin/java", 17, "17"
        ),
    )
    preflight_root = (
        tmp_path
        / "frontier-runs"
        / "native-frontier-test"
        / "direct-frontier-preflight"
    )

    def fake_frontier_start(spec):
        assert (preflight_root / "candidate_set.json").is_file()
        assert (preflight_root / "estimate_source.json").is_file()
        assert (preflight_root / "estimate_snapshot.json").is_file()
        assert (preflight_root / "semantic_frontier.json").is_file()
        assert (preflight_root / "preflight_manifest.json").is_file()
        return RunningService(spec, _StableProcess(), io.BytesIO())

    monkeypatch.setattr(native_services, "start_service", fake_frontier_start)
    monkeypatch.setattr(
        native_services,
        "wait_for_service_health",
        lambda service: native_services.HealthObservation(
            service.spec.service_id,
            True,
            1,
            1.0,
            200,
        ),
    )

    def fake_stop(service):
        service.log_handle.close()
        return ShutdownObservation(
            service.spec.service_id,
            service.process.pid,
            None,
            0,
            "SIGTERM",
            False,
            True,
        )

    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(
        native_services,
        "_run_fixture_and_query",
        lambda *_args: executed.append(
            (
                _args[3],
                _args[17].manifest["overlay_sha256"],
                str(_args[19]),
                _args[20].frontier.to_dict()["frontier_sha256"],
            )
        ),
    )
    record = run_m15_native_services(
        runtime_root=runtime,
        staging_manifest=staging,
        output_root=tmp_path / "frontier-runs",
        run_id="native-frontier-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="semantic_direct_frontier",
        predicate_overlay=overlay,
        semantic_base_bundle=base,
        semantic_catalog=catalog,
        predicate_mapping=mapping,
        direct_frontier_estimates=estimates,
    )

    assert record.success
    assert executed == [
        (
            "semantic_direct_frontier",
            overlay.manifest["overlay_sha256"],
            str(estimates),
            "e915ffdc4a19a21377cf18134024cbae47dbdaa80f8609296b52d28e41b8517a",
        )
    ]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == (
        native_services.DIRECT_SEMANTIC_FRONTIER_SERVICE_RUN_SCHEMA_VERSION
    )
    assert manifest["workload_mode"] == "semantic_direct_frontier"
    assert manifest["predicate_overlay"] == overlay.manifest
    assert manifest["direct_frontier_estimates"] == (
        load_m15_direct_estimate_source(estimates).to_dict()
    )
    preflight = json.loads(
        (preflight_root / "preflight_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert preflight["sealed_before_service_start"] is True
    assert preflight["backend_calls_before_seal"] == 0
    assert manifest["direct_frontier_preflight"] == preflight


def test_full_lifecycle_requires_and_records_scaled_workload_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    bundle = generate_m15_workload_bundle(
        M15WorkloadSpec(
            workload_id="native-scaled-test",
            seed="native-scaled-test-v1",
            company_count=12,
            transfer_count=40,
            high_risk_company_count=3,
            hot_company_count=2,
            hot_transfer_count=32,
            high_risk_placement="cold_first",
            max_bindings=12,
        ),
        tmp_path / "bundle",
    )
    with pytest.raises(ValueError, match="requires a verified bundle"):
        run_m15_native_services(
            runtime_root=runtime,
            staging_manifest=staging,
            output_root=tmp_path / "missing-runs",
            run_id="missing-scaled-bundle",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="scaled_adaptive",
        )
    with pytest.raises(ValueError, match="requires a verified bundle"):
        run_m15_native_services(
            runtime_root=runtime,
            staging_manifest=staging,
            output_root=tmp_path / "missing-matrix-runs",
            run_id="missing-matrix-bundle",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="scaled_method_matrix",
        )

    executed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: JavaEvidence("/opt/java17/bin/java", 17, "17"),
    )
    monkeypatch.setattr(
        native_services,
        "start_service",
        lambda spec: RunningService(spec, _StableProcess(), io.BytesIO()),
    )
    monkeypatch.setattr(
        native_services,
        "wait_for_service_health",
        lambda service: native_services.HealthObservation(
            service.spec.service_id,
            True,
            1,
            1.0,
            200,
        ),
    )

    def fake_stop(service):
        service.log_handle.close()
        return ShutdownObservation(
            service.spec.service_id,
            service.process.pid,
            None,
            0,
            "SIGTERM",
            False,
            True,
        )

    monkeypatch.setattr(native_services, "stop_service", fake_stop)
    monkeypatch.setattr(
        native_services,
        "_run_fixture_and_query",
        lambda *_args: executed.append((_args[3], _args[4].spec.workload_id)),
    )

    record = run_m15_native_services(
        runtime_root=runtime,
        staging_manifest=staging,
        output_root=tmp_path / "runs",
        run_id="native-scaled-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="scaled_adaptive",
        workload_bundle=bundle,
    )

    assert record.success
    assert executed == [("scaled_adaptive", "native-scaled-test")]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == (
        native_services.SCALED_ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION
    )
    assert manifest["workload_mode"] == "scaled_adaptive"
    assert manifest["workload_bundle"]["spec_sha256"] == bundle.manifest[
        "spec_sha256"
    ]

    matrix_runtime, matrix_staging = _staged_runtime(tmp_path / "matrix-lifecycle")
    matrix_record = run_m15_native_services(
        runtime_root=matrix_runtime,
        staging_manifest=matrix_staging,
        output_root=tmp_path / "runs",
        run_id="native-method-matrix-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="scaled_method_matrix",
        workload_bundle=bundle,
    )

    assert matrix_record.success
    assert executed[-1] == ("scaled_method_matrix", "native-scaled-test")
    matrix_manifest = json.loads(
        matrix_record.manifest_path.read_text(encoding="utf-8")
    )
    assert matrix_manifest["schema_version"] == (
        native_services.METHOD_MATRIX_SERVICE_RUN_SCHEMA_VERSION
    )
    assert matrix_manifest["workload_mode"] == "scaled_method_matrix"

    with pytest.raises(ValueError, match="requires config, session, spec hash"):
        run_m15_native_services(
            runtime_root=matrix_runtime,
            staging_manifest=matrix_staging,
            output_root=tmp_path / "missing-campaign-inputs",
            run_id="missing-campaign-inputs",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="scaled_campaign_session",
            workload_bundle=bundle,
        )

    campaign_runtime, campaign_staging = _staged_runtime(
        tmp_path / "campaign-lifecycle"
    )
    selective_bundle = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(
            REPO_ROOT / "experiments/configs/m15_f0_selective.json"
        ),
        tmp_path / "campaign-bundle",
    )
    campaign_config = REPO_ROOT / "experiments/configs/m15_f2_campaign_dev.json"
    campaign_plan = compile_m15_campaign_file(
        campaign_config,
        repo_root=REPO_ROOT,
    ).to_dict()
    campaign_session = next(
        item
        for item in campaign_plan["sessions"]
        if item["workload_label"] == "selective"
    )
    campaign_record = run_m15_native_services(
        runtime_root=campaign_runtime,
        staging_manifest=campaign_staging,
        output_root=tmp_path / "runs",
        run_id="native-campaign-session-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="scaled_campaign_session",
        workload_bundle=selective_bundle,
        campaign_config=campaign_config,
        campaign_session_id=campaign_session["session_id"],
        expected_campaign_spec_sha256=campaign_plan["campaign_spec_sha256"],
        expected_schedule_sha256=campaign_plan["schedule_sha256"],
    )

    assert campaign_record.success
    assert executed[-1] == ("scaled_campaign_session", "selective-dev-v1")
    campaign_manifest = json.loads(
        campaign_record.manifest_path.read_text(encoding="utf-8")
    )
    assert campaign_manifest["schema_version"] == (
        native_services.CAMPAIGN_SESSION_SERVICE_RUN_SCHEMA_VERSION
    )
    assert campaign_manifest["campaign_session"] == {
        "campaign_config": str(campaign_config),
        "session_id": campaign_session["session_id"],
        "expected_campaign_spec_sha256": campaign_plan[
            "campaign_spec_sha256"
        ],
        "expected_schedule_sha256": campaign_plan["schedule_sha256"],
    }

    with pytest.raises(ValueError, match="requires registry, session"):
        run_m15_native_services(
            runtime_root=matrix_runtime,
            staging_manifest=matrix_staging,
            output_root=tmp_path / "missing-query-bound-inputs",
            run_id="missing-query-bound-inputs",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="scaled_query_bound_session",
            workload_bundle=selective_bundle,
        )

    query_runtime, query_staging = _staged_runtime(
        tmp_path / "query-bound-lifecycle"
    )
    query_registry = (
        REPO_ROOT / "experiments/configs/m15_f2_query_bound_campaign_dev.json"
    )
    query_plan = compile_m15_query_bound_campaign_file(
        query_registry,
        repo_root=REPO_ROOT,
    ).to_dict()
    query_session = next(
        item
        for item in query_plan["sessions"]
        if item["workload_label"] == "selective"
    )
    query_record = run_m15_native_services(
        runtime_root=query_runtime,
        staging_manifest=query_staging,
        output_root=tmp_path / "runs",
        run_id="native-query-bound-session-test",
        filesystem_type="xfs",
        allocation_id="12345",
        java_command="/opt/java17/bin/java",
        repo_root=REPO_ROOT,
        workload_mode="scaled_query_bound_session",
        workload_bundle=selective_bundle,
        query_bound_registry=query_registry,
        query_bound_session_id=query_session["session_id"],
        expected_registry_spec_sha256=query_plan["registry_spec_sha256"],
        expected_query_bound_schedule_sha256=query_plan[
            "query_bound_schedule_sha256"
        ],
    )

    assert query_record.success
    assert executed[-1] == ("scaled_query_bound_session", "selective-dev-v1")
    query_manifest = json.loads(
        query_record.manifest_path.read_text(encoding="utf-8")
    )
    assert query_manifest["schema_version"] == (
        native_services.QUERY_BOUND_SESSION_SERVICE_RUN_SCHEMA_VERSION
    )
    assert query_manifest["query_bound_session"] == {
        "query_bound_registry": str(query_registry),
        "session_id": query_session["session_id"],
        "expected_registry_spec_sha256": query_plan["registry_spec_sha256"],
        "expected_query_bound_schedule_sha256": query_plan[
            "query_bound_schedule_sha256"
        ],
    }


def test_query_bound_contract_drift_rejects_before_service_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, staging = _staged_runtime(tmp_path)
    bundle = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(
            REPO_ROOT / "experiments/configs/m15_f0_selective.json"
        ),
        tmp_path / "bundle",
    )
    registry = (
        REPO_ROOT / "experiments/configs/m15_f2_query_bound_campaign_dev.json"
    )
    plan = compile_m15_query_bound_campaign_file(
        registry,
        repo_root=REPO_ROOT,
    ).to_dict()
    session = next(
        item
        for item in plan["sessions"]
        if item["workload_label"] == "selective"
    )
    monkeypatch.setattr(
        native_services,
        "inspect_java_runtime",
        lambda *_args, **_kwargs: pytest.fail(
            "contract drift must fail before Java or service observation"
        ),
    )

    with pytest.raises(ValueError, match="registry spec hash disagrees"):
        run_m15_native_services(
            runtime_root=runtime,
            staging_manifest=staging,
            output_root=tmp_path / "runs",
            run_id="query-bound-drift",
            filesystem_type="xfs",
            allocation_id="12345",
            java_command="/opt/java17/bin/java",
            repo_root=REPO_ROOT,
            workload_mode="scaled_query_bound_session",
            workload_bundle=bundle,
            query_bound_registry=registry,
            query_bound_session_id=session["session_id"],
            expected_registry_spec_sha256="0" * 64,
            expected_query_bound_schedule_sha256=plan[
                "query_bound_schedule_sha256"
            ],
        )

    assert not (tmp_path / "runs" / "query-bound-drift").exists()


def test_slurm_wrapper_records_and_cleans_allocation_local_runtime() -> None:
    script = (
        REPO_ROOT / "scripts" / "slurm" / "run_m15_native_services.sbatch"
    ).read_text(encoding="utf-8")
    assert "module load \"$JAVA_MODULE\"" in script
    assert 'LOCAL_BASE="${SLURM_TMPDIR:-/tmp}"' in script
    assert "stat -f -c %T" in script
    assert "--filesystem-type \"$FILESYSTEM_TYPE\"" in script
    assert "--allocation-id \"$SLURM_JOB_ID\"" in script
    assert "XGAP_STAGE_M15_NATIVE_RUNTIME=1" in script
    assert "XGAP_RUN_M15_NATIVE_SERVICES=1" in script
    assert "rm -rf -- \"$RUNTIME_ROOT\"" in script
    assert "runtime_removed" in script
    assert '--workload-mode "$WORKLOAD_MODE"' in script
    assert 'WORKLOAD_ARGS=(--workload-bundle "$WORKLOAD_BUNDLE")' in script
    assert "m15_f0_selective.json" in script
    assert "m15_f0_broad_hot.json" in script
    assert "scaled_method_matrix" in script
    assert "scaled_campaign_session" in script
    assert "scaled_query_bound_session" in script
    assert "parameterized_stream" in script
    assert "parameterized_family_transfer" in script
    assert "semantic_risk_relaxation" in script
    assert "semantic_predicate_relaxation" in script
    assert "semantic_direct_frontier" in script
    assert "m15_parameterized_workload" in script
    assert "m15_semantic_overlay" in script
    assert "m15_predicate_overlay" in script
    assert "--parameterized-workload-bundle" in script
    assert "--campaign-session-id" in script
    campaign_script = (
        REPO_ROOT / "scripts/slurm/run_m15_native_campaign_session.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=scaled_campaign_session" in campaign_script
    assert "XGAP_M15_CAMPAIGN_SESSION_ID" in campaign_script
    assert "XGAP_M15_CAMPAIGN_SPEC_SHA256" in campaign_script
    assert "XGAP_M15_CAMPAIGN_SCHEDULE_SHA256" in campaign_script
    assert "SLURM_SUBMIT_DIR" in campaign_script
    assert "BASH_SOURCE" not in campaign_script
    query_bound_script = (
        REPO_ROOT
        / "scripts/slurm/run_m15_native_query_bound_session.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=scaled_query_bound_session" in (
        query_bound_script
    )
    assert "XGAP_M15_QUERY_BOUND_SESSION_ID" in query_bound_script
    assert "XGAP_M15_QUERY_BOUND_REGISTRY_SPEC_SHA256" in query_bound_script
    assert "XGAP_M15_QUERY_BOUND_SCHEDULE_SHA256" in query_bound_script
    assert "SLURM_SUBMIT_DIR" in query_bound_script
    assert "BASH_SOURCE" not in query_bound_script
    parameterized_script = (
        REPO_ROOT
        / "scripts/slurm/run_m15_native_parameterized_stream.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=parameterized_stream" in parameterized_script
    assert "SLURM_SUBMIT_DIR" in parameterized_script
    assert "BASH_SOURCE" not in parameterized_script
    family_transfer_script = (
        REPO_ROOT
        / "scripts/slurm/run_m15_native_family_transfer.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=parameterized_family_transfer" in (
        family_transfer_script
    )
    assert "SLURM_SUBMIT_DIR" in family_transfer_script
    assert "BASH_SOURCE" not in family_transfer_script
    semantic_relaxation_script = (
        REPO_ROOT
        / "scripts/slurm/run_m15_native_semantic_risk_relaxation.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=semantic_risk_relaxation" in (
        semantic_relaxation_script
    )
    assert "SLURM_SUBMIT_DIR" in semantic_relaxation_script
    assert "BASH_SOURCE" not in semantic_relaxation_script
    predicate_relaxation_script = (
        REPO_ROOT
        / "scripts/slurm/run_m15_native_semantic_predicate_relaxation.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=semantic_predicate_relaxation" in (
        predicate_relaxation_script
    )
    assert "SLURM_SUBMIT_DIR" in predicate_relaxation_script
    assert "BASH_SOURCE" not in predicate_relaxation_script
    direct_frontier_script = (
        REPO_ROOT
        / "scripts/slurm/run_m15_native_semantic_direct_frontier.sbatch"
    ).read_text(encoding="utf-8")
    assert "XGAP_M15_WORKLOAD_MODE=semantic_direct_frontier" in (
        direct_frontier_script
    )
    assert "SLURM_SUBMIT_DIR" in direct_frontier_script
    assert "BASH_SOURCE" not in direct_frontier_script
    assert "--localhost" not in script  # Frozen by the typed service plan.
