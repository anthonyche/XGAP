"""Deterministic baseline policies for the goal loop."""

from __future__ import annotations

from dataclasses import dataclass

from xgap.agent.contracts import AgentDecision, GoalState, PlannedToolCall
from xgap.agent.environment import AgentEnvironment
from xgap.tools.contracts import ToolStatus


@dataclass(frozen=True)
class SequentialToolPolicy:
    """Execute a frozen tool sequence and stop on the first failed observation.

    This policy is the deterministic baseline for milestone and experiment
    orchestration.  Learned or LLM-backed policies can implement the same
    ``AgentPolicy`` contract later without changing the loop.
    """

    calls: tuple[PlannedToolCall, ...]

    def decide(self, state: GoalState, environment: AgentEnvironment) -> AgentDecision:
        del environment
        tool_observations = [
            observation for observation in state.observations if observation.kind == "tool_result"
        ]
        if tool_observations:
            latest = tool_observations[-1]
            status = latest.payload.get("status")
            if status == ToolStatus.UNAVAILABLE.value:
                return AgentDecision.block(
                    f"required tool is unavailable: {latest.payload.get('error')}"
                )
            if status == ToolStatus.ERROR.value:
                return AgentDecision.fail(f"tool failed: {latest.payload.get('error')}")

        if state.tool_calls < len(self.calls):
            call = self.calls[state.tool_calls]
            return AgentDecision.call(call, f"execute planned call '{call.call_id}'")

        return AgentDecision.succeed(
            "all planned tool calls completed successfully",
            output={
                "completed_call_ids": [call.call_id for call in self.calls],
                "success_criteria": list(state.goal.success_criteria),
            },
        )
