"""Compare bounded search with the tiny M11 experiment-only oracle."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
    compare_search_with_oracle,
    exhaustive_physical_oracle,
    index_logical_plan,
)


def profile(backend_id: str) -> BackendCapabilityProfile:
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
                SupportReason(code="controlled", message="controlled demo profile"),
            )
        },
    )


@dataclass(frozen=True)
class ControlledCompiler:
    compiler_id: str = "controlled-oracle-demo"

    def compile(self, logical_plan, state, backend_profiles, *, pattern_query=None):
        del logical_plan, backend_profiles, pattern_query
        return PhysicalCompilationResult(state.is_complete, False, "controlled")


@dataclass(frozen=True)
class ControlledEstimator:
    estimator_id: str = "controlled-oracle-demo"
    model_version: str = "1"

    def predict(self, state, confidence_context):
        del confidence_context
        bounds = {"backend-a": (1.0, 2.0), "backend-b": (3.0, 5.0)}
        lower, upper = bounds[state.selected_backend_ids[0]] if state.is_complete else (0.1, 100.0)
        return CostPrediction(0.0, 0.0, lower, upper, 0.0, self.estimator_id, self.model_version)


def main() -> None:
    plan = NodesOp()
    indexed = index_logical_plan(plan)
    profiles = (profile("backend-a"), profile("backend-b"))
    compiler = ControlledCompiler()
    oracle = exhaustive_physical_oracle(
        interpretation_id="controlled-interpretation",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=profiles,
        exchange_catalog=ExchangeCatalog(),
        physical_compiler=compiler,
        true_cost=lambda state: 2.0 if state.selected_backend_ids == ("backend-a",) else 5.0,
    )
    search = bnb_search(
        interpretation_id="controlled-interpretation",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=profiles,
        exchange_catalog=ExchangeCatalog(),
        budget=10,
        cost_estimator=ControlledEstimator(),
        confidence_context=ConfidenceContext(0.05, 3),
        physical_compiler=compiler,
        run_context=SearchRunContext("demo", "query", "task", "controlled-alignment"),
    )
    comparison = compare_search_with_oracle(search, oracle)
    print("M11 exhaustive oracle comparison:")
    print(f"reachable_states={comparison.reachable_states}")
    print(f"processed_states={comparison.processed_states}")
    print(f"oracle_best_true_cost={comparison.oracle_best_true_cost}")
    print(f"bnb_true_cost={comparison.bnb_true_cost}")
    print(f"true_log_cost_regret={comparison.true_log_cost_regret}")


if __name__ == "__main__":
    main()
