from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.experiments.m15_fixture_loader import RUN_SCHEMA_VERSION as FIXTURE_SCHEMA
from xgap.experiments.m15_live_federated import RUN_SCHEMA_VERSION as LIVE_SCHEMA
from xgap.experiments.m15_live_adaptive import run_m15_live_adaptive
from xgap.experiments.m15_native_artifacts import load_native_runtime_lock
from xgap.experiments.m15_native_evidence import audit_m15_native_run, main
from xgap.experiments.m15_native_runtime import STAGING_SCHEMA_VERSION
from xgap.experiments.m15_native_services import (
    ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION,
    SERVICE_PLAN_SCHEMA_VERSION,
    SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _complete_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    service = run / "native-service-run"
    fixture_root = service / "fixture-load"
    live_root = service / "federated-run"
    logs = service / "service_logs"
    logs.mkdir(parents=True)
    runtime_root = "/tmp/xgap-m15-8123.ABCDEF"
    lock_path = REPO_ROOT / "services" / "m15-native-runtime.lock.json"
    lock = load_native_runtime_lock(lock_path)
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()

    _write_json(
        run / "run_status.json",
        {
            "status": "success",
            "exit_code": 0,
            "slurm_job_id": "8123",
            "git_commit": COMMIT,
            "runtime_removed": True,
            "cleanup_error": None,
        },
    )
    (run / "environment.txt").write_text(
        "\n".join(
            [
                "run_version=m15-b2d-native-services-v1",
                "slurm_job_id=8123",
                f"git_commit={COMMIT}",
                "java_module=Java/17.0.6",
                f"runtime_root={runtime_root}",
                "runtime_filesystem_type=xfs",
                "loopback_only=true",
                "automatic_retries=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "runtime_mount.txt").write_text(
        "TARGET SOURCE FSTYPE OPTIONS\n/tmp /dev/nvme0 xfs rw\n", encoding="utf-8"
    )
    (run / "java_version.txt").write_text(
        'openjdk version "17.0.6"\n', encoding="utf-8"
    )
    (run / "runtime_lock.json").write_bytes(lock_path.read_bytes())

    staged = []
    for artifact in lock.artifacts:
        staged.append(
            {
                "product": artifact.product,
                "runtime_path": f"{runtime_root}/{artifact.extract_root}",
                "inspection": {
                    "archive_size_bytes": artifact.size_bytes,
                    "digest_algorithm": artifact.digest_algorithm,
                    "digest_value": artifact.digest_value,
                },
            }
        )
    staging = {
        "schema_version": STAGING_SCHEMA_VERSION,
        "status": "success",
        "runtime_root": runtime_root,
        "lock_sha256": lock_digest,
        "staged_artifacts": staged,
        "automatic_retries": 0,
    }
    _write_json(run / "runtime_staging.json", staging)
    staging_digest = hashlib.sha256((run / "runtime_staging.json").read_bytes()).hexdigest()

    neo4j_url = "http://127.0.0.1:17474"
    fuseki_url = "http://127.0.0.1:13030"
    plan = {
        "schema_version": SERVICE_PLAN_SCHEMA_VERSION,
        "allocation_id": "8123",
        "runtime_root": runtime_root,
        "filesystem_type": "xfs",
        "java": {"command": "/opt/java17/bin/java", "major": 17},
        "runtime_lock_sha256": lock_digest,
        "staging_manifest_sha256": staging_digest,
        "neo4j_http_url": neo4j_url,
        "fuseki_url": fuseki_url,
        "fuseki_dataset": "xgap",
        "services": [
            {
                "service_id": "neo4j",
                "version": "5.26.30",
                "command": [f"{runtime_root}/neo4j/bin/neo4j", "console"],
                "health_url": f"{neo4j_url}/db/neo4j/tx/commit",
            },
            {
                "service_id": "fuseki",
                "version": "5.6.0",
                "command": [
                    f"{runtime_root}/fuseki-server",
                    "--localhost",
                    "--ping",
                    "--port",
                    "13030",
                    "--update",
                    "--mem",
                    "/xgap",
                ],
                "health_url": f"{fuseki_url}/$/ping",
            },
        ],
        "public_ports": False,
        "automatic_retries": 0,
        "credentials_persisted": False,
    }
    _write_json(service / "service_plan.json", plan)
    (service / "neo4j.conf").write_text(
        "\n".join(
            [
                "dbms.security.auth_enabled=false",
                "server.http.listen_address=127.0.0.1:17474",
                f"server.directories.data={runtime_root}/xgap-service-state/neo4j/data",
                f"server.directories.lib={runtime_root}/neo4j-community-5.26.30/lib",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    health = [
        {"service_id": "neo4j", "success": True, "attempts": 3},
        {"service_id": "fuseki", "success": True, "attempts": 2},
    ]
    shutdown = [
        {
            "service_id": "fuseki",
            "success": True,
            "initial_exit_code": None,
            "final_exit_code": 143,
        },
        {
            "service_id": "neo4j",
            "success": True,
            "initial_exit_code": None,
            "final_exit_code": 143,
        },
    ]
    _write_json(service / "service_health.json", health)
    _write_json(service / "service_shutdown.json", shutdown)
    _write_json(
        service / "run_manifest.json",
        {
            "schema_version": SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "error": None,
            "allocation_id": "8123",
            "runtime_root": runtime_root,
            "service_plan": plan,
            "health": health,
            "shutdown": shutdown,
            "automatic_retries": 0,
            "service_restarts": 0,
            "public_ports": False,
            "credentials_persisted": False,
        },
    )
    exact_validation = {"passed": True, "checks": {"exact": True}}
    exact_health = {
        "neo4j": {"ok": True},
        "fuseki": {"ok": True},
    }
    load_reports = {
        "neo4j": {"success": True},
        "fuseki": {"success": True},
    }
    _write_json(
        fixture_root / "run_manifest.json",
        {
            "schema_version": FIXTURE_SCHEMA,
            "status": "success",
            "validation": exact_validation,
            "health_before": exact_health,
            "health_after": exact_health,
            "load_reports": load_reports,
            "automatic_retries": 0,
            "git": {"commit": COMMIT, "clean": True},
        },
    )
    _write_json(
        live_root / "run_manifest.json",
        {
            "schema_version": LIVE_SCHEMA,
            "status": "success",
            "validation": exact_validation,
            "backend_health": exact_health,
            "no_llm": True,
            "no_ontology": True,
            "automatic_retries": 0,
            "git": {"commit": COMMIT, "clean": True},
        },
    )
    expected = json.loads(
        (REPO_ROOT / "examples" / "m15_split_financial_risk" / "expected_result.json").read_text(
            encoding="utf-8"
        )
    )
    _write_json(
        live_root / "result.json",
        {
            "success": True,
            "final_rows": expected,
            "total_remote_calls": 2,
            "total_bytes_moved": 206,
        },
    )
    (logs / "neo4j.log").write_text("Neo4j started\n", encoding="utf-8")
    (logs / "fuseki.log").write_text("Fuseki started\n", encoding="utf-8")
    return run


@dataclass
class _AdaptiveFakeClient:
    backend_id: str
    rows: list[dict[str, object]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        rows = self.rows
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            rows = [
                row
                for row in rows
                if str(row.get("company_id", "")).removeprefix("neo:")
                in company_ids
            ]
        return ExecutionReport(
            self.backend_id,
            artifact.artifact_id,
            artifact.language,
            True,
            rows=[dict(row) for row in rows],
            elapsed_ms=2.0,
        )


@dataclass
class _AdaptiveNeo4jClient(_AdaptiveFakeClient):
    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        return self.execute(artifact)


def _complete_adaptive_run(tmp_path: Path) -> Path:
    run = _complete_run(tmp_path)
    service = run / "native-service-run"
    source_rows = json.loads(
        (
            REPO_ROOT
            / "examples"
            / "m15_split_financial_risk"
            / "expected_source_results.json"
        ).read_text(encoding="utf-8")
    )
    adaptive_record = run_m15_live_adaptive(
        output_root=service,
        run_id="adaptive-run",
        repo_root=REPO_ROOT,
        clients={
            "neo4j": _AdaptiveNeo4jClient("neo4j", source_rows["neo4j"]),
            "fuseki": _AdaptiveFakeClient("fuseki", source_rows["fuseki"]),
        },
    )
    assert adaptive_record.success, adaptive_record.error

    outer_path = run / "run_status.json"
    outer = json.loads(outer_path.read_text(encoding="utf-8"))
    outer["workload_mode"] = "adaptive"
    _write_json(outer_path, outer)

    environment_path = run / "environment.txt"
    environment = environment_path.read_text(encoding="utf-8").replace(
        "run_version=m15-b2d-native-services-v1",
        "run_version=m15-d2-native-adaptive-services-v1",
    )
    environment += "workload_mode=adaptive\n"
    environment_path.write_text(environment, encoding="utf-8")

    service_manifest_path = service / "run_manifest.json"
    service_manifest = json.loads(service_manifest_path.read_text(encoding="utf-8"))
    service_manifest["schema_version"] = ADAPTIVE_SERVICE_RUN_SCHEMA_VERSION
    service_manifest["workload_mode"] = "adaptive"
    _write_json(service_manifest_path, service_manifest)

    adaptive_manifest_path = adaptive_record.manifest_path
    adaptive_manifest = json.loads(adaptive_manifest_path.read_text(encoding="utf-8"))
    adaptive_manifest["git"] = {"commit": COMMIT, "clean": True}
    _write_json(adaptive_manifest_path, adaptive_manifest)
    return run


def test_complete_native_run_passes_cross_artifact_audit(tmp_path: Path) -> None:
    run = _complete_run(tmp_path)

    audit = audit_m15_native_run(
        run_root=run,
        expected_commit=COMMIT,
        repo_root=REPO_ROOT,
    )

    assert audit.success
    assert audit.failed_check_ids == ()
    assert len(audit.checks) >= 70


def test_complete_native_adaptive_run_passes_cross_artifact_audit(
    tmp_path: Path,
) -> None:
    run = _complete_adaptive_run(tmp_path)

    audit = audit_m15_native_run(
        run_root=run,
        expected_commit=COMMIT,
        repo_root=REPO_ROOT,
        workload_mode="adaptive",
    )

    assert audit.success, audit.failed_check_ids
    assert audit.failed_check_ids == ()
    assert len(audit.checks) >= 90


def test_adaptive_audit_detects_duplicate_query_invocation(tmp_path: Path) -> None:
    run = _complete_adaptive_run(tmp_path)
    invocation_path = (
        run
        / "native-service-run"
        / "adaptive-run"
        / "backend_invocations.json"
    )
    invocations = json.loads(invocation_path.read_text(encoding="utf-8"))
    invocations["events"].append(dict(invocations["events"][-1]))
    invocations["total_tool_invocations"] = 6
    _write_json(invocation_path, invocations)

    audit = audit_m15_native_run(
        run_root=run,
        expected_commit=COMMIT,
        repo_root=REPO_ROOT,
        workload_mode="adaptive",
    )

    assert not audit.success
    assert "invocations.total" in audit.failed_check_ids
    assert "invocations.sequence" in audit.failed_check_ids


def test_audit_detects_tampered_answer(tmp_path: Path) -> None:
    run = _complete_run(tmp_path)
    result_path = run / "native-service-run" / "federated-run" / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["final_rows"] = []
    _write_json(result_path, result)

    audit = audit_m15_native_run(
        run_root=run,
        expected_commit=COMMIT,
        repo_root=REPO_ROOT,
    )

    assert not audit.success
    assert "result.exact_rows" in audit.failed_check_ids


def test_audit_detects_staging_digest_mutation(tmp_path: Path) -> None:
    run = _complete_run(tmp_path)
    staging_path = run / "runtime_staging.json"
    staging = json.loads(staging_path.read_text(encoding="utf-8"))
    staging["staged_artifacts"][1]["inspection"]["digest_value"] = "0" * 128
    _write_json(staging_path, staging)

    audit = audit_m15_native_run(
        run_root=run,
        expected_commit=COMMIT,
        repo_root=REPO_ROOT,
    )

    assert not audit.success
    assert "staging.fuseki.digest" in audit.failed_check_ids
    assert "plan.staging_manifest_sha256" in audit.failed_check_ids


def test_audit_rejects_symlinked_service_log(tmp_path: Path) -> None:
    run = _complete_run(tmp_path)
    log = run / "native-service-run" / "service_logs" / "fuseki.log"
    target = tmp_path / "outside.log"
    target.write_text("forged\n", encoding="utf-8")
    log.unlink()
    log.symlink_to(target)

    audit = audit_m15_native_run(
        run_root=run,
        expected_commit=COMMIT,
        repo_root=REPO_ROOT,
    )

    assert not audit.success
    assert "artifact.fuseki_log" in audit.failed_check_ids


def test_cli_writes_audit_only_outside_completed_tree(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = _complete_run(tmp_path)
    output = tmp_path / "audit.json"
    code = main(
        [
            "--run-root",
            str(run),
            "--expected-commit",
            COMMIT,
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["success"] is True
    assert json.loads(capsys.readouterr().out)["run_tree_mutated"] is False

    code = main(
        [
            "--run-root",
            str(run),
            "--expected-commit",
            COMMIT,
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(run / "forbidden.json"),
        ]
    )
    assert code == 2
    assert not (run / "forbidden.json").exists()
