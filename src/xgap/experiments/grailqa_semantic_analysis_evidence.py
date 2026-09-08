"""Independent read-only audit of one GrailQA semantic analysis.

The auditor deliberately does not import or call ``grailqa_semantic_analysis``.
It validates the frozen 150-query ledger and independently reconstructs every
reported query-level statistic.  It performs no model, backend, catalog, or
ontology-service call and never promotes an analysis to a paper result.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
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


AUDIT_SCHEMA_VERSION = "m13e4-grailqa-semantic-analysis-evidence-audit-v1"
ANALYSIS_SCHEMA_VERSION = "m13e4-grailqa-semantic-analysis-v1"
QUERY_OUTCOME_SCHEMA_VERSION = "m13e4-grailqa-semantic-query-outcome-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
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


class GrailQASemanticAnalysisEvidenceError(ValueError):
    """Raised when the evidence package cannot be audited safely."""


def _strict_object(
    value: object, *, name: str, fields: set[str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GrailQASemanticAnalysisEvidenceError(f"{name} must be an object")
    result = dict(value)
    missing = fields - set(result)
    unknown = set(result) - fields
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(sorted(missing)))
        if unknown:
            details.append("unknown=" + ",".join(sorted(unknown)))
        raise GrailQASemanticAnalysisEvidenceError(
            f"{name} fields changed ({'; '.join(details)})"
        )
    return result


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise GrailQASemanticAnalysisEvidenceError(f"{name} must be nonempty text")
    return value


def _integer(value: object, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{name} must be an integer >= {minimum}"
        )
    return value


def _number(value: object, *, name: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GrailQASemanticAnalysisEvidenceError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise GrailQASemanticAnalysisEvidenceError(f"{name} is outside its domain")
    return result


def _boolean(value: object, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise GrailQASemanticAnalysisEvidenceError(f"{name} must be boolean")
    return value


def _regular_file(path: Path, *, name: str) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise GrailQASemanticAnalysisEvidenceError(
            f"{name} must be a regular non-symbolic-link file"
        )
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, *, name: str) -> dict[str, Any]:
    regular = _regular_file(path, name=name)
    try:
        value = json.loads(regular.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GrailQASemanticAnalysisEvidenceError(f"{name} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise GrailQASemanticAnalysisEvidenceError(f"{name} must contain an object")
    return dict(value)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    regular = _regular_file(path, name="outcome ledger")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        regular.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GrailQASemanticAnalysisEvidenceError(
                f"invalid JSONL at line {line_number}"
            ) from exc
        if not isinstance(value, Mapping):
            raise GrailQASemanticAnalysisEvidenceError(
                f"outcome line {line_number} is not an object"
            )
        rows.append(dict(value))
    return rows


def _candidate(value: object, *, question_id: str, position: int) -> dict[str, Any]:
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
    index = _integer(raw["candidate_index"], name="candidate_index", minimum=1)
    if index != position:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} candidate indices are not contiguous"
        )
    confidence = _number(raw["confidence"], name="confidence")
    if confidence > 1.0:
        raise GrailQASemanticAnalysisEvidenceError("confidence is outside [0, 1]")
    valid = _boolean(raw["validation_ok"], name="validation_ok")
    grounded = _boolean(raw["grounded"], name="grounded")
    hard = _boolean(
        raw["hard_constraints_preserved"], name="hard_constraints_preserved"
    )
    admissible = _boolean(raw["semantic_admissible"], name="semantic_admissible")
    if grounded and not valid:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} grounds an invalid candidate"
        )
    if admissible and (not valid or not grounded or not hard):
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} semantic admission bypasses deterministic guards"
        )
    deviation = raw["semantic_deviation"]
    if admissible:
        deviation = _number(deviation, name="semantic_deviation")
    elif deviation is not None:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} inadmissible candidate has semantic deviation"
        )
    return {
        "candidate_id": _text(raw["candidate_id"], name="candidate_id"),
        "candidate_index": index,
        "confidence": confidence,
        "validation_ok": valid,
        "grounded": grounded,
        "hard_constraints_preserved": hard,
        "semantic_admissible": admissible,
        "semantic_deviation": deviation,
        "equivalence_key": _text(raw["equivalence_key"], name="equivalence_key"),
        "reference_supported": _boolean(
            raw["reference_supported"], name="reference_supported"
        ),
    }


def _outcome(value: object) -> dict[str, Any]:
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
        raise GrailQASemanticAnalysisEvidenceError("query outcome schema changed")
    question_id = _text(raw["question_id"], name="question_id")
    split = str(raw["split"])
    if split not in {"train", "dev"}:
        raise GrailQASemanticAnalysisEvidenceError(f"{question_id} split is invalid")
    provider_raw = _strict_object(
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
    provider = {
        "completed": _boolean(provider_raw["completed"], name="provider.completed"),
        "external_calls": _integer(
            provider_raw["external_calls"], name="provider.external_calls"
        ),
        "repair_calls": _integer(
            provider_raw["repair_calls"], name="provider.repair_calls"
        ),
        "input_tokens": _integer(
            provider_raw["input_tokens"], name="provider.input_tokens"
        ),
        "output_tokens": _integer(
            provider_raw["output_tokens"], name="provider.output_tokens"
        ),
        "latency_ms": _number(provider_raw["latency_ms"], name="provider.latency_ms"),
    }
    if provider["repair_calls"] > 1:
        raise GrailQASemanticAnalysisEvidenceError("repair call bound exceeded")
    if provider["external_calls"] not in {0, 1, 2}:
        raise GrailQASemanticAnalysisEvidenceError("external call bound exceeded")
    if provider["repair_calls"] > provider["external_calls"]:
        raise GrailQASemanticAnalysisEvidenceError("repair calls exceed external calls")
    failure = raw["failure_category"]
    if failure not in _FAILURES:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} failure category is invalid"
        )
    values = raw["candidates"]
    if not isinstance(values, list) or len(values) > 3:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} candidate count exceeds the frozen cap"
        )
    candidates = [
        _candidate(item, question_id=question_id, position=index)
        for index, item in enumerate(values, start=1)
    ]
    if len({item["candidate_id"] for item in candidates}) != len(candidates):
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} candidate IDs are duplicated"
        )
    if not provider["completed"] and candidates:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} failed provider emits candidates"
        )
    completed_empty_failures = {
        "generation_miss",
        "entity_grounding_failure",
        "relation_grounding_failure",
    }
    if (
        provider["completed"]
        and not candidates
        and failure not in completed_empty_failures
    ):
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} completed provider emits no candidates"
        )
    if failure == "retrieval_miss":
        if provider["completed"] or provider["external_calls"]:
            raise GrailQASemanticAnalysisEvidenceError(
                f"{question_id} retrieval miss spent a provider call"
            )
    else:
        if provider["external_calls"] != provider["repair_calls"] + 1:
            raise GrailQASemanticAnalysisEvidenceError(
                f"{question_id} provider call accounting diverged"
            )
    if failure in {"provider_failure", "malformed_output"}:
        if provider["completed"]:
            raise GrailQASemanticAnalysisEvidenceError(
                f"{question_id} failed provider is marked completed"
            )
    elif failure != "retrieval_miss" and not provider["completed"]:
        raise GrailQASemanticAnalysisEvidenceError(
            f"{question_id} local failure lacks a provider response"
        )
    return {
        "question_id": question_id,
        "split": split,
        "q_bucket": _integer(raw["q_bucket"], name="q_bucket", minimum=1),
        "jointly_prompt_reachable": _boolean(
            raw["jointly_prompt_reachable"], name="jointly_prompt_reachable"
        ),
        "provider": provider,
        "failure_category": failure,
        "candidates": candidates,
    }


def _grounded(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in candidates
        if item["validation_ok"]
        and item["grounded"]
        and item["hard_constraints_preserved"]
    ]


def _comparator(
    candidates: Sequence[Mapping[str, Any]], comparator: str
) -> dict[str, Any] | None:
    eligible = _grounded(candidates)
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


def _frontier(
    candidates: Sequence[Mapping[str, Any]], epsilon: float
) -> list[dict[str, Any]]:
    eligible = [
        dict(item)
        for item in _grounded(candidates)
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
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in eligible:
        equivalence_key = str(item["equivalence_key"])
        if equivalence_key in seen:
            continue
        seen.add(equivalence_key)
        result.append(item)
    return result[:3]


def _mcnemar(
    rows: Sequence[Mapping[str, Any]], left: str, right: str
) -> dict[str, Any]:
    left_only = sum(bool(row[left]) and not bool(row[right]) for row in rows)
    right_only = sum(bool(row[right]) and not bool(row[left]) for row in rows)
    discordant = left_only + right_only
    if not discordant:
        p_value = 1.0
    else:
        smaller = min(left_only, right_only)
        tail = sum(math.comb(discordant, index) for index in range(smaller + 1))
        p_value = min(1.0, 2.0 * tail / (2**discordant))
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
        raise GrailQASemanticAnalysisEvidenceError("cannot summarize no values")
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bootstrap(
    rows: Sequence[Mapping[str, Any]], left: str, right: str
) -> dict[str, Any]:
    seed_text = "m13e4-grailqa-semantic-ci-v1"
    if not rows:
        return {
            "method": "query_paired_bootstrap_percentile",
            "resamples": 10000,
            "seed": seed_text,
            "confidence_interval": None,
        }
    seed = int(hashlib.sha256(seed_text.encode("ascii")).hexdigest()[:16], 16)
    generator = random.Random(seed)
    values = [float(bool(row[left])) - float(bool(row[right])) for row in rows]
    estimates = [
        sum(generator.choice(values) for _ in values) / len(values)
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


def _method(rows: Sequence[Mapping[str, Any]], prefix: str) -> dict[str, Any]:
    count = len(rows)
    correct = sum(bool(row[f"{prefix}_correct"]) for row in rows)
    covered = sum(bool(row[f"{prefix}_covered"]) for row in rows)
    return {
        "query_count": count,
        "correct_count": correct,
        "accuracy": correct / count if count else None,
        "covered_count": covered,
        "coverage": covered / count if count else None,
    }


def _paired(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    xgap = _method(rows, "xgap")
    comparator = _method(rows, "comparator")
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
        "confidence_interval": _bootstrap(
            rows, "xgap_correct", "comparator_correct"
        ),
    }


def _mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return sum(collected) / len(collected) if collected else None


def _holm(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    result: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - index) * value))
        result[name] = running
    return {name: result[name] for name in sorted(result)}


def _reconstruct_analysis(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    expected_ids: Sequence[str],
    expected_distribution: Mapping[str, Any],
    decisions: Mapping[str, str],
    protocol_sha256: str,
    author_selection_sha256: str,
    source_run_sha256: str,
    outcome_ledger_sha256: str,
) -> dict[str, Any]:
    if len(expected_ids) != 150 or len(set(expected_ids)) != 150:
        raise GrailQASemanticAnalysisEvidenceError(
            "expected population is not exactly 150 unique queries"
        )
    normalized = [_outcome(row) for row in outcomes]
    by_id = {row["question_id"]: row for row in normalized}
    if len(by_id) != len(normalized):
        raise GrailQASemanticAnalysisEvidenceError("outcome IDs are duplicated")
    if set(by_id) != set(expected_ids):
        raise GrailQASemanticAnalysisEvidenceError(
            "outcome ledger does not match the frozen query population"
        )
    observed_split = Counter(row["split"] for row in normalized)
    observed_q = Counter(str(row["q_bucket"]) for row in normalized)
    if dict(observed_split) != dict(expected_distribution["split"]):
        raise GrailQASemanticAnalysisEvidenceError("split distribution changed")
    if dict(observed_q) != dict(expected_distribution["Q"]):
        raise GrailQASemanticAnalysisEvidenceError("Q distribution changed")

    epsilon = float(decisions["primary_epsilon"])
    comparator_name = decisions["primary_comparator"]
    per_query: list[dict[str, Any]] = []
    for question_id in expected_ids:
        outcome = by_id[question_id]
        candidates = outcome["candidates"]
        frontier = _frontier(candidates, epsilon)
        xgap = frontier[0] if frontier else None
        comparator = _comparator(candidates, comparator_name)
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
                "provider": outcome["provider"],
            }
        )

    reporting_rows = per_query
    if decisions["primary_reporting_population"] == "jointly_reachable_only":
        reporting_rows = [row for row in per_query if row["jointly_prompt_reachable"]]
    inferential_rows = reporting_rows
    if (
        decisions["inference_failure_estimand"]
        == "available_case_primary_with_all_query_sensitivity"
    ):
        inferential_rows = [
            row
            for row in reporting_rows
            if row["xgap_covered"] and row["comparator_covered"]
        ]
    if not inferential_rows:
        raise GrailQASemanticAnalysisEvidenceError("primary population is empty")

    jointly_reachable = [row for row in per_query if row["jointly_prompt_reachable"]]
    provider_completers = [row for row in per_query if row["provider"]["completed"]]
    coverage_test = _mcnemar(
        reporting_rows, "xgap_covered", "comparator_covered"
    )
    failure_counts = Counter(row["failure_category"] for row in per_query)
    provider_totals = {
        field: sum(row["provider"][field] for row in per_query)
        for field in (
            "external_calls",
            "repair_calls",
            "input_tokens",
            "output_tokens",
            "latency_ms",
        )
    }
    provider_totals["completed_queries"] = sum(
        row["provider"]["completed"] for row in per_query
    )
    hard_violation_queries = sum(
        row["generated_hard_constraint_violation_count"] > 0
        for row in reporting_rows
    )
    body: dict[str, Any] = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "protocol_sha256": protocol_sha256,
        "author_selection_sha256": author_selection_sha256,
        "source_run_sha256": source_run_sha256,
        "outcome_ledger_sha256": outcome_ledger_sha256,
        "selected_decisions": dict(decisions),
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
        "primary": _paired(inferential_rows),
        "all_query_sensitivity": _paired(per_query),
        "jointly_prompt_reachable_stratum": _paired(jointly_reachable),
        "provider_completer_diagnostic": _paired(provider_completers),
        "secondary": {
            "candidate_recall_at_3": _mean(
                float(row["candidate_recall_at_3"]) for row in reporting_rows
            ),
            "mean_xgap_frontier_size": _mean(
                float(row["xgap_frontier_size"]) for row in reporting_rows
            ),
            "generated_hard_constraint_violation_count": sum(
                row["generated_hard_constraint_violation_count"]
                for row in reporting_rows
            ),
            "generated_hard_constraint_violation_query_count": hard_violation_queries,
            "generated_hard_constraint_violation_query_rate": (
                hard_violation_queries / len(reporting_rows)
                if reporting_rows
                else None
            ),
            "coverage_test": coverage_test,
            "holm_adjusted_p_values": _holm(
                {"coverage": float(coverage_test["p_value"])}
            ),
            "oracle_clarification_upper_bound": (
                _mean(
                    float(row["candidate_recall_at_3"])
                    for row in reporting_rows
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
    body["analysis_sha256"] = content_hash(body)
    return body


def _snapshot(paths: Sequence[Path]) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for path in paths:
        regular = _regular_file(path, name=str(path))
        result[str(regular)] = (regular.stat().st_size, _file_sha256(regular))
    return result


def audit_grailqa_semantic_analysis(
    *,
    outcomes_path: str | Path,
    analysis_path: str | Path,
    protocol_path: str | Path,
    author_selection_path: str | Path,
    repo_root: str | Path,
    source_run_sha256: str,
) -> dict[str, Any]:
    """Reconstruct an analysis and return a compact non-mutating audit."""

    if _SHA256.fullmatch(source_run_sha256) is None:
        raise GrailQASemanticAnalysisEvidenceError(
            "source_run_sha256 must be a lowercase SHA-256"
        )
    root = Path(repo_root).resolve()
    outcomes = Path(outcomes_path)
    analysis_file = Path(analysis_path)
    protocol = Path(protocol_path)
    selection = Path(author_selection_path)
    pilot = root / "datasets/grailqa_pilot_v1/pilot_ids.json"
    inputs = (outcomes, analysis_file, protocol, selection, pilot)
    before = _snapshot(inputs)
    checks: list[dict[str, Any]] = []

    def check(check_id: str, expected: Any, observed: Any) -> None:
        passed = expected == observed
        detail: dict[str, Any] | None = None
        if not passed:
            detail = {"expected": expected, "observed": observed}
        checks.append({"check_id": check_id, "passed": passed, "detail": detail})

    saved = _load_json(analysis_file, name="semantic analysis")
    check("analysis.schema", ANALYSIS_SCHEMA_VERSION, saved.get("schema_version"))
    saved_without_hash = {
        key: value for key, value in saved.items() if key != "analysis_sha256"
    }
    check(
        "analysis.self_hash",
        content_hash(saved_without_hash),
        saved.get("analysis_sha256"),
    )
    check("analysis.paper_result", False, saved.get("paper_result"))
    check("analysis.automatic_retries", 0, saved.get("automatic_retries"))
    claim = saved.get("claim_boundary")
    check(
        "analysis.zero_external_calls",
        {
            "backend_calls_made_by_analyzer": 0,
            "llm_calls_made_by_analyzer": 0,
            "ontology_service_calls_made_by_analyzer": 0,
        },
        (
            {
                key: claim.get(key)
                for key in (
                    "backend_calls_made_by_analyzer",
                    "llm_calls_made_by_analyzer",
                    "ontology_service_calls_made_by_analyzer",
                )
            }
            if isinstance(claim, Mapping)
            else None
        ),
    )

    reconstruction: dict[str, Any] | None = None
    reconstruction_error: str | None = None
    readiness: dict[str, Any] | None = None
    try:
        readiness = compile_grailqa_semantic_paper_readiness(
            protocol,
            repo_root=root,
            author_selection=selection,
        ).to_dict()
        if readiness["gates"]["author_approved"] is not True:
            raise GrailQASemanticAnalysisEvidenceError(
                "author selection is not approved"
            )
        pilot_value = _load_json(pilot, name="GrailQA pilot selection")
        decisions = {
            item["decision_id"]: item["selected_value"]
            for item in readiness["author_decisions"]
        }
        ledger_hash = _file_sha256(_regular_file(outcomes, name="outcome ledger"))
        reconstruction = _reconstruct_analysis(
            _load_jsonl(outcomes),
            expected_ids=[str(item) for item in pilot_value["question_ids"]],
            expected_distribution=dict(pilot_value["distribution"]),
            decisions=decisions,
            protocol_sha256=str(readiness["protocol_sha256"]),
            author_selection_sha256=str(readiness["author_selection_sha256"]),
            source_run_sha256=source_run_sha256,
            outcome_ledger_sha256=ledger_hash,
        )
    except Exception as exc:  # noqa: BLE001 - the audit records all defects.
        reconstruction_error = f"{type(exc).__name__}: {exc}"

    check("reconstruction.error", None, reconstruction_error)
    if reconstruction is not None:
        check(
            "analysis.protocol_sha256",
            reconstruction["protocol_sha256"],
            saved.get("protocol_sha256"),
        )
        check(
            "analysis.author_selection_sha256",
            reconstruction["author_selection_sha256"],
            saved.get("author_selection_sha256"),
        )
        check(
            "analysis.source_run_sha256",
            source_run_sha256,
            saved.get("source_run_sha256"),
        )
        check(
            "analysis.outcome_ledger_sha256",
            reconstruction["outcome_ledger_sha256"],
            saved.get("outcome_ledger_sha256"),
        )
        exact = reconstruction == saved
        checks.append(
            {
                "check_id": "analysis.exact_reconstruction",
                "passed": exact,
                "detail": (
                    None
                    if exact
                    else {
                        "expected_analysis_sha256": reconstruction[
                            "analysis_sha256"
                        ],
                        "observed_analysis_sha256": saved.get("analysis_sha256"),
                    }
                ),
            }
        )
    else:
        checks.append(
            {
                "check_id": "analysis.exact_reconstruction",
                "passed": False,
                "detail": {"expected": "exact reconstruction", "observed": None},
            }
        )

    after = _snapshot(inputs)
    check("inputs.not_mutated", before, after)
    failed = [row["check_id"] for row in checks if not row["passed"]]
    result: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "success": not failed,
        "check_count": len(checks),
        "failed_check_ids": failed,
        "input_artifacts_mutated": before != after,
        "analysis_exact_match": reconstruction == saved,
        "expected_source_run_sha256": source_run_sha256,
        "input_sha256": {
            "outcome_ledger": before[str(outcomes.resolve())][1],
            "analysis": before[str(analysis_file.resolve())][1],
            "protocol": before[str(protocol.resolve())][1],
            "author_selection": before[str(selection.resolve())][1],
            "pilot_selection": before[str(pilot.resolve())][1],
        },
        "external_call_counts": {
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "independent_analysis_reconstruction": True,
            "contains_new_measurements": False,
            "full_150_run_authorized": False,
            "paper_result": False,
        },
        "checks": checks,
        "paper_result": False,
    }
    result["audit_sha256"] = content_hash(result)
    return result


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"audit output already exists: {path}")
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
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument("--author-selection", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-run-sha256", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        audit = audit_grailqa_semantic_analysis(
            outcomes_path=arguments.outcomes,
            analysis_path=arguments.analysis,
            protocol_path=arguments.protocol,
            author_selection_path=arguments.author_selection,
            repo_root=arguments.repo_root,
            source_run_sha256=arguments.source_run_sha256,
        )
        _write_json_exclusive(Path(arguments.output), audit)
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "audit_error", "error": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "status": "success" if audit["success"] else "failed",
                "audit_sha256": audit["audit_sha256"],
                "output": str(Path(arguments.output)),
                "paper_result": False,
            },
            sort_keys=True,
        )
    )
    return 0 if audit["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
