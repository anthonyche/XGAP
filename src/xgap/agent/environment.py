"""Agent environment: tools, memory, and observable deployment metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from xgap.agent.contracts import GoalObservation, GoalSpec
from xgap.agent.memory import InMemoryStore, MemoryStore
from xgap.tools.registry import ToolRegistry


@dataclass
class AgentEnvironment:
    environment_id: str
    tools: ToolRegistry
    memory: MemoryStore = field(default_factory=InMemoryStore)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.environment_id.strip():
            raise ValueError("environment_id must be nonempty")

    def initial_observation(self, goal: GoalSpec) -> GoalObservation:
        available = {spec.name: spec.to_dict() for spec in self.tools.specs()}
        return GoalObservation(
            sequence=0,
            kind="environment",
            source=self.environment_id,
            payload={
                "goal_id": goal.goal_id,
                "available_tools": available,
                "allowed_tools": list(goal.allowed_tools),
                "metadata": dict(self.metadata),
            },
        )
