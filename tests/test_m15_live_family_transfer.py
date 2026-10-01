from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import xgap.experiments.m15_live_family_transfer as family_transfer

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_family_transfer_native_evidence import (
    audit_m15_family_transfer_native_run,
)
from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.experiments.m15_live_family_transfer import (
    build_m15_family_transfer_task_stream,
    run_m15_live_family_transfer,
)
from xgap.experiments.m15_native_services import (
    FAMILY_RUNTIME_COMPATIBILITY_SCHEMA_VERSION,
    FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_fixture import (
    load_m15_parameterized_fixture,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SPEC = (
    REPO_ROOT / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
)
QUERY_TEMPLATE = (
    REPO_ROOT
    / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
)
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
RUNTIME_HASH = "3" * 64


def _bundle(tmp_path: Path):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "bundle",
    )


@dataclass
class TransferClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    fail_artifacts: set[str] = field(default_factory=set)
    artifact_calls: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "family transfer fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_calls.append(artifact.artifact_id)
        if artifact.artifact_id in self.fail_artifacts:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="injected family-transfer failure",
            )
        # Make parallel_hash_join a stable development-fixture winner.  The
        # real experiment records wall-clock runtime rather than trusting this
        # synthetic elapsed_ms field.
        if artifact.artifact_id.endswith("neo4j-bound"):
            time.sleep(0.004)
        else:
            time.sleep(0.001)
        rows = [dict(row) for row in self.rows_by_artifact[artifact.artifact_id]]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                row
                for row in rows
                if str(row["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=4.0 if artifact.artifact_id.endswith("neo4j-bound") else 1.0,
        )


def _clients(bundle):
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    for query_id in bundle.instance_ids():
        source = load_m15_parameterized_instance(bundle, query_id)[
            "source_oracles"
        ]
        prefix = f"m15-f2c-{query_id}"
        rows["neo4j"][f"{prefix}-neo4j-full"] = source["neo4j_full"]
        rows["neo4j"][f"{prefix}-neo4j-bound"] = source["neo4j_full"]
        rows["fuseki"][f"{prefix}-fuseki-risk"] = source["fuseki_risk"]
    return {
        backend_id: TransferClient(backend_id, rows[backend_id])
        for backend_id in ("neo4j", "fuseki")
    }


@dataclass
class RecordingLoader:
    backend_id: str
    loaded: list[Path]

    def load(self, path: Path) -> BackendLoadReport:
        self.loaded.append(path)
        return BackendLoadReport(
            backend_id=self.backend_id,
            success=True,
            operations_attempted=1,
            bytes_sent=path.stat().st_size,
            elapsed_ms=1.0,
        )


def test_transfer_task_stream_freezes_seed_visibility(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    stream = build_m15_family_transfer_task_stream(bundle)

    seeds = [task for task in stream["tasks"] if task["split_role"] == "seed"]
    heldout = [
        task for task in stream["tasks"] if task["split_role"] == "heldout_instance"
    ]
    seed_ids = [task["task_id"] for task in seeds]
    assert len(seeds) == 4
    assert len(heldout) == 2
    assert all(task["memory"]["write_enabled"] for task in seeds)
    assert all(not task["memory"]["read_enabled"] for task in seeds)
    assert all(
        task["memory"]["eligible_predecessor_task_ids"] == seed_ids
        for task in heldout
    )
    assert all(not task["memory"]["write_enabled"] for task in heldout)
    assert not stream["cross_family_reads_allowed"]
    assert not stream["evaluation_writes_allowed"]


def test_live_transfer_reopens_seed_memory_and_selects_heldout_plans(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    record = run_m15_live_family_transfer(
        workload_bundle=bundle,
        clients=_clients(bundle),
        runtime_compatibility_sha256=RUNTIME_HASH,
        output_root=tmp_path / "runs",
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation"]["passed"]
    assert manifest["summary"] == {
        "calibration_remote_calls": 16,
        "evaluation_shadow_plan_runs": 2,
        "evaluation_shadow_remote_calls": 4,
        "heldout_online_plan_runs": 2,
        "heldout_task_count": 2,
        "memory_commit_count": 4,
        "observed_selection_count": 2,
        "online_remote_calls": 4,
        "seed_plan_runs": 8,
        "seed_task_count": 4,
        "selected_observed_winner_count": manifest["summary"][
            "selected_observed_winner_count"
        ],
    }
    assert manifest["answer_oracle_used_for_feature_or_selection"] is False
    assert manifest["answer_oracle_used_for_post_execution_validation"] is True
    assert manifest["memory_transfer_scope"] == (
        "same_method_same_family_same_runtime"
    )
    assert manifest["frozen_memory_view"]["eligible_task_ids"] == [
        "m15-f2c5-task-01",
        "m15-f2c5-task-02",
        "m15-f2c5-task-03",
        "m15-f2c5-task-04",
    ]
    assert len((record.run_root / "family_memory.jsonl").read_text().splitlines()) == 4
    assert all(
        result["selection"]["selection_mode"] == "family_local_knn"
        and result["selection"]["oracle_inputs"] == []
        and result["selected_exact"]
        and not result["memory_write_after_evaluation"]
        for result in manifest["heldout_results"].values()
    )
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert invocations["total_tool_invocations"] == 24
    assert invocations["automatic_retries"] == 0


def test_live_transfer_can_disable_evaluation_shadow_for_online_path(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    record = run_m15_live_family_transfer(
        workload_bundle=bundle,
        clients=_clients(bundle),
        runtime_compatibility_sha256=RUNTIME_HASH,
        output_root=tmp_path / "runs",
        evaluate_shadow=False,
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["summary"]["calibration_remote_calls"] == 16
    assert manifest["summary"]["online_remote_calls"] == 4
    assert manifest["summary"]["evaluation_shadow_remote_calls"] == 0
    assert manifest["summary"]["evaluation_shadow_plan_runs"] == 0
    assert manifest["evaluation_shadow_enabled"] is False
    assert all(
        not result["evaluation_shadow_runs"]
        and not result["order_confounded_development_diagnostic"]
        for result in manifest["heldout_results"].values()
    )


def test_answer_oracle_is_opened_only_after_seed_runs_or_heldout_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)
    output_root = tmp_path / "runs"
    run_root = output_root / "family-transfer-run"
    original = family_transfer.load_m15_parameterized_instance
    calls: list[str] = []

    def guarded_loader(bundle_value, query_id):
        task_root = run_root / "tasks" / query_id
        record = next(
            item
            for item in bundle.manifest["instances"]
            if item["query_id"] == query_id
        )
        if record["split_role"] == "seed":
            assert (task_root / "seed-parallel_hash_join.json").is_file()
            assert (task_root / "seed-risk_first_bind_join.json").is_file()
        else:
            assert (task_root / "selection.json").is_file()
            assert (task_root / "selected_run.json").is_file()
        calls.append(query_id)
        return original(bundle_value, query_id)

    monkeypatch.setattr(
        family_transfer,
        "load_m15_parameterized_instance",
        guarded_loader,
    )

    record = run_m15_live_family_transfer(
        workload_bundle=bundle,
        clients=clients,
        runtime_compatibility_sha256=RUNTIME_HASH,
        output_root=output_root,
        evaluate_shadow=False,
    )

    assert record.success
    assert calls == list(bundle.instance_ids())


def test_live_transfer_failure_is_not_retried_or_written_as_evaluation_memory(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)
    first_heldout = bundle.instance_ids()[4]
    clients["fuseki"].fail_artifacts.add(
        f"m15-f2c-{first_heldout}-fuseki-risk"
    )

    record = run_m15_live_family_transfer(
        workload_bundle=bundle,
        clients=clients,
        runtime_compatibility_sha256=RUNTIME_HASH,
        output_root=tmp_path / "runs",
    )

    assert not record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "failed"
    assert manifest["validation"]["passed"] is False
    assert manifest["automatic_retries"] == 0
    assert invocations["automatic_retries"] == 0
    assert len((record.run_root / "family_memory.jsonl").read_text().splitlines()) == 4
    assert manifest["summary"]["memory_commit_count"] == 4
    assert manifest["summary"]["heldout_online_plan_runs"] == 1
    assert manifest["summary"]["evaluation_shadow_plan_runs"] == 0


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _auditable_native_transfer(tmp_path: Path) -> tuple[Path, str]:
    expected_commit = "b" * 40
    run_root = tmp_path / "native-family-transfer"
    service_root = run_root / "native-service-run"
    bundle = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=run_root / "parameterized-workload-bundle",
    )
    clients = _clients(bundle)
    fixture = load_m15_parameterized_fixture(
        workload_bundle=bundle,
        clients=clients,
        loaders={
            backend_id: RecordingLoader(backend_id, [])
            for backend_id in ("neo4j", "fuseki")
        },
        output_root=service_root,
    )
    service_plan = {
        "schema_version": "m15-b2d-native-service-plan-v1",
        "allocation_id": "12345",
        "runtime_root": "/tmp/xgap-m15-12345.test",
        "filesystem_type": "xfs",
        "java": {
            "command": "/opt/java17/bin/java",
            "major": 17,
            "version_text": "openjdk 17.0.6",
        },
        "runtime_lock_sha256": "4" * 64,
        "staging_manifest_sha256": "5" * 64,
        "neo4j_http_url": "http://127.0.0.1:17474",
        "fuseki_url": "http://127.0.0.1:13030",
        "fuseki_dataset": "xgap",
        "services": [
            {
                "service_id": "neo4j",
                "product": "neo4j",
                "version": "5.26.30",
            },
            {
                "service_id": "fuseki",
                "product": "fuseki",
                "version": "5.6.0",
            },
        ],
        "public_ports": False,
        "automatic_retries": 0,
        "credentials_persisted": False,
    }
    runtime_identity = {
        "schema_version": FAMILY_RUNTIME_COMPATIBILITY_SCHEMA_VERSION,
        "allocation_id": "12345",
        "filesystem_type": "xfs",
        "java_major": 17,
        "runtime_lock_sha256": "4" * 64,
        "staging_manifest_sha256": "5" * 64,
        "services": [
            {
                "service_id": "fuseki",
                "product": "fuseki",
                "version": "5.6.0",
            },
            {
                "service_id": "neo4j",
                "product": "neo4j",
                "version": "5.26.30",
            },
        ],
        "reuse_scope": "same_native_service_allocation_only",
    }
    runtime_compatibility = {
        **runtime_identity,
        "runtime_compatibility_sha256": content_hash(runtime_identity),
    }
    _write_json(
        service_root / "family_runtime_compatibility.json",
        runtime_compatibility,
    )
    transfer = run_m15_live_family_transfer(
        workload_bundle=bundle,
        clients=clients,
        runtime_compatibility_sha256=runtime_compatibility[
            "runtime_compatibility_sha256"
        ],
        output_root=service_root,
    )
    for path in (fixture.manifest_path, transfer.manifest_path):
        value = json.loads(path.read_text(encoding="utf-8"))
        value["git"] = {"commit": expected_commit, "clean": True}
        _write_json(path, value)

    health = [
        {"service_id": backend_id, "success": True}
        for backend_id in ("neo4j", "fuseki")
    ]
    shutdown = [
        {"service_id": backend_id, "success": True}
        for backend_id in ("fuseki", "neo4j")
    ]
    _write_json(service_root / "service_health.json", health)
    _write_json(service_root / "service_shutdown.json", shutdown)
    _write_json(
        service_root / "run_status.json",
        {
            "schema_version": FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "error": None,
        },
    )
    _write_json(
        service_root / "run_manifest.json",
        {
            "schema_version": FAMILY_TRANSFER_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "error": None,
            "workload_mode": "parameterized_family_transfer",
            "workload_bundle": None,
            "parameterized_workload_bundle": dict(bundle.manifest),
            "service_plan": service_plan,
            "health": health,
            "shutdown": shutdown,
            "automatic_retries": 0,
            "service_restarts": 0,
            "public_ports": False,
            "credentials_persisted": False,
        },
    )
    _write_json(
        run_root / "run_status.json",
        {
            "status": "success",
            "exit_code": 0,
            "slurm_job_id": "12345",
            "git_commit": expected_commit,
            "workload_mode": "parameterized_family_transfer",
            "runtime_removed": True,
            "cleanup_error": None,
        },
    )
    (run_root / "environment.txt").write_text(
        "\n".join(
            (
                "run_version=m15-f2c5-native-live-family-transfer-services-v1",
                "slurm_job_id=12345",
                f"git_commit={expected_commit}",
                "runtime_filesystem_type=xfs",
                "workload_mode=parameterized_family_transfer",
                "loopback_only=true",
                "automatic_retries=0",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        run_root / "workload_generation.json",
        {"status": "success", "root": str(bundle.root), **bundle.manifest},
    )
    return run_root, expected_commit


def test_read_only_native_audit_binds_family_transfer_memory(
    tmp_path: Path,
) -> None:
    run_root, expected_commit = _auditable_native_transfer(tmp_path)

    audit = audit_m15_family_transfer_native_run(
        run_root=run_root,
        expected_commit=expected_commit,
    )

    assert audit.success
    assert len(audit.checks) >= 150
    assert audit.failed_check_ids == ()
    assert audit.to_dict()["run_tree_mutated"] is False
    json.dumps(audit.to_dict(), sort_keys=True)


def test_read_only_native_audit_rejects_changed_memory_observation(
    tmp_path: Path,
) -> None:
    run_root, expected_commit = _auditable_native_transfer(tmp_path)
    memory_path = (
        run_root
        / "native-service-run"
        / "family-transfer-run"
        / "family_memory.jsonl"
    )
    lines = memory_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["value"]["outcomes"][0]["elapsed_ms"] += 1000.0
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    memory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    audit = audit_m15_family_transfer_native_run(
        run_root=run_root,
        expected_commit=expected_commit,
    )

    assert not audit.success
    assert "memory.record.1.hash" in audit.failed_check_ids
