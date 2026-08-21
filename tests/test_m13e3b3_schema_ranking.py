from __future__ import annotations

import inspect

from xgap.experiments.schema_ranking import (
    SCHEMA_RANKING_VERSION,
    SchemaTerm,
    SchemaVocabularyStatistics,
    rank_schema_terms,
    ranking_contract,
)


def test_specific_phrase_outranks_generic_single_tokens() -> None:
    terms = (
        _term("r.sports", "sports"),
        _term("r.league", "league"),
        _term("r.sports_league", "sports league"),
    )
    ranked = _rank("which sports league is this?", terms)

    assert ranked[0].term.term_id == "r.sports_league"
    assert ranked[0].lexical.tier_name == "exact_normalized_phrase"
    assert {item.lexical.tier_name for item in ranked[1:]} == {
        "generic_single_token"
    }


def test_descriptor_rows_are_aggregated_before_term_truncation() -> None:
    terms = (
        SchemaTerm(
            "r.charge_unit",
            "charge unit",
            "relation",
            aliases=("charge unit", "charge-unit", "charge unit", "unit of charge"),
        ),
        _term("r.unit", "unit"),
    )
    ranked = _rank("what charge unit is used?", terms)

    assert [item.term.term_id for item in ranked] == ["r.charge_unit", "r.unit"]
    assert len({item.term.term_id for item in ranked}) == len(ranked)
    charge = ranked[0]
    normalized_descriptors = {
        item.descriptor.normalized for item in charge.descriptor_evidence
    }
    assert len(normalized_descriptors) == len(charge.descriptor_evidence)


def test_zero_overlap_uses_stable_schema_id_tie_break() -> None:
    terms = (_term("r.zeta", "zeta"), _term("r.alpha", "alpha"))
    first = _rank("unrelated words", terms)
    second = _rank("unrelated words", reversed(terms))

    assert [item.term.term_id for item in first] == ["r.alpha", "r.zeta"]
    assert [item.term.term_id for item in second] == ["r.alpha", "r.zeta"]
    assert all(item.lexical.tier_name == "zero_overlap" for item in first)


def test_relation_slot_candidate_pools_are_isolated() -> None:
    slot_one = (_term("r.birth_place", "birth place"),)
    slot_two = (_term("r.sports_league", "sports league"),)
    vocabulary = (*slot_one, *slot_two)
    statistics = SchemaVocabularyStatistics.from_terms(vocabulary)

    first = rank_schema_terms(
        "birth place and sports league",
        slot_one,
        statistics=statistics,
    )
    second = rank_schema_terms(
        "birth place and sports league",
        slot_two,
        statistics=statistics,
    )

    assert [item.term.term_id for item in first] == ["r.birth_place"]
    assert [item.term.term_id for item in second] == ["r.sports_league"]


def test_domain_range_coherence_breaks_a_lexical_tie_without_gold() -> None:
    terms = (
        SchemaTerm(
            "r.person_created",
            "created by",
            "relation",
            domain="people.person",
            range="work.work",
        ),
        SchemaTerm(
            "r.place_created",
            "created by",
            "relation",
            domain="location.location",
            range="work.work",
        ),
    )
    statistics = SchemaVocabularyStatistics.from_terms(terms)
    ranked = rank_schema_terms(
        "what was created by this person?",
        terms,
        statistics=statistics,
        expected_types=("people.person",),
        ontology_parents={},
    )

    assert ranked[0].term.term_id == "r.person_created"
    assert ranked[0].coherence_level == 2
    assert ranked[1].coherence_level == 0


def test_type_provenance_is_ranked_before_truncation_and_explained() -> None:
    terms = (
        SchemaTerm("type.person", "person", "type"),
        SchemaTerm("type.location", "location", "type"),
        SchemaTerm("type.organization", "organization", "type"),
    )
    statistics = SchemaVocabularyStatistics.from_terms(terms)
    ranked = rank_schema_terms(
        "who is the person?",
        terms,
        statistics=statistics,
        type_provenance={
            "type.location": ("relation_domain_range",),
            "type.organization": ("ontology_expansion",),
        },
    )

    assert ranked[0].term.term_id == "type.location"
    assert "relation_domain_range" in ranked[0].type_provenance
    assert "lexical_ontology" in ranked[0].type_provenance
    assert ranked[0].primary_tier == 5
    assert "ontology_expansion" in next(
        item for item in ranked if item.term.term_id == "type.organization"
    ).type_provenance


def test_ranking_contract_is_frozen_and_accepts_no_gold_inputs() -> None:
    terms = (_term("r.one", "one relation"),)
    first = SchemaVocabularyStatistics.from_terms(terms)
    second = SchemaVocabularyStatistics.from_terms(reversed(terms))
    contract = ranking_contract(first)

    assert first.statistics_hash == second.statistics_hash
    assert contract["schema_ranking_version"] == SCHEMA_RANKING_VERSION
    assert contract["gold_inputs"] is False
    assert contract["context_bound"] == 4
    assert {"gold", "reference", "answer"}.isdisjoint(
        inspect.signature(rank_schema_terms).parameters
    )


def _rank(question: str, terms: object):
    values = tuple(terms)  # type: ignore[arg-type]
    return rank_schema_terms(
        question,
        values,
        statistics=SchemaVocabularyStatistics.from_terms(values),
    )


def _term(term_id: str, label: str) -> SchemaTerm:
    return SchemaTerm(term_id, label, "relation")
