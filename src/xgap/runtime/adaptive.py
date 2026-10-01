"""Bounded observation-driven continuation and cross-task plan memory."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Mapping

from xgap.agent.memory import MemoryRecord, MemoryScope, MemoryStore
from xgap.runtime.contracts import (
    FederatedExecutionPlan,
    FederatedRunResult,
    JsonMap,
    RuntimeNode,
    RuntimeNodeKind,
    RuntimeNodeResult,
)
from xgap.runtime.planning import (
    FederatedPlanCandidate,
    FederatedPlanSelection,
    FederatedPlanSelector,
    FederatedPlanningError,
    PlanObservationSnapshot,
    RemoteEstimate,
)
from xgap.runtime.scheduler import FederatedScheduler


class AdaptiveExecutionError(ValueError):
    """Raised when an adaptive execution contract is invalid."""


@dataclass(frozen=True)
class ProbeObservation:
    node_id: str
    observation_key: str

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.observation_key.strip():
            raise AdaptiveExecutionError(
                "probe node id and observation key must be nonempty"
            )


@dataclass(frozen=True)
class ReplanPolicy:
    cardinality_factor_threshold: float = 2.0
    latency_factor_threshold: float = 2.0
    max_replans: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("cardinality_factor_threshold", self.cardinality_factor_threshold),
            ("latency_factor_threshold", self.latency_factor_threshold),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 1.0
            ):
                raise AdaptiveExecutionError(f"{name} must be finite and greater than 1")
        if isinstance(self.max_replans, bool) or self.max_replans not in {0, 1}:
            raise AdaptiveExecutionError("the current adaptive executor allows 0 or 1 replan")


@dataclass(frozen=True)
class AdaptiveFederatedRun:
    initial_selection: FederatedPlanSelection
    selection_after_probe: FederatedPlanSelection | None
    snapshot_before: PlanObservationSnapshot
    snapshot_after: PlanObservationSnapshot
    probe_run: FederatedRunResult
    final_run: FederatedRunResult | None
    replan_reasons: tuple[str, ...]
    replan_count: int
    reused_node_ids: tuple[str, ...]
    elapsed_ms: float
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None and self.final_run is not None and self.final_run.success

    @property
    def selected_plan_id(self) -> str:
        if self.final_run is not None:
            return self.final_run.plan_id
        return self.initial_selection.selected_plan_id

    @property
    def total_remote_calls(self) -> int:
        if self.final_run is not None:
            return self.final_run.total_remote_calls
        return self.probe_run.total_remote_calls

    @property
    def total_bytes_moved(self) -> int:
        if self.final_run is not None:
            return self.final_run.total_bytes_moved
        return self.probe_run.total_bytes_moved

    def to_dict(self) -> JsonMap:
        return {
            "success": self.success,
            "error": self.error,
            "initial_selection": self.initial_selection.to_dict(),
            "selection_after_probe": (
                self.selection_after_probe.to_dict()
                if self.selection_after_probe is not None
                else None
            ),
            "snapshot_before": self.snapshot_before.to_dict(),
            "snapshot_after": self.snapshot_after.to_dict(),
            "probe_run": self.probe_run.to_dict(),
            "final_run": self.final_run.to_dict() if self.final_run is not None else None,
            "selected_plan_id": self.selected_plan_id,
            "replan_reasons": list(self.replan_reasons),
            "replan_count": self.replan_count,
            "reused_node_ids": list(self.reused_node_ids),
            "elapsed_ms": self.elapsed_ms,
            "total_remote_calls": self.total_remote_calls,
            "total_bytes_moved": self.total_bytes_moved,
        }


class PlanSnapshotMemory:
    """Store immutable snapshot versions in the agent's execution memory."""

    KEY_PREFIX = "federated-plan-snapshot"

    def __init__(self, store: MemoryStore):
        self.store = store

    @classmethod
    def _key(cls, snapshot_id: str, version: str) -> str:
        return f"{cls.KEY_PREFIX}/{snapshot_id}/{version}"

    def put(
        self,
        snapshot: PlanObservationSnapshot,
        *,
        source: str,
        confidence: float = 1.0,
    ) -> None:
        key = self._key(snapshot.snapshot_id, snapshot.version)
        if self.store.get(MemoryScope.EXECUTION, key) is not None:
            raise AdaptiveExecutionError(
                f"plan snapshot '{snapshot.snapshot_id}/{snapshot.version}' already exists"
            )
        self.store.put(
            MemoryRecord(
                scope=MemoryScope.EXECUTION,
                key=key,
                value=snapshot.to_dict(),
                source=source,
                version=snapshot.version,
                confidence=confidence,
            )
        )

    def get(self, snapshot_id: str, version: str) -> PlanObservationSnapshot | None:
        record = self.store.get(
            MemoryScope.EXECUTION,
            self._key(snapshot_id, version),
        )
        if record is None:
            return None
        return self._decode(record, snapshot_id=snapshot_id, version=version)

    def latest(self, snapshot_id: str) -> PlanObservationSnapshot | None:
        prefix = f"{self.KEY_PREFIX}/{snapshot_id}/"
        records = tuple(
            record
            for record in self.store.records(MemoryScope.EXECUTION)
            if record.key.startswith(prefix)
        )
        if not records:
            return None
        selected = max(records, key=lambda record: (record.created_at, record.key))
        return self._decode(selected, snapshot_id=snapshot_id)

    @classmethod
    def _decode(
        cls,
        record: MemoryRecord,
        *,
        snapshot_id: str,
        version: str | None = None,
    ) -> PlanObservationSnapshot:
        if not isinstance(record.value, Mapping):
            raise AdaptiveExecutionError("stored plan snapshot must be an object")
        try:
            snapshot = PlanObservationSnapshot.from_dict(record.value)
        except FederatedPlanningError as exc:
            raise AdaptiveExecutionError(str(exc)) from exc
        if snapshot.version != record.version:
            raise AdaptiveExecutionError(
                "stored plan snapshot version disagrees with its memory record"
            )
        if snapshot.snapshot_id != snapshot_id:
            raise AdaptiveExecutionError(
                "stored plan snapshot id disagrees with its memory key"
            )
        if version is not None and snapshot.version != version:
            raise AdaptiveExecutionError(
                "stored plan snapshot version disagrees with its memory key"
            )
        if record.key != cls._key(snapshot.snapshot_id, snapshot.version):
            raise AdaptiveExecutionError(
                "stored plan snapshot identity disagrees with its memory key"
            )
        return snapshot


class AdaptiveFederatedExecutor:
    """Probe one common prefix, update estimates, and continue exactly once."""

    def __init__(
        self,
        scheduler: FederatedScheduler,
        selector: FederatedPlanSelector | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.selector = selector or FederatedPlanSelector()

    def execute(
        self,
        candidates: tuple[FederatedPlanCandidate, ...],
        snapshot: PlanObservationSnapshot,
        *,
        probe_plan: FederatedExecutionPlan,
        observations: tuple[ProbeObservation, ...],
        updated_version: str,
        observation_source: str,
        policy: ReplanPolicy = ReplanPolicy(),
        goal_id: str = "adaptive-federated-query",
    ) -> AdaptiveFederatedRun:
        started = time.perf_counter()
        if not observations:
            raise AdaptiveExecutionError("adaptive execution requires an observation")
        if (
            not isinstance(updated_version, str)
            or not updated_version.strip()
            or updated_version == snapshot.version
        ):
            raise AdaptiveExecutionError(
                "updated snapshot version must be new and nonempty"
            )
        if not isinstance(observation_source, str) or not observation_source.strip():
            raise AdaptiveExecutionError("observation source must be nonempty")
        self._validate_probe_contract(probe_plan, candidates, observations)

        initial = self.selector.select(candidates, snapshot)
        probe_run = self.scheduler.execute(
            probe_plan,
            goal_id=f"{goal_id}:probe",
        )
        if not probe_run.success:
            return AdaptiveFederatedRun(
                initial_selection=initial,
                selection_after_probe=None,
                snapshot_before=snapshot,
                snapshot_after=snapshot,
                probe_run=probe_run,
                final_run=None,
                replan_reasons=(),
                replan_count=0,
                reused_node_ids=(),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error="probe prefix failed; no continuation was attempted",
            )

        probe_results = {item.node_id: item for item in probe_run.node_results}
        updates: list[RemoteEstimate] = []
        reasons: list[str] = []
        for spec in observations:
            result = probe_results.get(spec.node_id)
            if result is None:
                raise AdaptiveExecutionError(
                    f"probe result has no node '{spec.node_id}'"
                )
            observed = RemoteEstimate.from_runtime_result(
                spec.observation_key,
                result,
                source=observation_source,
                version=updated_version,
            )
            expected = snapshot.by_key.get(spec.observation_key)
            if expected is None:
                raise AdaptiveExecutionError(
                    f"snapshot has no probe estimate '{spec.observation_key}'"
                )
            if expected.backend_id != observed.backend_id:
                raise AdaptiveExecutionError(
                    f"probe backend for '{spec.observation_key}' changed identity"
                )
            cardinality_factor = self._factor(expected.row_count, observed.row_count)
            latency_factor = self._factor(expected.elapsed_ms, observed.elapsed_ms)
            if cardinality_factor >= policy.cardinality_factor_threshold:
                reasons.append(
                    f"{spec.observation_key}:cardinality_factor={cardinality_factor:g}"
                )
            if latency_factor >= policy.latency_factor_threshold:
                reasons.append(
                    f"{spec.observation_key}:latency_factor={latency_factor:g}"
                )
            updates.append(observed)

        updated = snapshot.with_estimates(tuple(updates), version=updated_version)
        after_probe = self.selector.select(candidates, updated)
        should_replan = (
            bool(reasons)
            and policy.max_replans == 1
            and after_probe.selected_plan_id != initial.selected_plan_id
        )
        selected_plan_id = (
            after_probe.selected_plan_id if should_replan else initial.selected_plan_id
        )
        selected = next(
            candidate for candidate in candidates if candidate.plan.plan_id == selected_plan_id
        )
        initial_results = self._reusable_prefix(
            probe_plan,
            selected.plan,
            probe_results,
        )
        final = self.scheduler.execute(
            selected.plan,
            goal_id=f"{goal_id}:continuation",
            initial_results=initial_results,
        )
        return AdaptiveFederatedRun(
            initial_selection=initial,
            selection_after_probe=after_probe,
            snapshot_before=snapshot,
            snapshot_after=updated,
            probe_run=probe_run,
            final_run=final,
            replan_reasons=tuple(reasons),
            replan_count=1 if should_replan else 0,
            reused_node_ids=tuple(sorted(initial_results)),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    @staticmethod
    def _validate_probe_contract(
        probe_plan: FederatedExecutionPlan,
        candidates: tuple[FederatedPlanCandidate, ...],
        observations: tuple[ProbeObservation, ...],
    ) -> None:
        if not candidates:
            raise AdaptiveExecutionError("adaptive execution requires candidates")
        probe_nodes = {node.node_id: node for node in probe_plan.nodes}
        observation_nodes = [item.node_id for item in observations]
        observation_keys = [item.observation_key for item in observations]
        if len(observation_nodes) != len(set(observation_nodes)) or len(
            observation_keys
        ) != len(set(observation_keys)):
            raise AdaptiveExecutionError("probe observations must be unique")
        remote_node_ids = {
            node.node_id
            for node in probe_plan.nodes
            if node.kind
            in {RuntimeNodeKind.REMOTE_QUERY, RuntimeNodeKind.REMOTE_BIND_QUERY}
        }
        if set(observation_nodes) != remote_node_ids:
            raise AdaptiveExecutionError(
                "every remote probe node must have exactly one observation"
            )
        reachable: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in reachable:
                return
            reachable.add(node_id)
            for input_id in probe_nodes[node_id].inputs:
                visit(input_id)

        for root in probe_plan.roots:
            visit(root)
        if reachable != set(probe_nodes):
            raise AdaptiveExecutionError(
                "every probe node must contribute to a probe root"
            )
        for observation in observations:
            node = probe_nodes.get(observation.node_id)
            if node is None or node.kind not in {
                RuntimeNodeKind.REMOTE_QUERY,
                RuntimeNodeKind.REMOTE_BIND_QUERY,
            }:
                raise AdaptiveExecutionError(
                    f"probe observation '{observation.node_id}' must name a remote node"
                )
            if node.parameters.get("observation_key") != observation.observation_key:
                raise AdaptiveExecutionError(
                    f"probe observation key does not match node '{observation.node_id}'"
                )
        for candidate in candidates:
            candidate_nodes = {node.node_id: node for node in candidate.plan.nodes}
            for node in probe_plan.nodes:
                if candidate_nodes.get(node.node_id) != node:
                    raise AdaptiveExecutionError(
                        f"probe node '{node.node_id}' is not common to every candidate"
                    )

    @staticmethod
    def _reusable_prefix(
        probe_plan: FederatedExecutionPlan,
        selected_plan: FederatedExecutionPlan,
        probe_results: Mapping[str, RuntimeNodeResult],
    ) -> dict[str, RuntimeNodeResult]:
        selected_nodes: dict[str, RuntimeNode] = {
            node.node_id: node for node in selected_plan.nodes
        }
        reusable: dict[str, RuntimeNodeResult] = {}
        for probe_node in probe_plan.nodes:
            selected_node = selected_nodes.get(probe_node.node_id)
            if selected_node != probe_node:
                raise AdaptiveExecutionError(
                    f"probe node '{probe_node.node_id}' is not an exact common prefix"
                )
            reusable[probe_node.node_id] = probe_results[probe_node.node_id]
        return reusable

    @staticmethod
    def _factor(expected: float, observed: float) -> float:
        if expected == observed:
            return 1.0
        if expected == 0 or observed == 0:
            return math.inf
        return max(expected / observed, observed / expected)
