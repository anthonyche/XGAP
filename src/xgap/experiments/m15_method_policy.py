"""Executable M15 task policies for memory and replanning ablations.

This module keeps the comparison surface above the federated runtime.  It
does not change query semantics or expose backend-internal plan operators.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from xgap.runtime import (
    AdaptiveFederatedExecutor,
    FederatedPlanCandidate,
    FederatedPlanSelector,
    FederatedScheduler,
    FederatedExecutionPlan,
    PlanObservationCollection,
    PlanObservationCollector,
    PlanObservationRequest,
    PlanObservationSnapshot,
    PlanSnapshotMemory,
    ProbeObservation,
    ReplanPolicy,
)
from xgap.tools import BackendInvokeTool


METHOD_POLICY_SCHEMA_VERSION = "m15-f1-method-policy-v1"
MEMORY_CONTEXT_SCHEMA_VERSION = "m15-f1-memory-context-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class M15MethodError(ValueError):
    """Raised before tool invocation when a method contract is invalid."""


class M15Method(str, Enum):
    STATIC_PARALLEL_HASH = "static_parallel_hash"
    STATIC_RISK_FIRST_BIND = "static_risk_first_bind"
    NO_MEMORY = "no_memory"
    NO_PROFILE_PROBE = "no_profile_probe"
    NO_REPLAN = "no_replan"
    FULL_AGENT = "full_agent"


@dataclass(frozen=True)
class M15MethodPolicy:
    method: M15Method
    fixed_strategy: str | None
    read_memory: bool
    collect_on_miss: bool
    collect_every_task: bool
    probe_on_memory_hit: bool
    max_replans: int
    write_memory: bool

    def __post_init__(self) -> None:
        if not isinstance(self.method, M15Method):
            raise M15MethodError("method policy requires an M15Method")
        if self.fixed_strategy is not None and not self.fixed_strategy.strip():
            raise M15MethodError("fixed strategy must be nonempty when present")
        if self.max_replans not in {0, 1} or isinstance(self.max_replans, bool):
            raise M15MethodError("method policy permits zero or one replan")
        if self.collect_on_miss and not self.read_memory:
            raise M15MethodError("collect_on_miss requires memory reads")
        if self.collect_every_task and self.read_memory:
            raise M15MethodError("collect_every_task cannot also read memory")
        if self.probe_on_memory_hit and not self.read_memory:
            raise M15MethodError("a warm-memory probe requires memory reads")
        if self.max_replans and not self.probe_on_memory_hit:
            raise M15MethodError("replanning requires a warm-memory probe")
        if self.fixed_strategy is not None and any(
            (
                self.read_memory,
                self.collect_on_miss,
                self.collect_every_task,
                self.probe_on_memory_hit,
                self.write_memory,
                bool(self.max_replans),
            )
        ):
            raise M15MethodError("a static policy cannot enable agent mechanisms")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": METHOD_POLICY_SCHEMA_VERSION,
            "method": self.method.value,
            "fixed_strategy": self.fixed_strategy,
            "read_memory": self.read_memory,
            "collect_on_miss": self.collect_on_miss,
            "collect_every_task": self.collect_every_task,
            "probe_on_memory_hit": self.probe_on_memory_hit,
            "max_replans": self.max_replans,
            "write_memory": self.write_memory,
        }


M15_METHOD_POLICIES: Mapping[M15Method, M15MethodPolicy] = MappingProxyType(
    {
        M15Method.STATIC_PARALLEL_HASH: M15MethodPolicy(
            M15Method.STATIC_PARALLEL_HASH,
            "parallel_hash_join",
            False,
            False,
            False,
            False,
            0,
            False,
        ),
        M15Method.STATIC_RISK_FIRST_BIND: M15MethodPolicy(
            M15Method.STATIC_RISK_FIRST_BIND,
            "risk_first_bind_join",
            False,
            False,
            False,
            False,
            0,
            False,
        ),
        M15Method.NO_MEMORY: M15MethodPolicy(
            M15Method.NO_MEMORY,
            None,
            False,
            False,
            True,
            False,
            0,
            False,
        ),
        M15Method.NO_PROFILE_PROBE: M15MethodPolicy(
            M15Method.NO_PROFILE_PROBE,
            None,
            True,
            False,
            False,
            False,
            0,
            False,
        ),
        M15Method.NO_REPLAN: M15MethodPolicy(
            M15Method.NO_REPLAN,
            None,
            True,
            False,
            False,
            True,
            0,
            True,
        ),
        M15Method.FULL_AGENT: M15MethodPolicy(
            M15Method.FULL_AGENT,
            None,
            True,
            True,
            False,
            True,
            1,
            True,
        ),
    }
)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise M15MethodError(f"memory context is not canonical JSON: {exc}") from exc


@dataclass(frozen=True)
class M15PlanMemoryContext:
    """Exact compatibility boundary for a cross-task planning snapshot."""

    context_id: str
    semantic_equivalence_key: str
    fingerprint: str
    factors: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.context_id):
            raise M15MethodError("memory context_id contains unsupported characters")
        if not self.semantic_equivalence_key.strip():
            raise M15MethodError("memory semantic equivalence key must be nonempty")
        if not re.fullmatch(r"[0-9a-f]{64}", self.fingerprint):
            raise M15MethodError("memory context fingerprint must be a SHA-256 hex digest")
        if not isinstance(self.factors, Mapping):
            raise M15MethodError("memory context factors must be a mapping")
        object.__setattr__(self, "factors", MappingProxyType(dict(self.factors)))

    @property
    def snapshot_id(self) -> str:
        return f"{self.context_id}-{self.fingerprint}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MEMORY_CONTEXT_SCHEMA_VERSION,
            "context_id": self.context_id,
            "semantic_equivalence_key": self.semantic_equivalence_key,
            "fingerprint": self.fingerprint,
            "snapshot_id": self.snapshot_id,
            "factors": dict(self.factors),
        }

    def validate_task_inputs(
        self,
        *,
        candidates: tuple[FederatedPlanCandidate, ...],
        requests: tuple[PlanObservationRequest, ...],
        bandwidth_bytes_per_ms: float,
        exchange_fixed_ms: float,
        coordinator_row_ms: float,
    ) -> None:
        """Reject drift between a fingerprinted context and the running task."""

        expected_candidates = [
            candidate.plan.to_dict()
            for candidate in sorted(candidates, key=lambda item: item.plan.plan_id)
        ]
        expected_requests = [request.to_dict() for request in requests]
        expected_cost = {
            "bandwidth_bytes_per_ms": float(bandwidth_bytes_per_ms),
            "exchange_fixed_ms": float(exchange_fixed_ms),
            "coordinator_row_ms": float(coordinator_row_ms),
        }
        if self.factors.get("candidate_plans") != expected_candidates:
            raise M15MethodError("candidate plans disagree with the memory context")
        if self.factors.get("observation_requests") != expected_requests:
            raise M15MethodError("observation requests disagree with the memory context")
        if self.factors.get("cost_model") != expected_cost:
            raise M15MethodError("cost model disagrees with the memory context")

        encoded = _canonical_json(dict(self.factors)).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != self.fingerprint:
            raise M15MethodError("memory context factors disagree with its fingerprint")


def build_m15_plan_memory_context(
    *,
    context_id: str,
    candidates: tuple[FederatedPlanCandidate, ...],
    requests: tuple[PlanObservationRequest, ...],
    bandwidth_bytes_per_ms: float,
    exchange_fixed_ms: float,
    coordinator_row_ms: float,
    binding: Mapping[str, Any],
) -> M15PlanMemoryContext:
    """Bind memory reuse to exact plans, observations, model, and workload."""

    if not candidates:
        raise M15MethodError("memory context requires plan candidates")
    equivalence_keys = {item.semantic_equivalence_key for item in candidates}
    if len(equivalence_keys) != 1:
        raise M15MethodError("memory context requires one semantic equivalence class")
    if not requests:
        raise M15MethodError("memory context requires observation requests")
    if not isinstance(binding, Mapping) or not binding:
        raise M15MethodError("memory context requires a nonempty external binding")
    for name, value in (
        ("bandwidth_bytes_per_ms", bandwidth_bytes_per_ms),
        ("exchange_fixed_ms", exchange_fixed_ms),
        ("coordinator_row_ms", coordinator_row_ms),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise M15MethodError(f"{name} must be finite")
    if bandwidth_bytes_per_ms <= 0:
        raise M15MethodError("bandwidth_bytes_per_ms must be positive")
    if exchange_fixed_ms < 0 or coordinator_row_ms < 0:
        raise M15MethodError("coordinator cost values must be nonnegative")

    factors = {
        "schema_version": MEMORY_CONTEXT_SCHEMA_VERSION,
        "semantic_equivalence_key": next(iter(equivalence_keys)),
        "candidate_plans": [
            candidate.plan.to_dict()
            for candidate in sorted(candidates, key=lambda item: item.plan.plan_id)
        ],
        "observation_requests": [request.to_dict() for request in requests],
        "cost_model": {
            "bandwidth_bytes_per_ms": float(bandwidth_bytes_per_ms),
            "exchange_fixed_ms": float(exchange_fixed_ms),
            "coordinator_row_ms": float(coordinator_row_ms),
        },
        "external_binding": dict(binding),
    }
    encoded = _canonical_json(factors).encode("utf-8")
    return M15PlanMemoryContext(
        context_id=context_id,
        semantic_equivalence_key=next(iter(equivalence_keys)),
        fingerprint=hashlib.sha256(encoded).hexdigest(),
        factors=factors,
    )


@dataclass(frozen=True)
class M15MethodTaskResult:
    method: M15Method
    task_id: str
    context_fingerprint: str
    snapshot_id: str
    success: bool
    exact_answer: bool | None
    final_rows: tuple[Mapping[str, Any], ...]
    memory_state: str
    memory_reads: int
    memory_writes: int
    planning_profile_calls: int
    probe_remote_calls: int
    query_remote_calls: int
    total_backend_calls: int
    initial_plan_id: str | None
    post_probe_plan_id: str | None
    executed_plan_id: str | None
    replan_count: int
    total_bytes_moved: int
    planning_elapsed_ms: float
    query_elapsed_ms: float
    end_to_end_elapsed_ms: float
    snapshot_before: PlanObservationSnapshot | None
    snapshot_after: PlanObservationSnapshot | None
    observation_collection: PlanObservationCollection | None
    execution: Mapping[str, Any] | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": METHOD_POLICY_SCHEMA_VERSION,
            "method": self.method.value,
            "policy": M15_METHOD_POLICIES[self.method].to_dict(),
            "task_id": self.task_id,
            "context_fingerprint": self.context_fingerprint,
            "snapshot_id": self.snapshot_id,
            "success": self.success,
            "exact_answer": self.exact_answer,
            "final_rows": [dict(row) for row in self.final_rows],
            "memory_state": self.memory_state,
            "memory_reads": self.memory_reads,
            "memory_writes": self.memory_writes,
            "planning_profile_calls": self.planning_profile_calls,
            "probe_remote_calls": self.probe_remote_calls,
            "query_remote_calls": self.query_remote_calls,
            "total_backend_calls": self.total_backend_calls,
            "initial_plan_id": self.initial_plan_id,
            "post_probe_plan_id": self.post_probe_plan_id,
            "executed_plan_id": self.executed_plan_id,
            "replan_count": self.replan_count,
            "total_bytes_moved": self.total_bytes_moved,
            "planning_elapsed_ms": self.planning_elapsed_ms,
            "query_elapsed_ms": self.query_elapsed_ms,
            "end_to_end_elapsed_ms": self.end_to_end_elapsed_ms,
            "snapshot_before": (
                self.snapshot_before.to_dict() if self.snapshot_before else None
            ),
            "snapshot_after": (
                self.snapshot_after.to_dict() if self.snapshot_after else None
            ),
            "observation_collection": (
                self.observation_collection.to_dict()
                if self.observation_collection
                else None
            ),
            "execution": dict(self.execution) if self.execution else None,
            "error": self.error,
            "automatic_retries": 0,
            "llm_calls": 0,
            "ontology_calls": 0,
            "paper_result": False,
        }


def _candidate_for_strategy(
    candidates: tuple[FederatedPlanCandidate, ...],
    strategy: str,
) -> FederatedPlanCandidate:
    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.plan.metadata.get("physical_strategy") == strategy
    )
    if len(matches) != 1:
        raise M15MethodError(
            f"expected exactly one candidate for physical strategy '{strategy}'"
        )
    return matches[0]


def _validate_snapshot_compatibility(
    snapshot: PlanObservationSnapshot,
    *,
    context: M15PlanMemoryContext,
    requests: tuple[PlanObservationRequest, ...],
    bandwidth_bytes_per_ms: float,
    exchange_fixed_ms: float,
    coordinator_row_ms: float,
) -> None:
    if snapshot.snapshot_id != context.snapshot_id:
        raise M15MethodError("plan snapshot identity disagrees with the memory context")
    expected_backends = {
        request.observation_key: request.backend_id for request in requests
    }
    observed_backends = {
        estimate.observation_key: estimate.backend_id
        for estimate in snapshot.estimates
    }
    if observed_backends != expected_backends:
        raise M15MethodError(
            "plan snapshot observations disagree with the declared request tuple"
        )
    expected_cost = (
        float(bandwidth_bytes_per_ms),
        float(exchange_fixed_ms),
        float(coordinator_row_ms),
    )
    observed_cost = (
        float(snapshot.bandwidth_bytes_per_ms),
        float(snapshot.exchange_fixed_ms),
        float(snapshot.coordinator_row_ms),
    )
    if observed_cost != expected_cost:
        raise M15MethodError("plan snapshot cost model is incompatible with this task")


def run_m15_method_task(
    *,
    method: M15Method,
    task_id: str,
    context: M15PlanMemoryContext,
    candidates: tuple[FederatedPlanCandidate, ...],
    requests: tuple[PlanObservationRequest, ...],
    probe_plan: FederatedExecutionPlan,
    probe_observation: ProbeObservation,
    backend_tool: BackendInvokeTool,
    expected_rows: tuple[Mapping[str, Any], ...],
    bandwidth_bytes_per_ms: float,
    exchange_fixed_ms: float,
    coordinator_row_ms: float,
    memory: PlanSnapshotMemory | None = None,
    cardinality_factor_threshold: float = 2.0,
    latency_factor_threshold: float = 2.0,
) -> M15MethodTaskResult:
    """Execute one explicit method with exact action and cost accounting.

    Configuration and compatibility errors are rejected before a backend call.
    External observation or execution failures are returned as evidence and are
    never retried.
    """

    started = time.perf_counter()
    if not isinstance(method, M15Method):
        raise M15MethodError("method must be an M15Method")
    if not _SAFE_ID.fullmatch(task_id):
        raise M15MethodError("task_id contains unsupported characters")
    if not isinstance(expected_rows, tuple) or any(
        not isinstance(row, Mapping) for row in expected_rows
    ):
        raise M15MethodError("expected_rows must be a tuple of mappings")
    if not candidates:
        raise M15MethodError("method task requires candidates")
    if any(
        candidate.semantic_equivalence_key != context.semantic_equivalence_key
        for candidate in candidates
    ):
        raise M15MethodError("candidate semantics disagree with the memory context")
    context.validate_task_inputs(
        candidates=candidates,
        requests=requests,
        bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
        exchange_fixed_ms=exchange_fixed_ms,
        coordinator_row_ms=coordinator_row_ms,
    )

    policy = M15_METHOD_POLICIES[method]
    if (policy.read_memory or policy.write_memory) and memory is None:
        raise M15MethodError(f"method '{method.value}' requires a memory store")

    scheduler = FederatedScheduler(backend_tool)
    selector = FederatedPlanSelector()
    collection: PlanObservationCollection | None = None
    snapshot_before: PlanObservationSnapshot | None = None
    snapshot_after: PlanObservationSnapshot | None = None
    memory_state = "disabled"
    memory_reads = 0
    memory_writes = 0
    planning_profile_calls = 0
    probe_remote_calls = 0
    query_remote_calls = 0
    initial_plan_id: str | None = None
    post_probe_plan_id: str | None = None
    executed_plan_id: str | None = None
    replan_count = 0
    total_bytes_moved = 0
    planning_elapsed_ms = 0.0
    query_elapsed_ms = 0.0
    final_rows: tuple[Mapping[str, Any], ...] = ()
    execution: Mapping[str, Any] | None = None
    error: str | None = None

    if policy.read_memory:
        assert memory is not None
        memory_reads = 1
        snapshot_before = memory.latest(context.snapshot_id)
        memory_state = "hit" if snapshot_before is not None else "miss"
        if snapshot_before is not None:
            _validate_snapshot_compatibility(
                snapshot_before,
                context=context,
                requests=requests,
                bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
                exchange_fixed_ms=exchange_fixed_ms,
                coordinator_row_ms=coordinator_row_ms,
            )
        if snapshot_before is None and not policy.collect_on_miss:
            raise M15MethodError(
                f"method '{method.value}' requires a compatible warm-memory snapshot"
            )

    needs_collection = policy.collect_every_task or (
        policy.collect_on_miss and snapshot_before is None
    )
    if needs_collection:
        collection = PlanObservationCollector(backend_tool).collect(
            requests,
            snapshot_id=context.snapshot_id,
            version=f"profile-{task_id}",
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
            goal_id=f"{task_id}:collect-observations",
        )
        planning_profile_calls = collection.attempted_calls
        planning_elapsed_ms = collection.elapsed_ms
        if not collection.success or collection.snapshot is None:
            error = collection.error or "plan observation collection failed"
        else:
            snapshot_before = collection.snapshot
            snapshot_after = collection.snapshot
            memory_state = "profiled_without_memory"
            if policy.write_memory:
                assert memory is not None
                memory.put(
                    collection.snapshot,
                    source=f"{task_id}/registered-profile",
                )
                memory_writes += 1
                memory_state = "miss_profiled_and_persisted"

    if error is None:
        query_started = time.perf_counter()
        if policy.fixed_strategy is not None:
            selected = _candidate_for_strategy(candidates, policy.fixed_strategy)
            initial_plan_id = selected.plan.plan_id
            executed_plan_id = selected.plan.plan_id
            run = scheduler.execute(selected.plan, goal_id=f"{task_id}:static-query")
            query_remote_calls = run.total_remote_calls
            total_bytes_moved = run.total_bytes_moved
            final_rows = tuple(dict(row) for row in run.final_rows)
            execution = run.to_dict()
            if not run.success:
                error = run.error or "static federated execution failed"
        elif snapshot_before is not None and policy.probe_on_memory_hit and not needs_collection:
            adaptive = AdaptiveFederatedExecutor(scheduler, selector).execute(
                candidates,
                snapshot_before,
                probe_plan=probe_plan,
                observations=(probe_observation,),
                updated_version=f"probe-{task_id}",
                observation_source=f"{task_id}/runtime-probe/{probe_observation.node_id}",
                policy=ReplanPolicy(
                    cardinality_factor_threshold=cardinality_factor_threshold,
                    latency_factor_threshold=latency_factor_threshold,
                    max_replans=policy.max_replans,
                ),
                goal_id=f"{task_id}:adaptive-query",
            )
            probe_remote_calls = adaptive.probe_run.total_remote_calls
            query_remote_calls = adaptive.total_remote_calls
            initial_plan_id = adaptive.initial_selection.selected_plan_id
            post_probe_plan_id = (
                adaptive.selection_after_probe.selected_plan_id
                if adaptive.selection_after_probe is not None
                else None
            )
            executed_plan_id = adaptive.selected_plan_id
            replan_count = adaptive.replan_count
            total_bytes_moved = adaptive.total_bytes_moved
            snapshot_after = adaptive.snapshot_after
            execution = adaptive.to_dict()
            if adaptive.final_run is not None:
                final_rows = tuple(dict(row) for row in adaptive.final_run.final_rows)
            if (
                policy.write_memory
                and adaptive.selection_after_probe is not None
                and adaptive.snapshot_after.version != snapshot_before.version
            ):
                assert memory is not None
                memory.put(
                    adaptive.snapshot_after,
                    source=f"{task_id}/runtime-probe",
                )
                memory_writes += 1
            if not adaptive.success:
                error = adaptive.error or "adaptive federated execution failed"
        else:
            if snapshot_before is None:
                raise M15MethodError(
                    f"method '{method.value}' has no snapshot for plan selection"
                )
            selection = selector.select(candidates, snapshot_before)
            initial_plan_id = selection.selected_plan_id
            executed_plan_id = selection.selected_plan_id
            selected = next(
                item for item in candidates if item.plan.plan_id == selection.selected_plan_id
            )
            run = scheduler.execute(selected.plan, goal_id=f"{task_id}:selected-query")
            query_remote_calls = run.total_remote_calls
            total_bytes_moved = run.total_bytes_moved
            final_rows = tuple(dict(row) for row in run.final_rows)
            execution = {
                "selection": selection.to_dict(),
                "run": run.to_dict(),
            }
            if not run.success:
                error = run.error or "selected federated execution failed"
        query_elapsed_ms = (time.perf_counter() - query_started) * 1000

    exact_answer = None if error is not None else final_rows == expected_rows
    if error is None and not exact_answer:
        error = "federated answer disagrees with the exact oracle"
    total_backend_calls = planning_profile_calls + query_remote_calls
    success = error is None and exact_answer is True
    return M15MethodTaskResult(
        method=method,
        task_id=task_id,
        context_fingerprint=context.fingerprint,
        snapshot_id=context.snapshot_id,
        success=success,
        exact_answer=exact_answer,
        final_rows=final_rows,
        memory_state=memory_state,
        memory_reads=memory_reads,
        memory_writes=memory_writes,
        planning_profile_calls=planning_profile_calls,
        probe_remote_calls=probe_remote_calls,
        query_remote_calls=query_remote_calls,
        total_backend_calls=total_backend_calls,
        initial_plan_id=initial_plan_id,
        post_probe_plan_id=post_probe_plan_id,
        executed_plan_id=executed_plan_id,
        replan_count=replan_count,
        total_bytes_moved=total_bytes_moved,
        planning_elapsed_ms=planning_elapsed_ms,
        query_elapsed_ms=query_elapsed_ms,
        end_to_end_elapsed_ms=(time.perf_counter() - started) * 1000,
        snapshot_before=snapshot_before,
        snapshot_after=snapshot_after,
        observation_collection=collection,
        execution=execution,
        error=error,
    )
