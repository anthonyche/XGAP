from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from xgap.experiments.m15_live_method_matrix import (
    QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION,
)
from xgap.experiments.m15_live_query_bound_session import (
    LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION,
    main,
    prepare_m15_live_query_bound_session,
    run_m15_live_query_bound_session,
)
from xgap.experiments.m15_query_bound_campaign import (
    compile_m15_query_bound_campaign_file,
)
from xgap.experiments.m15_workload import (
    M15WorkloadSpec,
    generate_m15_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "experiments/configs/m15_f2_query_bound_campaign_dev.json"
SELECTIVE = REPO_ROOT / "experiments/configs/m15_f0_selective.json"


@dataclass
class _LiveClient:
    backend_id: str
    rows: list[dict[str, object]]
    health_calls: int = 0
    artifact_calls: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        self.health_calls += 1
        return BackendStatus(self.backend_id, True, "test client")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_calls.append(artifact.artifact_id)
        rows = [dict(row) for row in self.rows]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                row
                for row in rows
                if str(row["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            self.backend_id,
            artifact.artifact_id,
            artifact.language,
            True,
            rows=rows,
            elapsed_ms=2.0,
            metadata={"transport": "offline-live-query-bound-session"},
        )


@dataclass
class _Neo4jLiveClient(_LiveClient):
    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        return self.execute(artifact)


def _bundle(tmp_path: Path):
    return generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(SELECTIVE),
        tmp_path / "bundle",
    )


def _clients(bundle):
    return {
        "neo4j": _Neo4jLiveClient(
            "neo4j", bundle.expected_source_rows["neo4j"]
        ),
        "fuseki": _LiveClient(
            "fuseki", bundle.expected_source_rows["fuseki"]
        ),
    }


def _plan_and_session():
    plan = compile_m15_query_bound_campaign_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()
    session = next(
        item for item in plan["sessions"] if item["workload_label"] == "selective"
    )
    return plan, session


def test_live_query_bound_session_verifies_bundle_before_exact_execution(
    tmp_path: Path,
) -> None:
    plan, session = _plan_and_session()
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)

    record = run_m15_live_query_bound_session(
        query_bound_registry=REGISTRY,
        session_id=session["session_id"],
        expected_registry_spec_sha256=plan["registry_spec_sha256"],
        expected_query_bound_schedule_sha256=plan[
            "query_bound_schedule_sha256"
        ],
        workload_bundle=bundle,
        output_root=tmp_path,
        run_id="query-bound-session",
        repo_root=REPO_ROOT,
        clients=clients,
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    matrix_root = record.run_root / "method-matrix-run"
    matrix = json.loads(
        (matrix_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    calls = json.loads(
        (matrix_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    binding = matrix["campaign_binding"]
    query_id = "financial-risk-alice-high-risk"
    contract_path = record.run_root / "query_contracts" / f"{query_id}.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == LIVE_QUERY_BOUND_SESSION_SCHEMA_VERSION
    assert manifest["validation"]["passed"] is True
    assert manifest["query_bound_schedule_sha256"] == plan[
        "query_bound_schedule_sha256"
    ]
    assert manifest["claim_boundary"]["live_bundle_contracts_verified"] is True
    assert manifest["claim_boundary"]["native_service_lifecycle"] is False
    assert binding["schema_version"] == QUERY_BOUND_CAMPAIGN_BINDING_SCHEMA_VERSION
    assert binding["query_contracts"][query_id]["query_contract_sha256"] == (
        contract["query_contract_sha256"]
    )
    assert matrix["method_order"] == session["method_order"]
    assert matrix["evidence_class"] == (
        "live_backend_query_bound_session_engineering_gate"
    )
    assert calls["total_tool_invocations"] == 18
    assert calls["automatic_retries"] == 0
    assert all(item["exact_answer"] for item in matrix["methods"].values())
    assert manifest["paper_result"] is False
    assert clients["neo4j"].health_calls == 1
    assert clients["fuseki"].health_calls == 1


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("registry_spec_sha256", "registry spec hash disagrees"),
        ("query_bound_schedule_sha256", "schedule hash disagrees"),
    ],
)
def test_live_query_bound_session_rejects_plan_hash_drift_before_backend_call(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    plan, session = _plan_and_session()
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)
    values = {
        "registry_spec_sha256": plan["registry_spec_sha256"],
        "query_bound_schedule_sha256": plan["query_bound_schedule_sha256"],
    }
    values[field] = "0" * 64

    with pytest.raises(ValueError, match=message):
        run_m15_live_query_bound_session(
            query_bound_registry=REGISTRY,
            session_id=session["session_id"],
            expected_registry_spec_sha256=values["registry_spec_sha256"],
            expected_query_bound_schedule_sha256=values[
                "query_bound_schedule_sha256"
            ],
            workload_bundle=bundle,
            output_root=tmp_path / "runs",
            run_id="hash-drift",
            repo_root=REPO_ROOT,
            clients=clients,
        )

    assert clients["neo4j"].health_calls == 0
    assert clients["fuseki"].health_calls == 0
    assert not (tmp_path / "runs" / "hash-drift").exists()


def test_live_query_bound_session_rejects_wrong_workload_before_call(
    tmp_path: Path,
) -> None:
    plan, session = _plan_and_session()
    broad_bundle = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(
            REPO_ROOT / "experiments/configs/m15_f0_broad_hot.json"
        ),
        tmp_path / "broad",
    )

    with pytest.raises(ValueError, match="workload_id disagrees"):
        prepare_m15_live_query_bound_session(
            query_bound_registry=REGISTRY,
            session_id=session["session_id"],
            expected_registry_spec_sha256=plan["registry_spec_sha256"],
            expected_query_bound_schedule_sha256=plan[
                "query_bound_schedule_sha256"
            ],
            workload_bundle=broad_bundle,
            repo_root=REPO_ROOT,
        )


def test_live_query_bound_session_recomputes_and_rejects_wrong_contract_hash(
    tmp_path: Path,
) -> None:
    registry_payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry_payload["bindings"][0]["expected_query_contract_sha256"] = "0" * 64
    wrong_registry = tmp_path / "wrong-contract-registry.json"
    wrong_registry.write_text(json.dumps(registry_payload), encoding="utf-8")
    wrong_plan = compile_m15_query_bound_campaign_file(
        wrong_registry,
        repo_root=REPO_ROOT,
    ).to_dict()
    session = next(
        item
        for item in wrong_plan["sessions"]
        if item["workload_label"] == "selective"
    )
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)

    with pytest.raises(ValueError, match="live bundle query contract hash disagrees"):
        run_m15_live_query_bound_session(
            query_bound_registry=wrong_registry,
            session_id=session["session_id"],
            expected_registry_spec_sha256=wrong_plan["registry_spec_sha256"],
            expected_query_bound_schedule_sha256=wrong_plan[
                "query_bound_schedule_sha256"
            ],
            workload_bundle=bundle,
            output_root=tmp_path / "runs",
            run_id="wrong-contract",
            repo_root=REPO_ROOT,
            clients=clients,
        )

    assert clients["neo4j"].health_calls == 0
    assert clients["fuseki"].health_calls == 0
    assert not (tmp_path / "runs" / "wrong-contract").exists()


def test_live_query_bound_session_cli_is_explicitly_gated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_RUN_M15_LIVE_QUERY_BOUND_SESSION", raising=False)

    assert main(
        [
            "--query-bound-registry",
            "unused",
            "--session-id",
            "unused",
            "--expected-registry-spec-sha256",
            "0" * 64,
            "--expected-query-bound-schedule-sha256",
            "1" * 64,
            "--workload-bundle",
            "unused",
        ]
    ) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
