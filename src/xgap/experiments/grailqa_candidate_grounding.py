"""Versioned canonical-ID grounding for GrailQA, not native backend mappings.

The legacy runtime grounder remains the authority for anchors, slot coverage,
ordered relation hops and exact endpoint-derived types. This boundary also
checks what the candidate actually says, and isolates candidate-local failures.
It neither repairs an AST nor changes type checking or executable capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from xgap.experiments.runtime_alignment import (
    GroundedCandidate, GroundedPlannerResponse, PromptSchemaView,
    RuntimeAlignmentError, parse_grounded_planner_response,
)
from xgap.llm.openai_compatible import LiveFailureCategory
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.llm.schemas import PlannerResponse


LEGACY_GROUNDING_POLICY = "legacy_grounding_v1"
STRICT_GROUNDING_POLICY = "grailqa_canonical_ast_grounding_v1"
ENTITY_PROPERTY = "type.object.id"


def validate_grounding_policy(value: object) -> str:
    if not isinstance(value, str) or value not in (
        LEGACY_GROUNDING_POLICY, STRICT_GROUNDING_POLICY,
    ):
        raise ValueError("Unknown GrailQA candidate grounding policy.")
    return value


@dataclass(frozen=True)
class GroundingIssue:
    code: str
    message: str
    category: str = "relation_grounding_failure"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "category": self.category}


@dataclass(frozen=True)
class CandidateGroundingBatch:
    grounded: GroundedPlannerResponse
    failures: Mapping[str, GroundingIssue]


def ground_canonical_candidates(
    raw: Mapping[str, Any], parsed: PlannerResponse, view: PromptSchemaView,
) -> CandidateGroundingBatch:
    """Validate the shared envelope once, then each parsed candidate separately.

    Invalid JSON/ASTs are still rejected by the upstream provider/parser. This
    does not partially accept a malformed envelope or spend another model call.
    """
    raw_candidates = raw.get("candidates")
    ids = tuple(item.candidate_id for item in parsed.candidates)
    if (
        not isinstance(raw_candidates, list)
        or any(not isinstance(item, Mapping) for item in raw_candidates)
        or tuple(item.get("candidate_id") for item in raw_candidates) != ids
        or len(set(ids)) != len(ids)
        or len(ids) > parsed.request.max_candidates
    ):
        raise RuntimeAlignmentError(
            LiveFailureCategory.INVALID_CANDIDATE,
            "Canonical grounding requires unique ordered candidate IDs within the request cap.",
        )
    empty = replace(parsed, candidates=())
    anchors = parse_grounded_planner_response({**raw, "candidates": []}, empty, view)
    accepted: list[GroundedCandidate] = []
    failures: dict[str, GroundingIssue] = {}
    for candidate, raw_candidate in zip(parsed.candidates, raw_candidates):
        raw_grounding = raw_candidate.get("grounding")
        if isinstance(raw_grounding, Mapping):
            entities = raw_grounding.get("entity_ids", [])
            if (not isinstance(entities, list)
                    or any(not isinstance(item, str) or not item for item in entities)
                    or len(set(entities)) != len(entities)):
                failures[candidate.candidate_id] = GroundingIssue(
                    "invalid_entity_declaration", "Entity declarations must be a list of unique nonempty IDs.",
                    "entity_grounding_failure",
                )
                continue
        try:
            single = parse_grounded_planner_response(
                {**raw, "candidates": [raw_candidate]},
                replace(parsed, candidates=(candidate,)), view,
            )
        except RuntimeAlignmentError as error:
            failures[candidate.candidate_id] = GroundingIssue(
                "slot_grounding", str(error),
                "entity_grounding_failure" if "entity" in str(error).lower()
                else "relation_grounding_failure",
            )
            continue
        grounded = single.grounded_candidates[0]
        issue = canonical_ast_grounding_issue(grounded, view)
        if issue is not None:
            failures[candidate.candidate_id] = issue
        else:
            accepted.append(grounded)
    return CandidateGroundingBatch(
        GroundedPlannerResponse(parsed, anchors.query_anchors, tuple(accepted)), failures,
    )


def canonical_ast_grounding_issue(
    candidate: GroundedCandidate, view: PromptSchemaView,
) -> GroundingIssue | None:
    """Compare declarations with typed AST terms, never inferred aliases/gold.

    ``condition`` denotes one property only when every property predicate in
    that condition uses that same key. A class, empty label, or ambiguous group
    cannot stand in for a declared property realization.
    """
    pattern = path_pattern_query_to_dict(candidate.candidate.pattern_query)
    components: dict[str, tuple[str, str | None]] = {}
    used_entities: list[object] = []
    used_terms: list[tuple[str, str, object]] = []

    def properties(values: Mapping[str, Any], path: str) -> None:
        for name, value in values.items():
            ref = f"{path}.properties.{name}"
            components[ref] = ("property", name)
            if name == ENTITY_PROPERTY:
                used_entities.append(value)
            else:
                used_terms.append((ref, "property", name))

    for role in ("source", "target"):
        node = pattern[role]
        components[role] = ("class", node["label"])
        used_terms.append((role, "class", node["label"]))
        properties(node["properties"], role)

    def regex(expr: Mapping[str, Any], path: str) -> None:
        kind = expr["kind"]
        if kind == "rel":
            edge = expr["edge"]
            ref = f"{path}.edge"
            components[ref] = ("relation", edge["label"])
            used_terms.append((ref, "relation", edge["label"]))
            properties(edge["properties"], ref)
        elif kind in ("seq", "alt"):
            regex(expr["left"], f"{path}.left")
            regex(expr["right"], f"{path}.right")
        else:
            # The typed serializer only emits the existing unary regex kinds.
            regex(expr["child"], f"{path}.child")

    regex(pattern["expr"], "expr")
    condition_properties: set[str] = set()

    def condition(item: Mapping[str, Any] | None, path: str) -> None:
        if item is None:
            return
        kind = item["kind"]
        if kind in ("and", "or"):
            for index, child in enumerate(item["conditions"]):
                condition(child, f"{path}.conditions.{index}")
        elif kind == "not":
            condition(item["condition"], f"{path}.condition")
        elif "property" in item:
            name = item["property"]
            condition_properties.add(name)
            if name == ENTITY_PROPERTY:
                used_entities.append(item["value"])
            else:
                used_terms.append((path, "property", name))
        elif kind == "label_equals":
            used_terms.append((
                path, "class" if item["ref"]["kind"] == "node" else "relation", item["value"],
            ))

    condition(pattern["condition"], "condition")
    if len(condition_properties) == 1:
        components["condition"] = ("property", next(iter(condition_properties)))
    for realization in candidate.slot_realizations:
        actual = components.get(realization.component_ref)
        if actual is None or actual[1] != realization.ontology_term_id:
            return GroundingIssue(
                "component_term_mismatch",
                f"Declared term '{realization.ontology_term_id}' does not match actual "
                f"component '{realization.component_ref}': {actual!r}.",
            )
    visible = {item.term_id: item.kind for item in view.terms}
    derived = {(item.role.value, item.type_id) for item in candidate.endpoint_type_evidence}
    for ref, kind, term in used_terms:
        if term is None and not ref.startswith("condition"):
            continue  # An untyped pattern is not a declaration of a schema ID.
        if not isinstance(term, str) or not term:
            return GroundingIssue(
                "invalid_ast_term", f"Actual {kind} term at '{ref}' must be a nonempty string ID.",
            )
        if visible.get(term) != kind and (ref, term) not in derived:
            return GroundingIssue(
                "nonvisible_ast_term", f"Actual {kind} term '{term}' at '{ref}' is not prompt-visible.",
            )
    if any(not isinstance(item, str) or not item for item in used_entities):
        return GroundingIssue(
            "invalid_entity_literal", "Entity identity constraints require nonempty string IDs.",
            "entity_grounding_failure",
        )
    used_ids = set(used_entities)
    missing = used_ids - set(view.visible_entity_ids)
    undeclared = used_ids - set(candidate.entity_ids)
    if missing or undeclared:
        return GroundingIssue(
            "entity_identity_not_grounded",
            f"Actual entity IDs must be visible and declared; nonvisible={sorted(missing)}, "
            f"undeclared={sorted(undeclared)}.",
            "entity_grounding_failure",
        )
    return None
