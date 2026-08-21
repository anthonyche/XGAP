"""Post-hoc diagnostics for query-local GrailQA catalog audits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from xgap.experiments.grailqa_reachability import (
    CatalogUniverse,
    reference_requirements,
)


LOCAL_CONTRACT_COMPARISON_SCHEMA_VERSION = "m13e3b2-entity-retrieval-comparison-v1"
LOCAL_RELATION_DIAGNOSTIC_SCHEMA_VERSION = "m13e3b2-relation-diagnostic-v1"
LOCAL_TYPE_DIAGNOSTIC_SCHEMA_VERSION = "m13e3b2-type-diagnostic-v1"


def relation_type_diagnostics(
    *,
    references: Sequence[Mapping[str, Any]],
    retrieval_rows: Sequence[Mapping[str, Any]],
    catalog: CatalogUniverse,
    prompt_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retrieval_by_id = {str(item["question_id"]): item for item in retrieval_rows}
    relation_rows: list[dict[str, Any]] = []
    type_rows: list[dict[str, Any]] = []
    for reference in references:
        requirement = reference_requirements(reference)
        retrieval = retrieval_by_id[requirement.question_id]
        relation_slots = tuple(
            tuple(_diagnostic_candidate(item) for item in slot.get("candidates", ()))
            for slot in retrieval.get("relation_slots", ())
        )
        relation_requirements = []
        for index, relation_id in enumerate(requirement.relations):
            candidates = relation_slots[index] if index < len(relation_slots) else ()
            relation_requirements.append(
                _diagnose_required_candidate(
                    candidate_id=relation_id,
                    universe=catalog.relations,
                    retrieved=candidates,
                    prompt_visible=candidates[:prompt_limit],
                    position=index + 1,
                )
            )
        relation_rows.append(
            {
                "schema_version": LOCAL_RELATION_DIAGNOSTIC_SCHEMA_VERSION,
                "question_id": requirement.question_id,
                "required_reference_relation_sequence": list(requirement.relations),
                "retrieved_relation_slots": [
                    {"slot": index + 1, "candidates": list(candidates)}
                    for index, candidates in enumerate(relation_slots)
                ],
                "prompt_visible_relation_slots": [
                    {
                        "slot": index + 1,
                        "candidates": list(candidates[:prompt_limit]),
                    }
                    for index, candidates in enumerate(relation_slots)
                ],
                "required_relation_diagnostics": relation_requirements,
                "failure_stage": _overall_diagnostic_stage(relation_requirements),
            }
        )

        type_candidates = tuple(
            _diagnostic_candidate(item)
            for item in retrieval.get("type_candidates", ())
        )
        visible_types = type_candidates[:prompt_limit]
        type_requirements = [
            _diagnose_required_candidate(
                candidate_id=type_id,
                universe=catalog.types,
                retrieved=type_candidates,
                prompt_visible=visible_types,
            )
            for type_id in requirement.types
        ]
        type_rows.append(
            {
                "schema_version": LOCAL_TYPE_DIAGNOSTIC_SCHEMA_VERSION,
                "question_id": requirement.question_id,
                "required_reference_types": list(requirement.types),
                "retrieved_types": list(type_candidates),
                "prompt_visible_types": list(visible_types),
                "required_type_diagnostics": type_requirements,
                "failure_stage": _overall_diagnostic_stage(type_requirements),
            }
        )
    return relation_rows, type_rows


def diagnostic_stage_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stages = ("ontology_universe", "retrieval", "prompt_truncation", "reachable")
    counts = {stage: 0 for stage in stages}
    for row in rows:
        stage = str(row["failure_stage"])
        if stage not in counts:
            raise ValueError(f"Unknown relation/type diagnostic stage: {stage}")
        counts[stage] += 1
    total = len(rows)
    return {
        "question_count": total,
        "counts": counts,
        "ratios": {
            stage: count / total if total else None for stage, count in counts.items()
        },
    }


def previous_entity_contract_metrics(output: Path) -> dict[str, Any] | None:
    comparison_path = output / "entity_retrieval_before_after.json"
    if comparison_path.is_file():
        before = _read_json(comparison_path).get("before")
        if isinstance(before, dict):
            return before
    summary_path = output / "audit_summary.json"
    if not summary_path.is_file():
        return None
    return entity_contract_metrics(_read_json(summary_path))


def entity_contract_metrics(audit: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(audit.get("summary"), "summary")
    retrieval = _mapping(summary.get("retrieval"), "retrieval")
    deployed = _mapping(summary.get("deployed_prompt"), "deployed_prompt")
    return {
        "entity_recall": {
            key: dict(_mapping(_mapping(retrieval.get(key), key).get("entity"), "entity"))
            for key in ("1", "5", "10", "20")
        },
        "entity_prompt_coverage": dict(_mapping(deployed.get("entity"), "entity")),
        "joint_prompt_reachability": dict(_mapping(deployed.get("joint"), "joint")),
    }


def _diagnostic_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(value["id"]),
        "label": str(value.get("label", "")),
        "matched_label": str(value.get("matched_label", "")),
        "rank": int(value["rank"]),
        "score": float(value["score"]),
    }


def _diagnose_required_candidate(
    *,
    candidate_id: str,
    universe: Iterable[str],
    retrieved: Sequence[Mapping[str, Any]],
    prompt_visible: Sequence[Mapping[str, Any]],
    position: int | None = None,
) -> dict[str, Any]:
    retrieved_match = next(
        (item for item in retrieved if item["id"] == candidate_id), None
    )
    in_universe = candidate_id in universe
    is_prompt_visible = any(item["id"] == candidate_id for item in prompt_visible)
    if not in_universe:
        failure_stage = "ontology_universe"
    elif retrieved_match is None:
        failure_stage = "retrieval"
    elif not is_prompt_visible:
        failure_stage = "prompt_truncation"
    else:
        failure_stage = "reachable"
    result = {
        "id": candidate_id,
        "in_ontology_universe": in_universe,
        "retrieval_rank": (
            None if retrieved_match is None else int(retrieved_match["rank"])
        ),
        "retrieval_score": (
            None if retrieved_match is None else float(retrieved_match["score"])
        ),
        "prompt_visible": is_prompt_visible,
        "failure_stage": failure_stage,
    }
    if position is not None:
        result["position"] = position
    return result


def _overall_diagnostic_stage(requirements: Sequence[Mapping[str, Any]]) -> str:
    stages = {str(item["failure_stage"]) for item in requirements}
    for stage in ("ontology_universe", "retrieval", "prompt_truncation"):
        if stage in stages:
            return stage
    return "reachable"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(_mapping(value, str(path)))


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return value
