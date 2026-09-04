from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

import xgap.experiments.bundles as bundle_module
from xgap.backends import registry
from xgap.backends.mapping import BackendMappingError, RdfBackendMapping
from xgap.compilers import compile_cypher, compile_sparql
from xgap.experiments.bundles import DatasetBundle
from xgap.experiments.grailqa_pilot import select_pilot_records
from xgap.experiments.runtime_alignment import (
    OntologyArtifactLoader,
    assert_no_gold_leakage,
)
from xgap.llm.parser import parse_path_pattern_query
from xgap.infrastructure.descriptors import load_yaml_mapping


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = ROOT / "datasets" / "grailqa_pilot_v1"

pytestmark = pytest.mark.skipif(
    not (BUNDLE_ROOT / "dataset.yaml").is_file(),
    reason="external GrailQA pilot artifacts are not installed in this checkout",
)


def test_pilot_selection_is_seeded_and_outcome_independent() -> None:
    records = [
        {
            "question_id": f"q{index}",
            "split": "dev" if index % 5 == 0 else "train",
            "logical_plan_size": (13, 19, 25)[index % 3],
            "path_length": index % 3 + 1,
            "ambiguity": {"A_recommended": index % 10 + 1},
            "function": ">=" if index % 7 == 0 else "none",
            "traversal_relations": [f"domain{index % 4}.relation"],
        }
        for index in range(100)
    ]

    first = select_pilot_records(records, size=20, seed=1303)
    second = select_pilot_records(tuple(reversed(records)), size=20, seed=1303)

    assert [item["question_id"] for item in first] == [
        item["question_id"] for item in second
    ]
    assert sum(item["split"] == "dev" for item in first) == 4
    assert all("score" not in item and "correct" not in item for item in first)


def test_checked_pilot_bundle_loads_and_preserves_gold_isolation() -> None:
    bundle = DatasetBundle.load(BUNDLE_ROOT)
    loader = OntologyArtifactLoader.from_dataset(bundle)
    inference = json.loads((BUNDLE_ROOT / "inference_manifest.json").read_text())
    feasibility = json.loads(
        (BUNDLE_ROOT / "freebase_execution_feasibility.json").read_text()
    )
    distribution = json.loads((BUNDLE_ROOT / "pilot_ids.json").read_text())["distribution"]

    assert bundle.dataset_id == "grailqa_pilot_v1"
    assert len(bundle.questions) == 150
    assert bundle.controlled is False
    assert bundle.entity_catalog == ()
    assert bundle.aliases["entities"] == {}
    assert inference["gold_exposed_to_inference"] is False
    assert feasibility["outcome"] == "C"
    assert feasibility["grailqa_backend_execution_available"] is False
    assert loader.runtime_manifest["gold_artifacts_exposed"] is False
    assert sum(distribution["function"].get(key, 0) for key in ("<", "<=", ">", ">=")) > 0
    assert_no_gold_leakage(
        {
            "ontology": bundle.ontology.to_dict(),
            "aliases": bundle.aliases,
            "entity_catalog": [item.to_dict() for item in bundle.entity_catalog],
            "backend_mapping": bundle.backend_mapping,
            "schema_snapshot": bundle.schema_snapshot.to_dict(),
        }
    )


def test_pyyaml_empty_mappings_normalize_without_changing_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = DatasetBundle.load(BUNDLE_ROOT)
    baseline_mapping = RdfBackendMapping.from_artifact(baseline.backend_mapping)
    original_loader = bundle_module.load_yaml_mapping

    def load_with_pyyaml_nulls(path: str | Path) -> dict[str, object]:
        loaded = original_loader(path)
        name = Path(path).name
        if name == "dataset.yaml":
            loaded["backend_load"] = None
        elif name == "aliases.yaml":
            for field_name in ("ontology_terms", "relations", "entities"):
                loaded[field_name] = None
        elif name == "backend_mapping.yaml":
            tokens = loaded["backends"]["fuseki"]["compiler_tokens"]
            for token_kind in ("node_labels", "edge_labels", "properties"):
                tokens[token_kind] = None
        return loaded

    monkeypatch.setattr(bundle_module, "load_yaml_mapping", load_with_pyyaml_nulls)

    normalized = DatasetBundle.load(BUNDLE_ROOT)
    normalized_mapping = RdfBackendMapping.from_artifact(normalized.backend_mapping)

    assert normalized.bundle_hash == baseline.bundle_hash
    assert normalized_mapping.mapping_hash == baseline_mapping.mapping_hash
    assert normalized.aliases["ontology_terms"] == {}
    assert normalized.aliases["relations"] == {}
    assert normalized.aliases["entities"] == {}
    assert normalized_mapping.compiler_tokens == {
        "node_labels": {},
        "edge_labels": {},
        "properties": {},
    }


def test_rdf_mapping_still_rejects_non_mapping_compiler_tokens() -> None:
    bundle = DatasetBundle.load(BUNDLE_ROOT)
    malformed = deepcopy(bundle.backend_mapping)
    malformed["backends"]["fuseki"]["compiler_tokens"]["node_labels"] = []

    with pytest.raises(BackendMappingError, match="node_labels.*must be an object"):
        RdfBackendMapping.from_artifact(malformed)


def test_pilot_mapping_is_single_source_for_native_compilation() -> None:
    bundle = DatasetBundle.load(BUNDLE_ROOT)
    mapping = RdfBackendMapping.from_artifact(bundle.backend_mapping)
    references = [
        json.loads(line)
        for line in (BUNDLE_ROOT / "reference_interpretations.jsonl")
        .read_text()
        .splitlines()
    ]
    comparison_ids = {
        item.question_id
        for item in bundle.questions
        if item.metadata.get("function") in {"<", "<=", ">", ">="}
    }
    reference = next(item for item in references if item["question_id"] in comparison_ids)
    query = parse_path_pattern_query(reference["pattern_query"])
    registry.load_descriptors(ROOT / "descriptors" / "backends")

    cypher = compile_cypher(query, profile=registry.get_capability_profile("neo4j"))
    sparql = compile_sparql(
        query,
        profile=registry.get_capability_profile("fuseki"),
        backend_mapping=mapping,
    )

    assert cypher.language == "cypher"
    assert sparql.language == "sparql"
    assert "http://rdf.freebase.com/ns/" in sparql.text
    assert sparql.parameters["backend_mapping"]["mapping_id"] == mapping.mapping_id
    assert "rdf.freebase.com" not in (ROOT / "src/xgap/compilers/sparql.py").read_text()


def test_pilot_manifest_hashes_every_non_manifest_file() -> None:
    manifest = json.loads((BUNDLE_ROOT / "artifact_manifest.json").read_text())
    expected = {
        path.name for path in BUNDLE_ROOT.iterdir() if path.is_file()
    } - {"artifact_manifest.json"}

    assert set(manifest["artifacts"]) == expected
    for name, record in manifest["artifacts"].items():
        path = BUNDLE_ROOT / name
        assert record["bytes"] == path.stat().st_size
        assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_vertical_slice_uses_actual_boundaries_without_fake_execution() -> None:
    result = json.loads((BUNDLE_ROOT / "vertical_slice_results.json").read_text())

    assert result["status"] == "ok"
    assert result["Q_values"] == [13, 19, 25]
    assert all(item["m11"]["selected_plan_count"] == 1 for item in result["results"])
    assert all(
        item["semantic_deviation"]["value"] == 0.0 for item in result["results"]
    )
    assert all(item["execution"]["status"] == "blocked" for item in result["results"])
    assert result["physical_realizations"]["histogram"] == {"1": 150}
    assert result["backend_execution"]["financial_risk_D0_reused"] is False
