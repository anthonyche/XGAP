"""Typed agent-tool contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol


JsonMap = dict[str, Any]


class ToolEffect(str, Enum):
    READ_ONLY = "read_only"
    STATEFUL = "stateful"
    EXTERNAL = "external"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_kind: str
    effect: ToolEffect = ToolEffect.READ_ONLY
    remote: bool = False
    estimated_cost_units: float = 0.0
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name must be nonempty")
        if not self.description.strip():
            raise ValueError(f"tool '{self.name}' requires a description")
        if not self.output_kind.strip():
            raise ValueError(f"tool '{self.name}' requires an output kind")
        if self.estimated_cost_units < 0:
            raise ValueError("estimated tool cost must be nonnegative")

    def to_dict(self) -> JsonMap:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "output_kind": self.output_kind,
            "effect": self.effect.value,
            "remote": self.remote,
            "estimated_cost_units": self.estimated_cost_units,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class ToolContext:
    goal_id: str
    step: int
    call_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: ToolStatus
    value: Any = None
    error: str | None = None
    metrics: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("tool result requires a tool name")
        if self.status is ToolStatus.SUCCESS and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if self.status is not ToolStatus.SUCCESS and not self.error:
            raise ValueError("non-successful tool results require an error")

    @classmethod
    def success(
        cls,
        tool_name: str,
        value: Any = None,
        *,
        metrics: Mapping[str, float] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            tool_name=tool_name,
            status=ToolStatus.SUCCESS,
            value=value,
            metrics=dict(metrics or {}),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def error_result(cls, tool_name: str, error: str) -> "ToolResult":
        return cls(tool_name=tool_name, status=ToolStatus.ERROR, error=error)

    @classmethod
    def unavailable(cls, tool_name: str, error: str) -> "ToolResult":
        return cls(tool_name=tool_name, status=ToolStatus.UNAVAILABLE, error=error)

    def to_dict(self) -> JsonMap:
        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "value": self.value,
            "error": self.error,
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
        }


class AgentTool(Protocol):
    @property
    def spec(self) -> ToolSpec:
        """Describe the tool before the agent decides whether to invoke it."""

    def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """Invoke the tool exactly once and return a normalized result."""


ToolHandler = Callable[[Mapping[str, Any], ToolContext], ToolResult]


@dataclass
class FunctionTool:
    """Small adapter for exposing an explicitly supplied callable as a tool."""

    spec: ToolSpec
    handler: ToolHandler

    def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        return self.handler(dict(arguments), context)
