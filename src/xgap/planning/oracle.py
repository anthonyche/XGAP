"""Tiny exhaustive physical-search oracle for tests and controlled experiments."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from xgap.algebra.ops import AlgebraOp
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.pattern.ast import PathPatternQuery
from xgap.planning.contracts import JsonMap, PhysicalCompilationResult, PhysicalState
from xgap.planning.protocols import PhysicalCompiler
from xgap.planning.search import BnBSearchResult, ExchangeCatalog, enumerate_successors
from xgap.planning.topology import IndexedLogicalPlan


@dataclass(frozen=True)
class ExhaustivePlanRecord:
    state: PhysicalState
    compilation: PhysicalCompilationResult
    true_cost: float

    def to_dict(self) -> JsonMap:
        return {
            "state": self.state.to_dict(),
            "compilation": self.compilation.to_dict(),
            "true_cost": self.true_cost,
        }


@dataclass(frozen=True)
class ExhaustiveOracleResult:
    interpretation_id: str
    reachable_state_ids: tuple[str, ...]
    complete_plans: tuple[ExhaustivePlanRecord, ...]

    @property
    def best(self) -> ExhaustivePlanRecord | None:
        if not self.complete_plans:
            return None
        return min(self.complete_plans, key=lambda item: (item.true_cost, item.state.state_id))

    def to_dict(self) -> JsonMap:
        return {
            "interpretation_id": self.interpretation_id,
            "reachable_state_ids": list(self.reachable_state_ids),
            "reachable_state_count": len(self.reachable_state_ids),
            "complete_plans": [item.to_dict() for item in self.complete_plans],
            "best_state_id": self.best.state.state_id if self.best else None,
            "best_true_cost": self.best.true_cost if self.best else None,
        }


@dataclass(frozen=True)
class OracleComparison:
    oracle_best_state_id: str | None
    oracle_best_true_cost: float | None
    bnb_state_id: str | None
    bnb_true_cost: float | None
    true_log_cost_regret: float | None
    reachable_states: int
    processed_states: int
    generated_states: int
    pruned_states: int
    pruning_ratio: float
    search_space_reduction: float
    eta_search: float | None = None
    eta_select: float | None = None
    eta: float | None = None

    def to_dict(self) -> JsonMap:
        return {
            "oracle_best_state_id": self.oracle_best_state_id,
            "oracle_best_true_cost": self.oracle_best_true_cost,
            "bnb_state_id": self.bnb_state_id,
            "bnb_true_cost": self.bnb_true_cost,
            "true_log_cost_regret": self.true_log_cost_regret,
            "reachable_states": self.reachable_states,
            "processed_states": self.processed_states,
            "generated_states": self.generated_states,
            "pruned_states": self.pruned_states,
            "pruning_ratio": self.pruning_ratio,
            "search_space_reduction": self.search_space_reduction,
            "eta_search": self.eta_search,
            "eta_select": self.eta_select,
            "eta": self.eta,
        }


def exhaustive_physical_oracle(
    *,
    interpretation_id: str,
    logical_plan: AlgebraOp,
    indexed_plan: IndexedLogicalPlan,
    backend_profiles: Sequence[BackendCapabilityProfile],
    exchange_catalog: ExchangeCatalog,
    physical_compiler: PhysicalCompiler,
    true_cost: Callable[[PhysicalState], float],
    pattern_query: PathPatternQuery | None = None,
) -> ExhaustiveOracleResult:
    """Enumerate a tiny represented state space; never called by the main planner."""

    profiles = tuple(sorted(backend_profiles, key=lambda item: item.backend_id))
    profile_map = {item.backend_id: item for item in profiles}
    root = indexed_plan.root_state(interpretation_id)
    queue = deque([root])
    seen: dict[str, PhysicalState] = {}
    complete: list[ExhaustivePlanRecord] = []
    while queue:
        state = queue.popleft()
        if state.state_id in seen:
            continue
        seen[state.state_id] = state
        if state.is_complete:
            compilation = physical_compiler.compile(
                logical_plan,
                state,
                profile_map,
                pattern_query=pattern_query,
            )
            if compilation.feasible:
                value = float(true_cost(state))
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("Oracle true costs must be finite and positive.")
                complete.append(ExhaustivePlanRecord(state, compilation, value))
            continue
        successors, _ = enumerate_successors(
            state,
            backend_profiles=profiles,
            exchange_catalog=exchange_catalog,
        )
        queue.extend(item.state for item in successors)
    return ExhaustiveOracleResult(
        interpretation_id=interpretation_id,
        reachable_state_ids=tuple(sorted(seen)),
        complete_plans=tuple(sorted(complete, key=lambda item: item.state.state_id)),
    )


def compare_search_with_oracle(
    search: BnBSearchResult,
    oracle: ExhaustiveOracleResult,
    *,
    lower_bounds: Mapping[str, float] | None = None,
) -> OracleComparison:
    best = oracle.best
    incumbent_state_id = search.incumbent.state.state_id if search.incumbent else None
    true_cost_by_state = {item.state.state_id: item.true_cost for item in oracle.complete_plans}
    incumbent_true = true_cost_by_state.get(incumbent_state_id) if incumbent_state_id else None
    regret = None
    if best is not None and incumbent_true is not None:
        regret = math.log(incumbent_true) - math.log(best.true_cost)
    eta_search = eta_select = eta = None
    if lower_bounds is not None and oracle.complete_plans and search.discovered_complete_plans:
        all_complete = [lower_bounds[item.state.state_id] for item in oracle.complete_plans]
        discovered = [
            lower_bounds[item.state.state_id] for item in search.discovered_complete_plans
        ]
        if incumbent_state_id is not None:
            eta_search = min(discovered) - min(all_complete)
            eta_select = lower_bounds[incumbent_state_id] - min(discovered)
            eta = eta_search + eta_select
    generated_denominator = max(1, search.generated_count)
    reachable_denominator = max(1, len(oracle.reachable_state_ids))
    return OracleComparison(
        oracle_best_state_id=best.state.state_id if best else None,
        oracle_best_true_cost=best.true_cost if best else None,
        bnb_state_id=incumbent_state_id,
        bnb_true_cost=incumbent_true,
        true_log_cost_regret=regret,
        reachable_states=len(oracle.reachable_state_ids),
        processed_states=search.processed_count,
        generated_states=search.generated_count,
        pruned_states=search.pruned_count,
        pruning_ratio=search.pruned_count / generated_denominator,
        search_space_reduction=max(0.0, 1.0 - search.processed_count / reachable_denominator),
        eta_search=eta_search,
        eta_select=eta_select,
        eta=eta,
    )


def budget_quality_curve(
    budgets: Sequence[int],
    run_search: Callable[[int], BnBSearchResult],
    oracle: ExhaustiveOracleResult,
) -> tuple[JsonMap, ...]:
    records = []
    for budget in sorted(set(budgets)):
        result = run_search(budget)
        comparison = compare_search_with_oracle(result, oracle)
        records.append(
            {
                "budget": budget,
                "termination_reason": result.termination_reason,
                "incumbent_upper": result.incumbent.cost.upper if result.incumbent else None,
                "true_log_cost_regret": comparison.true_log_cost_regret,
                "processed_states": result.processed_count,
            }
        )
    return tuple(records)
