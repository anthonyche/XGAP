"""Pluggable boundaries used by the M11 physical planner."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from xgap.algebra.ops import AlgebraOp
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.llm.schemas import PlannerCandidate
from xgap.pattern.ast import PathPatternQuery
from xgap.planning.contracts import (
    ConfidenceContext,
    CostPrediction,
    FeatureVector,
    OntologyAlignmentContext,
    PhysicalCompilationResult,
    PhysicalState,
    QueryPlanningContext,
    SemanticDeviationResult,
)


class OntologyAlignmentProvider(Protocol):
    provider_id: str

    def resolve(
        self,
        query_context: QueryPlanningContext,
        interpretation: PlannerCandidate,
    ) -> OntologyAlignmentContext: ...


class SemanticDeviationScorer(Protocol):
    scorer_id: str

    def score(
        self,
        query_context: QueryPlanningContext,
        interpretation: PlannerCandidate,
        semantic_context: OntologyAlignmentContext,
    ) -> SemanticDeviationResult: ...


class StateFeatureExtractor(Protocol):
    extractor_id: str

    def features(self, state: PhysicalState) -> FeatureVector: ...


class CostEstimator(Protocol):
    estimator_id: str
    model_version: str

    def predict(
        self,
        state: PhysicalState,
        confidence_context: ConfidenceContext,
    ) -> CostPrediction: ...


class BudgetPolicy(Protocol):
    policy_id: str

    def budget(
        self,
        interpretation: PlannerCandidate,
        logical_plan: AlgebraOp,
        backend_profiles: Sequence[BackendCapabilityProfile],
    ) -> int: ...


class PhysicalCompiler(Protocol):
    compiler_id: str

    def compile(
        self,
        logical_plan: AlgebraOp,
        state: PhysicalState,
        backend_profiles: Mapping[str, BackendCapabilityProfile],
        *,
        pattern_query: PathPatternQuery | None = None,
    ) -> PhysicalCompilationResult: ...
