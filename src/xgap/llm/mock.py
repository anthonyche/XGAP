"""Mock provider for M10 tests and local demos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from xgap.llm.schemas import PlannerRequest


@dataclass(frozen=True)
class MockStructuredCandidateProvider:
    provider_id: str = "mock"
    payload: Mapping[str, Any] = field(default_factory=dict)

    def generate_candidates(self, request: PlannerRequest) -> Mapping[str, Any]:
        if not self.payload:
            return {
                "provider_id": self.provider_id,
                "model": "mock-structured-candidates",
                "candidates": [],
            }
        payload = dict(self.payload)
        payload.setdefault("provider_id", self.provider_id)
        payload.setdefault("model", "mock-structured-candidates")
        return payload
