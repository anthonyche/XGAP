"""Controlled M15 sanity check for executable plan choice and cost reversal."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.experiments.m15_live_federated import build_m15_plan_candidates
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import (
    FederatedPlanSelector,
    FederatedScheduler,
    PlanObservationSnapshot,
    RemoteEstimate,
)
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


@dataclass
class FixtureClient:
    backend_id: str
    rows: list[dict[str, object]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        rows = self.rows
        bindings = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(bindings, list):
            rows = [
                row
                for row in rows
                if str(row.get("company_id", "")).removeprefix("neo:") in bindings
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=1.0,
            metadata={"transport": "offline-fixture"},
        )


def snapshot(snapshot_id: str, *, bound_latency_ms: float) -> PlanObservationSnapshot:
    return PlanObservationSnapshot(
        snapshot_id=snapshot_id,
        version="controlled-v1",
        estimates=(
            RemoteEstimate(
                "neo4j-recent-transfers-full",
                "neo4j",
                50.0,
                10_000,
                100.0,
                "controlled/neo4j-full",
                "controlled-v1",
            ),
            RemoteEstimate(
                "neo4j-recent-transfers-bound",
                "neo4j",
                bound_latency_ms,
                10,
                100.0,
                "controlled/neo4j-bound",
                "controlled-v1",
            ),
            RemoteEstimate(
                "fuseki-high-risk",
                "fuseki",
                10.0,
                10,
                30.0,
                "controlled/fuseki-risk",
                "controlled-v1",
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
plugins = BackendPluginRegistry()
plugins.register(
    NativeBackendPlugin("neo4j", FixtureClient("neo4j", source_rows["neo4j"]))
)
plugins.register(
    NativeBackendPlugin("fuseki", FixtureClient("fuseki", source_rows["fuseki"]))
)
candidates = build_m15_plan_candidates(ROOT)
scheduler = FederatedScheduler(BackendInvokeTool(plugins))
executions = {
    candidate.plan.plan_id: scheduler.execute(candidate.plan).to_dict()
    for candidate in candidates
}
answers = {json.dumps(run["final_rows"], sort_keys=True) for run in executions.values()}
selector = FederatedPlanSelector()
transfer_sensitive = selector.select(
    candidates,
    snapshot("controlled-transfer-sensitive", bound_latency_ms=40.0),
)
slow_bind = selector.select(
    candidates,
    snapshot("controlled-slow-bind", bound_latency_ms=2_000.0),
)

payload = {
    "schema_version": "m15-controlled-plan-selection-v1",
    "evidence_class": "controlled_model_sanity_check",
    "paper_result": False,
    "same_exact_answer": len(answers) == 1,
    "semantic_equivalence_key": candidates[0].semantic_equivalence_key,
    "executions": {
        plan_id: {
            "success": run["success"],
            "final_rows": run["final_rows"],
            "total_remote_calls": run["total_remote_calls"],
            "total_bytes_moved": run["total_bytes_moved"],
        }
        for plan_id, run in sorted(executions.items())
    },
    "selections": {
        "transfer_sensitive": transfer_sensitive.to_dict(),
        "slow_bind": slow_bind.to_dict(),
    },
    "selection_flipped": (
        transfer_sensitive.selected_plan_id != slow_bind.selected_plan_id
    ),
}
print(json.dumps(payload, indent=2, sort_keys=True))
