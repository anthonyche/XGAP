from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction_evidence import (
    audit_m15_direct_family_prediction_validation,
    main,
)
from xgap.experiments.m15_direct_family_prediction_run import (
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
RUNTIME_HASH = content_hash({"runtime": "f2c10c-audit-fixture"})
EXPECTED_COMMIT = "d" * 40


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _auditable_run(tmp_path: Path) -> Path:
    record = run_m15_direct_family_prediction_validation(
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
        run_id="auditable",
    )
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    manifest["git"] = {"commit": EXPECTED_COMMIT, "clean": True}
    _write(record.manifest_path, manifest)
    return record.run_root


def test_read_only_audit_reconstructs_complete_f2c10c_run(
    tmp_path: Path,
) -> None:
    run_root = _auditable_run(tmp_path)

    audit = audit_m15_direct_family_prediction_validation(
        run_root=run_root,
        expected_commit=EXPECTED_COMMIT,
    )

    assert audit.success
    assert len(audit.checks) >= 105
    assert audit.failed_check_ids == ()
    assert audit.run_tree_mutated is False


def test_audit_rejects_postseal_frontier_mutation(tmp_path: Path) -> None:
    run_root = _auditable_run(tmp_path)
    frontier = sorted(
        (run_root / "selection/queries").glob("*/semantic_frontier.json")
    )[0]
    payload = json.loads(frontier.read_text(encoding="utf-8"))
    payload["returned_semantic_plans"][0]["semantic_deviation"] = 9.0
    _write(frontier, payload)

    audit = audit_m15_direct_family_prediction_validation(
        run_root=run_root,
        expected_commit=EXPECTED_COMMIT,
    )

    assert not audit.success
    assert "seal.file_hashes" in audit.failed_check_ids
    assert any(
        check_id.endswith("semantic_frontier.json.exact")
        for check_id in audit.failed_check_ids
    )


def test_audit_rejects_changed_answer(tmp_path: Path) -> None:
    run_root = _auditable_run(tmp_path)
    result_path = run_root / "semantic_results.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["results"][0]["runtime_result"]["final_rows"] = []
    _write(result_path, payload)

    audit = audit_m15_direct_family_prediction_validation(
        run_root=run_root,
        expected_commit=EXPECTED_COMMIT,
    )

    assert not audit.success
    assert "result.0.rows" in audit.failed_check_ids
    assert "summary.row_counts" in audit.failed_check_ids


def test_audit_cli_writes_only_outside_the_run_tree(
    tmp_path: Path,
    capsys,
) -> None:
    run_root = _auditable_run(tmp_path)
    output = tmp_path / "audits/f2c10c.json"

    assert (
        main(
            [
                "--run-root",
                str(run_root),
                "--expected-commit",
                EXPECTED_COMMIT,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert printed == persisted
    assert persisted["success"] is True
    assert persisted["run_tree_mutated"] is False

    assert (
        main(
            [
                "--run-root",
                str(run_root),
                "--expected-commit",
                EXPECTED_COMMIT,
                "--output",
                str(output),
            ]
        )
        == 2
    )
