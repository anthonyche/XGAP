"""Serializable contracts for ontology-bounded physical planning."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from xgap.infrastructure.runtime import QueryArtifact


JsonMap = dict[str, Any]


def canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_id(prefix: str, data: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _json_map(value: Mapping[str, Any] | None) -> JsonMap:
    return dict(value or {})


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite.")
    return result


class MappingSufficiencyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


class SemanticDeviationStatus(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class QueryPlanningContext:
    query_id: str
    task_id: str
    question: str
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query_id or not self.task_id or not self.question.strip():
            raise ValueError("query_id, task_id, and question must be non-empty.")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> JsonMap:
        return {
            "query_id": self.query_id,
            "task_id": self.task_id,
            "question": self.question,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LogicalOperatorSpec:
    operator_id: str
    operator_name: str
    feature_id: str
    output_kind: str

    def to_dict(self) -> JsonMap:
        return {
            "operator_id": self.operator_id,
            "operator_name": self.operator_name,
            "feature_id": self.feature_id,
            "output_kind": self.output_kind,
        }


@dataclass(frozen=True)
class LogicalDependency:
    dependency_id: str
    source_operator_id: str
    target_operator_id: str
    result_kind: str

    def to_dict(self) -> JsonMap:
        return {
            "dependency_id": self.dependency_id,
            "source_operator_id": self.source_operator_id,
            "target_operator_id": self.target_operator_id,
            "result_kind": self.result_kind,
        }


@dataclass(frozen=True)
class PlacementDecision:
    operator_id: str
    backend_id: str
    feature_id: str
    support_level: str
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "conditions", tuple(self.conditions))

    def to_dict(self) -> JsonMap:
        return {
            "operator_id": self.operator_id,
            "backend_id": self.backend_id,
            "feature_id": self.feature_id,
            "support_level": self.support_level,
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlacementDecision":
        return cls(
            operator_id=str(data["operator_id"]),
            backend_id=str(data["backend_id"]),
            feature_id=str(data["feature_id"]),
            support_level=str(data["support_level"]),
            conditions=tuple(str(item) for item in data.get("conditions", ())),
        )


@dataclass(frozen=True)
class ExchangeStrategy:
    strategy_id: str
    source_backend_id: str
    target_backend_id: str
    result_kind: str
    executable: bool = True
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("ExchangeStrategy strategy_id must be non-empty.")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> JsonMap:
        return {
            "strategy_id": self.strategy_id,
            "source_backend_id": self.source_backend_id,
            "target_backend_id": self.target_backend_id,
            "result_kind": self.result_kind,
            "executable": self.executable,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExchangeDecision:
    dependency_id: str
    source_operator_id: str
    target_operator_id: str
    source_backend_id: str
    target_backend_id: str
    strategy_id: str
    executable: bool = True
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> JsonMap:
        return {
            "dependency_id": self.dependency_id,
            "source_operator_id": self.source_operator_id,
            "target_operator_id": self.target_operator_id,
            "source_backend_id": self.source_backend_id,
            "target_backend_id": self.target_backend_id,
            "strategy_id": self.strategy_id,
            "executable": self.executable,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExchangeDecision":
        return cls(
            dependency_id=str(data["dependency_id"]),
            source_operator_id=str(data["source_operator_id"]),
            target_operator_id=str(data["target_operator_id"]),
            source_backend_id=str(data["source_backend_id"]),
            target_backend_id=str(data["target_backend_id"]),
            strategy_id=str(data["strategy_id"]),
            executable=bool(data.get("executable", True)),
            metadata=_json_map(data.get("metadata") if isinstance(data.get("metadata"), Mapping) else {}),
        )


@dataclass(frozen=True)
class PhysicalState:
    interpretation_id: str
    logical_plan_id: str
    operators: tuple[LogicalOperatorSpec, ...]
    dependencies: tuple[LogicalDependency, ...]
    placements: tuple[PlacementDecision, ...] = ()
    exchanges: tuple[ExchangeDecision, ...] = ()

    def __post_init__(self) -> None:
        operators = tuple(self.operators)
        dependencies = tuple(self.dependencies)
        placements = tuple(sorted(self.placements, key=lambda item: item.operator_id))
        exchanges = tuple(sorted(self.exchanges, key=lambda item: item.dependency_id))
        operator_ids = [item.operator_id for item in operators]
        if len(operator_ids) != len(set(operator_ids)):
            raise ValueError("PhysicalState operator identifiers must be unique.")
        if len({item.operator_id for item in placements}) != len(placements):
            raise ValueError("PhysicalState may place each operator at most once.")
        if not {item.operator_id for item in placements}.issubset(set(operator_ids)):
            raise ValueError("PhysicalState placement references an unknown operator.")
        dependency_ids = {item.dependency_id for item in dependencies}
        if len(dependency_ids) != len(dependencies):
            raise ValueError("PhysicalState dependency identifiers must be unique.")
        if not {item.dependency_id for item in exchanges}.issubset(dependency_ids):
            raise ValueError("PhysicalState exchange references an unknown dependency.")
        object.__setattr__(self, "operators", operators)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "placements", placements)
        object.__setattr__(self, "exchanges", exchanges)

    @property
    def state_id(self) -> str:
        return content_id("state", self._identity_dict())

    @property
    def operator_ids(self) -> tuple[str, ...]:
        return tuple(item.operator_id for item in self.operators)

    @property
    def assigned_operator_ids(self) -> tuple[str, ...]:
        assigned = {item.operator_id for item in self.placements}
        return tuple(operator_id for operator_id in self.operator_ids if operator_id in assigned)

    @property
    def unassigned_operator_ids(self) -> tuple[str, ...]:
        assigned = set(self.assigned_operator_ids)
        return tuple(operator_id for operator_id in self.operator_ids if operator_id not in assigned)

    def placement_for(self, operator_id: str) -> PlacementDecision | None:
        return next(
            (item for item in self.placements if item.operator_id == operator_id),
            None,
        )

    def exchange_for(self, dependency_id: str) -> ExchangeDecision | None:
        return next(
            (item for item in self.exchanges if item.dependency_id == dependency_id),
            None,
        )

    @property
    def resolved_dependency_ids(self) -> tuple[str, ...]:
        resolved: list[str] = []
        for dependency in self.dependencies:
            source = self.placement_for(dependency.source_operator_id)
            target = self.placement_for(dependency.target_operator_id)
            if source is None or target is None:
                continue
            if source.backend_id == target.backend_id:
                resolved.append(dependency.dependency_id)
                continue
            exchange = self.exchange_for(dependency.dependency_id)
            if exchange is not None and exchange.executable:
                resolved.append(dependency.dependency_id)
        return tuple(resolved)

    @property
    def unresolved_dependency_ids(self) -> tuple[str, ...]:
        resolved = set(self.resolved_dependency_ids)
        return tuple(
            item.dependency_id
            for item in self.dependencies
            if item.dependency_id not in resolved
        )

    @property
    def selected_backend_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.backend_id for item in self.placements}))

    @property
    def is_complete(self) -> bool:
        return not self.unassigned_operator_ids and not self.unresolved_dependency_ids

    def _identity_dict(self) -> JsonMap:
        return {
            "interpretation_id": self.interpretation_id,
            "logical_plan_id": self.logical_plan_id,
            "operators": [item.to_dict() for item in self.operators],
            "dependencies": [item.to_dict() for item in self.dependencies],
            "placements": [item.to_dict() for item in self.placements],
            "exchanges": [item.to_dict() for item in self.exchanges],
        }

    def to_dict(self) -> JsonMap:
        return {
            "state_id": self.state_id,
            **self._identity_dict(),
            "assigned_operator_ids": list(self.assigned_operator_ids),
            "unassigned_operator_ids": list(self.unassigned_operator_ids),
            "resolved_dependency_ids": list(self.resolved_dependency_ids),
            "unresolved_dependency_ids": list(self.unresolved_dependency_ids),
            "selected_backend_ids": list(self.selected_backend_ids),
            "is_complete": self.is_complete,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True)
class FeatureVector:
    schema_version: str
    schema_hash: str
    names: tuple[str, ...]
    values: tuple[float, ...]
    missing: tuple[bool, ...] = ()

    def __post_init__(self) -> None:
        names = tuple(self.names)
        values = tuple(_finite(item, "feature value") for item in self.values)
        missing = tuple(self.missing) if self.missing else tuple(False for _ in names)
        if len(names) != len(values) or len(names) != len(missing):
            raise ValueError("FeatureVector names, values, and missing flags must align.")
        if len(names) != len(set(names)):
            raise ValueError("FeatureVector names must be unique.")
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "missing", missing)

    @property
    def feature_ref(self) -> str:
        return content_id("features", self.to_dict())

    def to_dict(self) -> JsonMap:
        return {
            "schema_version": self.schema_version,
            "schema_hash": self.schema_hash,
            "names": list(self.names),
            "values": list(self.values),
            "missing": list(self.missing),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeatureVector":
        return cls(
            schema_version=str(data["schema_version"]),
            schema_hash=str(data["schema_hash"]),
            names=tuple(str(item) for item in data.get("names", ())),
            values=tuple(float(item) for item in data.get("values", ())),
            missing=tuple(bool(item) for item in data.get("missing", ())),
        )


@dataclass(frozen=True)
class ConfidenceContext:
    delta: float
    state_space_bound: int
    task_index: int = 1
    interpretation_count: int = 1

    def __post_init__(self) -> None:
        delta = _finite(self.delta, "delta")
        if not 0 < delta < 1:
            raise ValueError("delta must be strictly between zero and one.")
        if self.state_space_bound <= 0:
            raise ValueError("state_space_bound must be positive.")
        if self.task_index <= 0 or self.interpretation_count <= 0:
            raise ValueError("task_index and interpretation_count must be positive.")

    def to_dict(self) -> JsonMap:
        return {
            "delta": self.delta,
            "state_space_bound": self.state_space_bound,
            "task_index": self.task_index,
            "interpretation_count": self.interpretation_count,
        }


@dataclass(frozen=True)
class CostPrediction:
    mu: float
    sigma: float
    lower: float
    upper: float
    beta: float
    estimator_id: str
    model_version: str
    feature_ref: str | None = None
    feature_vector: FeatureVector | None = None
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("mu", "sigma", "lower", "upper", "beta"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.sigma < 0 or self.beta < 0:
            raise ValueError("CostPrediction sigma and beta must be nonnegative.")
        if self.lower <= 0 or self.upper <= 0 or self.lower > self.upper:
            raise ValueError("CostPrediction requires 0 < lower <= upper.")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> JsonMap:
        return {
            "mu": self.mu,
            "sigma": self.sigma,
            "lower": self.lower,
            "upper": self.upper,
            "beta": self.beta,
            "estimator_id": self.estimator_id,
            "model_version": self.model_version,
            "feature_ref": self.feature_ref,
            "feature_vector": self.feature_vector.to_dict() if self.feature_vector else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PhysicalCompilationResult:
    feasible: bool
    executable: bool
    status: str
    artifacts: tuple[QueryArtifact, ...] = ()
    reason_code: str | None = None
    message: str = ""
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> JsonMap:
        return {
            "feasible": self.feasible,
            "executable": self.executable,
            "status": self.status,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "reason_code": self.reason_code,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PhysicalRealization:
    state_id: str
    placements: tuple[PlacementDecision, ...]
    exchanges: tuple[ExchangeDecision, ...]
    compilation: PhysicalCompilationResult

    def to_dict(self) -> JsonMap:
        return {
            "state_id": self.state_id,
            "placements": [item.to_dict() for item in self.placements],
            "exchanges": [item.to_dict() for item in self.exchanges],
            "compilation": self.compilation.to_dict(),
        }


@dataclass(frozen=True)
class PhysicalPlan:
    interpretation_id: str
    logical_plan_id: str
    state: PhysicalState
    realization: PhysicalRealization
    cost: CostPrediction

    @property
    def plan_id(self) -> str:
        return content_id(
            "physical-plan",
            {
                "interpretation_id": self.interpretation_id,
                "logical_plan_id": self.logical_plan_id,
                "state_id": self.state.state_id,
                "realization": self.realization.to_dict(),
            },
        )

    def __post_init__(self) -> None:
        if not self.state.is_complete:
            raise ValueError("PhysicalPlan requires a complete PhysicalState.")
        if self.realization.state_id != self.state.state_id:
            raise ValueError("PhysicalPlan realization must refer to its state.")

    def to_dict(self) -> JsonMap:
        return {
            "plan_id": self.plan_id,
            "interpretation_id": self.interpretation_id,
            "logical_plan_id": self.logical_plan_id,
            "state": self.state.to_dict(),
            "realization": self.realization.to_dict(),
            "cost": self.cost.to_dict(),
        }


@dataclass(frozen=True)
class MappingSufficiencyResult:
    status: MappingSufficiencyStatus
    required_terms: tuple[str, ...] = ()
    mapped_terms: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_terms", tuple(self.required_terms))
        object.__setattr__(self, "mapped_terms", tuple(self.mapped_terms))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def sufficient(self) -> bool:
        return self.status is MappingSufficiencyStatus.SUFFICIENT

    def to_dict(self) -> JsonMap:
        return {
            "status": self.status.value,
            "required_terms": list(self.required_terms),
            "mapped_terms": list(self.mapped_terms),
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OntologyAlignmentContext:
    interpretation_id: str
    alignment_id: str
    ontology_artifact_id: str | None
    ontology_version: str | None
    mapping_artifact_id: str | None
    mapping_version: str | None
    mapping_sufficiency: MappingSufficiencyResult
    aliases: JsonMap = field(default_factory=dict)
    semantic_inputs: JsonMap = field(default_factory=dict)
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", dict(self.aliases))
        object.__setattr__(self, "semantic_inputs", dict(self.semantic_inputs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> JsonMap:
        return {
            "interpretation_id": self.interpretation_id,
            "alignment_id": self.alignment_id,
            "ontology_artifact_id": self.ontology_artifact_id,
            "ontology_version": self.ontology_version,
            "mapping_artifact_id": self.mapping_artifact_id,
            "mapping_version": self.mapping_version,
            "mapping_sufficiency": self.mapping_sufficiency.to_dict(),
            "aliases": dict(self.aliases),
            "semantic_inputs": dict(self.semantic_inputs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SemanticDeviationResult:
    interpretation_id: str
    status: SemanticDeviationStatus
    scorer_id: str
    value: float | None = None
    components: JsonMap = field(default_factory=dict)
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status is SemanticDeviationStatus.AVAILABLE:
            if self.value is None:
                raise ValueError("Available semantic deviation requires a value.")
            value = _finite(self.value, "semantic deviation")
            if value < 0:
                raise ValueError("Semantic deviation must be nonnegative.")
            object.__setattr__(self, "value", value)
        elif self.value is not None:
            raise ValueError("Unavailable semantic deviation must not carry a value.")
        object.__setattr__(self, "components", dict(self.components))

    def to_dict(self) -> JsonMap:
        return {
            "interpretation_id": self.interpretation_id,
            "status": self.status.value,
            "scorer_id": self.scorer_id,
            "value": self.value,
            "components": dict(self.components),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ObjectiveScore:
    interpretation_id: str
    semantic_deviation: float
    conservative_cost: float
    semantic_utility: float
    execution_utility: float
    nash_score: float | None
    semantically_admissible: bool
    nash_eligible: bool
    reason: str = ""

    def to_dict(self) -> JsonMap:
        return {
            "interpretation_id": self.interpretation_id,
            "semantic_deviation": self.semantic_deviation,
            "conservative_cost": self.conservative_cost,
            "semantic_utility": self.semantic_utility,
            "execution_utility": self.execution_utility,
            "nash_score": self.nash_score,
            "semantically_admissible": self.semantically_admissible,
            "nash_eligible": self.nash_eligible,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExecutionObservation:
    store_version: str
    observation_id: str
    task_id: str
    query_id: str
    interpretation_id: str
    physical_plan_id: str
    state_id: str
    raw_cost: float
    log_cost: float
    alignment_ref: str
    placements: tuple[PlacementDecision, ...]
    exchanges: tuple[ExchangeDecision, ...]
    feature_vector: FeatureVector
    estimator_version: str
    observed_at: str
    sequence: int
    complete: bool = True
    provenance: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw = _finite(self.raw_cost, "raw_cost")
        logged = _finite(self.log_cost, "log_cost")
        if raw <= 0:
            raise ValueError("ExecutionObservation raw_cost must be positive.")
        if not math.isclose(logged, math.log(raw), rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("ExecutionObservation log_cost must equal log(raw_cost).")
        if self.sequence < 0:
            raise ValueError("ExecutionObservation sequence must be nonnegative.")
        if not self.complete:
            raise ValueError("ExecutionObservation accepts complete physical plans only.")
        object.__setattr__(self, "placements", tuple(self.placements))
        object.__setattr__(self, "exchanges", tuple(self.exchanges))
        object.__setattr__(self, "provenance", dict(self.provenance))

    def to_dict(self) -> JsonMap:
        return {
            "store_version": self.store_version,
            "observation_id": self.observation_id,
            "task_id": self.task_id,
            "query_id": self.query_id,
            "interpretation_id": self.interpretation_id,
            "physical_plan_id": self.physical_plan_id,
            "state_id": self.state_id,
            "raw_cost": self.raw_cost,
            "log_cost": self.log_cost,
            "alignment_ref": self.alignment_ref,
            "placements": [item.to_dict() for item in self.placements],
            "exchanges": [item.to_dict() for item in self.exchanges],
            "feature_vector": self.feature_vector.to_dict(),
            "estimator_version": self.estimator_version,
            "observed_at": self.observed_at,
            "sequence": self.sequence,
            "complete": self.complete,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionObservation":
        return cls(
            store_version=str(data["store_version"]),
            observation_id=str(data["observation_id"]),
            task_id=str(data["task_id"]),
            query_id=str(data["query_id"]),
            interpretation_id=str(data["interpretation_id"]),
            physical_plan_id=str(data["physical_plan_id"]),
            state_id=str(data["state_id"]),
            raw_cost=float(data["raw_cost"]),
            log_cost=float(data["log_cost"]),
            alignment_ref=str(data["alignment_ref"]),
            placements=tuple(
                PlacementDecision.from_dict(item) for item in data.get("placements", ())
            ),
            exchanges=tuple(
                ExchangeDecision.from_dict(item) for item in data.get("exchanges", ())
            ),
            feature_vector=FeatureVector.from_dict(data["feature_vector"]),
            estimator_version=str(data["estimator_version"]),
            observed_at=str(data["observed_at"]),
            sequence=int(data["sequence"]),
            complete=bool(data.get("complete", False)),
            provenance=_json_map(
                data.get("provenance") if isinstance(data.get("provenance"), Mapping) else {}
            ),
        )


@dataclass(frozen=True)
class PlanningTraceEvent:
    run_id: str
    query_id: str
    task_id: str
    interpretation_id: str
    alignment_ref: str
    state_id: str
    parent_state_id: str | None
    processed_index: int | None
    action_id: str
    action: str
    placement_delta: PlacementDecision | None
    exchange_delta: tuple[ExchangeDecision, ...]
    open_size: int
    budget: int
    budget_used: int
    feasible: bool
    complete: bool
    prediction: CostPrediction | None
    pruned: bool
    prune_reason: str | None
    incumbent_before: float | None
    incumbent_after: float | None
    termination_reason: str | None = None
    timestamp: str = "deterministic"

    def to_dict(self) -> JsonMap:
        return {
            "run_id": self.run_id,
            "query_id": self.query_id,
            "task_id": self.task_id,
            "interpretation_id": self.interpretation_id,
            "alignment_ref": self.alignment_ref,
            "state_id": self.state_id,
            "parent_state_id": self.parent_state_id,
            "processed_index": self.processed_index,
            "action_id": self.action_id,
            "action": self.action,
            "placement_delta": self.placement_delta.to_dict() if self.placement_delta else None,
            "exchange_delta": [item.to_dict() for item in self.exchange_delta],
            "open_size": self.open_size,
            "budget": self.budget,
            "budget_used": self.budget_used,
            "feasible": self.feasible,
            "complete": self.complete,
            "feature_ref": self.prediction.feature_ref if self.prediction else None,
            "prediction": self.prediction.to_dict() if self.prediction else None,
            "pruned": self.pruned,
            "prune_reason": self.prune_reason,
            "incumbent_before": self.incumbent_before,
            "incumbent_after": self.incumbent_after,
            "termination_reason": self.termination_reason,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class PlanningConfig:
    run_id: str
    semantic_threshold: float
    execution_threshold: float
    top_k: int
    global_delta: float
    task_index: int = 1
    deterministic_seed: int = 0
    metadata: JsonMap = field(default_factory=dict)

    def __post_init__(self) -> None:
        semantic = _finite(self.semantic_threshold, "semantic_threshold")
        execution = _finite(self.execution_threshold, "execution_threshold")
        delta = _finite(self.global_delta, "global_delta")
        if semantic < 0 or execution <= 0:
            raise ValueError("semantic_threshold must be nonnegative and execution_threshold positive.")
        if self.top_k <= 0 or self.task_index <= 0:
            raise ValueError("top_k and task_index must be positive.")
        if not 0 < delta < 1:
            raise ValueError("global_delta must be strictly between zero and one.")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> JsonMap:
        return {
            "run_id": self.run_id,
            "semantic_threshold": self.semantic_threshold,
            "execution_threshold": self.execution_threshold,
            "top_k": self.top_k,
            "global_delta": self.global_delta,
            "task_index": self.task_index,
            "deterministic_seed": self.deterministic_seed,
            "metadata": dict(self.metadata),
        }


def objective_score(
    *,
    interpretation_id: str,
    semantic_deviation: float,
    conservative_cost: float,
    config: PlanningConfig,
) -> ObjectiveScore:
    semantic_deviation = _finite(semantic_deviation, "semantic_deviation")
    conservative_cost = _finite(conservative_cost, "conservative_cost")
    semantic_utility = config.semantic_threshold - semantic_deviation
    execution_utility = config.execution_threshold - conservative_cost
    semantically_admissible = semantic_deviation <= config.semantic_threshold
    eligible = semantically_admissible and semantic_utility > 0 and execution_utility > 0
    if not semantically_admissible:
        reason = "semantic_threshold_exceeded"
    elif semantic_utility <= 0:
        reason = "semantic_utility_not_positive"
    elif execution_utility <= 0:
        reason = "no_plan_under_execution_threshold"
    else:
        reason = "eligible"
    return ObjectiveScore(
        interpretation_id=interpretation_id,
        semantic_deviation=semantic_deviation,
        conservative_cost=conservative_cost,
        semantic_utility=semantic_utility,
        execution_utility=execution_utility,
        nash_score=semantic_utility * execution_utility if eligible else None,
        semantically_admissible=semantically_admissible,
        nash_eligible=eligible,
        reason=reason,
    )
