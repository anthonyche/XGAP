"""Synthetic offline checks for the existing normalized grounding contract.

These are syntax/grounding fixtures, not benchmark questions, gold answers,
model outputs, or claims of semantic-generation accuracy. They exercise the
actual parser and grounder without a provider or backend.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.runtime_alignment import (
    GroundedPlannerResponse,
    PromptQuerySlot,
    PromptSchemaView,
    RetrievedOntologyTerm,
    RetrievalLimits,
    RuntimeAlignmentError,
    parse_grounded_planner_response,
)
from xgap.llm.openai_compatible import LiveFailureCategory
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.llm.schemas import PlannerRequest


_SHAPES = ("one", "two", "three_left", "three_right")
_PATHS = {
    "one": ("expr.edge",),
    "two": ("expr.left.edge", "expr.right.edge"),
    "three_left": (
        "expr.left.left.edge", "expr.left.right.edge", "expr.right.edge"
    ),
    "three_right": (
        "expr.left.edge", "expr.right.left.edge", "expr.right.right.edge"
    ),
}


def _term(term_id: str, kind: str) -> RetrievedOntologyTerm:
    return RetrievedOntologyTerm(
        term_id=term_id,
        kind=kind,
        label=term_id,
        aliases=(),
        retrieval_score=1.0,
        retrieval_provenance=("synthetic-contract-fixture",),
        domain="NodeType" if kind == "relation" else None,
        range="NodeType" if kind == "relation" else None,
    )


def _view() -> PromptSchemaView:
    return PromptSchemaView(
        task_id="synthetic-output-contract",
        ontology_id="synthetic-contract-ontology",
        ontology_version="1",
        ontology_hash="synthetic-ontology-identity",
        schema_snapshot_version="1",
        schema_snapshot_hash="synthetic-schema-identity",
        terms=(
            _term("NodeType", "class"),
            _term("BroaderNodeType", "class"),
            *(_term(f"r{index}", "relation") for index in range(1, 4)),
            _term("r1-alternative", "relation"),
        ),
        entities=(),
        query_slots=(
            PromptQuerySlot(
                "retrieved-type", "synthetic type", "class", ("NodeType",),
                ("synthetic-contract-fixture",),
            ),
            *(
                PromptQuerySlot(
                    f"relation-hop-{index}", "synthetic relation", "relation",
                    (f"r{index}",), ("synthetic-contract-fixture",),
                    required_for_candidate=index == 1,
                )
                for index in range(1, 4)
            ),
        ),
        backend_hints={},
        source_schema_items=(),
        limits=RetrievalLimits(),
    )


def _rel(index: int) -> dict[str, Any]:
    return {
        "kind": "rel",
        "edge": {
            "var": f"e{index}",
            "label": f"r{index}",
            "direction": "OUT",
            "properties": {},
        },
    }


def _raw(shape: str = "one") -> dict[str, Any]:
    exprs = {
        "one": _rel(1),
        "two": {"kind": "seq", "left": _rel(1), "right": _rel(2)},
        "three_left": {
            "kind": "seq",
            "left": {"kind": "seq", "left": _rel(1), "right": _rel(2)},
            "right": _rel(3),
        },
        "three_right": {
            "kind": "seq",
            "left": _rel(1),
            "right": {"kind": "seq", "left": _rel(2), "right": _rel(3)},
        },
    }
    return {
        "provider_id": "synthetic-offline-contract",
        "model": "not-a-model-run",
        "query_slots": [
            {"slot_id": slot.slot_id, "query_anchor_id": slot.candidate_anchor_ids[0]}
            for slot in _view().query_slots
        ],
        "candidates": [{
            "candidate_id": "synthetic-candidate",
            "confidence": 0.5,
            "pattern_query": {
                "source": {"var": "n1", "label": "NodeType", "properties": {}},
                "expr": exprs[shape],
                "target": {"var": "n2", "label": "NodeType", "properties": {}},
                # Omitted defaults are valid at the normalized parser boundary.
            },
            "grounding": {
                "entity_ids": [],
                "slot_realizations": [
                    {
                        "slot_id": "retrieved-type",
                        "ontology_term_id": "NodeType",
                        "component_ref": "target",
                    },
                    *(
                        {
                            "slot_id": f"relation-hop-{index}",
                            "ontology_term_id": f"r{index}",
                            "component_ref": component_ref,
                        }
                        for index, component_ref in enumerate(_PATHS[shape], start=1)
                    ),
                ],
            },
        }],
    }


def _realizations(raw: dict[str, Any]) -> list[dict[str, str]]:
    return raw["candidates"][0]["grounding"]["slot_realizations"]


def _parse(
    raw: dict[str, Any], prompt_view: PromptSchemaView | None = None
) -> GroundedPlannerResponse:
    response = parse_normalized_planner_response(
        raw, PlannerRequest("Synthetic contract question", max_candidates=3)
    )
    return parse_grounded_planner_response(raw, response, prompt_view or _view())


def _reject(
    raw: dict[str, Any],
    category: LiveFailureCategory,
    message: str,
    prompt_view: PromptSchemaView | None = None,
) -> None:
    with pytest.raises(RuntimeAlignmentError, match=message) as caught:
        _parse(raw, prompt_view)
    assert caught.value.category is category


@pytest.mark.parametrize("shape", _SHAPES)
def test_complete_anchors_and_exact_structural_hops_accept_normalized_defaults(shape: str) -> None:
    raw = _raw(shape)
    before = deepcopy(raw)

    grounded = _parse(raw)

    assert raw == before
    assert len(grounded.query_anchors) == 4
    candidate = grounded.grounded_candidates[0]
    assert tuple(
        item.component_ref for item in candidate.slot_realizations
        if item.slot_id.startswith("relation-hop-")
    ) == _PATHS[shape]
    assert len(candidate.slot_realizations) == 1 + len(_PATHS[shape])
    normalized = path_pattern_query_to_dict(candidate.candidate.pattern_query)
    assert normalized["selector"] == {"kind": "ALL", "k": None}
    assert normalized["restrictor"] == "SIMPLE"
    assert "selector" not in raw["candidates"][0]["pattern_query"]
    assert "restrictor" not in raw["candidates"][0]["pattern_query"]


@pytest.mark.parametrize("slot_id", ("relation-hop-2", "relation-hop-3"))
def test_candidate_optional_hop_still_requires_its_top_level_anchor(slot_id: str) -> None:
    raw = _raw("one")
    assert not next(slot for slot in _view().query_slots if slot.slot_id == slot_id).required_for_candidate
    raw["query_slots"] = [row for row in raw["query_slots"] if row["slot_id"] != slot_id]
    _reject(raw, LiveFailureCategory.UNRESOLVED_QUERY_ANCHOR, "exactly one selected query anchor")


@pytest.mark.parametrize("slot_id", ("retrieved-type", "relation-hop-2"))
def test_duplicate_top_level_anchor_rejected_even_when_anchor_id_agrees(slot_id: str) -> None:
    raw = _raw()
    raw["query_slots"].append(deepcopy(next(row for row in raw["query_slots"] if row["slot_id"] == slot_id)))
    _reject(raw, LiveFailureCategory.UNRESOLVED_QUERY_ANCHOR, "exactly one selected query anchor")


@pytest.mark.parametrize("replacement", (
    {"slot_id": "unknown-slot", "query_anchor_id": "r1"},
    {"slot_id": "relation-hop-1", "query_anchor_id": "r1-alternative"},
))
def test_top_level_anchor_requires_slot_specific_membership(replacement: dict[str, str]) -> None:
    raw = _raw()
    raw["query_slots"][1] = replacement
    _reject(raw, LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID, "not visible for slot")


@pytest.mark.parametrize("slot_id", ("retrieved-type", "relation-hop-1"))
def test_missing_required_candidate_realization_rejected(slot_id: str) -> None:
    raw = _raw()
    _realizations(raw)[:] = [row for row in _realizations(raw) if row["slot_id"] != slot_id]
    _reject(raw, LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE, "every required query slot exactly once")


@pytest.mark.parametrize("slot_id", ("retrieved-type", "relation-hop-1", "relation-hop-2", "relation-hop-3"))
def test_duplicate_candidate_realization_rejected_for_required_and_optional_slots(slot_id: str) -> None:
    raw = _raw("three_left")
    _realizations(raw).append(deepcopy(next(row for row in _realizations(raw) if row["slot_id"] == slot_id)))
    _reject(raw, LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE, "every required query slot exactly once")


@pytest.mark.parametrize("shape, missing_slot", (
    ("two", "relation-hop-2"),
    ("three_left", "relation-hop-2"),
    ("three_left", "relation-hop-3"),
    ("three_right", "relation-hop-3"),
))
def test_actual_ast_hop_cannot_be_omitted_despite_optional_slot_flag(shape: str, missing_slot: str) -> None:
    raw = _raw(shape)
    _realizations(raw)[:] = [row for row in _realizations(raw) if row["slot_id"] != missing_slot]
    _reject(raw, LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE, "each ordered relation component")


@pytest.mark.parametrize("shape", ("two", "three_left", "three_right"))
def test_correct_component_paths_assigned_to_wrong_hop_order_rejected(shape: str) -> None:
    raw = _raw(shape)
    first, second = _realizations(raw)[1:3]
    first["component_ref"], second["component_ref"] = second["component_ref"], first["component_ref"]
    _reject(raw, LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE, "each ordered relation component")


def test_extra_optional_hop_cannot_reuse_an_existing_relation_component() -> None:
    raw = _raw("one")
    _realizations(raw).append({
        "slot_id": "relation-hop-2", "ontology_term_id": "r2", "component_ref": "expr.edge"
    })
    _reject(raw, LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE, "each ordered relation component")


@pytest.mark.parametrize("index, bad_ref", (
    (0, "n2"),
    (0, "target.label"),
    (0, "pattern_query.target"),
    (1, "e1"),
    (1, "expr.edge.label"),
    (1, "pattern_query.expr.edge"),
    (1, "expr.left.edge"),
    (1, "expr.0.edge"),
    (1, "expr"),
))
def test_component_refs_are_structural_paths_not_variables_scalars_or_nonexistent_paths(index: int, bad_ref: str) -> None:
    raw = _raw("one")
    _realizations(raw)[index]["component_ref"] = bad_ref
    _reject(raw, LiveFailureCategory.INVALID_CANDIDATE, "does not identify a PathPatternQuery component")


@pytest.mark.parametrize("index, bad_ref", ((0, "expr.edge"), (1, "source")))
def test_component_ref_must_have_the_slot_ontology_kind(index: int, bad_ref: str) -> None:
    raw = _raw()
    _realizations(raw)[index]["component_ref"] = bad_ref
    _reject(raw, LiveFailureCategory.INVALID_CANDIDATE, "not ontology kind")


def test_extra_hop_pointing_to_nonexistent_component_rejected() -> None:
    raw = _raw("one")
    _realizations(raw).append({
        "slot_id": "relation-hop-2", "ontology_term_id": "r2", "component_ref": "expr.right.edge"
    })
    _reject(raw, LiveFailureCategory.INVALID_CANDIDATE, "does not identify a PathPatternQuery component")


@pytest.mark.parametrize("term_id, category, message", (
    ("not-visible", LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID, "not prompt-visible"),
    ("NodeType", LiveFailureCategory.INVALID_CANDIDATE, "ontology kind 'class', expected 'relation'"),
))
def test_realization_alternative_must_still_be_visible_and_of_matching_kind(term_id: str, category: LiveFailureCategory, message: str) -> None:
    raw = _raw()
    _realizations(raw)[1]["ontology_term_id"] = term_id
    _reject(raw, category, message)


@pytest.mark.parametrize("kind", ("class", "relation"))
def test_visible_candidate_alternative_need_not_equal_selected_query_anchor(kind: str) -> None:
    raw = _raw()
    if kind == "class":
        slot_id, alternative, index = "retrieved-type", "BroaderNodeType", 0
        raw["candidates"][0]["pattern_query"]["target"]["label"] = alternative
    else:
        slot_id, alternative, index = "relation-hop-1", "r1-alternative", 1
        raw["candidates"][0]["pattern_query"]["expr"]["edge"]["label"] = alternative
    _realizations(raw)[index]["ontology_term_id"] = alternative

    grounded = _parse(raw)

    anchor = next(row for row in grounded.query_anchors if row.slot_id == slot_id)
    realization = next(row for row in grounded.grounded_candidates[0].slot_realizations if row.slot_id == slot_id)
    assert realization.ontology_term_id == alternative
    assert realization.ontology_term_id != anchor.query_anchor_id
    assert alternative in _view().visible_term_ids
    normalized = path_pattern_query_to_dict(grounded.grounded_candidates[0].candidate.pattern_query)
    actual_label = normalized["target"]["label"] if kind == "class" else normalized["expr"]["edge"]["label"]
    assert actual_label == realization.ontology_term_id
    # Grounding acceptance alone is not ontology-distance scoring or correctness.


def _property_case(component_ref: str) -> tuple[dict[str, Any], PromptSchemaView]:
    raw = _raw()
    view = _view()
    property_id = "property.synthetic"
    property_slot = PromptQuerySlot(
        "retrieved-property", "synthetic property", "property", (property_id,),
        ("synthetic-contract-fixture",),
    )
    view = replace(
        view,
        terms=(*view.terms, _term(property_id, "property")),
        query_slots=(*view.query_slots, property_slot),
    )
    raw["query_slots"].append({
        "slot_id": property_slot.slot_id, "query_anchor_id": property_id,
    })
    _realizations(raw).append({
        "slot_id": property_slot.slot_id,
        "ontology_term_id": property_id,
        "component_ref": component_ref,
    })
    pattern = raw["candidates"][0]["pattern_query"]
    # These are exact literal property keys, not traversal/index expressions.
    for component in (pattern["source"], pattern["target"], pattern["expr"]["edge"]):
        component["properties"] = {"metric.2": 7, "0": 3}
    pattern["condition"] = {
        "kind": "property_equals",
        "ref": {"kind": "node", "position": "first"},
        "property": "metric.2",
        "value": 7,
    }
    return raw, view


@pytest.mark.parametrize("component_ref", (
    "source.properties.metric.2",
    "target.properties.metric.2",
    "expr.edge.properties.metric.2",
    "source.properties.0",
    "condition",
))
def test_exact_registered_property_and_whole_condition_refs_are_accepted(component_ref: str) -> None:
    raw, view = _property_case(component_ref)

    grounded = _parse(raw, view)

    assert grounded.grounded_candidates[0].slot_realizations[-1].component_ref == component_ref


@pytest.mark.parametrize("component_ref", (
    "source.properties.absent",
    "source.properties.metric",
    "source.properties.metric[2]",
    "source.properties",
    "condition.property",
    "condition.conditions.0",
    "condition.conditions[0]",
))
def test_absent_properties_and_nested_condition_or_scalar_refs_are_rejected(component_ref: str) -> None:
    raw, view = _property_case(component_ref)
    _reject(
        raw, LiveFailureCategory.INVALID_CANDIDATE,
        "does not identify a PathPatternQuery component", view,
    )


def test_condition_ref_requires_a_condition_in_the_parsed_candidate() -> None:
    raw, view = _property_case("condition")
    pattern = raw["candidates"][0]["pattern_query"]
    pattern["condition"] = None
    # Avoid a SIMPLE-derived inequality: the parsed condition is truly absent.
    pattern["restrictor"] = "TRAIL"
    _reject(
        raw, LiveFailureCategory.INVALID_CANDIDATE,
        "does not identify a PathPatternQuery component", view,
    )
