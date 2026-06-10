"""Schemas for future ambiguity-aware planner output."""

from __future__ import annotations

from dataclasses import dataclass

from xgap.pattern.ast import PathPatternQuery


@dataclass(frozen=True)
class PlannerCandidate:
    question: str
    pattern_query: PathPatternQuery
    confidence: float | None = None
