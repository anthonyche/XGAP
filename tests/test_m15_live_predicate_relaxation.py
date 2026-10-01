from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from xgap.experiments.m15_live_predicate_relaxation import (
    build_m15_semantic_predicate_execution_plans,
    run_m15_live_semantic_predicate_relaxation,
)
from xgap.experiments.m15_live_semantic_relaxation import (
    FIXED_PHYSICAL_STRATEGY,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    generate_m15_predicate_overlay_bundle,
)
from xgap.experiments.m15_semantic_frontier import (
    load_m15_semantic_relaxation_catalog,
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
PREDICATE_MAPPING = (
    REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
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
    overlay = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=catalog,
        mapping=PREDICATE_MAPPING,
        destination=tmp_path / "predicate-overlay",
    )
    return base, catalog, overlay


@dataclass
class PredicateClient:
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
                error="injected predicate relaxation failure",
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
        backend_id: PredicateClient(backend_id, rows[backend_id])
        for backend_id in ("neo4j", "fuseki")
    }


def test_predicate_plans_bind_only_two_supported_direct_classes(
    tmp_path: Path,
) -> None:
    base, _, overlay = _overlay(tmp_path)

    built = build_m15_semantic_predicate_execution_plans(
        overlay=overlay,
        base_bundle=base,
    )

    assert len(built) == 2
    contracts = [contract for _, contract in built]
    assert {tuple(item["changed_slot_ids"]) for item in contracts} == {
        ("transfer-predicate",),
        ("risk-level", "transfer-predicate"),
    }
    assert [item["risk_transition"] for item in contracts] == [
        {"from": "HIGH", "to": "HIGH"},
        {"from": "HIGH", "to": "MEDIUM"},
    ]
    for plan, contract in built:
        assert contract["hard_bindings_preserved"] is True
        assert contract["path_shape"] == "direct"
        assert contract["predicate_transition"] == {
            "transition_id": "transfer-to-payment-sibling",
            "from": "transfer_to_company",
            "to": "payment_to_company",
            "transformation": "ontology_sibling",
            "evidence": {
                "kind": "development_mapping_fixture",
                "reference": "financial-relation-siblings-v1",
            },
            "backend_id": "neo4j",
            "relationship_type": "PAYMENT_TO_COMPANY",
        }
        assert contract["physical_strategy"] == FIXED_PHYSICAL_STRATEGY
        assert contract["oracle_inputs_to_selection"] == []
        assert plan.metadata["answer_oracle_used_for_selection"] is False
        assert "expected_result" not in json.dumps(
            [node.to_dict() for node in plan.nodes]
        ).lower()


def test_live_predicate_relaxation_runs_two_exact_plans(
    tmp_path: Path,
) -> None:
    base, catalog, overlay = _overlay(tmp_path)

    record = run_m15_live_semantic_predicate_relaxation(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=catalog,
        mapping=PREDICATE_MAPPING,
        clients=_clients(overlay.workload_bundle),
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    payload = json.loads(record.result_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["validation"]["passed"] is True
    assert manifest["summary"]["semantic_class_count"] == 2
    assert manifest["summary"]["physical_plan_run_count"] == 2
    assert manifest["summary"]["total_remote_calls"] == 4
    assert manifest["summary"]["final_row_counts"] == [6, 9]
    assert [item["expected_final_row_count"] for item in payload["results"]] == [
        6,
        9,
    ]
    assert all(item["exact_oracle_answer"] for item in payload["results"])
    assert invocations["total_tool_invocations"] == 4
    assert [event["backend_id"] for event in invocations["events"]] == [
        "fuseki",
        "neo4j",
        "fuseki",
        "neo4j",
    ]
    assert manifest["answer_oracle_used_for_plan_construction_or_selection"] is False
    assert manifest["answer_oracle_used_for_post_execution_validation"] is True
    assert manifest["physical_strategy_comparison_enabled"] is False
    assert manifest["memory_enabled"] is False
    assert manifest["llm_calls_made"] == 0
    assert manifest["ontology_calls_made"] == 0
    assert manifest["automatic_retries"] == 0
    assert manifest["paper_result"] is False


def test_live_predicate_relaxation_fails_closed_without_retry(
    tmp_path: Path,
) -> None:
    base, catalog, overlay = _overlay(tmp_path)
    clients = _clients(overlay.workload_bundle)
    first_query_id = sorted(
        item["query_id"]
        for item in overlay.manifest["overlay_instances"]
        if "transfer-predicate" in item["changed_slot_ids"]
    )[0]
    clients["fuseki"].failed_artifacts.add(
        f"m15-f2c-{first_query_id}-fuseki-risk"
    )

    record = run_m15_live_semantic_predicate_relaxation(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=catalog,
        mapping=PREDICATE_MAPPING,
        clients=clients,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
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
