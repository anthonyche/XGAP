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
    JsonlMemoryStore,
    MemoryRecord,
    MemoryScope,
    MemoryStore,
)
from xgap.agent.policy import SequentialToolPolicy
from xgap.agent.resolution import (
    SelectiveResolutionConfig,
    SelectiveSemanticResolutionPolicy,
    build_selective_resolution_goal,
    hard_constraints_sha256,
    selective_resolution_environment,
)

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
    "JsonlMemoryStore",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStore",
    "PlannedToolCall",
    "SequentialToolPolicy",
    "SelectiveResolutionConfig",
    "SelectiveSemanticResolutionPolicy",
    "build_selective_resolution_goal",
    "hard_constraints_sha256",
    "selective_resolution_environment",
]
