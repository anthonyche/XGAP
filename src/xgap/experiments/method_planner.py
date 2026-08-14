"""M12-D experiment policies over the unchanged logical and M11 boundaries."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from xgap.algebra.pretty import format_plan
from xgap.algebra.validation import validate_plan
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.compilers.features import plan_from_compiler_input
from xgap.experiments.methods import (
    MethodPolicy,
    RankingStrategy,
    SearchStrategy,
    seeded_choice,
)
from xgap.llm.schemas import PlannerCandidate
from xgap.pattern.lowering import lower_path_pattern
from xgap.planning.contracts import (
    ConfidenceContext,
    CostPrediction,
    ObjectiveScore,
    PhysicalPlan,
    PhysicalRealization,
    PlanningConfig,
    QueryPlanningContext,
    SemanticDeviationStatus,
    objective_score,
)
from xgap.planning.cost import (
    across_task_confidence_context,
    conservative_state_space_bound,
)
from xgap.planning.oracle import ExhaustiveOracleResult, exhaustive_physical_oracle
from xgap.planning.planner import (
    CandidatePlanningRecord,
    MainPlannerResult,
    SelectedPhysicalPlan,
    _overall_status,
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
    enumerate_successors,
)
from xgap.planning.topology import index_logical_plan


@dataclass(frozen=True)
class MethodPlanningResult:
    planner_result: MainPlannerResult
    method_policy: MethodPolicy
    sampled_decisions: tuple[Mapping[str, object], ...] = ()
    oracle_status: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "method_policy": self.method_policy.to_dict(),
            "planner_result": self.planner_result.to_dict(),
            "sampled_decisions": [dict(item) for item in self.sampled_decisions],
            "oracle_status": self.oracle_status,
        }


@dataclass(frozen=True)
class ControlledOracleExecution:
    status: str
    state_space_bound: int
    result: ExhaustiveOracleResult | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "state_space_bound": self.state_space_bound,
            "result": self.result.to_dict() if self.result is not None else None,
            "reason": self.reason,
        }


def run_controlled_exhaustive_oracle(
    *,
    policy: MethodPolicy,
    interpretation_id: str,
    logical_plan: object,
    indexed_plan: object,
    backend_profiles: Sequence[BackendCapabilityProfile],
    exchange_catalog: ExchangeCatalog,
    physical_compiler: PhysicalCompiler,
    true_cost: object,
    pattern_query: object | None = None,
) -> ControlledOracleExecution:
    if policy.search_strategy is not SearchStrategy.EXHAUSTIVE:
        raise ValueError("Controlled oracle execution requires exhaustive_oracle policy.")
    root = indexed_plan.root_state(interpretation_id)
    bound = conservative_state_space_bound(root, backend_profiles, exchange_catalog)
    assert policy.oracle_state_limit is not None
    if bound.value > policy.oracle_state_limit:
        return ControlledOracleExecution(
            status="oracle_not_available",
            state_space_bound=bound.value,
            reason=(
                f"Represented state bound {bound.value} exceeds controlled limit "
                f"{policy.oracle_state_limit}."
            ),
        )
    result = exhaustive_physical_oracle(
        interpretation_id=interpretation_id,
        logical_plan=logical_plan,
        indexed_plan=indexed_plan,
        backend_profiles=backend_profiles,
        exchange_catalog=exchange_catalog,
        physical_compiler=physical_compiler,
        true_cost=true_cost,
        pattern_query=pattern_query,
    )
    return ControlledOracleExecution("ok", bound.value, result)


def plan_candidates_with_method(
    *,
    policy: MethodPolicy,
    query_context: QueryPlanningContext,
    candidates: Sequence[PlannerCandidate],
    config: PlanningConfig,
    alignment_provider: OntologyAlignmentProvider,
    semantic_scorer: SemanticDeviationScorer,
    backend_profiles: Sequence[BackendCapabilityProfile],
    exchange_catalog: ExchangeCatalog,
    budget_policy: BudgetPolicy,
    cost_estimator: CostEstimator,
    physical_compiler: PhysicalCompiler,
) -> MethodPlanningResult:
    if policy.search_strategy is SearchStrategy.DIRECT:
        raise ValueError("direct_text2graphquery does not accept PathPatternQuery candidates.")
    if policy.search_strategy is SearchStrategy.EXHAUSTIVE:
        return _oracle_not_available(policy, query_context, config)

    profiles = tuple(sorted(backend_profiles, key=lambda item: item.backend_id))
    if policy.backend_id is not None:
        profiles = tuple(item for item in profiles if item.backend_id == policy.backend_id)
        if not profiles:
            raise ValueError(f"Configured backend '{policy.backend_id}' is unavailable.")

    ordered = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    if len({item.candidate_id for item in ordered}) != len(ordered):
        raise ValueError("Planner candidate identifiers must be unique.")
    records: list[CandidatePlanningRecord] = []
    eligible: list[SelectedPhysicalPlan] = []
    decisions: list[Mapping[str, object]] = []
    admissible_count = complete_count = under_threshold_count = 0

    for candidate in ordered:
        alignment = alignment_provider.resolve(query_context, candidate)
        if not alignment.mapping_sufficiency.sufficient:
            records.append(
                CandidatePlanningRecord(
                    candidate_id=candidate.candidate_id,
                    status=f"mapping_{alignment.mapping_sufficiency.status.value}",
                    message=alignment.mapping_sufficiency.reason,
                    alignment=alignment,
                )
            )
            continue
        semantic = semantic_scorer.score(query_context, candidate, alignment)
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
        if policy.apply_semantic_bound and semantic.value > config.semantic_threshold:
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
        admissible_count += 1
        logical_plan = lower_path_pattern(candidate.pattern_query)
        validate_plan(logical_plan)
        search_plan = _compiler_ready_search_plan(candidate, logical_plan, profiles)
        indexed = index_logical_plan(search_plan)
        budget = budget_policy.budget(candidate, search_plan, profiles)
        if policy.search_strategy is SearchStrategy.RANDOM_FEASIBLE:
            search, sampled = _random_feasible_search(
                candidate=candidate,
                logical_plan=search_plan,
                indexed_plan=indexed,
                profiles=profiles,
                exchange_catalog=exchange_catalog,
                physical_compiler=physical_compiler,
                budget=budget,
                policy=policy,
            )
            decisions.extend(sampled)
        else:
            bound = conservative_state_space_bound(
                indexed.root_state(candidate.candidate_id), profiles, exchange_catalog
            )
            confidence = across_task_confidence_context(
                global_delta=config.global_delta,
                task_index=config.task_index,
                interpretation_count=max(1, len(ordered)),
                state_space_bound=bound.value,
            )
            search = bnb_search(
                interpretation_id=candidate.candidate_id,
                logical_plan=search_plan,
                indexed_plan=indexed,
                backend_profiles=profiles,
                exchange_catalog=exchange_catalog,
                budget=budget,
                cost_estimator=cost_estimator,
                confidence_context=confidence,
                physical_compiler=physical_compiler,
                run_context=SearchRunContext(
                    config.run_id,
                    query_context.query_id,
                    query_context.task_id,
                    alignment.alignment_id,
                ),
                pattern_query=candidate.pattern_query,
                confidence_pruning=policy.confidence_pruning,
            )
        if search.incumbent is None:
            records.append(
                CandidatePlanningRecord(
                    candidate_id=candidate.candidate_id,
                    status="no_feasible_complete_plan",
                    message="Method search found no feasible complete plan.",
                    alignment=alignment,
                    semantic_deviation=semantic,
                    logical_plan_id=indexed.logical_plan_id,
                    formatted_logical_plan=format_plan(logical_plan),
                    search=search,
                )
            )
            continue
        complete_count += 1
        if policy.search_strategy is SearchStrategy.RANDOM_FEASIBLE:
            objective = _alternative_objective(
                candidate.candidate_id,
                semantic.value,
                search.incumbent.cost.upper,
                reason="eligible_pending_measured_t_max",
            )
            under_threshold_count += 1
        elif policy.ranking_strategy is RankingStrategy.NASH:
            threshold = config.semantic_threshold
            if not policy.apply_semantic_bound:
                threshold = max(threshold, 1.0 + 1e-12)
            objective = objective_score(
                interpretation_id=candidate.candidate_id,
                semantic_deviation=semantic.value,
                conservative_cost=search.incumbent.cost.upper,
                config=PlanningConfig(
                    run_id=config.run_id,
                    semantic_threshold=threshold,
                    execution_threshold=config.execution_threshold,
                    top_k=config.top_k,
                    global_delta=config.global_delta,
                    task_index=config.task_index,
                    deterministic_seed=config.deterministic_seed,
                    metadata=config.metadata,
                ),
            )
            under_threshold_count += int(
                search.incumbent.cost.upper < config.execution_threshold
            )
        else:
            eligible_by_cost = search.incumbent.cost.upper < config.execution_threshold
            objective = _alternative_objective(
                candidate.candidate_id,
                semantic.value,
                search.incumbent.cost.upper,
                reason="eligible_alternative_ranking" if eligible_by_cost else "no_plan_under_execution_threshold",
                eligible=eligible_by_cost,
            )
            under_threshold_count += int(eligible_by_cost)
        if not objective.nash_eligible:
            records.append(
                CandidatePlanningRecord(
                    candidate_id=candidate.candidate_id,
                    status=objective.reason,
                    message="Complete plan is outside the configured output domain.",
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
                message="Interpretation has one method-selected physical representative.",
                alignment=alignment,
                semantic_deviation=semantic,
                logical_plan_id=indexed.logical_plan_id,
                formatted_logical_plan=format_plan(logical_plan),
                search=search,
                objective=objective,
            )
        )

    ranked = tuple(sorted(eligible, key=lambda item: _rank_key(policy, item))[: config.top_k])
    status, reason = _overall_status(
        ranked_count=len(ranked),
        candidate_count=len(ordered),
        semantically_admissible_count=admissible_count,
        complete_plan_count=complete_count,
        under_threshold_count=under_threshold_count,
    )
    result = MainPlannerResult(
        run_id=config.run_id,
        query_id=query_context.query_id,
        task_id=query_context.task_id,
        status=status,
        reason=reason,
        candidate_records=tuple(records),
        selected_plans=ranked,
    )
    return MethodPlanningResult(result, policy, tuple(decisions))


def _rank_key(
    policy: MethodPolicy, item: SelectedPhysicalPlan
) -> tuple[float, float, str, str]:
    if policy.ranking_strategy is RankingStrategy.NASH:
        return (
            -float(item.objective.nash_score),
            0.0,
            item.candidate_id,
            item.physical_plan.plan_id,
        )
    if policy.ranking_strategy is RankingStrategy.SEMANTIC_THEN_COST:
        return (
            item.semantic_deviation.value or 0.0,
            item.physical_plan.cost.upper,
            item.candidate_id,
            item.physical_plan.plan_id,
        )
    return (
        item.physical_plan.cost.upper,
        item.semantic_deviation.value or 0.0,
        item.candidate_id,
        item.physical_plan.plan_id,
    )


def _compiler_ready_search_plan(
    candidate: PlannerCandidate,
    logical_plan: object,
    profiles: Sequence[BackendCapabilityProfile],
) -> object:
    """Use M9's audited ALL-selector normalization for native placement.

    The original deterministic lowering is still formatted and persisted. The
    returned plan is only the existing M9 row-oriented compiler input used for
    physical capability placement; no new compiler fragment is introduced.
    """

    native_profiles = tuple(
        item for item in profiles if item.language.lower() in {"cypher", "sparql"}
    )
    if not native_profiles:
        return logical_plan
    profile = native_profiles[0]
    compiler_plan, _, _ = plan_from_compiler_input(
        candidate.pattern_query,
        backend_id=profile.backend_id,
        language=profile.language,
    )
    validate_plan(compiler_plan)
    return compiler_plan


def _alternative_objective(
    interpretation_id: str,
    semantic_deviation: float,
    cost: float,
    *,
    reason: str,
    eligible: bool = True,
) -> ObjectiveScore:
    return ObjectiveScore(
        interpretation_id=interpretation_id,
        semantic_deviation=semantic_deviation,
        conservative_cost=cost,
        semantic_utility=1.0 / (1.0 + semantic_deviation),
        execution_utility=1.0 / (1.0 + cost),
        nash_score=None,
        semantically_admissible=True,
        nash_eligible=eligible,
        reason=reason,
    )


def _random_feasible_search(
    *,
    candidate: PlannerCandidate,
    logical_plan: object,
    indexed_plan: object,
    profiles: Sequence[BackendCapabilityProfile],
    exchange_catalog: ExchangeCatalog,
    physical_compiler: PhysicalCompiler,
    budget: int,
    policy: MethodPolicy,
) -> tuple[BnBSearchResult, tuple[Mapping[str, object], ...]]:
    root = indexed_plan.root_state(candidate.candidate_id)
    profile_map = {item.backend_id: item for item in profiles}
    decisions: list[Mapping[str, object]] = []
    generated = 1
    infeasible = 0
    for attempt in range(max(1, budget)):
        state = root
        step = 0
        while not state.is_complete:
            successors, rejected = enumerate_successors(
                state,
                backend_profiles=profiles,
                exchange_catalog=exchange_catalog,
            )
            generated += len(successors) + len(rejected)
            infeasible += len(rejected)
            if not successors:
                break
            chosen = seeded_choice(
                successors,
                seed=policy.seed,
                decision_key=f"{candidate.candidate_id}:{attempt}:{step}:{state.state_id}",
            )
            decisions.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "attempt": attempt,
                    "step": step,
                    "state_id": state.state_id,
                    "action_id": chosen.action_id,
                    "seed": policy.seed,
                }
            )
            state = chosen.state
            step += 1
        if not state.is_complete:
            continue
        compilation = physical_compiler.compile(
            logical_plan,
            state,
            profile_map,
            pattern_query=candidate.pattern_query,
        )
        if not compilation.feasible:
            infeasible += 1
            continue
        placeholder = CostPrediction(
            mu=0.0,
            sigma=0.0,
            lower=1.0,
            upper=1.0,
            beta=0.0,
            estimator_id="random-feasible-no-cost-guidance",
            model_version="m12d-random-v1",
            metadata={
                "not_a_cost_estimate": True,
                "t_max_policy": "apply_to_measured_complete_plan_cost",
            },
        )
        plan = PhysicalPlan(
            interpretation_id=candidate.candidate_id,
            logical_plan_id=state.logical_plan_id,
            state=state,
            realization=PhysicalRealization(
                state_id=state.state_id,
                placements=state.placements,
                exchanges=state.exchanges,
                compilation=compilation,
            ),
            cost=placeholder,
        )
        return (
            BnBSearchResult(
                interpretation_id=candidate.candidate_id,
                incumbent=plan,
                discovered_complete_plans=(plan,),
                trace=(),
                processed_state_ids=tuple(
                    str(item["state_id"])
                    for item in decisions
                    if item["candidate_id"] == candidate.candidate_id
                ),
                processed_count=step + 1,
                generated_count=generated,
                pruned_count=0,
                infeasible_count=infeasible,
                budget=budget,
                termination_reason="random_feasible_complete",
            ),
            tuple(decisions),
        )
    return (
        BnBSearchResult(
            interpretation_id=candidate.candidate_id,
            incumbent=None,
            discovered_complete_plans=(),
            trace=(),
            processed_state_ids=(),
            processed_count=min(budget, max(1, budget)),
            generated_count=generated,
            pruned_count=0,
            infeasible_count=infeasible,
            budget=budget,
            termination_reason="random_feasible_exhausted",
        ),
        tuple(decisions),
    )


def _oracle_not_available(
    policy: MethodPolicy,
    query_context: QueryPlanningContext,
    config: PlanningConfig,
) -> MethodPlanningResult:
    result = MainPlannerResult(
        run_id=config.run_id,
        query_id=query_context.query_id,
        task_id=query_context.task_id,
        status="oracle_not_available",
        reason=(
            "Exhaustive oracle requires controlled true-cost evidence and an explicit "
            f"state limit ({policy.oracle_state_limit})."
        ),
        candidate_records=(),
        selected_plans=(),
    )
    return MethodPlanningResult(result, policy, oracle_status="oracle_not_available")
