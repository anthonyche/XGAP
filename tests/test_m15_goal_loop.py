from __future__ import annotations

from pathlib import Path

import pytest

from xgap.agent import (
    AgentEnvironment,
    GoalLoop,
    GoalSpec,
    GoalStatus,
    InMemoryStore,
    JsonlMemoryStore,
    MemoryRecord,
    MemoryScope,
    PlannedToolCall,
    SequentialToolPolicy,
)
from xgap.tools import FunctionTool, ToolEffect, ToolRegistry, ToolResult, ToolSpec


def _tool(name: str, outcome: str = "success") -> FunctionTool:
    spec = ToolSpec(
        name=name,
        description=f"test tool {name}",
        input_schema={"type": "object"},
        output_kind="test_observation",
        effect=ToolEffect.READ_ONLY,
    )

    def handler(arguments, context):
        if outcome == "unavailable":
            return ToolResult.unavailable(name, "offline")
        if outcome == "error":
            return ToolResult.error_result(name, "failed")
        return ToolResult.success(
            name,
            {"arguments": dict(arguments), "goal_id": context.goal_id},
        )

    return FunctionTool(spec, handler)


def _goal(*allowed_tools: str, max_steps: int = 5, max_tool_calls: int = 3) -> GoalSpec:
    return GoalSpec(
        goal_id="goal-1",
        objective="complete the deterministic checks",
        success_criteria=("all checks return success",),
        allowed_tools=allowed_tools,
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
    )


def test_goal_loop_executes_tools_records_trace_and_memory() -> None:
    registry = ToolRegistry()
    registry.register(_tool("inspect.schema"))
    registry.register(_tool("backend.profile"))
    memory = InMemoryStore()
    environment = AgentEnvironment("test", registry, memory)
    policy = SequentialToolPolicy(
        (
            PlannedToolCall("inspect", "inspect.schema", {"source": "neo4j"}),
            PlannedToolCall("profile", "backend.profile", {"query": "q1"}),
        )
    )

    state = GoalLoop().run(
        _goal("inspect.schema", "backend.profile"),
        policy,
        environment,
    )

    assert state.status is GoalStatus.SUCCEEDED
    assert state.tool_calls == 2
    assert state.steps == 3
    assert [entry.tool_status for entry in state.trace[:2]] == ["success", "success"]
    assert len(memory.records(MemoryScope.EXECUTION)) == 2


def test_goal_loop_blocks_when_required_tool_is_unavailable() -> None:
    registry = ToolRegistry()
    registry.register(_tool("remote.llm", "unavailable"))
    environment = AgentEnvironment("test", registry)
    policy = SequentialToolPolicy((PlannedToolCall("llm", "remote.llm"),))

    state = GoalLoop().run(_goal("remote.llm"), policy, environment)

    assert state.status is GoalStatus.BLOCKED
    assert state.tool_calls == 1
    assert "unavailable" in str(state.message)


def test_goal_loop_does_not_retry_failed_tool() -> None:
    registry = ToolRegistry()
    registry.register(_tool("backend.execute", "error"))
    environment = AgentEnvironment("test", registry)
    policy = SequentialToolPolicy((PlannedToolCall("execute", "backend.execute"),))

    state = GoalLoop().run(_goal("backend.execute"), policy, environment)

    assert state.status is GoalStatus.FAILED
    assert state.tool_calls == 1


def test_goal_loop_enforces_tool_allowlist() -> None:
    registry = ToolRegistry()
    registry.register(_tool("backend.execute"))
    environment = AgentEnvironment("test", registry)
    policy = SequentialToolPolicy((PlannedToolCall("execute", "backend.execute"),))

    state = GoalLoop().run(_goal("inspect.schema"), policy, environment)

    assert state.status is GoalStatus.FAILED
    assert state.tool_calls == 0
    assert "not allowed" in str(state.message)


def test_goal_loop_enforces_tool_call_budget() -> None:
    registry = ToolRegistry()
    registry.register(_tool("inspect.schema"))
    environment = AgentEnvironment("test", registry)
    policy = SequentialToolPolicy((PlannedToolCall("inspect", "inspect.schema"),))
    goal = _goal("inspect.schema", max_steps=1, max_tool_calls=0)

    state = GoalLoop().run(goal, policy, environment)

    assert state.status is GoalStatus.BUDGET_EXHAUSTED
    assert state.tool_calls == 0


def test_jsonl_memory_persists_current_records_and_append_only_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory" / "observations.jsonl"
    store = JsonlMemoryStore(path, clock=lambda: 15.0)
    first = MemoryRecord(
        MemoryScope.EXECUTION,
        "query/q1",
        {"latency_ms": 10.0},
        "backend.profile",
        "v1",
        created_at=10.0,
    )
    second = MemoryRecord(
        MemoryScope.EXECUTION,
        "query/q1",
        {"latency_ms": 8.0},
        "backend.profile",
        "v2",
        created_at=11.0,
    )
    store.put(first)
    store.put(second)

    reopened = JsonlMemoryStore(path, clock=lambda: 15.0)

    assert reopened.get(MemoryScope.EXECUTION, "query/q1") == second
    assert reopened.records(MemoryScope.EXECUTION) == (second,)
    assert reopened.history(MemoryScope.EXECUTION) == (first, second)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_jsonl_memory_expires_live_value_but_retains_audit_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.jsonl"
    store = JsonlMemoryStore(path, clock=lambda: 15.0)
    store.put(
        MemoryRecord(
            MemoryScope.CACHE,
            "schema/neo4j",
            {"labels": ["Company"]},
            "backend.inspect",
            "v1",
            created_at=10.0,
            expires_at=20.0,
        )
    )

    reopened = JsonlMemoryStore(path, clock=lambda: 25.0)

    assert reopened.get(MemoryScope.CACHE, "schema/neo4j") is None
    assert len(reopened.history(MemoryScope.CACHE)) == 1


def test_jsonl_memory_fails_closed_on_malformed_or_non_json_value(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSONL memory line"):
        JsonlMemoryStore(malformed)

    store = JsonlMemoryStore(tmp_path / "valid.jsonl")
    with pytest.raises(ValueError, match="not JSON serializable"):
        store.put(
            MemoryRecord(
                MemoryScope.EXECUTION,
                "bad",
                {"value": object()},
                "test",
                "v1",
            )
        )


def test_jsonl_memory_rejects_even_a_broken_symbolic_link(tmp_path: Path) -> None:
    path = tmp_path / "memory.jsonl"
    path.symlink_to(tmp_path / "missing-target.jsonl")

    with pytest.raises(ValueError, match="regular file"):
        JsonlMemoryStore(path)
