"""Family-local plan memory for parameterized federated query instances.

The older M15 plan-snapshot cache is intentionally exact-context scoped.  It
cannot establish transfer across different query bindings.  This module adds
a separate F2C5 contract whose compatibility boundary is method x query
family x workload x runtime.  Only successful, exact seed executions may be
committed.  Evaluation tasks read an immutable predecessor view and never
write to it.

The included KNN selector is a transparent development reference policy, not
the frozen paper model.  It consumes only typed query bindings and prior
execution measurements; answer or source oracles are not part of its input.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from xgap.agent import MemoryRecord, MemoryScope, MemoryStore
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_parameterized_federation import (
    load_m15_parameterized_contract,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
    load_m15_parameterized_workload_bundle,
)
from xgap.runtime import FederatedRunResult


FAMILY_MEMORY_CONTEXT_SCHEMA_VERSION = "m15-f2c5-family-memory-context-v1"
FAMILY_QUERY_FEATURE_SCHEMA_VERSION = "m15-f2c5-family-query-features-v1"
FAMILY_PLAN_OBSERVATION_SCHEMA_VERSION = "m15-f2c5-family-plan-observation-v1"
FAMILY_MEMORY_VIEW_SCHEMA_VERSION = "m15-f2c5-family-memory-view-v1"
FAMILY_TRANSFER_SELECTION_SCHEMA_VERSION = (
    "m15-f2c5-family-transfer-selection-v1"
)
FAMILY_TRANSFER_MODEL_VERSION = "m15-f2c5-gower-knn-development-v1"
_MEMORY_KEY_PREFIX = "m15-f2c5-family-plan-observation"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FEATURE_KINDS = frozenset({"entity_id", "date", "integer", "enum", "string"})


class M15FamilyMemoryError(ValueError):
    """Raised before memory mutation or plan selection on contract drift."""


def _bundle(
    value: M15ParameterizedWorkloadBundle | str | Path,
) -> M15ParameterizedWorkloadBundle:
    if isinstance(value, M15ParameterizedWorkloadBundle):
        return value
    return load_m15_parameterized_workload_bundle(value)


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15FamilyMemoryError(f"{name} must be a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15FamilyMemoryError(f"{name} must be a SHA-256 hex digest")
    return value


def _finite_nonnegative(value: object, *, name: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise M15FamilyMemoryError(f"{name} must be finite and nonnegative")
    return float(value)


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise M15FamilyMemoryError(f"{name} must be a positive integer")
    return value


def _validate_feature_value(value: object, *, kind: str, slot_id: str) -> None:
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise M15FamilyMemoryError(
                f"feature slot '{slot_id}' must contain an integer"
            )
        return
    if not isinstance(value, str) or not value.strip():
        raise M15FamilyMemoryError(
            f"feature slot '{slot_id}' must contain a nonempty string"
        )
    if kind == "date":
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise M15FamilyMemoryError(
                f"feature slot '{slot_id}' must contain an ISO-8601 date"
            ) from exc
        if parsed.isoformat() != value:
            raise M15FamilyMemoryError(
                f"feature slot '{slot_id}' must contain a canonical date"
            )


@dataclass(frozen=True)
class M15FamilyMemoryContext:
    method_namespace: str
    family_compatibility_sha256: str
    workload_bundle_sha256: str
    runtime_compatibility_sha256: str
    feature_schema: tuple[tuple[str, str], ...]
    candidate_strategy_ids: tuple[str, ...]
    context_sha256: str

    def __post_init__(self) -> None:
        _safe_id(self.method_namespace, name="method_namespace")
        _sha256(
            self.family_compatibility_sha256,
            name="family_compatibility_sha256",
        )
        _sha256(self.workload_bundle_sha256, name="workload_bundle_sha256")
        _sha256(
            self.runtime_compatibility_sha256,
            name="runtime_compatibility_sha256",
        )
        _sha256(self.context_sha256, name="context_sha256")
        if not self.feature_schema:
            raise M15FamilyMemoryError("feature_schema must be nonempty")
        slot_ids: list[str] = []
        for slot_id, kind in self.feature_schema:
            slot_ids.append(_safe_id(slot_id, name="feature slot_id"))
            if kind not in _FEATURE_KINDS:
                raise M15FamilyMemoryError(
                    f"feature slot '{slot_id}' has unsupported kind '{kind}'"
                )
        if len(slot_ids) != len(set(slot_ids)) or slot_ids != sorted(slot_ids):
            raise M15FamilyMemoryError(
                "feature_schema slot IDs must be unique and sorted"
            )
        if len(self.candidate_strategy_ids) < 2:
            raise M15FamilyMemoryError(
                "family memory requires at least two candidate strategies"
            )
        if tuple(sorted(set(self.candidate_strategy_ids))) != (
            self.candidate_strategy_ids
        ):
            raise M15FamilyMemoryError(
                "candidate strategy IDs must be unique and sorted"
            )
        expected = content_hash(self._identity())
        if self.context_sha256 != expected:
            raise M15FamilyMemoryError(
                "family memory context hash does not match its identity"
            )

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_MEMORY_CONTEXT_SCHEMA_VERSION,
            "method_namespace": self.method_namespace,
            "family_compatibility_sha256": self.family_compatibility_sha256,
            "workload_bundle_sha256": self.workload_bundle_sha256,
            "runtime_compatibility_sha256": self.runtime_compatibility_sha256,
            "feature_schema": [
                {"slot_id": slot_id, "kind": kind}
                for slot_id, kind in self.feature_schema
            ],
            "candidate_strategy_ids": list(self.candidate_strategy_ids),
            "metric_schema": ["elapsed_ms", "total_bytes_moved"],
            "memory_scope": "successful_exact_seed_only",
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity(), "context_sha256": self.context_sha256}


def build_m15_family_memory_context(
    workload: M15ParameterizedWorkloadBundle | str | Path,
    *,
    method_namespace: str,
    runtime_compatibility_sha256: str,
) -> M15FamilyMemoryContext:
    """Build a transfer context shared by instances, not by runtimes."""

    bundle = _bundle(workload)
    first_query_id = bundle.instance_ids()[0]
    contract = load_m15_parameterized_contract(bundle, first_query_id)["contract"]
    family_hash = bundle.manifest["family_compatibility_sha256"]
    if contract["family_compatibility_sha256"] != family_hash:
        raise M15FamilyMemoryError("bundle and query family identities disagree")
    feature_schema = tuple(
        (item["slot_id"], item["kind"])
        for item in contract["family_template"]["binding_schema"]
    )
    strategies = tuple(
        sorted(contract["family_template"]["candidate_strategy_ids"])
    )
    identity = {
        "schema_version": FAMILY_MEMORY_CONTEXT_SCHEMA_VERSION,
        "method_namespace": _safe_id(
            method_namespace,
            name="method_namespace",
        ),
        "family_compatibility_sha256": family_hash,
        "workload_bundle_sha256": bundle.manifest["bundle_content_sha256"],
        "runtime_compatibility_sha256": _sha256(
            runtime_compatibility_sha256,
            name="runtime_compatibility_sha256",
        ),
        "feature_schema": [
            {"slot_id": slot_id, "kind": kind}
            for slot_id, kind in feature_schema
        ],
        "candidate_strategy_ids": list(strategies),
        "metric_schema": ["elapsed_ms", "total_bytes_moved"],
        "memory_scope": "successful_exact_seed_only",
    }
    return M15FamilyMemoryContext(
        method_namespace=identity["method_namespace"],
        family_compatibility_sha256=family_hash,
        workload_bundle_sha256=bundle.manifest["bundle_content_sha256"],
        runtime_compatibility_sha256=runtime_compatibility_sha256,
        feature_schema=feature_schema,
        candidate_strategy_ids=strategies,
        context_sha256=content_hash(identity),
    )


@dataclass(frozen=True)
class M15FamilyQueryFeatures:
    family_compatibility_sha256: str
    query_instance_sha256: str
    feature_schema: tuple[tuple[str, str], ...]
    values: tuple[tuple[str, Any], ...]
    features_sha256: str

    def __post_init__(self) -> None:
        _sha256(
            self.family_compatibility_sha256,
            name="family_compatibility_sha256",
        )
        _sha256(self.query_instance_sha256, name="query_instance_sha256")
        _sha256(self.features_sha256, name="features_sha256")
        slot_ids: list[str] = []
        for slot_id, kind in self.feature_schema:
            slot_ids.append(_safe_id(slot_id, name="feature slot_id"))
            if kind not in _FEATURE_KINDS:
                raise M15FamilyMemoryError(
                    f"feature slot '{slot_id}' has unsupported kind '{kind}'"
                )
        if len(slot_ids) != len(set(slot_ids)) or slot_ids != sorted(slot_ids):
            raise M15FamilyMemoryError(
                "feature schema slot IDs must be unique and sorted"
            )
        if tuple(slot_id for slot_id, _ in self.feature_schema) != tuple(
            slot_id for slot_id, _ in self.values
        ):
            raise M15FamilyMemoryError(
                "feature values do not match the ordered feature schema"
            )
        kinds = dict(self.feature_schema)
        for slot_id, value in self.values:
            _validate_feature_value(value, kind=kinds[slot_id], slot_id=slot_id)
        expected = content_hash(self._identity())
        if self.features_sha256 != expected:
            raise M15FamilyMemoryError("query feature hash does not match its values")

    def _identity(self) -> dict[str, Any]:
        kinds = dict(self.feature_schema)
        return {
            "schema_version": FAMILY_QUERY_FEATURE_SCHEMA_VERSION,
            "family_compatibility_sha256": self.family_compatibility_sha256,
            "query_instance_sha256": self.query_instance_sha256,
            "features": [
                {"slot_id": slot_id, "kind": kinds[slot_id], "value": value}
                for slot_id, value in self.values
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity(), "features_sha256": self.features_sha256}


def build_m15_family_query_features(
    workload: M15ParameterizedWorkloadBundle | str | Path,
    *,
    query_id: str,
    context: M15FamilyMemoryContext,
) -> M15FamilyQueryFeatures:
    """Extract typed bindings without opening source or final answer oracles."""

    bundle = _bundle(workload)
    identity = load_m15_parameterized_contract(bundle, query_id)
    contract = identity["contract"]
    family_hash = contract["family_compatibility_sha256"]
    if family_hash != context.family_compatibility_sha256:
        raise M15FamilyMemoryError("query belongs to a different memory family")
    if bundle.manifest["bundle_content_sha256"] != context.workload_bundle_sha256:
        raise M15FamilyMemoryError("query belongs to a different workload context")
    schema = tuple(
        (item["slot_id"], item["kind"])
        for item in contract["family_template"]["binding_schema"]
    )
    if schema != context.feature_schema:
        raise M15FamilyMemoryError("query feature schema drifted from memory context")
    by_slot = {item["slot_id"]: item["value"] for item in contract["bindings"]}
    values = tuple((slot_id, by_slot[slot_id]) for slot_id, _ in schema)
    feature_identity = {
        "schema_version": FAMILY_QUERY_FEATURE_SCHEMA_VERSION,
        "family_compatibility_sha256": family_hash,
        "query_instance_sha256": contract["query_instance_sha256"],
        "features": [
            {"slot_id": slot_id, "kind": kind, "value": by_slot[slot_id]}
            for slot_id, kind in schema
        ],
    }
    return M15FamilyQueryFeatures(
        family_compatibility_sha256=family_hash,
        query_instance_sha256=contract["query_instance_sha256"],
        feature_schema=schema,
        values=values,
        features_sha256=content_hash(feature_identity),
    )


@dataclass(frozen=True)
class M15FamilyPlanOutcome:
    strategy_id: str
    plan_id: str
    elapsed_ms: float
    total_bytes_moved: int
    total_remote_calls: int

    def __post_init__(self) -> None:
        _safe_id(self.strategy_id, name="strategy_id")
        _safe_id(self.plan_id, name="plan_id")
        _finite_nonnegative(self.elapsed_ms, name="elapsed_ms")
        if (
            isinstance(self.total_bytes_moved, bool)
            or not isinstance(self.total_bytes_moved, int)
            or self.total_bytes_moved < 0
        ):
            raise M15FamilyMemoryError(
                "total_bytes_moved must be a nonnegative integer"
            )
        _positive_int(self.total_remote_calls, name="total_remote_calls")

    @classmethod
    def from_run(
        cls,
        *,
        strategy_id: str,
        run: FederatedRunResult,
    ) -> "M15FamilyPlanOutcome":
        if not run.success:
            raise M15FamilyMemoryError("failed plans cannot enter family memory")
        return cls(
            strategy_id=strategy_id,
            plan_id=run.plan_id,
            elapsed_ms=run.elapsed_ms,
            total_bytes_moved=run.total_bytes_moved,
            total_remote_calls=run.total_remote_calls,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "M15FamilyPlanOutcome":
        try:
            return cls(
                strategy_id=value["strategy_id"],
                plan_id=value["plan_id"],
                elapsed_ms=value["elapsed_ms"],
                total_bytes_moved=value["total_bytes_moved"],
                total_remote_calls=value["total_remote_calls"],
            )
        except KeyError as exc:
            raise M15FamilyMemoryError(f"invalid plan outcome: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "plan_id": self.plan_id,
            "elapsed_ms": self.elapsed_ms,
            "total_bytes_moved": self.total_bytes_moved,
            "total_remote_calls": self.total_remote_calls,
        }


@dataclass(frozen=True)
class M15FamilyPlanObservation:
    context_sha256: str
    method_namespace: str
    family_compatibility_sha256: str
    task_id: str
    sequence_index: int
    query_id: str
    query_instance_sha256: str
    split_role: str
    features: M15FamilyQueryFeatures
    outcomes: tuple[M15FamilyPlanOutcome, ...]
    execution_success: bool
    exact_answer: bool
    observation_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.context_sha256, name="context_sha256")
        _safe_id(self.method_namespace, name="method_namespace")
        _sha256(
            self.family_compatibility_sha256,
            name="family_compatibility_sha256",
        )
        _safe_id(self.task_id, name="task_id")
        _positive_int(self.sequence_index, name="sequence_index")
        _safe_id(self.query_id, name="query_id")
        _sha256(self.query_instance_sha256, name="query_instance_sha256")
        _sha256(self.observation_sha256, name="observation_sha256")
        if self.split_role != "seed":
            raise M15FamilyMemoryError("only seed observations may be committed")
        if (
            not isinstance(self.execution_success, bool)
            or not isinstance(self.exact_answer, bool)
            or not self.execution_success
            or not self.exact_answer
        ):
            raise M15FamilyMemoryError(
                "family memory accepts only successful exact observations"
            )
        if self.features.family_compatibility_sha256 != (
            self.family_compatibility_sha256
        ) or self.features.query_instance_sha256 != self.query_instance_sha256:
            raise M15FamilyMemoryError("observation feature identity disagrees")
        strategy_ids = tuple(item.strategy_id for item in self.outcomes)
        if not strategy_ids or strategy_ids != tuple(sorted(set(strategy_ids))):
            raise M15FamilyMemoryError(
                "observation outcomes must be nonempty, unique, and sorted"
            )
        if self.observation_sha256 != content_hash(self._identity()):
            raise M15FamilyMemoryError(
                "family plan observation hash does not match its content"
            )

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_PLAN_OBSERVATION_SCHEMA_VERSION,
            "context_sha256": self.context_sha256,
            "method_namespace": self.method_namespace,
            "family_compatibility_sha256": self.family_compatibility_sha256,
            "task_id": self.task_id,
            "sequence_index": self.sequence_index,
            "query_id": self.query_id,
            "query_instance_sha256": self.query_instance_sha256,
            "split_role": self.split_role,
            "features": self.features.to_dict(),
            "outcomes": [item.to_dict() for item in self.outcomes],
            "execution_success": self.execution_success,
            "exact_answer": self.exact_answer,
            "answer_rows_stored": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity(),
            "observation_sha256": self.observation_sha256,
        }


def build_m15_family_plan_observation(
    *,
    context: M15FamilyMemoryContext,
    features: M15FamilyQueryFeatures,
    task_id: str,
    sequence_index: int,
    query_id: str,
    split_role: str,
    outcomes: Sequence[M15FamilyPlanOutcome],
    execution_success: bool,
    exact_answer: bool,
) -> M15FamilyPlanObservation:
    ordered = tuple(sorted(outcomes, key=lambda item: item.strategy_id))
    if tuple(item.strategy_id for item in ordered) != context.candidate_strategy_ids:
        raise M15FamilyMemoryError(
            "observation outcomes do not cover the family candidate strategies"
        )
    identity = {
        "schema_version": FAMILY_PLAN_OBSERVATION_SCHEMA_VERSION,
        "context_sha256": context.context_sha256,
        "method_namespace": context.method_namespace,
        "family_compatibility_sha256": context.family_compatibility_sha256,
        "task_id": task_id,
        "sequence_index": sequence_index,
        "query_id": query_id,
        "query_instance_sha256": features.query_instance_sha256,
        "split_role": split_role,
        "features": features.to_dict(),
        "outcomes": [item.to_dict() for item in ordered],
        "execution_success": execution_success,
        "exact_answer": exact_answer,
        "answer_rows_stored": False,
    }
    return M15FamilyPlanObservation(
        context_sha256=context.context_sha256,
        method_namespace=context.method_namespace,
        family_compatibility_sha256=context.family_compatibility_sha256,
        task_id=task_id,
        sequence_index=sequence_index,
        query_id=query_id,
        query_instance_sha256=features.query_instance_sha256,
        split_role=split_role,
        features=features,
        outcomes=ordered,
        execution_success=execution_success,
        exact_answer=exact_answer,
        observation_sha256=content_hash(identity),
    )


def _features_from_dict(value: Mapping[str, Any]) -> M15FamilyQueryFeatures:
    try:
        raw_features = value["features"]
        schema = tuple(
            (item["slot_id"], item["kind"]) for item in raw_features
        )
        values = tuple((item["slot_id"], item["value"]) for item in raw_features)
        return M15FamilyQueryFeatures(
            family_compatibility_sha256=value["family_compatibility_sha256"],
            query_instance_sha256=value["query_instance_sha256"],
            feature_schema=schema,
            values=values,
            features_sha256=value["features_sha256"],
        )
    except (KeyError, TypeError) as exc:
        raise M15FamilyMemoryError(f"invalid query features: {exc}") from exc


def _observation_from_dict(value: Mapping[str, Any]) -> M15FamilyPlanObservation:
    expected_fields = {
        "schema_version",
        "context_sha256",
        "method_namespace",
        "family_compatibility_sha256",
        "task_id",
        "sequence_index",
        "query_id",
        "query_instance_sha256",
        "split_role",
        "features",
        "outcomes",
        "execution_success",
        "exact_answer",
        "answer_rows_stored",
        "observation_sha256",
    }
    if set(value) != expected_fields:
        raise M15FamilyMemoryError("stored family observation fields are invalid")
    if value["schema_version"] != FAMILY_PLAN_OBSERVATION_SCHEMA_VERSION:
        raise M15FamilyMemoryError("stored family observation version is unsupported")
    if value["answer_rows_stored"] is not False:
        raise M15FamilyMemoryError("family memory must not store answer rows")
    raw_outcomes = value["outcomes"]
    if not isinstance(raw_outcomes, list):
        raise M15FamilyMemoryError("stored family outcomes must be a list")
    return M15FamilyPlanObservation(
        context_sha256=value["context_sha256"],
        method_namespace=value["method_namespace"],
        family_compatibility_sha256=value["family_compatibility_sha256"],
        task_id=value["task_id"],
        sequence_index=value["sequence_index"],
        query_id=value["query_id"],
        query_instance_sha256=value["query_instance_sha256"],
        split_role=value["split_role"],
        features=_features_from_dict(value["features"]),
        outcomes=tuple(M15FamilyPlanOutcome.from_dict(item) for item in raw_outcomes),
        execution_success=value["execution_success"],
        exact_answer=value["exact_answer"],
        observation_sha256=value["observation_sha256"],
    )


@dataclass(frozen=True)
class M15FamilyMemoryView:
    context_sha256: str
    current_sequence_index: int
    eligible_task_ids: tuple[str, ...]
    observations: tuple[M15FamilyPlanObservation, ...]
    view_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.context_sha256, name="context_sha256")
        _positive_int(self.current_sequence_index, name="current_sequence_index")
        if tuple(item.task_id for item in self.observations) != self.eligible_task_ids:
            raise M15FamilyMemoryError(
                "memory view tasks disagree with its observation order"
            )
        if any(
            item.context_sha256 != self.context_sha256
            or item.sequence_index >= self.current_sequence_index
            for item in self.observations
        ):
            raise M15FamilyMemoryError(
                "memory view contains incompatible or non-predecessor observations"
            )
        if self.view_sha256 != content_hash(self._identity()):
            raise M15FamilyMemoryError("memory view hash does not match its content")

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_MEMORY_VIEW_SCHEMA_VERSION,
            "context_sha256": self.context_sha256,
            "current_sequence_index": self.current_sequence_index,
            "eligible_task_ids": list(self.eligible_task_ids),
            "observation_sha256": [
                item.observation_sha256 for item in self.observations
            ],
            "writes_visible_from_current_task": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._identity(),
            "view_sha256": self.view_sha256,
            "observations": [item.to_dict() for item in self.observations],
        }


class M15FamilyPlanMemory:
    """Append-only adapter that exposes only an explicitly frozen view."""

    def __init__(self, store: MemoryStore, context: M15FamilyMemoryContext):
        self.store = store
        self.context = context

    def _key(self, task_id: str) -> str:
        return (
            f"{_MEMORY_KEY_PREFIX}/{self.context.method_namespace}/"
            f"{self.context.context_sha256}/{task_id}"
        )

    def commit(
        self,
        observation: M15FamilyPlanObservation,
        *,
        source: str,
    ) -> None:
        if observation.context_sha256 != self.context.context_sha256:
            raise M15FamilyMemoryError("cross-context memory write is prohibited")
        if observation.method_namespace != self.context.method_namespace:
            raise M15FamilyMemoryError("cross-method memory write is prohibited")
        if observation.family_compatibility_sha256 != (
            self.context.family_compatibility_sha256
        ):
            raise M15FamilyMemoryError("cross-family memory write is prohibited")
        key = self._key(observation.task_id)
        if self.store.get(MemoryScope.EXECUTION, key) is not None:
            raise M15FamilyMemoryError(
                f"family memory task '{observation.task_id}' already exists"
            )
        self.store.put(
            MemoryRecord(
                scope=MemoryScope.EXECUTION,
                key=key,
                value=observation.to_dict(),
                source=source,
                version=observation.observation_sha256,
                confidence=1.0,
            )
        )

    def freeze(
        self,
        *,
        current_sequence_index: int,
        eligible_task_ids: Sequence[str],
    ) -> M15FamilyMemoryView:
        _positive_int(current_sequence_index, name="current_sequence_index")
        task_ids = tuple(
            _safe_id(task_id, name="eligible task_id")
            for task_id in eligible_task_ids
        )
        if len(task_ids) != len(set(task_ids)):
            raise M15FamilyMemoryError("eligible task IDs must be unique")
        observations: list[M15FamilyPlanObservation] = []
        for task_id in task_ids:
            record = self.store.get(MemoryScope.EXECUTION, self._key(task_id))
            if record is None:
                raise M15FamilyMemoryError(
                    f"eligible family memory task '{task_id}' is missing"
                )
            if not isinstance(record.value, Mapping):
                raise M15FamilyMemoryError(
                    "family memory record value must be an object"
                )
            if record.version != record.value.get("observation_sha256"):
                raise M15FamilyMemoryError(
                    "memory record version disagrees with observation identity"
                )
            observation = _observation_from_dict(record.value)
            if observation.context_sha256 != self.context.context_sha256:
                raise M15FamilyMemoryError("cross-context memory read is prohibited")
            if observation.sequence_index >= current_sequence_index:
                raise M15FamilyMemoryError(
                    "current or future task memory is not visible"
                )
            observations.append(observation)
        ordered = tuple(sorted(observations, key=lambda item: item.sequence_index))
        ordered_ids = tuple(item.task_id for item in ordered)
        identity = {
            "schema_version": FAMILY_MEMORY_VIEW_SCHEMA_VERSION,
            "context_sha256": self.context.context_sha256,
            "current_sequence_index": current_sequence_index,
            "eligible_task_ids": list(ordered_ids),
            "observation_sha256": [item.observation_sha256 for item in ordered],
            "writes_visible_from_current_task": False,
        }
        return M15FamilyMemoryView(
            context_sha256=self.context.context_sha256,
            current_sequence_index=current_sequence_index,
            eligible_task_ids=ordered_ids,
            observations=ordered,
            view_sha256=content_hash(identity),
        )


def _feature_distance(
    left: M15FamilyQueryFeatures,
    right: M15FamilyQueryFeatures,
) -> float:
    if (
        left.family_compatibility_sha256 != right.family_compatibility_sha256
        or left.feature_schema != right.feature_schema
    ):
        raise M15FamilyMemoryError("cannot compare features across query families")
    left_values = dict(left.values)
    right_values = dict(right.values)
    components: list[float] = []
    for slot_id, kind in left.feature_schema:
        left_value = left_values[slot_id]
        right_value = right_values[slot_id]
        if kind == "integer":
            if (
                isinstance(left_value, bool)
                or not isinstance(left_value, int)
                or isinstance(right_value, bool)
                or not isinstance(right_value, int)
            ):
                raise M15FamilyMemoryError("integer feature value is invalid")
            scale = max(abs(left_value), abs(right_value), 1)
            components.append(min(1.0, abs(left_value - right_value) / scale))
        elif kind == "date":
            try:
                delta = abs(
                    date.fromisoformat(str(left_value)).toordinal()
                    - date.fromisoformat(str(right_value)).toordinal()
                )
            except ValueError as exc:
                raise M15FamilyMemoryError("date feature value is invalid") from exc
            components.append(min(1.0, delta / 365.0))
        else:
            components.append(0.0 if left_value == right_value else 1.0)
    return sum(components) / len(components)


@dataclass(frozen=True)
class M15FamilyTransferSelection:
    context_sha256: str
    memory_view_sha256: str
    query_instance_sha256: str
    model_version: str
    selection_mode: str
    selected_strategy_id: str
    predictions: tuple[Mapping[str, Any], ...]
    cold_start: bool
    selection_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.context_sha256, name="context_sha256")
        _sha256(self.memory_view_sha256, name="memory_view_sha256")
        _sha256(self.query_instance_sha256, name="query_instance_sha256")
        _safe_id(self.model_version, name="model_version")
        _safe_id(self.selection_mode, name="selection_mode")
        _safe_id(self.selected_strategy_id, name="selected_strategy_id")
        if not isinstance(self.cold_start, bool):
            raise M15FamilyMemoryError("cold_start must be boolean")
        object.__setattr__(
            self,
            "predictions",
            tuple(MappingProxyType(dict(item)) for item in self.predictions),
        )
        _sha256(self.selection_sha256, name="selection_sha256")
        if self.selection_sha256 != content_hash(self._identity()):
            raise M15FamilyMemoryError(
                "family transfer selection hash does not match its content"
            )

    def _identity(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_TRANSFER_SELECTION_SCHEMA_VERSION,
            "context_sha256": self.context_sha256,
            "memory_view_sha256": self.memory_view_sha256,
            "query_instance_sha256": self.query_instance_sha256,
            "model_version": self.model_version,
            "selection_mode": self.selection_mode,
            "selected_strategy_id": self.selected_strategy_id,
            "predictions": [dict(item) for item in self.predictions],
            "cold_start": self.cold_start,
            "objective": "min_predicted_elapsed_ms_then_bytes",
            "oracle_inputs": [],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity(), "selection_sha256": self.selection_sha256}


def select_m15_family_plan(
    *,
    context: M15FamilyMemoryContext,
    features: M15FamilyQueryFeatures,
    memory_view: M15FamilyMemoryView,
    k: int = 3,
    cold_start_strategy_id: str = "parallel_hash_join",
) -> M15FamilyTransferSelection:
    """Select one exact strategy from a frozen family-local memory view."""

    _positive_int(k, name="k")
    if memory_view.context_sha256 != context.context_sha256:
        raise M15FamilyMemoryError("memory view belongs to a different context")
    if features.family_compatibility_sha256 != (
        context.family_compatibility_sha256
    ) or features.feature_schema != context.feature_schema:
        raise M15FamilyMemoryError("query features belong to a different family")
    if cold_start_strategy_id not in context.candidate_strategy_ids:
        raise M15FamilyMemoryError("cold-start strategy is not a family candidate")

    predictions: list[dict[str, Any]] = []
    if not memory_view.observations:
        selected = cold_start_strategy_id
        mode = "cold_start_fallback"
        cold_start = True
    else:
        distances = sorted(
            (
                (_feature_distance(features, observation.features), observation)
                for observation in memory_view.observations
            ),
            key=lambda item: (item[0], item[1].sequence_index, item[1].task_id),
        )
        neighbors = distances[: min(k, len(distances))]
        for strategy_id in context.candidate_strategy_ids:
            weighted_elapsed = 0.0
            weighted_bytes = 0.0
            total_weight = 0.0
            neighbor_payload: list[dict[str, Any]] = []
            zero_distance = [item for item in neighbors if item[0] == 0.0]
            selected_neighbors = zero_distance or neighbors
            for distance, observation in selected_neighbors:
                outcome = next(
                    item
                    for item in observation.outcomes
                    if item.strategy_id == strategy_id
                )
                weight = 1.0 if zero_distance else 1.0 / max(distance, 1e-12)
                total_weight += weight
                weighted_elapsed += weight * outcome.elapsed_ms
                weighted_bytes += weight * outcome.total_bytes_moved
                neighbor_payload.append(
                    {
                        "task_id": observation.task_id,
                        "query_instance_sha256": observation.query_instance_sha256,
                        "distance": distance,
                        "weight": weight,
                        "elapsed_ms": outcome.elapsed_ms,
                        "total_bytes_moved": outcome.total_bytes_moved,
                    }
                )
            predictions.append(
                {
                    "strategy_id": strategy_id,
                    "predicted_elapsed_ms": weighted_elapsed / total_weight,
                    "predicted_total_bytes_moved": weighted_bytes / total_weight,
                    "neighbors": neighbor_payload,
                }
            )
        selected = min(
            predictions,
            key=lambda item: (
                item["predicted_elapsed_ms"],
                item["predicted_total_bytes_moved"],
                item["strategy_id"],
            ),
        )["strategy_id"]
        mode = "family_local_knn"
        cold_start = False

    identity = {
        "schema_version": FAMILY_TRANSFER_SELECTION_SCHEMA_VERSION,
        "context_sha256": context.context_sha256,
        "memory_view_sha256": memory_view.view_sha256,
        "query_instance_sha256": features.query_instance_sha256,
        "model_version": FAMILY_TRANSFER_MODEL_VERSION,
        "selection_mode": mode,
        "selected_strategy_id": selected,
        "predictions": predictions,
        "cold_start": cold_start,
        "objective": "min_predicted_elapsed_ms_then_bytes",
        "oracle_inputs": [],
    }
    return M15FamilyTransferSelection(
        context_sha256=context.context_sha256,
        memory_view_sha256=memory_view.view_sha256,
        query_instance_sha256=features.query_instance_sha256,
        model_version=FAMILY_TRANSFER_MODEL_VERSION,
        selection_mode=mode,
        selected_strategy_id=selected,
        predictions=tuple(predictions),
        cold_start=cold_start,
        selection_sha256=content_hash(identity),
    )
