"""M11 main planner over fixed interpretation-specific logical plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from xgap.algebra.pretty import format_plan
from xgap.algebra.validation import validate_plan
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.llm.schemas import PlannerCandidate
from xgap.pattern.lowering import lower_path_pattern
from xgap.planning.contracts import (
    JsonMap,
    ObjectiveScore,
    OntologyAlignmentContext,
    PhysicalPlan,
    PlanningConfig,
    QueryPlanningContext,
    SemanticDeviationResult,
    SemanticDeviationStatus,
    objective_score,
)
from xgap.planning.cost import (
    across_task_confidence_context,
    conservative_state_space_bound,
)
from xgap.planning.protocols import (
    BudgetPolicy,
    CostEstimator,
    OntologyAlignmentProvider,
    PhysicalCompiler,
    SemanticDeviationScorer,
)
from xgap.planning.search import (
    BnBSearchResult,
    ExchangeCatalog,
    SearchRunContext,
    bnb_search,
)
from xgap.planning.topology import index_logical_plan


@dataclass(frozen=True)
class CandidatePlanningRecord:
    candidate_id: str
    status: str
    message: str
    alignment: OntologyAlignmentContext
    semantic_deviation: SemanticDeviationResult | None = None
    logical_plan_id: str | None = None
    formatted_logical_plan: str | None = None
    search: BnBSearchResult | None = None
    objective: ObjectiveScore | None = None

    def to_dict(self) -> JsonMap:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "message": self.message,
            "alignment": self.alignment.to_dict(),
            "semantic_deviation": (
                self.semantic_deviation.to_dict() if self.semantic_deviation else None
            ),
            "logical_plan_id": self.logical_plan_id,
            "formatted_logical_plan": self.formatted_logical_plan,
            "search": self.search.to_dict() if self.search else None,
            "objective": self.objective.to_dict() if self.objective else None,
        }


@dataclass(frozen=True)
class SelectedPhysicalPlan:
    candidate_id: str
    physical_plan: PhysicalPlan
    semantic_deviation: SemanticDeviationResult
    objective: ObjectiveScore

    def to_dict(self) -> JsonMap:
        return {
            "candidate_id": self.candidate_id,
            "physical_plan": self.physical_plan.to_dict(),
            "semantic_deviation": self.semantic_deviation.to_dict(),
            "objective": self.objective.to_dict(),
        }


@dataclass(frozen=True)
class MainPlannerResult:
    run_id: str
    query_id: str
    task_id: str
    status: str
    reason: str
    candidate_records: tuple[CandidatePlanningRecord, ...]
    selected_plans: tuple[SelectedPhysicalPlan, ...]

    @property
    def traces(self):
        return tuple(
            event
            for record in self.candidate_records
            if record.search is not None
            for event in record.search.trace
        )

    def to_dict(self) -> JsonMap:
        return {
            "run_id": self.run_id,
            "query_id": self.query_id,
            "task_id": self.task_id,
            "status": self.status,
            "reason": self.reason,
            "candidate_records": [item.to_dict() for item in self.candidate_records],
            "selected_plans": [item.to_dict() for item in self.selected_plans],
        }


@dataclass(frozen=True)
class XGAPPhysicalPlanner:
    alignment_provider: OntologyAlignmentProvider
    semantic_scorer: SemanticDeviationScorer
    backend_profiles: tuple[BackendCapabilityProfile, ...]
    exchange_catalog: ExchangeCatalog
    budget_policy: BudgetPolicy
    cost_estimator: CostEstimator
    physical_compiler: PhysicalCompiler

    def __post_init__(self) -> None:
        profiles = tuple(sorted(self.backend_profiles, key=lambda item: item.backend_id))
        if not profiles:
            raise ValueError("XGAPPhysicalPlanner requires backend profiles.")
        if len({item.backend_id for item in profiles}) != len(profiles):
            raise ValueError("Backend profile identifiers must be unique.")
        object.__setattr__(self, "backend_profiles", profiles)

    def plan(
        self,
        *,
        query_context: QueryPlanningContext,
        candidates: Sequence[PlannerCandidate],
        config: PlanningConfig,
    ) -> MainPlannerResult:
        ordered = tuple(sorted(candidates, key=lambda item: item.candidate_id))
        if len({item.candidate_id for item in ordered}) != len(ordered):
            raise ValueError("Planner candidate identifiers must be unique.")
        records: list[CandidatePlanningRecord] = []
        eligible: list[SelectedPhysicalPlan] = []
        semantically_admissible_count = 0
        complete_plan_count = 0
        under_threshold_count = 0
        interpretation_count = max(1, len(ordered))

        for candidate in ordered:
            alignment = self.alignment_provider.resolve(query_context, candidate)
            if not alignment.mapping_sufficiency.sufficient:
                records.append(
                    CandidatePlanningRecord(
                        candidate_id=candidate.candidate_id,
                        status=f"mapping_{alignment.mapping_sufficiency.status.value}",
                        message=(
                            alignment.mapping_sufficiency.reason
                            or "Source-to-ontology mapping evidence is not sufficient."
                        ),
                        alignment=alignment,
                    )
                )
                continue

            semantic = self.semantic_scorer.score(query_context, candidate, alignment)
            if semantic.status is not SemanticDeviationStatus.AVAILABLE:
                records.append(
                    CandidatePlanningRecord(
                        candidate_id=candidate.candidate_id,
                        status=f"semantic_deviation_{semantic.status.value}",
                        message=semantic.reason,
                        alignment=alignment,
                        semantic_deviation=semantic,
                    )
                )
                continue
            assert semantic.value is not None
            if semantic.value > config.semantic_threshold:
                records.append(
                    CandidatePlanningRecord(
                        candidate_id=candidate.candidate_id,
                        status="semantic_threshold_exceeded",
                        message="Interpretation semantic deviation exceeds epsilon.",
                        alignment=alignment,
                        semantic_deviation=semantic,
                    )
                )
                continue
            semantically_admissible_count += 1

            logical_plan = lower_path_pattern(candidate.pattern_query)
            validate_plan(logical_plan)
            indexed = index_logical_plan(logical_plan)
            budget = self.budget_policy.budget(
                candidate,
                logical_plan,
                self.backend_profiles,
            )
            bound = conservative_state_space_bound(
                indexed.root_state(candidate.candidate_id),
                self.backend_profiles,
                self.exchange_catalog,
            )
            confidence = across_task_confidence_context(
                global_delta=config.global_delta,
                task_index=config.task_index,
                interpretation_count=interpretation_count,
                state_space_bound=bound.value,
            )
            search = bnb_search(
                interpretation_id=candidate.candidate_id,
                logical_plan=logical_plan,
                indexed_plan=indexed,
                backend_profiles=self.backend_profiles,
                exchange_catalog=self.exchange_catalog,
                budget=budget,
                cost_estimator=self.cost_estimator,
                confidence_context=confidence,
                physical_compiler=self.physical_compiler,
                run_context=SearchRunContext(
                    config.run_id,
                    query_context.query_id,
                    query_context.task_id,
                    alignment.alignment_id,
                ),
                pattern_query=candidate.pattern_query,
            )
            if search.incumbent is None:
                records.append(
                    CandidatePlanningRecord(
                        candidate_id=candidate.candidate_id,
                        status="no_feasible_complete_plan",
                        message="Bounded physical search found no feasible complete plan.",
                        alignment=alignment,
                        semantic_deviation=semantic,
                        logical_plan_id=indexed.logical_plan_id,
                        formatted_logical_plan=format_plan(logical_plan),
                        search=search,
                    )
                )
                continue
            complete_plan_count += 1
            objective = objective_score(
                interpretation_id=candidate.candidate_id,
                semantic_deviation=semantic.value,
                conservative_cost=search.incumbent.cost.upper,
                config=config,
            )
            if search.incumbent.cost.upper < config.execution_threshold:
                under_threshold_count += 1
            if not objective.nash_eligible:
                records.append(
                    CandidatePlanningRecord(
                        candidate_id=candidate.candidate_id,
                        status=objective.reason,
                        message="Complete plan is outside the strictly positive Nash-output domain.",
                        alignment=alignment,
                        semantic_deviation=semantic,
                        logical_plan_id=indexed.logical_plan_id,
                        formatted_logical_plan=format_plan(logical_plan),
                        search=search,
                        objective=objective,
                    )
                )
                continue
            selected = SelectedPhysicalPlan(
                candidate_id=candidate.candidate_id,
                physical_plan=search.incumbent,
                semantic_deviation=semantic,
                objective=objective,
            )
            eligible.append(selected)
            records.append(
                CandidatePlanningRecord(
                    candidate_id=candidate.candidate_id,
                    status="eligible",
                    message="Interpretation has one eligible discovered physical representative.",
                    alignment=alignment,
                    semantic_deviation=semantic,
                    logical_plan_id=indexed.logical_plan_id,
                    formatted_logical_plan=format_plan(logical_plan),
                    search=search,
                    objective=objective,
                )
            )

        ranked = tuple(
            sorted(
                eligible,
                key=lambda item: (
                    -float(item.objective.nash_score),
                    item.candidate_id,
                    item.physical_plan.plan_id,
                ),
            )[: config.top_k]
        )
        status, reason = _overall_status(
            ranked_count=len(ranked),
            candidate_count=len(ordered),
            semantically_admissible_count=semantically_admissible_count,
            complete_plan_count=complete_plan_count,
            under_threshold_count=under_threshold_count,
        )
        return MainPlannerResult(
            run_id=config.run_id,
            query_id=query_context.query_id,
            task_id=query_context.task_id,
            status=status,
            reason=reason,
            candidate_records=tuple(records),
            selected_plans=ranked,
        )


def _overall_status(
    *,
    ranked_count: int,
    candidate_count: int,
    semantically_admissible_count: int,
    complete_plan_count: int,
    under_threshold_count: int,
) -> tuple[str, str]:
    if ranked_count:
        return "ok", f"Returned {ranked_count} Nash-ranked physical plan(s)."
    if complete_plan_count and not under_threshold_count:
        return "no_plan_under_threshold", "No complete plan satisfies C_bar < T_max."
    if semantically_admissible_count and not complete_plan_count:
        return "no_feasible_physical_plan", "No bounded search found a complete physical plan."
    if semantically_admissible_count:
        return "no_positive_utility_plan", "No plan has strictly positive Nash utilities."
    if candidate_count:
        return "no_semantically_admissible_interpretation", "No candidate passed mapping and semantic admissibility."
    return "no_candidates", "The structured candidate set is empty."
