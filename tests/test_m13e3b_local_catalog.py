from __future__ import annotations

import inspect
import json
from pathlib import Path
import sqlite3

import pytest

from xgap.experiments.freebase_sources import (
    ALIAS_PREDICATE,
    HF_FREEBASE_REVISION,
    NAME_PREDICATE,
    TYPE_PREDICATE,
    ParquetTripleRecord,
)
from xgap.experiments.grailqa_catalog_v2 import GrailQAInferenceCatalogV2
from xgap.experiments.grailqa_local_diagnostics import relation_type_diagnostics
from xgap.experiments.grailqa_reachability import CatalogUniverse
from xgap.experiments import grailqa_local_catalog as local


ROOT = Path(__file__).resolve().parents[1]


def test_anchor_extraction_is_deterministic_and_normalized() -> None:
    first = local.extract_query_anchors("Where was Alice-Example born?")
    second = local.extract_query_anchors("Where was Alice-Example born?")

    assert first == second
    assert "alice example" in first
    assert "where" not in first
    assert "alice example born" in first


def test_batched_selection_equals_independent_selection_and_is_query_isolated() -> None:
    questions = (
        local.InferenceQuestion("q1", "Where was Alice born?"),
        local.InferenceQuestion("q2", "What is Paris?"),
    )
    records = _records()
    batched = local.select_query_candidates(questions, records)
    independent = {
        question.question_id: local.select_query_candidates((question,), records)[
            question.question_id
        ]
        for question in questions
    }

    assert batched == independent
    assert [item.entity_id for item in batched["q1"]] == ["m.alice"]
    assert [item.entity_id for item in batched["q2"]] == ["m.paris"]
    assert batched["q1"][0].source_shard == "default/data/0000.parquet"


def test_selection_filters_predicates_language_and_invalid_mids() -> None:
    question = (local.InferenceQuestion("q1", "Who is Alicia Alice?"),)
    candidates = local.select_query_candidates(question, _records())["q1"]

    assert [item.entity_id for item in candidates] == ["m.alice"]
    assert candidates[0].matched_label == "Alice"
    assert all(item.match_type.startswith("exact_normalized_") for item in candidates)


def test_question_loader_rejects_gold_fields(tmp_path: Path) -> None:
    questions = tmp_path / "questions.jsonl"
    questions.write_text(
        json.dumps({"question_id": "q1", "text": "Alice", "answer": "m.alice"})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-inference fields"):
        local.load_inference_questions(questions, question_ids=("q1",))
    assert set(inspect.signature(local.build_local_catalog).parameters).isdisjoint(
        {"gold", "answer", "logical_form", "reference", "reference_interpretations_path"}
    )


def test_local_build_is_gold_blind_filtered_typed_and_catalog_v2_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    catalog_root = fixture["catalog"]
    manifest = json.loads((catalog_root / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["gold_used_for_construction"] is False
    assert manifest["sources"]["freebase_archival_parquet"]["revision"] == HF_FREEBASE_REVISION
    assert manifest["counts"]["questions"] == 2
    assert manifest["counts"]["unique_candidate_mids"] == 2
    assert manifest["counts"]["query_candidate_assignments"] == 2
    assert manifest["counts"]["entity_types"] == 2
    assert manifest["scan"]["passes"] == 2
    assert fixture["calls"][0]["predicates"] == (NAME_PREDICATE, ALIAS_PREDICATE)
    assert fixture["calls"][1]["predicates"] == (
        NAME_PREDICATE,
        ALIAS_PREDICATE,
        TYPE_PREDICATE,
    )
    assert fixture["calls"][1]["subject_ids"] == ("m.alice", "m.paris")
    assert not (tmp_path / "reference_interpretations.jsonl").exists()
    assert fixture["inference_inputs_read"] == [fixture["questions"]]

    reused = local.build_local_catalog(
        inference_questions_path=fixture["questions"],
        question_ids=("q1", "q2"),
        workload_name="fixture",
        artifact_id="grailqa-local-catalog-fixture-v1",
        freebase_parquet_root=fixture["parquet_root"],
        source_manifest_path=fixture["source_manifest"],
        normalized_ontology_path=fixture["ontology"],
        reverse_properties_path=fixture["reverse"],
        output_root=catalog_root,
        staging_root=tmp_path / "node-local",
    )
    assert reused["catalog_hash"] == manifest["catalog_hash"]
    assert len(fixture["calls"]) == 2

    catalog = GrailQAInferenceCatalogV2.load(catalog_root)
    alice = catalog.retrieve("q1", "Where was Alice born?", top_k=20)
    paris = catalog.retrieve("q2", "What is Paris?", top_k=20)
    assert [item.candidate_id for item in alice.entities] == ["m.alice"]
    assert [item.candidate_id for item in paris.entities] == ["m.paris"]
    with pytest.raises(ValueError, match="differs from the text"):
        catalog.retrieve("q1", "What is Paris?", top_k=20)
    with pytest.raises(ValueError, match="differs from the frozen"):
        catalog.retrieve(
            "q1",
            "Where was Alice born?",
            allowed_entity_ids=("m.paris",),
        )


def test_query_local_retrieval_preserves_persisted_rank_and_question_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = _ranked_local_catalog_fixture(tmp_path)

    def reject_global_fts(*args: object, **kwargs: object) -> object:
        raise AssertionError("Query-local retrieval called the global FTS ranker.")

    monkeypatch.setattr(
        GrailQAInferenceCatalogV2, "_retrieve_entities", reject_global_fts
    )
    question = "white-faced whistling duck is an exhibit at what zoo?"
    complete = catalog.retrieve("q-white", question, top_k=20)
    expected = ["m.duck", "m.white1", "m.white2", "m.white3", "m.white4"]

    assert [item.candidate_id for item in complete.entities] == expected
    assert complete.entities[0].label == "White-faced Whistling-Duck"
    assert complete.entities[0].score == 2.44
    assert complete.entities[0].rank == 1
    assert complete.to_dict()["config"]["entity_retrieval_mode"] == (
        "query_local_persisted_rank"
    )
    assert "m.other" not in expected

    for top_k in (1, 5, 10, 20):
        result = catalog.retrieve("q-white", question, top_k=top_k)
        assert [item.candidate_id for item in result.entities] == expected[:top_k]

    other = catalog.retrieve("q-other", "what is the other white thing?", top_k=20)
    repeated = catalog.retrieve("q-white", question, top_k=20)
    assert [item.candidate_id for item in other.entities] == ["m.other"]
    assert repeated.to_dict() == complete.to_dict()


def test_global_catalog_still_delegates_to_unchanged_fts_entity_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_catalog = _ranked_local_catalog_fixture(tmp_path)
    global_catalog = GrailQAInferenceCatalogV2(
        root=local_catalog.root,
        manifest={"catalog_hash": "global-fixture"},
        ontology=local_catalog.ontology,
        terms=local_catalog.terms,
    )
    calls: list[tuple[str, int, object]] = []
    expected = local_catalog._retrieve_entities(
        "white-faced whistling duck is an exhibit at what zoo?", 3, None
    )
    original = GrailQAInferenceCatalogV2._retrieve_entities

    def recording_global_fts(
        self: GrailQAInferenceCatalogV2,
        question: str,
        top_k: int,
        allowed_entity_ids: object = None,
    ) -> object:
        calls.append((question, top_k, allowed_entity_ids))
        return original(self, question, top_k, allowed_entity_ids)  # type: ignore[arg-type]

    monkeypatch.setattr(
        GrailQAInferenceCatalogV2, "_retrieve_entities", recording_global_fts
    )
    result = global_catalog.retrieve(
        "arbitrary-global-id",
        "white-faced whistling duck is an exhibit at what zoo?",
        top_k=3,
    )

    assert result.entities == expected
    assert calls == [
        ("white-faced whistling duck is an exhibit at what zoo?", 3, None)
    ]
    config = result.to_dict()["config"]
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


def test_materialization_normalizes_posixpath_source_shard_only(
    tmp_path: Path,
) -> None:
    ontology, reverse = _schema(tmp_path)
    output = tmp_path / "materialized"
    output.mkdir()
    question = local.InferenceQuestion("q-path", "Where was Alice born?")
    candidate = local.LocalCandidateMatch(
        question_id=question.question_id,
        entity_id="m.alice",
        matched_label="Alice",
        normalized_label="alice",
        match_type="exact_normalized_alias",
        score=2.25,
        source_shard=Path("default/data/0000.parquet"),  # type: ignore[arg-type]
        rank=1,
    )
    metadata = local._CandidateMetadata(
        canonical_names={"m.alice": "Alice Example"},
        aliases={"m.alice": (("Alice Example", "canonical"), ("Alice", "alias"))},
        types={"m.alice": ("people.person",)},
    )

    local._materialize_subset(
        output=output,
        questions=(question,),
        candidates={question.question_id: (candidate,)},
        metadata=metadata,
        ontology_path=ontology,
        reverse_path=reverse,
    )

    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        row = connection.execute(
            "SELECT question_id,entity_id,rank,lexical_score,matched_label,"
            "normalized_label,match_type,source_shard FROM query_entity_candidates"
        ).fetchone()
    finally:
        connection.close()
    assert row == (
        "q-path",
        "m.alice",
        1,
        2.25,
        "Alice",
        "alice",
        "exact_normalized_alias",
        "default/data/0000.parquet",
    )
    assert candidate.to_dict()["source_shard"] == "default/data/0000.parquet"
    assert local._sqlite_row((7, 2.5, b"raw", None)) == (7, 2.5, b"raw", None)


def test_local_reachability_separates_local_catalog_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    references = tmp_path / "references.jsonl"
    references.write_text(
        "".join(
            json.dumps(_reference("q1", "m.alice")) + "\n"
            for _ in range(1)
        )
        + json.dumps(_reference("q2", "m.missing"))
        + "\n",
        encoding="utf-8",
    )
    workload = tmp_path / "workload.jsonl"
    workload.write_text(
        json.dumps({"question_id": "q1", "Q": 13, "path_length": 1})
        + "\n"
        + json.dumps({"question_id": "q2", "Q": 13, "path_length": 1})
        + "\n",
        encoding="utf-8",
    )
    before_summary = {
        "summary": {
            "retrieval": {
                key: {"entity": {"count": 0, "ratio": 0.0}}
                for key in ("1", "5", "10", "20")
            },
            "deployed_prompt": {
                "entity": {"count": 0, "ratio": 0.0},
                "joint": {"count": 0, "ratio": 0.0},
            },
        }
    }
    (fixture["catalog"] / "audit_summary.json").write_text(  # type: ignore[operator]
        json.dumps(before_summary), encoding="utf-8"
    )

    audit = local.run_local_reachability_audit(
        catalog_root=fixture["catalog"],
        inference_questions_path=fixture["questions"],
        question_ids=("q1", "q2"),
        reference_interpretations_path=references,
        workload_stats_path=workload,
        output_root=fixture["catalog"],
    )

    assert audit["gold_usage"] == "evaluation_only_after_retrieval_persisted"
    assert audit["stage_failure_counts"]["counts"][
        "reference_not_in_local_catalog"
    ] == 1
    assert audit["gate"]["minimum_joint_ratio"] == 0.20
    comparison = json.loads(
        (fixture["catalog"] / "entity_retrieval_before_after.json").read_text()  # type: ignore[operator]
    )
    assert comparison["before"]["entity_recall"]["20"]["ratio"] == 0.0
    assert comparison["after"]["entity_recall"]["20"]["ratio"] == 0.5
    assert comparison["after"]["entity_prompt_coverage"]["ratio"] == 0.5
    relation_diagnostics = [
        json.loads(line)
        for line in (
            fixture["catalog"] / "relation_diagnostics.jsonl"  # type: ignore[operator]
        ).read_text().splitlines()
    ]
    type_diagnostics = [
        json.loads(line)
        for line in (
            fixture["catalog"] / "type_diagnostics.jsonl"  # type: ignore[operator]
        ).read_text().splitlines()
    ]
    assert len(relation_diagnostics) == 2
    assert relation_diagnostics[0]["required_reference_relation_sequence"] == [
        "people.person.place_of_birth"
    ]
    assert {"rank", "score"} <= set(
        relation_diagnostics[0]["retrieved_relation_slots"][0]["candidates"][0]
    )
    assert len(type_diagnostics) == 2
    assert type_diagnostics[0]["required_reference_types"] == [
        "location.location",
        "people.person",
    ]
    assert audit["relation_type_diagnostic_stage_counts"]["relation"][
        "question_count"
    ] == 2
    schema_comparison = json.loads(
        (fixture["catalog"] / "schema_ranking_before_after.json").read_text()  # type: ignore[operator]
    )
    assert schema_comparison["ranking_contract"]["schema_ranking_version"] == (
        "m13e3b3-ontology-aware-schema-ranking-v1"
    )
    assert schema_comparison["ranking_contract"]["gold_inputs"] is False
    relation_ranking = [
        json.loads(line)
        for line in (
            fixture["catalog"] / "relation_ranking_audit.jsonl"  # type: ignore[operator]
        ).read_text().splitlines()
    ]
    type_ranking = [
        json.loads(line)
        for line in (
            fixture["catalog"] / "type_ranking_audit.jsonl"  # type: ignore[operator]
        ).read_text().splitlines()
    ]
    assert relation_ranking[0]["gold_usage"] == (
        "post_ranking_diagnostic_selection_only"
    )
    assert relation_ranking[0]["required_relation_rankings"][0]["legacy"]
    assert relation_ranking[0]["required_relation_rankings"][0]["repaired"]
    assert type_ranking[0]["required_type_rankings"][0]["repaired"][
        "type_provenance"
    ]
    for name in (
        "catalog_coverage.json",
        "retrieval_metrics.json",
        "prompt_reachability.json",
        "stage_failure_counts.json",
        "entity_retrieval_before_after.json",
        "relation_diagnostics.jsonl",
        "type_diagnostics.jsonl",
        "schema_ranking_before_after.json",
        "relation_ranking_audit.jsonl",
        "type_ranking_audit.jsonl",
        "relation_diagnostics_v2.jsonl",
        "type_diagnostics_v2.jsonl",
        "audit_summary.json",
    ):
        assert (fixture["catalog"] / name).is_file()

    historical_relation_diagnostics = (
        fixture["catalog"] / "relation_diagnostics.jsonl"  # type: ignore[operator]
    ).read_text()
    historical_hash = local.sha256_file(
        fixture["catalog"] / "relation_diagnostics.jsonl"  # type: ignore[operator]
    )
    local.run_local_reachability_audit(
        catalog_root=fixture["catalog"],
        inference_questions_path=fixture["questions"],
        question_ids=("q1", "q2"),
        reference_interpretations_path=references,
        workload_stats_path=workload,
        output_root=fixture["catalog"],
    )
    assert (
        fixture["catalog"] / "relation_diagnostics.jsonl"  # type: ignore[operator]
    ).read_text() == historical_relation_diagnostics
    rerun_comparison = json.loads(
        (fixture["catalog"] / "schema_ranking_before_after.json").read_text()  # type: ignore[operator]
    )
    assert rerun_comparison["preserved_before_artifact_hashes"][
        "relation_diagnostics.jsonl"
    ] == historical_hash


def test_comparison_keeps_unavailable_full_catalog_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    audit = {
        "summary": {
            "catalog": {"entity": {"ratio": 0.5}},
            "retrieval": {"20": {"entity": {"ratio": 0.25}}},
            "deployed_prompt": {"joint": {"ratio": 0.2}},
        }
    }
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    output = tmp_path / "comparison.json"

    result = local.compare_full_and_local(
        local_catalog_root=fixture["catalog"],
        local_audit_path=audit_path,
        output_path=output,
    )

    assert result["full_status"] == "pending_global_build"
    assert all(item["full"] is None for item in result["metrics"].values())
    assert result["metrics"]["joint_prompt_reachability"]["local"] == 0.2


def test_relation_type_diagnostics_separate_universe_retrieval_and_prompt_loss() -> None:
    references = (
        _diagnostic_reference("q-universe", "r.missing", "t.missing"),
        _diagnostic_reference("q-retrieval", "r.gold", "t.gold"),
        _diagnostic_reference("q-prompt", "r.gold", "t.gold"),
    )
    decoys = [
        {
            "id": f"r.decoy{index}",
            "label": f"decoy {index}",
            "matched_label": f"decoy {index}",
            "rank": index,
            "score": 10.0 - index,
        }
        for index in range(1, 5)
    ]
    type_decoys = [
        {
            "id": f"t.decoy{index}",
            "label": f"type decoy {index}",
            "matched_label": f"type decoy {index}",
            "rank": index,
            "score": 10.0 - index,
        }
        for index in range(1, 5)
    ]
    retrieval_rows = (
        _diagnostic_retrieval("q-universe", [], []),
        _diagnostic_retrieval("q-retrieval", decoys, type_decoys),
        _diagnostic_retrieval(
            "q-prompt",
            [
                *decoys,
                {
                    "id": "r.gold",
                    "label": "gold",
                    "matched_label": "gold",
                    "rank": 5,
                    "score": 1.0,
                },
            ],
            [
                *type_decoys,
                {
                    "id": "t.gold",
                    "label": "gold type",
                    "matched_label": "gold type",
                    "rank": 5,
                    "score": 1.0,
                },
            ],
        ),
    )
    relations, types = relation_type_diagnostics(
        references=references,
        retrieval_rows=retrieval_rows,
        catalog=CatalogUniverse(
            "fixture",
            "hash",
            frozenset(),
            frozenset({"r.gold"}),
            frozenset({"t.gold"}),
        ),
        prompt_limit=4,
    )

    assert [item["failure_stage"] for item in relations] == [
        "ontology_universe",
        "retrieval",
        "prompt_truncation",
    ]
    assert [item["failure_stage"] for item in types] == [
        "ontology_universe",
        "retrieval",
        "prompt_truncation",
    ]
    assert relations[2]["required_relation_diagnostics"][0]["retrieval_rank"] == 5
    assert not relations[2]["required_relation_diagnostics"][0]["prompt_visible"]


def test_local_slurm_job_is_cpu_only_separate_and_has_no_qwen() -> None:
    server = (ROOT / "scripts/server/build_grailqa_local_catalog.sh").read_text()
    slurm = (ROOT / "scripts/slurm/build_grailqa_local_catalog.sbatch").read_text()

    assert "XGAP_GRAILQA_LOCAL_CATALOG_ROOT" in server
    assert "XGAP_LOCAL_CATALOG_STAGING_ROOT" in server
    assert "preflight18|pilot150" in server
    assert "--audit-only" in server
    assert "#SBATCH --cpus-per-task=8" in slurm
    assert "#SBATCH --mem=48G" in slurm
    assert "module load Miniconda3" in slurm
    assert "XGAP_LOCAL_CATALOG_AUDIT_ONLY" in slurm
    assert "python --version" in slurm
    assert "#SBATCH --gres" not in slurm
    assert "DASHSCOPE" not in slurm
    assert "vllm" not in slurm.casefold()
    assert ".catalog-v2.building" not in slurm


def _build_fixture(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    questions = root / "questions.jsonl"
    questions.write_text(
        json.dumps({"question_id": "q1", "text": "Where was Alice born?"})
        + "\n"
        + json.dumps({"question_id": "q2", "text": "What is Paris?"})
        + "\n",
        encoding="utf-8",
    )
    ontology, reverse = _schema(root)
    parquet_root = root / "parquet"
    parquet_root.mkdir()
    source_manifest = root / "source_manifest.json"
    source_manifest.write_text("{}\n", encoding="utf-8")
    calls: list[dict[str, object]] = []
    inference_inputs_read: list[Path] = []
    original_read_jsonl = local._read_jsonl

    def guarded_read_jsonl(path: Path):
        resolved = Path(path)
        if any(token in resolved.name.casefold() for token in ("reference", "gold", "answer")):
            raise AssertionError(f"Construction attempted to read evaluation input: {resolved}")
        inference_inputs_read.append(resolved)
        return original_read_jsonl(resolved)

    monkeypatch.setattr(local, "_read_jsonl", guarded_read_jsonl)

    monkeypatch.setattr(
        local,
        "verify_parquet_source_manifest",
        lambda **_: {
            "status": "ok",
            "shard_count": 964,
            "total_bytes": 32_476_432_840,
        },
    )
    monkeypatch.setattr(
        local,
        "load_parquet_source_manifest",
        lambda _: {"resolved_parquet_revision": HF_FREEBASE_REVISION},
    )

    def fake_records(**kwargs: object):
        predicates = tuple(kwargs["predicates"])
        subject_ids = (
            None
            if kwargs.get("subject_ids") is None
            else tuple(kwargs["subject_ids"])
        )
        calls.append({"predicates": predicates, "subject_ids": subject_ids})
        statistics = kwargs["statistics"]
        assert isinstance(statistics, dict)
        statistics.update({"parquet_shards": 1, "input_rows": len(_records())})
        for record in _records():
            subject, predicate, *_ = record.triple
            if predicate not in predicates:
                continue
            if subject_ids is not None and subject not in subject_ids:
                continue
            yield record

    monkeypatch.setattr(local, "iter_parquet_triple_records", fake_records)
    catalog = root / "catalog"
    local.build_local_catalog(
        inference_questions_path=questions,
        question_ids=("q1", "q2"),
        workload_name="fixture",
        artifact_id="grailqa-local-catalog-fixture-v1",
        freebase_parquet_root=parquet_root,
        source_manifest_path=source_manifest,
        normalized_ontology_path=ontology,
        reverse_properties_path=reverse,
        output_root=catalog,
        staging_root=root / "node-local",
    )
    monkeypatch.setattr(local, "_read_jsonl", original_read_jsonl)
    return {
        "catalog": catalog,
        "questions": questions,
        "calls": calls,
        "inference_inputs_read": inference_inputs_read,
        "parquet_root": parquet_root,
        "source_manifest": source_manifest,
        "ontology": ontology,
        "reverse": reverse,
    }


def _ranked_local_catalog_fixture(root: Path) -> GrailQAInferenceCatalogV2:
    ontology, reverse = _schema(root)
    output = root / "ranked-local-catalog"
    output.mkdir()
    questions = (
        local.InferenceQuestion(
            "q-white", "white-faced whistling duck is an exhibit at what zoo?"
        ),
        local.InferenceQuestion("q-other", "what is the other white thing?"),
    )
    candidate_specs = (
        ("m.duck", "White-faced Whistling-Duck", 2.44, 1),
        ("m.white1", "WHITE", 1.2, 2),
        ("m.white2", "White", 1.1, 3),
        ("m.white3", "WHITE", 1.0, 4),
        ("m.white4", "White", 0.9, 5),
    )
    candidates = {
        "q-white": tuple(
            local.LocalCandidateMatch(
                question_id="q-white",
                entity_id=entity_id,
                matched_label=label,
                normalized_label=local.normalized_label(label),
                match_type="exact_normalized_name",
                score=score,
                source_shard="default/data/0000.parquet",
                rank=rank,
            )
            for entity_id, label, score, rank in candidate_specs
        ),
        "q-other": (
            local.LocalCandidateMatch(
                question_id="q-other",
                entity_id="m.other",
                matched_label="Other White Thing",
                normalized_label="other white thing",
                match_type="exact_normalized_name",
                score=2.33,
                source_shard="default/data/0001.parquet",
                rank=1,
            ),
        ),
    }
    labels = {
        entity_id: ((label, "canonical"),)
        for entity_id, label, _, _ in candidate_specs
    }
    labels["m.other"] = (("Other White Thing", "canonical"),)
    metadata = local._CandidateMetadata(
        canonical_names={key: values[0][0] for key, values in labels.items()},
        aliases=labels,
        types={key: () for key in labels},
    )
    local._materialize_subset(
        output=output,
        questions=questions,
        candidates=candidates,
        metadata=metadata,
        ontology_path=ontology,
        reverse_path=reverse,
    )
    ontology_graph = local.OntologyGraph.from_dict(
        local.load_yaml_mapping(ontology)
    )
    return GrailQAInferenceCatalogV2(
        root=output,
        manifest={
            "catalog_hash": "query-local-fixture",
            "requires_query_entity_filter": True,
        },
        ontology=ontology_graph,
        terms=(),
    )


def _records() -> tuple[ParquetTripleRecord, ...]:
    shard = "default/data/0000.parquet"
    return (
        _record("m.alice", NAME_PREDICATE, "Alice Example", "en", False, shard),
        _record("m.alice", ALIAS_PREDICATE, "Alice", "en", False, shard),
        _record("m.alice", ALIAS_PREDICATE, "Alicia", "es", False, shard),
        _record("m.alice", TYPE_PREDICATE, "people.person", None, True, shard),
        _record("m.paris", NAME_PREDICATE, "Paris", "en", False, shard),
        _record("m.paris", TYPE_PREDICATE, "location.location", None, True, shard),
        _record("x.invalid", ALIAS_PREDICATE, "Alice", "en", False, shard),
        _record("m.alice", "people.person.parents", "m.parent", None, True, shard),
    )


def _record(
    subject: str,
    predicate: str,
    value: str,
    language: str | None,
    is_resource: bool,
    shard: str,
) -> ParquetTripleRecord:
    return ParquetTripleRecord(
        triple=(subject, predicate, value, language, is_resource),
        source_shard=shard,
    )


def _schema(root: Path) -> tuple[Path, Path]:
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


def _diagnostic_reference(
    question_id: str, relation_id: str, type_id: str
) -> dict[str, object]:
    return {
        "question_id": question_id,
        "pattern_query": {
            "source": {"var": "answer", "label": type_id, "properties": {}},
            "expr": {
                "kind": "rel",
                "edge": {"label": relation_id},
            },
            "target": {"var": "anchor", "label": None, "properties": {}},
        },
    }


def _diagnostic_retrieval(
    question_id: str,
    relation_candidates: list[dict[str, object]],
    type_candidates: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "question_id": question_id,
        "entity_candidates": [],
        "relation_slots": [{"slot_id": "relation-hop-1", "candidates": relation_candidates}],
        "type_candidates": type_candidates,
    }
