"""Gold-free exhaustive checks for canonical eligibility before per-query Top-K."""

from __future__ import annotations

from dataclasses import replace
import inspect
from itertools import chain
from pathlib import Path
import random
import re
import sqlite3

import pytest

from xgap.experiments.freebase_sources import ALIAS_PREDICATE, NAME_PREDICATE, TYPE_PREDICATE, ParquetTripleRecord
from xgap.experiments.grailqa_catalog import normalized_label
from xgap.experiments.grailqa_eligible_candidates import select_eligible_query_candidates
from xgap.experiments.grailqa_local_catalog import InferenceQuestion, LocalCandidateMatch, extract_query_anchors


MID = re.compile(r"^[mg]\.[A-Za-z0-9_-]+$")


def record(mid, label, predicate=NAME_PREDICATE, *, language="en", resource=False, shard="synthetic/00.parquet"):
    return ParquetTripleRecord((mid, predicate, label, language, resource), shard)


def score(question, label):
    """Independent arithmetic for the frozen existing lexical score."""
    text = normalized_label(question)
    left, right = set(text.split()), set(label.split())
    value = len(left & right) / max(1, len(left | right))
    if f" {label} " in f" {text} ":
        value += 2.0 + min(len(right), 10) / 100.0
    return round(value, 12)


def key(candidate):
    # Existing ordering is preserved; exact name only breaks a previously
    # indistinguishable name/alias tie after every existing key component.
    return (-candidate.score, candidate.entity_id, candidate.matched_label,
            str(candidate.source_shard), candidate.match_type != "exact_normalized_name")


def exhaustive_oracle(questions, records, *, limit=50, min_tokens=1, max_tokens=8, omit_stopwords=True):
    """Full-record oracle, intentionally without bounded pruning or SQL.

    Existing normalization/anchor extraction are the unchanged lexical
    contract; eligibility, enumeration, scoring, deduplication and ranking are
    independently reconstructed here without calling either selector.
    """
    rows = tuple(records)
    eligible = {
        mid for row in rows
        for mid, predicate, value, language, resource in (row.triple,)
        if MID.fullmatch(mid) and predicate == NAME_PREDICATE and language == "en" and not resource
        and value.strip(" ")
    }
    expected, diagnostics = {}, {}
    for question in questions:
        anchors = set(extract_query_anchors(question.text, min_tokens=min_tokens,
                                           max_tokens=max_tokens, omit_stopword_only=omit_stopwords))
        best = {}
        for row in rows:
            mid, predicate, label, language, resource = row.triple
            normalized = normalized_label(label)
            if (not MID.fullmatch(mid) or language != "en" or resource
                    or predicate not in (NAME_PREDICATE, ALIAS_PREDICATE)
                    or not normalized or normalized not in anchors):
                continue
            match = LocalCandidateMatch(
                question.question_id, mid, label, normalized,
                "exact_normalized_name" if predicate == NAME_PREDICATE else "exact_normalized_alias",
                score(question.text, normalized), str(row.source_shard),
            )
            if mid not in best or key(match) < key(best[mid]):
                best[mid] = match
        all_ranked = sorted(best.values(), key=key)
        admissible = [candidate for candidate in all_ranked if candidate.entity_id in eligible]
        chosen = admissible[:limit]
        expected[question.question_id] = tuple(replace(candidate, rank=i) for i, candidate in enumerate(chosen, 1))
        legacy_top = all_ranked[:limit]
        legacy_retained = sum(candidate.entity_id in eligible for candidate in legacy_top)
        diagnostics[question.question_id] = {
            "matched_entity_count": len(best), "eligible_entity_count": len(admissible),
            "dropped_without_canonical_count": len(best)-len(admissible),
            "selected_count": len(chosen), "truncated_eligible_count": max(0, len(admissible)-limit),
            "legacy_topk_dropped_count": len(legacy_top)-legacy_retained,
            "backfilled_count": len(chosen)-legacy_retained,
        }
    return expected, diagnostics


def check_oracle(questions, records, **options):
    materialized = tuple(records)
    result = select_eligible_query_candidates(questions, iter(materialized), **options)
    expected, diagnostics = exhaustive_oracle(
        questions, materialized, limit=options.get("max_candidates_per_query", 50),
        min_tokens=options.get("anchor_min_tokens", 1), max_tokens=options.get("anchor_max_tokens", 8),
        omit_stopwords=options.get("omit_stopword_only", True),
    )
    assert result.candidates == expected
    assert result.diagnostics["schema_version"] == "m13e3b-canonical-eligible-selection-v2"
    assert result.diagnostics["selection_policy"] == "canonical_eligible_topk_v2"
    assert result.diagnostics["gold_inputs"] is False
    assert result.diagnostics["per_query"] == diagnostics
    return result


def test_alias_only_top1_cannot_displace_lower_scoring_canonical_entity():
    questions = (InferenceQuestion("q", "Alpha Beta"),)
    rows = (record("m.alias_only", "Alpha Beta", ALIAS_PREDICATE), record("m.valid", "Alpha"))
    result = check_oracle(questions, rows, max_candidates_per_query=1)
    chosen, = result.candidates["q"]
    assert chosen.entity_id == "m.valid"
    assert chosen.score == 2.51
    assert result.diagnostics["per_query"]["q"]["legacy_topk_dropped_count"] == 1
    assert result.diagnostics["per_query"]["q"]["backfilled_count"] == 1


def test_more_than_twice_k_ineligible_candidates_still_backfills_k():
    questions = (InferenceQuestion("q", "Alpha Beta"),)
    garbage = tuple(record(f"m.junk{i:02}", "Alpha Beta", ALIAS_PREDICATE) for i in range(13))
    legitimate = tuple(record(f"m.valid{i}", "Alpha") for i in range(4))
    result = check_oracle(questions, (*garbage, *legitimate), max_candidates_per_query=3)
    assert [x.entity_id for x in result.candidates["q"]] == ["m.valid0", "m.valid1", "m.valid2"]
    assert result.diagnostics["per_query"]["q"]["backfilled_count"] == 3
    assert result.diagnostics["per_query"]["q"]["truncated_eligible_count"] == 1


def test_canonical_eligibility_arriving_after_actual_sqlite_flush_still_backfills(tmp_path):
    questions = (InferenceQuestion("q", "Alpha Beta"),)
    rows = (
        record("m.valid0", "Alpha", ALIAS_PREDICATE), record("m.valid1", "Beta", ALIAS_PREDICATE),
        *(record(f"m.junk{i:05}", "Alpha Beta", ALIAS_PREDICATE) for i in range(5000)),
        record("m.valid0", "Formal Name Zero"), record("m.valid1", "Formal Name One"),
    )
    result = check_oracle(questions, rows, max_candidates_per_query=2, staging_root=tmp_path)
    assert [x.entity_id for x in result.candidates["q"]] == ["m.valid0", "m.valid1"]
    assert result.diagnostics["resource_usage"]["flush_count"] >= 2
    assert result.diagnostics["resource_usage"]["maximum_batch_rows"] <= 4096
    assert result.diagnostics["per_query"]["q"]["backfilled_count"] == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("canonical_first", [True, False])
@pytest.mark.parametrize("canonical_name", ["An Unrelated Formal Name", "..."])
def test_alias_qualifies_from_materializable_nonmatching_english_canonical(canonical_first, canonical_name):
    name = record("m.valid", canonical_name)
    alias = record("m.valid", "Alpha", ALIAS_PREDICATE)
    rows = (name, alias) if canonical_first else (alias, name)
    result = check_oracle((InferenceQuestion("q", "Alpha"),), rows, max_candidates_per_query=1)
    selected, = result.candidates["q"]
    assert selected.entity_id == "m.valid"
    assert selected.match_type == "exact_normalized_alias"


@pytest.mark.parametrize("canonical_first", [True, False])
@pytest.mark.parametrize("canonical_name", ["", " ", "   "])
def test_empty_or_ascii_space_canonical_drops_valid_alias_and_backfills(canonical_first, canonical_name):
    name = record("m.empty", canonical_name)
    alias = record("m.empty", "Alpha Beta", ALIAS_PREDICATE)
    rows = (name, alias) if canonical_first else (alias, name)
    result = check_oracle((InferenceQuestion("q", "Alpha Beta"),),
                          (*rows, record("m.valid", "Alpha")), max_candidates_per_query=1)
    selected, = result.candidates["q"]
    assert selected.entity_id == "m.valid"
    counts = result.diagnostics["per_query"]["q"]
    assert counts["matched_entity_count"] == 2
    assert counts["eligible_entity_count"] == 1
    assert counts["dropped_without_canonical_count"] == 1
    assert counts["legacy_topk_dropped_count"] == 1
    assert counts["backfilled_count"] == 1


@pytest.mark.parametrize("canonical_name", ["", " ", "   "])
@pytest.mark.parametrize("valid_first", [True, False])
def test_same_mid_empty_and_valid_canonical_remains_eligible(canonical_name, valid_first):
    empty, valid = record("m.valid", canonical_name), record("m.valid", "Unrelated Formal Name")
    names = (valid, empty) if valid_first else (empty, valid)
    rows = (*names, record("m.valid", "Alpha", ALIAS_PREDICATE))
    result = check_oracle((InferenceQuestion("q", "Alpha"),), rows, max_candidates_per_query=1)
    selected, = result.candidates["q"]
    assert selected.entity_id == "m.valid"
    assert selected.match_type == "exact_normalized_alias"
    assert result.diagnostics["per_query"]["q"]["dropped_without_canonical_count"] == 0
    assert result.diagnostics["resource_usage"]["canonical_entity_count"] == 1


@pytest.mark.parametrize("canonical_name", ["\t", "\n", "\u00a0", "\u2003", " \t ", " \u00a0 "])
def test_non_ascii_space_whitespace_preserves_sqlite_trim_eligibility(canonical_name):
    # SQLite trim(name) removes only U+0020. Python's unrestricted strip()
    # would silently change that existing final materialization contract.
    with sqlite3.connect(":memory:") as connection:
        assert connection.execute("SELECT trim(?) <> ''", (canonical_name,)).fetchone() == (1,)
    assert canonical_name.strip() == ""
    rows = (record("m.valid", canonical_name), record("m.valid", "Alpha", ALIAS_PREDICATE))
    result = check_oracle((InferenceQuestion("q", "Alpha"),), rows, max_candidates_per_query=1)
    selected, = result.candidates["q"]
    assert selected.entity_id == "m.valid"
    assert selected.match_type == "exact_normalized_alias"
    assert result.diagnostics["per_query"]["q"]["eligible_entity_count"] == 1


@pytest.mark.parametrize("canonical", [
    record("m.bad", "Other", language="fr"),
    record("m.bad", "Other", language="EN"),
    record("m.bad", "Other", language=None),
    record("m.bad", "Other", resource=True),
    record("m.bad", "Other", TYPE_PREDICATE),
])
def test_nonenglish_resource_or_nonname_cannot_supply_canonical_eligibility(canonical):
    result = check_oracle((InferenceQuestion("q", "Alpha"),),
                          (canonical, record("m.bad", "Alpha", ALIAS_PREDICATE)))
    assert result.candidates["q"] == ()
    assert result.diagnostics["per_query"]["q"]["dropped_without_canonical_count"] == 1


@pytest.mark.parametrize("mid", ["x.bad", "m.", "/m/id", "m.bad/slash", "", " m.space"])
def test_invalid_mid_never_matches_or_qualifies(mid):
    result = check_oracle((InferenceQuestion("q", "Alpha"),),
                          (record(mid, "Alpha"), record(mid, "Alpha", ALIAS_PREDICATE)))
    assert result.candidates["q"] == ()
    assert result.diagnostics["per_query"]["q"]["matched_entity_count"] == 0


def test_matching_label_must_itself_be_english_literal_allowed_predicate():
    rows = [record(f"m.entity{i}", "Unrelated Name") for i in range(4)]
    rows.extend((record("m.entity0", "Alpha", ALIAS_PREDICATE, language="fr"),
                 record("m.entity1", "Alpha", ALIAS_PREDICATE, resource=True),
                 record("m.entity2", "Alpha", TYPE_PREDICATE),
                 record("m.entity3", "Alpha", ALIAS_PREDICATE)))
    result = check_oracle((InferenceQuestion("q", "Alpha"),), rows)
    assert [x.entity_id for x in result.candidates["q"]] == ["m.entity3"]


def test_many_aliases_for_same_mid_consume_one_slot_and_keep_best_existing_score():
    rows = (record("m.one", "Formal One"), record("m.one", "Alpha", ALIAS_PREDICATE),
            record("m.one", "Beta", ALIAS_PREDICATE), record("m.one", "Alpha Beta", ALIAS_PREDICATE),
            record("m.two", "Beta"))
    result = check_oracle((InferenceQuestion("q", "Alpha Beta"),), rows * 3, max_candidates_per_query=2)
    assert [(x.entity_id, x.matched_label, x.rank) for x in result.candidates["q"]] == [
        ("m.one", "Alpha Beta", 1), ("m.two", "Beta", 2),
    ]


def test_name_alias_tie_break_is_deterministic_only_after_existing_key():
    questions = (InferenceQuestion("q", "Alpha"),)
    equal = (record("m.same", "Alpha", ALIAS_PREDICATE), record("m.same", "Alpha"))
    for rows in (equal, equal[::-1]):
        result = check_oracle(questions, rows)
        assert result.candidates["q"][0].match_type == "exact_normalized_name"
    # The old raw-label and shard ordering must still precede the new tie.
    for rows in (
        (record("m.same", "ALPHA", ALIAS_PREDICATE), record("m.same", "Alpha")),
        (record("m.same", "Alpha", ALIAS_PREDICATE, shard="a"), record("m.same", "Alpha", shard="z")),
    ):
        result = check_oracle(questions, rows)
        assert result.candidates["q"][0].match_type == "exact_normalized_alias"


def test_shard_path_provenance_is_preserved_as_string_for_deterministic_ordering():
    result = check_oracle((InferenceQuestion("q", "Alpha"),), (
        record("m.same", "Alpha", ALIAS_PREDICATE, shard=Path("synthetic/a.parquet")),
        record("m.same", "Alpha", shard=Path("synthetic/z.parquet")),
    ))
    candidate, = result.candidates["q"]
    assert candidate.source_shard == "synthetic/a.parquet"
    assert candidate.match_type == "exact_normalized_alias"


@pytest.mark.parametrize("options,ids", [
    ({}, ["m.multi", "m.alpha"]),
    ({"anchor_min_tokens": 2}, ["m.multi"]),
    ({"anchor_max_tokens": 1}, ["m.alpha"]),
    ({"omit_stopword_only": False}, ["m.multi", "m.alpha", "m.stop"]),
])
def test_existing_normalization_score_and_anchor_filters_preserved(options, ids):
    rows = (record("m.multi", "Alpha-Beta"), record("m.alpha", "ALPHA"),
            record("m.stop", "the"), record("m.short", "a"), record("m.noncontiguous", "Alpha the"))
    result = check_oracle((InferenceQuestion("q", "the AlphaBeta a"),), rows, **options)
    assert [x.entity_id for x in result.candidates["q"]] == ids


class Once:
    def __init__(self, rows):
        self.rows, self.iterations = rows, 0

    def __iter__(self):
        self.iterations += 1
        assert self.iterations == 1, "The record stream must not be rewound."
        yield from self.rows


def test_row_permutation_batch_boundaries_and_independent_queries_agree(tmp_path):
    questions = (InferenceQuestion("a", "Alpha Beta"), InferenceQuestion("b", "Gamma"), InferenceQuestion("empty", "No Match"))
    rows = (record("m.alpha", "Formal Name"), record("m.alpha", "Alpha", ALIAS_PREDICATE),
            record("m.gamma", "Gamma"), record("m.junk", "Alpha Beta", ALIAS_PREDICATE),
            record("m.beta", "Beta"), record("m.alpha", "ALPHA", ALIAS_PREDICATE))
    expected = check_oracle(questions, rows, staging_root=tmp_path, max_candidates_per_query=1)
    for batch_size in (1, 2, 4, 10):
        stream = Once(chain.from_iterable(rows[i:i+batch_size] for i in range(0, len(rows), batch_size)))
        observed = select_eligible_query_candidates(questions, stream, staging_root=tmp_path, max_candidates_per_query=1)
        assert observed.candidates == expected.candidates
        assert observed.diagnostics["per_query"] == expected.diagnostics["per_query"]
        assert stream.iterations == 1
    reversed_result = check_oracle(questions[::-1], rows[::-1], staging_root=tmp_path, max_candidates_per_query=1)
    assert reversed_result.candidates == expected.candidates
    for question in questions:
        single = check_oracle((question,), rows, staging_root=tmp_path, max_candidates_per_query=1)
        assert single.candidates[question.question_id] == expected.candidates[question.question_id]
        assert single.diagnostics["per_query"][question.question_id] == expected.diagnostics["per_query"][question.question_id]
    assert list(tmp_path.iterdir()) == []


def test_late_iterable_error_cleans_only_its_scratch_and_never_returns_partial(tmp_path):
    sentinel = tmp_path / "existing-evidence.txt"
    sentinel.write_text("preserve")
    rows = (record("m.valid", "Alpha"), record("m.junk", "Alpha", ALIAS_PREDICATE))

    class SourceFailure(RuntimeError):
        pass

    def broken():
        # Fail after at least one actual SQLite flush, not only an in-memory
        # prefix; the owned spool must still be removed without publication.
        yield from rows * 2500
        raise SourceFailure("Synthetic late source failure")

    with pytest.raises(SourceFailure, match="late source failure"):
        select_eligible_query_candidates((InferenceQuestion("q", "Alpha"),), broken(), staging_root=tmp_path)
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_text() == "preserve"
    check_oracle((InferenceQuestion("q", "Alpha"),), rows, staging_root=tmp_path)
    assert list(tmp_path.iterdir()) == [sentinel]


@pytest.mark.parametrize("questions,rows", [
    ((), (record("m.valid", "Alpha"),)),
    ((InferenceQuestion("q", "Alpha"),), ()),
    ((InferenceQuestion("q", "the a"),), (record("m.valid", "the"),)),
])
def test_empty_queries_matches_and_source_preserve_query_inventory(questions, rows, tmp_path):
    result = check_oracle(questions, rows, staging_root=tmp_path)
    assert result.candidates == {question.question_id: () for question in questions}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("options", [
    {"max_candidates_per_query": 0}, {"max_candidates_per_query": -1},
    {"max_candidates_per_query": True}, {"max_candidates_per_query": 1.5},
    {"max_candidates_per_query": 901},
    {"anchor_min_tokens": 0}, {"anchor_min_tokens": True},
    {"anchor_max_tokens": 0}, {"anchor_max_tokens": 2.5},
    {"anchor_min_tokens": 3, "anchor_max_tokens": 2}, {"omit_stopword_only": "yes"},
])
def test_invalid_bounds_fail_before_consuming_source_or_creating_scratch(options, tmp_path):
    stream = Once((record("m.valid", "Alpha"),))
    with pytest.raises((TypeError, ValueError)):
        select_eligible_query_candidates((InferenceQuestion("q", "Alpha"),), stream, staging_root=tmp_path, **options)
    assert stream.iterations == 0
    assert list(tmp_path.iterdir()) == []


def test_duplicate_question_ids_fail_before_source_or_scratch(tmp_path):
    stream = Once((record("m.valid", "Alpha"),))
    with pytest.raises(ValueError):
        select_eligible_query_candidates((InferenceQuestion("q", "Alpha"), InferenceQuestion("q", "Beta")),
                                         stream, staging_root=tmp_path)
    assert stream.iterations == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("question", [InferenceQuestion("", "Alpha"), InferenceQuestion(1, "Alpha"),
    InferenceQuestion("q", ""), InferenceQuestion("q", "   "), InferenceQuestion("q", None)])
def test_malformed_question_identity_or_text_fails_before_scanning(question, tmp_path):
    stream = Once((record("m.valid", "Alpha"),))
    with pytest.raises(ValueError):
        select_eligible_query_candidates((question,), stream, staging_root=tmp_path)
    assert stream.iterations == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("seed", range(16))
def test_small_randomized_population_matches_exhaustive_full_record_oracle(seed, tmp_path):
    rng = random.Random(seed)
    questions = tuple(InferenceQuestion(str(i), text) for i,text in enumerate(("Alpha Beta", "the Gamma", "Beta Alpha Gamma")))
    rows = []
    for i in range(15):
        mid = rng.choice((f"m.id{i}", f"g.id{i}", f"x.invalid{i}"))
        if rng.random() < 0.75:
            rows.append(record(mid, rng.choice(("", "Formal Name", "Alpha", "Gamma")),
                               language=rng.choice(("en", "en", "fr")), resource=rng.random() < 0.1))
        for _ in range(rng.randrange(1, 5)):
            rows.append(record(mid, rng.choice(("Alpha", "ALPHA", "Alpha Beta", "Beta", "Gamma", "the", "a", "Nope")),
                               rng.choice((NAME_PREDICATE, ALIAS_PREDICATE, TYPE_PREDICATE)),
                               language=rng.choice(("en", "en", "es")), resource=rng.random() < 0.1,
                               shard=rng.choice(("a.parquet", "z.parquet"))))
    rng.shuffle(rows)
    frozen_rows = tuple(rows)
    limit = 1 + seed % 4
    result = check_oracle(questions, rows, staging_root=tmp_path, max_candidates_per_query=limit)
    rng.shuffle(rows)
    second = check_oracle(questions, rows, staging_root=tmp_path, max_candidates_per_query=limit)
    assert second.candidates == result.candidates
    assert second.diagnostics["per_query"] == result.diagnostics["per_query"]
    assert set(rows) == set(frozen_rows)
    assert list(tmp_path.iterdir()) == []


def test_selector_surface_accepts_no_gold_or_reference_inputs():
    parameters = set(inspect.signature(select_eligible_query_candidates).parameters)
    assert parameters.isdisjoint({"gold", "answers", "reference", "reference_interpretations_path", "logical_forms"})
