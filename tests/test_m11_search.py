from dataclasses import dataclass

from xgap.algebra.conditions import LengthEquals
from xgap.algebra.ops import JoinOp, NodesOp, SelectionOp
from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    FeatureSupport,
    SupportLevel,
    SupportReason,
)
from xgap.planning import (
    ConfidenceContext,
    CostPrediction,
    ExchangeCatalog,
    ExchangeStrategy,
    PhysicalCompilationResult,
    SearchRunContext,
    bnb_search,
    index_logical_plan,
)


def _profile(backend_id: str, supported: tuple[str, ...]) -> BackendCapabilityProfile:
    all_features = ("path_algebra.Nodes", "path_algebra.Selection", "path_algebra.Join")
    return BackendCapabilityProfile(
        backend_id=backend_id,
        engine=backend_id,
        language="controlled",
        data_model="controlled",
        version=1,
        feature_namespace="xgap.path_gpc",
        features={
            feature_id: FeatureSupport(
                feature_id=feature_id,
                level=(
                    SupportLevel.SUPPORTED
                    if feature_id in supported
                    else SupportLevel.UNSUPPORTED
                ),
                reason=SupportReason(code="controlled", message="controlled test profile"),
            )
            for feature_id in all_features
        },
    )


@dataclass(frozen=True)
class ControlledCompiler:
    compiler_id: str = "controlled-physical-compiler"

    def compile(self, logical_plan, state, backend_profiles, *, pattern_query=None):
        del logical_plan, backend_profiles, pattern_query
        return PhysicalCompilationResult(
            feasible=state.is_complete,
            executable=False,
            status="controlled",
            reason_code="controlled_test_artifact",
        )


@dataclass(frozen=True)
class PlacementCostEstimator:
    bounds: dict[tuple[tuple[str, str], ...], tuple[float, float]]
    default: tuple[float, float] = (0.1, 100.0)
    estimator_id: str = "controlled-placement-cost"
    model_version: str = "1"

    def predict(self, state, confidence_context):
        del confidence_context
        key = tuple((item.operator_id, item.backend_id) for item in state.placements)
        lower, upper = self.bounds.get(key, self.default)
        return CostPrediction(
            mu=0.0,
            sigma=0.0,
            lower=lower,
            upper=upper,
            beta=0.0,
            estimator_id=self.estimator_id,
            model_version=self.model_version,
        )


def _run(plan, profiles, estimator, budget=20, exchanges=()):
    indexed = index_logical_plan(plan)
    return bnb_search(
        interpretation_id="candidate-1",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=profiles,
        exchange_catalog=ExchangeCatalog(tuple(exchanges)),
        budget=budget,
        cost_estimator=estimator,
        confidence_context=ConfidenceContext(delta=0.05, state_space_bound=100),
        physical_compiler=ControlledCompiler(),
        run_context=SearchRunContext("run-1", "query-1", "task-1", "alignment-1"),
    )


def test_first_incumbent_then_strict_upper_bound_replacement() -> None:
    plan = NodesOp()
    profiles = (_profile("a", ("path_algebra.Nodes",)), _profile("b", ("path_algebra.Nodes",)))
    estimator = PlacementCostEstimator(
        {
            (("op0000", "a"),): (1.0, 10.0),
            (("op0000", "b"),): (2.0, 3.0),
        }
    )

    result = _run(plan, profiles, estimator)

    assert [item.cost.upper for item in result.discovered_complete_plans] == [10.0, 3.0]
    assert result.incumbent is not None
    assert result.incumbent.cost.upper == 3.0
    assert result.incumbent.state.selected_backend_ids == ("b",)


def test_successor_pruning_and_extract_min_early_termination_are_safe() -> None:
    plan = NodesOp()
    profiles = (_profile("a", ("path_algebra.Nodes",)), _profile("b", ("path_algebra.Nodes",)))
    estimator = PlacementCostEstimator(
        {
            (("op0000", "a"),): (1.0, 3.0),
            (("op0000", "b"),): (5.0, 6.0),
        }
    )

    result = _run(plan, profiles, estimator)

    assert result.incumbent is not None
    assert result.incumbent.cost.upper == 3.0
    assert result.termination_reason == "bound_terminated"
    assert result.processed_count == 3
    assert result.trace[-1].prune_reason == "current_lower_not_better_than_incumbent_upper"


def test_successor_is_pruned_when_its_lower_cannot_improve_incumbent() -> None:
    plan = SelectionOp(condition=LengthEquals(0), child=NodesOp())
    profiles = (
        _profile("a", ("path_algebra.Nodes", "path_algebra.Selection")),
        _profile("b", ("path_algebra.Nodes", "path_algebra.Selection")),
    )
    estimator = PlacementCostEstimator(
        {
            (("op0000", "a"),): (0.5, 100.0),
            (("op0000", "b"),): (2.0, 100.0),
            (("op0000", "a"), ("op0001", "a")): (1.0, 3.0),
            (("op0000", "b"), ("op0001", "b")): (5.0, 6.0),
        }
    )

    result = _run(plan, profiles, estimator)

    assert result.incumbent is not None and result.incumbent.cost.upper == 3.0
    assert result.pruned_count == 1
    assert any(
        item.prune_reason == "successor_lower_not_better_than_incumbent_upper"
        for item in result.trace
    )


def test_missing_cross_backend_exchange_is_infeasible() -> None:
    plan = SelectionOp(condition=LengthEquals(0), child=NodesOp())
    profiles = (
        _profile("a", ("path_algebra.Nodes",)),
        _profile("b", ("path_algebra.Selection",)),
    )
    estimator = PlacementCostEstimator({})

    result = _run(plan, profiles, estimator)

    assert result.incumbent is None
    assert result.infeasible_count == 1
    assert any(item.prune_reason == "missing_exchange_strategy" for item in result.trace)


def test_explicit_exchange_makes_cross_backend_realization_complete() -> None:
    plan = SelectionOp(condition=LengthEquals(0), child=NodesOp())
    profiles = (
        _profile("a", ("path_algebra.Nodes",)),
        _profile("b", ("path_algebra.Selection",)),
    )
    strategy = ExchangeStrategy(
        strategy_id="controlled-pathset-transfer",
        source_backend_id="a",
        target_backend_id="b",
        result_kind="PATH_SET",
    )
    estimator = PlacementCostEstimator(
        {
            (("op0000", "a"), ("op0001", "b")): (1.0, 2.0),
        }
    )

    result = _run(plan, profiles, estimator, exchanges=(strategy,))

    assert result.incumbent is not None
    assert result.incumbent.state.is_complete
    assert result.incumbent.state.exchanges[0].strategy_id == strategy.strategy_id


def test_multiple_exchange_strategies_branch_only_when_explicitly_configured() -> None:
    plan = SelectionOp(condition=LengthEquals(0), child=NodesOp())
    profiles = (
        _profile("a", ("path_algebra.Nodes",)),
        _profile("b", ("path_algebra.Selection",)),
    )
    strategies = tuple(
        ExchangeStrategy(
            strategy_id=strategy_id,
            source_backend_id="a",
            target_backend_id="b",
            result_kind="PATH_SET",
        )
        for strategy_id in ("controlled-transfer-1", "controlled-transfer-2")
    )
    estimator = PlacementCostEstimator(
        {(("op0000", "a"), ("op0001", "b")): (1.0, 2.0)}
    )

    result = _run(plan, profiles, estimator, exchanges=strategies)

    assert len(result.discovered_complete_plans) == 2
    assert {
        item.state.exchanges[0].strategy_id for item in result.discovered_complete_plans
    } == {"controlled-transfer-1", "controlled-transfer-2"}


def test_budget_uses_extract_min_and_preserves_anytime_prefix() -> None:
    plan = NodesOp()
    profiles = (_profile("a", ("path_algebra.Nodes",)), _profile("b", ("path_algebra.Nodes",)))
    estimator = PlacementCostEstimator(
        {
            (("op0000", "a"),): (1.0, 10.0),
            (("op0000", "b"),): (2.0, 3.0),
        }
    )

    small = _run(plan, profiles, estimator, budget=2)
    large = _run(plan, profiles, estimator, budget=3)

    assert small.termination_reason == "budget_exhausted"
    assert small.trace[-1].termination_reason == "budget_exhausted"
    assert small.processed_count == 2
    assert large.processed_state_ids[: len(small.processed_state_ids)] == small.processed_state_ids
    assert small.incumbent is not None and large.incumbent is not None
    assert large.incumbent.cost.upper <= small.incumbent.cost.upper
