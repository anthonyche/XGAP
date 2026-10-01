"""Bounded collection of plan estimates through registered backend tools."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from xgap.runtime.contracts import JsonMap
from xgap.runtime.planning import (
    FederatedPlanningError,
    PlanObservationSnapshot,
    RemoteEstimate,
)
from xgap.tools.backends import BackendInvokeTool, BackendOperation
from xgap.tools.contracts import ToolContext, ToolResult, ToolStatus


@dataclass(frozen=True)
class PlanObservationRequest:
    """One allowlisted read-only observation used by the cost model."""

    call_id: str
    observation_key: str
    backend_id: str
    operation: BackendOperation
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("call_id", self.call_id),
            ("observation_key", self.observation_key),
            ("backend_id", self.backend_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise FederatedPlanningError(f"observation {name} must be nonempty")
        if self.operation not in {BackendOperation.PROFILE, BackendOperation.SAMPLE}:
            raise FederatedPlanningError(
                "plan estimates may use only profile or sample observations"
            )
        if not isinstance(self.payload, Mapping):
            raise FederatedPlanningError("observation payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_dict(self) -> JsonMap:
        return {
            "call_id": self.call_id,
            "observation_key": self.observation_key,
            "backend_id": self.backend_id,
            "operation": self.operation.value,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class PlanObservationCollection:
    """Complete or partial evidence from one no-retry collection attempt."""

    requests: tuple[PlanObservationRequest, ...]
    tool_results: tuple[ToolResult, ...]
    snapshot: PlanObservationSnapshot | None
    elapsed_ms: float
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None and self.snapshot is not None

    @property
    def attempted_calls(self) -> int:
        return len(self.tool_results)

    def to_dict(self) -> JsonMap:
        return {
            "success": self.success,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "attempted_calls": self.attempted_calls,
            "requests": [item.to_dict() for item in self.requests],
            "tool_results": [item.to_dict() for item in self.tool_results],
            "snapshot": self.snapshot.to_dict() if self.snapshot is not None else None,
            "automatic_retries": 0,
            "execution_order": "declared_sequential_order",
        }


class PlanObservationCollector:
    """Invoke each declared observation once and freeze one cost snapshot."""

    def __init__(self, backend_tool: BackendInvokeTool):
        self.backend_tool = backend_tool

    def collect(
        self,
        requests: tuple[PlanObservationRequest, ...],
        *,
        snapshot_id: str,
        version: str,
        bandwidth_bytes_per_ms: float,
        exchange_fixed_ms: float = 0.0,
        coordinator_row_ms: float = 0.0,
        goal_id: str = "collect-plan-observations",
    ) -> PlanObservationCollection:
        started = time.perf_counter()
        self._validate_requests(requests)
        if not isinstance(goal_id, str) or not goal_id.strip():
            raise FederatedPlanningError("observation goal id must be nonempty")

        # Validate every local model input before the first external call.
        PlanObservationSnapshot(
            snapshot_id=snapshot_id,
            version=version,
            estimates=(),
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
        )

        results: list[ToolResult] = []
        estimates: list[RemoteEstimate] = []
        for step, request in enumerate(requests, start=1):
            try:
                result = self.backend_tool.invoke(
                    {
                        "backend_id": request.backend_id,
                        "operation": request.operation.value,
                        "payload": dict(request.payload),
                    },
                    ToolContext(
                        goal_id=goal_id,
                        step=step,
                        call_id=request.call_id,
                        metadata={"observation_key": request.observation_key},
                    ),
                )
            except Exception as exc:
                message = (
                    f"observation call '{request.call_id}' raised "
                    f"{type(exc).__name__}: {exc}"
                )
                results.append(
                    ToolResult.error_result(
                        self.backend_tool.spec.name,
                        message,
                    )
                )
                return PlanObservationCollection(
                    requests=requests,
                    tool_results=tuple(results),
                    snapshot=None,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    error=message,
                )
            results.append(result)
            if result.status is not ToolStatus.SUCCESS:
                return PlanObservationCollection(
                    requests=requests,
                    tool_results=tuple(results),
                    snapshot=None,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    error=(
                        f"observation call '{request.call_id}' returned "
                        f"{result.status.value}: {result.error}"
                    ),
                )
            try:
                estimates.append(
                    RemoteEstimate.from_tool_result(
                        request.observation_key,
                        result,
                    )
                )
            except FederatedPlanningError as exc:
                return PlanObservationCollection(
                    requests=requests,
                    tool_results=tuple(results),
                    snapshot=None,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    error=f"observation call '{request.call_id}' is invalid: {exc}",
                )

        snapshot = PlanObservationSnapshot(
            snapshot_id=snapshot_id,
            version=version,
            estimates=tuple(estimates),
            bandwidth_bytes_per_ms=bandwidth_bytes_per_ms,
            exchange_fixed_ms=exchange_fixed_ms,
            coordinator_row_ms=coordinator_row_ms,
        )
        return PlanObservationCollection(
            requests=requests,
            tool_results=tuple(results),
            snapshot=snapshot,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    @staticmethod
    def _validate_requests(requests: tuple[PlanObservationRequest, ...]) -> None:
        if not isinstance(requests, tuple) or not requests:
            raise FederatedPlanningError(
                "plan observation collection requires a nonempty request tuple"
            )
        if any(not isinstance(item, PlanObservationRequest) for item in requests):
            raise FederatedPlanningError(
                "plan observation requests must be PlanObservationRequest values"
            )
        call_ids = [item.call_id for item in requests]
        observation_keys = [item.observation_key for item in requests]
        if len(call_ids) != len(set(call_ids)):
            raise FederatedPlanningError("observation call ids must be unique")
        if len(observation_keys) != len(set(observation_keys)):
            raise FederatedPlanningError("observation keys must be unique")
