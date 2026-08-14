"""Versioned observations and a small deterministic Gaussian-process estimator."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from xgap.backends.capabilities import BackendCapabilityProfile, SupportLevel
from xgap.backends.compatibility import check_backend_support
from xgap.planning.contracts import (
    ConfidenceContext,
    CostPrediction,
    ExecutionObservation,
    FeatureVector,
    JsonMap,
    PhysicalPlan,
    PhysicalState,
    canonical_json,
    content_id,
)
from xgap.planning.protocols import StateFeatureExtractor
from xgap.planning.search import ExchangeCatalog


OBSERVATION_STORE_VERSION = "m11-execution-observations-v1"


@dataclass(frozen=True)
class GaussianProcessConfig:
    estimator_id: str = "m11-gaussian-process"
    model_version: str = "m11-gp-v1"
    length_scale: float = 3.0
    signal_variance: float = 1.0
    noise_variance: float = 0.01
    jitter: float = 1e-9
    prior_log_cost: float = math.log(10.0)

    def __post_init__(self) -> None:
        values = (
            self.length_scale,
            self.signal_variance,
            self.noise_variance,
            self.jitter,
            self.prior_log_cost,
        )
        if not all(math.isfinite(item) for item in values):
            raise ValueError("GaussianProcessConfig values must be finite.")
        if self.length_scale <= 0 or self.signal_variance <= 0:
            raise ValueError("length_scale and signal_variance must be positive.")
        if self.noise_variance < 0 or self.jitter <= 0:
            raise ValueError("noise_variance must be nonnegative and jitter positive.")

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "GaussianProcessConfig":
        return cls(
            estimator_id=str(data.get("estimator_id", "m11-gaussian-process")),
            model_version=str(data.get("model_version", "m11-gp-v1")),
            length_scale=float(data.get("length_scale", 3.0)),
            signal_variance=float(data.get("signal_variance", 1.0)),
            noise_variance=float(data.get("noise_variance", 0.01)),
            jitter=float(data.get("jitter", 1e-9)),
            prior_log_cost=float(data.get("prior_log_cost", math.log(10.0))),
        )

    def to_dict(self) -> JsonMap:
        return {
            "estimator_id": self.estimator_id,
            "model_version": self.model_version,
            "length_scale": self.length_scale,
            "signal_variance": self.signal_variance,
            "noise_variance": self.noise_variance,
            "jitter": self.jitter,
            "prior_log_cost": self.prior_log_cost,
        }


class ExecutionObservationStore:
    """Append-only JSONL store; snapshots are immutable tuples."""

    def __init__(
        self,
        path: str | Path,
        *,
        store_version: str = OBSERVATION_STORE_VERSION,
    ) -> None:
        self.path = Path(path)
        self.store_version = store_version

    def load(self) -> tuple[ExecutionObservation, ...]:
        if not self.path.exists():
            return ()
        observations: list[ExecutionObservation] = []
        seen: set[str] = set()
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, Mapping):
                raise ValueError(f"Observation line {line_number} must be a JSON object.")
            observation = ExecutionObservation.from_dict(data)
            if observation.store_version != self.store_version:
                raise ValueError(
                    f"Observation line {line_number} uses store version "
                    f"'{observation.store_version}', expected '{self.store_version}'."
                )
            if observation.observation_id in seen:
                raise ValueError(f"Duplicate observation_id '{observation.observation_id}'.")
            seen.add(observation.observation_id)
            observations.append(observation)
        return tuple(observations)

    def append(self, observation: ExecutionObservation) -> None:
        if observation.store_version != self.store_version:
            raise ValueError("Observation store version mismatch.")
        existing = self.load()
        if observation.observation_id in {item.observation_id for item in existing}:
            raise ValueError(f"Duplicate observation_id '{observation.observation_id}'.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(observation.to_dict()) + "\n")

    def snapshot(self) -> tuple[ExecutionObservation, ...]:
        return self.load()

    def to_dict(self) -> JsonMap:
        return {
            "store_version": self.store_version,
            "path": str(self.path),
            "observation_count": len(self.load()),
        }


def make_execution_observation(
    *,
    plan: PhysicalPlan,
    raw_cost: float,
    query_id: str,
    task_id: str,
    alignment_ref: str,
    feature_vector: FeatureVector,
    estimator_version: str,
    observed_at: str,
    sequence: int,
    provenance: Mapping[str, object] | None = None,
) -> ExecutionObservation:
    if not plan.state.is_complete:
        raise ValueError("Execution observations require a complete plan.")
    raw = float(raw_cost)
    if not math.isfinite(raw) or raw <= 0:
        raise ValueError("Observed execution cost must be finite and positive.")
    identity = {
        "task_id": task_id,
        "query_id": query_id,
        "interpretation_id": plan.interpretation_id,
        "physical_plan_id": plan.plan_id,
        "sequence": sequence,
        "raw_cost": raw,
    }
    return ExecutionObservation(
        store_version=OBSERVATION_STORE_VERSION,
        observation_id=content_id("observation", identity),
        task_id=task_id,
        query_id=query_id,
        interpretation_id=plan.interpretation_id,
        physical_plan_id=plan.plan_id,
        state_id=plan.state.state_id,
        raw_cost=raw,
        log_cost=math.log(raw),
        alignment_ref=alignment_ref,
        placements=plan.state.placements,
        exchanges=plan.state.exchanges,
        feature_vector=feature_vector,
        estimator_version=estimator_version,
        observed_at=observed_at,
        sequence=sequence,
        complete=True,
        provenance=dict(provenance or {}),
    )


def confidence_beta(state_space_bound: int, delta: float) -> float:
    if state_space_bound <= 0:
        raise ValueError("state_space_bound must be positive.")
    if not 0 < delta < 1:
        raise ValueError("delta must be strictly between zero and one.")
    return 2.0 * math.log((2.0 * state_space_bound) / delta)


def across_task_delta(global_delta: float, task_index: int, interpretation_count: int) -> float:
    if not 0 < global_delta < 1:
        raise ValueError("global_delta must be strictly between zero and one.")
    if task_index <= 0 or interpretation_count <= 0:
        raise ValueError("task_index and interpretation_count must be positive.")
    return (6.0 * global_delta) / (
        math.pi**2 * task_index**2 * interpretation_count
    )


def across_task_confidence_context(
    *,
    global_delta: float,
    task_index: int,
    interpretation_count: int,
    state_space_bound: int,
) -> ConfidenceContext:
    return ConfidenceContext(
        delta=across_task_delta(global_delta, task_index, interpretation_count),
        state_space_bound=state_space_bound,
        task_index=task_index,
        interpretation_count=interpretation_count,
    )


@dataclass(frozen=True)
class StateSpaceBound:
    value: int
    placement_choice_counts: tuple[tuple[str, int], ...]
    exchange_choice_bounds: tuple[tuple[str, int], ...]

    def to_dict(self) -> JsonMap:
        return {
            "value": self.value,
            "placement_choice_counts": [
                {"operator_id": operator_id, "count": count}
                for operator_id, count in self.placement_choice_counts
            ],
            "exchange_choice_bounds": [
                {"dependency_id": dependency_id, "count": count}
                for dependency_id, count in self.exchange_choice_bounds
            ],
        }


def conservative_state_space_bound(
    state: PhysicalState,
    backend_profiles: Sequence[BackendCapabilityProfile],
    exchange_catalog: ExchangeCatalog,
) -> StateSpaceBound:
    profiles = tuple(backend_profiles)
    placement_counts: list[tuple[str, int]] = []
    prefix_count = 1
    partial_total = 1
    for operator in state.operators:
        count = sum(
            check_backend_support(profile, operator.feature_id).level
            is not SupportLevel.UNSUPPORTED
            for profile in profiles
        )
        placement_counts.append((operator.operator_id, count))
        if count == 0:
            return StateSpaceBound(max(1, partial_total), tuple(placement_counts), ())
        prefix_count *= count
        partial_total += prefix_count

    exchange_counts: list[tuple[str, int]] = []
    exchange_multiplier = 1
    for dependency in state.dependencies:
        max_choices = 1
        for source in profiles:
            for target in profiles:
                if source.backend_id == target.backend_id:
                    choices = 1
                else:
                    choices = len(
                        exchange_catalog.matching(
                            source.backend_id,
                            target.backend_id,
                            dependency.result_kind,
                        )
                    )
                max_choices = max(max_choices, choices)
        exchange_counts.append((dependency.dependency_id, max_choices))
        exchange_multiplier *= max_choices
    return StateSpaceBound(
        value=max(1, partial_total * exchange_multiplier),
        placement_choice_counts=tuple(placement_counts),
        exchange_choice_bounds=tuple(exchange_counts),
    )


class GaussianProcessCostEstimator:
    """Immutable RBF GP snapshot over small M11 feature vectors.

    XGAP has no scientific-computing dependency. This implementation uses a
    jittered Cholesky factorization from the Python standard library and is
    intentionally scoped to the small controlled planning datasets in M11.
    """

    def __init__(
        self,
        *,
        config: GaussianProcessConfig,
        feature_extractor: StateFeatureExtractor,
        observations: Iterable[ExecutionObservation] = (),
    ) -> None:
        self.config = config
        self.feature_extractor = feature_extractor
        self.observations = tuple(observations)
        self.estimator_id = config.estimator_id
        self.model_version = config.model_version
        schema_hashes = {item.feature_vector.schema_hash for item in self.observations}
        if len(schema_hashes) > 1:
            raise ValueError("GP observations must use one feature schema.")
        self._observation_schema_hash = next(iter(schema_hashes), None)
        self._x = tuple(item.feature_vector.values for item in self.observations)
        self._y = tuple(item.log_cost for item in self.observations)
        self._cholesky: tuple[tuple[float, ...], ...] | None = None
        self._alpha: tuple[float, ...] | None = None
        if self.observations:
            matrix = [
                [self._kernel(left, right) for right in self._x]
                for left in self._x
            ]
            diagonal = config.noise_variance + config.jitter
            for index in range(len(matrix)):
                matrix[index][index] += diagonal
            cholesky = _cholesky(matrix)
            centered = [value - config.prior_log_cost for value in self._y]
            alpha = _solve_cholesky(cholesky, centered)
            self._cholesky = tuple(tuple(row) for row in cholesky)
            self._alpha = tuple(alpha)

    def predict(
        self,
        state: PhysicalState,
        confidence_context: ConfidenceContext,
    ) -> CostPrediction:
        feature_vector = self.feature_extractor.features(state)
        if (
            self._observation_schema_hash is not None
            and feature_vector.schema_hash != self._observation_schema_hash
        ):
            raise ValueError("Prediction feature schema does not match GP observations.")
        vector = feature_vector.values
        if not self.observations:
            mu = self.config.prior_log_cost
            variance = self.config.signal_variance
        else:
            assert self._cholesky is not None and self._alpha is not None
            covariance = [self._kernel(vector, train) for train in self._x]
            mu = self.config.prior_log_cost + sum(
                left * right for left, right in zip(covariance, self._alpha, strict=True)
            )
            solved = _forward_substitution(self._cholesky, covariance)
            variance = max(
                0.0,
                self._kernel(vector, vector) - sum(value * value for value in solved),
            )
        sigma = math.sqrt(variance)
        beta = confidence_beta(
            confidence_context.state_space_bound,
            confidence_context.delta,
        )
        radius = math.sqrt(beta) * sigma
        lower = math.exp(max(-700.0, mu - radius))
        upper = math.exp(min(700.0, mu + radius))
        return CostPrediction(
            mu=mu,
            sigma=sigma,
            lower=lower,
            upper=upper,
            beta=beta,
            estimator_id=self.estimator_id,
            model_version=self.model_version,
            feature_ref=feature_vector.feature_ref,
            feature_vector=feature_vector,
            metadata={"observation_count": len(self.observations)},
        )

    def with_observations(
        self,
        observations: Iterable[ExecutionObservation],
        *,
        model_version: str | None = None,
    ) -> "GaussianProcessCostEstimator":
        config = self.config
        if model_version is not None:
            config = GaussianProcessConfig(
                **{**config.to_dict(), "model_version": model_version}
            )
        return GaussianProcessCostEstimator(
            config=config,
            feature_extractor=self.feature_extractor,
            observations=tuple(observations),
        )

    def _kernel(self, left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            raise ValueError("GP feature vectors must have equal dimensions.")
        squared_distance = sum(
            ((left_value - right_value) / self.config.length_scale) ** 2
            for left_value, right_value in zip(left, right, strict=True)
        )
        return self.config.signal_variance * math.exp(-0.5 * squared_distance)

    def to_dict(self) -> JsonMap:
        return {
            "estimator_id": self.estimator_id,
            "model_version": self.model_version,
            "config": self.config.to_dict(),
            "feature_extractor_id": self.feature_extractor.extractor_id,
            "observation_ids": [item.observation_id for item in self.observations],
            "observation_count": len(self.observations),
            "observation_schema_hash": self._observation_schema_hash,
        }


def gaussian_process_negative_log_marginal_likelihood(
    config: GaussianProcessConfig,
    observations: Iterable[ExecutionObservation],
) -> float:
    """Return the exact RBF GP negative log marginal likelihood.

    M12-C uses this small-data objective to calibrate the existing M11 GP
    family. It does not alter prediction, confidence, or search semantics.
    """

    observed = tuple(observations)
    if not observed:
        raise ValueError("GP calibration requires at least one observation.")
    schema_hashes = {item.feature_vector.schema_hash for item in observed}
    if len(schema_hashes) != 1:
        raise ValueError("GP calibration observations must use one feature schema.")
    vectors = tuple(item.feature_vector.values for item in observed)

    def kernel(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            raise ValueError("GP feature vectors must have equal dimensions.")
        squared_distance = sum(
            ((left_value - right_value) / config.length_scale) ** 2
            for left_value, right_value in zip(left, right, strict=True)
        )
        return config.signal_variance * math.exp(-0.5 * squared_distance)

    matrix = [[kernel(left, right) for right in vectors] for left in vectors]
    diagonal = config.noise_variance + config.jitter
    for index in range(len(matrix)):
        matrix[index][index] += diagonal
    cholesky = _cholesky(matrix)
    centered = [item.log_cost - config.prior_log_cost for item in observed]
    alpha = _solve_cholesky(cholesky, centered)
    data_fit = 0.5 * sum(
        value * coefficient
        for value, coefficient in zip(centered, alpha, strict=True)
    )
    complexity = sum(math.log(cholesky[index][index]) for index in range(len(cholesky)))
    normalizer = 0.5 * len(observed) * math.log(2.0 * math.pi)
    return data_fit + complexity + normalizer


def _cholesky(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    size = len(matrix)
    if any(len(row) != size for row in matrix):
        raise ValueError("Cholesky matrix must be square.")
    result = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            subtotal = sum(
                result[row][index] * result[column][index]
                for index in range(column)
            )
            if row == column:
                diagonal = matrix[row][row] - subtotal
                if diagonal <= 0 or not math.isfinite(diagonal):
                    raise ValueError("GP covariance is not positive definite after jitter.")
                result[row][column] = math.sqrt(diagonal)
            else:
                result[row][column] = (matrix[row][column] - subtotal) / result[column][column]
    return result


def _forward_substitution(
    lower: Sequence[Sequence[float]],
    values: Sequence[float],
) -> list[float]:
    result: list[float] = []
    for row, value in enumerate(values):
        subtotal = sum(lower[row][column] * result[column] for column in range(row))
        result.append((value - subtotal) / lower[row][row])
    return result


def _back_substitution_transpose(
    lower: Sequence[Sequence[float]],
    values: Sequence[float],
) -> list[float]:
    size = len(values)
    result = [0.0] * size
    for row in range(size - 1, -1, -1):
        subtotal = sum(lower[column][row] * result[column] for column in range(row + 1, size))
        result[row] = (values[row] - subtotal) / lower[row][row]
    return result


def _solve_cholesky(
    lower: Sequence[Sequence[float]],
    values: Sequence[float],
) -> list[float]:
    return _back_substitution_transpose(
        lower,
        _forward_substitution(lower, values),
    )
