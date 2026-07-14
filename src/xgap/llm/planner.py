"""Natural-language planner boundary for M10."""

from __future__ import annotations

from xgap.llm.parser import parse_planner_response
from xgap.llm.protocol import StructuredCandidateProvider
from xgap.llm.schemas import PlannerCandidate, PlannerRequest, PlannerResponse


def plan_from_question(
    question: str,
    *,
    provider: StructuredCandidateProvider | None = None,
    max_candidates: int = 3,
    schema_hints: tuple[str, ...] = (),
) -> list[PlannerCandidate]:
    """Return structured planner candidates from an explicit provider.

    M10 intentionally has no default live LLM provider. Callers must
    pass a provider that returns controlled JSON.
    """

    response = plan_response_from_question(
        question,
        provider=provider,
        max_candidates=max_candidates,
        schema_hints=schema_hints,
    )
    return list(response.candidates)


def plan_response_from_question(
    question: str,
    *,
    provider: StructuredCandidateProvider | None = None,
    max_candidates: int = 3,
    schema_hints: tuple[str, ...] = (),
) -> PlannerResponse:
    if provider is None:
        raise NotImplementedError(
            "M10 defines the structured planner boundary but has no default live LLM provider."
        )
    request = PlannerRequest(
        question=question,
        max_candidates=max_candidates,
        schema_hints=schema_hints,
    )
    raw_response = provider.generate_candidates(request)
    return parse_planner_response(raw_response, request)
