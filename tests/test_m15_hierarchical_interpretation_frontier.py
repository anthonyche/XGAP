from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    M15DirectFamilyPredictionError,
    M15DirectTrainingMemoryView,
    build_m15_controlled_training_observations,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_hierarchical_interpretation_frontier import (
    HIERARCHICAL_INTERPRETATION_FRONTIER_SCHEMA_VERSION,
    M15HierarchicalInterpretationFrontierError,
    select_m15_hierarchical_interpretation_frontier,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_resolution_execution_bridge import (
    _resolution_commit_hash,
    compile_m15_resolution_execution_bridge,
)
from xgap.experiments.m15_semantic_intake import run_semantic_intake


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SPEC = REPO_ROOT / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
QUERY_TEMPLATE = REPO_ROOT / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
SEMANTIC_CATALOG = REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
PREDICATE_MAPPING = REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
CARDINALITY_POLICY = REPO_ROOT / "experiments/configs/m15_f2c10_direct_semantic_workload_dev.json"
PREDICTOR_POLICY = REPO_ROOT / "experiments/configs/m15_f2c10_family_memory_predictor_dev.json"
INTERPRETATION_POLICY = REPO_ROOT / "experiments/configs/m15_e5_hierarchical_interpretation_policy_dev.json"
BRIDGE_SPEC = REPO_ROOT / "experiments/configs/m15_e4_resolution_execution_bridge_dev.json"
RUNTIME_HASH = content_hash(
    {
        "runtime": "e5-local-controlled-runtime",
        "neo4j": "controlled",
        "fuseki": "controlled",
    }
)


def _resolution() -> dict[str, object]:
    return run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=REPO_ROOT / "experiments/configs/m15_e3_financial_risk_intake_dev.json",
        catalog_path=REPO_ROOT / "experiments/specs/m15_e3_financial_risk_catalog_dev.json",
        ontology_path=REPO_ROOT / "experiments/specs/m15_e3_financial_risk_ontology_dev.json",
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="explicit-e5-test-selection",
    )


def _bridge(resolution: dict[str, object] | None = None):
    spec = json.loads(BRIDGE_SPEC.read_text(encoding="utf-8"))
    return compile_m15_resolution_execution_bridge(
        resolution or _resolution(),
        spec,
        repo_root=REPO_ROOT,
        bridge_spec_sha256=hashlib.sha256(BRIDGE_SPEC.read_bytes()).hexdigest(),
    )


@pytest.fixture(scope="module")
def e5_context(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("m15-e5")
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=root / "base",
    )
    direct = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        policy=CARDINALITY_POLICY,
        destination=root / "direct",
    )
    controlled = build_m15_controlled_training_observations(direct)
    memory = build_m15_direct_training_memory_view(
        workload=direct,
        raw_observations=controlled["observations"],
        runtime_compatibility_sha256=RUNTIME_HASH,
        policy=PREDICTOR_POLICY,
        measurement_source_kind="controlled_local_nonmeasurement_fixture",
    )
    return direct, memory, _bridge()


def _select(e5_context, **kwargs):
    direct, memory, bridge = e5_context
    return select_m15_hierarchical_interpretation_frontier(
        bridge=kwargs.pop("bridge", bridge),
        workload=direct,
        memory=kwargs.pop("memory", memory),
        predictor_policy=kwargs.pop("predictor_policy", PREDICTOR_POLICY),
        interpretation_policy=kwargs.pop(
            "interpretation_policy", INTERPRETATION_POLICY
        ),
        **kwargs,
    )


def test_r1_requires_relationship_structure_clarification(e5_context) -> None:
    payload = _select(e5_context).to_dict()

    assert payload["schema_version"] == HIERARCHICAL_INTERPRETATION_FRONTIER_SCHEMA_VERSION
    assert payload["status"] == "clarification_required"
    assert payload["clarification_required"] is True
    assert payload["execution_eligible"] is False
    assert payload["returned_interpretation_plans"] == []
    assert payload["counts"] == {
        "interpretation_classes": 6,
        "executable_interpretation_classes": 2,
        "unavailable_interpretation_classes": 4,
        "physical_candidates": 4,
        "family_cost_predictions": 4,
        "physical_representatives": 2,
        "clarification_requests": 1,
        "returned_interpretation_plans": 0,
        "anchored_relaxation_frontiers": 0,
    }
    request = payload["clarification_requests"][0]
    assert request["hole_id"] == "relationship-strength"
    assert [item["candidate_id"] for item in request["options"]] == [
        "constraint:single-transfer-at-least-50000",
        "constraint:amount-at-least-50000",
        "constraint:frequency-at-least-3",
    ]
    assert "单笔" in request["question"]
    assert "累计" in request["question"]
    assert "频率" in request["question"]
    assert request["varying_structural_dimensions"] == [
        "aggregation_operator",
        "quantification",
        "answer_meaning",
        "output_contract",
        "executable_capability",
    ]
    assert all(
        item["semantic_deviation"] is None
        and item["relaxation_base_id"] is None
        for item in payload["all_interpretation_classes"]
    )


def test_family_memory_reduces_only_within_each_executable_interpretation(
    e5_context,
) -> None:
    payload = _select(e5_context).to_dict()
    source = payload["family_cost_prediction_source"]
    predictions = {item["target_id"]: item for item in source["predictions"]}

    assert source["prediction_count"] == 4
    assert len(source["targets"]) == 4
    assert content_hash(source["targets"]) == source["target_set_sha256"]
    assert source["current_query_observation_operations"] == []
    assert source["backend_calls_made"] == 0
    assert source["oracle_inputs"] == []
    for interpretation in payload["all_interpretation_classes"]:
        plan_ids = interpretation["physical_candidate_ids"]
        if not plan_ids:
            assert interpretation["physical_representative"] is None
            continue
        expected = min(
            (predictions[plan_id] for plan_id in plan_ids),
            key=lambda item: (
                item["estimated_latency_ms"],
                item["estimated_total_bytes_moved"],
                item["target_id"],
            ),
        )
        assert interpretation["physical_representative"]["plan_id"] == expected[
            "target_id"
        ]


def test_authoritative_single_transfer_returns_two_predicate_representatives(
    e5_context,
) -> None:
    payload = _select(
        e5_context,
        authoritative_selections={
            "relationship-strength": "constraint:single-transfer-at-least-50000"
        },
        authority_source_id="explicit-e5-test-clarification",
    ).to_dict()

    assert payload["status"] == "ready_with_bounded_representatives"
    assert payload["clarification_required"] is False
    assert payload["execution_eligible"] is True
    assert len(payload["returned_interpretation_plans"]) == 2
    assert {
        item["selected_candidate_ids"]["transfer-predicate"]
        for item in payload["returned_interpretation_plans"]
    } == {"predicate:transferred_to", "predicate:paid_to"}
    assert all(
        item["selected_candidate_ids"]["relationship-strength"]
        == "constraint:single-transfer-at-least-50000"
        and item["semantic_deviation"] is None
        and item["physical_representative"] is not None
        for item in payload["returned_interpretation_plans"]
    )
    assert payload["counts"]["interpretation_classes"] == 6
    assert payload["counts"]["unavailable_interpretation_classes"] == 4


@pytest.mark.parametrize(
    "candidate_id",
    [
        "constraint:amount-at-least-50000",
        "constraint:frequency-at-least-3",
    ],
)
def test_authoritatively_selected_unavailable_structure_stays_visible(
    e5_context,
    candidate_id: str,
) -> None:
    payload = _select(
        e5_context,
        authoritative_selections={"relationship-strength": candidate_id},
        authority_source_id="explicit-e5-test-unavailable-selection",
    ).to_dict()

    assert payload["status"] == "authoritatively_selected_structure_unavailable"
    assert payload["clarification_required"] is False
    assert payload["execution_eligible"] is False
    assert payload["returned_interpretation_plans"] == []
    active = {
        item["interpretation_class_id"]: item
        for item in payload["all_interpretation_classes"]
        if item["interpretation_class_id"]
        in payload["active_interpretation_class_ids"]
    }
    assert len(active) == 2
    assert all(item["availability"] == "unavailable" for item in active.values())


def test_non_authoritative_subset_cannot_create_semantic_authority(e5_context) -> None:
    payload = _select(
        e5_context,
        non_authoritative_candidate_subset={
            "relationship-strength": [
                "constraint:single-transfer-at-least-50000"
            ]
        },
    ).to_dict()

    assert payload["clarification_required"] is True
    assert payload["authoritative_structural_selections"] == {}
    assert payload["non_authoritative_subset_used_for_authority"] is False
    assert payload["returned_interpretation_plans"] == []
    assert all(
        item["semantic_deviation"] is None
        for item in payload["all_interpretation_classes"]
    )


def test_candidate_order_does_not_change_authority_or_returned_identities(
    e5_context,
) -> None:
    reordered = copy.deepcopy(_resolution())
    output = reordered["goal_state"]["output"]
    output["candidate_sets"].reverse()
    for candidate_set in output["candidate_sets"]:
        candidate_set["candidate_ids"].reverse()
    output["resolution_commit_sha256"] = _resolution_commit_hash(output)

    first = _select(
        e5_context,
        authoritative_selections={
            "relationship-strength": "constraint:single-transfer-at-least-50000"
        },
        authority_source_id="explicit-e5-order-test",
    ).to_dict()
    second = _select(
        e5_context,
        bridge=_bridge(reordered),
        authoritative_selections={
            "relationship-strength": "constraint:single-transfer-at-least-50000"
        },
        authority_source_id="explicit-e5-order-test",
    ).to_dict()

    assert first["authoritative_structural_selections"] == second[
        "authoritative_structural_selections"
    ]
    assert [
        item["interpretation_class_id"]
        for item in first["returned_interpretation_plans"]
    ] == [
        item["interpretation_class_id"]
        for item in second["returned_interpretation_plans"]
    ]


def test_entity_or_out_of_set_authority_fails_closed(e5_context) -> None:
    with pytest.raises(
        M15HierarchicalInterpretationFrontierError,
        match="only R1 structural holes",
    ):
        _select(
            e5_context,
            authoritative_selections={"person-identity": "person:alice-smith"},
            authority_source_id="invalid-e5-entity-selection",
        )
    with pytest.raises(
        M15HierarchicalInterpretationFrontierError,
        match="outside the sealed E4 set",
    ):
        _select(
            e5_context,
            authoritative_selections={"relationship-strength": "constraint:other"},
            authority_source_id="invalid-e5-out-of-set-selection",
        )


def test_memory_and_policy_tampering_fail_closed(e5_context) -> None:
    _, memory, _ = e5_context
    tampered_memory = copy.deepcopy(memory.to_dict())
    tampered_memory["observations"][0]["median_elapsed_ms"] += 1.0
    with pytest.raises(M15DirectFamilyPredictionError, match="hash mismatch"):
        _select(e5_context, memory=M15DirectTrainingMemoryView(tampered_memory))

    tampered_policy = json.loads(INTERPRETATION_POLICY.read_text(encoding="utf-8"))
    tampered_policy["clarification_rule"][
        "execution_when_structurally_unresolved"
    ] = True
    with pytest.raises(
        M15HierarchicalInterpretationFrontierError,
        match="no longer implements R1",
    ):
        _select(e5_context, interpretation_policy=tampered_policy)


def test_portable_output_preserves_zero_call_and_claim_boundaries(e5_context) -> None:
    payload = _select(e5_context).to_dict()
    boundary = payload["claim_boundary"]

    assert boundary == {
        "artifact_class": "offline_hierarchical_interpretation_mechanism",
        "development_artifacts_only": True,
        "hard_constraints_preserved": True,
        "all_bounded_interpretations_preserved": True,
        "unavailable_interpretations_preserved": True,
        "answer_oracle_used_for_selection": False,
        "post_execution_measurements_used": False,
        "current_query_profile_calls": 0,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "native_query_text_emitted": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    assert payload["relaxation_frontiers"] == []
    assert payload["paper_result"] is False
    serialized = json.dumps(payload, sort_keys=True)
    assert " MATCH " not in serialized
    assert "SELECT " not in serialized
