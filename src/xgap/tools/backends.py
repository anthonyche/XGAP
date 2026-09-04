"""Pluggable black-box graph backend tools.

The plugin boundary does not expose or modify a database's internal optimizer.
It exposes only observable operations that a coordinator may invoke.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from xgap.backends.protocol import BackendClient
from xgap.infrastructure.runtime import QueryArtifact
from xgap.tools.contracts import ToolContext, ToolEffect, ToolResult, ToolSpec


BACKEND_INVOKE_TOOL = "backend.invoke"


class BackendOperation(str, Enum):
    HEALTHCHECK = "healthcheck"
    INSPECT_SCHEMA = "inspect_schema"
    EXPLAIN = "explain"
    PROFILE = "profile"
    SAMPLE = "sample"
    EXECUTE = "execute"


class BackendPlugin(Protocol):
    @property
    def backend_id(self) -> str:
        """Stable backend identity."""

    @property
    def supported_operations(self) -> frozenset[BackendOperation]:
        """Operations this plugin can actually perform."""

    def invoke(
        self,
        operation: BackendOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Invoke one observable black-box backend operation."""


class BackendPluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, BackendPlugin] = {}

    def register(self, plugin: BackendPlugin) -> None:
        if not plugin.backend_id.strip():
            raise ValueError("backend plugin id must be nonempty")
        if plugin.backend_id in self._plugins:
            raise ValueError(f"backend plugin '{plugin.backend_id}' is already registered")
        self._plugins[plugin.backend_id] = plugin

    def backend_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def describe(self) -> dict[str, list[str]]:
        return {
            backend_id: sorted(operation.value for operation in plugin.supported_operations)
            for backend_id, plugin in sorted(self._plugins.items())
        }

    def invoke(
        self,
        backend_id: str,
        operation: BackendOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        plugin = self._plugins.get(backend_id)
        if plugin is None:
            return ToolResult.unavailable(
                BACKEND_INVOKE_TOOL,
                f"backend plugin '{backend_id}' is not registered",
            )
        if operation not in plugin.supported_operations:
            return ToolResult.unavailable(
                BACKEND_INVOKE_TOOL,
                f"backend '{backend_id}' does not support '{operation.value}'",
            )
        return plugin.invoke(operation, payload, context)


@dataclass
class NativeBackendPlugin:
    """Adapter for the existing healthcheck/execute BackendClient protocol."""

    backend_id: str
    client: BackendClient
    supported_operations: frozenset[BackendOperation] = field(
        default_factory=lambda: frozenset(
            {BackendOperation.HEALTHCHECK, BackendOperation.EXECUTE}
        )
    )

    def invoke(
        self,
        operation: BackendOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        del context
        if operation is BackendOperation.HEALTHCHECK:
            status = self.client.healthcheck()
            if status.ok:
                return ToolResult.success(
                    BACKEND_INVOKE_TOOL,
                    {"backend_id": self.backend_id, "operation": operation.value, "status": status.to_dict()},
                )
            return ToolResult.error_result(BACKEND_INVOKE_TOOL, status.message)

        if operation is BackendOperation.EXECUTE:
            artifact_data = payload.get("artifact")
            if not isinstance(artifact_data, Mapping):
                return ToolResult.error_result(
                    BACKEND_INVOKE_TOOL,
                    "execute requires an 'artifact' mapping",
                )
            try:
                artifact = QueryArtifact.from_dict(artifact_data)
            except (KeyError, TypeError, ValueError) as exc:
                return ToolResult.error_result(
                    BACKEND_INVOKE_TOOL,
                    f"invalid query artifact: {exc}",
                )
            report = self.client.execute(artifact)
            if not report.success:
                return ToolResult.error_result(
                    BACKEND_INVOKE_TOOL,
                    report.error or f"backend '{self.backend_id}' execution failed",
                )
            metrics = {"elapsed_ms": float(report.elapsed_ms or 0.0), "row_count": float(report.row_count)}
            return ToolResult.success(
                BACKEND_INVOKE_TOOL,
                {
                    "backend_id": self.backend_id,
                    "operation": operation.value,
                    "execution": report.to_dict(),
                },
                metrics=metrics,
            )

        return ToolResult.unavailable(
            BACKEND_INVOKE_TOOL,
            f"native adapter does not implement '{operation.value}'",
        )


@dataclass
class BackendInvokeTool:
    """Single agent-visible dispatch tool backed by a plugin registry."""

    backends: BackendPluginRegistry

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=BACKEND_INVOKE_TOOL,
            description="Invoke an observable operation on a registered graph backend",
            input_schema={
                "type": "object",
                "required": ["backend_id", "operation"],
                "properties": {
                    "backend_id": {"type": "string"},
                    "operation": {
                        "enum": [operation.value for operation in BackendOperation]
                    },
                    "payload": {"type": "object"},
                },
            },
            output_kind="backend_observation",
            effect=ToolEffect.EXTERNAL,
            remote=True,
            tags=("graph", "backend", "federated"),
        )

    def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        backend_id = arguments.get("backend_id")
        raw_operation = arguments.get("operation")
        payload = arguments.get("payload", {})
        if not isinstance(backend_id, str) or not backend_id.strip():
            return ToolResult.error_result(BACKEND_INVOKE_TOOL, "backend_id must be nonempty")
        try:
            operation = BackendOperation(str(raw_operation))
        except ValueError:
            return ToolResult.error_result(
                BACKEND_INVOKE_TOOL,
                f"unknown backend operation '{raw_operation}'",
            )
        if not isinstance(payload, Mapping):
            return ToolResult.error_result(BACKEND_INVOKE_TOOL, "payload must be a mapping")
        return self.backends.invoke(backend_id, operation, payload, context)
