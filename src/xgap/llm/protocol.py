"""Provider protocol for M10 structured planner candidates."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from xgap.llm.schemas import PlannerRequest


class StructuredCandidateProvider(Protocol):
    """A provider that returns controlled candidate JSON.

    M10 providers must not return native Cypher, SPARQL, GQL, or
    arbitrary free-form query plans.
    """

    provider_id: str

    def generate_candidates(self, request: PlannerRequest) -> Mapping[str, Any]:
        """Return controlled JSON with a top-level candidates list."""
