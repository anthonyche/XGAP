from __future__ import annotations

import inspect
import json
from pathlib import Path
import sqlite3

import pytest

from xgap.experiments.grailqa_catalog_v2 import (
    GrailQAInferenceCatalogV2,
    build_catalog_v2,
    validate_catalog_v2,
    verify_source_manifest,
    write_source_manifest,
)
from xgap.experiments.grailqa_reachability import (
    CatalogUniverse,
    audit_reachability,
    run_m13e3_audit,
)


def test_catalog_build_is_restart_safe_and_records_integrity(tmp_path: Path) -> None:
    paths = _catalog_inputs(tmp_path)
    source_manifest = write_source_manifest(
        freebase_rdf_path=paths["rdf"],
        output_path=tmp_path / "source_manifest.json",
        source_url="https://example.invalid/freebase-rdf-latest.gz",
    )
    output = tmp_path / "catalog"
    first = build_catalog_v2(
        freebase_rdf_path=paths["rdf"],
        normalized_ontology_path=paths["ontology"],
        reverse_properties_path=paths["reverse"],
        source_manifest_path=tmp_path / "source_manifest.json",
        source_url="https://example.invalid/freebase-rdf-latest.gz",
        output_root=output,
    )
    second = build_catalog_v2(
        freebase_rdf_path=paths["rdf"],
        normalized_ontology_path=paths["ontology"],
        reverse_properties_path=paths["reverse"],
        source_manifest_path=tmp_path / "source_manifest.json",
        source_url="https://example.invalid/freebase-rdf-latest.gz",
        output_root=output,
    )

    assert first == second
    assert first["sources"]["freebase_rdf"]["sha256"] == source_manifest["sha256"]
    assert first["counts"]["entities"] == 2
    assert first["counts"]["canonical_names"] == 2
    assert first["counts"]["entity_aliases"] == 3
    assert first["counts"]["entity_types"] == 2
    assert first["ingestion_statistics"]["rejected_non_english_literals"] == 1
    assert first["ingestion_statistics"]["rejected_invalid_entity_ids"] == 1
    assert first["database_size_bytes"] > 0
    assert first["construction"]["constructed_at"].endswith("Z")
    assert validate_catalog_v2(output)["status"] == "ok"
    assert verify_source_manifest(
        freebase_rdf_path=paths["rdf"],
        source_manifest_path=tmp_path / "source_manifest.json",
    )["status"] == "ok"

    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "entity_canonical_name_idx" in indexes
        assert "entity_types_type_idx" in indexes
        assert connection.execute(
            "SELECT count(*) FROM entity_search WHERE entity_search MATCH 'Alice'"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM entity_aliases WHERE alias='Alicia'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_catalog_refuses_to_replace_complete_output_for_different_source(
    tmp_path: Path,
) -> None:
    paths = _catalog_inputs(tmp_path)
    output = tmp_path / "catalog"
    build_catalog_v2(
        freebase_rdf_path=paths["rdf"],
        normalized_ontology_path=paths["ontology"],
        reverse_properties_path=paths["reverse"],
        output_root=output,
    )
    original_hash = GrailQAInferenceCatalogV2.load(output).catalog_hash
    paths["rdf"].write_text(paths["rdf"].read_text() + "# changed\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="different inputs"):
        build_catalog_v2(
            freebase_rdf_path=paths["rdf"],
            normalized_ontology_path=paths["ontology"],
            reverse_properties_path=paths["reverse"],
            output_root=output,
        )
    assert GrailQAInferenceCatalogV2.load(output).catalog_hash == original_hash


def test_source_manifest_rejects_tampered_download(tmp_path: Path) -> None:
    source = tmp_path / "freebase-rdf-latest.gz"
    source.write_bytes(b"fixture")
    manifest = tmp_path / "source_manifest.json"
    write_source_manifest(freebase_rdf_path=source, output_path=manifest)
    source.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_source_manifest(
            freebase_rdf_path=source, source_manifest_path=manifest
        )


def test_reachability_reports_relation_any_all_slots_and_prompt_loss() -> None:
    reference = {
        "question_id": "q1",
        "pattern_query": _pattern(("r.first", "r.second"), "m.anchor"),
    }
    retrieval = {
        "question_id": "q1",
        "entity_candidates": [{"id": "m.decoy"}, {"id": "m.anchor"}],
        "relation_slots": [
            {"candidates": [{"id": "r.first"}]},
            {"candidates": [{"id": "r.decoy"}, {"id": "r.second"}]},
        ],
        "type_candidates": [{"id": "type.answer"}, {"id": "type.anchor"}],
    }
    audit = audit_reachability(
        references=[reference],
        retrieval_rows=[retrieval],
        catalog=CatalogUniverse(
            "fixture",
            "hash",
            frozenset({"m.anchor"}),
            frozenset({"r.first", "r.second"}),
            frozenset({"type.answer", "type.anchor"}),
        ),
        k_values=(1, 2),
        prompt_limit=1,
    )

    assert audit["summary"]["retrieval"]["1"]["relation_any"]["ratio"] == 1.0
    assert audit["summary"]["retrieval"]["1"]["all_required_relations"]["ratio"] == 0.0
    assert audit["summary"]["retrieval"]["2"]["all_required_relations"]["ratio"] == 1.0
    assert audit["summary"]["retrieval"]["1"]["relation_per_slot"]["1"]["ratio"] == 1.0
    assert audit["summary"]["retrieval"]["1"]["relation_per_slot"]["2"]["ratio"] == 0.0
    assert audit["rows"][0]["first_unreachable_stage"] == "reference_not_prompt_visible"


def test_m13e3_audit_writes_compact_outputs_without_gold_in_retrieval(
    tmp_path: Path,
) -> None:
    paths = _catalog_inputs(tmp_path)
    catalog_root = tmp_path / "catalog"
    build_catalog_v2(
        freebase_rdf_path=paths["rdf"],
        normalized_ontology_path=paths["ontology"],
        reverse_properties_path=paths["reverse"],
        output_root=catalog_root,
    )
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    questions = [
        {"question_id": "q1", "text": "Where was Alice born?"},
        {"question_id": "q2", "text": "Who are Alice's parents?"},
    ]
    references = [
        {"question_id": "q1", "pattern_query": _pattern(("people.person.place_of_birth",), "m.alice")},
        {"question_id": "q2", "pattern_query": _pattern(("people.person.parents",), "m.alice")},
    ]
    workload = [
        {"question_id": "q1", "Q": 13, "path_length": 1},
        {"question_id": "q2", "Q": 19, "path_length": 1},
    ]
    _write_jsonl(pilot / "inference_questions.jsonl", questions)
    _write_jsonl(pilot / "reference_interpretations.jsonl", references)
    _write_jsonl(pilot / "workload_stats.jsonl", workload)
    supported = tmp_path / "supported.jsonl"
    _write_jsonl(
        supported,
        [
            {
                "question_id": item["question_id"],
                "reference_interpretation": item["pattern_query"],
            }
            for item in references
        ],
    )
    output = tmp_path / "reachability"

    result = run_m13e3_audit(
        supported_questions_path=supported,
        pilot_root=pilot,
        catalog_root=catalog_root,
        output_root=output,
        expected_supported_questions=2,
        expected_pilot_questions=2,
    )

    assert result["all_supported_question_count"] == 2
    assert set(inspect.signature(GrailQAInferenceCatalogV2.retrieve).parameters).isdisjoint(
        {"gold", "reference", "answer"}
    )
    for name in (
        "audit_summary.json",
        "catalog_coverage.json",
        "retrieval_metrics.json",
        "prompt_reachability.json",
        "stage_failure_counts.json",
        "manifest_reference.json",
    ):
        assert (output / name).is_file()
    manifest = json.loads((output / "manifest_reference.json").read_text())
    assert manifest["status"] == "complete"
    assert manifest["large_artifacts_external"] == ["retrieval.jsonl", "reachability.jsonl"]


def test_m13e3_server_workflow_is_cpu_only_and_separates_stages() -> None:
    root = Path(__file__).resolve().parents[1]
    scripts = {
        name: (root / "scripts/server" / name).read_text(encoding="utf-8")
        for name in (
            "download_freebase_rdf.sh",
            "verify_freebase_rdf.sh",
            "build_freebase_catalog_v2.sh",
            "audit_grailqa_reachability_v2.sh",
        )
    }
    assert "XGAP_FREEBASE_RAW_DIR" in scripts["download_freebase_rdf.sh"]
    assert "--continue-at -" in scripts["download_freebase_rdf.sh"]
    assert "gzip --test" in scripts["verify_freebase_rdf.sh"]
    assert "XGAP_FREEBASE_CATALOG_DIR" in scripts["build_freebase_catalog_v2.sh"]
    assert "m13e3-audit" in scripts["audit_grailqa_reachability_v2.sh"]

    slurm = (root / "scripts/slurm/build_freebase_catalog_v2.sbatch").read_text()
    assert "#SBATCH --cpus-per-task=" in slurm
    assert "#SBATCH --mem=" in slurm
    assert "#SBATCH --time=" in slurm
    assert "--gres" not in slurm
    assert "vllm" not in slurm.casefold()
    assert "DASHSCOPE" not in slurm


def _catalog_inputs(root: Path) -> dict[str, Path]:
    ontology = root / "ontology.yaml"
    ontology.write_text(
        """schema_version: "m12-ontology-v1"
ontology_id: "fixture-freebase"
version: "fixture-v1"
classes: ["location.location", "people.person", "type.answer", "type.anchor"]
relations: ["people.person.place_of_birth", "people.person.parents"]
properties: []
subsumption:
  location.location: []
  people.person: []
  type.answer: []
  type.anchor: []
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
                '<http://rdf.freebase.com/ns/m.alice> <http://rdf.freebase.com/ns/common.topic.alias> "Alice"@en .',
                '<http://rdf.freebase.com/ns/m.alice> <http://rdf.freebase.com/ns/common.topic.alias> "Alicia"@es .',
                '<http://rdf.freebase.com/ns/m.alice> <http://rdf.freebase.com/ns/type.object.type> <http://rdf.freebase.com/ns/people.person> .',
                '<http://rdf.freebase.com/ns/m.paris> <http://rdf.freebase.com/ns/type.object.name> "Paris"@en .',
                '<http://rdf.freebase.com/ns/m.paris> <http://rdf.freebase.com/ns/type.object.type> <http://rdf.freebase.com/ns/location.location> .',
                '<http://rdf.freebase.com/ns/m.bad/id> <http://rdf.freebase.com/ns/type.object.name> "Bad"@en .',
                '<http://rdf.freebase.com/ns/people.person.place_of_birth> <http://rdf.freebase.com/ns/type.object.name> "Place of Birth"@en .',
                '<http://rdf.freebase.com/ns/people.person.parents> <http://rdf.freebase.com/ns/type.object.name> "Parents"@en .',
                "not an RDF triple",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return {"ontology": ontology, "reverse": reverse, "rdf": rdf}


def _pattern(relations: tuple[str, ...], entity: str) -> dict[str, object]:
    expressions = [
        {
            "kind": "rel",
            "edge": {"var": f"e{index}", "label": relation, "direction": "OUT", "properties": {}},
        }
        for index, relation in enumerate(relations, start=1)
    ]
    expr = expressions[0]
    for item in expressions[1:]:
        expr = {"kind": "seq", "left": expr, "right": item}
    return {
        "path_var": "p",
        "source": {"var": "answer", "label": "type.answer", "properties": {}},
        "expr": expr,
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


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
