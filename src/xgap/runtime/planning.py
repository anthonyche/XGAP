"""Observation-bound selection among equivalent federated execution plans."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from xgap.runtime.contracts import (
    FederatedExecutionPlan,
    JsonMap,
    RuntimeNode,
    RuntimeNodeKind,
    RuntimeNodeResult,
    RuntimeNodeStatus,
)
from xgap.tools.contracts import ToolResult, ToolStatus


class FederatedPlanningError(ValueError):
    """Raised when candidates or their observation evidence are incomplete."""


def _finite_number(value: object, *, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FederatedPlanningError(f"{field} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise FederatedPlanningError(f"{field} must be finite")
    return converted


def _nonnegative_integer(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FederatedPlanningError(f"{field} must be a nonnegative integer")
    return value


def _encoded_size(rows: object) -> int:
    return len(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    )


@dataclass(frozen=True)
class RemoteEstimate:
    observation_key: str
    backend_id: str
    elapsed_ms: float
    row_count: int
    row_width_bytes: float
    source: str
    version: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str)
            for value in (
                self.observation_key,
                self.backend_id,
                self.source,
                self.version,
            )
        ):
            raise FederatedPlanningError("remote estimate identities must be strings")
        if any(
            not value.strip()
            for value in (
                self.observation_key,
                self.backend_id,
                self.source,
                self.version,
            )
        ):
            raise FederatedPlanningError("remote estimate identities must be nonempty")
        elapsed_ms = _finite_number(
            self.elapsed_ms,
            field="remote estimate elapsed_ms",
        )
        if elapsed_ms < 0:
            raise FederatedPlanningError(
                "remote estimate elapsed_ms must be finite and nonnegative"
            )
        _nonnegative_integer(
            self.row_count,
            field="remote estimate row_count",
        )
        row_width = _finite_number(
            self.row_width_bytes,
            field="remote estimate row width",
        )
        if row_width <= 0:
            raise FederatedPlanningError(
                "remote estimate row width must be finite and positive"
            )

    @property
    def output_bytes(self) -> float:
        return self.row_count * self.row_width_bytes

    @classmethod
    def from_tool_result(
        cls,
        observation_key: str,
        result: ToolResult,
    ) -> "RemoteEstimate":
        if result.status is not ToolStatus.SUCCESS or not isinstance(result.value, Mapping):
            raise FederatedPlanningError(
                "remote estimate requires a successful backend observation"
            )
        value = result.value
        operation = value.get("operation")
        if operation not in {"profile", "sample"}:
            raise FederatedPlanningError(
                "only profile or sample observations estimate a remote node"
            )
        observation = value.get("observation")
        if not isinstance(observation, Mapping):
            raise FederatedPlanningError("backend observation report is missing")
        rows = observation.get("rows")
        row_count = observation.get("row_count")
        if (
            not isinstance(rows, list)
            or not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count != len(rows)
        ):
            raise FederatedPlanningError("backend observation rows and row_count disagree")
        elapsed = observation.get("elapsed_ms")
        if not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool):
            raise FederatedPlanningError("backend observation elapsed_ms is unavailable")
        backend_id = value.get("backend_id")
        catalog_id = value.get("catalog_id")
        catalog_version = value.get("catalog_version")
        artifact_sha256 = value.get("artifact_sha256")
        if not all(
            isinstance(item, str) and item
            for item in (backend_id, catalog_id, catalog_version, artifact_sha256)
        ):
            raise FederatedPlanningError("backend observation provenance is incomplete")
        encoded = _encoded_size(rows)
        row_width = max(1.0, encoded / max(row_count, 1))
        return cls(
            observation_key=observation_key,
            backend_id=backend_id,
            elapsed_ms=float(elapsed),
            row_count=row_count,
            row_width_bytes=row_width,
            source=f"{catalog_id}/{value.get('artifact_id')}/{artifact_sha256}",
            version=catalog_version,
        )

    @classmethod
    def from_runtime_result(
        cls,
        observation_key: str,
        result: RuntimeNodeResult,
        *,
        source: str,
        version: str,
    ) -> "RemoteEstimate":
        if result.status is not RuntimeNodeStatus.SUCCESS:
            raise FederatedPlanningError(
                "remote estimate requires a successful runtime result"
            )
        if result.kind not in {
            RuntimeNodeKind.REMOTE_QUERY,
            RuntimeNodeKind.REMOTE_BIND_QUERY,
        }:
            raise FederatedPlanningError(
                "remote estimate requires a remote runtime result"
            )
        backend_id = result.metadata.get("backend_id")
        if not isinstance(backend_id, str) or not backend_id:
            raise FederatedPlanningError("runtime result backend provenance is missing")
        tool_metrics = result.metadata.get("tool_metrics", {})
        backend_elapsed = (
            tool_metrics.get("elapsed_ms")
            if isinstance(tool_metrics, Mapping)
            else None
        )
        elapsed_ms = (
            float(backend_elapsed)
            if isinstance(backend_elapsed, (int, float))
            and not isinstance(backend_elapsed, bool)
            else result.elapsed_ms
        )
        row_width = max(1.0, result.output_bytes / max(result.row_count, 1))
        return cls(
            observation_key=observation_key,
            backend_id=backend_id,
            elapsed_ms=elapsed_ms,
            row_count=result.row_count,
            row_width_bytes=row_width,
            source=source,
            version=version,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RemoteEstimate":
        try:
            return cls(
                observation_key=data["observation_key"],
                backend_id=data["backend_id"],
                elapsed_ms=_finite_number(
                    data["elapsed_ms"],
                    field="remote estimate elapsed_ms",
                ),
                row_count=_nonnegative_integer(
                    data["row_count"],
                    field="remote estimate row_count",
                ),
                row_width_bytes=_finite_number(
                    data["row_width_bytes"],
                    field="remote estimate row width",
                ),
                source=data["source"],
                version=data["version"],
            )
        except KeyError as exc:
            raise FederatedPlanningError(f"invalid remote estimate: {exc}") from exc

    def to_dict(self) -> JsonMap:
        return {
            "observation_key": self.observation_key,
            "backend_id": self.backend_id,
            "elapsed_ms": self.elapsed_ms,
            "row_count": self.row_count,
            "row_width_bytes": self.row_width_bytes,
            "output_bytes": self.output_bytes,
            "source": self.source,
            "version": self.version,
        }


@dataclass(frozen=True)
class PlanObservationSnapshot:
    snapshot_id: str
    version: str
    estimates: tuple[RemoteEstimate, ...]
    bandwidth_bytes_per_ms: float
    exchange_fixed_ms: float = 0.0
    coordinator_row_ms: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not isinstance(self.version, str):
            raise FederatedPlanningError("snapshot id and version must be strings")
        if not self.snapshot_id.strip() or not self.version.strip():
            raise FederatedPlanningError("snapshot id and version must be nonempty")
        keys = [item.observation_key for item in self.estimates]
        if len(keys) != len(set(keys)):
            raise FederatedPlanningError("snapshot observation keys must be unique")
        bandwidth = _finite_number(
            self.bandwidth_bytes_per_ms,
            field="snapshot bandwidth",
        )
        if bandwidth <= 0:
            raise FederatedPlanningError("snapshot bandwidth must be finite and positive")
        for name, value in (
            ("exchange_fixed_ms", self.exchange_fixed_ms),
            ("coordinator_row_ms", self.coordinator_row_ms),
        ):
            converted = _finite_number(value, field=f"snapshot {name}")
            if converted < 0:
                raise FederatedPlanningError(f"snapshot {name} must be finite and nonnegative")

    @property
    def by_key(self) -> dict[str, RemoteEstimate]:
        return {item.observation_key: item for item in self.estimates}

    def to_dict(self) -> JsonMap:
        return {
            "snapshot_id": self.snapshot_id,
            "version": self.version,
            "estimates": [item.to_dict() for item in self.estimates],
            "bandwidth_bytes_per_ms": self.bandwidth_bytes_per_ms,
            "exchange_fixed_ms": self.exchange_fixed_ms,
            "coordinator_row_ms": self.coordinator_row_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanObservationSnapshot":
        raw_estimates = data.get("estimates")
        if not isinstance(raw_estimates, list) or any(
            not isinstance(item, Mapping) for item in raw_estimates
        ):
            raise FederatedPlanningError("snapshot estimates must be a list of objects")
        try:
            return cls(
                snapshot_id=data["snapshot_id"],
                version=data["version"],
                estimates=tuple(
                    RemoteEstimate.from_dict(item) for item in raw_estimates
                ),
                bandwidth_bytes_per_ms=_finite_number(
                    data["bandwidth_bytes_per_ms"],
                    field="snapshot bandwidth",
                ),
                exchange_fixed_ms=_finite_number(
                    data.get("exchange_fixed_ms", 0.0),
                    field="snapshot exchange_fixed_ms",
                ),
                coordinator_row_ms=_finite_number(
                    data.get("coordinator_row_ms", 0.0),
                    field="snapshot coordinator_row_ms",
                ),
            )
        except KeyError as exc:
            raise FederatedPlanningError(f"invalid observation snapshot: {exc}") from exc

    def with_estimates(
        self,
        estimates: tuple[RemoteEstimate, ...],
        *,
        version: str,
    ) -> "PlanObservationSnapshot":
        update_keys = [item.observation_key for item in estimates]
        if len(update_keys) != len(set(update_keys)):
            raise FederatedPlanningError(
                "updated snapshot observation keys must be unique"
            )
        merged = self.by_key
        merged.update({item.observation_key: item for item in estimates})
        return PlanObservationSnapshot(
            snapshot_id=self.snapshot_id,
            version=version,
            estimates=tuple(merged[key] for key in sorted(merged)),
            bandwidth_bytes_per_ms=self.bandwidth_bytes_per_ms,
            exchange_fixed_ms=self.exchange_fixed_ms,
            coordinator_row_ms=self.coordinator_row_ms,
        )


@dataclass(frozen=True)
class FederatedPlanCandidate:
    plan: FederatedExecutionPlan
    semantic_equivalence_key: str

    def __post_init__(self) -> None:
        if not self.semantic_equivalence_key.strip():
            raise FederatedPlanningError("semantic equivalence key must be nonempty")


@dataclass(frozen=True)
class PlanCostEstimate:
    plan_id: str
    predicted_latency_ms: float
    predicted_transfer_bytes: float
    remote_calls: int
    observation_keys: tuple[str, ...]
    node_completion_ms: Mapping[str, float]
    node_row_counts: Mapping[str, float]

    def to_dict(self) -> JsonMap:
        return {
            "plan_id": self.plan_id,
            "predicted_latency_ms": self.predicted_latency_ms,
            "predicted_transfer_bytes": self.predicted_transfer_bytes,
            "remote_calls": self.remote_calls,
            "observation_keys": list(self.observation_keys),
            "node_completion_ms": dict(self.node_completion_ms),
            "node_row_counts": dict(self.node_row_counts),
        }


@dataclass(frozen=True)
class FederatedPlanSelection:
    semantic_equivalence_key: str
    snapshot_id: str
    snapshot_version: str
    selected_plan_id: str
    estimates: tuple[PlanCostEstimate, ...]

    def to_dict(self) -> JsonMap:
        return {
            "semantic_equivalence_key": self.semantic_equivalence_key,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "selected_plan_id": self.selected_plan_id,
            "estimates": [item.to_dict() for item in self.estimates],
            "selection_rule": (
                "minimum predicted latency, then transfer bytes, remote calls, plan id"
            ),
        }


@dataclass(frozen=True)
class _NodeEstimate:
    completion_ms: float
    row_count: float
    row_width_bytes: float


class FederatedPlanSelector:
    """Select one lowest-cost plan within one exact semantic equivalence class."""

    def select(
        self,
        candidates: tuple[FederatedPlanCandidate, ...],
        snapshot: PlanObservationSnapshot,
    ) -> FederatedPlanSelection:
        if not candidates:
            raise FederatedPlanningError("at least one federated plan candidate is required")
        equivalence_keys = {item.semantic_equivalence_key for item in candidates}
        if len(equivalence_keys) != 1:
            raise FederatedPlanningError(
                "one physical selection may contain only one semantic equivalence class"
            )
        plan_ids = [item.plan.plan_id for item in candidates]
        if len(plan_ids) != len(set(plan_ids)):
            raise FederatedPlanningError("candidate plan ids must be unique")
        estimates = tuple(
            self.estimate(candidate.plan, snapshot)
            for candidate in sorted(candidates, key=lambda item: item.plan.plan_id)
        )
        selected = min(
            estimates,
            key=lambda item: (
                item.predicted_latency_ms,
                item.predicted_transfer_bytes,
                item.remote_calls,
                item.plan_id,
            ),
        )
        return FederatedPlanSelection(
            semantic_equivalence_key=next(iter(equivalence_keys)),
            snapshot_id=snapshot.snapshot_id,
            snapshot_version=snapshot.version,
            selected_plan_id=selected.plan_id,
            estimates=estimates,
        )

    def estimate(
        self,
        plan: FederatedExecutionPlan,
        snapshot: PlanObservationSnapshot,
    ) -> PlanCostEstimate:
        nodes = {item.node_id: item for item in plan.nodes}
        pending = set(nodes)
        estimates: dict[str, _NodeEstimate] = {}
        used_observations: set[str] = set()
        transfer_bytes = 0.0
        remote_calls = 0
        while pending:
            ready = [
                nodes[node_id]
                for node_id in sorted(pending)
                if all(input_id in estimates for input_id in nodes[node_id].inputs)
            ]
            if not ready:
                raise FederatedPlanningError("validated plan made no estimation progress")
            for node in ready:
                state, moved, calls, observation_key = self._estimate_node(
                    node,
                    estimates,
                    snapshot,
                )
                estimates[node.node_id] = state
                transfer_bytes += moved
                remote_calls += calls
                if observation_key is not None:
                    used_observations.add(observation_key)
                pending.remove(node.node_id)
        latency = max(estimates[root].completion_ms for root in plan.roots)
        return PlanCostEstimate(
            plan_id=plan.plan_id,
            predicted_latency_ms=latency,
            predicted_transfer_bytes=transfer_bytes,
            remote_calls=remote_calls,
            observation_keys=tuple(sorted(used_observations)),
            node_completion_ms={
                node.node_id: estimates[node.node_id].completion_ms for node in plan.nodes
            },
            node_row_counts={
                node.node_id: estimates[node.node_id].row_count for node in plan.nodes
            },
        )

    @staticmethod
    def _estimate_node(
        node: RuntimeNode,
        estimates: Mapping[str, _NodeEstimate],
        snapshot: PlanObservationSnapshot,
    ) -> tuple[_NodeEstimate, float, int, str | None]:
        inputs = [estimates[input_id] for input_id in node.inputs]
        ready_ms = max((item.completion_ms for item in inputs), default=0.0)
        if node.kind in {
            RuntimeNodeKind.REMOTE_QUERY,
            RuntimeNodeKind.REMOTE_BIND_QUERY,
        }:
            observation_key = node.parameters.get("observation_key")
            if not isinstance(observation_key, str) or not observation_key:
                raise FederatedPlanningError(
                    f"remote node '{node.node_id}' has no observation_key"
                )
            remote = snapshot.by_key.get(observation_key)
            if remote is None:
                raise FederatedPlanningError(
                    f"snapshot has no estimate '{observation_key}'"
                )
            backend_id = node.parameters.get("backend_id")
            if backend_id != remote.backend_id:
                raise FederatedPlanningError(
                    f"estimate '{observation_key}' belongs to backend "
                    f"'{remote.backend_id}', not '{backend_id}'"
                )
            return (
                _NodeEstimate(
                    ready_ms + remote.elapsed_ms,
                    float(remote.row_count),
                    remote.row_width_bytes,
                ),
                0.0,
                1,
                observation_key,
            )
        if node.kind is RuntimeNodeKind.EXCHANGE:
            source = inputs[0]
            moved = source.row_count * source.row_width_bytes
            duration = snapshot.exchange_fixed_ms + moved / snapshot.bandwidth_bytes_per_ms
            return (
                _NodeEstimate(
                    ready_ms + duration,
                    source.row_count,
                    source.row_width_bytes,
                ),
                moved,
                0,
                None,
            )
        if node.kind is RuntimeNodeKind.COORDINATOR_JOIN:
            left, right = inputs
            selectivity = FederatedPlanSelector._fraction(node, "join_selectivity", 1.0)
            rows = min(left.row_count, right.row_count) * selectivity
            duration = (left.row_count + right.row_count) * snapshot.coordinator_row_ms
            return (
                _NodeEstimate(
                    ready_ms + duration,
                    rows,
                    left.row_width_bytes + right.row_width_bytes,
                ),
                0.0,
                0,
                None,
            )
        if node.kind is RuntimeNodeKind.COORDINATOR_PATH_COMPOSE:
            # Explicit Cartesian/power proxy: path concatenation can expand rows,
            # unlike a unary filter. This is uncalibrated, not a measured bound.
            operation = node.parameters.get("operation")
            if operation == "join" and len(inputs) in (1, 2):
                left, right = inputs[0], inputs[-1]
                rows = left.row_count * right.row_count
                work = rows + left.row_count + right.row_count
                width = left.row_width_bytes + right.row_width_bytes
            elif operation == "recursive" and len(inputs) == 1:
                depth = node.parameters.get("max_depth")
                if type(depth) is not int or depth <= 0:
                    raise FederatedPlanningError("Scoped path cost requires finite positive depth")
                source = inputs[0]
                rows, frontier = 0.0, 1.0
                for _ in range(depth):
                    frontier *= source.row_count
                    rows += frontier
                work, width = rows, source.row_width_bytes * depth
            else:
                raise FederatedPlanningError("Invalid scoped path cost operation/arity")
            duration = work * snapshot.coordinator_row_ms
            if not all(math.isfinite(x) for x in (rows, width, duration)):
                raise FederatedPlanningError("Scoped path cost exceeds finite numeric range")
            return _NodeEstimate(ready_ms + duration, rows, width), 0.0, 0, None
        if node.kind is RuntimeNodeKind.COORDINATOR_SEMI_JOIN:
            left, right = inputs
            selectivity = FederatedPlanSelector._fraction(node, "semi_join_selectivity", 1.0)
            rows = left.row_count * selectivity
            duration = (left.row_count + right.row_count) * snapshot.coordinator_row_ms
            return (
                _NodeEstimate(ready_ms + duration, rows, left.row_width_bytes),
                0.0,
                0,
                None,
            )
        if node.kind is RuntimeNodeKind.COORDINATOR_GROUP_AGGREGATE:
            source = inputs[0]
            reduction = FederatedPlanSelector._fraction(
                node, "group_reduction_fraction", 1.0
            )
            rows = (1.0 if node.parameters.get("allow_global") and not node.parameters.get("group_by")
                    else source.row_count * reduction)
            duration = source.row_count * snapshot.coordinator_row_ms
            return (
                _NodeEstimate(ready_ms + duration, rows, source.row_width_bytes),
                0.0,
                0,
                None,
            )
        if node.kind is RuntimeNodeKind.COORDINATOR_SORT_LIMIT:
            source = inputs[0]
            limit = node.parameters.get("limit")
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                raise FederatedPlanningError(
                    f"runtime node '{node.node_id}' limit must be a positive integer"
                )
            rows = min(source.row_count, float(limit))
            duration = source.row_count * snapshot.coordinator_row_ms
            return (
                _NodeEstimate(ready_ms + duration, rows, source.row_width_bytes),
                0.0,
                0,
                None,
            )
        if node.kind is RuntimeNodeKind.MERGE:
            rows = sum(item.row_count for item in inputs)
            width = max((item.row_width_bytes for item in inputs), default=1.0)
            duration = rows * snapshot.coordinator_row_ms
            return _NodeEstimate(ready_ms + duration, rows, width), 0.0, 0, None
        source = inputs[0]
        if node.kind in {
            RuntimeNodeKind.COORDINATOR_FILTER, RuntimeNodeKind.COORDINATOR_PATH_SELECT,
            RuntimeNodeKind.COORDINATOR_ROW_PROJECT, RuntimeNodeKind.NORMALIZE_NODE_BINDINGS,
        }:
            # Defaults preserve input cardinality/width; these are explicit
            # conservative proxy assumptions, not measured selectivity.
            rows = source.row_count * FederatedPlanSelector._fraction(node, "output_row_fraction", 1.0)
            width = source.row_width_bytes * FederatedPlanSelector._fraction(node, "width_fraction", 1.0)
            return (_NodeEstimate(ready_ms + source.row_count * snapshot.coordinator_row_ms, rows, width),
                    0.0, 0, None)
        if node.kind is RuntimeNodeKind.PROJECT:
            width_fraction = FederatedPlanSelector._fraction(
                node,
                "width_fraction",
                1.0,
            )
            width = source.row_width_bytes * width_fraction
        else:
            width = source.row_width_bytes
        duration = source.row_count * snapshot.coordinator_row_ms
        return (
            _NodeEstimate(ready_ms + duration, source.row_count, width),
            0.0,
            0,
            None,
        )

    @staticmethod
    def _fraction(node: RuntimeNode, name: str, default: float) -> float:
        value = node.parameters.get(name, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise FederatedPlanningError(
                f"runtime node '{node.node_id}' {name} must be numeric"
            )
        selected = float(value)
        if not math.isfinite(selected) or not 0.0 <= selected <= 1.0:
            raise FederatedPlanningError(
                f"runtime node '{node.node_id}' {name} must be in [0, 1]"
            )
        return selected
