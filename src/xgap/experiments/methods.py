"""Explicit M12-D method and ablation policies.

The policies select existing deterministic components. They do not introduce
new logical operators or alter the frozen M11 objective/search definitions.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from xgap.experiments.contracts import AblationConfig, BaselineConfig, BaselineId
from xgap.experiments.cost_calibration import BackendCostModelRegistry
from xgap.planning.contracts import ConfidenceContext, CostPrediction, PhysicalState


class SearchStrategy(str, Enum):
    BNB = "bnb"
    RANDOM_FEASIBLE = "random_feasible"
    EXHAUSTIVE = "exhaustive"
    DIRECT = "direct"


class RankingStrategy(str, Enum):
    NASH = "nash"
    COST_ONLY = "cost_only"
    SEMANTIC_THEN_COST = "semantic_then_cost"
    TRUE_COST = "true_cost"
    DIRECT = "direct"


@dataclass(frozen=True)
class MethodPolicy:
    method_id: BaselineId
    search_strategy: SearchStrategy
    ranking_strategy: RankingStrategy
    use_gp_mean: bool
    use_gp_uncertainty: bool
    confidence_pruning: bool
    online_update: bool
    apply_semantic_bound: bool
    backend_id: str | None = None
    controlled_only: bool = False
    oracle_state_limit: int | None = None
    seed: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.method_id in {BaselineId.SINGLE_BACKEND, BaselineId.DIRECT_TEXT2GRAPHQUERY}:
            if not self.backend_id:
                raise ValueError(f"{self.method_id.value} requires one backend_id.")
        if self.method_id is BaselineId.EXHAUSTIVE_ORACLE:
            if not self.controlled_only or not self.oracle_state_limit:
                raise ValueError("exhaustive_oracle requires a positive controlled size limit.")
        if self.oracle_state_limit is not None and self.oracle_state_limit <= 0:
            raise ValueError("oracle_state_limit must be positive.")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "m12d-method-policy-v1",
            "method_id": self.method_id.value,
            "search_strategy": self.search_strategy.value,
            "ranking_strategy": self.ranking_strategy.value,
            "use_gp_mean": self.use_gp_mean,
            "use_gp_uncertainty": self.use_gp_uncertainty,
            "confidence_pruning": self.confidence_pruning,
            "online_update": self.online_update,
            "apply_semantic_bound": self.apply_semantic_bound,
            "backend_id": self.backend_id,
            "controlled_only": self.controlled_only,
            "oracle_state_limit": self.oracle_state_limit,
            "seed": self.seed,
            "metadata": dict(self.metadata),
        }


def list_methods() -> tuple[str, ...]:
    return tuple(item.value for item in BaselineId)


def resolve_method_policy(
    baseline: BaselineConfig,
    ablations: AblationConfig,
    *,
    seed: int,
    options: Mapping[str, Any] | None = None,
) -> MethodPolicy:
    """Resolve one frozen method identifier and composable ablations."""

    options = dict(options or {})
    method = baseline.baseline_id
    policies = {
        BaselineId.FULL_XGAP: MethodPolicy(
            BaselineId.FULL_XGAP,
            SearchStrategy.BNB,
            RankingStrategy.NASH,
            True,
            True,
            True,
            True,
            True,
        ),
        BaselineId.RANDOM_FEASIBLE: MethodPolicy(
            BaselineId.RANDOM_FEASIBLE,
            SearchStrategy.RANDOM_FEASIBLE,
            RankingStrategy.COST_ONLY,
            False,
            False,
            False,
            True,
            True,
        ),
        BaselineId.MEAN_ONLY: MethodPolicy(
            BaselineId.MEAN_ONLY,
            SearchStrategy.BNB,
            RankingStrategy.NASH,
            True,
            False,
            False,
            True,
            True,
            metadata={
                "pruning_policy": "disabled_without_confidence_bounds",
                "confidence_theorem_claimed": False,
            },
        ),
        BaselineId.NO_PRUNING: MethodPolicy(
            BaselineId.NO_PRUNING,
            SearchStrategy.BNB,
            RankingStrategy.NASH,
            True,
            True,
            False,
            True,
            True,
        ),
        BaselineId.NO_ONLINE_UPDATE: MethodPolicy(
            BaselineId.NO_ONLINE_UPDATE,
            SearchStrategy.BNB,
            RankingStrategy.NASH,
            True,
            True,
            True,
            False,
            True,
        ),
        BaselineId.SINGLE_BACKEND: MethodPolicy(
            BaselineId.SINGLE_BACKEND,
            SearchStrategy.BNB,
            RankingStrategy.NASH,
            True,
            True,
            True,
            True,
            True,
            backend_id=baseline.backend_id or "not-selected",
        ),
        BaselineId.EXHAUSTIVE_ORACLE: MethodPolicy(
            BaselineId.EXHAUSTIVE_ORACLE,
            SearchStrategy.EXHAUSTIVE,
            RankingStrategy.TRUE_COST,
            False,
            False,
            False,
            False,
            True,
            controlled_only=True,
            oracle_state_limit=int(options.get("oracle_state_limit", 4096)),
        ),
        BaselineId.DIRECT_TEXT2GRAPHQUERY: MethodPolicy(
            BaselineId.DIRECT_TEXT2GRAPHQUERY,
            SearchStrategy.DIRECT,
            RankingStrategy.DIRECT,
            False,
            False,
            False,
            False,
            False,
            backend_id=baseline.backend_id or "not-selected",
        ),
    }
    policy = replace(policies[method], seed=seed)
    _validate_ablation_combination(policy, ablations, options)
    if ablations.no_uncertainty:
        policy = replace(
            policy,
            use_gp_uncertainty=False,
            confidence_pruning=False,
            metadata={
                **dict(policy.metadata),
                "confidence_theorem_claimed": False,
            },
        )
    if ablations.no_pruning:
        policy = replace(policy, confidence_pruning=False)
    if ablations.no_online_learning:
        policy = replace(policy, online_update=False)
    if ablations.no_semantic_bound:
        policy = replace(policy, apply_semantic_bound=False)
    if ablations.cost_only:
        policy = replace(policy, ranking_strategy=RankingStrategy.COST_ONLY)
    if ablations.no_nash:
        policy = replace(policy, ranking_strategy=RankingStrategy.SEMANTIC_THEN_COST)
    return policy


def _validate_ablation_combination(
    policy: MethodPolicy,
    ablations: AblationConfig,
    options: Mapping[str, Any],
) -> None:
    if policy.search_strategy in {SearchStrategy.RANDOM_FEASIBLE, SearchStrategy.DIRECT}:
        if ablations.enabled:
            raise ValueError(
                f"Planner ablations cannot be applied to {policy.method_id.value}."
            )
    if policy.method_id is BaselineId.MEAN_ONLY and ablations.no_uncertainty:
        raise ValueError("mean_only already disables uncertainty influence.")
    if ablations.cost_only and ablations.no_nash:
        raise ValueError("cost_only and no_nash select contradictory ranking policies.")
    if ablations.no_nash and options.get("no_nash_ranking") != "semantic_then_cost":
        raise ValueError(
            "no_nash requires method_options.no_nash_ranking='semantic_then_cost'."
        )


class RegistryCostEstimator:
    """Route one physical state to its backend-local frozen GP snapshot."""

    def __init__(
        self,
        registry: BackendCostModelRegistry,
        *,
        use_uncertainty: bool = True,
    ) -> None:
        self.registry = registry
        self.use_uncertainty = use_uncertainty
        self.estimator_id = "m12d-backend-local-registry"
        self.model_version = "m12d-registry-snapshot-v1"

    def predict(
        self,
        state: PhysicalState,
        confidence_context: ConfidenceContext,
    ) -> CostPrediction:
        placed = state.selected_backend_ids
        backend_ids = placed or self.registry.list_backends()
        predictions = tuple(
            (backend_id, self.registry.get(backend_id).predict(state, confidence_context))
            for backend_id in backend_ids
        )
        if len(placed) > 1:
            raw_means = tuple(math.exp(item.mu) for _, item in predictions)
            first = predictions[0][1]
            raw_mean = sum(raw_means)
            return CostPrediction(
                mu=math.log(raw_mean),
                sigma=(
                    math.sqrt(sum(item.sigma**2 for _, item in predictions))
                    if self.use_uncertainty
                    else 0.0
                ),
                lower=(
                    sum(item.lower for _, item in predictions)
                    if self.use_uncertainty
                    else raw_mean
                ),
                upper=(
                    sum(item.upper for _, item in predictions)
                    if self.use_uncertainty
                    else raw_mean
                ),
                beta=(
                    max(item.beta for _, item in predictions)
                    if self.use_uncertainty
                    else 0.0
                ),
                estimator_id=self.estimator_id,
                model_version=self.model_version,
                feature_ref=first.feature_ref,
                feature_vector=first.feature_vector,
                metadata={
                    "backend_candidates": list(backend_ids),
                    "partial_backend_local_sum": True,
                    "cross_backend_movement_cost": "not_available",
                    "uncertainty_used": self.use_uncertainty,
                },
            )
        prediction = min(
            predictions,
            key=lambda item: (
                item[1].lower if self.use_uncertainty else math.exp(item[1].mu),
                item[0],
            ),
        )[1]
        if self.use_uncertainty:
            return replace(
                prediction,
                estimator_id=self.estimator_id,
                model_version=self.model_version,
                metadata={
                    **dict(prediction.metadata),
                    "backend_candidates": list(backend_ids),
                    "uncertainty_used": True,
                },
            )
        point = math.exp(max(-700.0, min(700.0, prediction.mu)))
        return replace(
            prediction,
            lower=point,
            upper=point,
            beta=0.0,
            estimator_id=self.estimator_id,
            model_version=self.model_version,
            metadata={
                **dict(prediction.metadata),
                "backend_candidates": list(backend_ids),
                "uncertainty_used": False,
                "confidence_theorem_claimed": False,
            },
        )


def seeded_choice(items: Sequence[Any], *, seed: int, decision_key: str) -> Any:
    if not items:
        raise ValueError("seeded_choice requires at least one item.")
    randomizer = random.Random(f"{seed}:{decision_key}")
    return items[randomizer.randrange(len(items))]
