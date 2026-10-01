"""Bounded observation-decision-action execution loop."""

from __future__ import annotations

from dataclasses import replace

from xgap.agent.contracts import (
    AgentPolicy,
    DecisionKind,
    GoalObservation,
    GoalSpec,
    GoalState,
    GoalStatus,
    GoalTraceEntry,
)
from xgap.agent.environment import AgentEnvironment
from xgap.agent.memory import MemoryRecord, MemoryScope
from xgap.tools.contracts import ToolContext


class GoalLoop:
    """Run a goal with explicit tool allowlists and finite budgets.

    The loop never retries a failed tool automatically.  A policy observes the
    normalized result and must explicitly decide whether to stop or issue a
    different call.
    """

    def run(
        self,
        goal: GoalSpec,
        policy: AgentPolicy,
        environment: AgentEnvironment,
    ) -> GoalState:
        state = GoalState(
            goal=goal,
            status=GoalStatus.RUNNING,
            observations=(environment.initial_observation(goal),),
        )

        while state.status is GoalStatus.RUNNING:
            if state.steps >= goal.max_steps:
                return replace(
                    state,
                    status=GoalStatus.BUDGET_EXHAUSTED,
                    message=f"step budget exhausted at {goal.max_steps}",
                )

            decision = policy.decide(state, environment)
            step = state.steps + 1

            if decision.kind is DecisionKind.CALL_TOOL:
                call = decision.tool_call
                assert call is not None
                if state.tool_calls >= goal.max_tool_calls:
                    return replace(
                        state,
                        status=GoalStatus.BUDGET_EXHAUSTED,
                        steps=step,
                        message=f"tool-call budget exhausted at {goal.max_tool_calls}",
                    )
                if call.tool_name not in goal.allowed_tools:
                    entry = GoalTraceEntry(
                        step=step,
                        decision_kind=decision.kind,
                        reason=decision.reason,
                        call_id=call.call_id,
                        tool_name=call.tool_name,
                        tool_status="denied",
                    )
                    return replace(
                        state,
                        status=GoalStatus.FAILED,
                        steps=step,
                        trace=state.trace + (entry,),
                        message=f"tool '{call.tool_name}' is not allowed for goal '{goal.goal_id}'",
                    )

                context = ToolContext(
                    goal_id=goal.goal_id,
                    step=step,
                    call_id=call.call_id,
                    metadata={"environment_id": environment.environment_id},
                )
                result = environment.tools.invoke(call.tool_name, call.arguments, context)
                observation = GoalObservation(
                    sequence=len(state.observations),
                    kind="tool_result",
                    source=call.tool_name,
                    payload={"call_id": call.call_id, **result.to_dict()},
                )
                entry = GoalTraceEntry(
                    step=step,
                    decision_kind=decision.kind,
                    reason=decision.reason,
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    tool_status=result.status.value,
                )
                environment.memory.put(
                    MemoryRecord(
                        scope=MemoryScope.EXECUTION,
                        key=f"{goal.goal_id}/{call.call_id}",
                        value=result.to_dict(),
                        source=call.tool_name,
                        version="goal-loop-v1",
                    )
                )
                state = replace(
                    state,
                    steps=step,
                    tool_calls=state.tool_calls + 1,
                    observations=state.observations + (observation,),
                    trace=state.trace + (entry,),
                )
                continue

            entry = GoalTraceEntry(
                step=step,
                decision_kind=decision.kind,
                reason=decision.reason,
            )
            terminal_status = {
                DecisionKind.SUCCEED: GoalStatus.SUCCEEDED,
                DecisionKind.BLOCK: GoalStatus.BLOCKED,
                DecisionKind.FAIL: GoalStatus.FAILED,
            }[decision.kind]
            return replace(
                state,
                status=terminal_status,
                steps=step,
                trace=state.trace + (entry,),
                output=decision.output,
                message=decision.reason,
            )

        return state
