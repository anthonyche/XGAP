from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction_run import (
    DIRECT_FAMILY_SELECTION_SEAL_SCHEMA_VERSION,
    DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION,
    M15DirectFamilyValidationError,
    main,
    run_m15_direct_family_prediction_validation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SPEC = (
    REPO_ROOT / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
)
QUERY_TEMPLATE = (
    REPO_ROOT
    / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
)
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
SEMANTIC_CATALOG = (
    REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
)
PREDICATE_MAPPING = (
    REPO_ROOT / "experiments/configs/m15_f2c8_predicate_mapping_dev.json"
)
CARDINALITY_POLICY = (
    REPO_ROOT
    / "experiments/configs/m15_f2c10_direct_semantic_workload_dev.json"
)
PREDICTOR_POLICY = (
    REPO_ROOT
    / "experiments/configs/m15_f2c10_family_memory_predictor_dev.json"
)
RUNTIME_HASH = content_hash(
    {
        "runtime": "f2c10c-controlled-validation",
        "neo4j": "oracle-double",
        "fuseki": "oracle-double",
    }
)


def _run(
    tmp_path: Path,
    *,
    run_id: str = "f2c10c-success",
    fail_at: int | None = None,
):
    return run_m15_direct_family_prediction_validation(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        semantic_catalog=SEMANTIC_CATALOG,
        predicate_mapping=PREDICATE_MAPPING,
        cardinality_policy=CARDINALITY_POLICY,
        predictor_policy=PREDICTOR_POLICY,
        runtime_compatibility_sha256=RUNTIME_HASH,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
        run_id=run_id,
        inject_failure_at_invocation=fail_at,
    )


def test_controlled_validation_seals_then_executes_only_returned_plans(
    tmp_path: Path,
) -> None:
    record = _run(tmp_path)

    assert record.success
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    seal = json.loads(
        (record.run_root / "selection_seal.json").read_text(encoding="utf-8")
    )
    results = json.loads(
        (record.run_root / "semantic_results.json").read_text(encoding="utf-8")
    )["results"]
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["schema_version"] == DIRECT_FAMILY_VALIDATION_RUN_SCHEMA_VERSION
    assert seal["schema_version"] == DIRECT_FAMILY_SELECTION_SEAL_SCHEMA_VERSION
    assert manifest["validation"]["passed"] is True
    assert manifest["summary"] == {
        "training_semantic_task_count": 18,
        "training_physical_plan_count": 36,
        "heldout_semantic_task_count": 10,
        "heldout_physical_prediction_count": 20,
        "returned_semantic_plan_count": 4,
        "physical_plan_run_count": 4,
        "total_remote_calls": 8,
        "total_bytes_moved": sum(
            item["runtime_result"]["total_bytes_moved"] for item in results
        ),
        "final_row_counts": [11, 9, 12, 7],
    }
    assert all(item["exact_oracle_answer"] for item in results)
    assert invocations["total_tool_invocations"] == 8
    assert all(item["operation"] == "execute" for item in invocations["events"])
    assert seal["sealed_before_oracle_access"] is True
    assert seal["backend_calls_before_seal"] == 0
    assert seal["answer_oracle_fields"] == []
    assert seal["current_query_observation_operations"] == []
    assert manifest["current_query_profile_calls"] == 0
    assert manifest["heldout_measurements_collected"] is False
    assert manifest["automatic_retries"] == 0
    assert manifest["paper_result"] is False

    selection_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((record.run_root / "selection").rglob("*.json"))
    )
    assert '"final_oracle"' not in selection_text
    assert '"expected_result"' not in selection_text


def test_selection_seal_is_deterministic_across_run_ids(tmp_path: Path) -> None:
    first = _run(tmp_path, run_id="first")
    second = _run(tmp_path, run_id="second")

    first_seal = json.loads(
        (first.run_root / "selection_seal.json").read_text(encoding="utf-8")
    )
    second_seal = json.loads(
        (second.run_root / "selection_seal.json").read_text(encoding="utf-8")
    )
    assert first_seal == second_seal


def test_controlled_validation_stops_after_first_failure_without_retry(
    tmp_path: Path,
) -> None:
    record = _run(tmp_path, run_id="failed", fail_at=1)

    assert not record.success
    results = json.loads(
        (record.run_root / "semantic_results.json").read_text(encoding="utf-8")
    )["results"]
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert len(results) == 1
    assert results[0]["runtime_result"]["success"] is False
    assert invocations["total_tool_invocations"] == 1
    assert invocations["automatic_retries"] == 0
    assert manifest["status"] == "failed"
    assert manifest["validation"]["passed"] is False
    assert manifest["automatic_retries"] == 0


def test_invalid_runtime_hash_fails_before_creating_a_run(tmp_path: Path) -> None:
    with pytest.raises(M15DirectFamilyValidationError):
        run_m15_direct_family_prediction_validation(
            workload_spec=WORKLOAD_SPEC,
            query_template_spec=QUERY_TEMPLATE,
            backend_template_root=BACKEND_TEMPLATES,
            semantic_catalog=SEMANTIC_CATALOG,
            predicate_mapping=PREDICATE_MAPPING,
            cardinality_policy=CARDINALITY_POLICY,
            predictor_policy=PREDICTOR_POLICY,
            runtime_compatibility_sha256="bad",
            output_root=tmp_path / "runs",
            repo_root=REPO_ROOT,
        )
    assert not (tmp_path / "runs").exists()


def test_cli_refuses_to_overwrite_an_existing_run(
    tmp_path: Path,
    capsys,
) -> None:
    arguments = [
        "--workload-spec",
        str(WORKLOAD_SPEC),
        "--query-template",
        str(QUERY_TEMPLATE),
        "--backend-templates",
        str(BACKEND_TEMPLATES),
        "--semantic-catalog",
        str(SEMANTIC_CATALOG),
        "--predicate-mapping",
        str(PREDICATE_MAPPING),
        "--cardinality-policy",
        str(CARDINALITY_POLICY),
        "--predictor-policy",
        str(PREDICTOR_POLICY),
        "--runtime-compatibility-sha256",
        RUNTIME_HASH,
        "--output-root",
        str(tmp_path / "runs"),
        "--repo-root",
        str(REPO_ROOT),
        "--run-id",
        "cli-run",
    ]
    assert main(arguments) == 0
    capsys.readouterr()
    assert main(arguments) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "configuration_error"
