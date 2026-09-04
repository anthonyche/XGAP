"""Goal-driven agent execution for XGAP."""

from xgap.agent.contracts import (
    AgentDecision,
    AgentPolicy,
    DecisionKind,
    GoalObservation,
    GoalSpec,
    GoalState,
    GoalStatus,
    GoalTraceEntry,
    PlannedToolCall,
)
from xgap.agent.environment import AgentEnvironment
from xgap.agent.loop import GoalLoop
from xgap.agent.memory import (
    InMemoryStore,
    MemoryRecord,
    MemoryScope,
    MemoryStore,
)
from xgap.agent.policy import SequentialToolPolicy

__all__ = [
    "AgentDecision",
    "AgentEnvironment",
    "AgentPolicy",
    "DecisionKind",
    "GoalLoop",
    "GoalObservation",
    "GoalSpec",
    "GoalState",
    "GoalStatus",
    "GoalTraceEntry",
    "InMemoryStore",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStore",
    "PlannedToolCall",
    "SequentialToolPolicy",
]
