from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from xgap.experiments.m15_direct_semantic_estimates import (
    bind_m15_direct_estimate_snapshot,
    load_m15_direct_estimate_source,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticFrontierError,
    build_m15_direct_semantic_candidate_set,
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_live_direct_semantic_frontier import (
    LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION,
    prepare_m15_direct_semantic_frontier,
    run_m15_live_direct_semantic_frontier,
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
ESTIMATE_SOURCE = (
    REPO_ROOT / "experiments/configs/m15_f2c9_direct_frontier_estimates_dev.json"
)
BASE_QUERY_ID = "financial-risk-alice-aug-high-v2"


def _overlay(tmp_path: Path):
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "base",
    )
    overlay = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        destination=tmp_path / "overlay",
    )
    return base, overlay


@dataclass
class FrontierOracleClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    failed_artifacts: set[str] = field(default_factory=set)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "frontier fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        if artifact.artifact_id in self.failed_artifacts:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                rows=[],
                elapsed_ms=1.0,
                error="injected frontier failure",
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


def _clients(bundle) -> dict[str, FrontierOracleClient]:
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    for query_id in bundle.instance_ids():
        sources = load_m15_parameterized_instance(bundle, query_id)[
            "source_oracles"
        ]
        prefix = f"m15-f2c-{query_id}"
        rows["neo4j"][f"{prefix}-neo4j-full"] = sources["neo4j_full"]
        rows["neo4j"][f"{prefix}-neo4j-bound"] = sources["neo4j_full"]
        rows["fuseki"][f"{prefix}-fuseki-risk"] = sources["fuseki_risk"]
    return {
        backend_id: FrontierOracleClient(backend_id, rows[backend_id])
        for backend_id in ("neo4j", "fuseki")
    }


def test_estimate_source_binds_the_sealed_controlled_frontier(
    tmp_path: Path,
) -> None:
    base, overlay = _overlay(tmp_path)
    candidates = build_m15_direct_semantic_candidate_set(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
    )
    source = load_m15_direct_estimate_source(ESTIMATE_SOURCE)
    snapshot = bind_m15_direct_estimate_snapshot(candidates, source)
    frontier = select_m15_direct_semantic_frontier(
        candidates,
        snapshot,
    ).to_dict()

    assert len(source.to_dict()["records"]) == 8
    assert snapshot.to_dict()["evidence_id"] == source.to_dict()["evidence_id"]
    assert frontier["counts"]["returned_semantic_plans"] == 3
    assert [
        item["changed_slot_ids"]
        for item in frontier["returned_semantic_plans"]
    ] == [[], ["risk-level", "transfer-predicate"], ["risk-level"]]


def test_estimate_source_rejects_duplicate_identity(tmp_path: Path) -> None:
    raw = json.loads(ESTIMATE_SOURCE.read_text(encoding="utf-8"))
    raw["records"][-1]["changed_slot_ids"] = []
    path = tmp_path / "bad-estimates.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(M15DirectSemanticFrontierError, match="cover each"):
        load_m15_direct_estimate_source(path)


def test_live_direct_frontier_executes_only_returned_plans(
    tmp_path: Path,
) -> None:
    base, overlay = _overlay(tmp_path)
    prepared = prepare_m15_direct_semantic_frontier(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        estimate_source=ESTIMATE_SOURCE,
    )
    record = run_m15_live_direct_semantic_frontier(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        estimate_source=ESTIMATE_SOURCE,
        clients=_clients(overlay.workload_bundle),
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
        prepared_frontier=prepared,
    )

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    results = json.loads(record.result_path.read_text(encoding="utf-8"))[
        "results"
    ]
    frontier = json.loads(
        (record.run_root / "semantic_frontier.json").read_text(encoding="utf-8")
    )
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["schema_version"] == (
        LIVE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION
    )
    assert manifest["validation"]["passed"] is True
    assert manifest["summary"] == {
        "declared_semantic_class_count": 12,
        "executable_direct_semantic_class_count": 4,
        "unavailable_multihop_semantic_class_count": 8,
        "physical_candidate_count": 8,
        "physical_representative_count": 4,
        "pareto_semantic_plan_count": 4,
        "epsilon_frontier_semantic_plan_count": 3,
        "returned_semantic_plan_count": 3,
        "physical_plan_run_count": 3,
        "total_remote_calls": 6,
        "total_bytes_moved": sum(
            item["runtime_result"]["total_bytes_moved"] for item in results
        ),
        "final_row_counts": [11, 9, 11],
    }
    assert all(item["exact_oracle_answer"] for item in results)
    assert [item["plan_id"] for item in results] == [
        item["plan_id"] for item in frontier["returned_semantic_plans"]
    ]
    assert invocations["total_tool_invocations"] == 6
    assert [item["backend_id"] for item in invocations["events"]] == [
        "fuseki",
        "neo4j",
        "fuseki",
        "neo4j",
        "fuseki",
        "neo4j",
    ]
    assert manifest["selection_sealed_before_oracle_access"] is True
    assert manifest["answer_oracle_used_for_selection"] is False
    assert manifest["answer_oracle_used_for_post_execution_validation"] is True
    assert manifest["costs_are_controlled_predictions_not_observations"] is True
    assert manifest["blocked_multihop_classes_executed"] is False
    assert manifest["automatic_retries"] == 0
    assert manifest["paper_result"] is False


def test_live_direct_frontier_stops_after_first_failure(tmp_path: Path) -> None:
    base, overlay = _overlay(tmp_path)
    candidates = build_m15_direct_semantic_candidate_set(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
    )
    source = load_m15_direct_estimate_source(ESTIMATE_SOURCE)
    snapshot = bind_m15_direct_estimate_snapshot(candidates, source)
    first = select_m15_direct_semantic_frontier(
        candidates,
        snapshot,
    ).to_dict()["returned_semantic_plans"][0]
    first_plan = candidates.plans[first["plan_id"]]
    first_artifact = next(
        node.parameters["artifact"]["artifact_id"]
        for node in first_plan.nodes
        if node.parameters.get("backend_id") == "fuseki"
    )
    clients = _clients(overlay.workload_bundle)
    clients["fuseki"].failed_artifacts.add(first_artifact)

    record = run_m15_live_direct_semantic_frontier(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        estimate_source=ESTIMATE_SOURCE,
        clients=clients,
        output_root=tmp_path / "failed-runs",
        repo_root=REPO_ROOT,
    )

    assert not record.success
    payload = json.loads(record.result_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(payload["results"]) == 1
    assert payload["results"][0]["runtime_result"]["success"] is False
    assert invocations["total_tool_invocations"] == 1
    assert invocations["automatic_retries"] == 0
    assert not (record.run_root / "validation.json").exists()
