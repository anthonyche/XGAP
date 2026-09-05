from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.experiments.m15_live_federated import (
    build_m15_execution_plan,
    build_m15_observation_catalogs,
    build_m15_plan_candidates,
    build_m15_semantic_program,
    main,
    run_m15_live_federated,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport
from xgap.runtime import FederatedScheduler, RuntimeNodeKind
from xgap.semantic import ConstraintPolicy
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_LIVE = os.environ.get("XGAP_RUN_M15_LIVE") == "1"


@dataclass
class FakeClient:
    backend_id: str
    rows: list[dict[str, object]]
    ready: bool = True

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(
            backend_id=self.backend_id,
            ok=self.ready,
            message="fixture ready" if self.ready else "fixture unavailable",
            details={"software_version": "fixture-v1"},
        )

    def execute(self, artifact) -> ExecutionReport:
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
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=2.0,
            metadata={"transport": "offline-fixture"},
        )


def _clients(*, fuseki_ready: bool = True) -> dict[str, FakeClient]:
    return {
        "neo4j": FakeClient(
            "neo4j",
            [
                {
                    "person_id": "person-alice-smith",
                    "person": "Alice Smith",
                    "company_id": "neo:C1",
                    "amount": 120000,
                    "currency": "USD",
                    "occurred_on": "2026-08-20",
                },
                {
                    "person_id": "person-alice-smith",
                    "person": "Alice Smith",
                    "company_id": "neo:C2",
                    "amount": 90000,
                    "currency": "USD",
                    "occurred_on": "2026-08-25",
                },
            ],
        ),
        "fuseki": FakeClient(
            "fuseki",
            [
                {
                    "company_id": "rdf:C1",
                    "company": "Redstone Analytics",
                    "risk": "HIGH",
                },
                {
                    "company_id": "rdf:C3",
                    "company": "Old Peak Holdings",
                    "risk": "HIGH",
                },
            ],
            ready=fuseki_ready,
        ),
    }


def test_m15_program_and_runtime_preserve_hard_window_and_split_sources() -> None:
    program = build_m15_semantic_program()
    constraints = {
        constraint.constraint_id: constraint
        for operator in program.operators
        for constraint in operator.constraints
    }
    assert constraints["person-identity"].policy is ConstraintPolicy.HARD
    assert constraints["frozen-window"].policy is ConstraintPolicy.HARD
    assert constraints["risk-classification"].policy is ConstraintPolicy.RELAXABLE
    assert program.metadata["llm_required"] is False
    assert program.metadata["ontology_required"] is False

    plan = build_m15_execution_plan(REPO_ROOT)
    remote = [node for node in plan.nodes if node.kind.value == "remote_query"]
    assert [node.parameters["backend_id"] for node in remote] == ["neo4j", "fuseki"]
    assert plan.max_remote_calls == 2
    assert plan.roots == ("project-answer",)


def test_m15_equivalent_plan_space_executes_same_answer_with_different_transfer() -> None:
    plugins = BackendPluginRegistry()
    clients = _clients()
    plugins.register(NativeBackendPlugin("neo4j", clients["neo4j"]))
    plugins.register(NativeBackendPlugin("fuseki", clients["fuseki"]))
    scheduler = FederatedScheduler(BackendInvokeTool(plugins))
    candidates = build_m15_plan_candidates(REPO_ROOT)

    results = {
        candidate.plan.plan_id: scheduler.execute(candidate.plan)
        for candidate in candidates
    }

    assert len({candidate.semantic_equivalence_key for candidate in candidates}) == 1
    assert all(result.success for result in results.values())
    assert results["m15-parallel-hash"].final_rows == results[
        "m15-risk-first-bind"
    ].final_rows
    assert results["m15-risk-first-bind"].total_bytes_moved < results[
        "m15-parallel-hash"
    ].total_bytes_moved
    bind_nodes = [
        node
        for node in candidates[1].plan.nodes
        if node.kind is RuntimeNodeKind.REMOTE_BIND_QUERY
    ]
    assert len(bind_nodes) == 1
    assert bind_nodes[0].parameters["max_bindings"] == 100


def test_m15_observation_catalogs_are_versioned_and_query_allowlisted() -> None:
    catalogs = build_m15_observation_catalogs(REPO_ROOT)

    assert set(catalogs) == {"neo4j", "fuseki"}
    assert catalogs["neo4j"].version == "v1"
    assert set(catalogs["neo4j"].query_artifacts) == {
        "recent-transfers-full",
        "recent-transfers-bound",
    }
    assert catalogs["neo4j"].query_artifacts[
        "recent-transfers-bound"
    ].parameters == {"company_ids": ["C1", "C3"]}
    assert set(catalogs["fuseki"].query_artifacts) == {"high-risk"}


def test_m15_live_runner_persists_exact_cross_source_evidence(tmp_path: Path) -> None:
    record = run_m15_live_federated(
        output_root=tmp_path,
        run_id="offline-live-contract",
        repo_root=REPO_ROOT,
        clients=_clients(),
    )
    assert record.success, record.error
    assert record.result_path is not None
    result = json.loads(record.result_path.read_text(encoding="utf-8"))
    assert result["total_remote_calls"] == 2
    assert result["total_bytes_moved"] > 0
    assert result["final_rows"] == json.loads(
        (REPO_ROOT / "examples/m15_split_financial_risk/expected_result.json").read_text(
            encoding="utf-8"
        )
    )

    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["no_llm"] is True
    assert manifest["no_ontology"] is True
    assert manifest["automatic_retries"] == 0
    assert "run_manifest.json" in manifest["artifacts"]
    assert manifest["validation"]["checks"]["exact_neo4j_source_rows"]
    assert manifest["validation"]["checks"]["exact_fuseki_source_rows"]
    assert manifest["validation"]["checks"]["neo4j_has_no_risk_or_company_name"]
    assert manifest["validation"]["checks"]["fuseki_has_no_person_or_transfer_fact"]
    assert {
        "execution_plan.json",
        "health.json",
        "result.json",
        "run_manifest.json",
        "run_status.json",
        "semantic_program.json",
        "validation.json",
    } <= {path.name for path in record.run_root.iterdir()}


def test_m15_live_runner_persists_health_failure_without_retry(tmp_path: Path) -> None:
    record = run_m15_live_federated(
        output_root=tmp_path,
        run_id="failed-health",
        repo_root=REPO_ROOT,
        clients=_clients(fuseki_ready=False),
    )
    assert not record.success
    assert "fuseki" in str(record.error)
    assert record.result_path is None
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert manifest["automatic_retries"] == 0
    assert manifest["backend_health"]["neo4j"]["ok"] is True
    assert manifest["backend_health"]["fuseki"]["ok"] is False


def test_m15_live_runner_refuses_to_overwrite_run(tmp_path: Path) -> None:
    run_m15_live_federated(
        output_root=tmp_path,
        run_id="immutable-run",
        repo_root=REPO_ROOT,
        clients=_clients(),
    )
    with pytest.raises(FileExistsError):
        run_m15_live_federated(
            output_root=tmp_path,
            run_id="immutable-run",
            repo_root=REPO_ROOT,
            clients=_clients(),
        )


def test_m15_live_cli_is_fail_closed_without_gate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_RUN_M15_LIVE", raising=False)
    assert main([]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"


@pytest.mark.skipif(
    not RUN_LIVE,
    reason="set XGAP_RUN_M15_LIVE=1 after loading both M15 split fixtures",
)
def test_m15_live_neo4j_fuseki_vertical_slice(tmp_path: Path) -> None:
    record = run_m15_live_federated(
        output_root=tmp_path,
        run_id="live-two-engine-gate",
        repo_root=REPO_ROOT,
    )
    assert record.success, record.error
