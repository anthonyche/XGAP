from __future__ import annotations

import inspect

import pytest

from xgap.experiments.grailqa_reachability import (
    CatalogUniverse,
    audit_reachability,
)
from xgap.experiments.relation_endpoints import (
    EndpointRole,
    RelationEndpointSelection,
    derive_relation_endpoint_types,
)
from xgap.experiments.runtime_alignment import (
    PromptQuerySlot,
    PromptSchemaView,
    RetrievalLimits,
    RetrievedOntologyTerm,
    RuntimeAlignmentError,
    parse_grounded_planner_response,
)
from xgap.llm.openai_compatible import LiveFailureCategory
from xgap.llm.parser import parse_planner_response
from xgap.llm.schemas import PlannerRequest
from xgap.pattern.ast import Direction


def test_relation_endpoint_contract_is_exact_role_aware_and_directional() -> None:
    outward = derive_relation_endpoint_types(
        (
            RelationEndpointSelection(
                "relation-hop-1",
                "expr.edge",
                "r.connected",
                Direction.OUT,
                "type.source",
                "type.target",
            ),
        )
    )
    inward = derive_relation_endpoint_types(
        (
            RelationEndpointSelection(
                "relation-hop-1",
                "expr.edge",
                "r.connected",
                Direction.IN,
                "type.source",
                "type.target",
            ),
        )
    )
    undirected = derive_relation_endpoint_types(
        (
            RelationEndpointSelection(
                "relation-hop-1",
                "expr.edge",
                "r.connected",
                Direction.UNDIRECTED,
                "type.source",
                "type.target",
            ),
        )
    )

    assert [(item.role, item.type_id) for item in outward] == [
        (EndpointRole.SOURCE, "type.source"),
        (EndpointRole.TARGET, "type.target"),
    ]
    assert [(item.role, item.type_id) for item in inward] == [
        (EndpointRole.SOURCE, "type.target"),
        (EndpointRole.TARGET, "type.source"),
    ]
    assert [(item.role, item.type_id) for item in undirected] == [
        (EndpointRole.SOURCE, "type.source"),
        (EndpointRole.SOURCE, "type.target"),
        (EndpointRole.TARGET, "type.source"),
        (EndpointRole.TARGET, "type.target"),
    ]
    assert set(inspect.signature(derive_relation_endpoint_types).parameters) == {
        "selections"
    }


def test_runtime_accepts_exact_selected_relation_range_outside_explicit_types() -> None:
    view = _prompt_view()
    raw = _grounded_raw(target_type="type.target")
    response = parse_planner_response(raw, PlannerRequest("question"))

    grounded = parse_grounded_planner_response(raw, response, view)

    evidence = grounded.grounded_candidates[0].endpoint_type_evidence
    assert [(item.role.value, item.type_id) for item in evidence] == [
        ("target", "type.target")
    ]
    assert grounded.grounded_candidates[0].to_dict()["endpoint_type_evidence"][0][
        "relation_id"
    ] == "r.connected"


@pytest.mark.parametrize(
    ("target_type", "relation_label"),
    (("type.wrong", "r.connected"), ("type.target", "r.other")),
)
def test_runtime_rejects_non_exact_or_unselected_endpoint_evidence(
    target_type: str, relation_label: str
) -> None:
    view = _prompt_view()
    raw = _grounded_raw(target_type=target_type, relation_label=relation_label)
    response = parse_planner_response(raw, PlannerRequest("question"))

    with pytest.raises(RuntimeAlignmentError) as caught:
        parse_grounded_planner_response(raw, response, view)

    assert caught.value.category is LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID


def test_reachability_preserves_explicit_type_metric_but_gates_on_effective_types() -> None:
    audit = audit_reachability(
        references=[{"question_id": "q1", "pattern_query": _pattern("OUT")}],
        retrieval_rows=[_retrieval(relation_rank=1)],
        catalog=_catalog(),
        k_values=(1,),
        prompt_limit=1,
    )

    row = audit["rows"][0]
    deployed = row["deployed_prompt"]
    assert not deployed["type"]["reachable"]
    assert deployed["effective_type"]["reachable"]
    assert deployed["effective_type"]["per_role"] == [
        {
            "role": "source",
            "type_id": "type.source",
            "reachable": True,
            "visibility_source": "m13e3b4-relation-endpoint-grounding-v1",
        },
        {
            "role": "target",
            "type_id": "type.target",
            "reachable": True,
            "visibility_source": "m13e3b4-relation-endpoint-grounding-v1",
        },
    ]
    assert deployed["joint"]["reachable"]
    assert audit["summary"]["deployed_prompt"]["type"]["ratio"] == 0.0
    assert audit["summary"]["deployed_prompt"]["effective_type"]["ratio"] == 1.0
    assert audit["summary"]["deployed_prompt"]["joint"]["ratio"] == 1.0


def test_reachability_requires_direction_and_prompt_visible_relation_slot() -> None:
    wrong_direction = audit_reachability(
        references=[{"question_id": "q1", "pattern_query": _pattern("IN")}],
        retrieval_rows=[_retrieval(relation_rank=1)],
        catalog=_catalog(),
        k_values=(1,),
        prompt_limit=1,
    )["rows"][0]
    truncated_relation = audit_reachability(
        references=[{"question_id": "q1", "pattern_query": _pattern("OUT")}],
        retrieval_rows=[_retrieval(relation_rank=2)],
        catalog=_catalog(),
        k_values=(2,),
        prompt_limit=1,
    )["rows"][0]

    assert not wrong_direction["deployed_prompt"]["effective_type"]["reachable"]
    assert not wrong_direction["deployed_prompt"]["joint"]["reachable"]
    assert not truncated_relation["deployed_prompt"]["effective_type"]["reachable"]
    assert not truncated_relation["deployed_prompt"]["relation"]["reachable"]


def _prompt_view() -> PromptSchemaView:
    terms = (
        RetrievedOntologyTerm(
            "type.source", "class", "source", (), 1.0, ("fixture",)
        ),
        RetrievedOntologyTerm(
            "r.connected",
            "relation",
            "connected",
            (),
            1.0,
            ("fixture",),
            domain="type.source",
            range="type.target",
        ),
    )
    slots = (
        PromptQuerySlot(
            "retrieved-type", "question", "class", ("type.source",), ("fixture",)
        ),
        PromptQuerySlot(
            "relation-hop-1", "question", "relation", ("r.connected",), ("fixture",)
        ),
    )
    return PromptSchemaView(
        task_id="q1",
        ontology_id="fixture",
        ontology_version="v1",
        ontology_hash="hash",
        schema_snapshot_version="v1",
        schema_snapshot_hash="schema-hash",
        terms=terms,
        entities=(),
        query_slots=slots,
        backend_hints={},
        source_schema_items=("r.connected", "type.source"),
        limits=RetrievalLimits(2, 1, 1, 2),
    )


def _grounded_raw(
    *, target_type: str, relation_label: str = "r.connected"
) -> dict[str, object]:
    return {
        "provider_id": "fixture",
        "query_slots": [
            {"slot_id": "retrieved-type", "query_anchor_id": "type.source"},
            {"slot_id": "relation-hop-1", "query_anchor_id": "r.connected"},
        ],
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "pattern_query": {
                    "path_var": "p",
                    "source": {"var": "s", "label": "type.source", "properties": {}},
                    "expr": {
                        "kind": "rel",
                        "edge": {
                            "var": "e",
                            "label": relation_label,
                            "direction": "OUT",
                            "properties": {},
                        },
                    },
                    "target": {"var": "t", "label": target_type, "properties": {}},
                    "selector": {"kind": "ALL", "k": None},
                    "restrictor": "SIMPLE",
                    "condition": None,
                    "max_depth": None,
                },
                "grounding": {
                    "slot_realizations": [
                        {
                            "slot_id": "retrieved-type",
                            "ontology_term_id": "type.source",
                            "component_ref": "source",
                        },
                        {
                            "slot_id": "relation-hop-1",
                            "ontology_term_id": "r.connected",
                            "component_ref": "expr.edge",
                        },
                    ],
                    "entity_ids": [],
                },
            }
        ],
    }


def _pattern(direction: str) -> dict[str, object]:
    return {
        "path_var": "p",
        "source": {"var": "s", "label": "type.source", "properties": {}},
        "expr": {
            "kind": "rel",
            "edge": {
                "var": "e",
                "label": "r.connected",
                "direction": direction,
                "properties": {},
            },
        },
        "target": {"var": "t", "label": "type.target", "properties": {}},
        "selector": {"kind": "ALL", "k": None},
        "restrictor": "SIMPLE",
        "condition": None,
        "max_depth": None,
    }


def _retrieval(*, relation_rank: int) -> dict[str, object]:
    relation_candidates = [
        {
            "id": "r.decoy",
            "domain": "type.decoy",
            "range": "type.decoy",
        }
    ]
    relation_candidates.insert(
        relation_rank - 1,
        {
            "id": "r.connected",
            "domain": "type.source",
            "range": "type.target",
        },
    )
    return {
        "question_id": "q1",
        "entity_candidates": [],
        "relation_slots": [{"candidates": relation_candidates}],
        "type_candidates": [{"id": "type.decoy"}],
    }


def _catalog() -> CatalogUniverse:
    return CatalogUniverse(
        "fixture",
        "hash",
        frozenset(),
        frozenset({"r.connected"}),
        frozenset({"type.source", "type.target"}),
    )
