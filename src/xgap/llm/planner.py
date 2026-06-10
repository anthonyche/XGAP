"""Natural-language planner interface."""

from __future__ import annotations

from xgap.llm.schemas import PlannerCandidate


def plan_from_question(question: str) -> list[PlannerCandidate]:
    raise NotImplementedError("LLM planning is planned for M7 and is not implemented yet.")
