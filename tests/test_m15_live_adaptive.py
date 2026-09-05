from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from xgap.experiments.m15_live_adaptive import (
    build_m15_observation_requests,
    build_m15_probe_plan,
    main,
    run_m15_live_adaptive,
)
from xgap.experiments.m15_workload import M15WorkloadSpec, generate_m15_workload_bundle
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import RuntimeNodeKind


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeClient:
    backend_id: str
    rows: list[dict[str, object]]
    fail_artifact_id: str | None = None
    artifact_calls: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_calls.append(artifact.artifact_id)
        if artifact.artifact_id == self.fail_artifact_id:
            return ExecutionReport(
                self.backend_id,
                artifact.artifact_id,
                artifact.language,
                False,
                error="controlled observation failure",
            )
        rows = self.rows
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            rows = [
                row
                for row in rows
                if str(row.get("company_id", "")).rsplit(":", 1)[-1] in company_ids
            ]
        return ExecutionReport(
            self.backend_id,
            artifact.artifact_id,
            artifact.language,
            True,
            rows=[dict(row) for row in rows],
            elapsed_ms=2.0,
            metadata={"transport": "offline-fixture"},
        )


@dataclass
class ProfileFakeClient(FakeClient):
    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        report = self.execute(artifact)
        return ExecutionReport(
            backend_id=report.backend_id,
            artifact_id=report.artifact_id,
            language=report.language,
            success=report.success,
            rows=report.rows,
            elapsed_ms=report.elapsed_ms,
            error=report.error,
            metadata={**report.metadata, "observation": "profile"},
        )


@dataclass
class FailSecondFusekiClient(FakeClient):
    execute_count: int = 0

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.execute_count += 1
        if self.execute_count == 2:
            self.artifact_calls.append(artifact.artifact_id)
            return ExecutionReport(
                self.backend_id,
                artifact.artifact_id,
                artifact.language,
                False,
                error="controlled probe failure",
            )
        return super().execute(artifact)


@dataclass
class RaisingProfileClient(ProfileFakeClient):
    raise_artifact_id: str = ""

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        if artifact.artifact_id == self.raise_artifact_id:
            raise RuntimeError("controlled unexpected transport exception")
        return super().execute(artifact)


def _clients(
    *,
    fail_neo4j_artifact: str | None = None,
) -> dict[str, FakeClient]:
    return {
        "neo4j": ProfileFakeClient(
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
            fail_artifact_id=fail_neo4j_artifact,
        ),
        "fuseki": FakeClient(
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
        ),
    }


def test_live_adaptive_contract_uses_three_profiles_and_two_query_calls(
    tmp_path: Path,
) -> None:
    record = run_m15_live_adaptive(
        output_root=tmp_path,
        run_id="offline-live-adaptive",
        repo_root=REPO_ROOT,
        clients=_clients(),
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    adaptive = json.loads(
        (record.run_root / "adaptive_result.json").read_text(encoding="utf-8")
    )
    events = invocations["events"]
    assert [event["operation"] for event in events] == [
        "profile",
        "profile",
        "profile",
        "execute",
        "execute",
    ]
    assert [event["observation_mode"] for event in events[:3]] == [
        "backend_native",
        "backend_native",
        "wall_clock_execute",
    ]
    execute_events = events[3:]
    assert sum(event["backend_id"] == "neo4j" for event in execute_events) == 1
    assert sum(event["backend_id"] == "fuseki" for event in execute_events) == 1
    assert adaptive["success"] is True
    assert adaptive["total_remote_calls"] == 2
    assert adaptive["replan_count"] in {0, 1}
    assert manifest["validation"]["passed"] is True
    assert manifest["memory_before_reopened"] is True
    assert manifest["memory_after_reopened"] is True
    assert manifest["paper_result"] is False
    assert manifest["automatic_retries"] == 0
    assert len(
        (record.run_root / "plan_memory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == 2


def test_live_adaptive_consumes_verified_scaled_workload_bundle(
    tmp_path: Path,
) -> None:
    bundle = generate_m15_workload_bundle(
        M15WorkloadSpec(
            workload_id="adaptive-test",
            seed="adaptive-test-v1",
            company_count=12,
            transfer_count=40,
            high_risk_company_count=3,
            hot_company_count=2,
            hot_transfer_count=32,
            high_risk_placement="cold_first",
            max_bindings=12,
        ),
        tmp_path / "bundle",
    )
    clients = {
        "neo4j": ProfileFakeClient(
            "neo4j",
            bundle.expected_source_rows["neo4j"],
        ),
        "fuseki": FakeClient(
            "fuseki",
            bundle.expected_source_rows["fuseki"],
        ),
    }

    record = run_m15_live_adaptive(
        output_root=tmp_path,
        run_id="scaled-live-adaptive",
        repo_root=REPO_ROOT,
        clients=clients,
        workload_bundle=bundle,
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    adaptive = json.loads(record.adaptive_result_path.read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == "m15_f0:adaptive-test"
    assert manifest["evidence_class"] == (
        "deterministic_scaled_live_backend_development_gate"
    )
    assert manifest["workload_bundle"]["spec_sha256"] == bundle.manifest[
        "spec_sha256"
    ]
    assert manifest["validation"]["passed"] is True
    assert adaptive["final_run"]["final_rows"] == bundle.expected_rows
    assert adaptive["total_remote_calls"] == 2
    assert manifest["paper_result"] is False


def test_live_adaptive_preserves_partial_observation_failure_without_query(
    tmp_path: Path,
) -> None:
    record = run_m15_live_adaptive(
        output_root=tmp_path,
        run_id="failed-live-adaptive",
        repo_root=REPO_ROOT,
        clients=_clients(fail_neo4j_artifact="m15-split-neo4j-bound"),
    )

    assert not record.success
    assert record.adaptive_result_path is None
    collection = json.loads(
        (record.run_root / "observation_collection.json").read_text(encoding="utf-8")
    )
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert collection["attempted_calls"] == 2
    assert collection["automatic_retries"] == 0
    assert [event["operation"] for event in invocations["events"]] == [
        "profile",
        "profile",
    ]
    assert "controlled observation failure" in str(record.error)


def test_live_adaptive_records_unexpected_observation_exception_once(
    tmp_path: Path,
) -> None:
    clients = _clients()
    original = clients["neo4j"]
    clients["neo4j"] = RaisingProfileClient(
        original.backend_id,
        original.rows,
        raise_artifact_id="m15-split-neo4j-bound",
    )

    record = run_m15_live_adaptive(
        output_root=tmp_path,
        run_id="raised-live-observation",
        repo_root=REPO_ROOT,
        clients=clients,
    )

    assert not record.success
    collection = json.loads(
        (record.run_root / "observation_collection.json").read_text(encoding="utf-8")
    )
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert collection["attempted_calls"] == 2
    assert [event["operation"] for event in invocations["events"]] == [
        "profile",
        "profile",
    ]
    assert invocations["events"][-1]["status"] == "error"
    assert "controlled unexpected transport exception" in str(record.error)


def test_live_adaptive_probe_failure_has_no_fallback_or_duplicate_memory(
    tmp_path: Path,
) -> None:
    clients = _clients()
    original = clients["fuseki"]
    clients["fuseki"] = FailSecondFusekiClient(
        original.backend_id,
        original.rows,
    )

    record = run_m15_live_adaptive(
        output_root=tmp_path,
        run_id="failed-live-probe",
        repo_root=REPO_ROOT,
        clients=clients,
    )

    assert not record.success
    assert record.adaptive_result_path is not None
    assert "no continuation" in str(record.error)
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert [event["operation"] for event in invocations["events"]] == [
        "profile",
        "profile",
        "profile",
        "execute",
    ]
    assert invocations["events"][-1]["backend_id"] == "fuseki"
    assert invocations["events"][-1]["status"] == "error"
    assert len(
        (record.run_root / "plan_memory.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == 1


def test_live_adaptive_plan_contract_is_declared_and_common() -> None:
    requests = build_m15_observation_requests()
    probe = build_m15_probe_plan(REPO_ROOT)

    assert [request.observation_key for request in requests] == [
        "neo4j-recent-transfers-full",
        "neo4j-recent-transfers-bound",
        "fuseki-high-risk",
    ]
    assert [node.kind for node in probe.nodes] == [
        RuntimeNodeKind.REMOTE_QUERY,
        RuntimeNodeKind.ALIGN,
        RuntimeNodeKind.EXCHANGE,
    ]
    assert probe.max_remote_calls == 1


def test_live_adaptive_cli_is_fail_closed_without_gate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_RUN_M15_ADAPTIVE", raising=False)

    assert main([]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
