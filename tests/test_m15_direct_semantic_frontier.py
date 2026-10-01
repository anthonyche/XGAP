from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticCandidateSet,
    M15DirectSemanticFrontierError,
    M15PreexecutionEstimateSnapshot,
    build_m15_direct_semantic_candidate_set,
    build_m15_preexecution_estimate_snapshot,
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_predicate_overlay import (
    generate_m15_predicate_overlay_bundle,
)


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


def _candidate_set(tmp_path: Path, name: str = "frontier"):
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / f"{name}-base",
    )
    overlay = generate_m15_predicate_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        destination=tmp_path / f"{name}-overlay",
    )
    candidates = build_m15_direct_semantic_candidate_set(
        predicate_overlay=overlay,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
    )
    return base, overlay, candidates


def _controlled_estimates(
    candidates: M15DirectSemanticCandidateSet,
) -> list[dict[str, object]]:
    payload = candidates.to_dict()
    changed_by_class = {
        item["semantic_class_id"]: tuple(item["changed_slot_ids"])
        for item in payload["semantic_classes"]
    }
    class_costs = {
        (): (100.0, 100.0),
        ("risk-level",): (90.0, 120.0),
        ("transfer-predicate",): (96.0, 97.0),
        ("risk-level", "transfer-predicate"): (60.0, 70.0),
    }
    estimates: list[dict[str, object]] = []
    for item in payload["physical_candidates"]:
        latency, resource = class_costs[
            changed_by_class[item["semantic_class_id"]]
        ]
        penalty = (
            0.0
            if item["physical_strategy"] == "risk_first_bind_join"
            else 10.0
        )
        estimates.append(
            {
                "plan_id": item["plan_id"],
                "estimated_latency_ms": latency + penalty,
                "estimated_resource_cost_units": resource + penalty,
            }
        )
    return estimates


def _snapshot(
    candidates: M15DirectSemanticCandidateSet,
    estimates: list[dict[str, object]] | None = None,
) -> M15PreexecutionEstimateSnapshot:
    return build_m15_preexecution_estimate_snapshot(
        candidates,
        estimates if estimates is not None else _controlled_estimates(candidates),
        evidence_kind="controlled_preexecution_fixture",
        evidence_id="m15-f2c9-controlled-estimates-v1",
    )


def _rehash(payload: dict[str, object], hash_field: str) -> None:
    body = {key: value for key, value in payload.items() if key != hash_field}
    payload[hash_field] = content_hash(body)


def test_candidate_set_exposes_capability_partition_without_oracle(
    tmp_path: Path,
) -> None:
    _, _, candidates = _candidate_set(tmp_path)
    payload = candidates.to_dict()

    assert payload["counts"] == {
        "declared_semantic_classes": 12,
        "executable_direct_semantic_classes": 4,
        "unavailable_semantic_classes": 8,
        "physical_candidates": 8,
        "physical_candidates_per_class": 2,
    }
    assert len(payload["semantic_classes"]) == 4
    assert len(payload["unavailable_semantic_class_ids"]) == 8
    assert len(payload["physical_candidates"]) == 8
    assert Counter(
        item["semantic_class_id"] for item in payload["physical_candidates"]
    ) == Counter(
        {
            item["semantic_class_id"]: 2
            for item in payload["semantic_classes"]
        }
    )
    assert {
        tuple(item["changed_slot_ids"]) for item in payload["semantic_classes"]
    } == {
        (),
        ("risk-level",),
        ("transfer-predicate",),
        ("risk-level", "transfer-predicate"),
    }
    assert sorted(
        item["semantic_deviation"] for item in payload["semantic_classes"]
    ) == [0.0, 1 / 3, 1 / 3, 2 / 3]
    assert all(
        item["binding_values"]["path-shape"] == "direct"
        and item["binding_values"]["person-identity"] == "person-alice-smith"
        and item["binding_values"]["time-lower-bound"] == "2026-08-01"
        and item["binding_values"]["amount-lower-bound"] == 50000
        for item in payload["semantic_classes"]
    )
    assert {
        item["physical_strategy"] for item in payload["physical_candidates"]
    } == {"parallel_hash_join", "risk_first_bind_join"}
    assert "final_oracle" not in json.dumps(payload, sort_keys=True)
    assert payload["claim_boundary"]["answer_oracle_used"] is False
    assert payload["claim_boundary"]["backend_calls_made"] == 0
    assert payload["paper_result"] is False


def test_frontier_reduces_physical_then_pareto_epsilon_and_k(
    tmp_path: Path,
) -> None:
    _, _, candidates = _candidate_set(tmp_path)
    frontier = select_m15_direct_semantic_frontier(
        candidates,
        _snapshot(candidates),
    ).to_dict()

    assert frontier["counts"] == {
        "declared_semantic_classes": 12,
        "executable_direct_semantic_classes": 4,
        "unavailable_semantic_classes": 8,
        "physical_candidates": 8,
        "physical_representatives": 4,
        "pareto_semantic_plans": 4,
        "epsilon_frontier_semantic_plans": 3,
        "returned_semantic_plans": 3,
    }
    assert len(frontier["epsilon_removed"]) == 1
    removed_id = frontier["epsilon_removed"][0]["semantic_class_id"]
    class_by_id = {
        item["semantic_class_id"]: item
        for item in candidates.to_dict()["semantic_classes"]
    }
    assert class_by_id[removed_id]["changed_slot_ids"] == [
        "transfer-predicate"
    ]
    assert frontier["returned_semantic_plans"][0]["semantic_deviation"] == 0
    assert len(
        {
            item["semantic_class_id"]
            for item in frontier["returned_semantic_plans"]
        }
    ) == 3
    assert len(frontier["returned_physical_plans"]) == 3
    assert all(
        item["metadata"]["semantic_class_id"]
        == selected["semantic_class_id"]
        for item, selected in zip(
            frontier["returned_physical_plans"],
            frontier["returned_semantic_plans"],
            strict=True,
        )
    )
    assert frontier["claim_boundary"] == {
        "artifact_class": "preexecution_estimated_direct_semantic_frontier",
        "costs_are_predictions_not_observed_execution": True,
        "answer_oracle_used": False,
        "exact_semantics_retained": True,
        "blocked_multihop_classes_returned": False,
        "backend_calls_made_by_selector": 0,
        "llm_calls_made": 0,
        "ontology_calls_made": 0,
        "semantic_user_utility_validated": False,
        "performance_superiority_validated": False,
        "paper_result": False,
    }
    assert frontier["paper_result"] is False


def test_preexecution_estimates_can_flip_one_physical_representative(
    tmp_path: Path,
) -> None:
    _, _, candidates = _candidate_set(tmp_path)
    first_estimates = _controlled_estimates(candidates)
    first = select_m15_direct_semantic_frontier(
        candidates,
        _snapshot(candidates, first_estimates),
    ).to_dict()
    target_class = next(
        item["semantic_class_id"]
        for item in candidates.to_dict()["semantic_classes"]
        if item["changed_slot_ids"] == ["risk-level"]
    )
    target_plan_ids = [
        item["plan_id"]
        for item in candidates.to_dict()["physical_candidates"]
        if item["semantic_class_id"] == target_class
    ]
    second_estimates = copy.deepcopy(first_estimates)
    target_records = [
        item for item in second_estimates if item["plan_id"] in target_plan_ids
    ]
    target_records[0]["estimated_latency_ms"] = 1.0
    target_records[0]["estimated_resource_cost_units"] = 1.0
    target_records[1]["estimated_latency_ms"] = 1000.0
    target_records[1]["estimated_resource_cost_units"] = 1000.0
    second = select_m15_direct_semantic_frontier(
        candidates,
        _snapshot(candidates, second_estimates),
    ).to_dict()

    def selected_plan(frontier: dict[str, object]) -> str:
        return next(
            item["plan_id"]
            for item in frontier["physical_representatives"]  # type: ignore[index]
            if item["semantic_class_id"] == target_class
        )

    assert selected_plan(first) != selected_plan(second)
    assert first["counts"]["physical_representatives"] == 4
    assert second["counts"]["physical_representatives"] == 4


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "exactly every physical candidate"),
        ("duplicate", "not unique"),
        ("unknown", "exactly every physical candidate"),
        ("oracle_field", "fields do not match"),
    ],
)
def test_estimate_builder_rejects_incomplete_or_leaky_inputs(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    _, _, candidates = _candidate_set(tmp_path)
    estimates = _controlled_estimates(candidates)
    if mutation == "missing":
        estimates.pop()
    elif mutation == "duplicate":
        estimates[-1]["plan_id"] = estimates[0]["plan_id"]
    elif mutation == "unknown":
        estimates[-1]["plan_id"] = "unknown-plan"
    else:
        estimates[0]["answer_oracle"] = []

    with pytest.raises(M15DirectSemanticFrontierError, match=message):
        _snapshot(candidates, estimates)


def test_snapshot_rejects_postexecution_kind_and_tamper(tmp_path: Path) -> None:
    _, _, candidates = _candidate_set(tmp_path)
    estimates = _controlled_estimates(candidates)
    with pytest.raises(M15DirectSemanticFrontierError, match="not admitted"):
        build_m15_preexecution_estimate_snapshot(
            candidates,
            estimates,
            evidence_kind="observed_execution_measurement",
            evidence_id="forbidden-observation",
        )

    valid = _snapshot(candidates)
    tampered_payload = valid.to_dict()
    tampered_payload["post_execution_measurements_used"] = True
    _rehash(tampered_payload, "estimate_snapshot_sha256")
    tampered = M15PreexecutionEstimateSnapshot(tampered_payload)
    with pytest.raises(M15DirectSemanticFrontierError, match="post-execution"):
        select_m15_direct_semantic_frontier(candidates, tampered)

    broken_hash_payload = valid.to_dict()
    broken_hash_payload["evidence_id"] = "changed-after-seal"
    broken_hash = M15PreexecutionEstimateSnapshot(broken_hash_payload)
    with pytest.raises(M15DirectSemanticFrontierError, match="hash mismatch"):
        select_m15_direct_semantic_frontier(candidates, broken_hash)


def test_candidate_set_rejects_runtime_plan_drift(tmp_path: Path) -> None:
    _, _, candidates = _candidate_set(tmp_path)
    payload = candidates.to_dict()
    payload["physical_candidates"][0]["plan"]["plan_id"] = "tampered-plan"
    _rehash(payload, "candidate_set_sha256")
    tampered = M15DirectSemanticCandidateSet(payload, candidates.plans)

    with pytest.raises(M15DirectSemanticFrontierError, match="runtime plan differ"):
        _snapshot(tampered)


def test_candidate_and_snapshot_hashes_are_deterministic(tmp_path: Path) -> None:
    _, _, first = _candidate_set(tmp_path, "first")
    _, _, second = _candidate_set(tmp_path, "second")
    first_snapshot = _snapshot(first)
    second_snapshot = _snapshot(second)

    assert first.to_dict() == second.to_dict()
    assert first.candidate_set_hash == second.candidate_set_hash
    assert first_snapshot.to_dict() == second_snapshot.to_dict()
    assert first_snapshot.snapshot_hash == second_snapshot.snapshot_hash
