from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import sqlite3

import pytest

from xgap.experiments.freebase_sources import (
    EXPECTED_PARQUET_COLUMNS,
    GOOGLE_RDF_GZIP,
    HF_ARCHIVAL_PARQUET,
    HF_FREEBASE_REVISION,
    PARQUET_SPEC_SCHEMA_VERSION,
    load_frozen_parquet_spec,
    normalize_source_mode,
    parquet_row_to_triple,
    smoke_parquet_source,
    verify_parquet_source_manifest,
    write_parquet_source_manifest,
)
from xgap.experiments.grailqa_catalog_v2 import (
    GrailQAInferenceCatalogV2,
    build_catalog_v2,
)
from xgap.experiments.grailqa_catalog_compatibility import build_compatibility_report


REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_SPEC = REPO_ROOT / "experiments/artifacts/freebase_hf_archival_parquet_v1.json"
NS = "http://rdf.freebase.com/ns/"


def test_frozen_archival_source_inventory_and_revision() -> None:
    spec = load_frozen_parquet_spec(FROZEN_SPEC)

    assert spec["revision"] == HF_FREEBASE_REVISION
    assert spec["resolved_parquet_revision"] == HF_FREEBASE_REVISION
    assert spec["shard_count"] == 964
    assert spec["total_bytes"] == 32_476_432_840
    assert [field["name"] for field in spec["parquet_schema"]["fields"]] == list(
        EXPECTED_PARQUET_COLUMNS
    )
    assert {field["type"] for field in spec["parquet_schema"]["fields"]} == {"string"}
    assert spec["shards"][0]["path"] == "default/data/0000.parquet"
    assert spec["shards"][-1]["path"] == "default/data/0963.parquet"
    assert all(HF_FREEBASE_REVISION in item["url"] for item in spec["shards"])
    assert all("/main/" not in item["url"] for item in spec["shards"])


def test_parquet_row_parser_matches_catalog_triple_contract() -> None:
    row = _row("m.alice", "type.object.name", "Alice", "literal", "en")
    assert parquet_row_to_triple(row) == (
        "m.alice",
        "type.object.name",
        "Alice",
        "en",
        False,
    )
    uri_row = _row(
        "m.alice", "type.object.type", "people.person", "uri", None
    )
    assert parquet_row_to_triple(uri_row) == (
        "m.alice",
        "type.object.type",
        "people.person",
        None,
        True,
    )
    assert parquet_row_to_triple(_row("m.alice", "p", "42", "literal", None)) is None


def test_source_mode_is_explicit_and_never_falls_back(tmp_path: Path) -> None:
    assert normalize_source_mode(GOOGLE_RDF_GZIP) == GOOGLE_RDF_GZIP
    assert normalize_source_mode(HF_ARCHIVAL_PARQUET) == HF_ARCHIVAL_PARQUET
    with pytest.raises(ValueError, match="Unsupported Freebase source_mode"):
        normalize_source_mode("auto")
    with pytest.raises(ValueError, match="requires freebase_parquet_root"):
        build_catalog_v2(
            source_mode=HF_ARCHIVAL_PARQUET,
            normalized_ontology_path=tmp_path / "missing-ontology",
            reverse_properties_path=tmp_path / "missing-reverse",
            output_root=tmp_path / "catalog",
        )
    with pytest.raises(ValueError, match="does not accept freebase_rdf_path"):
        build_catalog_v2(
            source_mode=HF_ARCHIVAL_PARQUET,
            freebase_rdf_path=tmp_path / "freebase.nt",
            freebase_parquet_root=tmp_path / "parquet",
            normalized_ontology_path=tmp_path / "missing-ontology",
            reverse_properties_path=tmp_path / "missing-reverse",
            output_root=tmp_path / "catalog",
        )


def test_parquet_manifest_requires_exact_local_shard_set(tmp_path: Path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    arrow = pytest.importorskip("pyarrow")
    root = tmp_path / "parquet"
    shard = root / "default/data/0000.parquet"
    shard.parent.mkdir(parents=True)
    parquet.write_table(
        _arrow_table(arrow, [_row("m.a", "type.object.name", "A", "literal", "en")]),
        shard,
    )
    spec_path = _write_fixture_spec(tmp_path, shard)
    manifest_path = tmp_path / "source_manifest.json"

    manifest = write_parquet_source_manifest(
        parquet_root=root,
        frozen_spec_path=spec_path,
        output_path=manifest_path,
    )
    assert manifest["source_mode"] == HF_ARCHIVAL_PARQUET
    assert manifest["shard_count"] == 1
    assert verify_parquet_source_manifest(
        parquet_root=root, source_manifest_path=manifest_path
    )["status"] == "ok"

    extra = root / "default/data/0001.parquet"
    parquet.write_table(
        _arrow_table(arrow, [_row("m.b", "type.object.name", "B", "literal", "en")]),
        extra,
    )
    with pytest.raises(ValueError, match="shard set differs"):
        verify_parquet_source_manifest(
            parquet_root=root, source_manifest_path=manifest_path
        )


def test_ntriples_and_parquet_build_identical_catalog_rows_and_retrieval(
    tmp_path: Path,
) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    arrow = pytest.importorskip("pyarrow")
    ontology, reverse = _write_schema_inputs(tmp_path)
    rows = _semantic_rows()
    rdf = tmp_path / "freebase.nt"
    rdf.write_text("\n".join(_ntriples(row) for row in rows) + "\n", encoding="utf-8")
    parquet_root = tmp_path / "parquet"
    shard = parquet_root / "default/data/0000.parquet"
    shard.parent.mkdir(parents=True)
    parquet.write_table(_arrow_table(arrow, rows), shard, row_group_size=3)
    spec = _write_fixture_spec(tmp_path, shard)
    source_manifest = tmp_path / "source_manifest.json"
    write_parquet_source_manifest(
        parquet_root=parquet_root,
        frozen_spec_path=spec,
        output_path=source_manifest,
    )

    rdf_catalog = tmp_path / "rdf-catalog"
    parquet_catalog = tmp_path / "parquet-catalog"
    rdf_manifest = build_catalog_v2(
        source_mode=GOOGLE_RDF_GZIP,
        freebase_rdf_path=rdf,
        normalized_ontology_path=ontology,
        reverse_properties_path=reverse,
        output_root=rdf_catalog,
    )
    parquet_manifest = build_catalog_v2(
        source_mode=HF_ARCHIVAL_PARQUET,
        freebase_parquet_root=parquet_root,
        source_manifest_path=source_manifest,
        normalized_ontology_path=ontology,
        reverse_properties_path=reverse,
        output_root=parquet_catalog,
    )

    tables = ("entities", "entity_aliases", "entity_types", "terms", "term_aliases")
    assert _database_rows(rdf_catalog, tables) == _database_rows(parquet_catalog, tables)
    assert rdf_manifest["counts"] == parquet_manifest["counts"]
    assert set(_database_schema(rdf_catalog)) == set(_database_schema(parquet_catalog))
    rdf_retrieval = GrailQAInferenceCatalogV2.load(rdf_catalog).retrieve(
        question_id="q1", question="Where was Alice born?"
    )
    parquet_retrieval = GrailQAInferenceCatalogV2.load(parquet_catalog).retrieve(
        question_id="q1", question="Where was Alice born?"
    )
    assert rdf_retrieval.entities == parquet_retrieval.entities
    assert rdf_retrieval.relations_by_slot == parquet_retrieval.relations_by_slot
    assert rdf_retrieval.types == parquet_retrieval.types
    assert rdf_manifest["construction"]["gold_inputs"] is False
    assert set(inspect.signature(build_catalog_v2).parameters).isdisjoint(
        {"question", "answer", "logical_form", "gold", "reference"}
    )


def test_bounded_parquet_smoke_requires_expected_constructs(tmp_path: Path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    arrow = pytest.importorskip("pyarrow")
    root = tmp_path / "parquet"
    shard = root / "default/data/0000.parquet"
    shard.parent.mkdir(parents=True)
    parquet.write_table(_arrow_table(arrow, _semantic_rows()), shard, row_group_size=20)
    spec = _write_fixture_spec(tmp_path, shard)

    result = smoke_parquet_source(
        parquet_root=root,
        frozen_spec_path=spec,
        max_row_groups=1,
    )

    assert result["status"] == "ok"
    assert all(value > 0 for value in result["counts"].values())
    assert result["statistics"]["parquet_row_groups"] == 1


def test_post_build_compatibility_lists_missing_references(tmp_path: Path) -> None:
    ontology, reverse = _write_schema_inputs(tmp_path)
    rdf = tmp_path / "freebase.nt"
    rdf.write_text("\n".join(_ntriples(row) for row in _semantic_rows()) + "\n")
    catalog = tmp_path / "catalog"
    build_catalog_v2(
        source_mode=GOOGLE_RDF_GZIP,
        freebase_rdf_path=rdf,
        normalized_ontology_path=ontology,
        reverse_properties_path=reverse,
        output_root=catalog,
    )
    present = _reference("q1", "m.alice")
    absent = _reference("q2", "m.missing")
    supported = tmp_path / "supported.jsonl"
    supported.write_text(
        "".join(
            json.dumps(
                {
                    "question_id": item["question_id"],
                    "reference_interpretation": item["pattern_query"],
                }
            )
            + "\n"
            for item in (present, absent)
        )
    )
    pilot = tmp_path / "pilot.jsonl"
    pilot.write_text(json.dumps(absent) + "\n")

    report = build_compatibility_report(
        supported_questions_path=supported,
        pilot_references_path=pilot,
        catalog_root=catalog,
        output_path=tmp_path / "compatibility.json",
    )

    assert report["pilot_reference_mids"]["missing_ids"] == ["m.missing"]
    assert report["supported_workload_reference_mids"]["missing_ids"] == ["m.missing"]
    assert report["ontology_relations_absent"] == []
    assert report["ontology_types_absent"] == []
    assert report["joint_catalog_coverage"]["all_supported"]["count"] == 1
    assert report["gold_usage"] == "evaluation_only_after_catalog_construction"


def test_archival_server_workflow_is_frozen_cpu_only_and_has_no_fallback() -> None:
    download = (REPO_ROOT / "scripts/server/download_freebase_archival_parquet.sh").read_text()
    smoke = (REPO_ROOT / "scripts/server/smoke_freebase_archival_parquet.sh").read_text()
    verify = (REPO_ROOT / "scripts/server/verify_freebase_archival_parquet.sh").read_text()
    slurm = (REPO_ROOT / "scripts/slurm/build_freebase_catalog_v2.sbatch").read_text()

    assert "--continue-at -" in download
    assert "source_manifest" in download
    assert "storage.googleapis.com" not in download
    assert "commondatastorage.googleapis.com" not in download
    assert "--max-row-groups 1" in smoke
    assert "freebase_sources verify" in verify
    assert "hf_archival_parquet" in slurm
    assert HF_FREEBASE_REVISION in slurm
    assert "#SBATCH --gres" not in slurm
    assert "DASHSCOPE" not in slurm


def _semantic_rows() -> list[dict[str, object]]:
    return [
        _row("m.alice", "type.object.name", "Alice Example", "literal", "en"),
        _row("m.alice", "common.topic.alias", "Alice", "literal", "en"),
        _row("m.alice", "common.topic.alias", "Alicia", "literal", "es"),
        _row("m.alice", "type.object.type", "people.person", "uri", None),
        _row("m.paris", "type.object.name", "Paris", "literal", "en"),
        _row("m.paris", "type.object.type", "location.location", "uri", None),
        _row("people.person.place_of_birth", "type.object.name", "Place of Birth", "literal", "en"),
        _row("people.person.parents", "type.object.name", "Parents", "literal", "en"),
    ]


def _row(
    subject: str, predicate: str, value: str, object_type: str, language: str | None
) -> dict[str, object]:
    return {
        "subject": NS + subject,
        "predicate": NS + predicate,
        "object": NS + value if object_type == "uri" else value,
        "object_type": object_type,
        "object_datatype": None,
        "object_language": language,
    }


def _ntriples(row: dict[str, object]) -> str:
    if row["object_type"] == "uri":
        object_text = f"<{row['object']}>"
    else:
        object_text = f'"{row["object"]}"@{row["object_language"]}'
    return f"<{row['subject']}> <{row['predicate']}> {object_text} ."


def _arrow_table(arrow: object, rows: list[dict[str, object]]) -> object:
    schema = arrow.schema(
        [arrow.field(name, arrow.string(), nullable=True) for name in EXPECTED_PARQUET_COLUMNS]
    )
    return arrow.Table.from_pylist(
        [{name: row[name] for name in EXPECTED_PARQUET_COLUMNS} for row in rows],
        schema=schema,
    )


def _write_fixture_spec(root: Path, shard: Path) -> Path:
    schema = {
        "fields": [
            {"name": name, "nullable": True, "type": "string"}
            for name in EXPECTED_PARQUET_COLUMNS
        ]
    }
    fingerprint = hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    relative = "default/data/0000.parquet"
    checksum = hashlib.sha256(shard.read_bytes()).hexdigest()
    spec = {
        "schema_version": PARQUET_SPEC_SCHEMA_VERSION,
        "source_mode": HF_ARCHIVAL_PARQUET,
        "repo_id": "CleverThis/freebase",
        "revision": HF_FREEBASE_REVISION,
        "resolved_parquet_revision": HF_FREEBASE_REVISION,
        "all_shards_same_revision": True,
        "dataset_source_url": "https://huggingface.co/datasets/CleverThis/freebase",
        "parquet_schema": schema,
        "schema_fingerprint": fingerprint,
        "shard_count": 1,
        "total_bytes": shard.stat().st_size,
        "shards": [
            {
                "path": relative,
                "size_bytes": shard.stat().st_size,
                "sha256": checksum,
                "blob_id": "fixture",
                "url": (
                    "https://huggingface.co/datasets/CleverThis/freebase/resolve/"
                    f"{HF_FREEBASE_REVISION}/{relative}"
                ),
            }
        ],
    }
    path = root / "fixture-parquet-spec.json"
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_schema_inputs(root: Path) -> tuple[Path, Path]:
    ontology = root / "ontology.yaml"
    ontology.write_text(
        """schema_version: "m12-ontology-v1"
ontology_id: "fixture-freebase"
version: "fixture-v1"
classes: ["location.location", "people.person"]
relations: ["people.person.place_of_birth", "people.person.parents"]
properties: []
subsumption:
  location.location: []
  people.person: []
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
    reverse.write_text("{}\n", encoding="utf-8")
    return ontology, reverse


def _reference(question_id: str, entity_id: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "pattern_query": {
            "path_var": "p",
            "source": {"var": "answer", "label": "people.person", "properties": {}},
            "expr": {
                "kind": "rel",
                "edge": {
                    "var": "e",
                    "label": "people.person.place_of_birth",
                    "direction": "OUT",
                    "properties": {},
                },
            },
            "target": {
                "var": "anchor",
                "label": "location.location",
                "properties": {"type.object.id": entity_id},
            },
            "selector": {"kind": "ALL", "k": None},
            "restrictor": "SIMPLE",
            "condition": None,
            "max_depth": None,
        },
    }


def _database_rows(root: Path, tables: tuple[str, ...]) -> dict[str, list[tuple[object, ...]]]:
    connection = sqlite3.connect(root / "catalog.sqlite3")
    try:
        return {
            table: list(connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2"))
            for table in tables
        }
    finally:
        connection.close()


def _database_schema(root: Path) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(root / "catalog.sqlite3")
    try:
        return list(
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE type IN ('table', 'index') ORDER BY type, name"
            )
        )
    finally:
        connection.close()
