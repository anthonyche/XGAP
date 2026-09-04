"""Agent-visible tool for executing a bounded federated plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from xgap.runtime.contracts import FederatedExecutionPlan, RuntimePlanError
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools.contracts import ToolContext, ToolEffect, ToolResult, ToolSpec, ToolStatus


FEDERATED_EXECUTION_TOOL = "runtime.execute_plan"


@dataclass
class FederatedExecutionTool:
    scheduler: FederatedScheduler

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=FEDERATED_EXECUTION_TOOL,
            description="Execute a bounded federated plan over registered graph backends",
            input_schema={
                "type": "object",
                "required": ["plan"],
                "properties": {"plan": {"type": "object"}},
            },
            output_kind="federated_run_result",
            effect=ToolEffect.EXTERNAL,
            remote=True,
            tags=("federated", "runtime", "coordinator"),
        )

    def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        raw_plan = arguments.get("plan")
        if not isinstance(raw_plan, Mapping):
            return ToolResult.error_result(FEDERATED_EXECUTION_TOOL, "plan must be a mapping")
        try:
            plan = FederatedExecutionPlan.from_dict(raw_plan)
        except RuntimePlanError as exc:
            return ToolResult.error_result(FEDERATED_EXECUTION_TOOL, str(exc))
        result = self.scheduler.execute(plan, goal_id=context.goal_id)
        metrics = {
            "elapsed_ms": result.elapsed_ms,
            "remote_calls": float(result.total_remote_calls),
            "bytes_moved": float(result.total_bytes_moved),
            "row_count": float(len(result.final_rows)),
        }
        if result.success:
            return ToolResult.success(
                FEDERATED_EXECUTION_TOOL,
                result.to_dict(),
                metrics=metrics,
            )
        return ToolResult(
            tool_name=FEDERATED_EXECUTION_TOOL,
            status=ToolStatus.ERROR,
            value=result.to_dict(),
            error="federated plan did not produce every root",
            metrics=metrics,
        )
