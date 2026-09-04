"""Offline M15-A goal-loop and pluggable-backend demonstration."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.agent import (
    AgentEnvironment,
    GoalLoop,
    GoalSpec,
    PlannedToolCall,
    SequentialToolPolicy,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport
from xgap.tools import (
    BACKEND_INVOKE_TOOL,
    BackendInvokeTool,
    BackendPluginRegistry,
    NativeBackendPlugin,
    ToolRegistry,
)


@dataclass
class OfflineBackendClient:
    backend_id: str

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "offline fixture ready")

    def execute(self, artifact) -> ExecutionReport:
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[],
            elapsed_ms=0.0,
        )


plugins = BackendPluginRegistry()
for backend_id in ("neo4j", "fuseki"):
    plugins.register(NativeBackendPlugin(backend_id, OfflineBackendClient(backend_id)))

tools = ToolRegistry()
tools.register(BackendInvokeTool(plugins))
environment = AgentEnvironment(
    environment_id="offline-federated-fixture",
    tools=tools,
    metadata={"backends": plugins.describe(), "llm_available": False},
)
goal = GoalSpec(
    goal_id="m15a-backend-readiness",
    objective="observe whether both graph backend adapters are ready",
    success_criteria=("neo4j healthcheck succeeds", "fuseki healthcheck succeeds"),
    allowed_tools=(BACKEND_INVOKE_TOOL,),
    max_steps=4,
    max_tool_calls=2,
)
policy = SequentialToolPolicy(
    tuple(
        PlannedToolCall(
            call_id=f"healthcheck-{backend_id}",
            tool_name=BACKEND_INVOKE_TOOL,
            arguments={"backend_id": backend_id, "operation": "healthcheck"},
        )
        for backend_id in plugins.backend_ids()
    )
)

result = GoalLoop().run(goal, policy, environment)
print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
