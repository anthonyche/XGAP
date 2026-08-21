"""Deterministic, gold-blind ranking for bounded ontology schema terms."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from xgap.experiments.grailqa_catalog import normalized_label
from xgap.experiments.hashing import content_hash


SCHEMA_RANKING_VERSION = "m13e3b3-ontology-aware-schema-ranking-v1"
DESCRIPTOR_NORMALIZATION_VERSION = "catalog-v2-normalized-label-v1"
SCHEMA_CONTEXT_BOUND = 4

EVIDENCE_TIERS = {
    "zero_overlap": 0,
    "generic_single_token": 1,
    "informative_partial_overlap": 2,
    "contiguous_partial_phrase": 3,
    "complete_informative_tokens": 4,
    "direct_ontology_provenance": 5,
    "exact_normalized_phrase": 6,
}

# This list is language-generic and frozen independently of GrailQA questions.
_UNINFORMATIVE_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "with",
    }
)


@dataclass(frozen=True)
class SchemaTerm:
    term_id: str
    label: str
    kind: str
    aliases: tuple[str, ...] = ()
    domain: str | None = None
    range: str | None = None
    reverse_id: str | None = None


@dataclass(frozen=True)
class DescriptorRecord:
    text: str
    normalized: str
    provenances: tuple[str, ...]

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(self.normalized.split())


@dataclass(frozen=True)
class LexicalEvidence:
    tier: int
    tier_name: str
    descriptor: DescriptorRecord
    informative_tokens: tuple[str, ...]
    matched_tokens: tuple[str, ...]
    longest_contiguous_match: int
    specificity: float

    @property
    def rank_key(self) -> tuple[int, int, float, int, int]:
        return (
            self.tier,
            len(self.matched_tokens),
            self.specificity,
            self.longest_contiguous_match,
            len(self.informative_tokens),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_name": self.tier_name,
            "descriptor": self.descriptor.text,
            "descriptor_normalized": self.descriptor.normalized,
            "descriptor_provenance": list(self.descriptor.provenances),
            "descriptor_tokens": list(self.descriptor.tokens),
            "informative_tokens": list(self.informative_tokens),
            "matched_tokens": list(self.matched_tokens),
            "longest_contiguous_match": self.longest_contiguous_match,
            "ontology_idf_sum": self.specificity,
        }


@dataclass(frozen=True)
class RankedSchemaTerm:
    term: SchemaTerm
    rank: int
    score: float
    lexical: LexicalEvidence
    descriptor_evidence: tuple[LexicalEvidence, ...]
    coherence_level: int
    coherence_evidence: tuple[str, ...]
    type_provenance: tuple[str, ...]
    primary_tier: int
    rank_key: tuple[int | float, ...]

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.term.term_id,
            "kind": self.term.kind,
            "label": self.term.label,
            "aliases": list(self.term.aliases),
            "domain": self.term.domain,
            "range": self.term.range,
            "reverse_id": self.term.reverse_id,
            "rank": self.rank,
            "score": self.score,
            "primary_tier": self.primary_tier,
            "rank_key": list(self.rank_key),
            "best_lexical_evidence": self.lexical.to_dict(),
            "descriptor_evidence": [item.to_dict() for item in self.descriptor_evidence],
            "coherence_level": self.coherence_level,
            "coherence_evidence": list(self.coherence_evidence),
            "type_provenance": list(self.type_provenance),
        }


@dataclass(frozen=True)
class LegacyRankedSchemaTerm:
    term: SchemaTerm
    rank: int
    score: float
    matched_descriptor: DescriptorRecord
    overlap_count: int
    descriptor_token_count: int
    substring_bonus: float

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "id": self.term.term_id,
            "kind": self.term.kind,
            "label": self.term.label,
            "aliases": list(self.term.aliases),
            "domain": self.term.domain,
            "range": self.term.range,
            "reverse_id": self.term.reverse_id,
            "rank": self.rank,
            "score": self.score,
            "matched_descriptor": self.matched_descriptor.text,
            "matched_descriptor_normalized": self.matched_descriptor.normalized,
            "descriptor_provenance": list(self.matched_descriptor.provenances),
            "normalized_descriptor_tokens": list(self.matched_descriptor.tokens),
            "overlap_count": self.overlap_count,
            "descriptor_token_count": self.descriptor_token_count,
            "overlap_fraction": (
                self.overlap_count / self.descriptor_token_count
                if self.descriptor_token_count
                else 0.0
            ),
            "substring_bonus": self.substring_bonus,
        }


@dataclass(frozen=True)
class SchemaVocabularyStatistics:
    document_count: int
    document_frequency: Mapping[str, int]
    statistics_hash: str

    @classmethod
    def from_terms(cls, terms: Iterable[SchemaTerm]) -> "SchemaVocabularyStatistics":
        term_values = tuple(terms)
        frequencies: dict[str, int] = {}
        for term in term_values:
            tokens = {
                token
                for descriptor in descriptors_for_term(term)
                for token in descriptor.tokens
                if token not in _UNINFORMATIVE_TOKENS
            }
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
        payload = {
            "descriptor_normalization_version": DESCRIPTOR_NORMALIZATION_VERSION,
            "document_count": len(term_values),
            "document_frequency": dict(sorted(frequencies.items())),
        }
        return cls(
            document_count=len(term_values),
            document_frequency=dict(sorted(frequencies.items())),
            statistics_hash=content_hash(payload),
        )

    def idf(self, token: str) -> float:
        frequency = self.document_frequency.get(token, 0)
        return math.log((self.document_count + 1) / (frequency + 1)) + 1.0


def ranking_contract(statistics: SchemaVocabularyStatistics) -> dict[str, Any]:
    return {
        "schema_ranking_version": SCHEMA_RANKING_VERSION,
        "descriptor_normalization_version": DESCRIPTOR_NORMALIZATION_VERSION,
        "evidence_tiers": dict(EVIDENCE_TIERS),
        "ontology_specificity": {
            "definition": "smoothed_idf_over_unique_schema_term_descriptors",
            "statistics_hash": statistics.statistics_hash,
            "document_count": statistics.document_count,
            "use": "secondary_lexicographic_tie_break_only",
        },
        "aggregation": "all_descriptors_then_term_dedup_then_rank_then_top_k",
        "relation_slot_policy": (
            "slot_1_uses_query_local_entity_types; later_slots_use_bounded_"
            "domain_range_endpoint_propagation"
        ),
        "direction_policy": (
            "bidirectional_domain_range_compatibility_when_no_deterministic_slot_"
            "direction_is_available"
        ),
        "type_provenance_policy": [
            "lexical_ontology",
            "entity_attached_type",
            "relation_domain_range",
            "ontology_expansion",
        ],
        "context_bound": SCHEMA_CONTEXT_BOUND,
        "tie_break": "lexicographic_evidence_then_schema_id_ascending",
        "gold_inputs": False,
    }


def descriptors_for_term(term: SchemaTerm) -> tuple[DescriptorRecord, ...]:
    values: list[tuple[str, str]] = [(term.label, "canonical_label")]
    values.extend((alias, "public_alias") for alias in term.aliases)
    values.append((normalized_label(term.term_id), "schema_id"))
    values.extend(
        (value, provenance)
        for value, provenance in (
            (normalized_label(term.domain or ""), "domain_metadata"),
            (normalized_label(term.range or ""), "range_metadata"),
            (normalized_label(term.reverse_id or ""), "reverse_metadata"),
        )
        if value
    )
    aggregated: dict[str, tuple[str, set[str]]] = {}
    for text, provenance in values:
        normalized = normalized_label(text)
        if not normalized:
            continue
        current = aggregated.get(normalized)
        if current is None:
            aggregated[normalized] = (text, {provenance})
        else:
            current[1].add(provenance)
    return tuple(
        DescriptorRecord(text, normalized, tuple(sorted(provenances)))
        for normalized, (text, provenances) in sorted(aggregated.items())
    )


def rank_schema_terms(
    question: str,
    terms: Iterable[SchemaTerm],
    *,
    statistics: SchemaVocabularyStatistics,
    expected_types: Iterable[str] = (),
    ontology_parents: Mapping[str, tuple[str, ...]] | None = None,
    type_provenance: Mapping[str, Iterable[str]] | None = None,
    top_k: int | None = None,
) -> tuple[RankedSchemaTerm, ...]:
    """Aggregate descriptor evidence by term before deterministic truncation."""

    if top_k is not None and top_k <= 0:
        raise ValueError("top_k must be positive when provided.")
    question_norm = normalized_label(question)
    question_tokens = tuple(question_norm.split())
    question_token_set = set(question_tokens)
    expected = frozenset(str(item) for item in expected_types)
    parents = ontology_parents or {}
    provenance_by_id = type_provenance or {}
    unranked: list[RankedSchemaTerm] = []
    for term in terms:
        descriptor_evidence = tuple(
            _lexical_evidence(
                descriptor,
                question_norm=question_norm,
                question_tokens=question_tokens,
                question_token_set=question_token_set,
                statistics=statistics,
            )
            for descriptor in descriptors_for_term(term)
        )
        best = max(
            descriptor_evidence,
            key=lambda item: (*item.rank_key, item.descriptor.normalized),
        )
        coherence_level, coherence_evidence = _coherence(
            term, expected_types=expected, parents=parents
        )
        provenance_values = set(provenance_by_id.get(term.term_id, ()))
        if term.kind == "type":
            provenance_values.add("lexical_ontology")
        provenances = tuple(sorted(provenance_values))
        provenance_tier = _type_provenance_tier(provenances)
        primary_tier = max(best.tier, provenance_tier)
        if term.kind == "relation":
            rank_key: tuple[int | float, ...] = (
                primary_tier,
                coherence_level,
                len(best.matched_tokens),
                best.specificity,
                best.longest_contiguous_match,
                len(best.informative_tokens),
            )
        else:
            rank_key = (
                primary_tier,
                int("entity_attached_type" in provenances),
                int("relation_domain_range" in provenances),
                best.tier,
                len(best.matched_tokens),
                best.specificity,
                best.longest_contiguous_match,
                len(best.informative_tokens),
            )
        unranked.append(
            RankedSchemaTerm(
                term=term,
                rank=0,
                score=float(primary_tier),
                lexical=best,
                descriptor_evidence=descriptor_evidence,
                coherence_level=coherence_level,
                coherence_evidence=coherence_evidence,
                type_provenance=provenances,
                primary_tier=primary_tier,
                rank_key=rank_key,
            )
        )
    ordered = sorted(
        unranked,
        key=lambda item: (*(-float(value) for value in item.rank_key), item.term.term_id),
    )
    selected = ordered if top_k is None else ordered[:top_k]
    return tuple(
        RankedSchemaTerm(**{**item.__dict__, "rank": rank})
        for rank, item in enumerate(selected, start=1)
    )


def rank_schema_terms_legacy(
    question: str,
    terms: Iterable[SchemaTerm],
    *,
    top_k: int | None = None,
) -> tuple[LegacyRankedSchemaTerm, ...]:
    """Reproduce the pre-E3B.3 lexical score for before/after diagnostics."""

    question_norm = normalized_label(question)
    question_tokens = set(question_norm.split())
    values: list[LegacyRankedSchemaTerm] = []
    for term in terms:
        best: tuple[float, DescriptorRecord, int, int, float] | None = None
        for descriptor in descriptors_for_term(term):
            tokens = set(descriptor.tokens)
            overlap = len(question_tokens & tokens)
            substring_bonus = (
                2.0
                if descriptor.normalized
                and f" {descriptor.normalized} " in f" {question_norm} "
                else 0.0
            )
            score = overlap / max(1, len(tokens)) + substring_bonus
            candidate = (score, descriptor, overlap, len(tokens), substring_bonus)
            if best is None or score > best[0]:
                best = candidate
        if best is None:
            continue
        values.append(
            LegacyRankedSchemaTerm(
                term=term,
                rank=0,
                score=best[0],
                matched_descriptor=best[1],
                overlap_count=best[2],
                descriptor_token_count=best[3],
                substring_bonus=best[4],
            )
        )
    ordered = sorted(values, key=lambda item: (-item.score, item.term.term_id))
    selected = ordered if top_k is None else ordered[:top_k]
    return tuple(
        LegacyRankedSchemaTerm(**{**item.__dict__, "rank": rank})
        for rank, item in enumerate(selected, start=1)
    )


def ontology_compatible(
    left: str | None,
    right_types: Iterable[str],
    parents: Mapping[str, tuple[str, ...]],
) -> int:
    """Return 2 for exact, 1 for hierarchy-related, and 0 otherwise."""

    if left is None:
        return 0
    expected = frozenset(right_types)
    if left in expected:
        return 2
    left_ancestors = _ancestors(left, parents)
    if left_ancestors & expected:
        return 1
    return int(any(left in _ancestors(item, parents) for item in expected))


def _lexical_evidence(
    descriptor: DescriptorRecord,
    *,
    question_norm: str,
    question_tokens: tuple[str, ...],
    question_token_set: set[str],
    statistics: SchemaVocabularyStatistics,
) -> LexicalEvidence:
    informative = tuple(
        token for token in descriptor.tokens if token not in _UNINFORMATIVE_TOKENS
    )
    matched = tuple(dict.fromkeys(token for token in informative if token in question_token_set))
    contiguous = _longest_contiguous_match(informative, question_tokens)
    exact_phrase = (
        len(informative) >= 2
        and f" {descriptor.normalized} " in f" {question_norm} "
    )
    if exact_phrase:
        tier_name = "exact_normalized_phrase"
    elif len(informative) >= 2 and len(matched) == len(set(informative)):
        tier_name = "complete_informative_tokens"
    elif contiguous >= 2:
        tier_name = "contiguous_partial_phrase"
    elif len(matched) >= 2:
        tier_name = "informative_partial_overlap"
    elif matched:
        tier_name = "generic_single_token"
    else:
        tier_name = "zero_overlap"
    return LexicalEvidence(
        tier=EVIDENCE_TIERS[tier_name],
        tier_name=tier_name,
        descriptor=descriptor,
        informative_tokens=informative,
        matched_tokens=matched,
        longest_contiguous_match=contiguous,
        specificity=round(sum(statistics.idf(token) for token in matched), 12),
    )


def _coherence(
    term: SchemaTerm,
    *,
    expected_types: frozenset[str],
    parents: Mapping[str, tuple[str, ...]],
) -> tuple[int, tuple[str, ...]]:
    if term.kind != "relation" or not expected_types:
        return 0, ()
    domain = ontology_compatible(term.domain, expected_types, parents)
    range_level = ontology_compatible(term.range, expected_types, parents)
    level = max(domain, range_level)
    evidence: list[str] = []
    if domain:
        evidence.append(f"domain_compatibility:{'exact' if domain == 2 else 'hierarchy'}")
    if range_level:
        evidence.append(f"range_compatibility:{'exact' if range_level == 2 else 'hierarchy'}")
    if term.reverse_id is not None:
        evidence.append("reverse_metadata_available")
    return level, tuple(evidence)


def _type_provenance_tier(provenances: tuple[str, ...]) -> int:
    if "entity_attached_type" in provenances or "relation_domain_range" in provenances:
        return EVIDENCE_TIERS["direct_ontology_provenance"]
    if "ontology_expansion" in provenances:
        return EVIDENCE_TIERS["contiguous_partial_phrase"]
    return 0


def _ancestors(term: str, parents: Mapping[str, tuple[str, ...]]) -> frozenset[str]:
    values: set[str] = set()
    frontier = list(parents.get(term, ()))
    while frontier:
        current = frontier.pop(0)
        if current in values:
            continue
        values.add(current)
        frontier.extend(parents.get(current, ()))
    return frozenset(values)


def _longest_contiguous_match(
    descriptor_tokens: tuple[str, ...], question_tokens: tuple[str, ...]
) -> int:
    best = 0
    for left in range(len(descriptor_tokens)):
        for right in range(left + 1, len(descriptor_tokens) + 1):
            phrase = descriptor_tokens[left:right]
            if len(phrase) <= best:
                continue
            if any(
                question_tokens[index : index + len(phrase)] == phrase
                for index in range(len(question_tokens) - len(phrase) + 1)
            ):
                best = len(phrase)
    return best
