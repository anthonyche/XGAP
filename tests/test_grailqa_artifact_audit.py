from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.grailqa_audit import (
    analyze_s_expression,
    convert_question_for_audit,
    load_ontology_resources,
    run_audit,
)


def _write_ontology(root: Path) -> None:
    root.mkdir()
    (root / "fb_roles").write_text(
        "person.person person.person.employer organization.organization\n"
        "organization.organization organization.organization.employees person.person\n",
        encoding="utf-8",
    )
    (root / "fb_types").write_text(
        "person.person meta.subclassOf common.topic .\n"
        "organization.organization meta.subclassOf common.topic\n",
        encoding="utf-8",
    )
    (root / "reverse_properties").write_text(
        "person.person.employer\torganization.organization.employees\n",
        encoding="utf-8",
    )
    (root / "domain_dict").write_text("people person.person\n", encoding="utf-8")
    (root / "domain_info").write_text("person.person people\n", encoding="utf-8")


def _question(qid: str = "1") -> dict[str, object]:
    return {
        "qid": qid,
        "question": "who employs alice?",
        "answer": [],
        "function": "none",
        "num_node": 2,
        "num_edge": 1,
        "level": "i.i.d.",
        "graph_query": {
            "nodes": [
                {
                    "nid": 0,
                    "node_type": "class",
                    "id": "organization.organization",
                    "class": "organization.organization",
                    "friendly_name": "Organization",
                    "question_node": 1,
                    "function": "none",
                },
                {
                    "nid": 1,
                    "node_type": "entity",
                    "id": "m.alice",
                    "class": "person.person",
                    "friendly_name": "Alice",
                    "question_node": 0,
                    "function": "none",
                },
            ],
            "edges": [
                {
                    "start": 1,
                    "end": 0,
                    "relation": "person.person.employer",
                    "friendly_name": "Employer",
                }
            ],
        },
        "sparql_query": "SELECT ?x0 WHERE {}",
        "s_expression": (
            "(AND organization.organization "
            "(JOIN (R organization.organization.employees) m.alice))"
        ),
    }


def test_s_expression_analysis_counts_operator_dependencies() -> None:
    analysis = analyze_s_expression("(COUNT (AND person.person (JOIN rel m.alice)))")

    assert analysis.operators == ("COUNT", "AND", "JOIN")
    assert analysis.operator_count == 3
    assert analysis.dependency_count == 2
    assert analysis.complexity == 5


def test_direct_entity_query_uses_production_lowering(tmp_path: Path) -> None:
    ontology_root = tmp_path / "ontology"
    _write_ontology(ontology_root)
    ontology = load_ontology_resources(ontology_root)

    result = convert_question_for_audit(_question(), "dev", ontology)

    assert ontology.malformed_type_lines == ()
    assert result.supported
    assert result.record["status"] == "supported"
    assert result.record["logical_plan_size"] == 13
    assert result.record["operators"] == [
        "Edges",
        "Selection",
        "Selection",
        "Selection",
        "Selection",
        "GroupBy",
        "Projection",
    ]


def test_reverse_relation_requires_official_mapping(tmp_path: Path) -> None:
    ontology_root = tmp_path / "ontology"
    _write_ontology(ontology_root)
    ontology = load_ontology_resources(ontology_root)
    question = _question()
    edge = question["graph_query"]["edges"][0]  # type: ignore[index]
    edge["start"], edge["end"] = edge["end"], edge["start"]  # type: ignore[index]

    result = convert_question_for_audit(question, "dev", ontology)

    assert result.supported
    assert result.record["reverse_property_used"] is True
    assert result.record["traversal_relation"] == "organization.organization.employees"


def test_count_and_masked_test_are_explicitly_unsupported(tmp_path: Path) -> None:
    ontology_root = tmp_path / "ontology"
    _write_ontology(ontology_root)
    ontology = load_ontology_resources(ontology_root)
    count_question = _question()
    count_question["function"] = "count"
    count_question["s_expression"] = f"(COUNT {count_question['s_expression']})"

    count_result = convert_question_for_audit(count_question, "train", ontology)
    masked_result = convert_question_for_audit(
        {"qid": "test-0", "question": "masked"},
        "test_public",
        ontology,
    )

    assert count_result.record["reason"] == "unsupported_aggregation"
    assert masked_result.record["reason"] == "missing_gold_logical_form"


def test_audit_writes_required_artifacts_deterministically(tmp_path: Path) -> None:
    ontology_root = tmp_path / "ontology"
    _write_ontology(ontology_root)
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    (dataset_root / "grailqa_v1.0_train.json").write_text(
        json.dumps([_question("train-1")]), encoding="utf-8"
    )
    (dataset_root / "grailqa_v1.0_dev.json").write_text(
        json.dumps([_question("dev-1")]), encoding="utf-8"
    )
    (dataset_root / "grailqa_v1.0_test_public.json").write_text(
        json.dumps([{"qid": "test-0", "question": "masked"}]), encoding="utf-8"
    )
    output_root = tmp_path / "output"

    summary = run_audit(dataset_root, ontology_root, output_root)

    assert summary["totals"] == {
        "public_questions": 3,
        "gold_available_questions": 2,
        "supported_questions": 2,
        "unsupported_questions": 1,
        "gold_available_unsupported_questions": 0,
        "supported_ratio_public": 2 / 3,
        "supported_ratio_gold_available": 1.0,
    }
    assert {path.name for path in output_root.iterdir()} == {
        "audit_summary.json",
        "complexity_distribution.json",
        "ontology_summary.json",
        "supported_questions.jsonl",
        "unsupported_questions.jsonl",
    }
    complexity = json.loads((output_root / "complexity_distribution.json").read_text())
    assert complexity["xgap_logical_plans"]["histogram"] == {"13": 2}
