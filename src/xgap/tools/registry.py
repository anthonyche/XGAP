"""Deterministic registry for agent-visible tools."""

from __future__ import annotations

from typing import Any, Mapping

from xgap.tools.contracts import AgentTool, ToolContext, ToolResult, ToolSpec


class ToolRegistryError(ValueError):
    """Raised for invalid tool registration."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ToolRegistryError(f"tool '{name}' is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolRegistryError(f"tool '{name}' is not registered") from exc

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name].spec for name in sorted(self._tools))

    def invoke(
        self,
        name: str,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.unavailable(name, f"tool '{name}' is not registered")
        try:
            result = tool.invoke(dict(arguments), context)
        except Exception as exc:  # A remote/tool failure becomes an observation.
            return ToolResult.error_result(name, f"{type(exc).__name__}: {exc}")
        if result.tool_name != name:
            return ToolResult.error_result(
                name,
                f"tool returned result for '{result.tool_name}' instead of '{name}'",
            )
        return result
