"""Controlled cross-task memory and within-query replanning demonstration."""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.agent import JsonlMemoryStore
from xgap.experiments.m15_live_federated import build_m15_plan_candidates
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import (
    AdaptiveFederatedExecutor,
    FederatedExecutionPlan,
    FederatedScheduler,
    PlanObservationSnapshot,
    PlanSnapshotMemory,
    ProbeObservation,
    RemoteEstimate,
)
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


@dataclass
class FixtureClient:
    backend_id: str
    rows: list[dict[str, object]]
    artifact_ids: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_ids.append(artifact.artifact_id)
        rows = self.rows
        bindings = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(bindings, list):
            rows = [
                row
                for row in rows
                if str(row.get("company_id", "")).removeprefix("neo:") in bindings
            ]
        return ExecutionReport(
            self.backend_id,
            artifact.artifact_id,
            artifact.language,
            True,
            rows=rows,
            elapsed_ms=1.0,
            metadata={"transport": "offline-fixture"},
        )


def stale_snapshot() -> PlanObservationSnapshot:
    return PlanObservationSnapshot(
        snapshot_id="m15-adaptive-demo",
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


source_rows = json.loads(
    (ROOT / "examples/m15_split_financial_risk/expected_source_results.json").read_text(
        encoding="utf-8"
    )
)
expected_answer = json.loads(
    (ROOT / "examples/m15_split_financial_risk/expected_result.json").read_text(
        encoding="utf-8"
    )
)
clients = {
    "neo4j": FixtureClient("neo4j", source_rows["neo4j"]),
    "fuseki": FixtureClient("fuseki", source_rows["fuseki"]),
}
plugins = BackendPluginRegistry()
for backend_id, client in clients.items():
    plugins.register(NativeBackendPlugin(backend_id, client))
candidates = build_m15_plan_candidates(ROOT)
common = {node.node_id: node for node in candidates[0].plan.nodes}
probe = FederatedExecutionPlan(
    plan_id="m15-risk-probe-prefix",
    nodes=(common["high-risk"], common["align-risk"], common["exchange-risk"]),
    roots=("exchange-risk",),
    max_remote_calls=1,
    max_parallelism=1,
)

with tempfile.TemporaryDirectory(prefix="xgap-m15-adaptive-") as directory:
    memory_path = Path(directory) / "memory.jsonl"
    memory = PlanSnapshotMemory(JsonlMemoryStore(memory_path))
    before = stale_snapshot()
    memory.put(before, source="task-0/profile")
    run = AdaptiveFederatedExecutor(
        FederatedScheduler(BackendInvokeTool(plugins))
    ).execute(
        candidates,
        before,
        probe_plan=probe,
        observations=(ProbeObservation("high-risk", "fuseki-high-risk"),),
        updated_version="task-1",
        observation_source="task-1/probe/high-risk",
        goal_id="m15-adaptive-demo",
    )
    memory.put(run.snapshot_after, source="task-1/probe")
    reopened = PlanSnapshotMemory(JsonlMemoryStore(memory_path))
    persisted_version = reopened.latest("m15-adaptive-demo").version

final = run.final_run
payload = {
    "schema_version": "m15-controlled-adaptive-replanning-v1",
    "evidence_class": "controlled_model_sanity_check",
    "paper_result": False,
    "success": run.success,
    "initial_plan_id": run.initial_selection.selected_plan_id,
    "post_probe_plan_id": (
        run.selection_after_probe.selected_plan_id
        if run.selection_after_probe is not None
        else None
    ),
    "executed_plan_id": run.selected_plan_id,
    "replan_count": run.replan_count,
    "replan_reasons": list(run.replan_reasons),
    "reused_node_ids": list(run.reused_node_ids),
    "backend_artifact_calls": {
        backend_id: client.artifact_ids for backend_id, client in clients.items()
    },
    "no_duplicate_probe_call": clients["fuseki"].artifact_ids
    == ["m15-split-fuseki"],
    "total_remote_calls": run.total_remote_calls,
    "adaptive_elapsed_ms": run.elapsed_ms,
    "exact_answer": (
        [dict(row) for row in final.final_rows] == expected_answer
        if final is not None
        else False
    ),
    "persisted_snapshot_version_after_reopen": persisted_version,
}
print(json.dumps(payload, indent=2, sort_keys=True))
