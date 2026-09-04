"""Offline cross-platform vertical slice with deliberately split facts."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.infrastructure.runtime import BackendStatus, ExecutionReport
from xgap.runtime import FederatedExecutionPlan, FederatedScheduler, RuntimeNode, RuntimeNodeKind
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


@dataclass
class FixtureClient:
    backend_id: str
    rows: list[dict[str, object]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "fixture ready")

    def execute(self, artifact) -> ExecutionReport:
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=self.rows,
            elapsed_ms=1.0,
        )


plugins = BackendPluginRegistry()
plugins.register(
    NativeBackendPlugin(
        "neo4j",
        FixtureClient(
            "neo4j",
            [
                {"person": "Alice Smith", "company_id": "neo:C1", "amount": 1200},
                {"person": "Alice Smith", "company_id": "neo:C2", "amount": 900},
            ],
        ),
    )
)
plugins.register(
    NativeBackendPlugin(
        "fuseki",
        FixtureClient("fuseki", [{"company_id": "rdf:C1", "risk": "high"}]),
    )
)

plan = FederatedExecutionPlan(
    plan_id="offline-split-risk",
    nodes=(
        RuntimeNode(
            "transfers",
            RuntimeNodeKind.REMOTE_QUERY,
            parameters={
                "backend_id": "neo4j",
                "artifact": {"artifact_id": "transfers", "language": "cypher", "text": "MATCH ..."},
            },
        ),
        RuntimeNode(
            "risk",
            RuntimeNodeKind.REMOTE_QUERY,
            parameters={
                "backend_id": "fuseki",
                "artifact": {"artifact_id": "risk", "language": "sparql", "text": "SELECT ..."},
            },
        ),
        RuntimeNode(
            "align-transfers",
            RuntimeNodeKind.ALIGN,
            inputs=("transfers",),
            parameters={"field": "company_id", "output_field": "company", "mapping": {"neo:C1": "C1", "neo:C2": "C2"}},
        ),
        RuntimeNode(
            "align-risk",
            RuntimeNodeKind.ALIGN,
            inputs=("risk",),
            parameters={"field": "company_id", "output_field": "company", "mapping": {"rdf:C1": "C1"}},
        ),
        RuntimeNode("move-transfers", RuntimeNodeKind.EXCHANGE, inputs=("align-transfers",)),
        RuntimeNode("move-risk", RuntimeNodeKind.EXCHANGE, inputs=("align-risk",)),
        RuntimeNode(
            "answer",
            RuntimeNodeKind.COORDINATOR_JOIN,
            inputs=("move-transfers", "move-risk"),
            parameters={"left_on": "company", "right_on": "company"},
        ),
    ),
    roots=("answer",),
    max_remote_calls=2,
    max_parallelism=2,
)

result = FederatedScheduler(BackendInvokeTool(plugins)).execute(plan)
print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
