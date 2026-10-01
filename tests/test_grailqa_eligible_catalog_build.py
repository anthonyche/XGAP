from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from xgap.experiments import grailqa_local_catalog as local
from xgap.experiments.freebase_sources import (
    ALIAS_PREDICATE, NAME_PREDICATE, TYPE_PREDICATE, HF_FREEBASE_REVISION,
    ParquetTripleRecord,
)
from xgap.experiments.grailqa_catalog import sha256_file
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.hashing import content_hash


@pytest.fixture
def build_inputs(tmp_path, monkeypatch):
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({"question_id": "q1", "text": "Alice Example"}) + "\n")
    ontology = tmp_path / "ontology.yaml"
    ontology.write_text('''schema_version: "m12-ontology-v1"
ontology_id: "fixture-freebase"
version: "fixture-v1"
classes: ["people.person"]
relations: ["people.person.parents"]
properties: []
subsumption:
  people.person: []
max_relaxation_hops: 3
sibling_admissibility:
  explicit_pairs: []
  rule_reference: null
domain_range:
  people.person.parents:
    domain: "people.person"
    range: "people.person"
''')
    reverse = tmp_path / "reverse.json"
    reverse.write_text("{}\n")
    source = tmp_path / "source.json"
    source.write_text("{}\n")
    parquet = tmp_path / "source"
    parquet.mkdir()
    state = {"scans": [], "verify_count": 0, "lose_canonical": False, "reverse": False,
             "extra_rows": [], "second_pass_rows": []}

    def verify(**kwargs):
        state["verify_count"] += 1
        return {"shard_count": 964, "total_bytes": 32_476_432_840, "status": "ok"}

    monkeypatch.setattr(local, "verify_parquet_source_manifest", verify)
    monkeypatch.setattr(local, "load_parquet_source_manifest",
                        lambda path: {"resolved_parquet_revision": HF_FREEBASE_REVISION})

    def records(**kwargs):
        state["scans"].append(kwargs)
        rows = [
            ("m.alias_only", ALIAS_PREDICATE, "Alice Example", "en", False),
            ("m.alice", ALIAS_PREDICATE, "Alice", "en", False),
            ("m.alice", NAME_PREDICATE, "Unmatched Canonical", "en", False),
            ("m.alice", TYPE_PREDICATE, "people.person", None, True),
        ]
        rows.extend(state["extra_rows"])
        if kwargs.get("subject_ids") is not None:
            rows.extend(state["second_pass_rows"])
        if state["reverse"]:
            rows.reverse()
        subjects = kwargs.get("subject_ids")
        for triple in rows:
            if triple[1] not in kwargs["predicates"]:
                continue
            if subjects is not None and triple[0] not in subjects:
                continue
            if state["lose_canonical"] and subjects is not None and triple[1] == NAME_PREDICATE:
                continue
            yield ParquetTripleRecord(triple=triple, source_shard=Path("data/000.parquet"))

    monkeypatch.setattr(local, "iter_parquet_triple_records", records)
    kwargs = dict(
        inference_questions_path=questions, question_ids=("q1",), workload_name="fixture",
        artifact_id="fixture", freebase_parquet_root=parquet, source_manifest_path=source,
        normalized_ontology_path=ontology, reverse_properties_path=reverse,
        output_root=tmp_path / "new-catalog", staging_root=tmp_path / "scratch",
        max_candidates_per_query=1, candidate_selection=local.ELIGIBLE_CANDIDATE_SELECTION,
    )
    return kwargs, state


def test_build_materializes_eligible_backfill_and_retrieves_it(build_inputs):
    kwargs, state = build_inputs
    manifest = local.build_local_catalog(**kwargs)
    root = kwargs["output_root"]
    assert manifest["local_catalog_schema_version"] == local.LOCAL_ELIGIBLE_CATALOG_SCHEMA_VERSION
    assert manifest["candidate_selection"] == local.ELIGIBLE_CANDIDATE_SELECTION
    assert manifest["paper_result"] is False
    assert manifest["counts"]["query_candidate_assignments"] == 1
    assert manifest["scan"]["passes"] == 2
    assert state["scans"][1]["subject_ids"] == ("m.alice",)
    diag = json.loads((root / "selection_diagnostics.json").read_text())
    assert diag["per_query"]["q1"] == {
        "matched_entity_count": 2, "eligible_entity_count": 1,
        "dropped_without_canonical_count": 1, "selected_count": 1,
        "truncated_eligible_count": 0, "legacy_topk_dropped_count": 1, "backfilled_count": 1,
    }
    assert "resource_usage" not in diag
    assert manifest["construction"]["selection_resource_usage"]["spool_bytes"] > 0
    assert list(kwargs["staging_root"].iterdir()) == []
    assert local.validate_local_catalog(root)["local_query_filter"] == "ok"
    retrieval = GrailQAInferenceCatalogV2.load(root).retrieve("q1", "Alice Example", top_k=20)
    assert [row.candidate_id for row in retrieval.entities] == ["m.alice"]
    assert retrieval.to_dict()["config"]["entity_retrieval_mode"] == "query_local_persisted_rank"
    with pytest.raises(ValueError, match="text"):
        GrailQAInferenceCatalogV2.load(root).retrieve("q1", "Bob Example")


def test_legacy_result_and_identity_remain_legacy(build_inputs):
    kwargs, _ = build_inputs
    kwargs.pop("candidate_selection")
    manifest = local.build_local_catalog(**kwargs)
    assert manifest["local_catalog_schema_version"] == local.LOCAL_CATALOG_SCHEMA_VERSION
    assert manifest["counts"]["query_candidate_assignments"] == 0
    assert "candidate_selection" not in manifest
    assert "selection_diagnostics.json" not in manifest["file_hashes"]
    assert "paper_result" not in manifest
    identity = {
        "schema_version": local.LOCAL_CATALOG_SCHEMA_VERSION,
        "source_manifest_sha256": manifest["sources"]["freebase_archival_parquet"]["source_manifest_sha256"],
        "question_text_sha256": manifest["question_text_sha256"],
        "content_file_hashes": {k: v for k, v in manifest["file_hashes"].items() if k != "catalog.sqlite3"},
    }
    assert manifest["catalog_hash"] == content_hash(identity)


def test_reordered_source_has_same_catalog_identity(build_inputs):
    kwargs, state = build_inputs
    first = local.build_local_catalog(**kwargs)
    kwargs["output_root"] = kwargs["output_root"].with_name("reordered")
    state["reverse"] = True
    second = local.build_local_catalog(**kwargs)
    assert first["catalog_hash"] == second["catalog_hash"]


@pytest.mark.parametrize("blank", ["", " ", "   "])
def test_blank_canonical_cannot_qualify_high_score_alias(build_inputs, blank):
    kwargs, state = build_inputs
    state["extra_rows"] = [("m.alias_only", NAME_PREDICATE, blank, "en", False)]
    manifest = local.build_local_catalog(**kwargs)
    assert manifest["counts"]["query_candidate_assignments"] == 1
    assert state["scans"][1]["subject_ids"] == ("m.alice",)


@pytest.mark.parametrize("reverse", [True, False])
def test_blank_and_valid_canonical_materializes_valid_name(build_inputs, reverse):
    kwargs, state = build_inputs
    state["reverse"] = reverse
    state["extra_rows"] = [("m.alice", NAME_PREDICATE, "   ", "en", False),
                           ("m.alice", NAME_PREDICATE, "", "en", False)]
    local.build_local_catalog(**kwargs)
    with sqlite3.connect(kwargs["output_root"] / "catalog.sqlite3") as conn:
        assert conn.execute("SELECT id,canonical_name FROM entities").fetchall() == [
            ("m.alice", "Unmatched Canonical")
        ]


def test_only_blank_canonical_in_second_pass_is_explicit_failure(build_inputs):
    kwargs, state = build_inputs
    # Replace the selected MID's valid canonical with blank metadata only on
    # enrichment; blank names must not satisfy the cross-pass membership check.
    original = local._collect_candidate_metadata

    def replace_names(records, **options):
        altered = (
            ParquetTripleRecord(
                triple=(r.triple[0], r.triple[1], "", *r.triple[3:]), source_shard=r.source_shard
            ) if r.triple[1] == NAME_PREDICATE else r
            for r in records
        )
        return original(altered, **options)

    from unittest.mock import patch
    with patch.object(local, "_collect_candidate_metadata", replace_names):
        with pytest.raises(ValueError, match="eligibility changed"):
            local.build_local_catalog(**kwargs)
    assert not kwargs["output_root"].exists()


@pytest.mark.parametrize("option,value", [
    ("max_candidates_per_query", True), ("max_candidates_per_query", 1.5),
    ("anchor_min_tokens", 0), ("anchor_min_tokens", True),
    ("anchor_max_tokens", 0), ("anchor_max_tokens", 1.5), ("omit_stopword_only", 1),
])
def test_invalid_v2_bounds_refused_before_full_source_verification(build_inputs, option, value):
    kwargs, state = build_inputs
    kwargs[option] = value
    with pytest.raises(ValueError):
        local.build_local_catalog(**kwargs)
    assert state["verify_count"] == 0 and state["scans"] == []


@pytest.mark.parametrize("condition", ["force", "existing", "symlink", "unknown"])
def test_unsafe_mode_or_output_refused_before_source_scan(build_inputs, condition):
    kwargs, state = build_inputs
    if condition == "force":
        kwargs["force"] = True
    elif condition == "existing":
        kwargs["output_root"].mkdir()
    elif condition == "symlink":
        kwargs["output_root"].symlink_to(kwargs["output_root"].with_name("missing"))
    else:
        kwargs["candidate_selection"] = "guessed_policy"
    with pytest.raises((ValueError, FileExistsError)):
        local.build_local_catalog(**kwargs)
    assert state["verify_count"] == 0 and state["scans"] == []


def test_missing_canonical_second_pass_is_failure_not_silent_shrink(build_inputs):
    kwargs, state = build_inputs
    state["lose_canonical"] = True
    with pytest.raises(ValueError, match="eligibility changed"):
        local.build_local_catalog(**kwargs)
    assert not kwargs["output_root"].exists()
    assert list(kwargs["staging_root"].iterdir()) == []


def _rewrite_manifest(root, change):
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    change(manifest)
    path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("change", [
    lambda m: m.update(catalog_hash="0" * 64),
    lambda m: m.update(candidate_selection=local.LEGACY_CANDIDATE_SELECTION),
    lambda m: m.update(paper_result=True),
    lambda m: m.update(local_catalog_schema_version=local.LOCAL_CATALOG_SCHEMA_VERSION),
    lambda m: m["anchor_extraction"].update(max_candidates_per_query=2),
])
def test_validator_rejects_manifest_identity_and_policy_tampering(build_inputs, change):
    kwargs, _ = build_inputs
    local.build_local_catalog(**kwargs)
    _rewrite_manifest(kwargs["output_root"], change)
    with pytest.raises(ValueError):
        local.validate_local_catalog(kwargs["output_root"])


def test_validator_rejects_database_candidate_mutation_even_with_new_file_hash(build_inputs):
    kwargs, _ = build_inputs
    root = kwargs["output_root"]
    local.build_local_catalog(**kwargs)
    with sqlite3.connect(root / "catalog.sqlite3") as conn:
        conn.execute("UPDATE query_entity_candidates SET rank=2")
    _rewrite_manifest(root, lambda m: m["file_hashes"].update({"catalog.sqlite3": sha256_file(root / "catalog.sqlite3")}))
    with pytest.raises(ValueError, match="ranks"):
        local.validate_local_catalog(root)


@pytest.mark.parametrize("statement", [
    "UPDATE entities SET canonical_name='Different Runtime Name'",
    "UPDATE entity_aliases SET alias_kind='alias' WHERE alias_kind='canonical'",
    "UPDATE entity_aliases SET normalized_alias='different'",
    "UPDATE entity_types SET type_id='another.type'",
    "UPDATE terms SET label='Different Term Label'",
    "UPDATE terms SET domain_id='another.type' WHERE kind='relation'",
    "UPDATE terms SET reverse_id='people.person.children' WHERE kind='relation'",
    "UPDATE term_aliases SET normalized_alias='different'",
])
def test_validator_rejects_runtime_table_changes_with_old_semantic_identity(build_inputs, statement):
    kwargs, _ = build_inputs
    root = kwargs["output_root"]
    original = local.build_local_catalog(**kwargs)
    with sqlite3.connect(root / "catalog.sqlite3") as conn:
        conn.execute(statement)
    _rewrite_manifest(root, lambda m: m["file_hashes"].update({
        "catalog.sqlite3": sha256_file(root / "catalog.sqlite3")
    }))
    assert json.loads((root / "manifest.json").read_text())["catalog_hash"] == original["catalog_hash"]
    with pytest.raises(ValueError):
        local.validate_local_catalog(root)


@pytest.mark.parametrize("field", [
    "entities", "canonical_names", "entity_aliases", "entity_types", "types", "relations",
    "relation_aliases", "reverse_property_entries", "questions", "query_anchors",
    "unique_candidate_mids", "query_candidate_assignments",
])
def test_validator_recomputes_every_published_count(build_inputs, field):
    kwargs, _ = build_inputs
    root = kwargs["output_root"]
    local.build_local_catalog(**kwargs)
    _rewrite_manifest(root, lambda m: m["counts"].update({field: 999}))
    with pytest.raises(ValueError):
        local.validate_local_catalog(root)


def _rehash_catalog(root):
    def update(manifest):
        manifest["file_hashes"] = {
            name: sha256_file(root / name) for name in manifest["file_hashes"]
        }
        manifest["catalog_hash"] = content_hash({
            "schema_version": manifest["local_catalog_schema_version"],
            "source_manifest_sha256": manifest["sources"]["freebase_archival_parquet"]["source_manifest_sha256"],
            "question_text_sha256": manifest["question_text_sha256"],
            "candidate_selection": manifest["candidate_selection"],
            "anchor_extraction": manifest["anchor_extraction"],
            "content_file_hashes": {k: v for k, v in manifest["file_hashes"].items() if k != "catalog.sqlite3"},
        })
    _rewrite_manifest(root, update)


@pytest.mark.parametrize("field,value", [
    ("lexical_score", 0.0), ("matched_label", "No such alias"),
    ("normalized_label", "incorrect normalization"),
    ("match_type", "invented_type"), ("match_type", "exact_normalized_name"),
])
def test_consistent_but_invalid_candidate_metadata_is_rejected(build_inputs, field, value):
    kwargs, _ = build_inputs
    root = kwargs["output_root"]
    local.build_local_catalog(**kwargs)
    with sqlite3.connect(root / "catalog.sqlite3") as conn:
        conn.execute(f"UPDATE query_entity_candidates SET {field}=?", (value,))
    path = root / "query_entity_candidates.jsonl"
    row = json.loads(path.read_text())
    row[field] = value
    path.write_text(json.dumps(row) + "\n")
    _rehash_catalog(root)
    with pytest.raises(ValueError):
        local.validate_local_catalog(root)


@pytest.mark.parametrize("change", [
    lambda d: d.update(gold_inputs=True),
    lambda d: d["per_query"]["q1"].update(selected_count=0),
    lambda d: d["per_query"]["q1"].update(backfilled_count=0),
    lambda d: d["per_query"]["q1"].update(eligible_entity_count=True),
    lambda d: d["per_query"].update(other=d["per_query"]["q1"]),
])
def test_validator_rejects_resigned_diagnostic_inconsistency(build_inputs, change):
    kwargs, _ = build_inputs
    root = kwargs["output_root"]
    local.build_local_catalog(**kwargs)
    path = root / "selection_diagnostics.json"
    diagnostic = json.loads(path.read_text())
    change(diagnostic)
    path.write_text(json.dumps(diagnostic))
    _rehash_catalog(root)
    with pytest.raises(ValueError):
        local.validate_local_catalog(root)


def test_v2_cannot_be_reused_as_v1_even_when_inputs_match(build_inputs):
    kwargs, _ = build_inputs
    local.build_local_catalog(**kwargs)
    kwargs["candidate_selection"] = local.LEGACY_CANDIDATE_SELECTION
    with pytest.raises(FileExistsError, match="different complete"):
        local.build_local_catalog(**kwargs)


def test_old_reachability_entry_refuses_v2_before_references(build_inputs, tmp_path):
    kwargs, _ = build_inputs
    local.build_local_catalog(**kwargs)
    with pytest.raises(ValueError, match="requires an M13-E3B catalog"):
        local.run_local_reachability_audit(
            catalog_root=kwargs["output_root"], inference_questions_path=kwargs["inference_questions_path"],
            question_ids=("q1",), reference_interpretations_path=tmp_path / "never-open-reference",
            workload_stats_path=tmp_path / "never-open-stats", output_root=tmp_path / "audit",
        )


@pytest.mark.parametrize("command", ["run", "audit", "compare"])
def test_v2_nonbuild_modes_fail_before_loading_inputs(monkeypatch, command):
    monkeypatch.setattr(local, "_command_context", lambda _: pytest.fail("loaded config"))
    with pytest.raises(ValueError, match="fresh build only"):
        local.main([command, "--candidate-selection", local.ELIGIBLE_CANDIDATE_SELECTION])


def test_v2_cli_requires_explicit_root_not_environment_default(monkeypatch):
    monkeypatch.setattr(local, "_command_context", lambda _: pytest.fail("loaded config"))
    with pytest.raises(ValueError, match="explicit --local-root"):
        local.main(["build", "--candidate-selection", local.ELIGIBLE_CANDIDATE_SELECTION])


@pytest.mark.parametrize("child", ["", "nested"])
def test_v2_cli_refuses_symlink_root_before_resolving_context(tmp_path, monkeypatch, child):
    target = tmp_path / "actual"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(local, "_command_context", lambda _: pytest.fail("loaded config"))
    with pytest.raises(ValueError, match="symlinks"):
        local.main(["build", "--candidate-selection", local.ELIGIBLE_CANDIDATE_SELECTION,
                    "--local-root", str(alias / child)])


def test_direct_build_refuses_symlink_ancestor_before_source_scan(build_inputs, tmp_path):
    kwargs, state = build_inputs
    target = tmp_path / "actual"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    kwargs["output_root"] = alias / "new"
    with pytest.raises(ValueError, match="ancestors"):
        local.build_local_catalog(**kwargs)
    assert state["verify_count"] == 0 and state["scans"] == []


def test_v2_cli_uses_distinct_names_and_passes_exact_selection(build_inputs, monkeypatch):
    kwargs, _ = build_inputs
    observed = {}
    monkeypatch.setattr(local, "_command_context", lambda _: {
        "questions": kwargs["inference_questions_path"], "question_ids": ("q1",),
        "artifact_id": "frozen-v1", "output": kwargs["output_root"],
        "parquet_root": kwargs["freebase_parquet_root"], "source_manifest": kwargs["source_manifest_path"],
        "ontology": kwargs["normalized_ontology_path"], "reverse": kwargs["reverse_properties_path"],
        "max_candidates": 50, "anchor_min_tokens": 1, "anchor_max_tokens": 8, "omit_stopword_only": True,
    })
    monkeypatch.setattr(local, "build_local_catalog", lambda **kw: observed.update(kw))
    assert local.main(["build", "--candidate-selection", local.ELIGIBLE_CANDIDATE_SELECTION,
                       "--local-root", "explicit", "--parquet-root", "source",
                       "--source-manifest", "source.json"]) == 0
    assert observed["output_root"].name == "new-catalog-eligible-v2"
    assert observed["artifact_id"] == "frozen-v1-eligible-v2"
    assert observed["candidate_selection"] == local.ELIGIBLE_CANDIDATE_SELECTION
    assert observed["max_candidates_per_query"] == 50


def test_existing_publication_like_directory_is_untouched(build_inputs):
    import os

    kwargs, _ = build_inputs
    old = kwargs["output_root"].with_name(f".{kwargs['output_root'].name}.publishing-{os.getpid()}")
    old.mkdir()
    (old / "preserve").write_text("user data")
    local.build_local_catalog(**kwargs)
    assert (old / "preserve").read_text() == "user data"


def test_failed_publication_retains_partial_and_never_reports_complete(build_inputs, monkeypatch):
    import xgap.experiments.grailqa_eligible_catalog_validation as publication

    kwargs, _ = build_inputs
    original = publication.os.link
    calls = []

    def fail_second(source, target, **kw):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("simulated publication error")
        return original(source, target, **kw)

    monkeypatch.setattr(publication.os, "link", fail_second)
    with pytest.raises(OSError, match="publication error"):
        local.build_local_catalog(**kwargs)
    assert kwargs["output_root"].is_dir()
    assert not (kwargs["output_root"] / "manifest.json").exists()
    assert list(kwargs["staging_root"].iterdir()) == []
    with pytest.raises(FileExistsError, match="fresh output"):
        local.build_local_catalog(**kwargs)
