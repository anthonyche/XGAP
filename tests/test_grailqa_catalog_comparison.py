"""Offline development comparison tests, not full-source coverage evidence."""

from __future__ import annotations

import json
from pathlib import Path
import socket

import pytest

from test_grailqa_eligible_catalog_build import build_inputs  # noqa: F401
from xgap.experiments import grailqa_catalog_comparison as comparison
from xgap.experiments import grailqa_local_catalog as local
from xgap.experiments.grailqa_catalog import sha256_file


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _reference(question_id: str = "q1", entity_id: str = "m.alice") -> dict:
    return {
        "question_id": question_id,
        "pattern_query": {
            "path_var": "path",
            "source": {"var": "person", "label": "people.person",
                       "properties": {"type.object.id": entity_id}},
            "expr": {"kind": "rel", "edge": {"label": "people.person.parents",
                                                  "direction": "OUT"}},
            "target": {"var": "parent", "label": "people.person", "properties": {}},
            "selector": {"kind": "ALL", "k": None},
            "restrictor": "SIMPLE",
            "condition": None,
            "max_depth": None,
        },
    }


def _build_pair(build_inputs, *, eligible_changes: dict | None = None,
                question_ids: tuple[str, ...] = ("q1",)) -> dict:
    options, _state = build_inputs
    legacy_root = options["output_root"].with_name("legacy-catalog")
    eligible_root = options["output_root"].with_name("eligible-catalog")
    local.build_local_catalog(**{
        **options, "output_root": legacy_root, "question_ids": question_ids,
        "candidate_selection": local.LEGACY_CANDIDATE_SELECTION,
    })
    local.build_local_catalog(**{
        **options, "output_root": eligible_root, "question_ids": question_ids,
        **(eligible_changes or {}),
    })
    references = options["output_root"].with_name("references.jsonl")
    _write_jsonl(references, [_reference(qid) for qid in question_ids])
    return {
        "legacy_catalog_root": legacy_root,
        "eligible_catalog_root": eligible_root,
        "inference_questions_path": options["inference_questions_path"],
        "question_ids": question_ids,
        "reference_interpretations_path": references,
        "output_root": options["output_root"].with_name("comparison"),
    }


@pytest.fixture
def comparison_inputs(build_inputs):
    return _build_pair(build_inputs)


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _tree_hashes(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha256_file(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_real_catalog_build_and_retrieval_show_backfill_not_a_model_result(
    comparison_inputs, monkeypatch,
):
    def no_network(*args, **kwargs):
        raise AssertionError("catalog comparison must not contact any service")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    before = {name: _tree_hashes(comparison_inputs[name])
              for name in ("legacy_catalog_root", "eligible_catalog_root")}
    report = comparison.compare_local_catalogs(**comparison_inputs)
    for stage in ("catalog", "retrieval", "deployed_prompt"):
        delta = report["coverage_changes"][stage]["entity"]
        assert delta == {
            "legacy_count": 0, "eligible_count": 1, "denominator": 1,
            "legacy_ratio": 0.0, "eligible_ratio": 1.0,
            "gained_question_ids": ["q1"], "lost_question_ids": [],
            "unchanged_reachable_question_ids": [],
            "unchanged_unreachable_question_ids": [],
        }
    rows = _read_rows(comparison_inputs["output_root"] / "retrieval.jsonl")
    assert len(rows) == 2
    by_variant = {row["variant"]: row["retrieval"] for row in rows}
    assert by_variant["legacy"]["entity_candidates"] == []
    assert [row["id"] for row in by_variant["eligible"]["entity_candidates"]] == ["m.alice"]
    assert by_variant["eligible"]["config"]["entity_retrieval_mode"] == "query_local_persisted_rank"
    assert report["variants"]["legacy"]["reachability"]["question_count"] == 1
    assert report["variants"]["eligible"]["reachability"]["question_count"] == 1
    assert report["paper_result"] is False
    assert report["live_execution_authorized"] is False
    assert report["backend_calls"] == report["llm_calls"] == 0
    assert json.loads((comparison_inputs["output_root"] / "comparison.json").read_text()) == report
    assert {name: _tree_hashes(comparison_inputs[name]) for name in before} == before


def test_reference_content_is_unread_until_both_retrievals_and_seal_exist(
    comparison_inputs, monkeypatch,
):
    reference = comparison_inputs["reference_interpretations_path"]
    output = comparison_inputs["output_root"]
    original_open = Path.open
    reads = []

    def guarded_open(path, *args, **kwargs):
        if path == reference:
            with original_open(output / "retrieval_seal.json", encoding="utf-8") as handle:
                seal = json.load(handle)
            rows = _read_rows(output / "retrieval.jsonl")
            assert {row["variant"] for row in rows} == {"legacy", "eligible"}
            assert len(rows) == 2
            assert sha256_file(output / "retrieval.jsonl") in json.dumps(seal)
            reads.append(seal)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    comparison.compare_local_catalogs(**comparison_inputs)
    assert reads, "reference content must actually be evaluated after sealing"


def test_reference_changes_do_not_change_frozen_retrieval(comparison_inputs):
    first = comparison.compare_local_catalogs(**comparison_inputs)
    old_retrieval = (comparison_inputs["output_root"] / "retrieval.jsonl").read_bytes()
    _write_jsonl(comparison_inputs["reference_interpretations_path"],
                 [_reference(entity_id="m.not_in_either_catalog")])
    second_inputs = {**comparison_inputs,
                     "output_root": comparison_inputs["output_root"].with_name("comparison-again")}
    second = comparison.compare_local_catalogs(**second_inputs)
    assert (second_inputs["output_root"] / "retrieval.jsonl").read_bytes() == old_retrieval
    assert first["coverage_changes"]["catalog"]["entity"]["gained_question_ids"] == ["q1"]
    delta = second["coverage_changes"]["catalog"]["entity"]
    assert delta["legacy_count"] == delta["eligible_count"] == 0
    assert delta["gained_question_ids"] == delta["lost_question_ids"] == []


@pytest.mark.parametrize("mutation", ["source", "ontology", "reverse", "source_mode"])
def test_comparison_refuses_different_source_or_semantic_bindings(
    comparison_inputs, mutation,
):
    path = comparison_inputs["legacy_catalog_root"] / "manifest.json"
    manifest = json.loads(path.read_text())
    if mutation == "source":
        manifest["sources"]["freebase_archival_parquet"]["source_manifest_sha256"] = "0" * 64
    elif mutation == "ontology":
        manifest["sources"]["ontology"]["sha256"] = "0" * 64
    elif mutation == "reverse":
        manifest["sources"]["ontology"]["reverse_properties_sha256"] = "0" * 64
    else:
        manifest["sources"]["freebase_archival_parquet"]["source_mode"] = "unreviewed_source"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)


@pytest.mark.parametrize("override", [
    {"max_candidates_per_query": 2}, {"anchor_min_tokens": 2},
    {"anchor_max_tokens": 7}, {"omit_stopword_only": False},
])
def test_comparison_refuses_valid_catalogs_built_with_different_bounds(build_inputs, override):
    options = _build_pair(build_inputs, eligible_changes=override)
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**options)


@pytest.mark.parametrize("top_k,prompt_limit", [
    (0, 4), (-1, 4), (True, 4), (1.5, 4), (20, 0), (20, True), (20, 1.5),
])
def test_invalid_retrieval_bounds_are_not_silently_coerced(
    comparison_inputs, top_k, prompt_limit,
):
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs, top_k=top_k,
                                          prompt_limit=prompt_limit)


@pytest.mark.parametrize("condition", ["existing", "dangling_symlink", "symlink_parent",
                                        "nested_legacy", "nested_eligible", "ancestor"])
def test_output_must_be_fresh_non_symlink_and_disjoint(comparison_inputs, condition):
    root = comparison_inputs["output_root"]
    if condition == "existing":
        root.mkdir()
        (root / "preserve.txt").write_text("user data")
    elif condition == "dangling_symlink":
        root.symlink_to(root.with_name("missing"))
    elif condition == "symlink_parent":
        parent = root.with_name("linked-parent")
        parent.symlink_to(root.parent, target_is_directory=True)
        comparison_inputs["output_root"] = parent / "new-comparison"
    elif condition.startswith("nested_"):
        variant = condition.removeprefix("nested_")
        comparison_inputs["output_root"] = comparison_inputs[f"{variant}_catalog_root"] / "new-output"
    else:
        comparison_inputs["output_root"] = comparison_inputs["legacy_catalog_root"].parent
    before = _tree_hashes(comparison_inputs["legacy_catalog_root"])
    with pytest.raises((ValueError, FileExistsError)):
        comparison.compare_local_catalogs(**comparison_inputs)
    assert _tree_hashes(comparison_inputs["legacy_catalog_root"]) == before
    if condition == "existing":
        assert (root / "preserve.txt").read_text() == "user data"


@pytest.mark.parametrize("input_name", ["legacy_catalog_root", "eligible_catalog_root",
                                       "inference_questions_path", "reference_interpretations_path"])
def test_symlinked_inputs_are_refused(comparison_inputs, input_name):
    original = comparison_inputs[input_name]
    link = original.with_name(original.name + "-link")
    link.symlink_to(original, target_is_directory=original.is_dir())
    comparison_inputs[input_name] = link
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)


@pytest.mark.parametrize("reference_rows", [[], [_reference("other")],
                                           [_reference(), _reference()]])
def test_missing_or_duplicate_reference_question_is_explicit_failure(
    comparison_inputs, reference_rows,
):
    _write_jsonl(comparison_inputs["reference_interpretations_path"], reference_rows)
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)
    output = comparison_inputs["output_root"]
    assert not (output / "comparison.json").exists()
    status = json.loads((output / "run_status.json").read_text())
    assert status["status"] == "failed"


def test_nonexistent_reference_file_cannot_be_a_successful_comparison(comparison_inputs):
    comparison_inputs["reference_interpretations_path"] = comparison_inputs["output_root"].with_name("absent.jsonl")
    with pytest.raises((ValueError, FileNotFoundError)):
        comparison.compare_local_catalogs(**comparison_inputs)
    assert not (comparison_inputs["output_root"] / "comparison.json").exists()


@pytest.mark.parametrize("defect", [
    "unknown_operator", "missing_selector", "missing_source", "missing_edge",
    "nested_unknown_operator", "wrong_label_type", "wrong_properties_type",
    "invalid_variable_types", "selector_requires_k",
])
def test_invalid_reference_is_rejected_after_seal_without_false_coverage_gain(
    comparison_inputs, defect,
):
    reference = _reference()
    query = reference["pattern_query"]
    if defect == "unknown_operator":
        query["expr"] = {"kind": "not-an-operator"}
    elif defect == "missing_selector":
        query.pop("selector")
    elif defect == "missing_source":
        query.pop("source")
    elif defect == "missing_edge":
        query["expr"].pop("edge")
    elif defect == "nested_unknown_operator":
        query["expr"] = {"kind": "seq", "left": query["expr"],
                         "right": {"kind": "not-an-operator"}}
    elif defect == "wrong_label_type":
        query["source"]["label"] = ["people.person"]
    elif defect == "wrong_properties_type":
        query["target"]["properties"] = []
    elif defect == "invalid_variable_types":
        query["expr"]["edge"]["var"] = query["source"]["var"]
    else:
        query["selector"] = {"kind": "ANY_K", "k": None}
    _write_jsonl(comparison_inputs["reference_interpretations_path"], [reference])
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)
    output = comparison_inputs["output_root"]
    assert len(_read_rows(output / "retrieval.jsonl")) == 2
    seal = json.loads((output / "retrieval_seal.json").read_text())
    assert seal["reference_content_read"] is False
    assert sha256_file(output / "retrieval.jsonl") == seal["file_hashes"]["retrieval.jsonl"]
    assert not (output / "comparison.json").exists()
    status = json.loads((output / "run_status.json").read_text())
    assert status["status"] == "failed"
    assert status["failed_stage"] == "evaluation"


@pytest.mark.parametrize("question_ids", [(), ("q2",), ("q1", "q1"), ("q1", "q2")])
def test_invalid_or_different_question_population_is_refused(comparison_inputs, question_ids):
    comparison_inputs["question_ids"] = question_ids
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)


def test_changed_question_text_is_refused(comparison_inputs):
    _write_jsonl(comparison_inputs["inference_questions_path"],
                 [{"question_id": "q1", "text": "Bob Example"}])
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)


def test_duplicate_question_records_are_refused(comparison_inputs):
    _write_jsonl(comparison_inputs["inference_questions_path"], [
        {"question_id": "q1", "text": "Alice Example"},
        {"question_id": "q1", "text": "Alice Example"},
    ])
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)


def test_variants_cannot_be_swapped_or_reuse_one_catalog(comparison_inputs):
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**{
            **comparison_inputs,
            "legacy_catalog_root": comparison_inputs["eligible_catalog_root"],
            "eligible_catalog_root": comparison_inputs["legacy_catalog_root"],
        })
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**{
            **comparison_inputs,
            "eligible_catalog_root": comparison_inputs["legacy_catalog_root"],
        })


def test_reachability_uses_per_question_catalog_not_union_of_all_entities(build_inputs):
    options, state = build_inputs
    _write_jsonl(options["inference_questions_path"], [
        {"question_id": "q1", "text": "Alice Example"},
        {"question_id": "q2", "text": "Bob Example"},
    ])
    state["extra_rows"] = [("m.bob", local.NAME_PREDICATE, "Bob", "en", False)]
    arguments = _build_pair(build_inputs, question_ids=("q1", "q2"))
    _write_jsonl(arguments["reference_interpretations_path"],
                 [_reference("q1", "m.bob"), _reference("q2", "m.bob")])
    report = comparison.compare_local_catalogs(**arguments)
    for variant in ("legacy", "eligible"):
        rows = report["variants"][variant]["reachability"]["rows"]
        assert [row["catalog"]["entity"]["reachable"] for row in rows] == [False, True]
    delta = report["coverage_changes"]["catalog"]["entity"]
    assert delta["legacy_count"] == delta["eligible_count"] == 1
    assert delta["denominator"] == 2
    assert delta["gained_question_ids"] == delta["lost_question_ids"] == []


def test_coverage_change_reporting_retains_gains_losses_and_unchanged_cases():
    def row(qid, reachable):
        coverage = {kind: {"reachable": reachable} for kind in
                    ("entity", "relation", "type", "effective_type", "joint")}
        return {"question_id": qid, "catalog": coverage,
                "retrieval": {"20": coverage}, "deployed_prompt": coverage}

    audits = {
        "legacy": {"rows": [row("gain", False), row("loss", True),
                             row("same-good", True), row("same-bad", False)]},
        "eligible": {"rows": [row("gain", True), row("loss", False),
                               row("same-good", True), row("same-bad", False)]},
    }
    changes = comparison._coverage_changes(audits, 20)
    for stage in ("catalog", "retrieval", "deployed_prompt"):
        for delta in changes[stage].values():
            assert delta == {
                "legacy_count": 2, "eligible_count": 2, "denominator": 4,
                "legacy_ratio": 0.5, "eligible_ratio": 0.5,
                "gained_question_ids": ["gain"], "lost_question_ids": ["loss"],
                "unchanged_reachable_question_ids": ["same-good"],
                "unchanged_unreachable_question_ids": ["same-bad"],
            }


def test_retrieval_failure_is_not_retried_or_followed_by_reference_evaluation(
    comparison_inputs, monkeypatch,
):
    original = comparison.GrailQAInferenceCatalogV2.retrieve
    calls = []

    def fail_eligible(catalog, *args, **kwargs):
        calls.append(catalog.root.name)
        if catalog.root == comparison_inputs["eligible_catalog_root"]:
            raise RuntimeError("injected local retrieval failure")
        return original(catalog, *args, **kwargs)

    def reference_must_not_open(*args, **kwargs):
        raise AssertionError("reference was read after incomplete retrieval")

    monkeypatch.setattr(comparison.GrailQAInferenceCatalogV2, "retrieve", fail_eligible)
    monkeypatch.setattr(comparison, "_read_references", reference_must_not_open)
    with pytest.raises(RuntimeError, match="injected"):
        comparison.compare_local_catalogs(**comparison_inputs)
    assert calls == ["legacy-catalog", "eligible-catalog"]
    output = comparison_inputs["output_root"]
    assert not (output / "retrieval_seal.json").exists()
    assert not (output / "comparison.json").exists()
    status = json.loads((output / "run_status.json").read_text())
    assert status["status"] == "failed"
    assert status["failed_stage"] == "retrieval"
    assert len(_read_rows(output / "retrieval.jsonl")) == 1


@pytest.mark.parametrize("target", ["reference", "questions", "retrieval", "seal", "catalog"])
def test_mutated_evaluation_inputs_or_sealed_evidence_cannot_publish_success(
    comparison_inputs, monkeypatch, target,
):
    original = comparison._read_references
    output = comparison_inputs["output_root"]

    def mutate_after_read(path, question_ids):
        references = original(path, question_ids)
        if target == "reference":
            destination = path
        elif target == "questions":
            destination = comparison_inputs["inference_questions_path"]
        elif target == "retrieval":
            destination = output / "retrieval.jsonl"
        elif target == "seal":
            destination = output / "retrieval_seal.json"
        else:
            destination = comparison_inputs["legacy_catalog_root"] / "manifest.json"
        destination.write_text(destination.read_text() + "\n", encoding="utf-8")
        if target == "seal":
            value = json.loads(destination.read_text())
            value["paper_result"] = True
            destination.write_text(json.dumps(value), encoding="utf-8")
        return references

    monkeypatch.setattr(comparison, "_read_references", mutate_after_read)
    with pytest.raises(ValueError):
        comparison.compare_local_catalogs(**comparison_inputs)
    assert not (output / "comparison.json").exists()
    assert json.loads((output / "run_status.json").read_text())["status"] == "failed"
