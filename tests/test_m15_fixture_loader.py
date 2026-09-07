from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.experiments.m15_fixture_loader import (
    BackendLoadReport,
    FusekiGraphStoreFixtureLoader,
    Neo4jCypherFixtureLoader,
    load_m15_split_fixture,
    main,
    split_cypher_statements,
)
from xgap.experiments.m15_workload import M15WorkloadSpec, generate_m15_workload_bundle
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SOURCES = json.loads(
    (
        REPO_ROOT
        / "examples"
        / "m15_split_financial_risk"
        / "expected_source_results.json"
    ).read_text(encoding="utf-8")
)


@dataclass
class FakeClient:
    backend_id: str
    rows: list[dict[str, object]]
    health_calls: int = 0
    execute_calls: int = 0

    def healthcheck(self) -> BackendStatus:
        self.health_calls += 1
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact) -> ExecutionReport:
        self.execute_calls += 1
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=self.rows,
        )


@dataclass
class FakeLoader:
    backend_id: str
    success: bool = True
    calls: int = 0

    def load(self, path: Path) -> BackendLoadReport:
        self.calls += 1
        return BackendLoadReport(
            backend_id=self.backend_id,
            success=self.success,
            operations_attempted=1,
            bytes_sent=path.stat().st_size,
            elapsed_ms=1.0,
            error=None if self.success else "injected load failure",
            metadata={"strategy": "fake"},
        )


def _components(*, fuseki_load_success: bool = True):
    clients = {
        backend_id: FakeClient(backend_id, rows)
        for backend_id, rows in EXPECTED_SOURCES.items()
    }
    loaders = {
        "neo4j": FakeLoader("neo4j"),
        "fuseki": FakeLoader("fuseki", success=fuseki_load_success),
    }
    return clients, loaders


def test_split_cypher_preserves_quoted_and_commented_semicolons() -> None:
    statements = split_cypher_statements(
        'RETURN "a;b" AS value; // comment; retained\nRETURN `x;y`;'
    )

    assert statements == (
        'RETURN "a;b" AS value',
        "// comment; retained\nRETURN `x;y`",
    )


def test_neo4j_loader_stops_at_first_failure_without_retry(tmp_path: Path) -> None:
    path = tmp_path / "load.cypher"
    path.write_text("RETURN 1; RETURN 2; RETURN 3;", encoding="utf-8")

    class FailingClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def healthcheck(self) -> BackendStatus:
            return BackendStatus("neo4j", True, "ready")

        def execute(self, artifact) -> ExecutionReport:
            self.calls.append(artifact.artifact_id)
            succeeds = artifact.artifact_id.endswith("001")
            return ExecutionReport(
                backend_id="neo4j",
                artifact_id=artifact.artifact_id,
                language="cypher",
                success=succeeds,
                error=None if succeeds else "injected",
            )

    client = FailingClient()
    report = Neo4jCypherFixtureLoader(client).load(path)

    assert not report.success
    assert report.operations_attempted == 2
    assert report.metadata["failed_statement_index"] == 2
    assert report.metadata["failed_statement_kind"] == "RETURN"
    assert report.metadata["failed_statement_bytes"] == len(b"RETURN 2")
    assert len(report.metadata["failed_statement_sha256"]) == 64
    assert client.calls == ["m15-load-neo4j-001", "m15-load-neo4j-002"]


def test_neo4j_loader_records_raised_adapter_failure(tmp_path: Path) -> None:
    path = tmp_path / "load.cypher"
    path.write_text("RETURN 1; RETURN 2;", encoding="utf-8")

    class RaisingClient:
        def healthcheck(self) -> BackendStatus:
            return BackendStatus("neo4j", True, "ready")

        def execute(self, artifact) -> ExecutionReport:
            raise RuntimeError(f"transport broke at {artifact.artifact_id}")

    report = Neo4jCypherFixtureLoader(RaisingClient()).load(path)

    assert not report.success
    assert report.operations_attempted == 1
    assert "m15-load-neo4j-001" in str(report.error)


def test_fuseki_loader_uses_append_post_without_persisting_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "fixture.ttl"
    data.write_text("<urn:s> <urn:p> <urn:o> .\n", encoding="utf-8")
    descriptor = BackendDescriptor.from_yaml(
        REPO_ROOT / "descriptors" / "backends" / "fuseki.yaml"
    )
    captured: dict[str, object] = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("FUSEKI_ADMIN_PASSWORD", "do-not-persist")

    report = FusekiGraphStoreFixtureLoader(descriptor).load(data)

    request = captured["request"]
    assert isinstance(request, urllib.request.Request)
    assert request.get_method() == "POST"
    assert request.data == data.read_bytes()
    assert report.success
    assert report.metadata["strategy"] == "graph_store_post"
    assert "do-not-persist" not in json.dumps(report.to_dict())


def test_fixture_loader_writes_exact_success_evidence(tmp_path: Path) -> None:
    clients, loaders = _components()
    record = load_m15_split_fixture(
        output_root=tmp_path,
        run_id="offline-fixture-load",
        repo_root=REPO_ROOT,
        clients=clients,
        loaders=loaders,
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    verification = json.loads(
        (record.run_root / "verification.json").read_text(encoding="utf-8")
    )
    assert manifest["automatic_retries"] == 0
    assert manifest["credentials_persisted"] is False
    assert manifest["mutation_scope"] == "namespaced_idempotent_append"
    assert manifest["validation"]["passed"] is True
    assert verification["validation"]["passed"] is True
    assert loaders["neo4j"].calls == 1
    assert loaders["fuseki"].calls == 1
    assert clients["neo4j"].health_calls == 2
    assert clients["fuseki"].health_calls == 2
    assert clients["neo4j"].execute_calls == 1
    assert clients["fuseki"].execute_calls == 1


def test_fixture_loader_consumes_verified_scaled_bundle_without_static_paths(
    tmp_path: Path,
) -> None:
    spec = M15WorkloadSpec(
        workload_id="loader-test",
        seed="loader-test-v1",
        company_count=12,
        transfer_count=40,
        high_risk_company_count=3,
        hot_company_count=2,
        hot_transfer_count=32,
        high_risk_placement="cold_first",
        max_bindings=12,
    )
    bundle = generate_m15_workload_bundle(spec, tmp_path / "bundle")
    clients = {
        backend_id: FakeClient(backend_id, rows)
        for backend_id, rows in bundle.expected_source_rows.items()
    }
    loaders = {
        "neo4j": FakeLoader("neo4j"),
        "fuseki": FakeLoader("fuseki"),
    }

    record = load_m15_split_fixture(
        output_root=tmp_path,
        run_id="scaled-fixture-load",
        repo_root=REPO_ROOT,
        clients=clients,
        loaders=loaders,
        workload_bundle=bundle,
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == "m15_f0:loader-test"
    assert manifest["workload_bundle"]["spec_sha256"] == bundle.manifest[
        "spec_sha256"
    ]
    assert set(manifest["input_sha256"]) == {
        *(f"bundle:loader-test/{name}" for name in bundle.source_hashes),
        "bundle:loader-test/manifest.json",
    }
    assert loaders["neo4j"].calls == loaders["fuseki"].calls == 1


def test_fixture_loader_persists_partial_failure_without_retry(tmp_path: Path) -> None:
    clients, loaders = _components(fuseki_load_success=False)
    record = load_m15_split_fixture(
        output_root=tmp_path,
        run_id="failed-fixture-load",
        repo_root=REPO_ROOT,
        clients=clients,
        loaders=loaders,
    )

    assert not record.success
    reports = json.loads(
        (record.run_root / "load_reports.json").read_text(encoding="utf-8")
    )
    assert reports["neo4j"]["success"] is True
    assert reports["fuseki"]["success"] is False
    assert loaders["neo4j"].calls == 1
    assert loaders["fuseki"].calls == 1
    assert clients["neo4j"].execute_calls == 0
    assert clients["fuseki"].execute_calls == 0


def test_fixture_loader_rejects_non_exact_source_rows(tmp_path: Path) -> None:
    clients, loaders = _components()
    clients["fuseki"].rows = clients["fuseki"].rows[:1]

    record = load_m15_split_fixture(
        output_root=tmp_path,
        run_id="wrong-source-rows",
        repo_root=REPO_ROOT,
        clients=clients,
        loaders=loaders,
    )

    assert not record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation"]["checks"]["fuseki_exact_rows"] is False


def test_fixture_loader_refuses_overwrite_and_partial_injection(tmp_path: Path) -> None:
    clients, loaders = _components()
    load_m15_split_fixture(
        output_root=tmp_path,
        run_id="immutable-load",
        repo_root=REPO_ROOT,
        clients=clients,
        loaders=loaders,
    )
    with pytest.raises(FileExistsError):
        load_m15_split_fixture(
            output_root=tmp_path,
            run_id="immutable-load",
            repo_root=REPO_ROOT,
            clients=clients,
            loaders=loaders,
        )
    with pytest.raises(ValueError, match="supplied together"):
        load_m15_split_fixture(
            output_root=tmp_path,
            run_id="partial-components",
            repo_root=REPO_ROOT,
            clients=clients,
        )


def test_fixture_loader_cli_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_LOAD_M15_FIXTURE", raising=False)

    assert main([]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"


@pytest.mark.skipif(
    os.environ.get("XGAP_LOAD_M15_FIXTURE") != "1",
    reason="set XGAP_LOAD_M15_FIXTURE=1 only for dedicated M15 services",
)
def test_live_fixture_loader_gate(tmp_path: Path) -> None:
    record = load_m15_split_fixture(
        output_root=tmp_path,
        run_id="live-fixture-load-gate",
        repo_root=REPO_ROOT,
    )
    assert record.success, record.error
