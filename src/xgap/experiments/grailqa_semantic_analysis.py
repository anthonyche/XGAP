"""Analyze paired GrailQA semantic-ranking outcomes at the query level.

This module consumes a post-inference query ledger.  It never calls the model,
catalog, ontology service, or a graph backend.  Both methods reuse the same
generated, validated, grounded candidates; only ranking/admission differs.
The analyzer remains ``paper_result=false`` until a separate evidence auditor
reconstructs both the ledger and these statistics.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
from typing import Any, Iterable, Mapping, Sequence

from xgap.experiments.grailqa_semantic_paper_protocol import (
    DEFAULT_PROTOCOL_PATH,
    compile_grailqa_semantic_paper_readiness,
)
from xgap.experiments.hashing import content_hash


QUERY_OUTCOME_SCHEMA_VERSION = "m13e4-grailqa-semantic-query-outcome-v1"
ANALYSIS_SCHEMA_VERSION = "m13e4-grailqa-semantic-analysis-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECISION_IDS = {
    "primary_reporting_population",
    "primary_epsilon",
    "primary_comparator",
    "inference_failure_estimand",
    "interactive_clarification_role",
}
_FAILURES = {
    None,
    "retrieval_miss",
    "provider_failure",
    "generation_miss",
    "malformed_output",
    "type_check_failure",
    "entity_grounding_failure",
    "relation_grounding_failure",
    "semantic_bound_rejection",
    "ranking_failure",
    "equivalence_failure",
}


class GrailQASemanticAnalysisError(ValueError):
    """Raised when an outcome ledger violates the paper analysis contract."""


def _strict_object(
    value: object, *, name: str, fields: set[str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GrailQASemanticAnalysisError(f"{name} must be an object")
    result = dict(value)
    missing = fields - set(result)
    unknown = set(result) - fields
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if unknown:
            details.append("unknown=" + ",".join(sorted(unknown)))
        raise GrailQASemanticAnalysisError(
            f"{name} fields changed ({'; '.join(details)})"
        )
    return result


def _finite_number(value: object, *, name: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GrailQASemanticAnalysisError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise GrailQASemanticAnalysisError(f"{name} is outside its domain")
    return result


def _integer(value: object, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GrailQASemanticAnalysisError(f"{name} must be an integer >= {minimum}")
    return value


def _boolean(value: object, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise GrailQASemanticAnalysisError(f"{name} must be boolean")
    return value


def _safe_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise GrailQASemanticAnalysisError(f"{name} must be nonempty text")
    return value


def _candidate(
    value: object, *, question_id: str, position: int
) -> dict[str, Any]:
    raw = _strict_object(
        value,
        name=f"{question_id}.candidates[{position}]",
        fields={
            "candidate_id",
            "candidate_index",
            "confidence",
            "validation_ok",
            "grounded",
            "hard_constraints_preserved",
            "semantic_admissible",
            "semantic_deviation",
            "equivalence_key",
            "reference_supported",
        },
    )
    candidate_id = _safe_text(raw["candidate_id"], name="candidate_id")
    index = _integer(raw["candidate_index"], name="candidate_index", minimum=1)
    if index != position:
        raise GrailQASemanticAnalysisError(
            f"{question_id} candidate indices must be contiguous and one-based"
        )
    confidence = _finite_number(raw["confidence"], name="confidence")
    if confidence > 1.0:
        raise GrailQASemanticAnalysisError("confidence must be within [0, 1]")
    validation_ok = _boolean(raw["validation_ok"], name="validation_ok")
    grounded = _boolean(raw["grounded"], name="grounded")
    hard = _boolean(
        raw["hard_constraints_preserved"], name="hard_constraints_preserved"
    )
    admissible = _boolean(raw["semantic_admissible"], name="semantic_admissible")
    if grounded and not validation_ok:
        raise GrailQASemanticAnalysisError(
            f"{question_id} cannot ground a type-invalid candidate"
        )
    if admissible and (not validation_ok or not grounded or not hard):
        raise GrailQASemanticAnalysisError(
            f"{question_id} semantic admission bypassed deterministic guards"
        )
    deviation = raw["semantic_deviation"]
    if admissible:
        deviation = _finite_number(deviation, name="semantic_deviation")
    elif deviation is not None:
        raise GrailQASemanticAnalysisError(
            f"{question_id} inadmissible candidate has a finite deviation"
        )
    equivalence_key = _safe_text(raw["equivalence_key"], name="equivalence_key")
    reference_supported = _boolean(
        raw["reference_supported"], name="reference_supported"
    )
    return {
        "candidate_id": candidate_id,
        "candidate_index": index,
        "confidence": confidence,
        "validation_ok": validation_ok,
        "grounded": grounded,
        "hard_constraints_preserved": hard,
        "semantic_admissible": admissible,
        "semantic_deviation": deviation,
        "equivalence_key": equivalence_key,
        "reference_supported": reference_supported,
    }


def _query_outcome(value: object) -> dict[str, Any]:
    raw = _strict_object(
        value,
        name="query_outcome",
        fields={
            "schema_version",
            "question_id",
            "split",
            "q_bucket",
            "jointly_prompt_reachable",
            "provider",
            "failure_category",
            "candidates",
        },
    )
    if raw["schema_version"] != QUERY_OUTCOME_SCHEMA_VERSION:
        raise GrailQASemanticAnalysisError("query outcome schema changed")
    question_id = _safe_text(raw["question_id"], name="question_id")
    split = str(raw["split"])
    if split not in {"train", "dev"}:
        raise GrailQASemanticAnalysisError(f"{question_id} split is invalid")
    q_bucket = _integer(raw["q_bucket"], name="q_bucket", minimum=1)
    reachable = _boolean(
        raw["jointly_prompt_reachable"], name="jointly_prompt_reachable"
    )
    provider = _strict_object(
        raw["provider"],
        name=f"{question_id}.provider",
        fields={
            "completed",
            "external_calls",
            "repair_calls",
            "input_tokens",
            "output_tokens",
            "latency_ms",
        },
    )
    normalized_provider = {
        "completed": _boolean(provider["completed"], name="provider.completed"),
        "external_calls": _integer(
            provider["external_calls"], name="provider.external_calls"
        ),
        "repair_calls": _integer(
            provider["repair_calls"], name="provider.repair_calls"
        ),
        "input_tokens": _integer(
            provider["input_tokens"], name="provider.input_tokens"
        ),
        "output_tokens": _integer(
            provider["output_tokens"], name="provider.output_tokens"
        ),
        "latency_ms": _finite_number(
            provider["latency_ms"], name="provider.latency_ms"
        ),
    }
    if normalized_provider["repair_calls"] > 1:
        raise GrailQASemanticAnalysisError("repair call bound exceeded")
    if normalized_provider["external_calls"] not in {0, 1, 2}:
        raise GrailQASemanticAnalysisError("external call bound exceeded")
    if normalized_provider["repair_calls"] > normalized_provider["external_calls"]:
        raise GrailQASemanticAnalysisError("repair calls exceed external calls")
    failure = raw["failure_category"]
    if failure not in _FAILURES:
        raise GrailQASemanticAnalysisError(
            f"{question_id} failure category is invalid"
        )
    candidate_values = raw["candidates"]
    if not isinstance(candidate_values, list) or len(candidate_values) > 3:
        raise GrailQASemanticAnalysisError(
            f"{question_id} candidate count exceeds the frozen cap"
        )
    candidates = [
        _candidate(item, question_id=question_id, position=index)
        for index, item in enumerate(candidate_values, start=1)
    ]
    if len({item["candidate_id"] for item in candidates}) != len(candidates):
        raise GrailQASemanticAnalysisError(
            f"{question_id} candidate IDs are not unique"
        )
    if not normalized_provider["completed"] and candidates:
        raise GrailQASemanticAnalysisError(
            f"{question_id} failed provider call cannot emit candidates"
        )
    completed_empty_failures = {
        "generation_miss",
        "entity_grounding_failure",
        "relation_grounding_failure",
    }
    if (
        normalized_provider["completed"]
        and not candidates
        and failure not in completed_empty_failures
    ):
        raise GrailQASemanticAnalysisError(
            f"{question_id} completed provider call must emit a nonempty candidate set"
        )
    if failure == "retrieval_miss":
        if normalized_provider["completed"] or normalized_provider["external_calls"]:
            raise GrailQASemanticAnalysisError(
                f"{question_id} retrieval miss cannot spend a provider call"
            )
    else:
        expected_calls = normalized_provider["repair_calls"] + 1
        if normalized_provider["external_calls"] != expected_calls:
            raise GrailQASemanticAnalysisError(
                f"{question_id} provider and repair call accounting diverged"
            )
    if failure in {"provider_failure", "malformed_output"}:
        if normalized_provider["completed"]:
            raise GrailQASemanticAnalysisError(
                f"{question_id} failed provider outcome cannot be completed"
            )
    elif failure != "retrieval_miss" and not normalized_provider["completed"]:
        raise GrailQASemanticAnalysisError(
            f"{question_id} local failure requires a completed provider response"
        )
    return {
        "question_id": question_id,
        "split": split,
        "q_bucket": q_bucket,
        "jointly_prompt_reachable": reachable,
        "provider": normalized_provider,
        "failure_category": failure,
        "candidates": candidates,
    }


def _selected_decisions(value: Mapping[str, object]) -> dict[str, str]:
    if set(value) != _DECISION_IDS:
        raise GrailQASemanticAnalysisError("selected decision registry changed")
    result = {key: str(item) for key, item in value.items()}
    allowed = {
        "primary_reporting_population": {
            "all_150_plus_joint_reachability_stratum",
            "jointly_reachable_only",
            "defer_semantic_track",
        },
        "primary_epsilon": {"0.0", "0.1", "0.25"},
        "primary_comparator": {
            "model_confidence_top1_same_candidate_set",
            "first_valid_grounded_candidate",
        },
        "inference_failure_estimand": {
            "all_queries_failures_count_incorrect",
            "available_case_primary_with_all_query_sensitivity",
        },
        "interactive_clarification_role": {
            "oracle_upper_bound_only",
            "exclude_from_grailqa",
        },
    }
    for key, selected in result.items():
        if selected not in allowed[key]:
            raise GrailQASemanticAnalysisError(f"{key} selection is invalid")
    if result["primary_reporting_population"] == "defer_semantic_track":
        raise GrailQASemanticAnalysisError(
            "deferred semantic track cannot produce a paper analysis"
        )
    return result


def _shared_grounded(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in candidates
        if item["validation_ok"]
        and item["grounded"]
        and item["hard_constraints_preserved"]
    ]


def _comparator_choice(
    candidates: Sequence[Mapping[str, Any]], comparator: str
) -> dict[str, Any] | None:
    eligible = _shared_grounded(candidates)
    if not eligible:
        return None
    if comparator == "first_valid_grounded_candidate":
        return min(
            eligible,
            key=lambda item: (item["candidate_index"], item["candidate_id"]),
        )
    return min(
        eligible,
        key=lambda item: (
            -float(item["confidence"]),
            int(item["candidate_index"]),
            str(item["candidate_id"]),
        ),
    )


def _xgap_frontier(
    candidates: Sequence[Mapping[str, Any]], epsilon: float
) -> list[dict[str, Any]]:
    eligible = [
        dict(item)
        for item in _shared_grounded(candidates)
        if item["semantic_admissible"]
        and item["semantic_deviation"] is not None
        and float(item["semantic_deviation"]) <= epsilon
    ]
    eligible.sort(
        key=lambda item: (
            float(item["semantic_deviation"]),
            -float(item["confidence"]),
            int(item["candidate_index"]),
            str(item["candidate_id"]),
        )
    )
    representatives: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in eligible:
        key = str(item["equivalence_key"])
        if key in seen:
            continue
        seen.add(key)
        representatives.append(item)
    return representatives[:3]


def _mcnemar(rows: Sequence[Mapping[str, Any]], left: str, right: str) -> dict[str, Any]:
    left_only = sum(bool(item[left]) and not bool(item[right]) for item in rows)
    right_only = sum(bool(item[right]) and not bool(item[left]) for item in rows)
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(
            math.comb(discordant, index)
            for index in range(min(left_only, right_only) + 1)
        ) / (2**discordant)
        p_value = min(1.0, 2.0 * tail)
    return {
        "method": "exact_two_sided_McNemar",
        "left_only": left_only,
        "right_only": right_only,
        "discordant_count": discordant,
        "p_value": p_value,
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise GrailQASemanticAnalysisError("cannot take a quantile of no values")
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _paired_bootstrap(
    rows: Sequence[Mapping[str, Any]], *, left: str, right: str
) -> dict[str, Any]:
    if not rows:
        return {
            "method": "query_paired_bootstrap_percentile",
            "resamples": 10000,
            "seed": "m13e4-grailqa-semantic-ci-v1",
            "confidence_interval": None,
        }
    seed_text = "m13e4-grailqa-semantic-ci-v1"
    seed = int(hashlib.sha256(seed_text.encode("ascii")).hexdigest()[:16], 16)
    generator = random.Random(seed)
    differences = [float(bool(item[left])) - float(bool(item[right])) for item in rows]
    estimates = [
        sum(generator.choice(differences) for _ in differences) / len(differences)
        for _ in range(10000)
    ]
    return {
        "method": "query_paired_bootstrap_percentile",
        "resamples": 10000,
        "seed": seed_text,
        "confidence_interval": [
            _quantile(estimates, 0.025),
            _quantile(estimates, 0.975),
        ],
    }


def _holm(items: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(items.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for index, (name, p_value) in enumerate(ordered):
        running = max(running, min(1.0, (count - index) * p_value))
        adjusted[name] = running
    return {name: adjusted[name] for name in sorted(adjusted)}


def _mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return sum(collected) / len(collected) if collected else None


def _method_metrics(rows: Sequence[Mapping[str, Any]], prefix: str) -> dict[str, Any]:
    count = len(rows)
    correct = sum(bool(item[f"{prefix}_correct"]) for item in rows)
    covered = sum(bool(item[f"{prefix}_covered"]) for item in rows)
    return {
        "query_count": count,
        "correct_count": correct,
        "accuracy": correct / count if count else None,
        "covered_count": covered,
        "coverage": covered / count if count else None,
    }


def _paired_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    xgap = _method_metrics(rows, "xgap")
    comparator = _method_metrics(rows, "comparator")
    difference = (
        xgap["accuracy"] - comparator["accuracy"]
        if xgap["accuracy"] is not None and comparator["accuracy"] is not None
        else None
    )
    return {
        "query_count": len(rows),
        "xgap": xgap,
        "comparator": comparator,
        "paired_accuracy_difference": difference,
        "primary_test": _mcnemar(rows, "xgap_correct", "comparator_correct"),
        "confidence_interval": _paired_bootstrap(
            rows, left="xgap_correct", right="comparator_correct"
        ),
    }


def analyze_grailqa_semantic_outcomes(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    expected_question_ids: Sequence[str],
    expected_distribution: Mapping[str, object],
    selected_decisions: Mapping[str, object],
    protocol_sha256: str,
    author_selection_sha256: str,
    source_run_sha256: str,
    outcome_ledger_sha256: str,
) -> dict[str, Any]:
    """Validate one exact population and compute the frozen paired analysis."""

    decisions = _selected_decisions(selected_decisions)
    for name, value in (
        ("protocol_sha256", protocol_sha256),
        ("author_selection_sha256", author_selection_sha256),
        ("source_run_sha256", source_run_sha256),
        ("outcome_ledger_sha256", outcome_ledger_sha256),
    ):
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise GrailQASemanticAnalysisError(f"{name} is not a SHA-256")
    expected = tuple(str(item) for item in expected_question_ids)
    if len(expected) != 150 or len(set(expected)) != 150:
        raise GrailQASemanticAnalysisError(
            "paper analysis requires exactly 150 unique frozen query IDs"
        )
    normalized = [_query_outcome(item) for item in outcomes]
    by_id = {item["question_id"]: item for item in normalized}
    if len(by_id) != len(normalized):
        raise GrailQASemanticAnalysisError("query outcomes contain duplicate IDs")
    if set(by_id) != set(expected):
        raise GrailQASemanticAnalysisError(
            "query outcomes do not cover the exact frozen 150-query population"
        )
    if not isinstance(expected_distribution, Mapping):
        raise GrailQASemanticAnalysisError("expected population distribution is invalid")
    expected_splits = expected_distribution.get("split")
    expected_q = expected_distribution.get("Q")
    if (
        not isinstance(expected_splits, Mapping)
        or not isinstance(expected_q, Mapping)
        or sum(expected_splits.values()) != len(expected)
        or sum(expected_q.values()) != len(expected)
    ):
        raise GrailQASemanticAnalysisError("expected population distribution is invalid")
    observed_splits = Counter(item["split"] for item in normalized)
    observed_q = Counter(str(item["q_bucket"]) for item in normalized)
    if dict(observed_splits) != dict(expected_splits):
        raise GrailQASemanticAnalysisError("query split distribution changed")
    if dict(observed_q) != dict(expected_q):
        raise GrailQASemanticAnalysisError("query Q-bucket distribution changed")

    epsilon = float(decisions["primary_epsilon"])
    comparator_name = decisions["primary_comparator"]
    per_query: list[dict[str, Any]] = []
    for question_id in expected:
        outcome = by_id[question_id]
        candidates = outcome["candidates"]
        frontier = _xgap_frontier(candidates, epsilon)
        xgap = frontier[0] if frontier else None
        comparator = _comparator_choice(candidates, comparator_name)
        provider = outcome["provider"]
        per_query.append(
            {
                "question_id": question_id,
                "split": outcome["split"],
                "q_bucket": outcome["q_bucket"],
                "jointly_prompt_reachable": outcome["jointly_prompt_reachable"],
                "failure_category": outcome["failure_category"],
                "candidate_count": len(candidates),
                "candidate_recall_at_3": any(
                    bool(item["reference_supported"]) for item in candidates
                ),
                "generated_hard_constraint_violation_count": sum(
                    not bool(item["hard_constraints_preserved"])
                    for item in candidates
                ),
                "xgap_frontier_candidate_ids": [
                    item["candidate_id"] for item in frontier
                ],
                "xgap_frontier_size": len(frontier),
                "xgap_selected_candidate_id": (
                    xgap["candidate_id"] if xgap is not None else None
                ),
                "xgap_covered": xgap is not None,
                "xgap_correct": bool(
                    xgap is not None and xgap["reference_supported"]
                ),
                "comparator_selected_candidate_id": (
                    comparator["candidate_id"] if comparator is not None else None
                ),
                "comparator_covered": comparator is not None,
                "comparator_correct": bool(
                    comparator is not None and comparator["reference_supported"]
                ),
                "provider": provider,
            }
        )

    reporting_rows = per_query
    if decisions["primary_reporting_population"] == "jointly_reachable_only":
        reporting_rows = [item for item in per_query if item["jointly_prompt_reachable"]]
    inferential_rows = reporting_rows
    if (
        decisions["inference_failure_estimand"]
        == "available_case_primary_with_all_query_sensitivity"
    ):
        inferential_rows = [
            item
            for item in reporting_rows
            if item["xgap_covered"] and item["comparator_covered"]
        ]
    if not inferential_rows:
        raise GrailQASemanticAnalysisError("selected primary population is empty")

    coverage_test = _mcnemar(
        reporting_rows, "xgap_covered", "comparator_covered"
    )
    correctness_test = _mcnemar(
        inferential_rows, "xgap_correct", "comparator_correct"
    )
    secondary_raw = {"coverage": float(coverage_test["p_value"])}
    failure_counts = Counter(item["failure_category"] for item in per_query)
    provider_totals = {
        field: sum(item["provider"][field] for item in per_query)
        for field in (
            "external_calls",
            "repair_calls",
            "input_tokens",
            "output_tokens",
            "latency_ms",
        )
    }
    provider_totals["completed_queries"] = sum(
        item["provider"]["completed"] for item in per_query
    )
    jointly_reachable = [item for item in per_query if item["jointly_prompt_reachable"]]
    provider_completers = [item for item in per_query if item["provider"]["completed"]]
    hard_violation_queries = sum(
        item["generated_hard_constraint_violation_count"] > 0
        for item in reporting_rows
    )
    body: dict[str, Any] = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "protocol_sha256": protocol_sha256,
        "author_selection_sha256": author_selection_sha256,
        "source_run_sha256": source_run_sha256,
        "outcome_ledger_sha256": outcome_ledger_sha256,
        "selected_decisions": decisions,
        "method_contract": {
            "shared_generated_validated_grounded_candidate_set": True,
            "xgap_primary_choice": "rank_1_of_bounded_frontier",
            "comparator_primary_choice": comparator_name,
            "primary_return_cardinality_matched": True,
            "any_frontier_member_correct_is_not_primary_correctness": True,
        },
        "population": {
            "frozen_query_count": len(per_query),
            "reporting_query_count": len(reporting_rows),
            "primary_inferential_query_count": len(inferential_rows),
            "jointly_prompt_reachable_query_count": len(jointly_reachable),
            "inferential_unit": "query",
            "repetitions_used_as_independent_units": False,
        },
        "primary": _paired_summary(inferential_rows),
        "all_query_sensitivity": _paired_summary(per_query),
        "jointly_prompt_reachable_stratum": _paired_summary(jointly_reachable),
        "provider_completer_diagnostic": _paired_summary(provider_completers),
        "secondary": {
            "candidate_recall_at_3": _mean(
                float(item["candidate_recall_at_3"]) for item in reporting_rows
            ),
            "mean_xgap_frontier_size": _mean(
                float(item["xgap_frontier_size"]) for item in reporting_rows
            ),
            "generated_hard_constraint_violation_count": sum(
                item["generated_hard_constraint_violation_count"]
                for item in reporting_rows
            ),
            "generated_hard_constraint_violation_query_count": (
                hard_violation_queries
            ),
            "generated_hard_constraint_violation_query_rate": (
                hard_violation_queries / len(reporting_rows)
                if reporting_rows
                else None
            ),
            "coverage_test": coverage_test,
            "holm_adjusted_p_values": _holm(secondary_raw),
            "oracle_clarification_upper_bound": (
                _mean(
                    float(item["candidate_recall_at_3"])
                    for item in reporting_rows
                )
                if decisions["interactive_clarification_role"]
                == "oracle_upper_bound_only"
                else None
            ),
        },
        "failures": {
            "policy": "no_imputation",
            "counts": {
                str(key if key is not None else "none"): failure_counts[key]
                for key in sorted(failure_counts, key=lambda item: str(item))
            },
        },
        "system_cost": provider_totals,
        "per_query": per_query,
        "claim_boundary": {
            "postinference_gold_used_for_evaluation_only": True,
            "backend_calls_made_by_analyzer": 0,
            "llm_calls_made_by_analyzer": 0,
            "ontology_service_calls_made_by_analyzer": 0,
            "independent_evidence_audit_required": True,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    if body["primary"]["primary_test"] != correctness_test:
        raise AssertionError("paired primary reconstruction diverged")
    body["analysis_sha256"] = content_hash(body)
    return body


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise GrailQASemanticAnalysisError(
            "outcome ledger must be a regular non-symbolic-link file"
        )
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GrailQASemanticAnalysisError(
                f"invalid JSONL at line {line_number}"
            ) from exc
        if not isinstance(value, Mapping):
            raise GrailQASemanticAnalysisError(
                f"outcome line {line_number} is not an object"
            )
        rows.append(dict(value))
    return rows


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise GrailQASemanticAnalysisError(
            "outcome ledger must be a regular non-symbolic-link file"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"analysis output already exists: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", required=True)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--author-selection", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-sha256", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        root = Path(arguments.repo_root).resolve()
        readiness = compile_grailqa_semantic_paper_readiness(
            arguments.protocol,
            repo_root=root,
            author_selection=arguments.author_selection,
        ).to_dict()
        if not readiness["gates"]["author_approved"]:
            raise GrailQASemanticAnalysisError(
                "semantic analysis requires an exact author selection"
            )
        decisions = {
            item["decision_id"]: item["selected_value"]
            for item in readiness["author_decisions"]
        }
        pilot = json.loads(
            (root / "datasets/grailqa_pilot_v1/pilot_ids.json").read_text(
                encoding="utf-8"
            )
        )
        outcomes_path = Path(arguments.outcomes)
        analysis = analyze_grailqa_semantic_outcomes(
            _read_jsonl(outcomes_path),
            expected_question_ids=pilot["question_ids"],
            expected_distribution=pilot["distribution"],
            selected_decisions=decisions,
            protocol_sha256=readiness["protocol_sha256"],
            author_selection_sha256=readiness["author_selection_sha256"],
            source_run_sha256=arguments.source_run_sha256,
            outcome_ledger_sha256=_sha256_file(outcomes_path),
        )
        _write_json_exclusive(Path(arguments.output), analysis)
    except (FileExistsError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "analysis_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "status": "success",
                "analysis_sha256": analysis["analysis_sha256"],
                "output": str(Path(arguments.output)),
                "paper_result": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
