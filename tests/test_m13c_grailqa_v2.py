from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.grailqa_audit import load_ontology_resources
from xgap.experiments.grailqa_v2 import (
    build_backend_mapping,
    convert_question_v2,
    normalize_answers,
    normalize_ontology,
    reference_ambiguity,
    run_audit_v2,
)
from xgap.experiments.semantic import (
    DirectionalOntologyDeviation,
    SemanticDeviationConfig,
    SlotAlignmentEvidence,
)
from xgap.infrastructure.descriptors import load_yaml_mapping


def _write_ontology(root: Path) -> None:
    root.mkdir()
    (root / "fb_roles").write_text(
        "person.person person.person.employer organization.organization\n"
        "organization.organization organization.organization.employees person.person\n"
        "organization.organization organization.organization.location location.location\n"
        "location.location location.location.organizations organization.organization\n"
        "organization.organization organization.organization.score type.int\n"
        "type.object type.object.id type.id\n",
        encoding="utf-8",
    )
    (root / "fb_types").write_text(
        "person.person meta.subclassOf common.topic .\n"
        "organization.organization meta.subclassOf common.topic .\n"
        "location.location meta.subclassOf common.topic .\n"
        "cycle.a meta.subclassOf cycle.b .\n"
        "cycle.b meta.subclassOf cycle.a .\n",
        encoding="utf-8",
    )
    (root / "reverse_properties").write_text(
        "person.person.employer organization.organization.employees\n"
        "organization.organization.location location.location.organizations\n",
        encoding="utf-8",
    )
    (root / "domain_dict").write_text("people person.person\n", encoding="utf-8")
    (root / "domain_info").write_text("person.person people\n", encoding="utf-8")


def _question(*, comparison: bool = False, qid: str = "q1") -> dict[str, object]:
    nodes: list[dict[str, object]] = [
        {
            "nid": 0,
            "node_type": "entity",
            "id": "m.alice",
            "class": "person.person",
            "friendly_name": "Alice",
            "question_node": 0,
        },
        {
            "nid": 1,
            "node_type": "class",
            "id": "organization.organization",
            "class": "organization.organization",
            "friendly_name": "Organization",
            "question_node": 0,
        },
        {
            "nid": 2,
            "node_type": "class",
            "id": "location.location",
            "class": "location.location",
            "friendly_name": "Location",
            "question_node": 1,
        },
    ]
    edges: list[dict[str, object]] = [
        {"start": 0, "end": 1, "relation": "person.person.employer"},
        {"start": 1, "end": 2, "relation": "organization.organization.location"},
    ]
    function = "none"
    expression = (
        "(AND location.location (JOIN organization.organization.location "
        "(JOIN person.person.employer m.alice)))"
    )
    if comparison:
        function = ">="
        nodes.append(
            {
                "nid": 3,
                "node_type": "literal",
                "id": "7^^http://www.w3.org/2001/XMLSchema#integer",
                "class": "type.int",
                "friendly_name": "7",
                "question_node": 0,
                "function": ">=",
            }
        )
        edges.append(
            {"start": 1, "end": 3, "relation": "organization.organization.score"}
        )
        expression = (
            "(AND location.location (AND (JOIN organization.organization.location "
            "(JOIN person.person.employer m.alice)) "
            "(GE organization.organization.score 7)))"
        )
    return {
        "qid": qid,
        "question": "where is Alice's employer with score at least seven?",
        "answer": [
            {
                "answer_type": "Entity",
                "answer_argument": "m.place",
                "entity_name": "Somewhere",
            }
        ],
        "function": function,
        "num_node": len(nodes),
        "num_edge": len(edges),
        "level": "i.i.d.",
        "graph_query": {"nodes": nodes, "edges": edges},
        "sparql_query": "SELECT ?x WHERE {}",
        "s_expression": expression,
    }


def test_scc_normalization_is_deterministic_and_acyclic(tmp_path: Path) -> None:
    root = tmp_path / "ontology"
    _write_ontology(root)
    ontology = load_ontology_resources(root)

    first = normalize_ontology(ontology)
    second = normalize_ontology(ontology)

    assert first.graph.ontology_hash == second.graph.ontology_hash
    assert first.term_to_representative["cycle.a"] == "cycle.a"
    assert first.term_to_representative["cycle.b"] == "cycle.a"
    assert first.artifact["counts"]["cyclic_scc_count"] == 1
    assert first.graph.parents.get("cycle.a", ()) == ()


def test_two_edge_and_comparison_queries_use_real_pipeline(tmp_path: Path) -> None:
    root = tmp_path / "ontology"
    _write_ontology(root)
    ontology = load_ontology_resources(root)
    normalized = normalize_ontology(ontology)

    path_result = convert_question_v2(
        _question(), "dev", ontology, normalized_ontology=normalized
    )
    comparison_result = convert_question_v2(
        _question(comparison=True), "dev", ontology, normalized_ontology=normalized
    )

    assert path_result.supported
    assert path_result.record["path_length"] == 2
    assert path_result.record["logical_plan_size"] == 19
    assert "node(1) != node(3)" in path_result.record["formatted_logical_plan"]
    assert comparison_result.supported
    assert comparison_result.record["comparison_property"] == (
        "organization.organization.score"
    )
    assert comparison_result.record["comparison_value"] == 7


def test_missing_reverse_and_focus_only_comparison_fail_explicitly(tmp_path: Path) -> None:
    root = tmp_path / "ontology"
    _write_ontology(root)
    (root / "reverse_properties").write_text("", encoding="utf-8")
    ontology = load_ontology_resources(root)
    question = _question()
    edge = question["graph_query"]["edges"][1]  # type: ignore[index]
    edge["start"], edge["end"] = edge["end"], edge["start"]  # type: ignore[index]

    missing = convert_question_v2(question, "dev", ontology)
    focus_only = _question(comparison=True)
    graph = focus_only["graph_query"]  # type: ignore[assignment]
    graph["nodes"] = [graph["nodes"][1], graph["nodes"][3]]  # type: ignore[index]
    graph["edges"] = [graph["edges"][2]]  # type: ignore[index]

    unsupported_focus = convert_question_v2(focus_only, "dev", ontology)

    assert missing.record["reason"] == "missing_relation_mapping"
    assert unsupported_focus.record["reason"] == "unsupported_comparison"
    assert "focus-only" in unsupported_focus.record["detail"]


def test_reference_ambiguity_is_ontology_derived_not_candidate_count(tmp_path: Path) -> None:
    root = tmp_path / "ontology"
    _write_ontology(root)
    ontology = load_ontology_resources(root)
    normalized = normalize_ontology(ontology)
    result = convert_question_v2(
        _question(), "dev", ontology, normalized_ontology=normalized
    )

    ambiguity = reference_ambiguity(result.record, normalized)

    assert ambiguity["semantic_deviation_definition"] == (
        "frozen_m12_directional_ontology_hop"
    )
    assert ambiguity["counts_by_epsilon"]["0"] == 1
    assert ambiguity["alternative_count"] > 1
    slots = result.record["ontology_slots"]
    person_index = next(
        index for index, slot in enumerate(slots) if slot["normalized_term"] == "person.person"
    )
    measured = DirectionalOntologyDeviation(
        normalized.graph, SemanticDeviationConfig(max_relaxation_hops=3)
    ).evaluate(
        tuple(
            SlotAlignmentEvidence(
                slot_id=slot["slot_id"],
                query_term=slot["normalized_term"],
                aligned_term=(
                    "common.topic" if index == person_index else slot["normalized_term"]
                ),
            )
            for index, slot in enumerate(slots)
        )
    )
    assert round(measured.finite_value or 0.0, 12) in ambiguity["finite_deviations"]


def test_answer_normalization_uses_entity_ids_and_deduplicates() -> None:
    answers = normalize_answers(
        [
            {"answer_type": "Entity", "answer_argument": "m.2", "entity_name": "B"},
            {"answer_type": "Entity", "answer_argument": "m.1", "entity_name": "A"},
            {"answer_type": "Entity", "answer_argument": "m.1", "entity_name": "Alias"},
            {"answer_type": "Value", "answer_argument": "7"},
        ]
    )

    assert [item["equivalence_key"] for item in answers] == [
        "entity:m.1",
        "entity:m.2",
        "scalar:7",
    ]
    assert answers[0]["label"] == "A"
    assert normalize_answers(
        [
            {
                "answer_type": "Entity",
                "answer_argument": "m.1",
                "entity_name": "Alias",
            },
            {
                "answer_type": "Entity",
                "answer_argument": "m.1",
                "entity_name": "A",
            },
        ]
    )[0]["label"] == "A"


def test_backend_mapping_and_small_audit_artifacts_load(tmp_path: Path) -> None:
    ontology_root = tmp_path / "ontology"
    _write_ontology(ontology_root)
    ontology = load_ontology_resources(ontology_root)
    mapping = build_backend_mapping(
        ontology,
        {
            "person.person",
            "organization.organization",
            "location.location",
            "person.person.employer",
            "organization.organization.location",
        },
    )
    assert mapping["term_mappings"]["fuseki"]["person.person"]["representation"] == (
        "fb:person.person"
    )

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    (dataset_root / "grailqa_v1.0_train.json").write_text(
        json.dumps([_question(qid="train")]), encoding="utf-8"
    )
    (dataset_root / "grailqa_v1.0_dev.json").write_text(
        json.dumps([_question(comparison=True, qid="dev")]), encoding="utf-8"
    )
    (dataset_root / "grailqa_v1.0_test_public.json").write_text(
        json.dumps([{"qid": "test", "question": "masked"}]), encoding="utf-8"
    )
    output = tmp_path / "audit"

    summary = run_audit_v2(dataset_root, ontology_root, output)

    assert summary["totals"]["supported_questions"] == 2
    assert summary["complexity"]["histogram"] == {"19": 2}
    assert load_yaml_mapping(output / "normalized_ontology.yaml")["ontology_id"] == (
        "grailqa-freebase-processed-normalized"
    )
    assert {item.name for item in output.iterdir()} == {
        "ambiguity.jsonl",
        "ambiguity_summary.json",
        "audit_summary.json",
        "backend_mapping_summary.json",
        "complexity_distribution.json",
        "normalized_ontology.yaml",
        "ontology_normalization.json",
        "supported_questions.jsonl",
        "unsupported_questions.jsonl",
    }
