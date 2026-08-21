from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_catalog_v2 import (
    GrailQAInferenceCatalogV2,
    build_catalog_v2,
    parse_freebase_triple,
)
from xgap.experiments.grailqa_preflight import (
    GrailQAPreflightSpec,
    preflight_readiness,
    run_preflight,
    select_preflight_ids,
)
from xgap.experiments.grailqa_reachability import (
    CatalogUniverse,
    audit_reachability,
    prompt_reachability_gate,
)
from xgap.experiments.interpretation_contract import (
    classify_first_failure,
    component_match_report,
    normalize_interpretation,
    normalized_interpretation_match,
    parse_normalized_planner_response,
    run_posthoc_contract_audit,
    semantic_deviation_distribution,
    validate_generated_condition,
)
from xgap.llm.schemas import PlannerRequest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog_v2(tmp_path_factory: pytest.TempPathFactory) -> GrailQAInferenceCatalogV2:
    root = tmp_path_factory.mktemp("catalog-v2")
    ontology = root / "ontology.yaml"
    ontology.write_text(
        """schema_version: "m12-ontology-v1"
ontology_id: "fixture-freebase"
version: "fixture-v1"
classes: ["location.location","people.person"]
relations: ["people.person.place_of_birth","people.person.parents"]
properties: []
subsumption:
  location.location: []
  people.person: []
  people.person.parents: []
  people.person.place_of_birth: []
max_relaxation_hops: 3
sibling_admissibility:
  explicit_pairs: []
  rule_reference: null
domain_range:
  people.person.parents:
    domain: "people.person"
    range: "people.person"
  people.person.place_of_birth:
    domain: "people.person"
    range: "location.location"
""",
        encoding="utf-8",
    )
    reverse = root / "reverse.json"
    reverse.write_text(
        json.dumps(
            {
                "people.person.place_of_birth": "location.location.people_born_here",
                "location.location.people_born_here": "people.person.place_of_birth",
            }
        ),
        encoding="utf-8",
    )
    rdf = root / "freebase.nt"
    rdf.write_text(
        "\n".join(
            (
                '<http://rdf.freebase.com/ns/m.alice> <http://rdf.freebase.com/ns/type.object.name> "Alice Example"@en .',
                '<http://rdf.freebase.com/ns/m.alice> <http://rdf.freebase.com/ns/common.topic.alias> "Alice"@en .',
                '<http://rdf.freebase.com/ns/m.alice> <http://rdf.freebase.com/ns/type.object.type> <http://rdf.freebase.com/ns/people.person> .',
                '<http://rdf.freebase.com/ns/people.person.place_of_birth> <http://rdf.freebase.com/ns/type.object.name> "Place of Birth"@en .',
                '<http://rdf.freebase.com/ns/people.person.parents> <http://rdf.freebase.com/ns/type.object.name> "Parents"@en .',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    first = root / "first"
    second = root / "second"
    first_manifest = build_catalog_v2(
        freebase_rdf_path=rdf,
        normalized_ontology_path=ontology,
        reverse_properties_path=reverse,
        output_root=first,
        source_url="https://example.invalid/frozen-fixture.nt",
    )
    second_manifest = build_catalog_v2(
        freebase_rdf_path=rdf,
        normalized_ontology_path=ontology,
        reverse_properties_path=reverse,
        output_root=second,
        source_url="https://example.invalid/frozen-fixture.nt",
    )
    assert first_manifest["catalog_hash"] == second_manifest["catalog_hash"]
    return GrailQAInferenceCatalogV2.load(first)


def test_catalog_v2_is_query_independent_and_retrieval_is_deterministic(
    catalog_v2: GrailQAInferenceCatalogV2,
) -> None:
    signature = inspect.signature(build_catalog_v2)
    assert not ({"question", "gold", "reference"} & set(signature.parameters))
    first = catalog_v2.retrieve("q1", "Where was Alice born?", top_k=2)
    second = catalog_v2.retrieve("q1", "Where was Alice born?", top_k=2)

    assert first.to_dict() == second.to_dict()
    config = first.to_dict()["config"]
    assert {key: value for key, value in config.items() if key != "schema_ranking"} == {
        "entity_channels": ["exact_alias", "normalized_alias", "bm25"],
        "tie_break": "score_descending_then_id",
        "relation_channels": [
            "phrase_lexical",
            "public_metadata",
            "ontology_coherence",
        ],
        "type_channels": [
            "lexical_ontology",
            "entity_attached_type",
            "relation_domain_range",
            "ontology_expansion",
        ],
        "relation_slots": 3,
        "gold_inputs": False,
    }
    assert config["schema_ranking"]["schema_ranking_version"] == (
        "m13e3b3-ontology-aware-schema-ranking-v1"
    )
    assert config["schema_ranking"]["gold_inputs"] is False
    assert first.entities[0].candidate_id == "m.alice"
    assert "normalized_alias" in first.entities[0].evidence
    assert first.relations_by_slot[0][0].candidate_id == "people.person.place_of_birth"
    assert first.relations_by_slot[0][0].reverse_id == "location.location.people_born_here"
    assert "people.person" in first.expanded_types
    assert "location.location" in first.expanded_types
    assert len(first.relations_by_slot) == 3
    assert catalog_v2.prompt_view(first).query_slots[-1].required_for_candidate is False


def test_catalog_v2_loader_rejects_tampered_hashed_content(
    catalog_v2: GrailQAInferenceCatalogV2, tmp_path: Path
) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(catalog_v2.root, copied)
    aliases = copied / "entity_aliases.jsonl"
    aliases.write_text(aliases.read_text() + "{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        GrailQAInferenceCatalogV2.load(copied)


def test_freebase_stream_parser_handles_escaped_public_literals() -> None:
    parsed = parse_freebase_triple(
        '<http://rdf.freebase.com/ns/m.x> <http://rdf.freebase.com/ns/type.object.name> '
        '"Alice \\u0026 Bob"@en .\n'
    )
    assert parsed == ("m.x", "type.object.name", "Alice & Bob", "en", False)


def test_reachability_decomposes_catalog_retrieval_and_prompt_loss() -> None:
    reference = {
        "question_id": "q1",
        "pattern_query": _pattern(relation="r.gold", entity="m.gold"),
    }
    retrieval = {
        "question_id": "q1",
        "entity_candidates": [{"id": "m.decoy"}, {"id": "m.gold"}],
        "relation_candidates": [{"id": "r.decoy"}, {"id": "r.gold"}],
        "type_candidates": [{"id": "type.answer"}, {"id": "type.anchor"}],
    }
    catalog = CatalogUniverse(
        "fixture",
        "hash",
        frozenset({"m.gold"}),
        frozenset({"r.gold"}),
        frozenset({"type.answer", "type.anchor"}),
    )
    audit = audit_reachability(
        references=[reference],
        retrieval_rows=[retrieval],
        catalog=catalog,
        k_values=(1, 2),
        prompt_limit=1,
    )

    assert audit["summary"]["catalog"]["joint"]["ratio"] == 1.0
    assert audit["summary"]["retrieval"]["1"]["joint"]["ratio"] == 0.0
    assert audit["summary"]["retrieval"]["2"]["joint"]["ratio"] == 1.0
    assert audit["summary"]["deployed_prompt"]["joint"]["ratio"] == 0.0
    assert audit["rows"][0]["first_unreachable_stage"] == "reference_not_prompt_visible"
    assert not prompt_reachability_gate(audit, minimum_joint_ratio=0.2)["passed"]


def test_m13d_reachability_baseline_reproduces_frozen_diagnosis() -> None:
    summary = json.loads(
        (ROOT / "datasets/grailqa_m13d_reachability_baseline/summary.json").read_text()
    )["summary"]
    assert summary["catalog"]["entity"]["count"] == 12
    assert summary["retrieval"]["20"]["entity"]["count"] == 10
    assert summary["retrieval"]["20"]["relation"]["count"] == 47
    assert summary["retrieval"]["20"]["type"]["count"] == 67
    assert summary["deployed_prompt"]["entity"]["count"] == 9
    assert summary["deployed_prompt"]["relation"]["count"] == 22
    assert summary["deployed_prompt"]["type"]["count"] == 38
    assert summary["deployed_prompt"]["joint"]["count"] == 0


def test_canonical_normalization_adds_only_profile_defaults_and_simple_constraints() -> None:
    generated = _pattern(relation="r.gold", entity="m.gold")
    generated.pop("selector")
    generated.pop("restrictor")
    generated["condition"] = {
        "kind": "property_gt",
        "ref": {"kind": "node", "position": 1},
        "property": "score",
        "value": 10,
    }
    reference = _pattern(relation="r.gold", entity="m.gold")
    reference["condition"] = {
        "kind": "and",
        "conditions": [
            {
                "kind": "node_not_equals",
                "left": {"kind": "node", "position": 1},
                "right": {"kind": "node", "position": 2},
            },
            generated["condition"],
        ],
    }

    normalized = normalize_interpretation(generated)
    assert normalized["selector"] == {"kind": "ALL", "k": None}
    assert normalized["restrictor"] == "SIMPLE"
    assert normalized_interpretation_match(generated, reference)
    report = component_match_report(generated, reference)
    assert report["matches"]["explicit_constraint"]
    assert report["matches"]["canonical_condition"]


@pytest.mark.parametrize("difference", ["relation", "direction", "condition", "focus"])
def test_normalized_equivalence_rejects_real_semantic_differences(difference: str) -> None:
    reference = _pattern(relation="r.gold", entity="m.gold")
    generated = json.loads(json.dumps(reference))
    if difference == "relation":
        generated["expr"]["edge"]["label"] = "r.other"
    elif difference == "direction":
        generated["expr"]["edge"]["direction"] = "IN"
    elif difference == "condition":
        generated["condition"] = {
            "kind": "property_gt",
            "ref": {"kind": "node", "position": 1},
            "property": "score",
            "value": 10,
        }
    else:
        generated["source"]["properties"] = {"type.object.id": "m.gold"}
        generated["target"]["properties"] = {}
    assert not normalized_interpretation_match(generated, reference)


def test_typed_condition_contract_accepts_recursive_grammar_and_rejects_inequality() -> None:
    validate_generated_condition(
        {
            "kind": "and",
            "conditions": [
                {
                    "kind": "property_gte",
                    "ref": {"kind": "node", "position": 1},
                    "property": "score",
                    "value": 10,
                },
                {
                    "kind": "not",
                    "condition": {
                        "kind": "property_equals",
                        "ref": {"kind": "edge", "index": 1},
                        "property": "status",
                        "value": "closed",
                    },
                },
            ],
        }
    )
    with pytest.raises(ValueError, match="must not be generated"):
        validate_generated_condition(
            {
                "kind": "node_not_equals",
                "left": {"kind": "node", "position": 1},
                "right": {"kind": "node", "position": 2},
            }
        )
    schema = json.loads(
        (ROOT / "models/qwen3_max_dashscope_live_m13e1/structured_schema.json").read_text()
    )
    assert "condition" in schema["$defs"]
    assert "node_not_equals" not in json.dumps(schema["$defs"]["condition"])


def test_v2_response_parser_applies_canonical_defaults_before_typed_validation() -> None:
    pattern = _pattern(relation="r.gold", entity="m.gold")
    pattern.pop("selector")
    pattern.pop("restrictor")
    response = {
        "provider_id": "fixture",
        "model": "fixture",
        "candidates": [
            {
                "candidate_id": "c1",
                "confidence": 1.0,
                "rationale": None,
                "pattern_query": pattern,
                "grounding": {"slot_realizations": [], "entity_ids": []},
            }
        ],
    }
    parsed = parse_normalized_planner_response(
        response, PlannerRequest("question", max_candidates=1)
    )
    query = parsed.candidates[0].pattern_query
    assert query.selector.kind.name == "ALL"
    assert query.restrictor.name == "SIMPLE"
    assert query.condition is not None


def test_stage_taxonomy_and_c_sem_audit_are_observable() -> None:
    reachability = {"first_unreachable_stage": "reference_not_retrieved"}
    assert (
        classify_first_failure(
            reachability_row=reachability,
            malformed_output=True,
        )
        == "reference_not_retrieved"
    )
    distribution = semantic_deviation_distribution(
        [
            {"question_id": "q1", "semantic_deviation": 0.0},
            {"question_id": "q1", "semantic_deviation": 0.5},
            {"question_id": "q2", "semantic_deviation": None},
        ]
    )
    assert distribution["finite_count"] == 2
    assert distribution["infinite_count"] == 1
    assert distribution["fraction"]["le_0.0"] == 0.5
    assert distribution["per_query_distinct_values"]["maximum"] == 2


def test_posthoc_audit_writes_separate_normalized_and_stage_outputs(tmp_path: Path) -> None:
    source = tmp_path / "frozen-source"
    pilot = tmp_path / "pilot"
    output = tmp_path / "posthoc"
    source.mkdir()
    pilot.mkdir()
    reference = _pattern(relation="r.gold", entity="m.gold")
    generated = json.loads(json.dumps(reference))
    generated["condition"] = None
    (pilot / "reference_interpretations.jsonl").write_text(
        json.dumps({"question_id": "q1", "pattern_query": reference}) + "\n"
    )
    (source / "metrics.json").write_text(
        json.dumps({"candidate": {"candidate_recall": 0.0}})
    )
    (source / "validated_candidates.jsonl").write_text(
        json.dumps(
            {
                "question_id": "q1",
                "candidate_id": "c1",
                "pattern_query": generated,
                "semantic_admissible": True,
            }
        )
        + "\n"
    )
    (source / "semantic_scores.jsonl").write_text(
        json.dumps({"question_id": "q1", "measurement": {"finite_value": 0.0}})
        + "\n"
    )
    (source / "failures.jsonl").write_text("")
    reachability = tmp_path / "reachability.jsonl"
    reachability.write_text(
        json.dumps({"question_id": "q1", "first_unreachable_stage": None}) + "\n"
    )

    result = run_posthoc_contract_audit(
        source_run=source,
        pilot_root=pilot,
        output_root=output,
        reachability_path=reachability,
    )

    assert result["old_frozen_candidate_recall"] == 0.0
    assert result["new_normalized_candidate_recall"] == 1.0
    assert (output / "component_match.jsonl").is_file()
    assert (output / "failures.jsonl").read_text() == ""


def test_preflight_spec_is_frozen_and_readiness_refuses_missing_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = GrailQAPreflightSpec.load(
        ROOT / "experiments/specs/grailqa_semantic_preflight_v2.json"
    )
    assert len(spec.question_ids) == 18
    assert len(set(spec.question_ids)) == 18
    assert ModelBundle.load(ROOT / spec.data["model_bundle_root"]).bundle_hash == spec.data[
        "model_bundle_hash"
    ]
    monkeypatch.setenv("DASHSCOPE_API_KEY", "not-a-real-key")
    readiness = preflight_readiness(spec, ROOT, require_credentials=True)
    assert readiness["ready"] is False
    assert next(item for item in readiness["checks"] if item["name"] == "catalog_v2")[
        "status"
    ] == "fail"
    with pytest.raises(RuntimeError, match="readiness failed"):
        run_preflight(
            spec_path=spec.path,
            repo_root=ROOT,
            output_root=tmp_path / "blocked-live-run",
        )
    assert not (tmp_path / "blocked-live-run/llm_requests.jsonl").exists()


def test_preflight_selection_is_deterministic_and_not_reachable_only() -> None:
    rows = []
    workload = {}
    for index in range(30):
        question_id = f"q{index:02d}"
        q = (13, 19, 25)[index % 3]
        rows.append(
            {
                "question_id": question_id,
                "deployed_prompt": {
                    kind: {"reachable": (index + offset) % 3 == 0}
                    for offset, kind in enumerate(("entity", "relation", "type"))
                },
            }
        )
        workload[question_id] = {
            "Q": q,
            "path_length": (1, 2, 3)[index % 3],
            "relations": [f"domain{index % 5}.relation"],
        }
    first = select_preflight_ids(rows, workload)
    second = select_preflight_ids(tuple(reversed(rows)), workload)
    assert first == second
    assert len(first) == 18
    assert {workload[item]["Q"] for item in first} == {13, 19, 25}


def _pattern(*, relation: str, entity: str) -> dict[str, object]:
    return {
        "path_var": "p",
        "source": {"var": "answer", "label": "type.answer", "properties": {}},
        "expr": {
            "kind": "rel",
            "edge": {
                "var": "e",
                "label": relation,
                "direction": "OUT",
                "properties": {},
            },
        },
        "target": {
            "var": "anchor",
            "label": "type.anchor",
            "properties": {"type.object.id": entity},
        },
        "selector": {"kind": "ALL", "k": None},
        "restrictor": "SIMPLE",
        "condition": None,
        "max_depth": None,
    }
