from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.freebase_sources import (
    ALIAS_PREDICATE,
    HF_FREEBASE_REVISION,
    NAME_PREDICATE,
    TYPE_PREDICATE,
    ParquetTripleRecord,
)
from xgap.experiments import grailqa_local_catalog as producer
from xgap.experiments.grailqa_local_catalog_evidence import (
    GrailQALocalCatalogEvidenceError,
    audit_grailqa_local_catalog,
)


BUILDER_COMMIT = "1" * 40
ROOT = Path(__file__).resolve().parents[1]


def test_catalog_audit_slurm_wrapper_is_cpu_only_and_fail_closed() -> None:
    wrapper = (
        ROOT / "scripts/slurm/audit_grailqa_local_catalog.sbatch"
    ).read_text(encoding="utf-8")

    assert "#SBATCH --cpus-per-task=2" in wrapper
    assert "#SBATCH --mem=8G" in wrapper
    assert "XGAP_GRAILQA_CATALOG_BUILDER_COMMIT" in wrapper
    assert "grailqa_local_catalog_evidence" in wrapper
    assert "#SBATCH --gres" not in wrapper
    assert "vllm" not in wrapper.casefold()
    assert "DASHSCOPE" not in wrapper


def test_independent_pilot150_catalog_audit_passes_and_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _catalog_fixture(tmp_path, monkeypatch)
    before = _snapshot(fixture["catalog"])

    audit = audit_grailqa_local_catalog(
        catalog_root=fixture["catalog"],
        repo_root=fixture["repo"],
        source_manifest_path=fixture["source_manifest"],
        expected_builder_commit=BUILDER_COMMIT,
    )

    assert audit["success"] is True
    assert audit["failed_check_ids"] == []
    assert audit["question_count"] == 150
    assert audit["run_tree_mutated"] is False
    assert audit["source_verification_boundary"] == {
        "source_manifest_sha256": _sha256(fixture["source_manifest"]),
        "source_inventory_bound": True,
        "freebase_bytes_rescanned_by_auditor": 0,
    }
    assert audit["external_call_counts"] == {
        "llm_calls": 0,
        "backend_calls": 0,
        "ontology_service_calls": 0,
    }
    assert audit["paper_result"] is False
    assert _snapshot(fixture["catalog"]) == before


def test_independent_catalog_audit_detects_candidate_artifact_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _catalog_fixture(tmp_path, monkeypatch)
    candidates = fixture["catalog"] / "query_entity_candidates.jsonl"
    candidates.write_text(
        candidates.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )

    audit = audit_grailqa_local_catalog(
        catalog_root=fixture["catalog"],
        repo_root=fixture["repo"],
        source_manifest_path=fixture["source_manifest"],
        expected_builder_commit=BUILDER_COMMIT,
    )

    assert audit["success"] is False
    assert "catalog.file_hash.query_entity_candidates.jsonl" in audit[
        "failed_check_ids"
    ]


def test_independent_catalog_audit_detects_builder_commit_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _catalog_fixture(tmp_path, monkeypatch)

    audit = audit_grailqa_local_catalog(
        catalog_root=fixture["catalog"],
        repo_root=fixture["repo"],
        source_manifest_path=fixture["source_manifest"],
        expected_builder_commit="2" * 40,
    )

    assert audit["success"] is False
    assert "manifest.builder_commit" in audit["failed_check_ids"]


def test_independent_catalog_audit_rejects_symbolic_link_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _catalog_fixture(tmp_path, monkeypatch)
    catalog_link = tmp_path / "catalog-link"
    catalog_link.symlink_to(fixture["catalog"], target_is_directory=True)

    with pytest.raises(
        GrailQALocalCatalogEvidenceError,
        match="catalog_root must be a non-symbolic-link directory",
    ):
        audit_grailqa_local_catalog(
            catalog_root=catalog_link,
            repo_root=fixture["repo"],
            source_manifest_path=fixture["source_manifest"],
            expected_builder_commit=BUILDER_COMMIT,
        )


def _catalog_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    repo = tmp_path / "repo"
    pilot = repo / "datasets/grailqa_pilot_v1"
    pilot.mkdir(parents=True)
    ids = tuple(f"q-{index:03d}" for index in range(150))
    questions = pilot / "inference_questions.jsonl"
    questions.write_text(
        "".join(
            json.dumps({"question_id": item, "text": "Where was Alice born?"})
            + "\n"
            for item in ids
        ),
        encoding="utf-8",
    )
    (pilot / "pilot_ids.json").write_text(
        json.dumps({"question_ids": list(ids)}) + "\n", encoding="utf-8"
    )
    (pilot / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "inference_questions.jsonl": {"sha256": _sha256(questions)}
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    references = pilot / "reference_interpretations.jsonl"
    references.write_text(
        "".join(json.dumps(_reference(item)) + "\n" for item in ids),
        encoding="utf-8",
    )
    workload = pilot / "workload_stats.jsonl"
    workload.write_text(
        "".join(
            json.dumps({"question_id": item, "Q": 13, "path_length": 1})
            + "\n"
            for item in ids
        ),
        encoding="utf-8",
    )
    ontology, reverse = _schema(tmp_path)
    parquet = tmp_path / "parquet"
    parquet.mkdir()
    source_manifest = tmp_path / "source_manifest.json"
    source_manifest.write_text("{}\n", encoding="utf-8")
    records = (
        _record("m.alice", NAME_PREDICATE, "Alice Example", "en", False),
        _record("m.alice", ALIAS_PREDICATE, "Alice", "en", False),
        _record("m.alice", TYPE_PREDICATE, "people.person", None, True),
    )

    monkeypatch.setattr(producer, "_git_commit", lambda: BUILDER_COMMIT)
    monkeypatch.setattr(
        producer,
        "verify_parquet_source_manifest",
        lambda **_: {
            "status": "ok",
            "shard_count": 964,
            "total_bytes": 32_476_432_840,
        },
    )
    monkeypatch.setattr(
        producer,
        "load_parquet_source_manifest",
        lambda _: {"resolved_parquet_revision": HF_FREEBASE_REVISION},
    )

    def fake_records(**kwargs: object):
        predicates = tuple(kwargs["predicates"])
        subject_ids = kwargs.get("subject_ids")
        statistics = kwargs["statistics"]
        assert isinstance(statistics, dict)
        statistics.update({"parquet_shards": 1, "input_rows": len(records)})
        for record in records:
            subject, predicate, *_ = record.triple
            if predicate in predicates and (
                subject_ids is None or subject in subject_ids
            ):
                yield record

    monkeypatch.setattr(producer, "iter_parquet_triple_records", fake_records)
    catalog = tmp_path / "catalog"
    producer.build_local_catalog(
        inference_questions_path=questions,
        question_ids=ids,
        workload_name="pilot150",
        artifact_id="grailqa-local-catalog-pilot150-v1",
        freebase_parquet_root=parquet,
        source_manifest_path=source_manifest,
        normalized_ontology_path=ontology,
        reverse_properties_path=reverse,
        output_root=catalog,
        staging_root=tmp_path / "staging",
    )
    producer.run_local_reachability_audit(
        catalog_root=catalog,
        inference_questions_path=questions,
        question_ids=ids,
        reference_interpretations_path=references,
        workload_stats_path=workload,
        output_root=catalog,
    )
    return {
        "repo": repo,
        "catalog": catalog,
        "source_manifest": source_manifest,
    }


def _record(
    subject: str,
    predicate: str,
    value: str,
    language: str | None,
    is_resource: bool,
) -> ParquetTripleRecord:
    return ParquetTripleRecord(
        triple=(subject, predicate, value, language, is_resource),
        source_shard="default/data/0000.parquet",
    )


def _schema(root: Path) -> tuple[Path, Path]:
    ontology = root / "ontology.yaml"
    ontology.write_text(
        """schema_version: "m12-ontology-v1"
ontology_id: "fixture-freebase"
version: "fixture-v1"
classes: ["location.location", "people.person"]
relations: ["people.person.place_of_birth"]
properties: []
subsumption:
  location.location: []
  people.person: []
max_relaxation_hops: 3
sibling_admissibility:
  explicit_pairs: []
  rule_reference: null
domain_range:
  people.person.place_of_birth:
    domain: "people.person"
    range: "location.location"
""",
        encoding="utf-8",
    )
    reverse = root / "reverse.json"
    reverse.write_text("{}\n", encoding="utf-8")
    return ontology, reverse


def _reference(question_id: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "pattern_query": {
            "path_var": "p",
            "source": {
                "var": "answer",
                "label": "people.person",
                "properties": {},
            },
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
                "properties": {"type.object.id": "m.alice"},
            },
            "selector": {"kind": "ALL", "k": None},
            "restrictor": "SIMPLE",
            "condition": None,
            "max_depth": None,
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in root.rglob("*")
        if path.is_file()
    }
