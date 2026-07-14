"""Planner-facing records for M10 structured LLM boundaries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from xgap.pattern.ast import PathPatternQuery

JsonMap = dict[str, Any]


def _dict(value: Mapping[str, Any] | None) -> JsonMap:
    return dict(value or {})


@dataclass(frozen=True)
class PlannerRequest:
    """Natural-language planning request passed to a structured provider."""

    question: str
    max_candidates: int = 3
    schema_hints: tuple[str, ...] = ()
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("PlannerRequest question must be non-empty.")
        if self.max_candidates <= 0:
            raise ValueError("PlannerRequest max_candidates must be positive.")
        object.__setattr__(self, "schema_hints", tuple(self.schema_hints))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlannerRequest":
        return cls(
            question=str(data["question"]),
            max_candidates=int(data.get("max_candidates", 3)),
            schema_hints=tuple(str(item) for item in data.get("schema_hints", ())),
            metadata=_dict(data.get("metadata") if isinstance(data.get("metadata"), Mapping) else {}),
        )

    def to_dict(self) -> JsonMap:
        return {
            "question": self.question,
            "max_candidates": self.max_candidates,
            "schema_hints": list(self.schema_hints),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlannerCandidate:
    """One parsed candidate proposed by the LLM boundary."""

    question: str
    pattern_query: PathPatternQuery
    confidence: float | None = None
    candidate_id: str = "candidate-1"
    rationale: str | None = None
    raw: JsonMap = field(default_factory=dict)
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("PlannerCandidate question must be non-empty.")
        if not self.candidate_id.strip():
            raise ValueError("PlannerCandidate candidate_id must be non-empty.")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("PlannerCandidate confidence must be between 0 and 1.")
        object.__setattr__(self, "raw", dict(self.raw))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class PlannerResponse:
    """Parsed provider response containing structured candidates."""

    request: PlannerRequest
    candidates: tuple[PlannerCandidate, ...]
    provider_id: str = "unknown"
    model: str | None = None
    raw: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("PlannerResponse provider_id must be non-empty.")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "raw", dict(self.raw))

    def to_dict(self) -> JsonMap:
        from xgap.llm.parser import path_pattern_query_to_dict

        return {
            "request": self.request.to_dict(),
            "provider_id": self.provider_id,
            "model": self.model,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "question": candidate.question,
                    "confidence": candidate.confidence,
                    "rationale": candidate.rationale,
                    "pattern_query": path_pattern_query_to_dict(candidate.pattern_query),
                    "metadata": dict(candidate.metadata),
                }
                for candidate in self.candidates
            ],
            "raw": dict(self.raw),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(frozen=True)
class CandidateValidationReport:
    """Deterministic validation result for one candidate."""

    candidate_id: str
    ok: bool
    stage: str
    message: str
    formatted_plan: str | None = None
    metadata: JsonMap = field(default_factory=dict)

    def to_dict(self) -> JsonMap:
        return {
            "candidate_id": self.candidate_id,
            "ok": self.ok,
            "stage": self.stage,
            "message": self.message,
            "formatted_plan": self.formatted_plan,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)
