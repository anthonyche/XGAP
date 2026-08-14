"""M12-C backend-local execution measurement and RBF GP calibration."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from xgap.backends.protocol import BackendClient
from xgap.experiments.calibration_contracts import (
    CalibratedGPModelArtifact,
    CalibrationPlanRecord,
    CalibrationStatus,
    D0Record,
    ExecutionMeasurement,
)
from xgap.experiments.contracts import ExecutionProtocol
from xgap.experiments.hashing import content_hash
from xgap.infrastructure.runtime import ExecutionReport
from xgap.planning import (
    ExecutionObservation,
    GaussianProcessConfig,
    GaussianProcessCostEstimator,
    PhysicalPlan,
    gaussian_process_negative_log_marginal_likelihood,
    make_execution_observation,
)
from xgap.planning.protocols import StateFeatureExtractor


@dataclass(frozen=True)
class MeasurementBatch:
    measurements: tuple[ExecutionMeasurement, ...]
    status: CalibrationStatus
    aggregated_cost_ms: float | None
    successful_latencies_ms: tuple[float, ...]
    representative_rows: tuple[Mapping[str, object], ...] = ()
    row_counts: tuple[int, ...] = ()


def deterministic_stratified_sample(
    plans: Sequence[CalibrationPlanRecord],
    *,
    sample_count: int,
    seed: int,
) -> tuple[CalibrationPlanRecord, ...]:
    """Round-robin deterministic strata after seeded content ordering."""

    eligible = tuple(item for item in plans if item.status is CalibrationStatus.SUCCESS)
    if sample_count <= 0:
        raise ValueError("Calibration sample_count must be positive.")
    if len(eligible) < sample_count:
        raise ValueError(
            f"Calibration requested {sample_count} plans but only {len(eligible)} are eligible."
        )
    strata: dict[str, list[CalibrationPlanRecord]] = {}
    for item in eligible:
        strata.setdefault(item.stratum, []).append(item)
    for stratum, records in strata.items():
        records.sort(
            key=lambda item: content_hash(
                {
                    "seed": seed,
                    "stratum": stratum,
                    "physical_plan_id": item.physical_plan_id,
                }
            )
        )
    stratum_order = sorted(
        strata,
        key=lambda stratum: content_hash({"seed": seed, "stratum": stratum}),
    )
    selected: list[CalibrationPlanRecord] = []
    depth = 0
    while len(selected) < sample_count:
        added = False
        for stratum in stratum_order:
            records = strata[stratum]
            if depth < len(records):
                selected.append(records[depth])
                added = True
                if len(selected) == sample_count:
                    break
        if not added:
            break
        depth += 1
    return tuple(selected)


def aggregate_latencies(values: Sequence[float], statistic: str) -> float:
    latencies = tuple(float(value) for value in values)
    if not latencies or any(not math.isfinite(value) or value <= 0 for value in latencies):
        raise ValueError("Latency aggregation requires finite positive measurements.")
    if statistic == "median":
        return float(statistics.median(latencies))
    if statistic == "mean":
        return float(statistics.mean(latencies))
    if statistic == "min":
        return min(latencies)
    raise ValueError(f"Unsupported latency aggregation statistic '{statistic}'.")


def _report_status(report: ExecutionReport) -> CalibrationStatus:
    if report.success:
        if report.elapsed_ms is None or not math.isfinite(float(report.elapsed_ms)):
            return CalibrationStatus.NONPOSITIVE_COST
        if float(report.elapsed_ms) <= 0:
            return CalibrationStatus.NONPOSITIVE_COST
        return CalibrationStatus.SUCCESS
    message = (report.error or "").lower()
    if "timed out" in message or "timeout" in message:
        return CalibrationStatus.TIMEOUT
    return CalibrationStatus.BACKEND_ERROR


def measure_complete_plan(
    *,
    calibration_id: str,
    query_id: str,
    plan: PhysicalPlan,
    backend_id: str,
    client: BackendClient,
    protocol: ExecutionProtocol,
    feature_extractor: StateFeatureExtractor,
    measurement_protocol_hash: str,
    machine_metadata: Mapping[str, object],
    backend_metadata: Mapping[str, object],
    start_order: int = 0,
) -> MeasurementBatch:
    if not plan.state.is_complete:
        raise ValueError("Calibration measurement requires a complete physical plan.")
    placement_backends = {item.backend_id for item in plan.state.placements}
    if placement_backends != {backend_id} or plan.state.exchanges:
        return _unavailable_batch(
            calibration_id=calibration_id,
            query_id=query_id,
            plan=plan,
            backend_id=backend_id,
            protocol=protocol,
            feature_extractor=feature_extractor,
            measurement_protocol_hash=measurement_protocol_hash,
            machine_metadata=machine_metadata,
            backend_metadata=backend_metadata,
            order=start_order,
            status=CalibrationStatus.CROSS_BACKEND_MEASUREMENT_UNAVAILABLE,
            reason="M12-C does not measure distributed cross-backend movement.",
        )
    compilation = plan.realization.compilation
    if not compilation.executable or len(compilation.artifacts) != 1:
        raise ValueError("Calibration measurement requires one executable query artifact.")
    artifact = compilation.artifacts[0]
    feature = feature_extractor.features(plan.state)
    records: list[ExecutionMeasurement] = []
    successful: list[float] = []
    row_counts: list[int] = []
    representative_rows: tuple[Mapping[str, object], ...] = ()
    order = start_order

    def execute_phase(phase: str, repetition_index: int) -> None:
        nonlocal order, representative_rows
        report = client.execute(artifact)
        status = _report_status(report)
        if report.backend_id != backend_id:
            status = CalibrationStatus.BACKEND_ERROR
            error = (
                f"Execution report backend '{report.backend_id}' does not match "
                f"calibration backend '{backend_id}'."
            )
        else:
            error = report.error
        raw_latency = (
            float(report.elapsed_ms)
            if status is CalibrationStatus.SUCCESS and report.elapsed_ms is not None
            else None
        )
        if phase == "measured" and raw_latency is not None:
            successful.append(raw_latency)
            row_counts.append(report.row_count)
            representative_rows = tuple(dict(item) for item in report.rows)
        records.append(
            ExecutionMeasurement(
                calibration_id=calibration_id,
                query_id=query_id,
                interpretation_id=plan.interpretation_id,
                physical_plan_id=plan.plan_id,
                state_id=plan.state.state_id,
                backend_id=backend_id,
                artifact_id=artifact.artifact_id,
                phase=phase,
                repetition_index=repetition_index,
                order=order,
                status=status,
                raw_latency_ms=raw_latency,
                aggregated_execution_cost_ms=None,
                aggregation_statistic=protocol.aggregation_statistic,
                warmup_runs=protocol.warmup_runs,
                measured_repetitions=protocol.measured_repetitions,
                feature_ref=feature.feature_ref,
                feature_schema_hash=feature.schema_hash,
                measurement_protocol_hash=measurement_protocol_hash,
                row_count=report.row_count,
                result_status=report.result_status,
                started_at=report.started_at,
                ended_at=report.ended_at,
                error=error,
                backend_metadata={**dict(backend_metadata), **dict(report.metadata)},
                machine_metadata=machine_metadata,
            )
        )
        order += 1

    for repetition in range(1, protocol.warmup_runs + 1):
        execute_phase("warmup", repetition)
    for repetition in range(1, protocol.measured_repetitions + 1):
        execute_phase("measured", repetition)

    if len(successful) == protocol.measured_repetitions:
        aggregate = aggregate_latencies(successful, protocol.aggregation_statistic)
        batch_status = CalibrationStatus.SUCCESS
        reason = None
    else:
        aggregate = None
        batch_status = CalibrationStatus.INSUFFICIENT_REPETITIONS
        reason = (
            f"Expected {protocol.measured_repetitions} successful measured repetitions, "
            f"received {len(successful)}."
        )
    records.append(
        ExecutionMeasurement(
            calibration_id=calibration_id,
            query_id=query_id,
            interpretation_id=plan.interpretation_id,
            physical_plan_id=plan.plan_id,
            state_id=plan.state.state_id,
            backend_id=backend_id,
            artifact_id=artifact.artifact_id,
            phase="aggregate",
            repetition_index=None,
            order=order,
            status=batch_status,
            raw_latency_ms=None,
            aggregated_execution_cost_ms=aggregate,
            aggregation_statistic=protocol.aggregation_statistic,
            warmup_runs=protocol.warmup_runs,
            measured_repetitions=protocol.measured_repetitions,
            feature_ref=feature.feature_ref,
            feature_schema_hash=feature.schema_hash,
            measurement_protocol_hash=measurement_protocol_hash,
            row_count=(
                records[-1].row_count
                if records and len({item.row_count for item in records if item.phase == "measured"}) <= 1
                else None
            ),
            result_status=(
                "execution_success_nonempty"
                if records and any(item.row_count for item in records if item.phase == "measured")
                else "execution_success_empty"
                if records and all(
                    item.result_status == "execution_success_empty"
                    for item in records
                    if item.phase == "measured"
                )
                else "execution_error"
            ),
            ended_at=next((item.ended_at for item in reversed(records) if item.ended_at), None),
            error=reason,
            backend_metadata=backend_metadata,
            machine_metadata=machine_metadata,
        )
    )
    return MeasurementBatch(
        tuple(records),
        batch_status,
        aggregate,
        tuple(successful),
        representative_rows,
        tuple(row_counts),
    )


def backend_unavailable_batch(
    *,
    calibration_id: str,
    query_id: str,
    plan: PhysicalPlan,
    backend_id: str,
    protocol: ExecutionProtocol,
    feature_extractor: StateFeatureExtractor,
    measurement_protocol_hash: str,
    machine_metadata: Mapping[str, object],
    backend_metadata: Mapping[str, object],
    order: int,
    reason: str,
) -> MeasurementBatch:
    return _unavailable_batch(
        calibration_id=calibration_id,
        query_id=query_id,
        plan=plan,
        backend_id=backend_id,
        protocol=protocol,
        feature_extractor=feature_extractor,
        measurement_protocol_hash=measurement_protocol_hash,
        machine_metadata=machine_metadata,
        backend_metadata=backend_metadata,
        order=order,
        status=CalibrationStatus.BACKEND_UNAVAILABLE,
        reason=reason,
    )


def _unavailable_batch(
    *,
    calibration_id: str,
    query_id: str,
    plan: PhysicalPlan,
    backend_id: str,
    protocol: ExecutionProtocol,
    feature_extractor: StateFeatureExtractor,
    measurement_protocol_hash: str,
    machine_metadata: Mapping[str, object],
    backend_metadata: Mapping[str, object],
    order: int,
    status: CalibrationStatus,
    reason: str,
) -> MeasurementBatch:
    feature = feature_extractor.features(plan.state)
    artifact_id = (
        plan.realization.compilation.artifacts[0].artifact_id
        if plan.realization.compilation.artifacts
        else "not_available"
    )
    record = ExecutionMeasurement(
        calibration_id=calibration_id,
        query_id=query_id,
        interpretation_id=plan.interpretation_id,
        physical_plan_id=plan.plan_id,
        state_id=plan.state.state_id,
        backend_id=backend_id,
        artifact_id=artifact_id,
        phase="aggregate",
        repetition_index=None,
        order=order,
        status=status,
        raw_latency_ms=None,
        aggregated_execution_cost_ms=None,
        aggregation_statistic=protocol.aggregation_statistic,
        warmup_runs=protocol.warmup_runs,
        measured_repetitions=protocol.measured_repetitions,
        feature_ref=feature.feature_ref,
        feature_schema_hash=feature.schema_hash,
        measurement_protocol_hash=measurement_protocol_hash,
        row_count=None,
        result_status="execution_error",
        error=reason,
        backend_metadata=backend_metadata,
        machine_metadata=machine_metadata,
    )
    return MeasurementBatch((record,), status, None, ())


def make_d0_record(
    *,
    calibration_id: str,
    query_id: str,
    backend_id: str,
    split: str,
    plan: PhysicalPlan,
    feature_extractor: StateFeatureExtractor,
    batch: MeasurementBatch,
    aggregation_statistic: str,
    measurement_protocol_hash: str,
    sequence: int,
    measurement_source: str = "real_backend",
) -> D0Record:
    if batch.status is not CalibrationStatus.SUCCESS or batch.aggregated_cost_ms is None:
        raise ValueError("D0 records require a successful complete measurement batch.")
    feature = feature_extractor.features(plan.state)
    measured = tuple(
        item
        for item in batch.measurements
        if item.phase == "measured" and item.status is CalibrationStatus.SUCCESS
    )
    observed_at = next(
        (item.ended_at for item in reversed(batch.measurements) if item.ended_at),
        "not_available",
    )
    observation = make_execution_observation(
        plan=plan,
        raw_cost=batch.aggregated_cost_ms,
        query_id=query_id,
        task_id=f"{calibration_id}-d0",
        alignment_ref=f"{calibration_id}:{split}",
        feature_vector=feature,
        estimator_version="m12c-d0-observation-v1",
        observed_at=observed_at,
        sequence=sequence,
        provenance={
            "backend_id": backend_id,
            "calibration_id": calibration_id,
            "split": split,
            "cost_unit": "milliseconds",
            "target": "log_execution_cost_ms",
            "aggregation_statistic": aggregation_statistic,
            "measurement_protocol_hash": measurement_protocol_hash,
            "measurement_ids": [item.measurement_id for item in measured],
        },
    )
    return D0Record(
        calibration_id=calibration_id,
        backend_id=backend_id,
        split=split,
        raw_execution_cost_ms=batch.aggregated_cost_ms,
        log_execution_cost=math.log(batch.aggregated_cost_ms),
        repetition_latencies_ms=batch.successful_latencies_ms,
        aggregation_statistic=aggregation_statistic,
        measurement_protocol_hash=measurement_protocol_hash,
        measurement_ids=tuple(item.measurement_id for item in measured),
        observation=observation,
        provenance={"source": measurement_source},
    )


def _sample_variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = statistics.mean(values)
    return sum((value - average) ** 2 for value in values) / (len(values) - 1)


def fit_backend_gp(
    *,
    backend_id: str,
    d0_records: Sequence[D0Record],
    initial_config: GaussianProcessConfig,
    feature_extractor: StateFeatureExtractor,
    execution_protocol_hash: str,
    backend_descriptor_hash: str,
    random_seed: int,
) -> tuple[GaussianProcessCostEstimator, CalibratedGPModelArtifact]:
    records = tuple(d0_records)
    if not records:
        raise ValueError("Backend GP calibration requires non-empty D0.")
    if {item.backend_id for item in records} != {backend_id}:
        raise ValueError("Backend GP calibration cannot mix backend observations.")
    observations = tuple(item.observation for item in records)
    schema_hashes = {item.feature_vector.schema_hash for item in observations}
    expected_schema_hash = getattr(feature_extractor, "schema_hash", None)
    if schema_hashes != {expected_schema_hash}:
        raise ValueError("Calibration feature schema does not match the configured extractor.")

    log_costs = tuple(item.log_cost for item in observations)
    prior_log_cost = statistics.mean(log_costs)
    repeated_log_variances = tuple(
        _sample_variance(tuple(math.log(value) for value in item.repetition_latencies_ms))
        for item in records
        if len(item.repetition_latencies_ms) >= 2
    )
    noise_floor = max(1e-6, initial_config.noise_variance * 0.01)
    estimated_noise = max(
        noise_floor,
        statistics.mean(repeated_log_variances) if repeated_log_variances else noise_floor,
    )
    target_variance = _sample_variance(log_costs)
    signal_center = max(target_variance, initial_config.signal_variance * 0.1, 1e-4)

    lengths = _positive_candidates(
        initial_config.length_scale,
        initial_config.length_scale * 0.5,
        initial_config.length_scale * 2.0,
    )
    signals = _positive_candidates(
        initial_config.signal_variance,
        signal_center,
        signal_center * 0.5,
        signal_center * 2.0,
    )
    noises = _positive_candidates(
        initial_config.noise_variance,
        estimated_noise,
        estimated_noise * 0.5,
        estimated_noise * 2.0,
    )

    candidates: list[tuple[float, float, float, float, GaussianProcessConfig]] = []
    for length_scale in lengths:
        for signal_variance in signals:
            for noise_variance in noises:
                config = GaussianProcessConfig(
                    estimator_id=f"m12c-{backend_id}-rbf-gp",
                    model_version=f"m12c-{backend_id}-calibrated-v1",
                    length_scale=length_scale,
                    signal_variance=signal_variance,
                    noise_variance=noise_variance,
                    jitter=initial_config.jitter,
                    prior_log_cost=prior_log_cost,
                )
                objective = gaussian_process_negative_log_marginal_likelihood(
                    config, observations
                )
                candidates.append(
                    (objective, length_scale, signal_variance, noise_variance, config)
                )
    objective, _, _, _, fitted = min(candidates, key=lambda item: item[:4])
    estimator = GaussianProcessCostEstimator(
        config=fitted,
        feature_extractor=feature_extractor,
        observations=observations,
    )
    d0_hash = content_hash([item.to_hash_dict() for item in sorted(records, key=lambda x: x.d0_record_id)])
    artifact = CalibratedGPModelArtifact(
        backend_id=backend_id,
        config=fitted,
        d0_hash=d0_hash,
        observation_ids=tuple(item.observation_id for item in observations),
        feature_schema_hash=next(iter(schema_hashes)),
        execution_protocol_hash=execution_protocol_hash,
        backend_descriptor_hash=backend_descriptor_hash,
        fitting_objective="negative_log_marginal_likelihood",
        fitting_method="deterministic_bounded_grid_v1",
        objective_value=objective,
        initialization=initial_config.to_dict(),
        random_seed=random_seed,
        feature_normalization={
            "method": "none",
            "frozen_during_evaluation": True,
            "missing_value_representation": "value_zero_plus_presence_bit",
        },
        noise_handling={
            "execution_noise_variance": estimated_noise,
            "fitted_observation_noise_variance": fitted.noise_variance,
            "noise_floor": noise_floor,
            "source": "repeated_log_latency_variance_with_positive_floor",
            "predictive_uncertainty": "posterior_rbf_gp_variance",
        },
    )
    return estimator, artifact


def _positive_candidates(*values: float) -> tuple[float, ...]:
    return tuple(sorted({float(value) for value in values if math.isfinite(value) and value > 0}))


def observation_backend_id(observation: ExecutionObservation) -> str:
    backends = {item.backend_id for item in observation.placements}
    if len(backends) != 1 or observation.exchanges:
        raise ValueError(
            CalibrationStatus.CROSS_BACKEND_MEASUREMENT_UNAVAILABLE.value
        )
    return next(iter(backends))


class BackendCostModelRegistry:
    """Immutable mapping from backend IDs to frozen GP posterior snapshots."""

    def __init__(
        self,
        models: Mapping[str, GaussianProcessCostEstimator],
        hyperparameter_hashes: Mapping[str, str],
    ) -> None:
        if not models or set(models) != set(hyperparameter_hashes):
            raise ValueError("Cost model registry requires matching non-empty model/hash maps.")
        self._models = dict(models)
        self._hyperparameter_hashes = dict(hyperparameter_hashes)

    @classmethod
    def from_calibration(
        cls,
        *,
        model_artifacts: Mapping[str, CalibratedGPModelArtifact],
        d0_records: Mapping[str, Sequence[D0Record]],
        feature_extractors: Mapping[str, StateFeatureExtractor],
    ) -> "BackendCostModelRegistry":
        if not model_artifacts or set(model_artifacts) != set(d0_records) or set(model_artifacts) != set(feature_extractors):
            raise ValueError("Calibrated registry inputs must define identical backend IDs.")
        models: dict[str, GaussianProcessCostEstimator] = {}
        hashes: dict[str, str] = {}
        for backend_id, artifact in model_artifacts.items():
            records = tuple(d0_records[backend_id])
            if {item.backend_id for item in records} != {backend_id}:
                raise ValueError("Calibrated registry cannot mix backend-local D0 records.")
            observations = tuple(item.observation for item in records)
            if tuple(item.observation_id for item in observations) != artifact.observation_ids:
                raise ValueError("Calibrated model observation IDs do not match D0.")
            models[backend_id] = GaussianProcessCostEstimator(
                config=artifact.config,
                feature_extractor=feature_extractors[backend_id],
                observations=observations,
            )
            hashes[backend_id] = artifact.hyperparameter_hash
        return cls(models, hashes)

    def get(self, backend_id: str) -> GaussianProcessCostEstimator:
        try:
            return self._models[backend_id]
        except KeyError as error:
            raise KeyError(f"No calibrated cost model for backend '{backend_id}'.") from error

    def list_backends(self) -> tuple[str, ...]:
        return tuple(sorted(self._models))

    def hyperparameter_hash(self, backend_id: str) -> str:
        return self._hyperparameter_hashes[backend_id]

    def model_hash(self, backend_id: str) -> str:
        return content_hash(self.get(backend_id).to_dict())

    def with_observation_batch(
        self,
        observations: Iterable[ExecutionObservation],
    ) -> "BackendCostModelRegistry":
        batches: dict[str, list[ExecutionObservation]] = {}
        for observation in observations:
            backend_id = observation_backend_id(observation)
            if backend_id not in self._models:
                raise ValueError(f"No calibrated model for observation backend '{backend_id}'.")
            batches.setdefault(backend_id, []).append(observation)
        models = dict(self._models)
        for backend_id, batch in batches.items():
            current = models[backend_id]
            existing_ids = {item.observation_id for item in current.observations}
            new_ids = [item.observation_id for item in batch]
            if len(new_ids) != len(set(new_ids)) or existing_ids.intersection(new_ids):
                raise ValueError("Posterior update observation IDs must be new and unique.")
            models[backend_id] = current.with_observations((*current.observations, *batch))
        return BackendCostModelRegistry(models, self._hyperparameter_hashes)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "m12c-backend-cost-model-registry-v1",
            "backends": {
                backend_id: {
                    "model": self.get(backend_id).to_dict(),
                    "model_hash": self.model_hash(backend_id),
                    "hyperparameter_hash": self.hyperparameter_hash(backend_id),
                    "hyperparameters_frozen": True,
                }
                for backend_id in self.list_backends()
            },
        }
