from __future__ import annotations

from dataclasses import dataclass

import pytest

from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import (
    FederatedExecutionPlan,
    FederatedPlanCandidate,
    FederatedPlanSelector,
    FederatedPlanningError,
    PlanObservationSnapshot,
    PlanObservationCollector,
    PlanObservationRequest,
    RemoteEstimate,
    RuntimeNode,
    RuntimeNodeKind,
)
from xgap.tools import (
    BackendInvokeTool,
    BackendObservationCatalog,
    BackendOperation,
    BackendPluginRegistry,
    CatalogBackendPlugin,
    ToolContext,
)


SEMANTIC_KEY = "m15:recent-alice-transfers-to-high-risk-company:v1"


def _remote(
    node_id: str,
    backend_id: str,
    observation_key: str,
    *,
    kind: RuntimeNodeKind = RuntimeNodeKind.REMOTE_QUERY,
    inputs: tuple[str, ...] = (),
) -> RuntimeNode:
    parameters: dict[str, object] = {
        "backend_id": backend_id,
        "observation_key": observation_key,
        "artifact": {
            "artifact_id": node_id,
            "language": "cypher" if backend_id == "neo4j" else "sparql",
            "text": "RETURN 1" if backend_id == "neo4j" else "SELECT * WHERE {}",
        },
    }
    if kind is RuntimeNodeKind.REMOTE_BIND_QUERY:
        parameters.update(
            {
                "bind_field": "company_id",
                "parameter": "company_ids",
                "max_bindings": 100,
            }
        )
    return RuntimeNode(
        node_id=node_id,
        kind=kind,
        inputs=inputs,
        parameters=parameters,
    )


def _parallel_plan() -> FederatedExecutionPlan:
    return FederatedExecutionPlan(
        plan_id="parallel-hash",
        nodes=(
            _remote("transfers", "neo4j", "neo4j-full"),
            _remote("risks", "fuseki", "fuseki-risk"),
            RuntimeNode(
                "transfer-exchange",
                RuntimeNodeKind.EXCHANGE,
                inputs=("transfers",),
            ),
            RuntimeNode(
                "risk-exchange",
                RuntimeNodeKind.EXCHANGE,
                inputs=("risks",),
            ),
            RuntimeNode(
                "answer",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("transfer-exchange", "risk-exchange"),
                parameters={"join_selectivity": 1.0},
            ),
        ),
        roots=("answer",),
    )


def _bind_plan() -> FederatedExecutionPlan:
    return FederatedExecutionPlan(
        plan_id="risk-first-bind",
        nodes=(
            _remote("risks", "fuseki", "fuseki-risk"),
            RuntimeNode(
                "risk-exchange",
                RuntimeNodeKind.EXCHANGE,
                inputs=("risks",),
            ),
            _remote(
                "bound-transfers",
                "neo4j",
                "neo4j-bound",
                kind=RuntimeNodeKind.REMOTE_BIND_QUERY,
                inputs=("risk-exchange",),
            ),
            RuntimeNode(
                "transfer-exchange",
                RuntimeNodeKind.EXCHANGE,
                inputs=("bound-transfers",),
            ),
            RuntimeNode(
                "answer",
                RuntimeNodeKind.COORDINATOR_JOIN,
                inputs=("transfer-exchange", "risk-exchange"),
                parameters={"join_selectivity": 1.0},
            ),
        ),
        roots=("answer",),
    )


def _candidates() -> tuple[FederatedPlanCandidate, ...]:
    return (
        FederatedPlanCandidate(_parallel_plan(), SEMANTIC_KEY),
        FederatedPlanCandidate(_bind_plan(), SEMANTIC_KEY),
    )


def _snapshot(*, bound_latency_ms: float = 40.0) -> PlanObservationSnapshot:
    return PlanObservationSnapshot(
        snapshot_id=f"controlled-{bound_latency_ms:g}",
        version="v1",
        estimates=(
            RemoteEstimate(
                "neo4j-full",
                "neo4j",
                elapsed_ms=50.0,
                row_count=10_000,
                row_width_bytes=100.0,
                source="controlled/neo4j-full",
                version="v1",
            ),
            RemoteEstimate(
                "neo4j-bound",
                "neo4j",
                elapsed_ms=bound_latency_ms,
                row_count=10,
                row_width_bytes=100.0,
                source="controlled/neo4j-bound",
                version="v1",
            ),
            RemoteEstimate(
                "fuseki-risk",
                "fuseki",
                elapsed_ms=10.0,
                row_count=10,
                row_width_bytes=30.0,
                source="controlled/fuseki-risk",
                version="v1",
            ),
        ),
        bandwidth_bytes_per_ms=1_000.0,
        exchange_fixed_ms=0.5,
        coordinator_row_ms=0.001,
    )


def test_selector_prefers_bind_when_it_avoids_large_transfer() -> None:
    selection = FederatedPlanSelector().select(_candidates(), _snapshot())

    assert selection.selected_plan_id == "risk-first-bind"
    costs = {item.plan_id: item for item in selection.estimates}
    assert costs["risk-first-bind"].predicted_transfer_bytes < costs[
        "parallel-hash"
    ].predicted_transfer_bytes
    assert costs["risk-first-bind"].observation_keys == (
        "fuseki-risk",
        "neo4j-bound",
    )


def test_selector_estimates_group_reduction_and_ordered_limit() -> None:
    plan = FederatedExecutionPlan(
        plan_id="aggregate-top-k",
        nodes=(
            _remote("transfers", "neo4j", "neo4j-full"),
            RuntimeNode(
                "company-totals",
                RuntimeNodeKind.COORDINATOR_GROUP_AGGREGATE,
                inputs=("transfers",),
                parameters={"group_reduction_fraction": 0.25},
            ),
            RuntimeNode(
                "top-companies",
                RuntimeNodeKind.COORDINATOR_SORT_LIMIT,
                inputs=("company-totals",),
                parameters={
                    "order_by": [{"field": "total_amount", "direction": "desc"}],
                    "limit": 10,
                },
            ),
        ),
        roots=("top-companies",),
    )

    selection = FederatedPlanSelector().select(
        (FederatedPlanCandidate(plan, SEMANTIC_KEY),), _snapshot()
    )

    estimate = selection.estimates[0]
    assert estimate.node_row_counts["company-totals"] == 2_500
    assert estimate.node_row_counts["top-companies"] == 10
    assert selection.to_dict()["snapshot_version"] == "v1"


def test_selector_flips_to_parallel_when_bound_query_is_slow() -> None:
    selection = FederatedPlanSelector().select(
        _candidates(),
        _snapshot(bound_latency_ms=2_000.0),
    )

    assert selection.selected_plan_id == "parallel-hash"


def test_selector_refuses_mixed_semantics_or_missing_evidence() -> None:
    selector = FederatedPlanSelector()
    mixed = (
        _candidates()[0],
        FederatedPlanCandidate(_bind_plan(), "different-semantics"),
    )
    with pytest.raises(FederatedPlanningError, match="semantic equivalence"):
        selector.select(mixed, _snapshot())

    incomplete = PlanObservationSnapshot(
        snapshot_id="incomplete",
        version="v1",
        estimates=_snapshot().estimates[:1],
        bandwidth_bytes_per_ms=1_000.0,
    )
    with pytest.raises(FederatedPlanningError, match="has no estimate"):
        selector.estimate(_bind_plan(), incomplete)


def test_selector_refuses_observation_from_wrong_backend() -> None:
    bad = PlanObservationSnapshot(
        snapshot_id="wrong-backend",
        version="v1",
        estimates=(
            RemoteEstimate(
                "fuseki-risk",
                "fuseki",
                elapsed_ms=1.0,
                row_count=1,
                row_width_bytes=1.0,
                source="controlled/fuseki",
                version="v1",
            ),
            RemoteEstimate(
                "neo4j-full",
                "fuseki",
                elapsed_ms=1.0,
                row_count=1,
                row_width_bytes=1.0,
                source="controlled/wrong",
                version="v1",
            ),
        ),
        bandwidth_bytes_per_ms=1.0,
    )
    with pytest.raises(FederatedPlanningError, match="belongs to backend"):
        FederatedPlanSelector().estimate(_parallel_plan(), bad)


@dataclass
class _ObservedClient:
    backend_id: str = "neo4j"

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[{"company_id": "C1"}, {"company_id": "C2"}],
            elapsed_ms=7.5,
        )


def test_remote_estimate_is_derived_from_catalog_observation_with_provenance() -> None:
    plugins = BackendPluginRegistry()
    plugins.register(
        CatalogBackendPlugin(
            "neo4j",
            _ObservedClient(),
            BackendObservationCatalog(
                "m15-catalog",
                "v3",
                sample_artifacts={
                    "companies": QueryArtifact(
                        "sample-companies",
                        "cypher",
                        "MATCH (c:Company) RETURN c.id AS company_id LIMIT 2",
                    )
                },
            ),
        )
    )
    result = BackendInvokeTool(plugins).invoke(
        {
            "backend_id": "neo4j",
            "operation": "sample",
            "payload": {"sample_id": "companies"},
        },
        ToolContext(goal_id="g", step=1, call_id="sample"),
    )

    estimate = RemoteEstimate.from_tool_result("neo4j-sample", result)

    assert estimate.backend_id == "neo4j"
    assert estimate.elapsed_ms == 7.5
    assert estimate.row_count == 2
    assert estimate.version == "v3"
    assert "m15-catalog/sample-companies/" in estimate.source
    assert estimate.output_bytes > 0


def _observation_tool(client: _ObservedClient) -> BackendInvokeTool:
    plugins = BackendPluginRegistry()
    plugins.register(
        CatalogBackendPlugin(
            "neo4j",
            client,
            BackendObservationCatalog(
                "m15-collector-catalog",
                "catalog-v1",
                sample_artifacts={
                    "companies": QueryArtifact(
                        "sample-companies",
                        "cypher",
                        "MATCH (c:Company) RETURN c.id AS company_id LIMIT 2",
                    )
                },
            ),
        )
    )
    return BackendInvokeTool(plugins)


def _sample_request(call_id: str, observation_key: str, sample_id: str):
    return PlanObservationRequest(
        call_id,
        observation_key,
        "neo4j",
        BackendOperation.SAMPLE,
        {"sample_id": sample_id},
    )


def test_observation_collector_freezes_complete_snapshot_without_retry() -> None:
    collector = PlanObservationCollector(_observation_tool(_ObservedClient()))

    collection = collector.collect(
        (_sample_request("sample-1", "neo4j-company-sample", "companies"),),
        snapshot_id="live-m15",
        version="task-0",
        bandwidth_bytes_per_ms=1000.0,
        exchange_fixed_ms=0.5,
        coordinator_row_ms=0.001,
    )

    assert collection.success
    assert collection.attempted_calls == 1
    assert collection.snapshot is not None
    assert collection.snapshot.snapshot_id == "live-m15"
    assert collection.snapshot.estimates[0].source.startswith(
        "m15-collector-catalog/sample-companies/"
    )
    assert collection.to_dict()["automatic_retries"] == 0


def test_observation_collector_stops_on_first_failure_and_keeps_partial_evidence() -> None:
    collector = PlanObservationCollector(_observation_tool(_ObservedClient()))
    requests = (
        _sample_request("sample-1", "observed-1", "companies"),
        _sample_request("missing", "observed-2", "missing"),
        _sample_request("must-not-run", "observed-3", "companies"),
    )

    collection = collector.collect(
        requests,
        snapshot_id="failed-m15",
        version="task-0",
        bandwidth_bytes_per_ms=1000.0,
    )

    assert not collection.success
    assert collection.snapshot is None
    assert collection.attempted_calls == 2
    assert [result.status.value for result in collection.tool_results] == [
        "success",
        "unavailable",
    ]
    assert "must-not-run" not in str(collection.to_dict()["tool_results"])


def test_observation_collector_rejects_invalid_contract_before_tool_calls() -> None:
    collector = PlanObservationCollector(_observation_tool(_ObservedClient()))
    request = _sample_request("same", "same-key", "companies")

    with pytest.raises(FederatedPlanningError, match="call ids must be unique"):
        collector.collect(
            (request, request),
            snapshot_id="invalid",
            version="task-0",
            bandwidth_bytes_per_ms=1000.0,
        )
