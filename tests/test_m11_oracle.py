from dataclasses import dataclass

from xgap.algebra.ops import NodesOp
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
    PhysicalCompilationResult,
    SearchRunContext,
    bnb_search,
    budget_quality_curve,
    compare_search_with_oracle,
    exhaustive_physical_oracle,
    index_logical_plan,
)


def _profile(backend_id):
    feature_id = "path_algebra.Nodes"
    return BackendCapabilityProfile(
        backend_id=backend_id,
        engine=backend_id,
        language="controlled",
        data_model="controlled",
        version=1,
        feature_namespace="xgap.path_gpc",
        features={
            feature_id: FeatureSupport(
                feature_id,
                SupportLevel.SUPPORTED,
                SupportReason(code="controlled", message="controlled"),
            )
        },
    )


@dataclass(frozen=True)
class Compiler:
    compiler_id: str = "controlled"

    def compile(self, logical_plan, state, backend_profiles, *, pattern_query=None):
        del logical_plan, backend_profiles, pattern_query
        return PhysicalCompilationResult(state.is_complete, False, "controlled")


@dataclass(frozen=True)
class Estimator:
    estimator_id: str = "controlled"
    model_version: str = "1"

    def predict(self, state, confidence_context):
        del confidence_context
        bounds = {"a": (1.0, 2.0), "b": (3.0, 5.0)}
        lower, upper = bounds[state.selected_backend_ids[0]] if state.is_complete else (0.1, 100.0)
        return CostPrediction(0.0, 0.0, lower, upper, 0.0, self.estimator_id, self.model_version)


def _search(budget):
    plan = NodesOp()
    indexed = index_logical_plan(plan)
    return bnb_search(
        interpretation_id="c1",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=(_profile("a"), _profile("b")),
        exchange_catalog=ExchangeCatalog(),
        budget=budget,
        cost_estimator=Estimator(),
        confidence_context=ConfidenceContext(0.05, 3),
        physical_compiler=Compiler(),
        run_context=SearchRunContext("r", "q", "t", "a"),
    )


def test_exhaustive_oracle_agrees_at_sufficient_budget_and_reports_metrics() -> None:
    plan = NodesOp()
    indexed = index_logical_plan(plan)
    profiles = (_profile("a"), _profile("b"))
    oracle = exhaustive_physical_oracle(
        interpretation_id="c1",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=profiles,
        exchange_catalog=ExchangeCatalog(),
        physical_compiler=Compiler(),
        true_cost=lambda state: 2.0 if state.selected_backend_ids == ("a",) else 5.0,
    )
    search = _search(10)
    lower_bounds = {
        item.state.state_id: (1.0 if item.state.selected_backend_ids == ("a",) else 3.0)
        for item in oracle.complete_plans
    }
    comparison = compare_search_with_oracle(search, oracle, lower_bounds=lower_bounds)

    assert len(oracle.reachable_state_ids) == 3
    assert oracle.best is not None and oracle.best.true_cost == 2.0
    assert comparison.true_log_cost_regret == 0.0
    assert comparison.pruning_ratio >= 0
    assert comparison.search_space_reduction >= 0
    assert comparison.eta == comparison.eta_search + comparison.eta_select


def test_budget_quality_curve_records_anytime_result_quality() -> None:
    plan = NodesOp()
    indexed = index_logical_plan(plan)
    oracle = exhaustive_physical_oracle(
        interpretation_id="c1",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=(_profile("a"), _profile("b")),
        exchange_catalog=ExchangeCatalog(),
        physical_compiler=Compiler(),
        true_cost=lambda state: 2.0 if state.selected_backend_ids == ("a",) else 5.0,
    )
    curve = budget_quality_curve((1, 2, 3), _search, oracle)

    assert [item["budget"] for item in curve] == [1, 2, 3]
    assert curve[0]["incumbent_upper"] is None
    assert curve[-1]["true_log_cost_regret"] == 0.0
