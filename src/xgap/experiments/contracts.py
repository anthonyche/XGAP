"""Versioned contracts for reproducible M12 experiments."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from xgap.experiments.hashing import content_hash
from xgap.experiments.semantic import SemanticDeviationConfig


class BaselineId(str, Enum):
    FULL_XGAP = "full_xgap"
    RANDOM_FEASIBLE = "random_feasible"
    MEAN_ONLY = "mean_only"
    NO_PRUNING = "no_pruning"
    NO_ONLINE_UPDATE = "no_online_update"
    SINGLE_BACKEND = "single_backend"
    EXHAUSTIVE_ORACLE = "exhaustive_oracle"
    DIRECT_TEXT2GRAPHQUERY = "direct_text2graphquery"


class MetricAvailability(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ArtifactReference:
    status: MetricAvailability
    path: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is MetricAvailability.AVAILABLE and not self.path:
            raise ValueError("Available artifact references require a path.")
        if self.status is not MetricAvailability.AVAILABLE and self.path is not None:
            raise ValueError("Unavailable artifact references cannot contain a path.")
        if self.status is not MetricAvailability.AVAILABLE and not self.reason:
            raise ValueError("Unavailable artifact references require a reason.")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactReference":
        return cls(
            status=MetricAvailability(str(data.get("status", ""))),
            path=str(data["path"]) if data.get("path") is not None else None,
            reason=str(data["reason"]) if data.get("reason") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "path": self.path, "reason": self.reason}


@dataclass(frozen=True)
class CalibrationProtocol:
    split_id: str
    sampling_policy_id: str
    plan_count: int
    random_seed: int
    backend_scope: tuple[str, ...]
    observation_artifact: ArtifactReference
    repeated_measurement_policy_ref: str
    fit_hyperparameters: bool = True

    def __post_init__(self) -> None:
        if not self.split_id or not self.sampling_policy_id:
            raise ValueError("Calibration split and sampling policy IDs are required.")
        if self.plan_count <= 0:
            raise ValueError("Calibration plan_count must be positive.")
        if not self.backend_scope:
            raise ValueError("Calibration backend_scope must be non-empty.")
        if not self.repeated_measurement_policy_ref:
            raise ValueError("Calibration repeated-measurement policy is required.")
        object.__setattr__(self, "backend_scope", tuple(self.backend_scope))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationProtocol":
        return cls(
            split_id=str(data.get("split_id", "")),
            sampling_policy_id=str(data.get("sampling_policy_id", "")),
            plan_count=int(data.get("plan_count", 0)),
            random_seed=int(data.get("random_seed", 0)),
            backend_scope=tuple(str(item) for item in data.get("backend_scope", ())),
            observation_artifact=ArtifactReference.from_dict(
                _mapping(data.get("observation_artifact"), "observation_artifact")
            ),
            repeated_measurement_policy_ref=str(
                data.get("repeated_measurement_policy_ref", "")
            ),
            fit_hyperparameters=bool(data.get("fit_hyperparameters", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_id": self.split_id,
            "sampling_policy_id": self.sampling_policy_id,
            "plan_count": self.plan_count,
            "random_seed": self.random_seed,
            "backend_scope": list(self.backend_scope),
            "observation_artifact": self.observation_artifact.to_dict(),
            "repeated_measurement_policy_ref": self.repeated_measurement_policy_ref,
            "fit_hyperparameters": self.fit_hyperparameters,
        }


@dataclass(frozen=True)
class GPProtocol:
    calibration: CalibrationProtocol
    target: str = "log_execution_cost"
    kernel: str = "rbf"
    complete_plans_only: bool = True
    freeze_hyperparameters_during_evaluation: bool = True
    update_posterior_between_tasks: bool = True
    update_within_task: bool = False
    schema_version: str = "m12-gp-protocol-v1"

    def __post_init__(self) -> None:
        if self.target != "log_execution_cost" or self.kernel != "rbf":
            raise ValueError("M12 freezes the M11 log-cost RBF GP family.")
        if not self.complete_plans_only:
            raise ValueError("GP observations may be collected from complete plans only.")
        if not self.calibration.fit_hyperparameters:
            raise ValueError("Full XGAP fits GP hyperparameters on D_0.")
        if not self.freeze_hyperparameters_during_evaluation:
            raise ValueError("GP hyperparameters must remain frozen during evaluation.")
        if self.update_within_task:
            raise ValueError("The frozen GP protocol forbids within-task posterior updates.")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GPProtocol":
        evaluation = _mapping(data.get("evaluation"), "gp_protocol.evaluation")
        return cls(
            schema_version=str(data.get("schema_version", "m12-gp-protocol-v1")),
            target=str(data.get("target", "")),
            kernel=str(data.get("kernel", "")),
            complete_plans_only=bool(data.get("complete_plans_only", True)),
            calibration=CalibrationProtocol.from_dict(
                _mapping(data.get("calibration"), "gp_protocol.calibration")
            ),
            freeze_hyperparameters_during_evaluation=bool(
                evaluation.get("freeze_hyperparameters", True)
            ),
            update_posterior_between_tasks=bool(
                evaluation.get("update_posterior_between_tasks", True)
            ),
            update_within_task=bool(evaluation.get("update_within_task", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "kernel": self.kernel,
            "complete_plans_only": self.complete_plans_only,
            "calibration": self.calibration.to_dict(),
            "evaluation": {
                "freeze_hyperparameters": self.freeze_hyperparameters_during_evaluation,
                "update_posterior_between_tasks": self.update_posterior_between_tasks,
                "update_within_task": self.update_within_task,
            },
        }


@dataclass(frozen=True)
class FeatureSchemaReference:
    extractor_id: str
    version: str
    schema_hash: str
    unavailable_statistics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.extractor_id or not self.version or not self.schema_hash:
            raise ValueError("Feature schema extractor, version, and hash are required.")
        object.__setattr__(self, "unavailable_statistics", tuple(self.unavailable_statistics))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeatureSchemaReference":
        return cls(
            extractor_id=str(data.get("extractor_id", "")),
            version=str(data.get("version", "")),
            schema_hash=str(data.get("schema_hash", "")),
            unavailable_statistics=tuple(
                str(item) for item in data.get("unavailable_statistics", ())
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "extractor_id": self.extractor_id,
            "version": self.version,
            "schema_hash": self.schema_hash,
            "unavailable_statistics": list(self.unavailable_statistics),
        }


@dataclass(frozen=True)
class BaselineConfig:
    baseline_id: BaselineId
    backend_id: str | None = None
    controlled_scope: bool = False
    model_bundle_ref: str | None = None

    def __post_init__(self) -> None:
        needs_backend = self.baseline_id in {
            BaselineId.SINGLE_BACKEND,
            BaselineId.DIRECT_TEXT2GRAPHQUERY,
        }
        if needs_backend and not self.backend_id:
            raise ValueError(f"{self.baseline_id.value} requires one backend_id.")
        if self.baseline_id is BaselineId.EXHAUSTIVE_ORACLE and not self.controlled_scope:
            raise ValueError("exhaustive_oracle is restricted to controlled small spaces.")
        if self.baseline_id is BaselineId.DIRECT_TEXT2GRAPHQUERY and not self.model_bundle_ref:
            raise ValueError("direct_text2graphquery requires an explicit model bundle.")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BaselineConfig":
        return cls(
            baseline_id=BaselineId(str(data.get("id", ""))),
            backend_id=str(data["backend_id"]) if data.get("backend_id") else None,
            controlled_scope=bool(data.get("controlled_scope", False)),
            model_bundle_ref=(
                str(data["model_bundle_ref"])
                if data.get("model_bundle_ref") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.baseline_id.value,
            "backend_id": self.backend_id,
            "controlled_scope": self.controlled_scope,
            "model_bundle_ref": self.model_bundle_ref,
        }


@dataclass(frozen=True)
class AblationConfig:
    no_uncertainty: bool = False
    no_pruning: bool = False
    no_online_learning: bool = False
    no_semantic_bound: bool = False
    cost_only: bool = False
    no_nash: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AblationConfig":
        known = set(cls.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown ablation switch(es): {sorted(unknown)}")
        return cls(**{name: bool(data.get(name, False)) for name in known})

    @property
    def enabled(self) -> tuple[str, ...]:
        return tuple(name for name in self.__dataclass_fields__ if getattr(self, name))

    def to_dict(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class MetricValue:
    status: MetricAvailability
    value: float | int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is MetricAvailability.AVAILABLE:
            if self.value is None or isinstance(self.value, bool):
                raise ValueError("Available metrics require a numeric value.")
            if not math.isfinite(float(self.value)):
                raise ValueError("Metric values must be finite.")
        elif self.value is not None:
            raise ValueError("Unavailable metrics cannot contain a value.")
        elif not self.reason:
            raise ValueError("Unavailable metrics require a reason.")

    @classmethod
    def available(cls, value: float | int) -> "MetricValue":
        return cls(MetricAvailability.AVAILABLE, value=value)

    @classmethod
    def unavailable(cls, reason: str) -> "MetricValue":
        return cls(MetricAvailability.NOT_AVAILABLE, reason=reason)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MetricValue":
        raw_value = data.get("value")
        return cls(
            status=MetricAvailability(str(data.get("status", ""))),
            value=(
                float(raw_value)
                if raw_value is not None and not isinstance(raw_value, bool)
                else None
            ),
            reason=str(data["reason"]) if data.get("reason") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "value": self.value, "reason": self.reason}


INTERPRETATION_METRICS = (
    "top_1_interpretation_accuracy",
    "oracle_at_k",
    "supported_coverage",
    "semantic_deviation",
    "mapping_failure_rate",
    "unsupported_rate",
)
PHYSICAL_PLANNING_METRICS = (
    "planning_latency_seconds",
    "states_generated",
    "states_processed",
    "states_pruned",
    "pruning_ratio",
    "search_reduction",
    "true_regret",
    "eta_search",
    "eta_select",
    "cost_prediction_error",
    "confidence_coverage",
)
END_TO_END_METRICS = (
    "execution_accuracy",
    "exact_match",
    "f1",
    "backend_execution_latency_seconds",
    "end_to_end_latency_seconds",
    "data_movement_bytes",
    "success_rate",
    "error_rate",
)
LIVE_GENERATION_METRICS = (
    "generation_success_rate",
    "structured_parse_success_rate",
    "candidate_validation_success_rate",
    "candidates_per_question",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "llm_latency_seconds",
    "repair_rate",
    "ontology_grounding_success_rate",
    "unresolved_anchor_rate",
    "hallucinated_ontology_id_rate",
    "mapping_failure_rate",
    "semantic_inadmissibility_rate",
)


@dataclass(frozen=True)
class ExperimentMetrics:
    interpretation: Mapping[str, MetricValue]
    physical_planning: Mapping[str, MetricValue]
    end_to_end: Mapping[str, MetricValue]
    live_generation: Mapping[str, MetricValue] = field(default_factory=dict)
    schema_version: str = "m12-metrics-v1"

    def __post_init__(self) -> None:
        groups = (
            ("interpretation", self.interpretation, INTERPRETATION_METRICS),
            ("physical_planning", self.physical_planning, PHYSICAL_PLANNING_METRICS),
            ("end_to_end", self.end_to_end, END_TO_END_METRICS),
        )
        for name, values, expected in groups:
            if set(values) != set(expected):
                raise ValueError(f"Metric group '{name}' must define exactly {expected}.")
            object.__setattr__(self, name, dict(values))
        if self.live_generation and set(self.live_generation) != set(LIVE_GENERATION_METRICS):
            raise ValueError(
                f"Metric group 'live_generation' must define exactly {LIVE_GENERATION_METRICS}."
            )
        object.__setattr__(self, "live_generation", dict(self.live_generation))

    @classmethod
    def unavailable(cls, reason: str) -> "ExperimentMetrics":
        return cls(
            interpretation={name: MetricValue.unavailable(reason) for name in INTERPRETATION_METRICS},
            physical_planning={name: MetricValue.unavailable(reason) for name in PHYSICAL_PLANNING_METRICS},
            end_to_end={name: MetricValue.unavailable(reason) for name in END_TO_END_METRICS},
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExperimentMetrics":
        def group(name: str) -> dict[str, MetricValue]:
            raw = _mapping(data.get(name), name)
            return {
                str(key): MetricValue.from_dict(_mapping(value, f"{name}.{key}"))
                for key, value in raw.items()
            }

        return cls(
            schema_version=str(data.get("schema_version", "m12-metrics-v1")),
            interpretation=group("interpretation"),
            physical_planning=group("physical_planning"),
            end_to_end=group("end_to_end"),
            live_generation=(
                group("live_generation") if "live_generation" in data else {}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "interpretation": {key: value.to_dict() for key, value in self.interpretation.items()},
            "physical_planning": {key: value.to_dict() for key, value in self.physical_planning.items()},
            "end_to_end": {key: value.to_dict() for key, value in self.end_to_end.items()},
        }
        if self.live_generation:
            result["live_generation"] = {
                key: value.to_dict() for key, value in self.live_generation.items()
            }
        return result


@dataclass(frozen=True)
class ExecutionProtocol:
    warmup_runs: int = 1
    measured_repetitions: int = 5
    aggregation_statistic: str = "median"
    timeout_seconds: float = 60.0
    cache_policy: str = "record_without_forced_flush"
    backend_reset_policy: str = "none_between_repetitions"
    mode: str = "isolated"
    machine_metadata_policy: str = "record_available"
    record_docker_backend_versions: bool = True
    schema_version: str = "m12-execution-protocol-v1"

    def __post_init__(self) -> None:
        if self.warmup_runs < 0 or self.measured_repetitions <= 0:
            raise ValueError("Execution repetitions must include at least one measured run.")
        if self.aggregation_statistic not in {"median", "mean", "min"}:
            raise ValueError("Unsupported execution aggregation statistic.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Execution timeout_seconds must be positive and finite.")
        if self.mode not in {"isolated", "concurrent"}:
            raise ValueError("Execution mode must be isolated or concurrent.")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionProtocol":
        return cls(
            schema_version=str(data.get("schema_version", "m12-execution-protocol-v1")),
            warmup_runs=int(data.get("warmup_runs", 1)),
            measured_repetitions=int(data.get("measured_repetitions", 5)),
            aggregation_statistic=str(data.get("aggregation_statistic", "median")),
            timeout_seconds=float(data.get("timeout_seconds", 60.0)),
            cache_policy=str(data.get("cache_policy", "record_without_forced_flush")),
            backend_reset_policy=str(data.get("backend_reset_policy", "none_between_repetitions")),
            mode=str(data.get("mode", "isolated")),
            machine_metadata_policy=str(data.get("machine_metadata_policy", "record_available")),
            record_docker_backend_versions=bool(data.get("record_docker_backend_versions", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "warmup_runs": self.warmup_runs,
            "measured_repetitions": self.measured_repetitions,
            "aggregation_statistic": self.aggregation_statistic,
            "timeout_seconds": self.timeout_seconds,
            "cache_policy": self.cache_policy,
            "backend_reset_policy": self.backend_reset_policy,
            "mode": self.mode,
            "machine_metadata_policy": self.machine_metadata_policy,
            "record_docker_backend_versions": self.record_docker_backend_versions,
        }


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    run_id: str
    dataset_bundle_ref: str
    model_bundle_ref: str
    question_ids: tuple[str, ...]
    backend_ids: tuple[str, ...]
    semantic_deviation: SemanticDeviationConfig
    epsilon: float
    execution_threshold: float
    top_k: int
    candidate_cap: int
    budget: dict[str, Any]
    cost_estimator: dict[str, Any]
    gp_protocol: GPProtocol
    feature_schema: FeatureSchemaReference
    baseline: BaselineConfig
    ablations: AblationConfig
    random_seed: int
    execution_protocol: ExecutionProtocol
    metric_ids: tuple[str, ...]
    output_root: str
    global_delta: float = 0.05
    descriptor_dir: str = "descriptors/backends"
    candidate_provider_id: str = "model_bundle"
    alignment_provider_id: str = "controlled_artifact"
    runtime_grounding: Mapping[str, Any] = field(default_factory=dict)
    orchestration: Mapping[str, Any] = field(default_factory=dict)
    future_artifacts: Mapping[str, ArtifactReference] = field(default_factory=dict)
    schema_version: str = "m12-experiment-spec-v1"

    def __post_init__(self) -> None:
        if not all((self.experiment_id, self.run_id, self.dataset_bundle_ref, self.model_bundle_ref)):
            raise ValueError("Experiment ID, run ID, dataset, and model bundle are required.")
        if not self.question_ids or len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("Experiment question_ids must be non-empty and unique.")
        if not self.backend_ids or len(set(self.backend_ids)) != len(self.backend_ids):
            raise ValueError("Experiment backend_ids must be non-empty and unique.")
        if self.baseline.backend_id and self.baseline.backend_id not in self.backend_ids:
            raise ValueError("Baseline backend_id must be included in backend_ids.")
        if self.baseline.baseline_id in {BaselineId.SINGLE_BACKEND, BaselineId.DIRECT_TEXT2GRAPHQUERY} and len(self.backend_ids) != 1:
            raise ValueError(f"{self.baseline.baseline_id.value} requires exactly one backend.")
        if self.baseline.baseline_id is BaselineId.NO_PRUNING and self.ablations.no_pruning:
            raise ValueError("Do not duplicate no_pruning as baseline and ablation.")
        if self.baseline.baseline_id is BaselineId.NO_ONLINE_UPDATE and self.ablations.no_online_learning:
            raise ValueError("Do not duplicate no-online-update semantics.")
        if self.baseline.baseline_id is BaselineId.DIRECT_TEXT2GRAPHQUERY and self.ablations.enabled:
            raise ValueError("XGAP planner ablations do not apply to direct_text2graphquery.")
        if not math.isfinite(self.epsilon) or self.epsilon not in self.semantic_deviation.epsilon_values:
            raise ValueError("Experiment epsilon must occur in the configured epsilon sweep.")
        if not math.isfinite(self.execution_threshold) or self.execution_threshold <= 0:
            raise ValueError("T_max must be positive and finite.")
        if self.top_k <= 0 or self.candidate_cap <= 0 or self.top_k > self.candidate_cap:
            raise ValueError("K and candidate cap must be positive with K <= M.")
        if not 0 < self.global_delta < 1:
            raise ValueError("global_delta must lie strictly within (0,1).")
        if not self.output_root:
            raise ValueError("Experiment output_root is required.")
        if self.candidate_provider_id != "model_bundle":
            raise ValueError("M12 supports the ModelBundle candidate-provider selector only.")
        if self.alignment_provider_id not in {"controlled_artifact", "file_backed_runtime"}:
            raise ValueError("Unknown ontology/alignment provider selection.")
        portable_paths = (
            self.dataset_bundle_ref,
            self.model_bundle_ref,
            self.output_root,
            self.descriptor_dir,
        )
        if any(Path(value).is_absolute() for value in portable_paths):
            raise ValueError("ExperimentSpec paths must be repository-relative for stable hashing.")
        if (
            self.baseline.baseline_id is BaselineId.FULL_XGAP
            and not self.gp_protocol.update_posterior_between_tasks
        ):
            raise ValueError("full_xgap requires posterior updates between evaluation tasks.")
        if (
            self.baseline.baseline_id is BaselineId.NO_ONLINE_UPDATE
            and self.gp_protocol.update_posterior_between_tasks
        ):
            raise ValueError("no_online_update must disable between-task posterior updates.")
        if self.ablations.no_online_learning and self.gp_protocol.update_posterior_between_tasks:
            raise ValueError("no_online_learning must disable between-task posterior updates.")
        object.__setattr__(self, "question_ids", tuple(self.question_ids))
        object.__setattr__(self, "backend_ids", tuple(self.backend_ids))
        object.__setattr__(self, "budget", dict(self.budget))
        object.__setattr__(self, "cost_estimator", dict(self.cost_estimator))
        object.__setattr__(self, "metric_ids", tuple(self.metric_ids))
        object.__setattr__(self, "runtime_grounding", dict(self.runtime_grounding))
        object.__setattr__(self, "orchestration", dict(self.orchestration))
        object.__setattr__(self, "future_artifacts", dict(self.future_artifacts))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExperimentSpec":
        planning = _mapping(data.get("planning"), "planning")
        artifacts = _mapping(data.get("future_artifacts", {}), "future_artifacts")
        return cls(
            schema_version=str(data.get("schema_version", "m12-experiment-spec-v1")),
            experiment_id=str(data.get("experiment_id", "")),
            run_id=str(data.get("run_id", "")),
            dataset_bundle_ref=str(data.get("dataset_bundle", "")),
            model_bundle_ref=str(data.get("model_bundle", "")),
            question_ids=tuple(str(item) for item in data.get("question_ids", ())),
            backend_ids=tuple(str(item) for item in data.get("backend_ids", ())),
            semantic_deviation=SemanticDeviationConfig.from_dict(
                _mapping(data.get("semantic_deviation"), "semantic_deviation")
            ),
            epsilon=float(planning.get("epsilon", -1)),
            execution_threshold=float(planning.get("t_max", 0)),
            top_k=int(planning.get("top_k", 0)),
            candidate_cap=int(planning.get("candidate_cap", 0)),
            global_delta=float(planning.get("global_delta", 0.05)),
            budget=_mapping(data.get("budget"), "budget"),
            cost_estimator=_mapping(data.get("cost_estimator"), "cost_estimator"),
            gp_protocol=GPProtocol.from_dict(_mapping(data.get("gp_protocol"), "gp_protocol")),
            feature_schema=FeatureSchemaReference.from_dict(
                _mapping(data.get("feature_schema"), "feature_schema")
            ),
            baseline=BaselineConfig.from_dict(_mapping(data.get("baseline"), "baseline")),
            ablations=AblationConfig.from_dict(_mapping(data.get("ablations", {}), "ablations")),
            random_seed=int(data.get("random_seed", 0)),
            execution_protocol=ExecutionProtocol.from_dict(
                _mapping(data.get("execution_protocol"), "execution_protocol")
            ),
            metric_ids=tuple(str(item) for item in data.get("metric_ids", ())),
            output_root=str(data.get("output_root", "")),
            descriptor_dir=str(data.get("descriptor_dir", "descriptors/backends")),
            candidate_provider_id=str(data.get("candidate_provider", "model_bundle")),
            alignment_provider_id=str(data.get("alignment_provider", "controlled_artifact")),
            runtime_grounding=_mapping(data.get("runtime_grounding", {}), "runtime_grounding"),
            orchestration=_mapping(data.get("orchestration", {}), "orchestration"),
            future_artifacts={
                str(name): ArtifactReference.from_dict(_mapping(value, str(name)))
                for name, value in artifacts.items()
            },
        )

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentSpec":
        import json

        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("ExperimentSpec JSON root must be an object.")
        return cls.from_dict(raw)

    def to_hash_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "dataset_bundle": self.dataset_bundle_ref,
            "model_bundle": self.model_bundle_ref,
            "question_ids": list(self.question_ids),
            "backend_ids": list(self.backend_ids),
            "semantic_deviation": self.semantic_deviation.to_dict(),
            "planning": {
                "epsilon": self.epsilon,
                "t_max": self.execution_threshold,
                "top_k": self.top_k,
                "candidate_cap": self.candidate_cap,
                "global_delta": self.global_delta,
            },
            "budget": dict(self.budget),
            "cost_estimator": dict(self.cost_estimator),
            "gp_protocol": self.gp_protocol.to_dict(),
            "feature_schema": self.feature_schema.to_dict(),
            "baseline": self.baseline.to_dict(),
            "ablations": self.ablations.to_dict(),
            "random_seed": self.random_seed,
            "execution_protocol": self.execution_protocol.to_dict(),
            "metric_ids": list(self.metric_ids),
            "output_root": self.output_root,
            "descriptor_dir": self.descriptor_dir,
            "candidate_provider": self.candidate_provider_id,
            "alignment_provider": self.alignment_provider_id,
            "runtime_grounding": dict(self.runtime_grounding),
            "future_artifacts": {
                key: value.to_dict() for key, value in sorted(self.future_artifacts.items())
            },
        }
        if self.orchestration:
            result["orchestration"] = dict(self.orchestration)
        return result

    @property
    def spec_hash(self) -> str:
        return content_hash(self.to_hash_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_hash_dict(), "spec_hash": self.spec_hash}


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping.")
    return dict(value)
