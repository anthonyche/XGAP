from __future__ import annotations

import io
import hashlib
import json
import signal
import subprocess
import urllib.error
from pathlib import Path

import pytest
import xgap.experiments.m15_native_services as native_services

from xgap.experiments.m15_workload import M15WorkloadSpec, generate_m15_workload_bundle
from xgap.experiments.m15_native_runtime import STAGING_SCHEMA_VERSION
from xgap.experiments.m15_native_services import (
    JavaEvidence,
    LoopbackPortReservations,
    RunningService,
    ServiceSpec,
    ShutdownObservation,
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
    assert "--localhost" not in script  # Frozen by the typed service plan.
