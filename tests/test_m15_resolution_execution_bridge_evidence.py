from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_live_resolution_execution_bridge import (
    RESOLUTION_EXECUTION_BRIDGE_PREFLIGHT_SCHEMA_VERSION,
    prepare_m15_resolution_execution_bridge,
    run_m15_live_resolution_execution_bridge,
)
from xgap.experiments.m15_native_services import (
    RESOLUTION_EXECUTION_BRIDGE_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_fixture import (
    PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_resolution_execution_bridge_evidence import (
    audit_m15_resolution_execution_bridge_run,
)
from xgap.experiments.m15_semantic_intake import run_semantic_intake
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SPEC = (
    REPO_ROOT / "experiments/configs/m15_e4_resolution_execution_bridge_dev.json"
)
EXPECTED_COMMIT = "1" * 40


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class _Client:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        rows = [dict(item) for item in self.rows_by_artifact[artifact.artifact_id]]
        upper = artifact.parameters.get("occurred_on_lt")
        if self.backend_id == "neo4j" and isinstance(upper, str):
            rows = [item for item in rows if str(item["occurred_on"]) < upper]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                item
                for item in rows
                if str(item["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=1.0,
        )


def _clients(prepared):
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    candidates = {
        item["plan_id"]: item
        for item in prepared.bridge.to_dict()["physical_candidates"]
    }
    for plan_id, plan in prepared.bridge.plans.items():
        instance = load_m15_parameterized_instance(
            prepared.workload.workload_bundle,
            candidates[plan_id]["query_id"],
        )
        for node in plan.nodes:
            backend_id = node.parameters.get("backend_id")
            if backend_id not in rows:
                continue
            artifact = QueryArtifact.from_dict(node.parameters["artifact"])
            role = (
                "fuseki_risk"
                if backend_id == "fuseki"
                else "neo4j_bound"
                if "company_ids" in artifact.parameters
                else "neo4j_full"
            )
            rows[backend_id][artifact.artifact_id] = instance["source_oracles"][role]
    return {key: _Client(key, value) for key, value in rows.items()}


@pytest.fixture(scope="module")
def audited_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("e4b-evidence") / "outer"
    service = root / "native-service-run"
    preflight = service / "resolution-execution-bridge-preflight"
    fixture = service / "resolution-execution-fixture-load"
    root.mkdir(parents=True)
    resolution = run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=REPO_ROOT / "experiments/configs/m15_e3_financial_risk_intake_dev.json",
        catalog_path=REPO_ROOT / "experiments/specs/m15_e3_financial_risk_catalog_dev.json",
        ontology_path=REPO_ROOT / "experiments/specs/m15_e3_financial_risk_ontology_dev.json",
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="e4b-evidence-test",
    )
    resolution_path = root / "resolution_run.json"
    _write(resolution_path, resolution)
    spec_path = root / "resolution_bridge_spec.json"
    shutil.copyfile(BRIDGE_SPEC, spec_path)
    prepared = prepare_m15_resolution_execution_bridge(
        resolution_run_path=resolution_path,
        bridge_spec_path=spec_path,
        workload_destination=preflight / "workload",
        repo_root=REPO_ROOT,
    )
    bridge_payload = prepared.bridge.to_dict()
    _write(preflight / "bridge_plan.json", bridge_payload)
    preflight_manifest = {
        "schema_version": RESOLUTION_EXECUTION_BRIDGE_PREFLIGHT_SCHEMA_VERSION,
        "sealed_before_service_start": True,
        "bridge_sealed_before_workload_generation": True,
        "bridge_plan_sha256": bridge_payload["bridge_plan_sha256"],
        "resolution_run_sha256": _sha256(resolution_path),
        "bridge_spec_sha256": _sha256(spec_path),
        "workload_manifest_sha256": _sha256(prepared.workload.root / "manifest.json"),
        "expected_counts": bridge_payload["counts"],
        "backend_calls_before_seal": 0,
        "answer_oracle_opened_before_seal": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    preflight_manifest["preflight_sha256"] = content_hash(preflight_manifest)
    _write(preflight / "preflight_manifest.json", preflight_manifest)

    with patch(
        "xgap.experiments.m15_live_resolution_execution_bridge._git_state",
        return_value={"commit": EXPECTED_COMMIT, "clean": True},
    ):
        record = run_m15_live_resolution_execution_bridge(
            resolution_run_path=resolution_path,
            bridge_spec_path=spec_path,
            prepared=prepared,
            clients=_clients(prepared),
            output_root=service,
            repo_root=REPO_ROOT,
        )
    assert record.success

    fixture.mkdir()
    _write(fixture / "run_status.json", {
        "schema_version": PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
        "status": "success",
    })
    loads = {
        key: {"success": True, "backend_id": key}
        for key in ("neo4j", "fuseki")
    }
    verification = {"validation": {"passed": True, "checks": {"exact": True}}}
    _write(fixture / "load_reports.json", loads)
    _write(fixture / "verification.json", verification)
    _write(fixture / "run_manifest.json", {
        "schema_version": PARAMETERIZED_FIXTURE_SCHEMA_VERSION,
        "status": "success",
        "error": None,
        "git": {"commit": EXPECTED_COMMIT, "clean": True},
        "workload_bundle": dict(prepared.workload.workload_bundle.manifest),
        "verification": {"passed": True},
        "automatic_retries": 0,
    })
    _write(root / "run_status.json", {
        "status": "success",
        "exit_code": 0,
        "git_commit": EXPECTED_COMMIT,
        "workload_mode": "resolution_execution_bridge",
        "runtime_removed": True,
        "cleanup_error": None,
    })
    (root / "environment.txt").write_text(
        "\n".join((
            "run_version=m15-e4b-native-live-resolution-execution-bridge-services-v1",
            f"git_commit={EXPECTED_COMMIT}",
            "workload_mode=resolution_execution_bridge",
            "loopback_only=true",
            "automatic_retries=0",
        )) + "\n",
        encoding="utf-8",
    )
    _write(service / "run_status.json", {"status": "success"})
    _write(service / "service_plan.json", {"loopback_only": True})
    _write(service / "service_health.json", [
        {"service_id": "neo4j", "success": True},
        {"service_id": "fuseki", "success": True},
    ])
    _write(service / "service_shutdown.json", [
        {"service_id": "fuseki", "success": True},
        {"service_id": "neo4j", "success": True},
    ])
    _write(service / "run_manifest.json", {
        "schema_version": RESOLUTION_EXECUTION_BRIDGE_SERVICE_RUN_SCHEMA_VERSION,
        "status": "success",
        "error": None,
        "runtime_root": str(root / "deleted-runtime"),
        "workload_mode": "resolution_execution_bridge",
        "resolution_execution_bridge": {
            "resolution_run": str(resolution_path),
            "bridge_spec": str(spec_path),
        },
        "resolution_execution_bridge_preflight": preflight_manifest,
        "health": [
            {"service_id": "neo4j", "success": True},
            {"service_id": "fuseki", "success": True},
        ],
        "shutdown": [
            {"service_id": "fuseki", "success": True},
            {"service_id": "neo4j", "success": True},
        ],
        "automatic_retries": 0,
        "service_restarts": 0,
        "public_ports": False,
        "credentials_persisted": False,
    })
    return root


def test_e4b_audit_reconstructs_exact_answers_without_mutation(
    audited_run: Path,
) -> None:
    before = sorted(
        (path.relative_to(audited_run).as_posix(), path.read_bytes())
        for path in audited_run.rglob("*")
        if path.is_file()
    )
    audit = audit_m15_resolution_execution_bridge_run(
        run_root=audited_run,
        expected_commit=EXPECTED_COMMIT,
        repo_root=REPO_ROOT,
    )
    after = sorted(
        (path.relative_to(audited_run).as_posix(), path.read_bytes())
        for path in audited_run.rglob("*")
        if path.is_file()
    )
    assert audit.success
    assert not audit.failed_check_ids
    assert not audit.run_tree_mutated
    assert before == after


def test_e4b_audit_rejects_postexecution_row_tampering(
    audited_run: Path,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "tampered"
    shutil.copytree(audited_run, copied)
    results_path = (
        copied
        / "native-service-run/resolution-execution-bridge-run/execution_results.json"
    )
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["results"][0]["runtime_result"]["final_rows"] = []
    _write(results_path, results)

    audit = audit_m15_resolution_execution_bridge_run(
        run_root=copied,
        expected_commit=EXPECTED_COMMIT,
        repo_root=REPO_ROOT,
    )

    assert not audit.success
    assert "result.0.exact_rows" in audit.failed_check_ids
    assert not audit.run_tree_mutated
