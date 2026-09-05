from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_semantic_frontier import (
    SEMANTIC_FRONTIER_SCHEMA_VERSION,
    SEMANTIC_SOLUTION_SPACE_SCHEMA_VERSION,
    M15SemanticFrontierError,
    build_m15_semantic_frontier,
    build_m15_semantic_solution_space,
    load_m15_semantic_relaxation_catalog,
    main,
    validate_m15_semantic_relaxation_catalog,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_SPEC = (
    REPO_ROOT
    / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
)
CATALOG = (
    REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
)


def _query() -> dict[str, object]:
    return json.loads(QUERY_SPEC.read_text(encoding="utf-8"))


def _catalog() -> dict[str, object]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _space(query: dict[str, object] | None = None):
    return build_m15_semantic_solution_space(
        query or _query(), load_m15_semantic_relaxation_catalog(CATALOG)
    )


def _costs(space, *, mode: str = "all_pareto") -> list[dict[str, object]]:
    payload = space.to_dict()
    classes = sorted(
        payload["semantic_equivalence_classes"],
        key=lambda item: (
            item["semantic_deviation"],
            item["semantic_class_id"],
        ),
    )
    result: list[dict[str, object]] = []
    for index, semantic_class in enumerate(classes):
        if mode == "all_pareto":
            latency = 1000.0 * (0.9**index)
            resource = 100.0 + index
        elif mode == "trivial_first_gain":
            if index == 0:
                latency, resource = 100.0, 100.0
            elif index == 1:
                latency, resource = 99.0, 99.0
            else:
                latency, resource = 50.0 - index, 200.0 + index
        else:
            raise AssertionError(mode)
        interpretation_id = semantic_class["canonical_interpretation_id"]
        result.extend(
            [
                {
                    "plan_id": f"slower-{index:02d}",
                    "interpretation_id": interpretation_id,
                    "latency_ms": latency + 10.0,
                    "resource_cost_units": resource - 10.0,
                    "evidence_id": f"dev-measurement-slower-{index:02d}",
                    "success": True,
                },
                {
                    "plan_id": f"faster-{index:02d}",
                    "interpretation_id": interpretation_id,
                    "latency_ms": latency,
                    "resource_cost_units": resource,
                    "evidence_id": f"dev-measurement-faster-{index:02d}",
                    "success": True,
                },
            ]
        )
    return result


def test_selected_catalog_builds_bounded_typed_solution_space() -> None:
    payload = _space().to_dict()

    assert payload["schema_version"] == SEMANTIC_SOLUTION_SPACE_SCHEMA_VERSION
    assert payload["raw_interpretation_count"] == 12
    assert payload["semantic_class_count"] == 12
    assert len(payload["solution_space_sha256"]) == 64
    assert sum(
        item["semantic_deviation"] == 0
        for item in payload["raw_interpretations"]
    ) == 1
    assert max(
        item["semantic_deviation"]
        for item in payload["raw_interpretations"]
    ) == 1.0
    assert {
        item["semantic_deviation_fraction"]["denominator"]
        for item in payload["raw_interpretations"]
    } <= {1, 2, 3, 6}
    assert payload["hard_bindings"] == {
        "amount-lower-bound": 50000,
        "person-identity": "person-alice-smith",
        "time-lower-bound": "2026-08-05",
    }
    assert all(
        item["compiled_contract_sha256"]
        for item in payload["raw_interpretations"]
    )
    assert payload["claim_boundary"] == {
        "artifact_class": "unexecuted_bounded_semantic_solution_space",
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_calls_made": 0,
        "contains_measurements": False,
        "paper_result": False,
    }
    assert payload["paper_result"] is False


def test_catalog_is_value_independent_within_the_query_family() -> None:
    query = _query()
    query["query_id"] = "financial-risk-bob-medium-f2c6"
    by_slot = {item["slot_id"]: item for item in query["binding_slots"]}
    by_slot["person-identity"]["value"] = "person-bob-jones"
    by_slot["risk-level"]["value"] = "MEDIUM"

    payload = _space(query).to_dict()

    assert payload["raw_interpretation_count"] == 18
    assert payload["semantic_class_count"] == 18
    risk_values = {
        next(
            value["value"]
            for value in item["semantic_values"]
            if value["constraint_id"] == "risk-level"
        )
        for item in payload["raw_interpretations"]
    }
    assert risk_values == {"LOW", "MEDIUM", "HIGH"}
    assert payload["hard_bindings"]["person-identity"] == "person-bob-jones"


def test_duplicate_derivations_merge_before_physical_reduction() -> None:
    catalog = _catalog()
    risk = next(
        item for item in catalog["dimensions"] if item["constraint_id"] == "risk-level"
    )
    duplicate = copy.deepcopy(risk["transitions"][0])
    duplicate["transition_id"] = "risk-high-to-medium-alternate-proof"
    duplicate["evidence"]["reference"] = "risk-level-adjacency-alternate-v1"
    risk["transitions"].append(duplicate)

    payload = build_m15_semantic_solution_space(
        _query(), validate_m15_semantic_relaxation_catalog(catalog)
    ).to_dict()

    assert payload["raw_interpretation_count"] == 18
    assert payload["semantic_class_count"] == 12
    assert max(
        len(item["member_interpretation_ids"])
        for item in payload["semantic_equivalence_classes"]
    ) == 2


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda catalog: catalog.update(
                family_compatibility_sha256="0" * 64
            ),
            "compatibility hashes differ",
        ),
        (
            lambda catalog: catalog["dimensions"].pop(),
            "all and only relaxable constraints",
        ),
        (
            lambda catalog: catalog["dimensions"][0]["transitions"][0].update(
                transformation="undeclared_transform"
            ),
            "undeclared transformation",
        ),
        (
            lambda catalog: catalog["dimensions"][0]["transitions"][0].update(
                steps=2
            ),
            "exceeds max_steps",
        ),
    ],
)
def test_solution_space_rejects_unsafe_catalog_relationships(
    mutation, message: str
) -> None:
    catalog = _catalog()
    mutation(catalog)

    with pytest.raises(M15SemanticFrontierError, match=message):
        build_m15_semantic_solution_space(
            _query(), validate_m15_semantic_relaxation_catalog(catalog)
        )


def test_catalog_rejects_ambiguous_semantic_target_and_retry() -> None:
    ambiguous = _catalog()
    risk = ambiguous["dimensions"][0]
    duplicate = copy.deepcopy(risk["transitions"][0])
    duplicate["transition_id"] = "risk-high-to-different-medium"
    duplicate["to_value"] = "OTHER"
    risk["transitions"].append(duplicate)
    with pytest.raises(M15SemanticFrontierError, match="maps to multiple values"):
        validate_m15_semantic_relaxation_catalog(ambiguous)

    retry = _catalog()
    retry["automatic_retries"] = 1
    with pytest.raises(M15SemanticFrontierError, match="disable retry"):
        validate_m15_semantic_relaxation_catalog(retry)


def test_solution_space_hash_is_deterministic_across_catalog_order() -> None:
    query = _query()
    first_catalog = _catalog()
    reordered = copy.deepcopy(first_catalog)
    reordered["dimensions"].reverse()
    for dimension in reordered["dimensions"]:
        dimension["transitions"].reverse()

    first = build_m15_semantic_solution_space(query, first_catalog).to_dict()
    second = build_m15_semantic_solution_space(query, reordered).to_dict()

    assert first == second


def test_frontier_reduces_physical_plans_then_bounds_representatives() -> None:
    space = _space()
    frontier = build_m15_semantic_frontier(space, _costs(space)).to_dict()

    assert frontier["schema_version"] == SEMANTIC_FRONTIER_SCHEMA_VERSION
    assert frontier["counts"] == {
        "raw_interpretations": 12,
        "semantic_equivalence_classes": 12,
        "successful_physical_plan_costs": 24,
        "physical_representatives": 12,
        "pareto_plans": 12,
        "epsilon_frontier_plans": 12,
        "returned_representatives": 4,
    }
    assert all(
        item["plan_id"].startswith("faster-")
        for item in frontier["physical_representatives"]
    )
    assert frontier["returned_representatives"][0]["semantic_deviation"] == 0
    assert [
        item["selection_rank"] for item in frontier["returned_representatives"]
    ] == [1, 2, 3, 4]
    assert len(frontier["not_returned_semantic_class_ids"]) == 8
    assert frontier["claim_boundary"]["semantic_quality_validated"] is False
    assert frontier["claim_boundary"]["performance_superiority_validated"] is False
    assert frontier["paper_result"] is False


def test_epsilon_dominance_removes_trivial_semantic_cost_tradeoff() -> None:
    space = _space()
    frontier = build_m15_semantic_frontier(
        space, _costs(space, mode="trivial_first_gain")
    ).to_dict()

    assert frontier["epsilon_removed"]
    removed_ids = {
        item["semantic_class_id"] for item in frontier["epsilon_removed"]
    }
    first_positive = min(
        (
            item
            for item in frontier["pareto_plans"]
            if item["semantic_deviation"] > 0
        ),
        key=lambda item: (
            item["semantic_deviation"],
            item["semantic_class_id"],
        ),
    )
    assert first_positive["semantic_class_id"] in removed_ids
    assert any(
        item["semantic_deviation"] == 0
        for item in frontier["epsilon_frontier_plans"]
    )
    assert frontier["returned_representatives"][0]["semantic_deviation"] == 0


def test_frontier_rejects_unknown_or_incomplete_cost_evidence() -> None:
    space = _space()
    costs = _costs(space)
    costs[0]["interpretation_id"] = "unknown-interpretation"
    with pytest.raises(M15SemanticFrontierError, match="unknown interpretation"):
        build_m15_semantic_frontier(space, costs)

    incomplete = _costs(space)
    missing_interpretation = incomplete[0]["interpretation_id"]
    incomplete = [
        item
        for item in incomplete
        if item["interpretation_id"] != missing_interpretation
    ]
    with pytest.raises(M15SemanticFrontierError, match="every semantic"):
        build_m15_semantic_frontier(space, incomplete)


def test_cli_writes_one_immutable_unexecuted_solution_space(
    tmp_path: Path,
) -> None:
    output = tmp_path / "solution-space.json"
    assert (
        main(
            [
                "--query-spec",
                str(QUERY_SPEC),
                "--catalog",
                str(CATALOG),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["raw_interpretation_count"] == 12
    assert payload["claim_boundary"]["backend_calls_made"] == 0
    with pytest.raises(FileExistsError):
        main(
            [
                "--query-spec",
                str(QUERY_SPEC),
                "--catalog",
                str(CATALOG),
                "--output",
                str(output),
            ]
        )
