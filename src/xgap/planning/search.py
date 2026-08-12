"""Deterministic budgeted branch-and-bound over physical realizations."""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from xgap.algebra.ops import AlgebraOp
from xgap.backends.capabilities import BackendCapabilityProfile, SupportLevel
from xgap.backends.compatibility import check_backend_support
from xgap.pattern.ast import PathPatternQuery
from xgap.planning.contracts import (
    ConfidenceContext,
    CostPrediction,
    ExchangeDecision,
    ExchangeStrategy,
    JsonMap,
    PhysicalPlan,
    PhysicalRealization,
    PhysicalState,
    PlacementDecision,
    PlanningTraceEvent,
)
from xgap.planning.protocols import CostEstimator, PhysicalCompiler
from xgap.planning.topology import IndexedLogicalPlan


@dataclass(frozen=True)
class ExchangeCatalog:
    strategies: tuple[ExchangeStrategy, ...] = ()
    catalog_id: str = "empty-exchange-catalog"
    version: str = "1"

    def __post_init__(self) -> None:
        strategies = tuple(
            sorted(
                self.strategies,
                key=lambda item: (
                    item.source_backend_id,
                    item.target_backend_id,
                    item.result_kind,
                    item.strategy_id,
                ),
            )
        )
        keys = [
            (
                item.source_backend_id,
                item.target_backend_id,
                item.result_kind,
                item.strategy_id,
            )
            for item in strategies
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("ExchangeCatalog strategies must have unique keys.")
        object.__setattr__(self, "strategies", strategies)

    def matching(
        self,
        source_backend_id: str,
        target_backend_id: str,
        result_kind: str,
    ) -> tuple[ExchangeStrategy, ...]:
        return tuple(
            item
            for item in self.strategies
            if item.executable
            and item.source_backend_id == source_backend_id
            and item.target_backend_id == target_backend_id
            and item.result_kind == result_kind
        )

    def to_dict(self) -> JsonMap:
        return {
            "catalog_id": self.catalog_id,
            "version": self.version,
            "strategies": [item.to_dict() for item in self.strategies],
        }


@dataclass(frozen=True)
class SearchRunContext:
    run_id: str
    query_id: str
    task_id: str
    alignment_ref: str


@dataclass(frozen=True)
class SearchTransition:
    state: PhysicalState
    parent_state_id: str
    action_id: str
    action: str
    placement: PlacementDecision
    exchanges: tuple[ExchangeDecision, ...]


@dataclass(frozen=True)
class BnBSearchResult:
    interpretation_id: str
    incumbent: PhysicalPlan | None
    discovered_complete_plans: tuple[PhysicalPlan, ...]
    trace: tuple[PlanningTraceEvent, ...]
    processed_state_ids: tuple[str, ...]
    processed_count: int
    generated_count: int
    pruned_count: int
    infeasible_count: int
    budget: int
    termination_reason: str

    @property
    def found_plan(self) -> bool:
        return self.incumbent is not None

    def to_dict(self) -> JsonMap:
        return {
            "interpretation_id": self.interpretation_id,
            "incumbent": self.incumbent.to_dict() if self.incumbent else None,
            "discovered_complete_plans": [
                item.to_dict() for item in self.discovered_complete_plans
            ],
            "processed_state_ids": list(self.processed_state_ids),
            "processed_count": self.processed_count,
            "generated_count": self.generated_count,
            "pruned_count": self.pruned_count,
            "infeasible_count": self.infeasible_count,
            "budget": self.budget,
            "termination_reason": self.termination_reason,
        }


def enumerate_successors(
    state: PhysicalState,
    *,
    backend_profiles: Sequence[BackendCapabilityProfile],
    exchange_catalog: ExchangeCatalog,
) -> tuple[tuple[SearchTransition, ...], tuple[SearchTransition, ...]]:
    """Return feasible and exchange-infeasible transitions in stable order."""

    if state.is_complete or not state.unassigned_operator_ids:
        return (), ()
    next_operator_id = state.unassigned_operator_ids[0]
    operator = next(item for item in state.operators if item.operator_id == next_operator_id)
    feasible: list[SearchTransition] = []
    infeasible: list[SearchTransition] = []

    for profile in sorted(backend_profiles, key=lambda item: item.backend_id):
        support = check_backend_support(profile, operator.feature_id)
        if support.level is SupportLevel.UNSUPPORTED:
            continue
        placement = PlacementDecision(
            operator_id=operator.operator_id,
            backend_id=profile.backend_id,
            feature_id=operator.feature_id,
            support_level=support.level.value,
            conditions=support.conditions,
        )
        placed_state = PhysicalState(
            interpretation_id=state.interpretation_id,
            logical_plan_id=state.logical_plan_id,
            operators=state.operators,
            dependencies=state.dependencies,
            placements=(*state.placements, placement),
            exchanges=state.exchanges,
        )
        unresolved_cross = _new_cross_backend_dependencies(placed_state)
        choices: list[tuple[ExchangeDecision, ...]] = []
        missing = False
        for dependency in unresolved_cross:
            source = placed_state.placement_for(dependency.source_operator_id)
            target = placed_state.placement_for(dependency.target_operator_id)
            assert source is not None and target is not None
            strategies = exchange_catalog.matching(
                source.backend_id,
                target.backend_id,
                dependency.result_kind,
            )
            if not strategies:
                missing = True
                break
            choices.append(
                tuple(
                    ExchangeDecision(
                        dependency_id=dependency.dependency_id,
                        source_operator_id=dependency.source_operator_id,
                        target_operator_id=dependency.target_operator_id,
                        source_backend_id=source.backend_id,
                        target_backend_id=target.backend_id,
                        strategy_id=strategy.strategy_id,
                        executable=strategy.executable,
                        metadata={
                            "catalog_id": exchange_catalog.catalog_id,
                            "catalog_version": exchange_catalog.version,
                            **strategy.metadata,
                        },
                    )
                    for strategy in strategies
                )
            )

        if missing:
            action_id = f"place:{operator.operator_id}:{profile.backend_id}:no-exchange"
            infeasible.append(
                SearchTransition(
                    state=placed_state,
                    parent_state_id=state.state_id,
                    action_id=action_id,
                    action="placement",
                    placement=placement,
                    exchanges=(),
                )
            )
            continue

        exchange_combinations = itertools.product(*choices) if choices else [()]
        for combination in exchange_combinations:
            exchange_delta = tuple(combination)
            successor = PhysicalState(
                interpretation_id=state.interpretation_id,
                logical_plan_id=state.logical_plan_id,
                operators=state.operators,
                dependencies=state.dependencies,
                placements=placed_state.placements,
                exchanges=(*state.exchanges, *exchange_delta),
            )
            suffix = ",".join(item.strategy_id for item in exchange_delta) or "local"
            feasible.append(
                SearchTransition(
                    state=successor,
                    parent_state_id=state.state_id,
                    action_id=f"place:{operator.operator_id}:{profile.backend_id}:{suffix}",
                    action="placement",
                    placement=placement,
                    exchanges=exchange_delta,
                )
            )
    return (
        tuple(sorted(feasible, key=lambda item: (item.action_id, item.state.state_id))),
        tuple(sorted(infeasible, key=lambda item: (item.action_id, item.state.state_id))),
    )


def _new_cross_backend_dependencies(state: PhysicalState):
    result = []
    for dependency in state.dependencies:
        if state.exchange_for(dependency.dependency_id) is not None:
            continue
        source = state.placement_for(dependency.source_operator_id)
        target = state.placement_for(dependency.target_operator_id)
        if source is None or target is None or source.backend_id == target.backend_id:
            continue
        result.append(dependency)
    return tuple(sorted(result, key=lambda item: item.dependency_id))


def bnb_search(
    *,
    interpretation_id: str,
    logical_plan: AlgebraOp,
    indexed_plan: IndexedLogicalPlan,
    backend_profiles: Sequence[BackendCapabilityProfile],
    exchange_catalog: ExchangeCatalog,
    budget: int,
    cost_estimator: CostEstimator,
    confidence_context: ConfidenceContext,
    physical_compiler: PhysicalCompiler,
    run_context: SearchRunContext,
    pattern_query: PathPatternQuery | None = None,
) -> BnBSearchResult:
    """Search one fixed logical plan; ontology and semantics are already fixed."""

    if budget <= 0:
        raise ValueError("BnB budget must be positive.")
    profiles = tuple(sorted(backend_profiles, key=lambda item: item.backend_id))
    if not profiles:
        raise ValueError("BnBSearch requires at least one backend profile.")
    profile_map = {item.backend_id: item for item in profiles}
    if len(profile_map) != len(profiles):
        raise ValueError("Backend profile identifiers must be unique.")

    root = indexed_plan.root_state(interpretation_id)
    root_prediction = cost_estimator.predict(root, confidence_context)
    open_heap: list[tuple[float, str, PhysicalState]] = [
        (root_prediction.lower, root.state_id, root)
    ]
    predictions: dict[str, CostPrediction] = {root.state_id: root_prediction}
    transition_by_state: dict[str, SearchTransition] = {}
    trace: list[PlanningTraceEvent] = []
    processed_state_ids: list[str] = []
    discovered: list[PhysicalPlan] = []
    incumbent: PhysicalPlan | None = None
    processed = 0
    generated = 1
    pruned = 0
    infeasible_count = 0
    termination_reason = "open_empty"

    while open_heap and processed < budget:
        _, _, state = heapq.heappop(open_heap)
        prediction = predictions[state.state_id]
        processed += 1
        processed_state_ids.append(state.state_id)
        incumbent_before = incumbent.cost.upper if incumbent else None
        transition = transition_by_state.get(state.state_id)

        if incumbent is not None and prediction.lower >= incumbent.cost.upper:
            termination_reason = "bound_terminated"
            trace.append(
                _trace_event(
                    state=state,
                    transition=transition,
                    prediction=prediction,
                    run_context=run_context,
                    budget=budget,
                    budget_used=processed,
                    processed_index=processed,
                    open_size=len(open_heap),
                    feasible=True,
                    pruned=True,
                    prune_reason="current_lower_not_better_than_incumbent_upper",
                    incumbent_before=incumbent_before,
                    incumbent_after=incumbent.cost.upper,
                    termination_reason=termination_reason,
                )
            )
            break

        feasible = True
        if state.is_complete:
            compilation = physical_compiler.compile(
                logical_plan,
                state,
                profile_map,
                pattern_query=pattern_query,
            )
            feasible = compilation.feasible
            if feasible:
                realization = PhysicalRealization(
                    state_id=state.state_id,
                    placements=state.placements,
                    exchanges=state.exchanges,
                    compilation=compilation,
                )
                plan = PhysicalPlan(
                    interpretation_id=interpretation_id,
                    logical_plan_id=state.logical_plan_id,
                    state=state,
                    realization=realization,
                    cost=prediction,
                )
                discovered.append(plan)
                if incumbent is None or plan.cost.upper < incumbent.cost.upper:
                    incumbent = plan
            else:
                infeasible_count += 1

        trace.append(
            _trace_event(
                state=state,
                transition=transition,
                prediction=prediction,
                run_context=run_context,
                budget=budget,
                budget_used=processed,
                processed_index=processed,
                open_size=len(open_heap),
                feasible=feasible,
                pruned=False,
                prune_reason=None if feasible else "physical_compiler_infeasible",
                incumbent_before=incumbent_before,
                incumbent_after=incumbent.cost.upper if incumbent else None,
            )
        )
        if state.is_complete:
            continue

        successors, infeasible = enumerate_successors(
            state,
            backend_profiles=profiles,
            exchange_catalog=exchange_catalog,
        )
        generated += len(successors) + len(infeasible)
        infeasible_count += len(infeasible)
        for item in infeasible:
            trace.append(
                _trace_event(
                    state=item.state,
                    transition=item,
                    prediction=None,
                    run_context=run_context,
                    budget=budget,
                    budget_used=processed,
                    processed_index=None,
                    open_size=len(open_heap),
                    feasible=False,
                    pruned=True,
                    prune_reason="missing_exchange_strategy",
                    incumbent_before=incumbent.cost.upper if incumbent else None,
                    incumbent_after=incumbent.cost.upper if incumbent else None,
                )
            )
        for item in successors:
            successor_prediction = cost_estimator.predict(item.state, confidence_context)
            predictions[item.state.state_id] = successor_prediction
            transition_by_state[item.state.state_id] = item
            if incumbent is not None and successor_prediction.lower >= incumbent.cost.upper:
                pruned += 1
                trace.append(
                    _trace_event(
                        state=item.state,
                        transition=item,
                        prediction=successor_prediction,
                        run_context=run_context,
                        budget=budget,
                        budget_used=processed,
                        processed_index=None,
                        open_size=len(open_heap),
                        feasible=True,
                        pruned=True,
                        prune_reason="successor_lower_not_better_than_incumbent_upper",
                        incumbent_before=incumbent.cost.upper,
                        incumbent_after=incumbent.cost.upper,
                    )
                )
                continue
            heapq.heappush(
                open_heap,
                (successor_prediction.lower, item.state.state_id, item.state),
            )

    else:
        if open_heap and processed >= budget:
            termination_reason = "budget_exhausted"
        else:
            termination_reason = "open_empty"

    if trace and trace[-1].termination_reason is None:
        trace[-1] = replace(trace[-1], termination_reason=termination_reason)

    return BnBSearchResult(
        interpretation_id=interpretation_id,
        incumbent=incumbent,
        discovered_complete_plans=tuple(discovered),
        trace=tuple(trace),
        processed_state_ids=tuple(processed_state_ids),
        processed_count=processed,
        generated_count=generated,
        pruned_count=pruned,
        infeasible_count=infeasible_count,
        budget=budget,
        termination_reason=termination_reason,
    )


def _trace_event(
    *,
    state: PhysicalState,
    transition: SearchTransition | None,
    prediction: CostPrediction | None,
    run_context: SearchRunContext,
    budget: int,
    budget_used: int,
    processed_index: int | None,
    open_size: int,
    feasible: bool,
    pruned: bool,
    prune_reason: str | None,
    incumbent_before: float | None,
    incumbent_after: float | None,
    termination_reason: str | None = None,
) -> PlanningTraceEvent:
    return PlanningTraceEvent(
        run_id=run_context.run_id,
        query_id=run_context.query_id,
        task_id=run_context.task_id,
        interpretation_id=state.interpretation_id,
        alignment_ref=run_context.alignment_ref,
        state_id=state.state_id,
        parent_state_id=transition.parent_state_id if transition else None,
        processed_index=processed_index,
        action_id=transition.action_id if transition else "root",
        action=transition.action if transition else "root",
        placement_delta=transition.placement if transition else None,
        exchange_delta=transition.exchanges if transition else (),
        open_size=open_size,
        budget=budget,
        budget_used=budget_used,
        feasible=feasible,
        complete=state.is_complete,
        prediction=prediction,
        pruned=pruned,
        prune_reason=prune_reason,
        incumbent_before=incumbent_before,
        incumbent_after=incumbent_after,
        termination_reason=termination_reason,
    )
