"""Frozen M12 directional ontology-hop semantic-deviation protocol."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from xgap.llm.schemas import PlannerCandidate
from xgap.planning.contracts import (
    OntologyAlignmentContext,
    QueryPlanningContext,
    SemanticDeviationResult,
    SemanticDeviationStatus,
)
from xgap.experiments.hashing import content_hash


DEFAULT_EPSILON_VALUES = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)


class RelaxationKind(str, Enum):
    EXACT = "exact"
    SPECIALIZATION = "specialization"
    GENERALIZATION = "generalization"
    SIBLING = "sibling"
    UNRELATED = "unrelated"


class InfinitePolicy(str, Enum):
    INFINITY = "infinity"


@dataclass(frozen=True)
class SemanticDeviationConfig:
    max_relaxation_hops: int
    epsilon_values: tuple[float, ...] = DEFAULT_EPSILON_VALUES
    method: str = "directional_ontology_hop"
    ontology_distance_type: str = "normalized_shortest_hop"
    exact_penalty: float = 0.0
    specialization_penalty: float = 1.0 / 3.0
    generalization_penalty: float = 2.0 / 3.0
    sibling_penalty: float = 1.0
    slot_weight_type: str = "uniform"
    incomplete_slot_policy: InfinitePolicy = InfinitePolicy.INFINITY
    missing_mapping_policy: InfinitePolicy = InfinitePolicy.INFINITY
    unrelated_policy: InfinitePolicy = InfinitePolicy.INFINITY
    schema_version: str = "m12-semantic-deviation-v1"

    def __post_init__(self) -> None:
        if self.max_relaxation_hops <= 0:
            raise ValueError("max_relaxation_hops must be a positive integer.")
        if self.method != "directional_ontology_hop":
            raise ValueError("M12-A supports directional_ontology_hop only.")
        if self.ontology_distance_type != "normalized_shortest_hop":
            raise ValueError("M12-A supports normalized_shortest_hop only.")
        if self.slot_weight_type != "uniform":
            raise ValueError("M12-A requires uniform slot weights.")
        expected = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
        actual = (
            self.exact_penalty,
            self.specialization_penalty,
            self.generalization_penalty,
            self.sibling_penalty,
        )
        if any(not math.isclose(left, right) for left, right in zip(actual, expected, strict=True)):
            raise ValueError("M12-A directional penalties are frozen at 0, 1/3, 2/3, and 1.")
        epsilon_values = tuple(float(item) for item in self.epsilon_values)
        if not epsilon_values or any(
            not math.isfinite(item) or item < 0 or item > 1 for item in epsilon_values
        ):
            raise ValueError("epsilon_values must be a non-empty list within [0, 1].")
        if len(set(epsilon_values)) != len(epsilon_values):
            raise ValueError("epsilon_values must not contain duplicates.")
        object.__setattr__(self, "epsilon_values", epsilon_values)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticDeviationConfig":
        distance = _mapping(data.get("ontology_distance"), "ontology_distance")
        penalties = _mapping(data.get("direction_penalty"), "direction_penalty")
        slot_weights = _mapping(data.get("slot_weights"), "slot_weights")
        return cls(
            schema_version=str(data.get("schema_version", "m12-semantic-deviation-v1")),
            method=str(data.get("method", "")),
            ontology_distance_type=str(distance.get("type", "")),
            max_relaxation_hops=int(distance.get("max_relaxation_hops", 0)),
            exact_penalty=float(penalties.get("exact", 0.0)),
            specialization_penalty=float(penalties.get("specialization", 1.0 / 3.0)),
            generalization_penalty=float(penalties.get("generalization", 2.0 / 3.0)),
            sibling_penalty=float(penalties.get("sibling", 1.0)),
            slot_weight_type=str(slot_weights.get("type", "")),
            incomplete_slot_policy=InfinitePolicy(str(data.get("incomplete_slot_policy", ""))),
            missing_mapping_policy=InfinitePolicy(str(data.get("missing_mapping_policy", ""))),
            unrelated_policy=InfinitePolicy(str(data.get("unrelated_policy", ""))),
            epsilon_values=tuple(float(item) for item in data.get("epsilon_values", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "method": self.method,
            "ontology_distance": {
                "type": self.ontology_distance_type,
                "max_relaxation_hops": self.max_relaxation_hops,
            },
            "direction_penalty": {
                "exact": self.exact_penalty,
                "specialization": self.specialization_penalty,
                "generalization": self.generalization_penalty,
                "sibling": self.sibling_penalty,
            },
            "slot_weights": {"type": self.slot_weight_type},
            "incomplete_slot_policy": self.incomplete_slot_policy.value,
            "missing_mapping_policy": self.missing_mapping_policy.value,
            "unrelated_policy": self.unrelated_policy.value,
            "epsilon_values": list(self.epsilon_values),
        }

    @property
    def config_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class OntologyGraph:
    ontology_id: str
    version: str
    classes: tuple[str, ...]
    relations: tuple[str, ...]
    properties: tuple[str, ...]
    parents: Mapping[str, tuple[str, ...]]
    max_relaxation_hops: int
    admissible_sibling_pairs: tuple[tuple[str, str], ...] = ()
    sibling_rule_reference: str | None = None
    domain_range: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    schema_version: str = "m12-ontology-v1"

    def __post_init__(self) -> None:
        if not self.ontology_id or not self.version:
            raise ValueError("Ontology ID and version must be non-empty.")
        if self.max_relaxation_hops <= 0:
            raise ValueError("Ontology max_relaxation_hops must be positive.")
        classes = tuple(sorted(set(self.classes)))
        relations = tuple(sorted(set(self.relations)))
        properties = tuple(sorted(set(self.properties)))
        all_terms = set(classes) | set(relations) | set(properties)
        if len(all_terms) != len(classes) + len(relations) + len(properties):
            raise ValueError("Ontology terms must have one unambiguous category.")
        parents = {
            str(child): tuple(sorted(str(parent) for parent in values))
            for child, values in self.parents.items()
        }
        for child, values in parents.items():
            if child not in all_terms or any(parent not in all_terms for parent in values):
                raise ValueError("Subsumption edges must reference declared ontology terms.")
            if any(self._category_from_sets(parent, classes, relations, properties)
                   != self._category_from_sets(child, classes, relations, properties)
                   for parent in values):
                raise ValueError("Subsumption edges cannot cross ontology term categories.")
        sibling_pairs = tuple(
            sorted({tuple(sorted((str(left), str(right)))) for left, right in self.admissible_sibling_pairs})
        )
        for left, right in sibling_pairs:
            if left == right or left not in all_terms or right not in all_terms:
                raise ValueError("Sibling pairs must contain distinct declared terms.")
        object.__setattr__(self, "classes", classes)
        object.__setattr__(self, "relations", relations)
        object.__setattr__(self, "properties", properties)
        object.__setattr__(self, "parents", parents)
        object.__setattr__(self, "admissible_sibling_pairs", sibling_pairs)
        object.__setattr__(
            self,
            "domain_range",
            {str(key): dict(value) for key, value in self.domain_range.items()},
        )
        self._validate_acyclic()

    @staticmethod
    def _category_from_sets(
        term: str,
        classes: tuple[str, ...],
        relations: tuple[str, ...],
        properties: tuple[str, ...],
    ) -> str:
        if term in classes:
            return "class"
        if term in relations:
            return "relation"
        if term in properties:
            return "property"
        raise KeyError(term)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OntologyGraph":
        subsumption = _mapping(data.get("subsumption"), "subsumption")
        sibling_data = _mapping(data.get("sibling_admissibility", {}), "sibling_admissibility")
        pairs: list[tuple[str, str]] = []
        for item in sibling_data.get("explicit_pairs", ()):
            parts = str(item).split("|", 1)
            if len(parts) != 2:
                raise ValueError("Sibling pair entries must use 'left|right'.")
            pairs.append((parts[0], parts[1]))
        return cls(
            schema_version=str(data.get("schema_version", "m12-ontology-v1")),
            ontology_id=str(data.get("ontology_id", "")),
            version=str(data.get("version", "")),
            classes=tuple(str(item) for item in data.get("classes", ())),
            relations=tuple(str(item) for item in data.get("relations", ())),
            properties=tuple(str(item) for item in data.get("properties", ())),
            parents={
                str(child): tuple(str(parent) for parent in values)
                for child, values in subsumption.items()
                if isinstance(values, list | tuple)
            },
            max_relaxation_hops=int(data.get("max_relaxation_hops", 0)),
            admissible_sibling_pairs=tuple(pairs),
            sibling_rule_reference=(
                str(sibling_data["rule_reference"])
                if sibling_data.get("rule_reference") is not None
                else None
            ),
            domain_range={
                str(key): {str(k): str(v) for k, v in value.items()}
                for key, value in _mapping(data.get("domain_range", {}), "domain_range").items()
                if isinstance(value, Mapping)
            },
        )

    @property
    def all_terms(self) -> tuple[str, ...]:
        return (*self.classes, *self.relations, *self.properties)

    def category(self, term: str) -> str | None:
        if term in self.classes:
            return "class"
        if term in self.relations:
            return "relation"
        if term in self.properties:
            return "property"
        return None

    def ancestor_distances(self, term: str) -> dict[str, int]:
        if term not in self.all_terms:
            return {}
        distances = {term: 0}
        frontier = [term]
        while frontier:
            child = frontier.pop(0)
            for parent in self.parents.get(child, ()):
                distance = distances[child] + 1
                if parent not in distances or distance < distances[parent]:
                    distances[parent] = distance
                    frontier.append(parent)
        return distances

    def relation(self, query_term: str, aligned_term: str) -> tuple[RelaxationKind, int | None]:
        if query_term == aligned_term and query_term in self.all_terms:
            return RelaxationKind.EXACT, 0
        if self.category(query_term) is None or self.category(query_term) != self.category(aligned_term):
            return RelaxationKind.UNRELATED, None
        aligned_ancestors = self.ancestor_distances(aligned_term)
        if query_term in aligned_ancestors:
            return RelaxationKind.SPECIALIZATION, aligned_ancestors[query_term]
        query_ancestors = self.ancestor_distances(query_term)
        if aligned_term in query_ancestors:
            return RelaxationKind.GENERALIZATION, query_ancestors[aligned_term]
        pair = tuple(sorted((query_term, aligned_term)))
        if pair not in self.admissible_sibling_pairs:
            return RelaxationKind.UNRELATED, None
        common = set(query_ancestors) & set(aligned_ancestors)
        common.discard(query_term)
        common.discard(aligned_term)
        if not common:
            return RelaxationKind.UNRELATED, None
        _, hops = min(
            (
                (ancestor, query_ancestors[ancestor] + aligned_ancestors[ancestor])
                for ancestor in common
            ),
            key=lambda item: (item[1], item[0]),
        )
        return RelaxationKind.SIBLING, hops

    def _validate_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(term: str) -> None:
            if term in visiting:
                raise ValueError("Ontology subsumption graph must be acyclic.")
            if term in visited:
                return
            visiting.add(term)
            for parent in self.parents.get(term, ()):
                visit(parent)
            visiting.remove(term)
            visited.add(term)

        for term in self.all_terms:
            visit(term)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ontology_id": self.ontology_id,
            "version": self.version,
            "classes": list(self.classes),
            "relations": list(self.relations),
            "properties": list(self.properties),
            "subsumption": {key: list(value) for key, value in sorted(self.parents.items())},
            "domain_range": {key: dict(value) for key, value in sorted(self.domain_range.items())},
            "max_relaxation_hops": self.max_relaxation_hops,
            "sibling_admissibility": {
                "explicit_pairs": [f"{left}|{right}" for left, right in self.admissible_sibling_pairs],
                "rule_reference": self.sibling_rule_reference,
            },
        }

    @property
    def ontology_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class SlotAlignmentEvidence:
    slot_id: str
    query_term: str | None
    aligned_term: str | None
    covered: bool = True
    query_anchor_available: bool = True
    mapping_available: bool = True
    alignment_evidence_available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SlotAlignmentEvidence":
        return cls(
            slot_id=str(data.get("slot_id", "")),
            query_term=str(data["query_term"]) if data.get("query_term") is not None else None,
            aligned_term=str(data["aligned_term"]) if data.get("aligned_term") is not None else None,
            covered=bool(data.get("covered", True)),
            query_anchor_available=bool(data.get("query_anchor_available", True)),
            mapping_available=bool(data.get("mapping_available", True)),
            alignment_evidence_available=bool(data.get("alignment_evidence_available", True)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "query_term": self.query_term,
            "aligned_term": self.aligned_term,
            "covered": self.covered,
            "query_anchor_available": self.query_anchor_available,
            "mapping_available": self.mapping_available,
            "alignment_evidence_available": self.alignment_evidence_available,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SlotDeviation:
    slot_id: str
    relation: RelaxationKind
    hop_distance: int | None
    normalized_distance: float | None
    penalty: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "relation": self.relation.value,
            "hop_distance": self.hop_distance,
            "normalized_distance": self.normalized_distance,
            "penalty": self.penalty if self.penalty is not None else "infinity",
        }


@dataclass(frozen=True)
class SemanticDeviationMeasurement:
    finite_value: float | None
    admissible: bool
    reason: str
    slots: tuple[SlotDeviation, ...]
    schema_version: str = "m12-semantic-measurement-v1"

    @property
    def is_infinite(self) -> bool:
        return self.finite_value is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "value": self.finite_value if self.finite_value is not None else "infinity",
            "admissible": self.admissible,
            "reason": self.reason,
            "slots": [item.to_dict() for item in self.slots],
        }


class DirectionalOntologyDeviation:
    def __init__(self, ontology: OntologyGraph, config: SemanticDeviationConfig) -> None:
        if ontology.max_relaxation_hops != config.max_relaxation_hops:
            raise ValueError("Semantic config H must match the ontology bundle H.")
        self.ontology = ontology
        self.config = config

    def evaluate(self, slots: tuple[SlotAlignmentEvidence, ...]) -> SemanticDeviationMeasurement:
        if not slots:
            return SemanticDeviationMeasurement(None, False, "no_ontology_slots", ())
        deviations: list[SlotDeviation] = []
        for slot in slots:
            failure = self._slot_failure(slot)
            if failure is not None:
                return SemanticDeviationMeasurement(None, False, failure, tuple(deviations))
            assert slot.query_term is not None and slot.aligned_term is not None
            relation, hops = self.ontology.relation(slot.query_term, slot.aligned_term)
            if relation is RelaxationKind.UNRELATED or hops is None:
                deviations.append(SlotDeviation(slot.slot_id, relation, hops, None, None))
                return SemanticDeviationMeasurement(None, False, "unrelated_terms", tuple(deviations))
            if hops > self.config.max_relaxation_hops:
                deviations.append(SlotDeviation(slot.slot_id, RelaxationKind.UNRELATED, hops, None, None))
                return SemanticDeviationMeasurement(None, False, "relaxation_radius_exceeded", tuple(deviations))
            normalized = hops / self.config.max_relaxation_hops
            multiplier = {
                RelaxationKind.EXACT: self.config.exact_penalty,
                RelaxationKind.SPECIALIZATION: self.config.specialization_penalty,
                RelaxationKind.GENERALIZATION: self.config.generalization_penalty,
                RelaxationKind.SIBLING: self.config.sibling_penalty,
            }[relation]
            deviations.append(
                SlotDeviation(slot.slot_id, relation, hops, normalized, multiplier * normalized)
            )
        value = sum(item.penalty for item in deviations if item.penalty is not None) / len(slots)
        if not 0 <= value <= 1:
            raise ValueError("Finite semantic deviation must lie in [0, 1].")
        return SemanticDeviationMeasurement(value, True, "finite", tuple(deviations))

    @staticmethod
    def _slot_failure(slot: SlotAlignmentEvidence) -> str | None:
        if not slot.covered:
            return "incomplete_slot_coverage"
        if not slot.query_anchor_available or slot.query_term is None:
            return "missing_ontology_anchor"
        if not slot.mapping_available or slot.aligned_term is None:
            return "missing_source_mapping"
        if not slot.alignment_evidence_available:
            return "missing_alignment_evidence"
        return None


@dataclass(frozen=True)
class DirectionalOntologySemanticDeviationScorer:
    ontology: OntologyGraph
    config: SemanticDeviationConfig
    scorer_id: str = "m12-directional-ontology-hop"

    def score(
        self,
        query_context: QueryPlanningContext,
        interpretation: PlannerCandidate,
        semantic_context: OntologyAlignmentContext,
    ) -> SemanticDeviationResult:
        del query_context
        raw_slots = semantic_context.semantic_inputs.get("slot_alignments")
        if not isinstance(raw_slots, list):
            return SemanticDeviationResult(
                interpretation_id=interpretation.candidate_id,
                status=SemanticDeviationStatus.MISSING,
                scorer_id=self.scorer_id,
                reason="slot_alignments are missing from the alignment artifact.",
            )
        slots = tuple(
            SlotAlignmentEvidence.from_dict(item)
            for item in raw_slots
            if isinstance(item, Mapping)
        )
        if len(slots) != len(raw_slots):
            return SemanticDeviationResult(
                interpretation_id=interpretation.candidate_id,
                status=SemanticDeviationStatus.UNSUPPORTED,
                scorer_id=self.scorer_id,
                reason="Every slot alignment must be an object.",
            )
        measurement = DirectionalOntologyDeviation(self.ontology, self.config).evaluate(slots)
        if measurement.is_infinite:
            status = (
                SemanticDeviationStatus.MISSING
                if measurement.reason.startswith("missing") or measurement.reason == "incomplete_slot_coverage"
                else SemanticDeviationStatus.UNSUPPORTED
            )
            return SemanticDeviationResult(
                interpretation_id=interpretation.candidate_id,
                status=status,
                scorer_id=self.scorer_id,
                reason=measurement.reason,
                components={"measurement": measurement.to_dict()},
            )
        return SemanticDeviationResult(
            interpretation_id=interpretation.candidate_id,
            status=SemanticDeviationStatus.AVAILABLE,
            scorer_id=self.scorer_id,
            value=measurement.finite_value,
            components={"measurement": measurement.to_dict()},
        )


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping.")
    return dict(value)
