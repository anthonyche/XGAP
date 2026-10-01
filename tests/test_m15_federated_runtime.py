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
        rows = list(self.rows_by_artifact.get(artifact.artifact_id, []))
        company_ids = artifact.parameters.get("company_ids")
        if company_ids is not None:
            allowed = {str(item) for item in company_ids}
            rows = [
                row
                for row in rows
                if str(row.get("company_id", "")).removeprefix("neo:") in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
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


def _runtime_tool(
    *,
    fail_fuseki: bool = False,
    fuseki_rows: list[dict[str, object]] | None = None,
) -> FederatedExecutionTool:
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
                {
                    "risk": (
                        [{"company_id": "rdf:C1", "risk": "high"}]
                        if fuseki_rows is None
                        else fuseki_rows
                    )
                },
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


def test_continuation_seed_must_be_a_valid_ancestor_closed_prefix() -> None:
    scheduler = _runtime_tool().scheduler
    completed = scheduler.execute(_plan())
    by_id = {item.node_id: item for item in completed.node_results}

    with pytest.raises(RuntimePlanError, match="must be a mapping"):
        scheduler.execute(
            _plan(),
            initial_results=[by_id["neo4j-transfers"]],  # type: ignore[arg-type]
        )
    with pytest.raises(RuntimePlanError, match="unknown node"):
        scheduler.execute(
            _plan(),
            initial_results={"unknown": by_id["neo4j-transfers"]},
        )
    with pytest.raises(RuntimePlanError, match="ancestor-closed"):
        scheduler.execute(
            _plan(),
            initial_results={"align-transfers": by_id["align-transfers"]},
        )


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


def test_coordinator_project_removes_internal_join_fields() -> None:
    base = _plan()
    project = RuntimeNode(
        "project",
        RuntimeNodeKind.PROJECT,
        inputs=("join",),
        parameters={"fields": ["person_id", "amount", "risk"]},
    )
    plan = FederatedExecutionPlan(
        plan_id="projected-split-risk-query",
        nodes=base.nodes + (project,),
        roots=("project",),
        max_remote_calls=base.max_remote_calls,
        max_parallelism=base.max_parallelism,
    )

    result = _runtime_tool().scheduler.execute(plan)

    assert result.success
    assert result.final_rows == (
        {"person_id": "alice:1", "amount": 1200, "risk": "high"},
    )


def _bind_plan(*, max_bindings: int = 8) -> FederatedExecutionPlan:
    return FederatedExecutionPlan(
        plan_id="risk-first-bind-query",
        nodes=(
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
                "exchange-risk",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-risk",),
            ),
            RuntimeNode(
                "neo4j-bound-transfers",
                RuntimeNodeKind.REMOTE_BIND_QUERY,
                inputs=("exchange-risk",),
                parameters={
                    "backend_id": "neo4j",
                    "artifact": {
                        "artifact_id": "transfers",
                        "language": "cypher",
                        "text": "MATCH ... WHERE company.id IN $company_ids",
                    },
                    "bind_field": "canonical_company_id",
                    "parameter": "company_ids",
                    "max_bindings": max_bindings,
                },
            ),
            RuntimeNode(
                "align-transfers",
                RuntimeNodeKind.ALIGN,
                inputs=("neo4j-bound-transfers",),
                parameters={
                    "field": "company_id",
                    "output_field": "canonical_company_id",
                    "mapping": {"neo:C1": "C1", "neo:C2": "C2"},
                },
            ),
            RuntimeNode(
                "exchange-transfers",
                RuntimeNodeKind.EXCHANGE,
                inputs=("align-transfers",),
            ),
            RuntimeNode(
                "join",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("exchange-transfers", "exchange-risk"),
                parameters={
                    "left_on": "canonical_company_id",
                    "right_on": "canonical_company_id",
                },
            ),
        ),
        roots=("join",),
        max_remote_calls=2,
        max_parallelism=2,
    )


def test_risk_first_bind_query_matches_parallel_hash_answer() -> None:
    runtime = _runtime_tool()

    parallel = runtime.scheduler.execute(_plan())
    bound = runtime.scheduler.execute(_bind_plan())

    assert parallel.success and bound.success
    assert bound.final_rows == parallel.final_rows
    by_id = {item.node_id: item for item in bound.node_results}
    assert by_id["neo4j-bound-transfers"].metadata["binding_count"] == 1
    assert bound.total_remote_calls == 2
    assert bound.total_bytes_moved < parallel.total_bytes_moved


def test_bind_query_short_circuits_empty_driver_without_remote_call() -> None:
    result = _runtime_tool(fuseki_rows=[]).scheduler.execute(_bind_plan())

    assert result.success
    assert result.final_rows == ()
    bound = next(
        item for item in result.node_results if item.node_id == "neo4j-bound-transfers"
    )
    assert bound.remote_calls == 0
    assert bound.metadata["empty_binding_short_circuit"] is True
    assert result.total_remote_calls == 1


def test_bind_query_limit_fails_before_backend_invocation() -> None:
    result = _runtime_tool().scheduler.execute(_bind_plan(max_bindings=0))

    assert not result.success
    bound = next(
        item for item in result.node_results if item.node_id == "neo4j-bound-transfers"
    )
    assert bound.status is RuntimeNodeStatus.ERROR
    assert "positive max_bindings" in str(bound.error)
    assert bound.remote_calls == 0


def test_coordinator_semi_join_returns_only_matching_left_rows() -> None:
    base = _plan()
    semi = RuntimeNode(
        "semi",
        RuntimeNodeKind.COORDINATOR_SEMI_JOIN,
        inputs=("align-transfers", "align-risk"),
        parameters={
            "left_on": "canonical_company_id",
            "right_on": "canonical_company_id",
        },
    )
    plan = FederatedExecutionPlan(
        "semi-risk",
        base.nodes[:4] + (semi,),
        ("semi",),
        max_remote_calls=2,
        max_parallelism=2,
    )

    result = _runtime_tool().scheduler.execute(plan)

    assert result.success
    assert result.final_rows == (
        {
            "person_id": "alice:1",
            "company_id": "neo:C1",
            "amount": 1200,
            "canonical_company_id": "C1",
        },
    )


def test_collection_semi_join_group_aggregate_and_top_k() -> None:
    runtime = _runtime_tool()
    plan = FederatedExecutionPlan(
        "aggregate-risk",
        (
            RuntimeNode(
                "accounts",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "neo4j",
                    "artifact": {
                        "artifact_id": "account-amounts",
                        "language": "cypher",
                        "text": "MATCH ...",
                    },
                },
            ),
            RuntimeNode(
                "risk",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "fuseki",
                    "artifact": {
                        "artifact_id": "medium-risk",
                        "language": "sparql",
                        "text": "SELECT ...",
                    },
                },
            ),
            RuntimeNode(
                "eligible",
                RuntimeNodeKind.COORDINATOR_SEMI_JOIN,
                inputs=("accounts", "risk"),
                parameters={
                    "left_on": "medium_ids",
                    "right_on": "medium_id",
                    "left_value_mode": "collection",
                },
            ),
            RuntimeNode(
                "totals",
                RuntimeNodeKind.COORDINATOR_GROUP_AGGREGATE,
                inputs=("eligible",),
                parameters={
                    "group_by": ["company_id"],
                    "aggregations": {
                        "total_amount": {"op": "sum", "field": "account_amount"}
                    },
                },
            ),
            RuntimeNode(
                "top",
                RuntimeNodeKind.COORDINATOR_SORT_LIMIT,
                inputs=("totals",),
                parameters={
                    "order_by": [
                        {"field": "total_amount", "direction": "desc"},
                        {"field": "company_id", "direction": "asc"},
                    ],
                    "limit": 2,
                },
            ),
        ),
        ("top",),
        max_remote_calls=2,
        max_parallelism=2,
    )
    runtime.scheduler._backend_tool.backends._plugins["neo4j"].client.rows_by_artifact[
        "account-amounts"
    ] = [
        {"company_id": "C1", "medium_ids": ["M1", "M2"], "account_amount": 3.1},
        {"company_id": "C1", "medium_ids": ["M2"], "account_amount": 4.2},
        {"company_id": "C2", "medium_ids": ["M3"], "account_amount": 8.0},
        {"company_id": "C3", "medium_ids": ["M1"], "account_amount": 7.5},
    ]
    runtime.scheduler._backend_tool.backends._plugins["fuseki"].client.rows_by_artifact[
        "medium-risk"
    ] = [{"medium_id": "M1"}, {"medium_id": "M2"}]

    result = runtime.scheduler.execute(plan)

    assert result.success
    assert result.final_rows == (
        {"company_id": "C3", "total_amount": 7.5},
        {"company_id": "C1", "total_amount": 7.3},
    )


@pytest.mark.parametrize(
    ("kind", "parameters", "message"),
    [
        (
            RuntimeNodeKind.COORDINATOR_GROUP_AGGREGATE,
            {"group_by": [], "aggregations": {"n": {"op": "count"}}},
            "group_by",
        ),
        (
            RuntimeNodeKind.COORDINATOR_SORT_LIMIT,
            {"order_by": [{"field": "x"}], "limit": 0},
            "positive integer",
        ),
    ],
)
def test_new_coordinator_operators_fail_closed(kind, parameters, message) -> None:
    base = _plan()
    node = RuntimeNode("invalid-local", kind, inputs=("neo4j-transfers",), parameters=parameters)
    plan = FederatedExecutionPlan(
        "invalid-local-plan",
        base.nodes[:2] + (node,),
        ("invalid-local",),
        max_remote_calls=2,
    )

    result = _runtime_tool().scheduler.execute(plan)

    assert not result.success
    assert message in str(result.node_results[-1].error)
