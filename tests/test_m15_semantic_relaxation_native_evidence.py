from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.experiments.m15_live_semantic_relaxation import (
    run_m15_live_semantic_risk_relaxation,
)
from xgap.experiments.m15_native_services import (
    SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION,
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
from xgap.experiments.m15_semantic_frontier import (
    load_m15_semantic_relaxation_catalog,
)
from xgap.experiments.m15_semantic_overlay import (
    generate_m15_semantic_overlay_bundle,
)
from xgap.experiments.m15_semantic_relaxation_native_evidence import (
    audit_m15_semantic_relaxation_native_run,
    main,
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
SEMANTIC_CATALOG = (
    REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
)
BASE_QUERY_ID = "financial-risk-alice-aug-high-v2"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass
class AuditClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
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
class AuditLoader:
    backend_id: str

    def load(self, path: Path) -> BackendLoadReport:
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
        backend_id: AuditClient(backend_id, rows[backend_id])
        for backend_id in ("neo4j", "fuseki")
    }


def _auditable_run(tmp_path: Path) -> tuple[Path, str]:
    expected_commit = "a" * 40
    run_root = tmp_path / "native-run"
    run_root.mkdir()
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=run_root / "semantic-base-workload-bundle",
    )
    catalog_path = run_root / "semantic_catalog.json"
    catalog_path.write_bytes(SEMANTIC_CATALOG.read_bytes())
    catalog = load_m15_semantic_relaxation_catalog(catalog_path)
    overlay = generate_m15_semantic_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=catalog,
        destination=run_root / "semantic-overlay",
    )
    clients = _clients(overlay.workload_bundle)
    service_root = run_root / "native-service-run"
    fixture = load_m15_parameterized_fixture(
        workload_bundle=overlay.workload_bundle,
        clients=clients,
        loaders={
            backend_id: AuditLoader(backend_id)
            for backend_id in ("neo4j", "fuseki")
        },
        output_root=service_root,
        run_id="semantic-fixture-load",
        repo_root=REPO_ROOT,
    )
    live = run_m15_live_semantic_risk_relaxation(
        semantic_overlay=overlay,
        base_bundle=base,
        catalog=catalog,
        clients=clients,
        output_root=service_root,
        run_id="semantic-risk-relaxation-run",
        repo_root=REPO_ROOT,
    )
    for path in (fixture.manifest_path, live.manifest_path):
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
            "schema_version": SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "error": None,
        },
    )
    _write_json(
        service_root / "run_manifest.json",
        {
            "schema_version": SEMANTIC_RELAXATION_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "error": None,
            "workload_mode": "semantic_risk_relaxation",
            "workload_bundle": None,
            "parameterized_workload_bundle": None,
            "semantic_base_workload_bundle": dict(base.manifest),
            "semantic_overlay": dict(overlay.manifest),
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
            "workload_mode": "semantic_risk_relaxation",
            "runtime_removed": True,
            "cleanup_error": None,
        },
    )
    (run_root / "environment.txt").write_text(
        "\n".join(
            (
                "run_version=m15-f2c7b2-native-live-semantic-risk-relaxation-services-v1",
                f"git_commit={expected_commit}",
                "workload_mode=semantic_risk_relaxation",
                "loopback_only=true",
                "automatic_retries=0",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        run_root / "semantic_base_generation.json",
        {"status": "success", "root": str(base.root), **base.manifest},
    )
    _write_json(
        run_root / "semantic_overlay_generation.json",
        {"status": "success", "root": str(overlay.root), **overlay.manifest},
    )
    return run_root, expected_commit


def test_read_only_audit_binds_semantic_class_plan_and_result(
    tmp_path: Path,
) -> None:
    run_root, expected_commit = _auditable_run(tmp_path)

    audit = audit_m15_semantic_relaxation_native_run(
        run_root=run_root,
        expected_commit=expected_commit,
    )

    assert audit.success
    assert len(audit.checks) >= 100
    assert audit.failed_check_ids == ()
    assert audit.to_dict()["run_tree_mutated"] is False


def test_read_only_audit_rejects_changed_relaxed_answer(tmp_path: Path) -> None:
    run_root, expected_commit = _auditable_run(tmp_path)
    result_path = (
        run_root
        / "native-service-run"
        / "semantic-risk-relaxation-run"
        / "semantic_result.json"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["final_rows"] = []
    _write_json(result_path, result)

    audit = audit_m15_semantic_relaxation_native_run(
        run_root=run_root,
        expected_commit=expected_commit,
    )

    assert not audit.success
    assert "result.exact_rows" in audit.failed_check_ids


def test_read_only_audit_rejects_semantic_plan_identity_drift(
    tmp_path: Path,
) -> None:
    run_root, expected_commit = _auditable_run(tmp_path)
    plan_path = (
        run_root
        / "native-service-run"
        / "semantic-risk-relaxation-run"
        / "semantic_plan.json"
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["metadata"]["semantic_class_id"] = "m15-class-tampered"
    _write_json(plan_path, plan)

    audit = audit_m15_semantic_relaxation_native_run(
        run_root=run_root,
        expected_commit=expected_commit,
    )

    assert not audit.success
    assert "semantic_plan" in audit.failed_check_ids


def test_audit_cli_writes_only_a_separate_output(tmp_path: Path, capsys) -> None:
    run_root, expected_commit = _auditable_run(tmp_path)
    output = tmp_path / "audits" / "semantic-audit.json"

    assert (
        main(
            [
                "--run-root",
                str(run_root),
                "--expected-commit",
                expected_commit,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert printed == persisted
    assert persisted["success"] is True
    assert persisted["run_tree_mutated"] is False

    assert (
        main(
            [
                "--run-root",
                str(run_root),
                "--expected-commit",
                expected_commit,
                "--output",
                str(output),
            ]
        )
        == 2
    )
