from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.experiments.m15_resolution_execution_bridge import (
    M15ResolutionExecutionBridgeError,
    _resolution_commit_hash,
    compile_m15_resolution_execution_bridge,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_intake import run_semantic_intake
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import FederatedScheduler
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SPEC = (
    REPO_ROOT / "experiments/configs/m15_e4_resolution_execution_bridge_dev.json"
)


@dataclass
class _BridgeBundleClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "bridge fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        rows = [dict(item) for item in self.rows_by_artifact[artifact.artifact_id]]
        occurred_on_lt = artifact.parameters.get("occurred_on_lt")
        if self.backend_id == "neo4j" and isinstance(occurred_on_lt, str):
            rows = [
                item
                for item in rows
                if str(item["occurred_on"]) < occurred_on_lt
            ]
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


def _spec() -> dict[str, object]:
    return json.loads(BRIDGE_SPEC.read_text(encoding="utf-8"))


def _resolution() -> dict[str, object]:
    return run_semantic_intake(
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
        user_source_id="explicit-e4-test-selection",
    )


def _compile(
    resolution: dict[str, object] | None = None,
    spec: dict[str, object] | None = None,
):
    return compile_m15_resolution_execution_bridge(
        resolution or _resolution(),
        spec or _spec(),
        repo_root=REPO_ROOT,
        bridge_spec_sha256=hashlib.sha256(BRIDGE_SPEC.read_bytes()).hexdigest(),
    )


def test_bridge_preserves_all_six_interpretations_and_exposes_gaps() -> None:
    plan = _compile()
    payload = plan.to_dict()

    assert payload["counts"] == {
        "raw_interpretations": 6,
        "semantic_equivalence_classes": 6,
        "executable_semantic_classes": 2,
        "unavailable_semantic_classes": 4,
        "physical_candidates": 4,
    }
    assert len(plan.plans) == 4
    assert {
        tuple(item["missing_capability_ids"])
        for item in payload["semantic_classes"]
    } == {
        (),
        ("relationship.window-total-amount-lower-bound",),
        ("relationship.window-transfer-count-lower-bound",),
    }
    unavailable = [
        item
        for item in payload["semantic_classes"]
        if item["availability"] == "unavailable"
    ]
    executable = [
        item
        for item in payload["semantic_classes"]
        if item["availability"] == "executable"
    ]
    assert len(unavailable) == 4
    assert len(executable) == 2
    assert all(
        item["availability"] == "unavailable"
        and item["physical_candidate_ids"] == []
        and item["unavailable_reasons"]
        for item in unavailable
    )
    assert all(len(item["physical_candidate_ids"]) == 2 for item in executable)


def test_bridge_does_not_mislabel_edge_filter_as_window_aggregate() -> None:
    payload = _compile().to_dict()
    capabilities = {
        item["capability_id"]
        for item in payload["executable_family"]["available_capabilities"]
    }

    assert "relationship.edge-amount-lower-bound" in capabilities
    assert "relationship.window-total-amount-lower-bound" not in capabilities
    assert "time.lower-inclusive" in capabilities
    assert "time.upper-exclusive" in capabilities


def test_executable_plans_use_hash_bound_window_templates() -> None:
    plan = _compile()
    payload = plan.to_dict()

    assert len(payload["physical_candidates"]) == 4
    for physical in payload["physical_candidates"]:
        assert physical["physical_strategy"] in {
            "parallel_hash_join",
            "risk_first_bind_join",
        }
        assert any(
            role in physical["registered_template_roles"]
            for role in {
                "neo4j_full_window_template",
                "neo4j_bound_window_template",
            }
        )
        runtime_plan = plan.plans[physical["plan_id"]]
        neo4j_nodes = [
            node
            for node in runtime_plan.nodes
            if node.parameters.get("backend_id") == "neo4j"
        ]
        assert len(neo4j_nodes) == 1
        artifact = neo4j_nodes[0].parameters["artifact"]
        assert "edge.occurred_on < date($occurred_on_lt)" in artifact["text"]
        assert artifact["parameters"]["occurred_on_lt"] == "2026-09-01"
        assert runtime_plan.metadata["answer_oracle_used_for_construction"] is False


def test_every_executable_bridge_plan_runs_to_the_exact_fixture_answer(
    tmp_path: Path,
) -> None:
    bridge = _compile()
    registry = _spec()["source_artifacts"]["executable_family_registry"]
    registry_payload = json.loads(
        (REPO_ROOT / registry["path"]).read_text(encoding="utf-8")
    )
    sources = registry_payload["families"][0]["sources"]
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=REPO_ROOT / sources["workload_spec"]["path"],
        query_template_spec=REPO_ROOT / sources["query_template"]["path"],
        backend_template_root=(
            REPO_ROOT / sources["neo4j_full_template"]["path"]
        ).parent,
        destination=tmp_path / "base",
    )
    direct = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=REPO_ROOT / sources["semantic_catalog"]["path"],
        mapping=REPO_ROOT / sources["predicate_mapping"]["path"],
        policy=REPO_ROOT / sources["semantic_workload_policy"]["path"],
        destination=tmp_path / "direct",
    )
    query_ids = {
        item["query_id"] for item in bridge.to_dict()["physical_candidates"]
    }
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    expected: dict[str, tuple[dict[str, object], ...]] = {}
    for query_id in query_ids:
        instance = load_m15_parameterized_instance(direct.workload_bundle, query_id)
        source_rows = instance["source_oracles"]
        outside_window = {
            **source_rows["neo4j_bound"][0],
            "transfer_id": "T-OUTSIDE-E4-WINDOW",
            "occurred_on": "2026-09-01",
        }
        rows["neo4j"][f"m15-f2c-{query_id}-neo4j-full-window-e4"] = (
            [*source_rows["neo4j_full"], outside_window]
        )
        rows["neo4j"][f"m15-f2c-{query_id}-neo4j-bound-window-e4"] = (
            [*source_rows["neo4j_bound"], outside_window]
        )
        rows["fuseki"][f"m15-f2c-{query_id}-fuseki-risk"] = source_rows[
            "fuseki_risk"
        ]
        expected[query_id] = tuple(instance["final_oracle"])
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            NativeBackendPlugin(
                backend_id,
                _BridgeBundleClient(backend_id, rows[backend_id]),
            )
        )
    scheduler = FederatedScheduler(BackendInvokeTool(plugins))

    physical_by_id = {
        item["plan_id"]: item for item in bridge.to_dict()["physical_candidates"]
    }
    for plan_id, runtime_plan in bridge.plans.items():
        result = scheduler.execute(runtime_plan, goal_id="m15-e4-test")
        assert result.success
        assert result.total_remote_calls == 2
        assert result.final_rows == expected[physical_by_id[plan_id]["query_id"]]


def test_class_identity_is_independent_of_candidate_and_hole_order() -> None:
    original = _resolution()
    reordered = copy.deepcopy(original)
    output = reordered["goal_state"]["output"]
    output["candidate_sets"].reverse()
    for candidate_set in output["candidate_sets"]:
        candidate_set["candidate_ids"].reverse()
    output["resolution_commit_sha256"] = _resolution_commit_hash(output)

    first = _compile(original).to_dict()
    second = _compile(reordered).to_dict()
    assert [
        item["semantic_class_id"] for item in first["semantic_classes"]
    ] == [item["semantic_class_id"] for item in second["semantic_classes"]]
    assert first["bridge_plan_sha256"] != second["bridge_plan_sha256"]


def test_resolution_commit_and_authoritative_identity_fail_closed() -> None:
    tampered = _resolution()
    tampered["goal_state"]["output"]["resolution_commit_sha256"] = "0" * 64
    with pytest.raises(
        M15ResolutionExecutionBridgeError, match="resolution commit hash mismatch"
    ):
        _compile(tampered)

    non_authoritative = _resolution()
    entity = next(
        item
        for item in non_authoritative["goal_state"]["output"]["candidate_sets"]
        if item["hole_id"] == "person-identity"
    )
    entity["authoritative"] = False
    output = non_authoritative["goal_state"]["output"]
    output["resolution_commit_sha256"] = _resolution_commit_hash(output)
    with pytest.raises(
        M15ResolutionExecutionBridgeError, match="authoritative resolved binding"
    ):
        _compile(non_authoritative)


def test_hard_constraint_and_source_drift_fail_closed() -> None:
    tampered = _resolution()
    program = tampered["intake"]["program"]
    program["operators"][0]["constraints"][1]["expression"] = (
        "occurred_on >= 2026-08-01"
    )
    with pytest.raises(
        M15ResolutionExecutionBridgeError, match="hard constraint hash drift"
    ):
        _compile(tampered)

    spec = _spec()
    spec["source_artifacts"]["resolution_catalog"]["sha256"] = "0" * 64
    with pytest.raises(
        M15ResolutionExecutionBridgeError, match="source artifact SHA-256 mismatch"
    ):
        _compile(spec=spec)


def test_mapping_cap_and_capability_evidence_are_closed_contracts() -> None:
    missing_mapping = _spec()
    missing_mapping["candidate_mappings"].pop()
    with pytest.raises(
        M15ResolutionExecutionBridgeError, match="has no bridge mapping"
    ):
        _compile(spec=missing_mapping)

    capped = _spec()
    capped["limits"]["maximum_raw_semantic_classes"] = 3
    with pytest.raises(
        M15ResolutionExecutionBridgeError, match="cross-product exceeds"
    ):
        _compile(spec=capped)

    false_capability = _spec()
    false_capability["executable_family"]["available_capabilities"].append(
        {
            "capability_id": "relationship.window-total-amount-lower-bound",
            "evidence_kind": "hard_constraint",
            "evidence_id": "window-total-amount-lower-bound",
        }
    )
    with pytest.raises(
        M15ResolutionExecutionBridgeError,
        match="hard constraint 'window-total-amount-lower-bound' is absent",
    ):
        _compile(spec=false_capability)


def test_output_contains_no_native_query_or_oracle_payload() -> None:
    payload = _compile().to_dict()
    serialized = json.dumps(payload, sort_keys=True).lower()

    assert '"cypher"' not in serialized
    assert '"sparql"' not in serialized
    assert "expected_result" not in serialized
    assert "source_oracles" not in serialized
    assert payload["claim_boundary"] == {
        "artifact_class": "capability_checked_unexecuted_bridge_plan",
        "development_artifacts_only": True,
        "all_bounded_interpretations_preserved": True,
        "unsupported_interpretations_silently_dropped": False,
        "hard_constraints_relaxed": False,
        "answer_oracle_used_for_selection": False,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "native_query_text_emitted": False,
        "paper_result": False,
    }
