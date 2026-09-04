"""Contracts for bounded goal-driven execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from xgap.agent.environment import AgentEnvironment


JsonMap = dict[str, Any]


class GoalStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class DecisionKind(str, Enum):
    CALL_TOOL = "call_tool"
    SUCCEED = "succeed"
    BLOCK = "block"
    FAIL = "fail"


@dataclass(frozen=True)
class GoalSpec:
    goal_id: str
    objective: str
    success_criteria: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    max_steps: int = 16
    max_tool_calls: int = 12
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.goal_id.strip():
            raise ValueError("goal_id must be nonempty")
        if not self.objective.strip():
            raise ValueError("goal objective must be nonempty")
        if not self.success_criteria or any(not item.strip() for item in self.success_criteria):
            raise ValueError("a goal requires explicit nonempty success criteria")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise ValueError("allowed_tools must be unique")
        if self.max_steps <= 0 or self.max_tool_calls < 0:
            raise ValueError("goal budgets must be nonnegative and max_steps must be positive")
        if self.max_tool_calls > self.max_steps:
            raise ValueError("max_tool_calls cannot exceed max_steps")

    def to_dict(self) -> JsonMap:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "success_criteria": list(self.success_criteria),
            "allowed_tools": list(self.allowed_tools),
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlannedToolCall:
    call_id: str
    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise ValueError("tool call_id must be nonempty")
        if not self.tool_name.strip():
            raise ValueError("tool_name must be nonempty")

    def to_dict(self) -> JsonMap:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True)
class AgentDecision:
    kind: DecisionKind
    reason: str
    tool_call: PlannedToolCall | None = None
    output: Any = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("agent decisions require a reason")
        if self.kind is DecisionKind.CALL_TOOL and self.tool_call is None:
            raise ValueError("CALL_TOOL decisions require a tool call")
        if self.kind is not DecisionKind.CALL_TOOL and self.tool_call is not None:
            raise ValueError("terminal decisions cannot contain a tool call")

    @classmethod
    def call(cls, call: PlannedToolCall, reason: str) -> "AgentDecision":
        return cls(kind=DecisionKind.CALL_TOOL, reason=reason, tool_call=call)

    @classmethod
    def succeed(cls, reason: str, output: Any = None) -> "AgentDecision":
        return cls(kind=DecisionKind.SUCCEED, reason=reason, output=output)

    @classmethod
    def block(cls, reason: str) -> "AgentDecision":
        return cls(kind=DecisionKind.BLOCK, reason=reason)

    @classmethod
    def fail(cls, reason: str) -> "AgentDecision":
        return cls(kind=DecisionKind.FAIL, reason=reason)


@dataclass(frozen=True)
class GoalObservation:
    sequence: int
    kind: str
    source: str
    payload: Mapping[str, Any]

    def to_dict(self) -> JsonMap:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "source": self.source,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class GoalTraceEntry:
    step: int
    decision_kind: DecisionKind
    reason: str
    call_id: str | None = None
    tool_name: str | None = None
    tool_status: str | None = None

    def to_dict(self) -> JsonMap:
        return {
            "step": self.step,
            "decision_kind": self.decision_kind.value,
            "reason": self.reason,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "tool_status": self.tool_status,
        }


@dataclass(frozen=True)
class GoalState:
    goal: GoalSpec
    status: GoalStatus = GoalStatus.PENDING
    steps: int = 0
    tool_calls: int = 0
    observations: tuple[GoalObservation, ...] = ()
    trace: tuple[GoalTraceEntry, ...] = ()
    output: Any = None
    message: str | None = None

    def to_dict(self) -> JsonMap:
        return {
            "goal": self.goal.to_dict(),
            "status": self.status.value,
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "observations": [observation.to_dict() for observation in self.observations],
            "trace": [entry.to_dict() for entry in self.trace],
            "output": self.output,
            "message": self.message,
        }


class AgentPolicy(Protocol):
    def decide(self, state: GoalState, environment: "AgentEnvironment") -> AgentDecision:
        """Choose exactly one bounded action from the current observations."""
