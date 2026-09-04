from __future__ import annotations

from dataclasses import dataclass

import pytest

from xgap.infrastructure.runtime import BackendStatus, ExecutionReport
from xgap.tools import (
    BACKEND_INVOKE_TOOL,
    BackendInvokeTool,
    BackendOperation,
    BackendPluginRegistry,
    NativeBackendPlugin,
    ToolContext,
    ToolRegistry,
    ToolRegistryError,
    ToolStatus,
)


@dataclass
class FakeBackendClient:
    backend_id: str
    healthy: bool = True

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(
            backend_id=self.backend_id,
            ok=self.healthy,
            message="ready" if self.healthy else "down",
        )

    def execute(self, artifact):
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[{"answer": 1}],
            elapsed_ms=2.5,
        )


def _context() -> ToolContext:
    return ToolContext(goal_id="g", step=1, call_id="c")


def _tool() -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    plugins.register(NativeBackendPlugin("neo4j", FakeBackendClient("neo4j")))
    return BackendInvokeTool(plugins)


def test_native_backend_plugin_healthcheck_and_execute() -> None:
    tool = _tool()
    health = tool.invoke(
        {"backend_id": "neo4j", "operation": "healthcheck"},
        _context(),
    )
    execution = tool.invoke(
        {
            "backend_id": "neo4j",
            "operation": "execute",
            "payload": {
                "artifact": {
                    "artifact_id": "q1",
                    "language": "cypher",
                    "text": "RETURN 1 AS answer",
                }
            },
        },
        _context(),
    )

    assert health.status is ToolStatus.SUCCESS
    assert execution.status is ToolStatus.SUCCESS
    assert execution.metrics == {"elapsed_ms": 2.5, "row_count": 1.0}


def test_native_adapter_reports_unimplemented_observation_tools() -> None:
    tool = _tool()
    result = tool.invoke(
        {"backend_id": "neo4j", "operation": BackendOperation.PROFILE.value},
        _context(),
    )
    assert result.status is ToolStatus.UNAVAILABLE
    assert "does not support" in str(result.error)


def test_backend_registry_is_pluggable_and_rejects_duplicates() -> None:
    plugins = BackendPluginRegistry()
    plugin = NativeBackendPlugin("neo4j", FakeBackendClient("neo4j"))
    plugins.register(plugin)
    with pytest.raises(ValueError, match="already registered"):
        plugins.register(plugin)
    assert plugins.describe() == {"neo4j": ["execute", "healthcheck"]}


def test_tool_registry_normalizes_unknown_tools_and_rejects_duplicates() -> None:
    registry = ToolRegistry()
    tool = _tool()
    registry.register(tool)
    with pytest.raises(ToolRegistryError, match="already registered"):
        registry.register(tool)
    missing = registry.invoke("missing", {}, _context())
    assert missing.status is ToolStatus.UNAVAILABLE
    assert registry.specs()[0].name == BACKEND_INVOKE_TOOL
