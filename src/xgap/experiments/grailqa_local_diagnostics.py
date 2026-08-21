"""Post-hoc diagnostics for query-local GrailQA catalog audits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from xgap.experiments.grailqa_reachability import (
    CatalogUniverse,
    reference_requirements,
)
from xgap.experiments.schema_ranking import RankedSchemaTerm


LOCAL_CONTRACT_COMPARISON_SCHEMA_VERSION = "m13e3b2-entity-retrieval-comparison-v1"
LOCAL_RELATION_DIAGNOSTIC_SCHEMA_VERSION = "m13e3b2-relation-diagnostic-v1"
LOCAL_TYPE_DIAGNOSTIC_SCHEMA_VERSION = "m13e3b2-type-diagnostic-v1"
SCHEMA_RANKING_COMPARISON_SCHEMA_VERSION = "m13e3b3-schema-ranking-comparison-v1"
RELATION_RANKING_AUDIT_SCHEMA_VERSION = "m13e3b3-relation-ranking-audit-v1"
TYPE_RANKING_AUDIT_SCHEMA_VERSION = "m13e3b3-type-ranking-audit-v1"
RELATION_DIAGNOSTIC_V2_SCHEMA_VERSION = "m13e3b3-relation-diagnostic-v2"
TYPE_DIAGNOSTIC_V2_SCHEMA_VERSION = "m13e3b3-type-diagnostic-v2"
ENDPOINT_GROUNDING_COMPARISON_SCHEMA_VERSION = (
    "m13e3b4-relation-endpoint-grounding-comparison-v1"
)
ENDPOINT_GROUNDING_DIAGNOSTIC_SCHEMA_VERSION = (
    "m13e3b4-relation-endpoint-grounding-diagnostic-v1"
)


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


def previous_schema_ranking_metrics(output: Path) -> dict[str, Any] | None:
    comparison_path = output / "schema_ranking_before_after.json"
    if comparison_path.is_file():
        before = _read_json(comparison_path).get("before")
        if isinstance(before, dict):
            return before
    summary_path = output / "audit_summary.json"
    if not summary_path.is_file():
        return None
    return schema_ranking_metrics(_read_json(summary_path))


def schema_ranking_metrics(audit: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(audit.get("summary"), "summary")
    retrieval = _mapping(summary.get("retrieval", {}), "retrieval")
    deployed = _mapping(summary.get("deployed_prompt", {}), "deployed_prompt")
    return {
        "relation_recall": {
            key: _optional_metric(retrieval.get(key), "relation")
            for key in ("1", "5", "10", "20")
        },
        "relation_prompt_coverage": _optional_metric(deployed, "relation"),
        "type_recall": {
            key: _optional_metric(retrieval.get(key), "type")
            for key in ("1", "5", "10", "20")
        },
        "type_prompt_coverage": _optional_metric(deployed, "type"),
        "joint_prompt_reachability": _optional_metric(deployed, "joint"),
    }


def previous_endpoint_grounding_metrics(output: Path) -> dict[str, Any] | None:
    comparison_path = output / "endpoint_grounding_before_after.json"
    if comparison_path.is_file():
        before = _read_json(comparison_path).get("before")
        if isinstance(before, dict):
            return before
    summary_path = output / "audit_summary.json"
    if not summary_path.is_file():
        return None
    return endpoint_grounding_metrics(_read_json(summary_path))


def endpoint_grounding_metrics(audit: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(audit.get("summary"), "summary")
    deployed = _mapping(summary.get("deployed_prompt", {}), "deployed_prompt")
    explicit = _optional_metric(deployed, "type")
    effective = _optional_metric(deployed, "effective_type") or explicit
    return {
        "explicit_type_prompt_coverage": explicit,
        "effective_type_prompt_coverage": effective,
        "joint_prompt_reachability": _optional_metric(deployed, "joint"),
    }


def endpoint_grounding_diagnostics(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        deployed = _mapping(row.get("deployed_prompt"), "deployed_prompt")
        grounding = _mapping(
            row.get("relation_endpoint_grounding"), "relation_endpoint_grounding"
        )
        result.append(
            {
                "schema_version": ENDPOINT_GROUNDING_DIAGNOSTIC_SCHEMA_VERSION,
                "question_id": str(row["question_id"]),
                "requirements": dict(_mapping(row.get("requirements"), "requirements")),
                "contract_version": grounding.get("contract_version"),
                "evidence": list(grounding.get("evidence", ())),
                "explicit_type": dict(_mapping(deployed.get("type"), "type")),
                "effective_type": dict(
                    _mapping(deployed.get("effective_type"), "effective_type")
                ),
                "joint": dict(_mapping(deployed.get("joint"), "joint")),
            }
        )
    return result


def schema_ranking_audits(
    *,
    references: Sequence[Mapping[str, Any]],
    trace_provider: Callable[[str], Mapping[str, Any]],
    prompt_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Use gold only to select records from already-computed ranking traces."""

    relation_rows: list[dict[str, Any]] = []
    type_rows: list[dict[str, Any]] = []
    taxonomy_counts: dict[str, int] = {}
    for reference in references:
        question_id = str(reference["question_id"])
        trace = trace_provider(question_id)
        # Only after the complete gold-free trace exists do we inspect requirements.
        requirement = reference_requirements(reference)
        relation_requirements: list[dict[str, Any]] = []
        raw_slots = tuple(trace["relation_slots"])
        for index, relation_id in enumerate(requirement.relations):
            slot = raw_slots[index] if index < len(raw_slots) else None
            record = _ranking_record(
                candidate_id=relation_id,
                legacy=() if slot is None else tuple(slot["legacy"]),
                repaired=() if slot is None else tuple(slot["repaired"]),
                prompt_limit=prompt_limit,
                legacy_rank_field="slot_rank",
                slot_context=() if slot is None else tuple(slot["expected_types"]),
                query_tokens=tuple(trace["query_tokens"]),
                relation_slots=raw_slots,
                relation_slot=index,
            )
            relation_requirements.append(record)
            for category in record["failure_taxonomy_before"]:
                taxonomy_counts[category] = taxonomy_counts.get(category, 0) + 1
        relation_rows.append(
            {
                "schema_version": RELATION_RANKING_AUDIT_SCHEMA_VERSION,
                "question_id": requirement.question_id,
                "query_tokens": list(trace["query_tokens"]),
                "required_reference_relation_sequence": list(requirement.relations),
                "required_relation_rankings": relation_requirements,
                "ranking_contract": dict(trace["contract"]),
                "gold_usage": "post_ranking_diagnostic_selection_only",
            }
        )

        type_trace = _mapping(trace["types"], "types")
        type_requirements = []
        for type_id in requirement.types:
            record = _ranking_record(
                candidate_id=type_id,
                legacy=tuple(type_trace["legacy"]),
                repaired=tuple(type_trace["repaired"]),
                prompt_limit=prompt_limit,
                legacy_rank_field="post_merge_rank",
                slot_context=(),
                query_tokens=tuple(trace["query_tokens"]),
            )
            type_requirements.append(record)
            for category in record["failure_taxonomy_before"]:
                taxonomy_counts[category] = taxonomy_counts.get(category, 0) + 1
        type_rows.append(
            {
                "schema_version": TYPE_RANKING_AUDIT_SCHEMA_VERSION,
                "question_id": requirement.question_id,
                "query_tokens": list(trace["query_tokens"]),
                "required_reference_types": list(requirement.types),
                "required_type_rankings": type_requirements,
                "candidate_provenance": {
                    key: list(value)
                    for key, value in sorted(
                        _mapping(type_trace["provenance"], "provenance").items()
                    )
                },
                "ranking_contract": dict(trace["contract"]),
                "gold_usage": "post_ranking_diagnostic_selection_only",
            }
        )
    return relation_rows, type_rows, dict(sorted(taxonomy_counts.items()))


def diagnostic_rows_v2(
    rows: Sequence[Mapping[str, Any]],
    ranking_rows: Sequence[Mapping[str, Any]],
    *,
    kind: str,
) -> list[dict[str, Any]]:
    ranking_by_id = {str(item["question_id"]): item for item in ranking_rows}
    result = []
    for row in rows:
        question_id = str(row["question_id"])
        value = dict(row)
        value["schema_version"] = (
            RELATION_DIAGNOSTIC_V2_SCHEMA_VERSION
            if kind == "relation"
            else TYPE_DIAGNOSTIC_V2_SCHEMA_VERSION
        )
        ranking = ranking_by_id[question_id]
        key = (
            "required_relation_rankings"
            if kind == "relation"
            else "required_type_rankings"
        )
        value["ranking_failure_taxonomy_before"] = [
            {
                "id": item["id"],
                "categories": list(item["failure_taxonomy_before"]),
            }
            for item in ranking[key]
        ]
        result.append(value)
    return result


def _ranking_record(
    *,
    candidate_id: str,
    legacy: Sequence[Mapping[str, Any]],
    repaired: Sequence[RankedSchemaTerm],
    prompt_limit: int,
    legacy_rank_field: str,
    slot_context: Sequence[str],
    query_tokens: Sequence[str],
    relation_slots: Sequence[Mapping[str, Any]] = (),
    relation_slot: int | None = None,
) -> dict[str, Any]:
    legacy_match = next((item for item in legacy if item["id"] == candidate_id), None)
    repaired_match = next(
        (item for item in repaired if item.term.term_id == candidate_id), None
    )
    legacy_rank = (
        None if legacy_match is None else legacy_match.get(legacy_rank_field)
    )
    repaired_rank = None if repaired_match is None else repaired_match.rank
    legacy_beating = [
        dict(item)
        for item in legacy
        if item.get(legacy_rank_field) is not None
        and (legacy_rank is None or int(item[legacy_rank_field]) < int(legacy_rank))
    ][:8]
    repaired_beating = [
        item.to_audit_dict()
        for item in repaired
        if repaired_rank is None or item.rank < repaired_rank
    ][:8]
    repaired_dict = None if repaired_match is None else repaired_match.to_audit_dict()
    taxonomy = _failure_taxonomy(
        legacy_match=legacy_match,
        repaired_match=repaired_match,
        legacy_beating=legacy_beating,
        legacy_rank=legacy_rank,
        prompt_limit=prompt_limit,
        relation_slots=relation_slots,
        relation_slot=relation_slot,
        candidate_id=candidate_id,
    )
    return {
        "id": candidate_id,
        "query_tokens": list(query_tokens),
        "slot_tokens": list(query_tokens),
        "slot_expected_types": list(slot_context),
        "legacy": None if legacy_match is None else dict(legacy_match),
        "repaired": repaired_dict,
        "legacy_pretruncation_rank": (
            None
            if legacy_match is None
            else legacy_match.get("lexical_pretruncation_rank", legacy_match.get("rank"))
        ),
        "legacy_top_20_member": legacy_rank is not None and int(legacy_rank) <= 20,
        "legacy_top_4_prompt_member": (
            legacy_rank is not None and int(legacy_rank) <= prompt_limit
        ),
        "repaired_pretruncation_rank": repaired_rank,
        "repaired_top_20_member": (
            repaired_rank is not None and repaired_rank <= 20
        ),
        "repaired_top_4_prompt_member": (
            repaired_rank is not None and repaired_rank <= prompt_limit
        ),
        "legacy_candidates_that_beat_required": legacy_beating,
        "repaired_candidates_that_beat_required": repaired_beating,
        "failure_taxonomy_before": taxonomy,
    }


def _failure_taxonomy(
    *,
    legacy_match: Mapping[str, Any] | None,
    repaired_match: RankedSchemaTerm | None,
    legacy_beating: Sequence[Mapping[str, Any]],
    legacy_rank: object,
    prompt_limit: int,
    relation_slots: Sequence[Mapping[str, Any]],
    relation_slot: int | None,
    candidate_id: str,
) -> list[str]:
    if legacy_rank is not None and int(legacy_rank) <= prompt_limit:
        return []
    categories: set[str] = set()
    if legacy_match is None or float(legacy_match.get("score", 0.0)) <= 0.0:
        categories.add("zero_overlap_tie")
        categories.add("missing_public_descriptor")
    if repaired_match is not None:
        tier = repaired_match.lexical.tier_name
        if tier == "exact_normalized_phrase":
            categories.add("exact_phrase_loses")
        elif tier in {
            "complete_informative_tokens",
            "contiguous_partial_phrase",
            "informative_partial_overlap",
        }:
            categories.add("partial_overlap_bias")
        if repaired_match.coherence_level and (
            legacy_rank is None or int(legacy_rank) > prompt_limit
        ):
            categories.add("schema_coherence_unused")
    if any(
        int(item.get("descriptor_token_count", 0)) == 1
        and float(item.get("score", 0.0)) > 0.0
        for item in legacy_beating
    ):
        categories.add("generic_token_dominance")
    if relation_slot is not None and any(
        index != relation_slot
        and any(
            item["id"] == candidate_id and item.get("slot_rank") is not None
            and int(item["slot_rank"]) <= prompt_limit
            for item in slot["legacy"]
        )
        for index, slot in enumerate(relation_slots)
    ):
        categories.add("slot_misalignment")
    return sorted(categories)


def _optional_metric(value: object, kind: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    metric = value.get(kind)
    return dict(metric) if isinstance(metric, Mapping) else None


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
