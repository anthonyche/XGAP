"""Typed M12-C calibration and measured-cost artifact contracts."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.contracts import ExecutionProtocol
from xgap.experiments.hashing import content_hash
from xgap.infrastructure.runtime import QueryArtifact
from xgap.planning import ExecutionObservation, FeatureVector, GaussianProcessConfig


class CalibrationStatus(str, Enum):
    SUCCESS = "success"
    COMPILE_UNSUPPORTED = "compile_unsupported"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BACKEND_ERROR = "backend_error"
    TIMEOUT = "timeout"
    NONPOSITIVE_COST = "nonpositive_cost"
    INSUFFICIENT_REPETITIONS = "insufficient_repetitions"
    FEATURE_ERROR = "feature_error"
    CALIBRATION_FIT_ERROR = "calibration_fit_error"
    MODEL_SERIALIZATION_ERROR = "model_serialization_error"
    ONLINE_UPDATE_ERROR = "online_update_error"
    CROSS_BACKEND_MEASUREMENT_UNAVAILABLE = "cross_backend_measurement_unavailable"


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Calibration field '{field_name}' must be a mapping.")
    return dict(value)


def _relative_path(value: str, field_name: str) -> str:
    if not value:
        raise ValueError(f"Calibration field '{field_name}' must be non-empty.")
    if Path(value).is_absolute():
        raise ValueError(f"Calibration field '{field_name}' must be repository-relative.")
    return value


@dataclass(frozen=True)
class CalibrationRunConfig:
    calibration_id: str
    run_id: str
    dataset_id: str
    dataset_version: str
    dataset_bundle_ref: str
    cases_artifact_ref: str
    descriptor_dir: str
    backend_ids: tuple[str, ...]
    calibration_split: str
    evaluation_split: str
    sampling_policy_id: str
    sample_count_per_backend: int
    random_seed: int
    execution_protocol: ExecutionProtocol
    feature_extractor_id: str
    feature_schema_version: str
    feature_schema_hash: str
    optional_stat_names: tuple[str, ...]
    initial_gp_config: GaussianProcessConfig
    output_root: str
    schema_version: str = "m12c-calibration-config-v1"

    def __post_init__(self) -> None:
        required = (
            self.calibration_id,
            self.run_id,
            self.dataset_id,
            self.dataset_version,
            self.calibration_split,
            self.evaluation_split,
            self.sampling_policy_id,
            self.feature_extractor_id,
            self.feature_schema_version,
            self.feature_schema_hash,
        )
        if not all(required):
            raise ValueError("M12-C calibration identifiers must be non-empty.")
        if self.calibration_split == self.evaluation_split:
            raise ValueError("Calibration and evaluation splits must be distinct.")
        if not self.backend_ids or len(set(self.backend_ids)) != len(self.backend_ids):
            raise ValueError("Calibration backend_ids must be non-empty and unique.")
        if self.sample_count_per_backend <= 0:
            raise ValueError("Calibration sample_count_per_backend must be positive.")
        if self.sampling_policy_id != "deterministic-stratified-v1":
            raise ValueError("M12-C supports deterministic-stratified-v1 sampling only.")
        for field_name, value in (
            ("dataset_bundle", self.dataset_bundle_ref),
            ("cases_artifact", self.cases_artifact_ref),
            ("descriptor_dir", self.descriptor_dir),
            ("output_root", self.output_root),
        ):
            _relative_path(value, field_name)
        object.__setattr__(self, "backend_ids", tuple(self.backend_ids))
        object.__setattr__(self, "optional_stat_names", tuple(self.optional_stat_names))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationRunConfig":
        dataset = _mapping(data.get("dataset"), "dataset")
        splits = _mapping(data.get("splits"), "splits")
        sampling = _mapping(data.get("sampling"), "sampling")
        feature = _mapping(data.get("feature_schema"), "feature_schema")
        cost_model = _mapping(data.get("cost_model"), "cost_model")
        if str(cost_model.get("type", "")) != "rbf_gaussian_process":
            raise ValueError("M12-C calibrates the existing RBF Gaussian-process family only.")
        return cls(
            schema_version=str(data.get("schema_version", "m12c-calibration-config-v1")),
            calibration_id=str(data.get("calibration_id", "")),
            run_id=str(data.get("run_id", "")),
            dataset_id=str(dataset.get("id", "")),
            dataset_version=str(dataset.get("version", "")),
            dataset_bundle_ref=str(dataset.get("bundle", "")),
            cases_artifact_ref=str(data.get("cases_artifact", "")),
            descriptor_dir=str(data.get("descriptor_dir", "descriptors/backends")),
            backend_ids=tuple(str(item) for item in data.get("backend_ids", ())),
            calibration_split=str(splits.get("calibration", "")),
            evaluation_split=str(splits.get("evaluation", "")),
            sampling_policy_id=str(sampling.get("policy_id", "")),
            sample_count_per_backend=int(sampling.get("sample_count_per_backend", 0)),
            random_seed=int(sampling.get("seed", 0)),
            execution_protocol=ExecutionProtocol.from_dict(
                _mapping(data.get("execution_protocol"), "execution_protocol")
            ),
            feature_extractor_id=str(feature.get("extractor_id", "")),
            feature_schema_version=str(feature.get("version", "")),
            feature_schema_hash=str(feature.get("schema_hash", "")),
            optional_stat_names=tuple(
                str(item) for item in feature.get("unavailable_statistics", ())
            ),
            initial_gp_config=GaussianProcessConfig.from_dict(
                _mapping(cost_model.get("initial_config"), "cost_model.initial_config")
            ),
            output_root=str(data.get("output_root", "")),
        )

    @classmethod
    def load(cls, path: str | Path) -> "CalibrationRunConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("Calibration config root must be an object.")
        return cls.from_dict(raw)

    def to_hash_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "calibration_id": self.calibration_id,
            "run_id": self.run_id,
            "dataset": {
                "id": self.dataset_id,
                "version": self.dataset_version,
                "bundle": self.dataset_bundle_ref,
            },
            "cases_artifact": self.cases_artifact_ref,
            "descriptor_dir": self.descriptor_dir,
            "backend_ids": list(self.backend_ids),
            "splits": {
                "calibration": self.calibration_split,
                "evaluation": self.evaluation_split,
            },
            "sampling": {
                "policy_id": self.sampling_policy_id,
                "sample_count_per_backend": self.sample_count_per_backend,
                "seed": self.random_seed,
            },
            "execution_protocol": self.execution_protocol.to_dict(),
            "feature_schema": {
                "extractor_id": self.feature_extractor_id,
                "version": self.feature_schema_version,
                "schema_hash": self.feature_schema_hash,
                "unavailable_statistics": list(self.optional_stat_names),
            },
            "cost_model": {
                "type": "rbf_gaussian_process",
                "initial_config": self.initial_gp_config.to_dict(),
                "backend_policy": "independent_backend_local",
            },
            "output_root": self.output_root,
        }

    @property
    def config_hash(self) -> str:
        return content_hash(self.to_hash_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_hash_dict(), "config_hash": self.config_hash}


_FORBIDDEN_CASE_KEYS = {
    "gold_answers",
    "gold_logical_form",
    "gold_alignment",
    "evaluation_label",
    "future_observations",
}


def _find_forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _FORBIDDEN_CASE_KEYS:
                found.add(str(key))
            found.update(_find_forbidden_keys(item))
    elif isinstance(value, list | tuple):
        for item in value:
            found.update(_find_forbidden_keys(item))
    return found


@dataclass(frozen=True)
class CalibrationCase:
    case_id: str
    query_id: str
    interpretation_id: str
    split: str
    stratum: str
    question: str
    pattern_query: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "m12c-calibration-case-v1"

    def __post_init__(self) -> None:
        if not all(
            (self.case_id, self.query_id, self.interpretation_id, self.split, self.stratum)
        ):
            raise ValueError("Calibration case identifiers must be non-empty.")
        forbidden = _find_forbidden_keys(
            {"pattern_query": self.pattern_query, "metadata": self.metadata}
        )
        if forbidden:
            raise ValueError(
                "Calibration cases must not contain evaluation-only fields: "
                + ", ".join(sorted(forbidden))
            )
        object.__setattr__(self, "pattern_query", dict(self.pattern_query))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationCase":
        forbidden = _find_forbidden_keys(data)
        if forbidden:
            raise ValueError(
                "Calibration cases must not contain evaluation-only fields: "
                + ", ".join(sorted(forbidden))
            )
        return cls(
            schema_version=str(data.get("schema_version", "m12c-calibration-case-v1")),
            case_id=str(data.get("case_id", "")),
            query_id=str(data.get("query_id", "")),
            interpretation_id=str(data.get("interpretation_id", "")),
            split=str(data.get("split", "")),
            stratum=str(data.get("stratum", "")),
            question=str(data.get("question", "")),
            pattern_query=_mapping(data.get("pattern_query"), "pattern_query"),
            metadata=_mapping(data.get("metadata", {}), "metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "query_id": self.query_id,
            "interpretation_id": self.interpretation_id,
            "split": self.split,
            "stratum": self.stratum,
            "question": self.question,
            "pattern_query": dict(self.pattern_query),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CalibrationPlanRecord:
    case_id: str
    query_id: str
    interpretation_id: str
    backend_id: str
    split: str
    stratum: str
    status: CalibrationStatus
    state_id: str | None = None
    physical_plan_id: str | None = None
    logical_plan_id: str | None = None
    operator_names: tuple[str, ...] = ()
    feature_vector: FeatureVector | None = None
    query_artifact: QueryArtifact | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_names", tuple(self.operator_names))
        if self.status is CalibrationStatus.SUCCESS:
            if not all((self.state_id, self.physical_plan_id, self.logical_plan_id)):
                raise ValueError("Successful calibration plans require complete identifiers.")
            if self.feature_vector is None or self.query_artifact is None:
                raise ValueError("Successful calibration plans require features and native artifacts.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "query_id": self.query_id,
            "interpretation_id": self.interpretation_id,
            "backend_id": self.backend_id,
            "split": self.split,
            "stratum": self.stratum,
            "status": self.status.value,
            "state_id": self.state_id,
            "physical_plan_id": self.physical_plan_id,
            "logical_plan_id": self.logical_plan_id,
            "operator_names": list(self.operator_names),
            "feature_vector": self.feature_vector.to_dict() if self.feature_vector else None,
            "query_artifact": self.query_artifact.to_dict() if self.query_artifact else None,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CalibrationWorkload:
    calibration_id: str
    dataset_id: str
    dataset_version: str
    backend_id: str
    calibration_split: str
    evaluation_split: str
    sampling_policy_id: str
    sample_count: int
    seed: int
    eligible_physical_plan_ids: tuple[str, ...]
    selected_physical_plan_ids: tuple[str, ...]
    execution_protocol_hash: str
    feature_schema_hash: str
    compiler_id: str
    backend_descriptor_hash: str
    schema_version: str = "m12c-calibration-workload-v1"

    def __post_init__(self) -> None:
        eligible = tuple(self.eligible_physical_plan_ids)
        selected = tuple(self.selected_physical_plan_ids)
        if not set(selected).issubset(set(eligible)):
            raise ValueError("Selected calibration plans must be eligible complete plans.")
        if len(selected) != self.sample_count:
            raise ValueError("Calibration workload selected count must match sample_count.")
        if self.calibration_split == self.evaluation_split:
            raise ValueError("Calibration workload cannot use the evaluation split.")
        object.__setattr__(self, "eligible_physical_plan_ids", eligible)
        object.__setattr__(self, "selected_physical_plan_ids", selected)

    def to_hash_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "calibration_id": self.calibration_id,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "backend_id": self.backend_id,
            "calibration_split": self.calibration_split,
            "evaluation_split": self.evaluation_split,
            "sampling_policy_id": self.sampling_policy_id,
            "sample_count": self.sample_count,
            "seed": self.seed,
            "eligible_physical_plan_ids": list(self.eligible_physical_plan_ids),
            "selected_physical_plan_ids": list(self.selected_physical_plan_ids),
            "execution_protocol_hash": self.execution_protocol_hash,
            "feature_schema_hash": self.feature_schema_hash,
            "compiler_id": self.compiler_id,
            "backend_descriptor_hash": self.backend_descriptor_hash,
        }

    @property
    def workload_hash(self) -> str:
        return content_hash(self.to_hash_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_hash_dict(), "workload_hash": self.workload_hash}


@dataclass(frozen=True)
class ExecutionMeasurement:
    calibration_id: str
    query_id: str
    interpretation_id: str
    physical_plan_id: str
    state_id: str
    backend_id: str
    artifact_id: str
    phase: str
    repetition_index: int | None
    order: int
    status: CalibrationStatus
    raw_latency_ms: float | None
    aggregated_execution_cost_ms: float | None
    aggregation_statistic: str
    warmup_runs: int
    measured_repetitions: int
    feature_ref: str
    feature_schema_hash: str
    measurement_protocol_hash: str
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    backend_metadata: Mapping[str, Any] = field(default_factory=dict)
    machine_metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "m12c-execution-measurement-v1"

    def __post_init__(self) -> None:
        if self.phase not in {"warmup", "measured", "aggregate"}:
            raise ValueError("Measurement phase must be warmup, measured, or aggregate.")
        if self.order < 0:
            raise ValueError("Measurement order must be nonnegative.")
        if self.raw_latency_ms is not None:
            if not math.isfinite(self.raw_latency_ms) or self.raw_latency_ms <= 0:
                raise ValueError("Measured latency must be finite and positive.")
        if self.aggregated_execution_cost_ms is not None:
            if (
                not math.isfinite(self.aggregated_execution_cost_ms)
                or self.aggregated_execution_cost_ms <= 0
            ):
                raise ValueError("Aggregated execution cost must be finite and positive.")
        object.__setattr__(self, "backend_metadata", dict(self.backend_metadata))
        object.__setattr__(self, "machine_metadata", dict(self.machine_metadata))

    @property
    def measurement_id(self) -> str:
        return "measurement-" + content_hash(
            {
                "calibration_id": self.calibration_id,
                "physical_plan_id": self.physical_plan_id,
                "backend_id": self.backend_id,
                "phase": self.phase,
                "repetition_index": self.repetition_index,
                "order": self.order,
                "raw_latency_ms": self.raw_latency_ms,
                "status": self.status.value,
                "protocol": self.measurement_protocol_hash,
            }
        )[:20]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "measurement_id": self.measurement_id,
            "calibration_id": self.calibration_id,
            "query_id": self.query_id,
            "interpretation_id": self.interpretation_id,
            "physical_plan_id": self.physical_plan_id,
            "state_id": self.state_id,
            "backend_id": self.backend_id,
            "artifact_id": self.artifact_id,
            "phase": self.phase,
            "repetition_index": self.repetition_index,
            "order": self.order,
            "status": self.status.value,
            "raw_latency_ms": self.raw_latency_ms,
            "aggregated_execution_cost_ms": self.aggregated_execution_cost_ms,
            "aggregation_statistic": self.aggregation_statistic,
            "warmup_runs": self.warmup_runs,
            "measured_repetitions": self.measured_repetitions,
            "feature_ref": self.feature_ref,
            "feature_schema_hash": self.feature_schema_hash,
            "measurement_protocol_hash": self.measurement_protocol_hash,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "backend_metadata": dict(self.backend_metadata),
            "machine_metadata": dict(self.machine_metadata),
        }


@dataclass(frozen=True)
class D0Record:
    calibration_id: str
    backend_id: str
    split: str
    raw_execution_cost_ms: float
    log_execution_cost: float
    repetition_latencies_ms: tuple[float, ...]
    aggregation_statistic: str
    measurement_protocol_hash: str
    measurement_ids: tuple[str, ...]
    observation: ExecutionObservation
    provenance: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "m12c-d0-record-v1"

    def __post_init__(self) -> None:
        if self.raw_execution_cost_ms <= 0 or not math.isfinite(self.raw_execution_cost_ms):
            raise ValueError("D0 raw execution cost must be finite and positive.")
        if not math.isclose(
            self.log_execution_cost,
            math.log(self.raw_execution_cost_ms),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("D0 log cost must equal log(raw_execution_cost_ms).")
        if not self.observation.complete:
            raise ValueError("D0 accepts complete-plan observations only.")
        observed_backends = {item.backend_id for item in self.observation.placements}
        if observed_backends != {self.backend_id} or self.observation.exchanges:
            raise ValueError("D0 observations must be backend-local and exchange-free.")
        if not self.repetition_latencies_ms:
            raise ValueError("D0 requires persisted successful repetition latencies.")
        object.__setattr__(self, "repetition_latencies_ms", tuple(self.repetition_latencies_ms))
        object.__setattr__(self, "measurement_ids", tuple(self.measurement_ids))
        object.__setattr__(self, "provenance", dict(self.provenance))

    @property
    def d0_record_id(self) -> str:
        return "d0-" + content_hash(self.to_hash_dict())[:20]

    def to_hash_dict(self) -> dict[str, Any]:
        observation = self.observation.to_dict()
        observation.pop("observed_at", None)
        return {
            "schema_version": self.schema_version,
            "calibration_id": self.calibration_id,
            "backend_id": self.backend_id,
            "split": self.split,
            "raw_execution_cost_ms": self.raw_execution_cost_ms,
            "log_execution_cost": self.log_execution_cost,
            "repetition_latencies_ms": list(self.repetition_latencies_ms),
            "aggregation_statistic": self.aggregation_statistic,
            "measurement_protocol_hash": self.measurement_protocol_hash,
            "measurement_ids": list(self.measurement_ids),
            "observation": observation,
            "provenance": dict(self.provenance),
        }

    def to_dict(self) -> dict[str, Any]:
        observation = self.observation.to_dict()
        return {
            **observation,
            "schema_version": self.schema_version,
            "d0_record_id": self.d0_record_id,
            "calibration_id": self.calibration_id,
            "backend_id": self.backend_id,
            "split": self.split,
            "complete_state_id": self.observation.state_id,
            "physical_plan_id": self.observation.physical_plan_id,
            "raw_execution_cost_ms": self.raw_execution_cost_ms,
            "log_execution_cost": self.log_execution_cost,
            "repetition_latencies_ms": list(self.repetition_latencies_ms),
            "aggregation_statistic": self.aggregation_statistic,
            "measurement_protocol_hash": self.measurement_protocol_hash,
            "measurement_ids": list(self.measurement_ids),
            "feature_vector": self.observation.feature_vector.to_dict(),
            "feature_schema_hash": self.observation.feature_vector.schema_hash,
            "d0_provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class CalibratedGPModelArtifact:
    backend_id: str
    config: GaussianProcessConfig
    d0_hash: str
    observation_ids: tuple[str, ...]
    feature_schema_hash: str
    execution_protocol_hash: str
    backend_descriptor_hash: str
    fitting_objective: str
    fitting_method: str
    objective_value: float
    initialization: Mapping[str, Any]
    random_seed: int
    feature_normalization: Mapping[str, Any]
    noise_handling: Mapping[str, Any]
    kernel_type: str = "rbf"
    schema_version: str = "m12c-calibrated-gp-v1"

    def __post_init__(self) -> None:
        if self.kernel_type != "rbf":
            raise ValueError("M12-C calibrates the existing RBF GP only.")
        if self.config.noise_variance <= 0:
            raise ValueError("Calibrated execution-noise variance must be positive.")
        if not self.observation_ids:
            raise ValueError("A calibrated GP artifact requires non-empty D0 observations.")
        if not math.isfinite(self.objective_value):
            raise ValueError("GP fitting objective must be finite.")
        object.__setattr__(self, "observation_ids", tuple(self.observation_ids))
        object.__setattr__(self, "initialization", dict(self.initialization))
        object.__setattr__(self, "feature_normalization", dict(self.feature_normalization))
        object.__setattr__(self, "noise_handling", dict(self.noise_handling))

    @property
    def hyperparameter_hash(self) -> str:
        return content_hash(
            {
                "kernel_type": self.kernel_type,
                "length_scale": self.config.length_scale,
                "signal_variance": self.config.signal_variance,
                "noise_variance": self.config.noise_variance,
                "jitter": self.config.jitter,
                "prior_log_cost": self.config.prior_log_cost,
                "feature_normalization": dict(self.feature_normalization),
            }
        )

    def to_hash_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend_id": self.backend_id,
            "kernel_type": self.kernel_type,
            "config": self.config.to_dict(),
            "d0_hash": self.d0_hash,
            "observation_ids": list(self.observation_ids),
            "feature_schema_hash": self.feature_schema_hash,
            "execution_protocol_hash": self.execution_protocol_hash,
            "backend_descriptor_hash": self.backend_descriptor_hash,
            "fitting_objective": self.fitting_objective,
            "fitting_method": self.fitting_method,
            "objective_value": self.objective_value,
            "initialization": dict(self.initialization),
            "random_seed": self.random_seed,
            "feature_normalization": dict(self.feature_normalization),
            "noise_handling": dict(self.noise_handling),
            "hyperparameter_hash": self.hyperparameter_hash,
        }

    @property
    def model_hash(self) -> str:
        return content_hash(self.to_hash_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_hash_dict(), "model_hash": self.model_hash}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibratedGPModelArtifact":
        artifact = cls(
            schema_version=str(data.get("schema_version", "m12c-calibrated-gp-v1")),
            backend_id=str(data["backend_id"]),
            kernel_type=str(data.get("kernel_type", "rbf")),
            config=GaussianProcessConfig.from_dict(_mapping(data.get("config"), "config")),
            d0_hash=str(data["d0_hash"]),
            observation_ids=tuple(str(item) for item in data.get("observation_ids", ())),
            feature_schema_hash=str(data["feature_schema_hash"]),
            execution_protocol_hash=str(data["execution_protocol_hash"]),
            backend_descriptor_hash=str(data["backend_descriptor_hash"]),
            fitting_objective=str(data["fitting_objective"]),
            fitting_method=str(data["fitting_method"]),
            objective_value=float(data["objective_value"]),
            initialization=_mapping(data.get("initialization", {}), "initialization"),
            random_seed=int(data.get("random_seed", 0)),
            feature_normalization=_mapping(
                data.get("feature_normalization", {}), "feature_normalization"
            ),
            noise_handling=_mapping(data.get("noise_handling", {}), "noise_handling"),
        )
        if data.get("hyperparameter_hash") not in {None, artifact.hyperparameter_hash}:
            raise ValueError("Calibrated GP hyperparameter hash does not match its content.")
        if data.get("model_hash") not in {None, artifact.model_hash}:
            raise ValueError("Calibrated GP model hash does not match its content.")
        return artifact
