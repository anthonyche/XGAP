from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from xgap.agent import JsonlMemoryStore
from xgap.experiments.m15_live_federated import build_m15_plan_candidates
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import (
    AdaptiveExecutionError,
    AdaptiveFederatedExecutor,
    FederatedExecutionPlan,
    FederatedScheduler,
    FederatedPlanningError,
    PlanObservationSnapshot,
    PlanSnapshotMemory,
    ProbeObservation,
    RemoteEstimate,
    ReplanPolicy,
)
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CountingClient:
    backend_id: str
    rows: list[dict[str, object]]
    fail: bool = False
    artifact_ids: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, not self.fail, "ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_ids.append(artifact.artifact_id)
        if self.fail:
            return ExecutionReport(
                self.backend_id,
                artifact.artifact_id,
                artifact.language,
                False,
                error="probe unavailable",
            )
        rows = self.rows
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            rows = [
                row
                for row in rows
                if str(row.get("company_id", "")).removeprefix("neo:")
                in company_ids
            ]
        return ExecutionReport(
            self.backend_id,
            artifact.artifact_id,
            artifact.language,
            True,
            rows=rows,
            elapsed_ms=1.0,
        )


def _executor(
    *,
    fail_fuseki: bool = False,
) -> tuple[AdaptiveFederatedExecutor, dict[str, CountingClient]]:
    clients = {
        "neo4j": CountingClient(
            "neo4j",
            [
                {
                    "person_id": "person-alice-smith",
                    "person": "Alice Smith",
                    "company_id": "neo:C1",
                    "amount": 120000,
                    "currency": "USD",
                    "occurred_on": "2026-08-20",
                },
                {
                    "person_id": "person-alice-smith",
                    "person": "Alice Smith",
                    "company_id": "neo:C2",
                    "amount": 90000,
                    "currency": "USD",
                    "occurred_on": "2026-08-25",
                },
            ],
        ),
        "fuseki": CountingClient(
            "fuseki",
            [
                {
                    "company_id": "rdf:C1",
                    "company": "Redstone Analytics",
                    "risk": "HIGH",
                },
                {
                    "company_id": "rdf:C3",
                    "company": "Old Peak Holdings",
                    "risk": "HIGH",
                },
            ],
            fail=fail_fuseki,
        ),
    }
    plugins = BackendPluginRegistry()
    for backend_id, client in clients.items():
        plugins.register(NativeBackendPlugin(backend_id, client))
    scheduler = FederatedScheduler(BackendInvokeTool(plugins))
    return AdaptiveFederatedExecutor(scheduler), clients


def _stale_snapshot() -> PlanObservationSnapshot:
    return PlanObservationSnapshot(
        snapshot_id="m15-adaptive",
        version="task-0",
        estimates=(
            RemoteEstimate(
                "neo4j-recent-transfers-full",
                "neo4j",
                50.0,
                10_000,
                100.0,
                "prior-task/neo4j-full",
                "task-0",
            ),
            RemoteEstimate(
                "neo4j-recent-transfers-bound",
                "neo4j",
                40.0,
                10,
                100.0,
                "prior-task/neo4j-bound",
                "task-0",
            ),
            RemoteEstimate(
                "fuseki-high-risk",
                "fuseki",
                2_000.0,
                2,
                80.0,
                "prior-task/fuseki-risk",
                "task-0",
            ),
        ),
        bandwidth_bytes_per_ms=1_000.0,
        exchange_fixed_ms=0.5,
        coordinator_row_ms=0.001,
    )


def _probe_plan() -> FederatedExecutionPlan:
    candidates = build_m15_plan_candidates(REPO_ROOT)
    nodes = {node.node_id: node for node in candidates[0].plan.nodes}
    return FederatedExecutionPlan(
        plan_id="m15-risk-probe-prefix",
        nodes=(nodes["high-risk"], nodes["align-risk"], nodes["exchange-risk"]),
        roots=("exchange-risk",),
        max_remote_calls=1,
        max_parallelism=1,
        metadata={"execution_phase": "adaptive_probe"},
    )


def _run(executor: AdaptiveFederatedExecutor, *, max_replans: int = 1):
    return executor.execute(
        build_m15_plan_candidates(REPO_ROOT),
        _stale_snapshot(),
        probe_plan=_probe_plan(),
        observations=(ProbeObservation("high-risk", "fuseki-high-risk"),),
        updated_version="task-1",
        observation_source="task-1/probe/high-risk",
        policy=ReplanPolicy(max_replans=max_replans),
        goal_id="m15-adaptive-test",
    )


def test_adaptive_executor_replans_and_reuses_probe_without_duplicate_call() -> None:
    executor, clients = _executor()

    run = _run(executor)

    assert run.success
    assert run.initial_selection.selected_plan_id == "m15-parallel-hash"
    assert run.selection_after_probe is not None
    assert run.selection_after_probe.selected_plan_id == "m15-risk-first-bind"
    assert run.selected_plan_id == "m15-risk-first-bind"
    assert run.replan_count == 1
    assert run.reused_node_ids == ("align-risk", "exchange-risk", "high-risk")
    assert any("latency_factor=2000" in reason for reason in run.replan_reasons)
    assert clients["fuseki"].artifact_ids == ["m15-split-fuseki"]
    assert clients["neo4j"].artifact_ids == ["m15-split-neo4j-bound"]
    assert run.final_run is not None
    assert run.total_remote_calls == 2
    assert run.elapsed_ms >= run.probe_run.elapsed_ms
    assert len(run.final_run.final_rows) == 1


def test_no_replan_baseline_keeps_initial_plan_but_still_reuses_probe() -> None:
    executor, clients = _executor()

    run = _run(executor, max_replans=0)

    assert run.success
    assert run.selection_after_probe is not None
    assert run.selection_after_probe.selected_plan_id == "m15-risk-first-bind"
    assert run.selected_plan_id == "m15-parallel-hash"
    assert run.replan_count == 0
    assert clients["fuseki"].artifact_ids == ["m15-split-fuseki"]
    assert clients["neo4j"].artifact_ids == ["m15-split-neo4j"]
    assert run.final_run is not None
    assert run.total_remote_calls == 2


def test_failed_probe_is_evidence_and_does_not_execute_a_fallback_plan() -> None:
    executor, clients = _executor(fail_fuseki=True)

    run = _run(executor)

    assert not run.success
    assert run.final_run is None
    assert run.replan_count == 0
    assert clients["fuseki"].artifact_ids == ["m15-split-fuseki"]
    assert clients["neo4j"].artifact_ids == []
    assert "no continuation" in str(run.error)


def test_probe_must_be_exact_common_prefix_before_any_remote_call() -> None:
    executor, clients = _executor()
    probe = _probe_plan()
    changed = replace(
        probe.nodes[1],
        parameters={**dict(probe.nodes[1].parameters), "on_missing": "drop"},
    )
    invalid_probe = replace(probe, nodes=(probe.nodes[0], changed, probe.nodes[2]))

    with pytest.raises(AdaptiveExecutionError, match="not common"):
        executor.execute(
            build_m15_plan_candidates(REPO_ROOT),
            _stale_snapshot(),
            probe_plan=invalid_probe,
            observations=(ProbeObservation("high-risk", "fuseki-high-risk"),),
            updated_version="task-1",
            observation_source="task-1/probe/high-risk",
        )

    assert clients["fuseki"].artifact_ids == []
    assert clients["neo4j"].artifact_ids == []


def test_every_remote_probe_node_must_be_declared_before_any_call() -> None:
    executor, clients = _executor()
    candidates = build_m15_plan_candidates(REPO_ROOT)
    nodes = {node.node_id: node for node in candidates[0].plan.nodes}
    two_remote_probe = FederatedExecutionPlan(
        plan_id="m15-two-remote-probe",
        nodes=(nodes["recent-transfers"], nodes["high-risk"]),
        roots=("recent-transfers", "high-risk"),
        max_remote_calls=2,
        max_parallelism=2,
    )

    with pytest.raises(AdaptiveExecutionError, match="every remote probe node"):
        executor.execute(
            candidates,
            _stale_snapshot(),
            probe_plan=two_remote_probe,
            observations=(ProbeObservation("high-risk", "fuseki-high-risk"),),
            updated_version="task-1",
            observation_source="task-1/probe/high-risk",
        )

    assert clients["fuseki"].artifact_ids == []
    assert clients["neo4j"].artifact_ids == []


def test_plan_snapshot_memory_survives_process_boundary(tmp_path: Path) -> None:
    path = tmp_path / "m15-memory.jsonl"
    first = PlanSnapshotMemory(JsonlMemoryStore(path))
    first.put(_stale_snapshot(), source="task-0/profile")
    executor, _ = _executor()
    adaptive = _run(executor)
    first.put(adaptive.snapshot_after, source="task-1/probe")

    reopened = PlanSnapshotMemory(JsonlMemoryStore(path))

    assert reopened.get("m15-adaptive", "task-0") == _stale_snapshot()
    assert reopened.latest("m15-adaptive") == adaptive.snapshot_after
    with pytest.raises(AdaptiveExecutionError, match="already exists"):
        reopened.put(adaptive.snapshot_after, source="duplicate")


def test_snapshot_update_rejects_duplicate_observation_keys() -> None:
    snapshot = _stale_snapshot()
    duplicate = snapshot.estimates[0]

    with pytest.raises(FederatedPlanningError, match="must be unique"):
        snapshot.with_estimates(
            (duplicate, duplicate),
            version="task-1",
        )


@pytest.mark.parametrize("invalid", [True, 1.5])
def test_remote_estimate_rejects_non_integer_row_counts(invalid: object) -> None:
    payload = _stale_snapshot().estimates[0].to_dict()
    payload["row_count"] = invalid

    with pytest.raises(FederatedPlanningError, match="nonnegative integer"):
        RemoteEstimate.from_dict(payload)
