"""Deterministic validation helpers for M10 planner candidates."""

from __future__ import annotations

from xgap.algebra.pretty import format_plan
from xgap.algebra.validation import validate_plan
from xgap.llm.schemas import CandidateValidationReport, PlannerCandidate
from xgap.pattern.lowering import lower_path_pattern
from xgap.pattern.typecheck import type_check_path_pattern


def validate_candidate(candidate: PlannerCandidate) -> CandidateValidationReport:
    """Type-check, lower, and validate one planner candidate.

    This helper is deterministic and does not call a provider, compiler,
    backend, optimizer, or LLM.
    """

    try:
        type_check_path_pattern(candidate.pattern_query)
    except Exception as error:  # noqa: BLE001 - report boundary must preserve stage.
        return CandidateValidationReport(
            candidate_id=candidate.candidate_id,
            ok=False,
            stage="type_check",
            message=str(error),
        )

    try:
        plan = lower_path_pattern(candidate.pattern_query)
    except Exception as error:  # noqa: BLE001
        return CandidateValidationReport(
            candidate_id=candidate.candidate_id,
            ok=False,
            stage="lowering",
            message=str(error),
        )

    try:
        validate_plan(plan)
    except Exception as error:  # noqa: BLE001
        return CandidateValidationReport(
            candidate_id=candidate.candidate_id,
            ok=False,
            stage="validation",
            message=str(error),
        )

    return CandidateValidationReport(
        candidate_id=candidate.candidate_id,
        ok=True,
        stage="validated",
        message="Candidate type checking, lowering, and plan validation passed.",
        formatted_plan=format_plan(plan),
    )
