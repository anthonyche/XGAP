"""Finite deterministic M11 physical-search budget policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from xgap.algebra.ops import AlgebraOp
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.llm.schemas import PlannerCandidate


@dataclass(frozen=True)
class FixedBudgetPolicy:
    value: int
    policy_id: str = "fixed-budget"

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("Fixed search budget must be positive.")

    def budget(
        self,
        interpretation: PlannerCandidate,
        logical_plan: AlgebraOp,
        backend_profiles: Sequence[BackendCapabilityProfile],
    ) -> int:
        del interpretation, logical_plan, backend_profiles
        return self.value


@dataclass(frozen=True)
class PolynomialBudgetPolicy:
    base: int = 1
    operator_factor: int = 2
    backend_factor: int = 1
    maximum: int = 1000
    policy_id: str = "polynomial-capped-budget"

    def __post_init__(self) -> None:
        if min(self.base, self.operator_factor, self.backend_factor, self.maximum) <= 0:
            raise ValueError("Polynomial budget parameters must be positive.")

    def budget(
        self,
        interpretation: PlannerCandidate,
        logical_plan: AlgebraOp,
        backend_profiles: Sequence[BackendCapabilityProfile],
    ) -> int:
        del interpretation
        operator_count = _operator_count(logical_plan)
        backend_count = len(backend_profiles)
        value = (
            self.base
            + self.operator_factor * operator_count**2
            + self.backend_factor * backend_count**2
        )
        return min(self.maximum, value)


def _operator_count(plan: AlgebraOp) -> int:
    return 1 + sum(_operator_count(child) for child in plan.children())
