"""Typed tools and pluggable graph-backend adapters."""

from xgap.tools.backends import (
    BACKEND_INVOKE_TOOL,
    BackendInvokeTool,
    BackendObservationCatalog,
    BackendOperation,
    BackendPlugin,
    BackendPluginRegistry,
    CatalogBackendPlugin,
    NativeBackendPlugin,
)
from xgap.tools.contracts import (
    AgentTool,
    FunctionTool,
    ToolContext,
    ToolEffect,
    ToolResult,
    ToolSpec,
    ToolStatus,
)
from xgap.tools.registry import ToolRegistry, ToolRegistryError
from xgap.tools.remote import (
    REMOTE_EXECUTOR_TOOL,
    RemoteCommandResult,
    RemoteExecutorOperation,
    RemoteExecutorPlugin,
    RemoteExecutorRegistry,
    RemoteExecutorTool,
    RemoteJobState,
    RemoteTransport,
    SlurmRemoteExecutor,
    SshTransport,
)

__all__ = [
    "AgentTool",
    "BACKEND_INVOKE_TOOL",
    "BackendInvokeTool",
    "BackendObservationCatalog",
    "BackendOperation",
    "BackendPlugin",
    "BackendPluginRegistry",
    "CatalogBackendPlugin",
    "FunctionTool",
    "NativeBackendPlugin",
    "REMOTE_EXECUTOR_TOOL",
    "RemoteCommandResult",
    "RemoteExecutorOperation",
    "RemoteExecutorPlugin",
    "RemoteExecutorRegistry",
    "RemoteExecutorTool",
    "RemoteJobState",
    "RemoteTransport",
    "SlurmRemoteExecutor",
    "SshTransport",
    "ToolContext",
    "ToolEffect",
    "ToolRegistry",
    "ToolRegistryError",
    "ToolResult",
    "ToolSpec",
    "ToolStatus",
]
