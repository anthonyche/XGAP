from __future__ import annotations

from dataclasses import dataclass

import pytest

from xgap.agent import (
    AgentEnvironment,
    GoalLoop,
    GoalSpec,
    GoalStatus,
    PlannedToolCall,
    SequentialToolPolicy,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport
from xgap.runtime import (
    FEDERATED_EXECUTION_TOOL,
    FederatedExecutionPlan,
    FederatedExecutionTool,
    FederatedScheduler,
    RuntimeNode,
    RuntimeNodeKind,
    RuntimeNodeStatus,
    RuntimePlanError,
)
from xgap.tools import (
    BackendInvokeTool,
    BackendPluginRegistry,
    NativeBackendPlugin,
    ToolRegistry,
)


@dataclass
class RowsBackendClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]
    fail: bool = False

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, not self.fail, "ready" if not self.fail else "down")

    def execute(self, artifact) -> ExecutionReport:
        if self.fail:
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="backend unavailable",
            )
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=self.rows_by_artifact.get(artifact.artifact_id, []),
            elapsed_ms=1.25,
        )


def _plan() -> FederatedExecutionPlan:
    return FederatedExecutionPlan(
        plan_id="split-risk-query",
        nodes=(
            RuntimeNode(
                "neo4j-transfers",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "neo4j",
                    "artifact": {
                        "artifact_id": "transfers",
                        "language": "cypher",
                        "text": "MATCH ...",
                    },
                },
                semantic_operator_ids=("match-transfers",),
            ),
            RuntimeNode(
                "fuseki-risk",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "fuseki",
                    "artifact": {
                        "artifact_id": "risk",
                        "language": "sparql",
                        "text": "SELECT ...",
                    },
                },
                semantic_operator_ids=("match-risk",),
            ),
            RuntimeNode(
                "align-transfers",
                RuntimeNodeKind.ALIGN,
                inputs=("neo4j-transfers",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": {"neo:C1": "C1", "neo:C2": "C2"},
                },
            ),
            RuntimeNode(
                "align-risk",
                RuntimeNodeKind.ALIGN,
                inputs=("fuseki-risk",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": {"rdf:C1": "C1"},
                },
            ),
            RuntimeNode(
                "exchange-transfers",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-transfers",),
            ),
            RuntimeNode(
                "exchange-risk",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-risk",),
            ),
            RuntimeNode(
                "join",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("exchange-transfers", "exchange-risk"),
                parameters={
                    "left_on": "canonical_company_id",
                    "right_on": "canonical_company_id",
                },
                semantic_operator_ids=("join-transfer-risk",),
            ),
        ),
        roots=("join",),
        max_remote_calls=2,
        max_parallelism=2,
    )


def _runtime_tool(*, fail_fuseki: bool = False) -> FederatedExecutionTool:
    plugins = BackendPluginRegistry()
    plugins.register(
        NativeBackendPlugin(
            "neo4j",
            RowsBackendClient(
                "neo4j",
                {
                    "transfers": [
                        {"person_id": "alice:1", "company_id": "neo:C1", "amount": 1200},
                        {"person_id": "alice:1", "company_id": "neo:C2", "amount": 900},
                    ]
                },
            ),
        )
    )
    plugins.register(
        NativeBackendPlugin(
            "fuseki",
            RowsBackendClient(
                "fuseki",
                {"risk": [{"company_id": "rdf:C1", "risk": "high"}]},
                fail=fail_fuseki,
            ),
        )
    )
    return FederatedExecutionTool(FederatedScheduler(BackendInvokeTool(plugins)))


def test_two_backend_plan_aligns_exchanges_and_joins() -> None:
    result = _runtime_tool().scheduler.execute(_plan(), goal_id="risk-goal")

    assert result.success
    assert result.total_remote_calls == 2
    assert result.total_bytes_moved > 0
    assert result.final_rows == (
        {
            "person_id": "alice:1",
            "company_id": "neo:C1",
            "amount": 1200,
            "canonical_company_id": "C1",
            "right.company_id": "rdf:C1",
            "risk": "high",
        },
    )
    assert [item.status for item in result.node_results].count(RuntimeNodeStatus.SUCCESS) == 7


def test_failed_backend_skips_dependent_nodes_and_preserves_observation() -> None:
    result = _runtime_tool(fail_fuseki=True).scheduler.execute(_plan())

    assert not result.success
    by_id = {item.node_id: item for item in result.node_results}
    assert by_id["fuseki-risk"].status is RuntimeNodeStatus.ERROR
    assert by_id["align-risk"].status is RuntimeNodeStatus.SKIPPED
    assert by_id["join"].status is RuntimeNodeStatus.SKIPPED
    assert result.total_remote_calls == 2


def test_federated_runtime_is_invokable_from_goal_loop() -> None:
    tools = ToolRegistry()
    tools.register(_runtime_tool())
    environment = AgentEnvironment("offline-split-data", tools)
    goal = GoalSpec(
        goal_id="answer-split-risk-query",
        objective="join transfer and risk facts across graph engines",
        success_criteria=("return the one high-risk company linked to Alice",),
        allowed_tools=(FEDERATED_EXECUTION_TOOL,),
        max_steps=3,
        max_tool_calls=1,
    )
    policy = SequentialToolPolicy(
        (
            PlannedToolCall(
                "execute-federated-plan",
                FEDERATED_EXECUTION_TOOL,
                {"plan": _plan().to_dict()},
            ),
        )
    )

    state = GoalLoop().run(goal, policy, environment)

    assert state.status is GoalStatus.SUCCEEDED
    run = state.observations[-1].payload["value"]
    assert run["success"] is True
    assert run["total_remote_calls"] == 2
    assert len(run["final_rows"]) == 1


def test_runtime_plan_enforces_remote_call_budget() -> None:
    plan = _plan().to_dict()
    plan["max_remote_calls"] = 1
    with pytest.raises(RuntimePlanError, match="remote calls"):
        FederatedExecutionPlan.from_dict(plan)


def test_runtime_plan_rejects_cycles() -> None:
    left = RuntimeNode("left", RuntimeNodeKind.ALIGN, inputs=("right",), parameters={"field": "x"})
    right = RuntimeNode("right", RuntimeNodeKind.EXCHANGE, inputs=("left",))
    with pytest.raises(RuntimePlanError, match="acyclic"):
        FederatedExecutionPlan("cycle", (left, right), ("right",))
