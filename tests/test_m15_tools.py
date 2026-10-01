from __future__ import annotations

from dataclasses import dataclass

import pytest

from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.tools import (
    BACKEND_INVOKE_TOOL,
    BackendInvokeTool,
    BackendObservationCatalog,
    BackendOperation,
    BackendPluginRegistry,
    CatalogBackendPlugin,
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


@dataclass
class ObservableFakeBackendClient(FakeBackendClient):
    def explain(self, artifact: QueryArtifact) -> ExecutionReport:
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            metadata={"native_plan": {"operatorType": "ProduceResults"}},
            elapsed_ms=1.0,
        )

    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[{"answer": 1}],
            metadata={"native_plan": {"rows": 1}},
            elapsed_ms=3.0,
        )


def _catalog_plugin(*, observable: bool = True) -> CatalogBackendPlugin:
    schema = QueryArtifact("schema", "cypher", "CALL db.labels()")
    query = QueryArtifact("q1", "cypher", "MATCH (n) RETURN n LIMIT 5")
    sample = QueryArtifact("s1", "cypher", "MATCH (n) RETURN n LIMIT 2")
    client = (
        ObservableFakeBackendClient("neo4j")
        if observable
        else FakeBackendClient("neo4j")
    )
    return CatalogBackendPlugin(
        "neo4j",
        client,
        BackendObservationCatalog(
            "m15-observations",
            "v1",
            schema_artifact=schema,
            query_artifacts={"risk-query": query},
            sample_artifacts={"node-sample": sample},
        ),
    )


def test_catalog_plugin_exposes_registered_observation_operations() -> None:
    plugins = BackendPluginRegistry()
    plugins.register(_catalog_plugin())
    tool = BackendInvokeTool(plugins)

    schema = tool.invoke(
        {"backend_id": "neo4j", "operation": "inspect_schema"},
        _context(),
    )
    explain = tool.invoke(
        {
            "backend_id": "neo4j",
            "operation": "explain",
            "payload": {"query_id": "risk-query"},
        },
        _context(),
    )
    profile = tool.invoke(
        {
            "backend_id": "neo4j",
            "operation": "profile",
            "payload": {"query_id": "risk-query"},
        },
        _context(),
    )
    sample = tool.invoke(
        {
            "backend_id": "neo4j",
            "operation": "sample",
            "payload": {"sample_id": "node-sample"},
        },
        _context(),
    )

    assert all(
        result.status is ToolStatus.SUCCESS
        for result in (schema, explain, profile, sample)
    )
    assert profile.value["catalog_version"] == "v1"
    assert profile.value["observation_mode"] == "backend_native"
    assert len(profile.value["artifact_sha256"]) == 64
    assert profile.metrics == {"elapsed_ms": 3.0, "row_count": 1.0}
    assert profile.metadata == {"read_only_catalog": True}


def test_observation_interface_rejects_unregistered_or_injected_query_text() -> None:
    plugin = _catalog_plugin()

    missing = plugin.invoke(
        BackendOperation.PROFILE,
        {"query_id": "missing"},
        _context(),
    )
    injected = plugin.invoke(
        BackendOperation.PROFILE,
        {"query_id": "risk-query", "artifact": {"text": "DELETE n"}},
        _context(),
    )

    assert missing.status is ToolStatus.UNAVAILABLE
    assert injected.status is ToolStatus.ERROR
    assert "accepts only" in str(injected.error)


def test_explain_is_explicitly_unavailable_without_backend_support() -> None:
    plugins = BackendPluginRegistry()
    plugins.register(_catalog_plugin(observable=False))
    tool = BackendInvokeTool(plugins)

    result = tool.invoke(
        {
            "backend_id": "neo4j",
            "operation": "explain",
            "payload": {"query_id": "risk-query"},
        },
        _context(),
    )

    assert result.status is ToolStatus.UNAVAILABLE
    assert "does not support" in str(result.error)


def test_observation_catalog_rejects_invalid_entries() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        BackendObservationCatalog("", "v1")
    with pytest.raises(TypeError, match="schema_artifact"):
        BackendObservationCatalog("catalog", "v1", schema_artifact=object())
    with pytest.raises(ValueError, match="nonempty strings"):
        BackendObservationCatalog(
            "catalog",
            "v1",
            query_artifacts={1: QueryArtifact("q", "cypher", "RETURN 1")},
        )
    with pytest.raises(TypeError, match="QueryArtifact"):
        BackendObservationCatalog("catalog", "v1", query_artifacts={"q": object()})


def test_catalog_plugin_rejects_mismatched_backend_identity() -> None:
    with pytest.raises(ValueError, match="must match"):
        CatalogBackendPlugin(
            "neo4j",
            FakeBackendClient("different"),
            BackendObservationCatalog("catalog", "v1"),
        )
