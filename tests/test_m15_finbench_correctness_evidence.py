from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments import m15_finbench_correctness_evidence as evidence
from xgap.experiments.m15_finbench_federation import FEDERATION_SCHEMA_VERSION
from xgap.experiments.m15_live_finbench_correctness import (
    LIVE_CORRECTNESS_SCHEMA_VERSION,
    PLAN_CATALOG_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
)
from xgap.experiments.m15_native_services import (
    FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.runtime import (
    FederatedExecutionPlan,
    FederatedPlanCandidate,
    RuntimeNode,
    RuntimeNodeKind,
)


COMMIT = "a" * 40
FAMILY = "f1_direct_transfer_control"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _candidate(plan_id: str, strategy: str) -> FederatedPlanCandidate:
    plan = FederatedExecutionPlan(
        plan_id=plan_id,
        nodes=(
            RuntimeNode(
                "source",
                RuntimeNodeKind.REMOTE_QUERY,
                parameters={
                    "backend_id": "neo4j",
                    "artifact": {
                        "artifact_id": plan_id,
                        "language": "cypher",
                        "text": "RETURN 1",
                    },
                },
            ),
        ),
        roots=("source",),
        max_remote_calls=2,
        metadata={
            "schema_version": FEDERATION_SCHEMA_VERSION,
            "physical_strategy": strategy,
        },
    )
    return FederatedPlanCandidate(plan, "workload:q-f1:exact")


def _run_tree(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "run"
    service = root / "native-service-run"
    live = service / "finbench-correctness-run"
    workload = root / "finbench-primary-workload"
    partition = root / "finbench-source-partition"
    workload.mkdir(parents=True)
    partition.mkdir()
    candidates = (
        _candidate("q-f1-graph", "graph_first_hash"),
        _candidate("q-f1-bind", "control_first_bind"),
    )
    instance = {
        "query_id": "q-f1",
        "family_id": FAMILY,
        "split_role": "heldout_instance",
        "parameters": {},
    }
    public = {
        "manifest": {"population_id": "population", "workload_sha256": "b" * 64},
        "public_instances": {"instances": [instance]},
    }
    oracle = {
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
    partition_payload = {"partition_sha256": "c" * 64}
    monkeypatch.setattr(
        evidence, "load_finbench_primary_public_workload", lambda _root: public
    )
    monkeypatch.setattr(
        evidence, "load_finbench_primary_workload", lambda _root: oracle
    )
    monkeypatch.setattr(
        evidence, "load_finbench_source_partition", lambda _root: partition_payload
    )
    monkeypatch.setattr(
        evidence,
        "build_finbench_plan_candidates",
        lambda _root, *, query_id: candidates,
    )

    entries = [
        {
            "query_id": "q-f1",
            "family_id": FAMILY,
            "split_role": "heldout_instance",
            "semantic_equivalence_key": candidate.semantic_equivalence_key,
            "physical_strategy": candidate.plan.metadata["physical_strategy"],
            "plan": candidate.plan.to_dict(),
        }
        for candidate in candidates
    ]
    catalog = {
        "schema_version": PLAN_CATALOG_SCHEMA_VERSION,
        "population_id": "population",
        "workload_sha256": "b" * 64,
        "source_partition_sha256": "c" * 64,
        "query_count": 1,
        "plan_count": 2,
        "plans": entries,
        "sealed_before_fixture_load": True,
        "answer_oracle_bytes_hashed_for_identity": True,
        "answer_oracle_content_parsed": False,
        "backend_calls_before_seal": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    catalog["plan_catalog_sha256"] = evidence._canonical_sha256(catalog)
    rows = [{"company_id": "C1", "account_id": "A1", "total_amount": 7.0}]
    results = [
        {
            "query_id": "q-f1",
            "family_id": FAMILY,
            "split_role": "heldout_instance",
            "plan_id": candidate.plan.plan_id,
            "physical_strategy": candidate.plan.metadata["physical_strategy"],
            "success": True,
            "elapsed_ms": 1.0,
            "total_remote_calls": 2,
            "total_bytes_moved": 10,
            "runtime_result": {
                "success": True,
                "total_remote_calls": 2,
                "final_rows": rows,
            },
        }
        for candidate in candidates
    ]
    comparisons = [
        {
            "query_id": "q-f1",
            "family_id": FAMILY,
            "plan_id": result["plan_id"],
            "physical_strategy": result["physical_strategy"],
            "exact": True,
            "actual_row_count": 1,
            "expected_row_count": 1,
        }
        for result in results
    ]
    validation = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "passed": True,
        "all_plans_exact": True,
        "all_physical_pairs_equivalent": True,
        "paired_equivalence": {"q-f1": True},
        "comparisons": comparisons,
        "expected_backend_calls": 4,
        "observed_backend_calls": 4,
        "answer_oracle_content_parsed_after_all_plan_runs": True,
        "answer_oracle_fields_used_for_selection": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    validation["validation_sha256"] = evidence._canonical_sha256(validation)
    manifest = {
        "schema_version": LIVE_CORRECTNESS_SCHEMA_VERSION,
        "run_id": "finbench-correctness-run",
        "status": "success",
        "error": None,
        "started_at": "2026-09-07T00:00:00+00:00",
        "ended_at": "2026-09-07T00:01:00+00:00",
        "execution_elapsed_ms": 1.0,
        "git": {"commit": COMMIT, "clean": True},
        "population_id": "population",
        "workload_sha256": "b" * 64,
        "source_partition_sha256": "c" * 64,
        "plan_catalog_sha256": catalog["plan_catalog_sha256"],
        "query_ids": ["q-f1"],
        "summary": {
            "query_count": 1,
            "family_counts": {FAMILY: 1},
            "physical_plan_run_count": 2,
            "backend_calls": 4,
            "all_plans_exact": True,
            "all_physical_pairs_equivalent": True,
        },
        "oracle_boundary": {
            "bytes_hashed_for_identity_before_execution": True,
            "content_parsed": True,
            "content_parsed_after_all_plan_runs": True,
            "backend_calls_before_open": 4,
            "used_for_selection": False,
        },
        "automatic_retries": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "development_correctness_gate_only": True,
        "paper_result": False,
    }
    manifest["manifest_sha256"] = evidence._canonical_sha256(manifest)

    _write(
        root / "run_status.json",
        {
            "status": "success",
            "exit_code": 0,
            "git_commit": COMMIT,
            "workload_mode": "finbench_correctness",
            "runtime_removed": True,
        },
    )
    _write(
        service / "run_status.json",
        {
            "schema_version": FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
        },
    )
    _write(
        service / "run_manifest.json",
        {
            "schema_version": FINBENCH_CORRECTNESS_SERVICE_RUN_SCHEMA_VERSION,
            "status": "success",
            "finbench_correctness": {
                "workload": str(workload),
                "partition": str(partition),
                "query_ids": None,
            },
        },
    )
    _write(
        live / "run_status.json",
        {"schema_version": LIVE_CORRECTNESS_SCHEMA_VERSION, "status": "success", "error": None},
    )
    _write(live / "run_manifest.json", manifest)
    _write(live / "plan_catalog.json", catalog)
    _write(
        live / "load_reports.json",
        {
            backend_id: {"backend_id": backend_id, "success": True, "error": None}
            for backend_id in ("neo4j", "fuseki")
        },
    )
    _write(live / "execution_results.json", {"results": results})
    _write(live / "validation.json", validation)
    return root


def test_finbench_correctness_audit_reconstructs_clean_run(
    tmp_path: Path, monkeypatch
) -> None:
    root = _run_tree(tmp_path, monkeypatch)

    audit = evidence.audit_m15_finbench_correctness(
        run_root=root, expected_commit=COMMIT
    )

    assert audit.success
    assert audit.failed_check_ids == ()
    assert audit.run_tree_mutated is False


def test_finbench_correctness_audit_rejects_tampered_answer(
    tmp_path: Path, monkeypatch
) -> None:
    root = _run_tree(tmp_path, monkeypatch)
    execution_path = (
        root
        / "native-service-run/finbench-correctness-run/execution_results.json"
    )
    execution = json.loads(execution_path.read_text())
    execution["results"][0]["runtime_result"]["final_rows"][0]["total_amount"] = 8.0
    _write(execution_path, execution)

    audit = evidence.audit_m15_finbench_correctness(
        run_root=root, expected_commit=COMMIT
    )

    assert not audit.success
    assert "validation.exact" in audit.failed_check_ids
