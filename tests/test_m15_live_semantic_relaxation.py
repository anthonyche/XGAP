from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from xgap.experiments.m15_live_semantic_relaxation import (
    FIXED_PHYSICAL_STRATEGY,
    build_m15_semantic_risk_execution_plan,
    run_m15_live_semantic_risk_relaxation,
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


def _overlay(tmp_path: Path):
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "base",
    )
    catalog = load_m15_semantic_relaxation_catalog(SEMANTIC_CATALOG)
    overlay = generate_m15_semantic_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=catalog,
        destination=tmp_path / "overlay",
    )
    return base, catalog, overlay


@dataclass
class SemanticClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    failed_artifacts: set[str] = field(default_factory=set)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        if artifact.artifact_id in self.failed_artifacts:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="injected semantic relaxation failure",
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
        backend_id: SemanticClient(backend_id, rows[backend_id])
        for backend_id in ("neo4j", "fuseki")
    }


def test_execution_plan_binds_only_the_supported_risk_relaxation(
    tmp_path: Path,
) -> None:
    base, _, overlay = _overlay(tmp_path)

    plan, contract = build_m15_semantic_risk_execution_plan(
        overlay=overlay,
        base_bundle=base,
    )

    assert contract["changed_slot_ids"] == ["risk-level"]
    assert contract["risk_transition"] == {"from": "HIGH", "to": "MEDIUM"}
    assert contract["hard_bindings_preserved"] is True
    assert contract["oracle_inputs_to_selection"] == []
    assert contract["physical_strategy"] == FIXED_PHYSICAL_STRATEGY
    assert plan.metadata["semantic_deviation"] == 1 / 3
    assert plan.metadata["semantic_class_id"] == contract["semantic_class_id"]
    assert plan.metadata["physical_selection_mode"] == "fixed_mechanism_gate"
    assert plan.metadata["answer_oracle_used_for_selection"] is False


def test_live_semantic_relaxation_executes_one_plan_and_exact_oracle(
    tmp_path: Path,
) -> None:
    base, catalog, overlay = _overlay(tmp_path)

    record = run_m15_live_semantic_risk_relaxation(
        semantic_overlay=overlay,
        base_bundle=base,
        catalog=catalog,
        clients=_clients(overlay.workload_bundle),
        output_root=tmp_path / "runs",
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    result = json.loads(record.result_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    query_id = manifest["execution_contract"]["query_id"]
    oracle = load_m15_parameterized_instance(
        overlay.workload_bundle,
        query_id,
    )["final_oracle"]
    assert manifest["validation"]["passed"] is True
    assert manifest["summary"] == {
        "semantic_class_count": 1,
        "semantic_deviation": 1 / 3,
        "physical_plan_run_count": 1,
        "total_remote_calls": 2,
        "total_bytes_moved": manifest["summary"]["total_bytes_moved"],
        "final_row_count": 11,
    }
    assert result["final_rows"] == oracle
    assert {row["risk"] for row in result["final_rows"]} == {"MEDIUM"}
    assert invocations["total_tool_invocations"] == 2
    assert [event["backend_id"] for event in invocations["events"]] == [
        "fuseki",
        "neo4j",
    ]
    assert manifest["answer_oracle_used_for_plan_construction_or_selection"] is False
    assert manifest["answer_oracle_used_for_post_execution_validation"] is True
    assert manifest["physical_strategy_comparison_enabled"] is False
    assert manifest["automatic_retries"] == 0
    assert manifest["paper_result"] is False


def test_live_semantic_relaxation_fails_closed_without_retry(
    tmp_path: Path,
) -> None:
    base, catalog, overlay = _overlay(tmp_path)
    clients = _clients(overlay.workload_bundle)
    query_id = overlay.manifest["overlay_instances"][0]["query_id"]
    clients["fuseki"].failed_artifacts.add(
        f"m15-f2c-{query_id}-fuseki-risk"
    )

    record = run_m15_live_semantic_risk_relaxation(
        semantic_overlay=overlay,
        base_bundle=base,
        catalog=catalog,
        clients=clients,
        output_root=tmp_path / "runs",
    )

    assert not record.success
    status = json.loads(record.status_path.read_text(encoding="utf-8"))
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["status"] == "failed"
    assert manifest["status"] == "failed"
    assert manifest["automatic_retries"] == 0
    assert invocations["automatic_retries"] == 0
    assert invocations["total_tool_invocations"] == 1
