from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.experiments.m15_live_resolution_execution_bridge import (
    prepare_m15_resolution_execution_bridge,
    run_m15_live_resolution_execution_bridge,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_semantic_intake import run_semantic_intake
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SPEC = (
    REPO_ROOT / "experiments/configs/m15_e4_resolution_execution_bridge_dev.json"
)


@dataclass
class _LiveBridgeClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    fail_first: bool = False
    calls: int = 0

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="controlled first-call failure",
            )
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


def _resolution_file(tmp_path: Path) -> Path:
    result = run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=(
            REPO_ROOT
            / "experiments/configs/m15_e3_financial_risk_intake_dev.json"
        ),
        catalog_path=(
            REPO_ROOT
            / "experiments/specs/m15_e3_financial_risk_catalog_dev.json"
        ),
        ontology_path=(
            REPO_ROOT
            / "experiments/specs/m15_e3_financial_risk_ontology_dev.json"
        ),
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="explicit-live-bridge-test-selection",
    )
    path = tmp_path / "resolution_run.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


def _prepared(tmp_path: Path):
    resolution = _resolution_file(tmp_path)
    prepared = prepare_m15_resolution_execution_bridge(
        resolution_run_path=resolution,
        bridge_spec_path=BRIDGE_SPEC,
        workload_destination=tmp_path / "workload",
        repo_root=REPO_ROOT,
    )
    return resolution, prepared


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
        source = instance["source_oracles"]
        for node in plan.nodes:
            backend_id = node.parameters.get("backend_id")
            if backend_id not in rows:
                continue
            artifact = QueryArtifact.from_dict(node.parameters["artifact"])
            if backend_id == "fuseki":
                role = "fuseki_risk"
            elif "company_ids" in artifact.parameters:
                role = "neo4j_bound"
            else:
                role = "neo4j_full"
            rows[backend_id][artifact.artifact_id] = source[role]
    return {
        backend_id: _LiveBridgeClient(backend_id, values)
        for backend_id, values in rows.items()
    }


def test_live_bridge_executes_exactly_four_plans_without_profiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolution, prepared = _prepared(tmp_path)
    clients = _clients(prepared)

    def guarded_instance_load(*args, **kwargs):
        assert sum(client.calls for client in clients.values()) == 8
        return load_m15_parameterized_instance(*args, **kwargs)

    monkeypatch.setattr(
        "xgap.experiments.m15_live_resolution_execution_bridge."
        "load_m15_parameterized_instance",
        guarded_instance_load,
    )

    record = run_m15_live_resolution_execution_bridge(
        resolution_run_path=resolution,
        bridge_spec_path=BRIDGE_SPEC,
        prepared=prepared,
        clients=clients,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    results = json.loads(record.result_path.read_text(encoding="utf-8"))["results"]
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert manifest["validation"]["passed"]
    assert manifest["summary"]["physical_plan_run_count"] == 4
    assert manifest["summary"]["total_remote_calls"] == 8
    assert manifest["current_query_profile_calls"] == 0
    assert manifest["llm_calls_made"] == 0
    assert manifest["answer_oracle_opened_after_all_executions"]
    assert len(results) == 4
    assert all(item["exact_oracle_answer"] for item in results)
    assert invocations["total_tool_invocations"] == 8
    assert invocations["automatic_retries"] == 0


def test_live_bridge_stops_after_first_failed_plan_without_retry(
    tmp_path: Path,
) -> None:
    resolution, prepared = _prepared(tmp_path)
    clients = _clients(prepared)
    first_plan = prepared.bridge.to_dict()["physical_candidates"][0]
    first_runtime = prepared.bridge.plans[first_plan["plan_id"]]
    first_backend = next(
        str(node.parameters["backend_id"])
        for node in first_runtime.nodes
        if node.parameters.get("backend_id") in clients
    )
    clients[first_backend].fail_first = True

    record = run_m15_live_resolution_execution_bridge(
        resolution_run_path=resolution,
        bridge_spec_path=BRIDGE_SPEC,
        prepared=prepared,
        clients=clients,
        output_root=tmp_path / "failed-runs",
        repo_root=REPO_ROOT,
    )

    assert not record.success
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    results = json.loads(record.result_path.read_text(encoding="utf-8"))["results"]
    assert invocations["automatic_retries"] == 0
    # The first candidate is a parallel plan, so both of its independent
    # backend calls may already be in flight when one fails.  Fail-stop means
    # no later physical plan starts and neither call is retried.
    assert invocations["total_tool_invocations"] == 2
    assert len(results) == 1
    assert results[0]["plan_id"] == first_plan["plan_id"]
    assert not results[0]["runtime_result"]["success"]
    assert results[0]["expected_final_row_count"] is None
    assert results[0]["exact_oracle_answer"] is None
    assert clients[first_backend].calls == 1
    assert sum(client.calls for client in clients.values()) == 2
