"""Pluggable black-box graph backend tools.

The plugin boundary does not expose or modify a database's internal optimizer.
It exposes only observable operations that a coordinator may invoke.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
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


def _artifact_sha256(artifact: QueryArtifact) -> str:
    payload = json.dumps(
        artifact.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class BackendObservationCatalog:
    """Versioned, coordinator-owned allowlist for read-only observations.

    Observation calls select an existing artifact ID. They cannot submit new
    native query text through the observation interface.
    """

    catalog_id: str
    version: str
    schema_artifact: QueryArtifact | None = None
    query_artifacts: Mapping[str, QueryArtifact] = field(default_factory=dict)
    sample_artifacts: Mapping[str, QueryArtifact] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.catalog_id.strip() or not self.version.strip():
            raise ValueError("observation catalog id and version must be nonempty")
        if self.schema_artifact is not None and not isinstance(
            self.schema_artifact,
            QueryArtifact,
        ):
            raise TypeError("schema_artifact must be a QueryArtifact")
        for collection_name, artifacts in (
            ("query_artifacts", self.query_artifacts),
            ("sample_artifacts", self.sample_artifacts),
        ):
            for key, artifact in artifacts.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError(
                        f"{collection_name} keys must be nonempty strings"
                    )
                if not isinstance(artifact, QueryArtifact):
                    raise TypeError(f"{collection_name} values must be QueryArtifact")
            object.__setattr__(self, collection_name, MappingProxyType(dict(artifacts)))


@dataclass
class CatalogBackendPlugin:
    """Black-box backend adapter with a frozen read-only observation catalog."""

    backend_id: str
    client: BackendClient
    catalog: BackendObservationCatalog

    def __post_init__(self) -> None:
        if not self.backend_id.strip():
            raise ValueError("backend plugin id must be nonempty")
        client_backend_id = getattr(self.client, "backend_id", None)
        if client_backend_id != self.backend_id:
            raise ValueError(
                "catalog plugin backend id must match its backend client"
            )

    @property
    def supported_operations(self) -> frozenset[BackendOperation]:
        operations = {BackendOperation.HEALTHCHECK, BackendOperation.EXECUTE}
        if self.catalog.schema_artifact is not None:
            operations.add(BackendOperation.INSPECT_SCHEMA)
        if self.catalog.sample_artifacts:
            operations.add(BackendOperation.SAMPLE)
        if self.catalog.query_artifacts:
            operations.add(BackendOperation.PROFILE)
            if callable(getattr(self.client, "explain", None)):
                operations.add(BackendOperation.EXPLAIN)
        return frozenset(operations)

    def invoke(
        self,
        operation: BackendOperation,
        payload: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        if operation in {BackendOperation.HEALTHCHECK, BackendOperation.EXECUTE}:
            return NativeBackendPlugin(self.backend_id, self.client).invoke(
                operation,
                payload,
                context,
            )
        del context
        if operation is BackendOperation.INSPECT_SCHEMA:
            if payload:
                return ToolResult.error_result(
                    BACKEND_INVOKE_TOOL,
                    "inspect_schema accepts no query payload",
                )
            artifact = self.catalog.schema_artifact
            if artifact is None:
                return self._unavailable(operation)
            return self._run_observation(operation, artifact, self.client.execute)

        key_name = "sample_id" if operation is BackendOperation.SAMPLE else "query_id"
        selected_id = payload.get(key_name)
        if not isinstance(selected_id, str) or not selected_id.strip():
            return ToolResult.error_result(
                BACKEND_INVOKE_TOOL,
                f"{operation.value} requires a nonempty '{key_name}'",
            )
        allowed_keys = {key_name}
        if set(payload) != allowed_keys:
            return ToolResult.error_result(
                BACKEND_INVOKE_TOOL,
                f"{operation.value} accepts only the registered '{key_name}'",
            )
        artifacts = (
            self.catalog.sample_artifacts
            if operation is BackendOperation.SAMPLE
            else self.catalog.query_artifacts
        )
        artifact = artifacts.get(selected_id)
        if artifact is None:
            return ToolResult.unavailable(
                BACKEND_INVOKE_TOOL,
                f"backend '{self.backend_id}' has no registered {key_name} '{selected_id}'",
            )
        if operation is BackendOperation.EXPLAIN:
            explain = getattr(self.client, "explain", None)
            if not callable(explain):
                return self._unavailable(operation)
            return self._run_observation(operation, artifact, explain)
        if operation is BackendOperation.PROFILE:
            profile = getattr(self.client, "profile", None)
            executor = profile if callable(profile) else self.client.execute
            mode = "backend_native" if callable(profile) else "wall_clock_execute"
            return self._run_observation(operation, artifact, executor, mode=mode)
        if operation is BackendOperation.SAMPLE:
            return self._run_observation(operation, artifact, self.client.execute)
        return self._unavailable(operation)

    def _run_observation(
        self,
        operation: BackendOperation,
        artifact: QueryArtifact,
        executor: Any,
        *,
        mode: str = "registered_read_only_query",
    ) -> ToolResult:
        report = executor(artifact)
        if report.backend_id != self.backend_id:
            return ToolResult.error_result(
                BACKEND_INVOKE_TOOL,
                "backend observation report identity does not match the plugin",
            )
        if not report.success:
            return ToolResult.error_result(
                BACKEND_INVOKE_TOOL,
                report.error
                or f"backend '{self.backend_id}' {operation.value} failed",
            )
        return ToolResult.success(
            BACKEND_INVOKE_TOOL,
            {
                "backend_id": self.backend_id,
                "operation": operation.value,
                "catalog_id": self.catalog.catalog_id,
                "catalog_version": self.catalog.version,
                "artifact_id": artifact.artifact_id,
                "artifact_sha256": _artifact_sha256(artifact),
                "observation_mode": mode,
                "observation": report.to_dict(),
            },
            metrics={
                "elapsed_ms": float(report.elapsed_ms or 0.0),
                "row_count": float(report.row_count),
            },
            metadata={"read_only_catalog": True},
        )

    def _unavailable(self, operation: BackendOperation) -> ToolResult:
        return ToolResult.unavailable(
            BACKEND_INVOKE_TOOL,
            f"backend '{self.backend_id}' does not support '{operation.value}'",
        )


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
                    {
                        "backend_id": self.backend_id,
                        "operation": operation.value,
                        "status": status.to_dict(),
                    },
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
            metrics = {
                "elapsed_ms": float(report.elapsed_ms or 0.0),
                "row_count": float(report.row_count),
            }
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
