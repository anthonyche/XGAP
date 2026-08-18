from __future__ import annotations

import json
from pathlib import Path

from xgap.backends import registry
from xgap.experiments.kqapro_audit import (
    analyze_sparql,
    build_audit_rdf_mapping,
    convert_question_for_audit,
    load_kb_resources,
    run_audit,
)


def _write_kb(path: Path, *, duplicate_human: bool = False) -> None:
    concepts = {
        "C0": {"name": "entity", "instanceOf": []},
        "C1": {"name": "human", "instanceOf": ["C0"]},
        "C2": {"name": "organization", "instanceOf": ["C0"]},
    }
    if duplicate_human:
        concepts["C3"] = {"name": "human", "instanceOf": ["C0"]}
    path.write_text(
        json.dumps(
            {
                "concepts": concepts,
                "entities": {
                    "Q1": {
                        "name": "Alice",
                        "instanceOf": ["C1"],
                        "attributes": [
                            {
                                "key": "birth date",
                                "value": {"type": "date", "value": "2000/01/01"},
                                "qualifiers": {},
                            }
                        ],
                        "relations": [
                            {
                                "predicate": "member of",
                                "object": "Q2",
                                "direction": "forward",
                                "qualifiers": {},
                            },
                            {
                                "predicate": "colleague",
                                "object": "Q3",
                                "direction": "backward",
                                "qualifiers": {
                                    "start time": [
                                        {"type": "year", "value": 2020}
                                    ]
                                },
                            },
                        ],
                    },
                    "Q2": {
                        "name": "Acme",
                        "instanceOf": ["C2"],
                        "attributes": [],
                        "relations": [],
                    },
                    "Q3": {
                        "name": "Bob",
                        "instanceOf": ["C1"],
                        "attributes": [],
                        "relations": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _question(*, direction: str = "forward") -> dict[str, object]:
    predicate = "member of" if direction == "forward" else "colleague"
    concept = "organization" if direction == "forward" else "human"
    return {
        "question": "Who or what is connected to Alice?",
        "choices": ["Acme", "Bob"],
        "program": [
            {"function": "Find", "dependencies": [], "inputs": ["Alice"]},
            {
                "function": "Relate",
                "dependencies": [0],
                "inputs": [predicate, direction],
            },
            {
                "function": "FilterConcept",
                "dependencies": [1],
                "inputs": [concept],
            },
            {"function": "What", "dependencies": [2], "inputs": []},
        ],
        "sparql": (
            "SELECT DISTINCT ?e WHERE { ?e_1 <member_of> ?e . "
            '?e_1 <pred:name> "Alice" . ?e <pred:instance_of> ?c . }'
        ),
        "answer": "Acme" if direction == "forward" else "Bob",
    }


def _profiles(repo_root: Path):
    registry.load_descriptors(repo_root / "descriptors" / "backends")
    return tuple(registry.get_capability_profile(name) for name in ("fuseki", "neo4j"))


def test_kb_resource_audit_uses_only_explicit_metadata(tmp_path: Path) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)

    kb = load_kb_resources(kb_path)

    assert len(kb.concept_ids) == 3
    assert len(kb.entity_ids) == 3
    assert kb.relation_names == {"member of", "colleague"}
    assert kb.attribute_names == {"birth date"}
    assert kb.qualifier_names == {"start time"}
    assert kb.hierarchy_cycle_count == 0


def test_linear_forward_and_backward_paths_use_production_boundaries(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    kb = load_kb_resources(kb_path)
    mapping = build_audit_rdf_mapping(kb)
    profiles = _profiles(repo_root)

    forward = convert_question_for_audit(
        _question(), "val", 0, kb, rdf_mapping=mapping, backend_profiles=profiles
    )
    backward = convert_question_for_audit(
        _question(direction="backward"),
        "val",
        1,
        kb,
        rdf_mapping=mapping,
        backend_profiles=profiles,
    )

    assert forward.supported and backward.supported
    assert forward.record["status"] == "planning-supported"
    assert forward.record["physical_edge_labels"] == ["member of"]
    assert forward.record["answer_endpoint"] == "target"
    assert backward.record["physical_edge_labels"] == ["colleague"]
    assert backward.record["answer_endpoint"] == "source"
    assert forward.record["backend_local_physical_realizations"] == 2
    assert forward.record["currently_executable_with_repository_dataset"] is False


def test_unsupported_semantics_and_ambiguous_concepts_are_explicit(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path, duplicate_human=True)
    kb = load_kb_resources(kb_path)
    mapping = build_audit_rdf_mapping(kb)
    profiles = _profiles(repo_root)
    count = _question()
    count["program"] = [
        *count["program"][:-1],  # type: ignore[index]
        {"function": "Count", "dependencies": [2], "inputs": []},
    ]

    count_result = convert_question_for_audit(
        count, "train", 0, kb, rdf_mapping=mapping, backend_profiles=profiles
    )
    ambiguous = convert_question_for_audit(
        _question(direction="backward"),
        "train",
        1,
        kb,
        rdf_mapping=mapping,
        backend_profiles=profiles,
    )

    assert count_result.record["reason"] == "unsupported_aggregation"
    assert ambiguous.record["reason"] == "ambiguous_concept_mapping"


def test_sparql_audit_reports_generated_surface_features() -> None:
    triple_count, features = analyze_sparql(
        "SELECT (COUNT(DISTINCT ?e) AS ?count) WHERE { "
        "?e <population> ?v . FILTER (?v > 1) . }"
    )

    assert triple_count == 2
    assert {"aggregation", "comparison", "filters"}.issubset(features)


def test_full_audit_writes_the_required_eight_artifacts(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    _write_kb(dataset / "kb.json")
    supported = _question()
    unsupported = _question()
    unsupported["program"] = [
        *unsupported["program"][:-1],  # type: ignore[index]
        {"function": "Count", "dependencies": [2], "inputs": []},
    ]
    (dataset / "train.json").write_text(json.dumps([supported]), encoding="utf-8")
    (dataset / "val.json").write_text(json.dumps([unsupported]), encoding="utf-8")
    (dataset / "test.json").write_text(
        json.dumps([{"question": "masked", "choices": ["x"]}]), encoding="utf-8"
    )
    output = tmp_path / "output"

    summary = run_audit(dataset, output, repo_root=Path(__file__).resolve().parents[1])

    assert summary["totals"]["public_questions"] == 3
    assert summary["totals"]["gold_available_questions"] == 2
    assert summary["totals"]["supported_questions"] == 1
    assert summary["totals"]["unsupported_questions"] == 2
    assert {path.name for path in output.iterdir()} == {
        "audit_summary.json",
        "supported_questions.jsonl",
        "unsupported_questions.jsonl",
        "kopl_operator_statistics.json",
        "sparql_statistics.json",
        "ontology_summary.json",
        "complexity_distribution.json",
        "oracle_candidates.jsonl",
    }
    oracle = json.loads((output / "oracle_candidates.jsonl").read_text())
    assert oracle["query_id"] == "train-000000"
