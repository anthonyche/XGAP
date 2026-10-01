from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.experiments.m15_live_parameterized_stream import (
    build_m15_parameterized_task_stream,
    run_m15_live_parameterized_stream,
)
from xgap.experiments.m15_parameterized_fixture import (
    load_m15_parameterized_fixture,
)
from xgap.experiments.m15_parameterized_native_evidence import (
    audit_m15_parameterized_native_run,
)
from xgap.experiments.m15_native_services import (
    PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
    load_m15_parameterized_workload_bundle,
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


def _bundle(tmp_path: Path):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "bundle",
    )


@dataclass
class BundleClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    fail_artifact: str | None = None

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        if artifact.artifact_id == self.fail_artifact:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="injected failure",
            )
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
            elapsed_ms=1.0,
        )


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
        backend_id: BundleClient(backend_id, rows[backend_id])
        for backend_id in ("neo4j", "fuseki")
    }


def test_task_stream_is_explicit_seed_then_heldout_contract(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    stream = build_m15_parameterized_task_stream(bundle)

    assert stream["task_count"] == 6
    assert [task["sequence_index"] for task in stream["tasks"]] == list(
        range(1, 7)
    )
    assert [task["split_role"] for task in stream["tasks"]] == [
        "seed",
        "seed",
        "seed",
        "seed",
        "heldout_instance",
        "heldout_instance",
    ]
    assert {task["family_compatibility_sha256"] for task in stream["tasks"]} == {
        bundle.manifest["family_compatibility_sha256"]
    }
    assert all(task["semantic_deviation"] == 0 for task in stream["tasks"])


def test_parameterized_fixture_loads_once_and_verifies_all_instances(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)
    loaded: list[Path] = []
    loaders = {
        backend_id: RecordingLoader(backend_id, loaded)
        for backend_id in ("neo4j", "fuseki")
    }

    record = load_m15_parameterized_fixture(
        workload_bundle=bundle,
        clients=clients,
        loaders=loaders,
        output_root=tmp_path / "runs",
    )

    assert record.success
    assert loaded == [
        bundle.path("load_neo4j.cypher"),
        bundle.path("load_fuseki.ttl"),
    ]
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["verification"]["passed"]
    assert manifest["verification"]["query_instance_count"] == 6
    assert manifest["verification"]["backend_query_count"] == 12
    assert len(manifest["verification"]["checks"]) == 24
    assert manifest["automatic_retries"] == 0


def test_live_stream_executes_both_exact_plans_for_all_instances(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    record = run_m15_live_parameterized_stream(
        workload_bundle=bundle,
        clients=_clients(bundle),
        output_root=tmp_path / "runs",
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation"]["passed"]
    assert manifest["summary"] == {
        "exact_answer_count": 12,
        "query_instance_count": 6,
        "strategy_run_count": 12,
        "total_bytes_moved": manifest["summary"]["total_bytes_moved"],
        "total_remote_calls": 24,
    }
    assert not manifest["answer_oracle_used_for_plan_construction"]
    assert manifest["memory_enabled"] is False
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert invocations["total_tool_invocations"] == 24
    assert invocations["automatic_retries"] == 0


def test_live_stream_fails_closed_and_keeps_failure_evidence(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)
    first_query = bundle.instance_ids()[0]
    clients["neo4j"].fail_artifact = f"m15-f2c-{first_query}-neo4j-full"

    record = run_m15_live_parameterized_stream(
        workload_bundle=bundle,
        clients=clients,
        output_root=tmp_path / "runs",
    )

    assert not record.success
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert manifest["status"] == "failed"
    assert manifest["automatic_retries"] == 0
    assert (record.run_root / "backend_invocations.json").is_file()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _auditable_run(tmp_path: Path) -> tuple[Path, str]:
    expected_commit = "a" * 40
    run_root = tmp_path / "native-run"
    service_root = run_root / "native-service-run"
    bundle = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=run_root / "parameterized-workload-bundle",
    )
    clients = _clients(bundle)
    loaded: list[Path] = []
    fixture = load_m15_parameterized_fixture(
        workload_bundle=bundle,
        clients=clients,
        loaders={
            backend_id: RecordingLoader(backend_id, loaded)
            for backend_id in ("neo4j", "fuseki")
        },
        output_root=service_root,
    )
    stream = run_m15_live_parameterized_stream(
        workload_bundle=bundle,
        clients=clients,
        output_root=service_root,
    )
    for path in (fixture.manifest_path, stream.manifest_path):
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
            "schema_version": PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "error": None,
        },
    )
    _write_json(
        service_root / "run_manifest.json",
        {
            "schema_version": PARAMETERIZED_STREAM_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "error": None,
            "workload_mode": "parameterized_stream",
            "workload_bundle": None,
            "parameterized_workload_bundle": dict(bundle.manifest),
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
            "workload_mode": "parameterized_stream",
            "runtime_removed": True,
            "cleanup_error": None,
        },
    )
    (run_root / "environment.txt").write_text(
        "\n".join(
            (
                "run_version=m15-f2c4-native-live-parameterized-stream-services-v1",
                f"git_commit={expected_commit}",
                "workload_mode=parameterized_stream",
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


def test_read_only_audit_binds_every_parameterized_result(tmp_path: Path) -> None:
    run_root, expected_commit = _auditable_run(tmp_path)

    audit = audit_m15_parameterized_native_run(
        run_root=run_root,
        expected_commit=expected_commit,
    )

    assert audit.success
    assert len(audit.checks) >= 140
    assert audit.failed_check_ids == ()
    assert audit.to_dict()["run_tree_mutated"] is False


def test_read_only_audit_rejects_one_changed_answer(tmp_path: Path) -> None:
    run_root, expected_commit = _auditable_run(tmp_path)
    bundle = load_m15_parameterized_workload_bundle(
        run_root / "parameterized-workload-bundle"
    )
    query_id = bundle.instance_ids()[0]
    result_path = (
        run_root
        / "native-service-run"
        / "parameterized-stream-run"
        / "tasks"
        / query_id
        / "parallel_hash_join.json"
    )
    value = json.loads(result_path.read_text(encoding="utf-8"))
    value["final_rows"] = []
    _write_json(result_path, value)

    audit = audit_m15_parameterized_native_run(
        run_root=run_root,
        expected_commit=expected_commit,
    )

    assert not audit.success
    assert (
        f"task.{query_id}.parallel_hash_join.exact_rows"
        in audit.failed_check_ids
    )
