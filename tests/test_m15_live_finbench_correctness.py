from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xgap.experiments import m15_finbench_federation as federation
from xgap.experiments import m15_live_finbench_correctness as live
from xgap.experiments.m15_finbench_workload import _templates
from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport


@dataclass
class Loader:
    backend_id: str

    def load(self, path: Path) -> BackendLoadReport:
        return BackendLoadReport(
            backend_id=self.backend_id,
            success=True,
            operations_attempted=1,
            bytes_sent=path.stat().st_size,
            elapsed_ms=1.0,
        )


@dataclass
class Client:
    backend_id: str

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact) -> ExecutionReport:
        rows = (
            [{"account_id": "A1"}]
            if self.backend_id == "fuseki"
            else [
                {"company_id": "C1", "account_id": "A1", "total_amount": 7.0}
            ]
        )
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=1.0,
        )


def test_live_gate_seals_plans_before_load_and_opens_oracle_after_execution(
    tmp_path: Path, monkeypatch
) -> None:
    workload_root = tmp_path / "workload"
    templates = workload_root / "templates"
    templates.mkdir(parents=True)
    for name, text in _templates().items():
        (templates / name).write_text(text, encoding="utf-8")
    partition_root = tmp_path / "partition"
    partition_root.mkdir()
    (partition_root / "load_neo4j.cypher").write_text("RETURN 1;\n")
    (partition_root / "load_fuseki.ttl").write_text("# empty\n")
    instance = {
        "query_id": "q-f1",
        "family_id": "f1_direct_transfer_control",
        "split_role": "heldout_instance",
        "parameters": {
            "person_id": "P1",
            "start_time": "2020-01-01 00:00:00.000",
            "end_time": "2020-12-31 23:59:59.999",
        },
    }
    public = {
        "root": workload_root,
        "manifest": {
            "population_id": "test-population",
            "workload_sha256": "a" * 64,
            "source_partition_sha256": "b" * 64,
            "source_archive_sha256": "c" * 64,
        },
        "public_instances": {"instances": [instance]},
        "family_contracts": {},
    }
    full = {
        **public,
        "sealed_oracles": {
            "queries": {
                "q-f1": {
                    "final_rows": [
                        {
                            "company_id": "C1",
                            "account_id": "A1",
                            "total_amount": "7.000",
                        }
                    ]
                }
            }
        },
    }
    partition = {
        "partition_sha256": "b" * 64,
        "source_archive": {"sha256": "c" * 64},
    }
    oracle_load_observations: list[int] = []
    clients = {backend_id: Client(backend_id) for backend_id in ("neo4j", "fuseki")}
    loaders = {backend_id: Loader(backend_id) for backend_id in ("neo4j", "fuseki")}
    calls = {"count": 0}
    for client in clients.values():
        original = client.execute

        def execute(artifact, *, _original=original):
            calls["count"] += 1
            return _original(artifact)

        client.execute = execute  # type: ignore[method-assign]

    monkeypatch.setattr(
        federation, "load_finbench_primary_public_workload", lambda _root: public
    )
    monkeypatch.setattr(
        live, "load_finbench_primary_public_workload", lambda _root: public
    )
    monkeypatch.setattr(live, "load_finbench_source_partition", lambda _root: partition)

    def open_oracle(_root):
        oracle_load_observations.append(calls["count"])
        return full

    monkeypatch.setattr(live, "load_finbench_primary_workload", open_oracle)

    record = live.run_m15_live_finbench_correctness(
        workload_root=workload_root,
        partition_root=partition_root,
        clients=clients,
        loaders=loaders,
        output_root=tmp_path / "runs",
        query_ids=("q-f1",),
    )

    assert record.success
    assert oracle_load_observations == [4]
    plan_catalog = json.loads((record.run_root / "plan_catalog.json").read_text())
    manifest = json.loads(record.manifest_path.read_text())
    validation = json.loads((record.run_root / "validation.json").read_text())
    assert plan_catalog["sealed_before_fixture_load"] is True
    assert plan_catalog["answer_oracle_bytes_hashed_for_identity"] is True
    assert plan_catalog["answer_oracle_content_parsed"] is False
    assert validation["passed"] is True
    assert manifest["summary"] == {
        "all_physical_pairs_equivalent": True,
        "all_plans_exact": True,
        "backend_calls": 4,
        "family_counts": {"f1_direct_transfer_control": 1},
        "physical_plan_run_count": 2,
        "query_count": 1,
    }
    assert manifest["oracle_boundary"]["content_parsed_after_all_plan_runs"] is True
    assert manifest["paper_result"] is False
