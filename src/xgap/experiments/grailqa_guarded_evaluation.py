"""Independent aggregation of reconstructed development outcomes.

The caller opens evaluation-only inputs after all inference reconstruction.
This module shares the frozen component/failure/semantic mathematics, never
the producer's evaluation loop or its retained aggregate metrics.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_inline_evidence import _same
from xgap.experiments.interpretation_contract import (
    STAGE_AWARE_FAILURE_TAXONOMY, classify_first_failure, component_match_report,
    semantic_deviation_distribution,
)


def reconstruct_guarded_evaluation(
    *, states: Sequence[Mapping[str, Any]], references: Mapping[str, Mapping[str, Any]],
    reachability: Mapping[str, Mapping[str, Any]], coverage: Mapping[str, Any],
    epsilon_values: Sequence[float],
) -> dict[str, Any]:
    """Evaluate all questions, retaining rejected siblings and zero-call failures."""
    ids = [s["question"]["question_id"] for s in states]
    _same(sorted(references), sorted(ids), "exact evaluation reference population")
    _same(sorted(reachability), sorted(ids), "exact evaluation reachability population")
    candidates, rejected, components, failures, capabilities, semantic = [], [], [], [], [], []
    accepted_by_id, matched_by_id = {}, {}
    for state in states:
        qid = state["question"]["question_id"]
        _same(state["candidate_grounding_policy"], SEMANTIC_GROUNDING_POLICY, "evaluation grounding policy")
        _same(state["candidate_repair_policy"], TYPED_GROUNDING_ONCE, "evaluation repair policy")
        accepted = []
        semantic.extend(state["semantic_scores"])
        matched_by_id[qid] = False
        for row in state["candidates"]:
            capabilities.append({
                "question_id": qid, "candidate_id": row["candidate_id"],
                "semantic_valid": row["validation"]["ok"], "grounded": row["grounded"],
                "semantic_admissible": row["semantic_admissible"], "logical_lowering": row["logical_lowering"],
            })
            if row["validation"]["ok"] is not True or row["grounded"] is not True:
                rejected.append(dict(row))
                continue
            accepted.append(row)
            comparison = component_match_report(row["pattern_query"], references[qid]["pattern_query"])
            matches = comparison["matches"]["full_normalized_interpretation"]
            matched_by_id[qid] |= matches
            candidates.append({**row, "normalized_reference_match": matches})
            components.append({"question_id": qid, "candidate_id": row["candidate_id"], **comparison})
        accepted_by_id[qid] = accepted
        original_failure = state["failure"]
        shared_grounding_failure = bool(
            not state["candidates"] and original_failure
            and original_failure["category"] in {"entity_grounding_failure", "relation_grounding_failure"}
        )
        category = classify_first_failure(
            reachability_row=reachability[qid],
            malformed_output=bool(original_failure and original_failure["category"] == "malformed_output"),
            generated_candidates=state["returned_candidate_count"],
            type_check_ok=shared_grounding_failure or any(r["validation"]["ok"] is True for r in state["candidates"]),
            grounding_ok=bool(accepted), semantic_admissible=any(r["semantic_admissible"] for r in accepted),
            selected_candidate=bool(accepted), equivalent=matched_by_id[qid],
        )
        if category is not None:
            failures.append({
                "schema_version": "m13e1-stage-aware-failure-v1", "question_id": qid, "category": category,
                **({"original_inference_failure": dict(original_failure)} if original_failure is not None else {}),
            })
    subset = [qid for qid in ids if reachability[qid]["deployed_prompt"]["joint"]["reachable"]]
    count, total = len(subset), len(ids)
    by_id = {s["question"]["question_id"]: s for s in states}

    def rate(values, denominator):
        return sum(values) / denominator if denominator else None

    component_accuracy = {
        key: rate((bool(row["matches"][key]) for row in components), len(components))
        for key in (components[0]["matches"] if components else ())
    }
    failure_counts = Counter(r["category"] for r in failures)
    metrics = {
        "schema_version": "grailqa-semantic-capability-preflight-metrics-v1", "query_count": total,
        "catalog_availability": coverage["catalog"], "prompt_reachability": coverage["deployed_prompt"],
        "provider_success_rate": rate((s["api_call_completed"] for s in states), total),
        "structured_valid_rate": rate((bool(accepted_by_id[q]) for q in ids), total),
        "candidate_recall": rate(matched_by_id.values(), total),
        "jointly_reachable_subset": {
            "schema_version": "m13e3b5-jointly-reachable-subset-v1", "question_count": count,
            "unreachable_question_count": total - count, "prompt_reachability_ceiling": count / total if total else None,
            "provider_success_rate": rate((by_id[q]["api_call_completed"] for q in subset), count),
            "structured_valid_rate": rate((bool(accepted_by_id[q]) for q in subset), count),
            "candidate_recall": rate((matched_by_id[q] for q in subset), count),
            "matched_question_count": sum(matched_by_id[q] for q in subset),
        },
        "component_accuracy": component_accuracy,
        "full_normalized_interpretation_accuracy": component_accuracy.get("full_normalized_interpretation"),
        "c_sem": semantic_deviation_distribution(candidates),
        "feasible_coverage": {
            str(float(epsilon)): rate((any(r.get("semantic_deviation") is not None
                and float(r["semantic_deviation"]) <= float(epsilon) for r in accepted_by_id[q]) for q in ids), total)
            for epsilon in epsilon_values
        },
        "failure_taxonomy": {name: failure_counts[name] for name in STAGE_AWARE_FAILURE_TAXONOMY},
        "candidate_grounding_policy": SEMANTIC_GROUNDING_POLICY,
        "generated_candidate_count": sum(s["returned_candidate_count"] for s in states),
        "validated_grounded_candidate_count": len(candidates), "rejected_candidate_count": len(rejected),
        "unassessed_candidate_count": sum(s["returned_candidate_count"] - len(s["candidates"]) for s in states),
        "component_accuracy_scope": "validated_grounded_candidates_only",
        "candidate_recall_denominator": "all_questions_including_failures",
        "candidate_repair_policy": TYPED_GROUNDING_ONCE,
        "structured_valid_scope": "typed_semantics_and_grounding_not_execution",
        "logical_lowering_scope": "validated_grounded_candidates_not_backend_execution",
        "logical_lowering_status_counts": {
            status: sum(r["logical_lowering"]["status"] == status for r in candidates)
            for status in ("available", "unavailable", "error", "not_assessed")
        },
        "logical_lowering_available_query_rate": (
            sum(any(r["logical_lowering"]["available"] for r in accepted_by_id[q]) for q in ids) / total if total else 0.0),
        "backend_execution_verified": False,
    }
    return {"validated_candidates": candidates, "rejected_candidates": rejected,
            "component_match": components, "semantic_scores": semantic, "failures": failures,
            "candidate_capabilities": capabilities, "metrics": metrics}
