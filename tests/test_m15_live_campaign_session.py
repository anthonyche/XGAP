from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from xgap.experiments.m15_campaign import compile_m15_campaign_file
from xgap.experiments.m15_live_campaign_session import (
    LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION,
    main,
    run_m15_live_campaign_session,
)
from xgap.experiments.m15_workload import (
    M15WorkloadSpec,
    generate_m15_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_CONFIG = REPO_ROOT / "experiments/configs/m15_f2_campaign_dev.json"
SELECTIVE_CONFIG = REPO_ROOT / "experiments/configs/m15_f0_selective.json"


@dataclass
class _LiveClient:
    backend_id: str
    rows: list[dict[str, object]]
    health_calls: int = 0
    artifact_calls: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        self.health_calls += 1
        return BackendStatus(self.backend_id, True, "test client")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_calls.append(artifact.artifact_id)
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
            metadata={"transport": "offline-live-campaign-session"},
        )


@dataclass
class _Neo4jLiveClient(_LiveClient):
    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        return self.execute(artifact)


def _bundle(tmp_path: Path):
    return generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(SELECTIVE_CONFIG),
        tmp_path / "bundle",
    )


def _clients(bundle):
    return {
        "neo4j": _Neo4jLiveClient(
            "neo4j", bundle.expected_source_rows["neo4j"]
        ),
        "fuseki": _LiveClient(
            "fuseki", bundle.expected_source_rows["fuseki"]
        ),
    }


def _plan_and_session(config: Path = CAMPAIGN_CONFIG):
    plan = compile_m15_campaign_file(config, repo_root=REPO_ROOT).to_dict()
    session = next(
        item for item in plan["sessions"] if item["workload_label"] == "selective"
    )
    return plan, session


def test_live_campaign_session_executes_compiled_order_and_binds_hashes(
    tmp_path: Path,
) -> None:
    plan, session = _plan_and_session()
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)

    record = run_m15_live_campaign_session(
        campaign_config=CAMPAIGN_CONFIG,
        session_id=session["session_id"],
        expected_campaign_spec_sha256=plan["campaign_spec_sha256"],
        expected_schedule_sha256=plan["schedule_sha256"],
        workload_bundle=bundle,
        output_root=tmp_path,
        run_id="campaign-session-run",
        repo_root=REPO_ROOT,
        clients=clients,
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    matrix_root = record.run_root / "method-matrix-run"
    matrix = json.loads(
        (matrix_root / "run_manifest.json").read_text(encoding="utf-8")
    )
    invocations = json.loads(
        (matrix_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == LIVE_CAMPAIGN_SESSION_SCHEMA_VERSION
    assert manifest["validation"]["passed"] is True
    assert manifest["campaign_spec_sha256"] == plan["campaign_spec_sha256"]
    assert manifest["schedule_sha256"] == plan["schedule_sha256"]
    assert manifest["method_order"] == session["method_order"]
    assert manifest["paper_result"] is False
    assert manifest["claim_boundary"]["multi_task_memory_stream"] is False
    assert matrix["method_order"] == session["method_order"]
    assert matrix["order_policy"] == "williams_campaign_sequence"
    assert matrix["campaign_binding"]["session_id"] == session["session_id"]
    assert matrix["campaign_binding"]["schedule_sha256"] == plan["schedule_sha256"]
    expected_streams = {
        stream["method"]: stream for stream in session["method_streams"]
    }
    assert matrix["campaign_binding"]["method_task_ids"] == {
        method: stream["measured_run_ids"][0]
        for method, stream in expected_streams.items()
    }
    assert matrix["execution_namespaces"]["logical_memory_namespaces"] == {
        method: stream["memory_namespace"]
        for method, stream in expected_streams.items()
    }
    assert all(
        result["task_id"]
        == expected_streams[method]["measured_run_ids"][0]
        for method, result in matrix["methods"].items()
    )
    assert matrix["evidence_class"] == "live_backend_campaign_session_engineering_gate"
    assert invocations["total_tool_invocations"] == 18
    assert invocations["automatic_retries"] == 0
    assert all(value["exact_answer"] for value in matrix["methods"].values())
    assert clients["neo4j"].health_calls == 1
    assert clients["fuseki"].health_calls == 1


@pytest.mark.parametrize(
    ("hash_field", "replacement", "message"),
    [
        (
            "campaign_spec_sha256",
            "0" * 64,
            "campaign spec hash disagrees",
        ),
        (
            "schedule_sha256",
            "1" * 64,
            "campaign schedule hash disagrees",
        ),
    ],
)
def test_live_campaign_session_rejects_hash_drift_before_backend_call(
    tmp_path: Path,
    hash_field: str,
    replacement: str,
    message: str,
) -> None:
    plan, session = _plan_and_session()
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)
    values = {
        "campaign_spec_sha256": plan["campaign_spec_sha256"],
        "schedule_sha256": plan["schedule_sha256"],
    }
    values[hash_field] = replacement

    with pytest.raises(ValueError, match=message):
        run_m15_live_campaign_session(
            campaign_config=CAMPAIGN_CONFIG,
            session_id=session["session_id"],
            expected_campaign_spec_sha256=values["campaign_spec_sha256"],
            expected_schedule_sha256=values["schedule_sha256"],
            workload_bundle=bundle,
            output_root=tmp_path / "runs",
            run_id="hash-drift",
            repo_root=REPO_ROOT,
            clients=clients,
        )

    assert clients["neo4j"].health_calls == 0
    assert clients["fuseki"].health_calls == 0
    assert not (tmp_path / "runs" / "hash-drift").exists()


def test_live_campaign_session_rejects_multi_query_placeholder(
    tmp_path: Path,
) -> None:
    payload = json.loads(CAMPAIGN_CONFIG.read_text(encoding="utf-8"))
    payload["workloads"][0]["query_ids"].append("unsupported-second-query")
    config = tmp_path / "multi-query-campaign.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    plan, session = _plan_and_session(config)
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)

    with pytest.raises(ValueError, match="supports exactly one frozen query"):
        run_m15_live_campaign_session(
            campaign_config=config,
            session_id=session["session_id"],
            expected_campaign_spec_sha256=plan["campaign_spec_sha256"],
            expected_schedule_sha256=plan["schedule_sha256"],
            workload_bundle=bundle,
            output_root=tmp_path / "runs",
            run_id="multi-query-refused",
            repo_root=REPO_ROOT,
            clients=clients,
        )

    assert clients["neo4j"].health_calls == 0
    assert clients["fuseki"].health_calls == 0


def test_live_campaign_session_rejects_unimplemented_warmup_phase(
    tmp_path: Path,
) -> None:
    payload = json.loads(CAMPAIGN_CONFIG.read_text(encoding="utf-8"))
    payload["protocol"]["warmup_runs_per_method"] = 1
    config = tmp_path / "warmup-campaign.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    plan, session = _plan_and_session(config)
    bundle = _bundle(tmp_path)
    clients = _clients(bundle)

    with pytest.raises(ValueError, match="requires zero warmup runs"):
        run_m15_live_campaign_session(
            campaign_config=config,
            session_id=session["session_id"],
            expected_campaign_spec_sha256=plan["campaign_spec_sha256"],
            expected_schedule_sha256=plan["schedule_sha256"],
            workload_bundle=bundle,
            output_root=tmp_path / "runs",
            run_id="warmup-refused",
            repo_root=REPO_ROOT,
            clients=clients,
        )

    assert clients["neo4j"].health_calls == 0
    assert clients["fuseki"].health_calls == 0


def test_live_campaign_session_cli_is_explicitly_gated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_RUN_M15_LIVE_CAMPAIGN_SESSION", raising=False)

    assert main(
        [
            "--campaign-config",
            "unused",
            "--session-id",
            "unused",
            "--expected-campaign-spec-sha256",
            "0" * 64,
            "--expected-schedule-sha256",
            "1" * 64,
            "--workload-bundle",
            "unused",
        ]
    ) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
