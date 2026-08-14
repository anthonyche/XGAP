from __future__ import annotations

import pytest

from xgap.algebra.ops import NodesOp
from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    FeatureSupport,
    SupportLevel,
    SupportReason,
)
from xgap.experiments.contracts import AblationConfig, BaselineConfig, BaselineId
from xgap.experiments.method_planner import run_controlled_exhaustive_oracle
from xgap.experiments.methods import (
    RankingStrategy,
    SearchStrategy,
    list_methods,
    resolve_method_policy,
    seeded_choice,
)
from xgap.planning import ExchangeCatalog, PhysicalCompilationResult, index_logical_plan


class _ControlledCompiler:
    compiler_id = "m12d-controlled-test"

    def compile(self, logical_plan, state, backend_profiles, *, pattern_query=None):
        del logical_plan, backend_profiles, pattern_query
        return PhysicalCompilationResult(state.is_complete, False, "controlled")


def _profile(backend_id: str) -> BackendCapabilityProfile:
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


def _baseline(method: BaselineId) -> BaselineConfig:
    return BaselineConfig(
        method,
        backend_id=(
            "neo4j"
            if method in {BaselineId.SINGLE_BACKEND, BaselineId.DIRECT_TEXT2GRAPHQUERY}
            else None
        ),
        controlled_scope=method is BaselineId.EXHAUSTIVE_ORACLE,
        model_bundle_ref=(
            "models/qwen3_max_dashscope_live"
            if method is BaselineId.DIRECT_TEXT2GRAPHQUERY
            else None
        ),
    )


def test_method_registry_has_all_frozen_identifiers_and_distinct_policies() -> None:
    assert set(list_methods()) == {item.value for item in BaselineId}
    policies = {
        method: resolve_method_policy(_baseline(method), AblationConfig(), seed=7)
        for method in BaselineId
    }
    assert policies[BaselineId.FULL_XGAP].confidence_pruning
    assert policies[BaselineId.FULL_XGAP].use_gp_uncertainty
    assert policies[BaselineId.RANDOM_FEASIBLE].search_strategy is SearchStrategy.RANDOM_FEASIBLE
    assert not policies[BaselineId.RANDOM_FEASIBLE].use_gp_mean
    assert not policies[BaselineId.MEAN_ONLY].use_gp_uncertainty
    assert not policies[BaselineId.MEAN_ONLY].confidence_pruning
    assert not policies[BaselineId.NO_PRUNING].confidence_pruning
    assert not policies[BaselineId.NO_ONLINE_UPDATE].online_update
    assert policies[BaselineId.SINGLE_BACKEND].backend_id == "neo4j"
    assert policies[BaselineId.EXHAUSTIVE_ORACLE].controlled_only
    assert policies[BaselineId.DIRECT_TEXT2GRAPHQUERY].search_strategy is SearchStrategy.DIRECT


def test_ablation_switches_have_real_composable_behavior() -> None:
    policy = resolve_method_policy(
        _baseline(BaselineId.FULL_XGAP),
        AblationConfig(
            no_uncertainty=True,
            no_pruning=True,
            no_online_learning=True,
            no_semantic_bound=True,
            cost_only=True,
        ),
        seed=3,
    )
    assert not policy.use_gp_uncertainty
    assert not policy.confidence_pruning
    assert not policy.online_update
    assert not policy.apply_semantic_bound
    assert policy.ranking_strategy is RankingStrategy.COST_ONLY


def test_no_nash_requires_documented_alternative() -> None:
    with pytest.raises(ValueError, match="no_nash_ranking"):
        resolve_method_policy(
            _baseline(BaselineId.FULL_XGAP),
            AblationConfig(no_nash=True),
            seed=0,
        )
    policy = resolve_method_policy(
        _baseline(BaselineId.FULL_XGAP),
        AblationConfig(no_nash=True),
        seed=0,
        options={"no_nash_ranking": "semantic_then_cost"},
    )
    assert policy.ranking_strategy is RankingStrategy.SEMANTIC_THEN_COST


def test_seeded_random_decisions_are_reproducible() -> None:
    values = tuple(range(10))
    assert seeded_choice(values, seed=17, decision_key="state-a") == seeded_choice(
        values, seed=17, decision_key="state-a"
    )


def test_exhaustive_oracle_is_bounded_and_requires_explicit_true_cost() -> None:
    policy = resolve_method_policy(
        _baseline(BaselineId.EXHAUSTIVE_ORACLE),
        AblationConfig(),
        seed=0,
        options={"oracle_state_limit": 2},
    )
    plan = NodesOp()
    indexed = index_logical_plan(plan)
    blocked = run_controlled_exhaustive_oracle(
        policy=policy,
        interpretation_id="candidate-1",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=(_profile("a"), _profile("b")),
        exchange_catalog=ExchangeCatalog(),
        physical_compiler=_ControlledCompiler(),
        true_cost=lambda state: 1.0,
    )
    assert blocked.status == "oracle_not_available"
    assert blocked.result is None

    allowed_policy = resolve_method_policy(
        _baseline(BaselineId.EXHAUSTIVE_ORACLE),
        AblationConfig(),
        seed=0,
        options={"oracle_state_limit": 3},
    )
    allowed = run_controlled_exhaustive_oracle(
        policy=allowed_policy,
        interpretation_id="candidate-1",
        logical_plan=plan,
        indexed_plan=indexed,
        backend_profiles=(_profile("a"), _profile("b")),
        exchange_catalog=ExchangeCatalog(),
        physical_compiler=_ControlledCompiler(),
        true_cost=lambda state: 2.0 if state.selected_backend_ids == ("a",) else 5.0,
    )
    assert allowed.status == "ok"
    assert allowed.result is not None
    assert allowed.result.best is not None
    assert allowed.result.best.true_cost == 2.0
