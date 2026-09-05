from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from xgap.experiments.m15_live_method_matrix import (
    main,
    run_m15_live_method_matrix,
)
from xgap.experiments.m15_method_policy import M15Method
from xgap.experiments.m15_workload import M15WorkloadSpec, generate_m15_workload_bundle
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _LiveClient:
    backend_id: str
    rows: list[dict[str, object]]
    fail_artifact_id: str | None = None
    health_ok: bool = True
    artifact_calls: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, self.health_ok, "test client")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_calls.append(artifact.artifact_id)
        if artifact.artifact_id == self.fail_artifact_id:
            return ExecutionReport(
                self.backend_id,
                artifact.artifact_id,
                artifact.language,
                False,
                error="controlled live matrix failure",
            )
        rows = [dict(row) for row in self.rows]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                row
                for row in rows
                if str(row["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            self.backend_id,
            artifact.artifact_id,
            artifact.language,
            True,
            rows=rows,
            elapsed_ms=2.0,
            metadata={"transport": "offline-live-matrix"},
        )


@dataclass
class _Neo4jLiveClient(_LiveClient):
    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        return self.execute(artifact)


def _bundle(tmp_path: Path):
    return generate_m15_workload_bundle(
        M15WorkloadSpec(
            workload_id="live-matrix-test",
            seed="live-matrix-test-v1",
            company_count=20,
            transfer_count=100,
            high_risk_company_count=4,
            hot_company_count=3,
            hot_transfer_count=80,
            high_risk_placement="cold_first",
            max_bindings=20,
        ),
        tmp_path / "bundle",
    )


def _clients(bundle, *, fail_neo4j: str | None = None):
    return {
        "neo4j": _Neo4jLiveClient(
            "neo4j",
            bundle.expected_source_rows["neo4j"],
            fail_artifact_id=fail_neo4j,
        ),
        "fuseki": _LiveClient(
            "fuseki",
            bundle.expected_source_rows["fuseki"],
        ),
    }


def test_live_matrix_runs_six_distinct_methods_with_exact_accounting(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    record = run_m15_live_method_matrix(
        workload_bundle=bundle,
        output_root=tmp_path,
        run_id="live-matrix-run",
        repo_root=REPO_ROOT,
        clients=_clients(bundle),
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert manifest["validation"]["passed"] is True
    assert set(manifest["methods"]) == {method.value for method in M15Method}
    assert manifest["calibration"]["attempted_calls"] == 3
    assert manifest["calibration_accounting"]["included_in_method_metrics"] is False
    assert manifest["calibration_accounting"]["seed_memory_writes"] == 3
    assert manifest["order_policy"] == "fixed_engineering_gate_not_counterbalanced"
    assert manifest["cache_state"] == "shared_unknown_not_reset_between_methods"
    assert manifest["paper_result"] is False
    assert invocations["total_tool_invocations"] == 18
    assert len(invocations["events_by_phase"]["calibration"]) == 3

    methods = manifest["methods"]
    assert methods[M15Method.STATIC_PARALLEL_HASH.value]["total_backend_calls"] == 2
    assert methods[M15Method.STATIC_RISK_FIRST_BIND.value]["total_backend_calls"] == 2
    assert methods[M15Method.NO_MEMORY.value]["total_backend_calls"] == 5
    assert methods[M15Method.NO_PROFILE_PROBE.value]["total_backend_calls"] == 2
    assert methods[M15Method.NO_REPLAN.value]["total_backend_calls"] == 2
    assert methods[M15Method.FULL_AGENT.value]["total_backend_calls"] == 2
    assert methods[M15Method.NO_REPLAN.value]["replan_count"] == 0
    assert methods[M15Method.FULL_AGENT.value]["replan_count"] in {0, 1}
    assert all(value["exact_answer"] is True for value in methods.values())


def test_live_matrix_stops_after_partial_calibration_failure(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    failed_artifact = f"m15-f0-{bundle.spec.workload_id}-neo4j-bound"
    record = run_m15_live_method_matrix(
        workload_bundle=bundle,
        output_root=tmp_path,
        run_id="failed-live-matrix",
        repo_root=REPO_ROOT,
        clients=_clients(bundle, fail_neo4j=failed_artifact),
    )

    assert not record.success
    assert "controlled live matrix failure" in str(record.error)
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert manifest["methods"] == {}
    assert manifest["calibration"]["attempted_calls"] == 2
    assert invocations["total_tool_invocations"] == 2
    assert invocations["automatic_retries"] == 0
    assert not (record.run_root / "methods").exists()


def test_live_matrix_rejects_an_incomplete_client_set_before_backend_call(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)
    clients.pop("fuseki")

    record = run_m15_live_method_matrix(
        workload_bundle=bundle,
        output_root=tmp_path,
        run_id="missing-client-matrix",
        repo_root=REPO_ROOT,
        clients=clients,
    )

    assert not record.success
    assert "requires exactly neo4j and fuseki" in str(record.error)
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert invocations["total_tool_invocations"] == 0


def test_live_matrix_refuses_overwrite(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    run_m15_live_method_matrix(
        workload_bundle=bundle,
        output_root=tmp_path,
        run_id="immutable-live-matrix",
        repo_root=REPO_ROOT,
        clients=_clients(bundle),
    )

    with pytest.raises(FileExistsError):
        run_m15_live_method_matrix(
            workload_bundle=bundle,
            output_root=tmp_path,
            run_id="immutable-live-matrix",
            repo_root=REPO_ROOT,
            clients=_clients(bundle),
        )


def test_live_matrix_cli_is_explicitly_gated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_RUN_M15_LIVE_METHOD_MATRIX", raising=False)

    assert main(["--workload-bundle", "unused"]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"


def test_live_matrix_rejects_custom_order_without_campaign_binding(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    order = tuple(reversed(tuple(M15Method)))

    with pytest.raises(ValueError, match="requires a campaign binding"):
        run_m15_live_method_matrix(
            workload_bundle=bundle,
            output_root=tmp_path,
            run_id="unbound-custom-order",
            repo_root=REPO_ROOT,
            clients=_clients(bundle),
            method_order=order,
        )

    assert not (tmp_path / "unbound-custom-order").exists()
