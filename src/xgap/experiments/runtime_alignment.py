"""Bounded runtime ontology retrieval and file-backed M12-B alignment."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import (
    DatasetBundle,
    EntityCatalogRecord,
    SchemaSnapshot,
)
from xgap.experiments.semantic import OntologyGraph
from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import LiveFailureCategory
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.llm.schemas import PlannerCandidate, PlannerResponse
from xgap.pattern.ast import Alt, Bounded, OptionalExpr, Plus, RegexExpr, Rel, Seq, Star
from xgap.planning.contracts import (
    MappingSufficiencyResult,
    MappingSufficiencyStatus,
    OntologyAlignmentContext,
    QueryPlanningContext,
)


FORBIDDEN_INFERENCE_KEYS = frozenset(
    {"gold_answers", "gold_logical_form", "gold_alignments", "evaluation_labels"}
)


@dataclass(frozen=True)
class RetrievalLimits:
    max_slots: int = 8
    max_candidates_per_slot: int = 4
    max_entities: int = 4
    max_schema_items: int = 12

    def __post_init__(self) -> None:
        if min(
            self.max_slots,
            self.max_candidates_per_slot,
            self.max_entities,
            self.max_schema_items,
        ) <= 0:
            raise ValueError("Runtime ontology retrieval limits must be positive.")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_slots": self.max_slots,
            "max_candidates_per_slot": self.max_candidates_per_slot,
            "max_entities": self.max_entities,
            "max_schema_items": self.max_schema_items,
        }


@dataclass(frozen=True)
class RetrievedOntologyTerm:
    term_id: str
    kind: str
    label: str
    aliases: tuple[str, ...]
    retrieval_score: float
    retrieval_provenance: tuple[str, ...]
    domain: str | None = None
    range: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "term_id": self.term_id,
            "kind": self.kind,
            "label": self.label,
            "aliases": list(self.aliases),
            "retrieval_score": self.retrieval_score,
            "retrieval_provenance": list(self.retrieval_provenance),
            "domain": self.domain,
            "range": self.range,
        }


@dataclass(frozen=True)
class PromptQuerySlot:
    slot_id: str
    mention: str
    kind: str
    candidate_anchor_ids: tuple[str, ...]
    retrieval_provenance: tuple[str, ...]
    required_for_candidate: bool = True

    def __post_init__(self) -> None:
        if not self.slot_id or not self.mention or not self.candidate_anchor_ids:
            raise ValueError("Prompt query slots require an ID, mention, and candidates.")
        object.__setattr__(self, "candidate_anchor_ids", tuple(self.candidate_anchor_ids))

    def to_dict(self) -> dict[str, Any]:
        result = {
            "slot_id": self.slot_id,
            "mention": self.mention,
            "kind": self.kind,
            "candidate_anchor_ids": list(self.candidate_anchor_ids),
            "retrieval_provenance": list(self.retrieval_provenance),
        }
        if not self.required_for_candidate:
            result["required_for_candidate"] = False
        return result


@dataclass(frozen=True)
class PromptSchemaView:
    task_id: str
    ontology_id: str
    ontology_version: str
    ontology_hash: str
    schema_snapshot_version: str
    schema_snapshot_hash: str
    terms: tuple[RetrievedOntologyTerm, ...]
    entities: tuple[dict[str, Any], ...]
    query_slots: tuple[PromptQuerySlot, ...]
    backend_hints: Mapping[str, Mapping[str, Any]]
    source_schema_items: tuple[str, ...]
    limits: RetrievalLimits
    retrieval_method: str = "deterministic_lexical_alias_v1"
    schema_version: str = "m12-prompt-schema-view-v1"

    def __post_init__(self) -> None:
        if not self.task_id or not self.ontology_id or not self.ontology_hash:
            raise ValueError("Prompt schema view identity fields are required.")
        term_ids = {item.term_id for item in self.terms}
        if len(term_ids) != len(self.terms):
            raise ValueError("Prompt schema view ontology terms must be unique.")
        if any(
            candidate not in term_ids
            for slot in self.query_slots
            for candidate in slot.candidate_anchor_ids
        ):
            raise ValueError("Every query-anchor candidate must be visible in the prompt view.")
        object.__setattr__(self, "entities", tuple(dict(item) for item in self.entities))
        object.__setattr__(
            self,
            "backend_hints",
            {key: dict(value) for key, value in self.backend_hints.items()},
        )
        assert_no_gold_leakage(self.to_dict())

    @property
    def visible_term_ids(self) -> tuple[str, ...]:
        return tuple(item.term_id for item in self.terms)

    @property
    def visible_entity_ids(self) -> tuple[str, ...]:
        return tuple(str(item["entity_id"]) for item in self.entities)

    @property
    def view_hash(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "ontology": {
                "id": self.ontology_id,
                "version": self.ontology_version,
                "hash": self.ontology_hash,
            },
            "schema_snapshot": {
                "version": self.schema_snapshot_version,
                "hash": self.schema_snapshot_hash,
            },
            "terms": [item.to_dict() for item in self.terms],
            "entities": [dict(item) for item in self.entities],
            "query_slots": [item.to_dict() for item in self.query_slots],
            "backend_hints": {
                key: dict(value) for key, value in sorted(self.backend_hints.items())
            },
            "source_schema_items": list(self.source_schema_items),
            "retrieval": {
                "method": self.retrieval_method,
                "limits": self.limits.to_dict(),
            },
        }


@dataclass(frozen=True)
class QueryAnchorSelection:
    slot_id: str
    query_anchor_id: str
    provenance: str = "live_structured_selection"

    def to_dict(self) -> dict[str, str]:
        return {
            "slot_id": self.slot_id,
            "query_anchor_id": self.query_anchor_id,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class CandidateSlotRealization:
    slot_id: str
    ontology_term_id: str
    component_ref: str

    def to_dict(self) -> dict[str, str]:
        return {
            "slot_id": self.slot_id,
            "ontology_term_id": self.ontology_term_id,
            "component_ref": self.component_ref,
        }


@dataclass(frozen=True)
class GroundedCandidate:
    candidate: PlannerCandidate
    slot_realizations: tuple[CandidateSlotRealization, ...]
    entity_ids: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate.candidate_id,
            "pattern_query": path_pattern_query_to_dict(self.candidate.pattern_query),
            "query_slots": [item.slot_id for item in self.slot_realizations],
            "slot_realizations": [item.to_dict() for item in self.slot_realizations],
            "ontology_term_ids": [item.ontology_term_id for item in self.slot_realizations],
            "entity_ids": list(self.entity_ids),
            "model_confidence": self.candidate.confidence,
            "rationale": self.candidate.rationale,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class GroundedPlannerResponse:
    planner_response: PlannerResponse
    query_anchors: tuple[QueryAnchorSelection, ...]
    grounded_candidates: tuple[GroundedCandidate, ...]

    def candidate(self, candidate_id: str) -> GroundedCandidate:
        for item in self.grounded_candidates:
            if item.candidate.candidate_id == candidate_id:
                return item
        raise KeyError(candidate_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_anchors": [item.to_dict() for item in self.query_anchors],
            "grounded_candidates": [item.to_dict() for item in self.grounded_candidates],
        }


class RuntimeAlignmentError(ValueError):
    def __init__(self, category: LiveFailureCategory, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class OntologyArtifactLoader:
    """Validate and expose DatasetBundle runtime artifacts without gold data."""

    dataset_id: str
    ontology: OntologyGraph
    aliases: Mapping[str, Any]
    entity_catalog: tuple[EntityCatalogRecord, ...]
    backend_mapping: Mapping[str, Any]
    schema_snapshot: SchemaSnapshot

    @classmethod
    def from_dataset(cls, dataset: DatasetBundle) -> "OntologyArtifactLoader":
        return cls(
            dataset_id=dataset.dataset_id,
            ontology=dataset.ontology,
            aliases=dict(dataset.aliases),
            entity_catalog=tuple(dataset.entity_catalog),
            backend_mapping=dict(dataset.backend_mapping),
            schema_snapshot=dataset.schema_snapshot,
        )

    def __post_init__(self) -> None:
        if content_hash(self.ontology.to_dict()) != self.ontology.ontology_hash:
            raise ValueError("Ontology artifact hash validation failed.")
        if content_hash(self.schema_snapshot.content) != self.schema_snapshot.content_hash:
            raise ValueError("Schema snapshot hash validation failed.")
        mapping_id = self.backend_mapping.get("mapping_id")
        mapping_version = self.backend_mapping.get("version")
        if not mapping_id or not mapping_version:
            raise ValueError("Backend mapping must define mapping_id and version.")
        known_terms = set(self.ontology.all_terms)
        for relation_id, constraints in self.ontology.domain_range.items():
            if self.ontology.category(relation_id) != "relation":
                raise ValueError(
                    f"Domain/range entry '{relation_id}' must reference a relation ID."
                )
            unknown_bounds = {
                str(constraints[name])
                for name in ("domain", "range")
                if constraints.get(name) and str(constraints[name]) not in known_terms
            }
            if unknown_bounds:
                raise ValueError(
                    f"Domain/range entry '{relation_id}' references unknown ontology IDs: "
                    f"{sorted(unknown_bounds)}"
                )
        for group_name in ("ontology_terms", "relations"):
            aliases = _mapping(self.aliases.get(group_name, {}))
            unknown = {str(term_id) for term_id in aliases.values()} - known_terms
            if unknown:
                raise ValueError(
                    f"Alias group '{group_name}' references unknown ontology IDs: "
                    f"{sorted(unknown)}"
                )
            if group_name == "relations" and any(
                self.ontology.category(str(term_id)) != "relation"
                for term_id in aliases.values()
            ):
                raise ValueError("Relation aliases must reference relation ontology IDs.")
        known_entities = {item.entity_id for item in self.entity_catalog}
        entity_aliases = _mapping(self.aliases.get("entities", {}))
        unknown_entities = {
            str(entity_id) for entity_id in entity_aliases.values()
        } - known_entities
        if unknown_entities:
            raise ValueError(
                "Entity aliases reference unknown entity IDs: "
                f"{sorted(unknown_entities)}"
            )
        backends = _mapping(self.backend_mapping.get("backends", {}))
        term_mappings = _mapping(self.backend_mapping.get("term_mappings", {}))
        unknown_backends = set(term_mappings) - set(backends)
        if unknown_backends:
            raise ValueError(
                "Term mappings reference undeclared backends: "
                f"{sorted(unknown_backends)}"
            )
        for backend_id, raw_mapping in term_mappings.items():
            backend_terms = _mapping(raw_mapping)
            unknown = set(backend_terms) - known_terms
            if unknown:
                raise ValueError(
                    f"Backend '{backend_id}' maps unknown ontology IDs: {sorted(unknown)}"
                )
            for term_id, raw_record in backend_terms.items():
                record = _mapping(raw_record)
                if not record.get("kind") or not record.get("representation"):
                    raise ValueError(
                        f"Backend mapping '{backend_id}.{term_id}' requires kind and representation."
                    )
                if str(record["kind"]) != self.ontology.category(term_id):
                    raise ValueError(
                        f"Backend mapping '{backend_id}.{term_id}' has the wrong ontology kind."
                    )

    @property
    def runtime_manifest(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "ontology_id": self.ontology.ontology_id,
            "ontology_version": self.ontology.version,
            "ontology_hash": self.ontology.ontology_hash,
            "aliases_hash": content_hash(self.aliases),
            "entity_catalog_hash": content_hash(
                [item.to_dict() for item in self.entity_catalog]
            ),
            "backend_mapping_id": self.backend_mapping["mapping_id"],
            "backend_mapping_version": self.backend_mapping["version"],
            "backend_mapping_hash": content_hash(self.backend_mapping),
            "schema_snapshot_hash": self.schema_snapshot.content_hash,
            "gold_artifacts_exposed": False,
        }


@dataclass(frozen=True)
class OntologyContextRetriever:
    loader: OntologyArtifactLoader
    limits: RetrievalLimits = field(default_factory=RetrievalLimits)

    def retrieve(self, question: str) -> tuple[
        tuple[RetrievedOntologyTerm, ...],
        tuple[dict[str, Any], ...],
        tuple[PromptQuerySlot, ...],
    ]:
        normalized_question = _normalize(question)
        direct: dict[str, tuple[float, list[str], str]] = {}
        aliases = self.loader.aliases
        ontology_aliases = _mapping(aliases.get("ontology_terms", {}))
        relation_aliases = _mapping(aliases.get("relations", {}))
        all_aliases = {**ontology_aliases, **relation_aliases}
        for alias, term_id in sorted(all_aliases.items()):
            if _phrase_in_question(str(alias), normalized_question):
                direct[str(term_id)] = (
                    120.0 + len(_normalize(str(alias))),
                    [f"alias:{alias}"],
                    str(alias),
                )
        for term_id in self.loader.ontology.all_terms:
            label = _term_label(term_id)
            if _phrase_in_question(label, normalized_question):
                current = direct.get(term_id, (0.0, [], label))
                direct[term_id] = (
                    max(current[0], 100.0 + len(label)),
                    [*current[1], f"canonical:{label}"],
                    current[2],
                )

        entities = self._entities(normalized_question)
        for entity in entities:
            for term_id in entity.types:
                current = direct.get(term_id, (0.0, [], entity.canonical_label))
                direct[term_id] = (
                    max(current[0], 130.0),
                    [*current[1], f"entity_type:{entity.entity_id}"],
                    entity.canonical_label,
                )

        ranked = sorted(direct.items(), key=lambda item: (-item[1][0], item[0]))
        selected: list[tuple[str, tuple[float, list[str], str]]] = []
        for item in ranked:
            term_id, (_, _, mention) = item
            kind = self.loader.ontology.category(term_id)
            normalized_mention = _normalize(mention)
            if any(
                self.loader.ontology.category(selected_id) == kind
                and f" {normalized_mention} " in f" {_normalize(selected_mention)} "
                for selected_id, (_, _, selected_mention) in selected
            ):
                continue
            selected.append(item)
            if len(selected) >= self.limits.max_slots:
                break
        ranked = selected
        visible_ids: set[str] = set()
        slots: list[PromptQuerySlot] = []
        score_by_term: dict[str, float] = {}
        provenance_by_term: dict[str, set[str]] = {}
        alias_by_term = self._aliases_by_term()
        for index, (anchor_id, (score, provenance, mention)) in enumerate(ranked, start=1):
            candidates = self._candidate_terms(anchor_id)
            visible_ids.update(candidates)
            score_by_term[anchor_id] = max(score_by_term.get(anchor_id, 0.0), score)
            provenance_by_term.setdefault(anchor_id, set()).update(provenance)
            for candidate in candidates[1:]:
                score_by_term[candidate] = max(score_by_term.get(candidate, 0.0), score - 20.0)
                provenance_by_term.setdefault(candidate, set()).add(
                    f"ontology_neighbor_of:{anchor_id}"
                )
            kind = self.loader.ontology.category(anchor_id)
            assert kind is not None
            slots.append(
                PromptQuerySlot(
                    slot_id=f"slot-{index}-{_slug(anchor_id)}",
                    mention=mention,
                    kind=kind,
                    candidate_anchor_ids=candidates,
                    retrieval_provenance=tuple(sorted(set(provenance))),
                )
            )

        terms = tuple(
            self._term_record(
                term_id,
                score_by_term.get(term_id, 0.0),
                tuple(sorted(provenance_by_term.get(term_id, set()))),
                alias_by_term.get(term_id, ()),
            )
            for term_id in sorted(visible_ids)
        )
        entity_records = tuple(
            {
                "entity_id": item.entity_id,
                "canonical_label": item.canonical_label,
                "aliases": list(item.aliases),
                "types": list(item.types),
                "retrieval_provenance": ["deterministic_entity_alias_match"],
            }
            for item in entities[: self.limits.max_entities]
        )
        return terms, entity_records, tuple(slots)

    def _entities(self, normalized_question: str) -> tuple[EntityCatalogRecord, ...]:
        matches = []
        alias_map = _mapping(self.loader.aliases.get("entities", {}))
        by_id = {item.entity_id: item for item in self.loader.entity_catalog}
        matched_ids = {
            str(entity_id)
            for alias, entity_id in alias_map.items()
            if _phrase_in_question(str(alias), normalized_question)
        }
        for entity in self.loader.entity_catalog:
            names = (entity.canonical_label, *entity.aliases)
            if entity.entity_id in matched_ids or any(
                _phrase_in_question(name, normalized_question) for name in names
            ):
                matches.append(entity)
        matches.extend(by_id[item] for item in matched_ids if item in by_id and by_id[item] not in matches)
        return tuple(sorted(matches, key=lambda item: item.entity_id))

    def _candidate_terms(self, anchor_id: str) -> tuple[str, ...]:
        ontology = self.loader.ontology
        candidates = {anchor_id}
        candidates.update(ontology.parents.get(anchor_id, ()))
        candidates.update(
            child for child, parents in ontology.parents.items() if anchor_id in parents
        )
        for left, right in ontology.admissible_sibling_pairs:
            if anchor_id == left:
                candidates.add(right)
            elif anchor_id == right:
                candidates.add(left)
        same_kind = [
            item
            for item in candidates
            if ontology.category(item) == ontology.category(anchor_id)
        ]
        ordered = [anchor_id, *sorted(item for item in same_kind if item != anchor_id)]
        return tuple(ordered[: self.limits.max_candidates_per_slot])

    def _aliases_by_term(self) -> dict[str, tuple[str, ...]]:
        aliases: dict[str, list[str]] = {}
        for group_name in ("ontology_terms", "relations"):
            for alias, term_id in _mapping(
                self.loader.aliases.get(group_name, {})
            ).items():
                aliases.setdefault(str(term_id), []).append(str(alias))
        return {key: tuple(sorted(values)) for key, values in aliases.items()}

    def _term_record(
        self,
        term_id: str,
        score: float,
        provenance: tuple[str, ...],
        aliases: tuple[str, ...],
    ) -> RetrievedOntologyTerm:
        ontology = self.loader.ontology
        constraints = ontology.domain_range.get(term_id, {})
        kind = ontology.category(term_id)
        assert kind is not None
        return RetrievedOntologyTerm(
            term_id=term_id,
            kind=kind,
            label=_term_label(term_id),
            aliases=aliases,
            retrieval_score=score,
            retrieval_provenance=provenance,
            domain=str(constraints["domain"]) if constraints.get("domain") else None,
            range=str(constraints["range"]) if constraints.get("range") else None,
        )


@dataclass(frozen=True)
class PromptSchemaViewBuilder:
    loader: OntologyArtifactLoader
    retriever: OntologyContextRetriever

    def build(
        self,
        *,
        task_id: str,
        question: str,
        backend_ids: Sequence[str],
    ) -> PromptSchemaView:
        terms, entities, slots = self.retriever.retrieve(question)
        term_ids = {item.term_id for item in terms}
        backend_hints: dict[str, dict[str, Any]] = {}
        term_mappings = _mapping(self.loader.backend_mapping.get("term_mappings", {}))
        for backend_id in backend_ids:
            backend_mapping = _mapping(term_mappings.get(backend_id, {}))
            backend_hints[str(backend_id)] = {
                term_id: backend_mapping[term_id]
                for term_id in sorted(term_ids)
                if term_id in backend_mapping
            }
        source_items = self._source_schema_items(term_ids)
        view = PromptSchemaView(
            task_id=task_id,
            ontology_id=self.loader.ontology.ontology_id,
            ontology_version=self.loader.ontology.version,
            ontology_hash=self.loader.ontology.ontology_hash,
            schema_snapshot_version=self.loader.schema_snapshot.version,
            schema_snapshot_hash=self.loader.schema_snapshot.content_hash,
            terms=terms,
            entities=entities,
            query_slots=slots,
            backend_hints=backend_hints,
            source_schema_items=source_items,
            limits=self.retriever.limits,
        )
        assert_no_gold_leakage(view.to_dict())
        return view

    def _source_schema_items(self, visible_term_ids: set[str]) -> tuple[str, ...]:
        content = self.loader.schema_snapshot.content
        flattened: list[str] = []
        for section_name, section in sorted(content.items()):
            if not isinstance(section, Mapping):
                continue
            for field_name, values in sorted(section.items()):
                if isinstance(values, list):
                    for value in values:
                        normalized = _normalize(str(value))
                        if any(
                            normalized in _normalize(term_id)
                            or _normalize(term_id) in normalized
                            for term_id in visible_term_ids
                        ):
                            flattened.append(f"{section_name}.{field_name}:{value}")
        return tuple(sorted(set(flattened))[: self.retriever.limits.max_schema_items])


def parse_grounded_planner_response(
    raw: Mapping[str, Any],
    planner_response: PlannerResponse,
    prompt_view: PromptSchemaView,
) -> GroundedPlannerResponse:
    raw_slots = raw.get("query_slots")
    if not isinstance(raw_slots, list):
        raise RuntimeAlignmentError(
            LiveFailureCategory.UNRESOLVED_QUERY_ANCHOR,
            "Structured response query_slots must be a list.",
        )
    expected_slots = {item.slot_id: item for item in prompt_view.query_slots}
    visible_terms_by_id = {item.term_id: item for item in prompt_view.terms}
    selections: list[QueryAnchorSelection] = []
    for item in raw_slots:
        if not isinstance(item, Mapping):
            raise RuntimeAlignmentError(
                LiveFailureCategory.UNRESOLVED_QUERY_ANCHOR,
                "Every query-anchor selection must be an object.",
            )
        slot_id = str(item.get("slot_id", ""))
        anchor_id = str(item.get("query_anchor_id", ""))
        slot = expected_slots.get(slot_id)
        if slot is None or anchor_id not in slot.candidate_anchor_ids:
            raise RuntimeAlignmentError(
                LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID,
                f"Query anchor '{anchor_id}' is not visible for slot '{slot_id}'.",
            )
        selections.append(QueryAnchorSelection(slot_id, anchor_id))
    if {item.slot_id for item in selections} != set(expected_slots) or len(selections) != len(expected_slots):
        raise RuntimeAlignmentError(
            LiveFailureCategory.UNRESOLVED_QUERY_ANCHOR,
            "Every prompt query slot must have exactly one selected query anchor.",
        )

    raw_candidates = raw.get("candidates")
    assert isinstance(raw_candidates, list)
    raw_by_id = {
        str(item.get("candidate_id")): item
        for item in raw_candidates
        if isinstance(item, Mapping)
    }
    visible_terms = set(prompt_view.visible_term_ids)
    visible_entities = set(prompt_view.visible_entity_ids)
    grounded: list[GroundedCandidate] = []
    for candidate in planner_response.candidates:
        raw_candidate = raw_by_id.get(candidate.candidate_id)
        if not isinstance(raw_candidate, Mapping):
            raise RuntimeAlignmentError(
                LiveFailureCategory.INVALID_CANDIDATE,
                f"Missing raw grounding for candidate '{candidate.candidate_id}'.",
            )
        grounding = raw_candidate.get("grounding")
        if not isinstance(grounding, Mapping):
            raise RuntimeAlignmentError(
                LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE,
                f"Candidate '{candidate.candidate_id}' has no grounding object.",
            )
        raw_realizations = grounding.get("slot_realizations")
        if not isinstance(raw_realizations, list):
            raise RuntimeAlignmentError(
                LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE,
                f"Candidate '{candidate.candidate_id}' has no slot realizations.",
            )
        realizations: list[CandidateSlotRealization] = []
        component_kinds = _path_pattern_component_kinds(candidate)
        for item in raw_realizations:
            if not isinstance(item, Mapping):
                raise RuntimeAlignmentError(
                    LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE,
                    "Candidate slot realizations must be objects.",
                )
            realization = CandidateSlotRealization(
                slot_id=str(item.get("slot_id", "")),
                ontology_term_id=str(item.get("ontology_term_id", "")),
                component_ref=str(item.get("component_ref", "")),
            )
            if realization.slot_id not in expected_slots:
                raise RuntimeAlignmentError(
                    LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE,
                    f"Unknown candidate slot '{realization.slot_id}'.",
                )
            if realization.ontology_term_id not in visible_terms:
                raise RuntimeAlignmentError(
                    LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID,
                    f"Ontology term '{realization.ontology_term_id}' was not prompt-visible.",
                )
            if not realization.component_ref:
                raise RuntimeAlignmentError(
                    LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE,
                    "Candidate slot realization requires component_ref.",
                )
            slot_kind = expected_slots[realization.slot_id].kind
            term_kind = visible_terms_by_id[realization.ontology_term_id].kind
            component_kind = component_kinds.get(realization.component_ref)
            if term_kind != slot_kind:
                raise RuntimeAlignmentError(
                    LiveFailureCategory.INVALID_CANDIDATE,
                    f"Candidate slot '{realization.slot_id}' has ontology kind "
                    f"'{term_kind}', expected '{slot_kind}'.",
                )
            if component_kind is None:
                raise RuntimeAlignmentError(
                    LiveFailureCategory.INVALID_CANDIDATE,
                    f"Candidate component_ref '{realization.component_ref}' does not identify "
                    "a PathPatternQuery component.",
                )
            if component_kind != term_kind:
                raise RuntimeAlignmentError(
                    LiveFailureCategory.INVALID_CANDIDATE,
                    f"Candidate component_ref '{realization.component_ref}' has kind "
                    f"'{component_kind}', not ontology kind '{term_kind}'.",
                )
            realizations.append(realization)
        realized_slot_ids = [item.slot_id for item in realizations]
        required_slot_ids = {
            item.slot_id for item in expected_slots.values() if item.required_for_candidate
        }
        if (
            not required_slot_ids.issubset(realized_slot_ids)
            or len(realized_slot_ids) != len(set(realized_slot_ids))
        ):
            raise RuntimeAlignmentError(
                LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE,
                f"Candidate '{candidate.candidate_id}' must cover every required query slot "
                "exactly once and may cover optional slots at most once.",
            )
        hop_slots = {
            item.slot_id: item.component_ref
            for item in realizations
            if item.slot_id.startswith("relation-hop-")
        }
        if any(slot_id.startswith("relation-hop-") for slot_id in expected_slots):
            relation_components = tuple(
                component_ref
                for component_ref, kind in component_kinds.items()
                if kind == "relation"
            )
            expected_hops = {
                f"relation-hop-{index}": component_ref
                for index, component_ref in enumerate(relation_components, start=1)
            }
            if hop_slots != expected_hops:
                raise RuntimeAlignmentError(
                    LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE,
                    f"Candidate '{candidate.candidate_id}' must ground each ordered relation "
                    "component through its corresponding relation-hop slot.",
                )
        entity_ids = tuple(str(item) for item in grounding.get("entity_ids", ()))
        unknown_entities = set(entity_ids) - visible_entities
        if unknown_entities:
            raise RuntimeAlignmentError(
                LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID,
                f"Entity IDs were not prompt-visible: {sorted(unknown_entities)}",
            )
        grounded.append(
            GroundedCandidate(
                candidate=candidate,
                slot_realizations=tuple(realizations),
                entity_ids=entity_ids,
                provenance={
                    "source": "live_structured_response",
                    "prompt_schema_view_hash": prompt_view.view_hash,
                },
            )
        )
    return GroundedPlannerResponse(
        planner_response=planner_response,
        query_anchors=tuple(sorted(selections, key=lambda item: item.slot_id)),
        grounded_candidates=tuple(grounded),
    )


def _path_pattern_component_kinds(candidate: PlannerCandidate) -> dict[str, str]:
    query = candidate.pattern_query
    components = {"source": "class", "target": "class"}
    components.update(_regex_component_kinds(query.expr, "expr"))
    for name in query.source.properties:
        components[f"source.properties.{name}"] = "property"
    for name in query.target.properties:
        components[f"target.properties.{name}"] = "property"
    if query.condition is not None:
        components["condition"] = "property"
    return components


def _regex_component_kinds(expr: RegexExpr, path: str) -> dict[str, str]:
    if isinstance(expr, Rel):
        components = {f"{path}.edge": "relation"}
        for name in expr.edge.properties:
            components[f"{path}.edge.properties.{name}"] = "property"
        return components
    if isinstance(expr, Seq | Alt):
        return {
            **_regex_component_kinds(expr.left, f"{path}.left"),
            **_regex_component_kinds(expr.right, f"{path}.right"),
        }
    if isinstance(expr, Plus | Star | OptionalExpr | Bounded):
        return _regex_component_kinds(expr.child, f"{path}.child")
    raise TypeError(f"Unsupported PathPatternQuery expression {type(expr).__name__}.")


@dataclass(frozen=True)
class FileBackedRuntimeAlignmentProvider:
    """M11 provider over validated runtime grounding; performs no OWL/DL reasoning."""

    loader: OntologyArtifactLoader
    prompt_view: PromptSchemaView
    grounded_response: GroundedPlannerResponse
    backend_ids: tuple[str, ...]
    provider_id: str = "m12-file-backed-runtime-alignment"

    def __post_init__(self) -> None:
        if self.prompt_view.ontology_id != self.loader.ontology.ontology_id:
            raise ValueError("Prompt view ontology ID does not match DatasetBundle.")
        if self.prompt_view.ontology_hash != self.loader.ontology.ontology_hash:
            raise ValueError("Prompt view ontology hash does not match DatasetBundle.")
        if not self.backend_ids:
            raise ValueError("Runtime alignment requires at least one backend mapping scope.")
        known_backends = set(_mapping(self.loader.backend_mapping.get("backends", {})))
        unknown_backends = set(self.backend_ids) - known_backends
        if unknown_backends:
            raise ValueError(
                f"Runtime alignment references unknown backend mappings: {sorted(unknown_backends)}"
            )
        object.__setattr__(self, "backend_ids", tuple(self.backend_ids))

    def resolve(
        self,
        query_context: QueryPlanningContext,
        interpretation: PlannerCandidate,
    ) -> OntologyAlignmentContext:
        del query_context
        grounded = self.grounded_response.candidate(interpretation.candidate_id)
        anchors = {item.slot_id: item.query_anchor_id for item in self.grounded_response.query_anchors}
        missing_terms = tuple(
            sorted(
                {
                    item.ontology_term_id
                    for item in grounded.slot_realizations
                    if not self._mapped(item.ontology_term_id)
                }
            )
        )
        status = (
            MappingSufficiencyStatus.MISSING
            if missing_terms
            else MappingSufficiencyStatus.SUFFICIENT
        )
        reason = (
            "Missing backend mapping for ontology term(s): " + ", ".join(missing_terms)
            if missing_terms
            else ""
        )
        mapped_terms = tuple(
            item.ontology_term_id
            for item in grounded.slot_realizations
            if item.ontology_term_id not in missing_terms
        )
        slot_alignments = [
            {
                "slot_id": item.slot_id,
                "query_term": anchors[item.slot_id],
                "aligned_term": item.ontology_term_id,
                "covered": True,
                "query_anchor_available": True,
                "mapping_available": item.ontology_term_id not in missing_terms,
                "alignment_evidence_available": True,
                "metadata": {"component_ref": item.component_ref},
            }
            for item in grounded.slot_realizations
        ]
        identity = {
            "prompt_schema_view_hash": self.prompt_view.view_hash,
            "candidate_id": interpretation.candidate_id,
            "query_anchors": anchors,
            "slot_realizations": [item.to_dict() for item in grounded.slot_realizations],
            "mapping_hash": content_hash(self.loader.backend_mapping),
        }
        mapping = self.loader.backend_mapping
        return OntologyAlignmentContext(
            interpretation_id=interpretation.candidate_id,
            alignment_id="runtime-alignment-" + content_hash(identity)[:20],
            ontology_artifact_id=self.loader.ontology.ontology_id,
            ontology_version=self.loader.ontology.version,
            mapping_artifact_id=str(mapping["mapping_id"]),
            mapping_version=str(mapping["version"]),
            mapping_sufficiency=MappingSufficiencyResult(
                status=status,
                required_terms=tuple(item.ontology_term_id for item in grounded.slot_realizations),
                mapped_terms=mapped_terms,
                evidence=tuple(
                    f"runtime:{item.slot_id}:{anchors[item.slot_id]}->{item.ontology_term_id}"
                    for item in grounded.slot_realizations
                ),
                reason=reason,
            ),
            aliases={},
            semantic_inputs={"slot_alignments": slot_alignments},
            metadata={
                "provider_id": self.provider_id,
                "runtime": True,
                "gold_artifacts_used": False,
                "ontology_hash": self.loader.ontology.ontology_hash,
                "mapping_hash": content_hash(mapping),
                "prompt_schema_view_hash": self.prompt_view.view_hash,
            },
        )

    def grounding_record(self, candidate_id: str) -> dict[str, Any]:
        context = self.resolve(
            QueryPlanningContext("artifact", "artifact", "artifact"),
            self.grounded_response.candidate(candidate_id).candidate,
        )
        return {
            "candidate_id": candidate_id,
            "grounded_candidate": self.grounded_response.candidate(candidate_id).to_dict(),
            "alignment": context.to_dict(),
        }

    def _mapped(self, term_id: str) -> bool:
        mappings = _mapping(self.loader.backend_mapping.get("term_mappings", {}))
        return any(
            bool(_mapping(_mapping(mappings.get(backend_id, {})).get(term_id)))
            for backend_id in self.backend_ids
        )


def assert_no_gold_leakage(value: object) -> None:
    def visit(item: object, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                normalized_key = str(key).lower()
                if normalized_key in FORBIDDEN_INFERENCE_KEYS:
                    raise ValueError(f"Evaluation-only field leaked into inference artifact: {path}{key}")
                visit(child, f"{path}{key}.")
        elif isinstance(item, list | tuple):
            for index, child in enumerate(item):
                visit(child, f"{path}{index}.")

    visit(value, "")


def _normalize(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    normalized = [
        token[:-3] + "y"
        if token.endswith("ies") and len(token) > 4
        else token[:-1]
        if token.endswith("s") and len(token) > 3
        else token
        for token in tokens
    ]
    return " ".join(normalized)


def _phrase_in_question(phrase: str, normalized_question: str) -> bool:
    normalized = _normalize(phrase)
    return bool(normalized) and f" {normalized} " in f" {normalized_question} "


def _term_label(term_id: str) -> str:
    return _normalize(term_id)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize(value)).strip("-")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
