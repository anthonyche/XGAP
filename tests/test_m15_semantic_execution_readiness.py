from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadError,
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_execution_readiness import (
    SEMANTIC_EXECUTION_READINESS_SCHEMA_VERSION,
    M15SemanticExecutionReadinessError,
    audit_m15_semantic_execution_readiness,
    main,
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
QUERY_ID = "financial-risk-alice-aug-high-v2"


def _bundle(tmp_path: Path, name: str = "bundle"):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / name,
    )


def _audit(tmp_path: Path):
    return audit_m15_semantic_execution_readiness(
        bundle=_bundle(tmp_path),
        query_id=QUERY_ID,
        catalog=SEMANTIC_CATALOG,
    )


def test_readiness_separates_bound_generatable_and_blocked_classes(
    tmp_path: Path,
) -> None:
    payload = _audit(tmp_path).to_dict()

    assert payload["schema_version"] == SEMANTIC_EXECUTION_READINESS_SCHEMA_VERSION
    assert payload["counts"] == {
        "semantic_classes": 12,
        "bound_ready": 1,
        "overlay_generation_ready": 1,
        "blocked": 10,
    }
    assert len(payload["readiness_sha256"]) == 64
    assert payload["current_executor_capabilities"] == {
        "risk_levels": ["HIGH", "MEDIUM", "LOW"],
        "transfer_predicates": ["transfer_to_company"],
        "path_shapes": ["direct"],
    }
    assert payload["claim_boundary"] == {
        "artifact_class": "semantic_execution_readiness_audit",
        "relaxed_backend_artifacts_executed": False,
        "semantic_answer_quality_validated": False,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_calls_made": 0,
        "contains_measurements": False,
        "paper_result": False,
    }
    assert payload["paper_result"] is False


def test_exact_is_materialized_and_risk_only_relaxation_is_generatable(
    tmp_path: Path,
) -> None:
    payload = _audit(tmp_path).to_dict()
    exact = [
        item for item in payload["interpretations"] if not item["changed_slot_ids"]
    ]
    assert len(exact) == 1
    assert exact[0]["status"] == "bound_ready"
    assert exact[0]["bundle_artifacts_materialized"] is True
    assert exact[0]["semantic_deviation"] == 0

    risk_only = [
        item
        for item in payload["interpretations"]
        if item["changed_slot_ids"] == ["risk-level"]
    ]
    assert len(risk_only) == 1
    assert risk_only[0]["status"] == "overlay_generation_ready"
    assert risk_only[0]["backend_template_compilable"] is True
    assert risk_only[0]["dataset_supported"] is True
    assert risk_only[0]["oracle_generator_supported"] is True
    assert risk_only[0]["bundle_artifacts_materialized"] is False
    assert risk_only[0]["blockers"] == []


def test_readiness_reports_all_current_execution_gaps(tmp_path: Path) -> None:
    payload = _audit(tmp_path).to_dict()

    assert payload["blocker_occurrence_counts"] == {
        "path_backend_template_missing": 8,
        "path_data_missing": 8,
        "path_oracle_support_missing": 8,
        "path_semantics_unbound": 8,
        "predicate_backend_mapping_missing": 6,
        "predicate_data_missing": 6,
        "predicate_oracle_support_missing": 6,
    }
    assert payload["next_required_actions"] == [
        {
            "action_id": "materialize-supported-relaxation-overlay",
            "requires_user_decision": False,
            "affected_semantic_class_count": 1,
        },
        {
            "action_id": "add-versioned-payment-data-compiler-and-oracle",
            "requires_user_decision": False,
            "affected_semantic_class_count": 6,
        },
        {
            "action_id": "freeze-multihop-hard-constraint-semantics",
            "requires_user_decision": True,
            "affected_semantic_class_count": 8,
        },
    ]


def test_all_hard_bindings_remain_fixed_in_readiness_matrix(
    tmp_path: Path,
) -> None:
    payload = _audit(tmp_path).to_dict()
    for interpretation in payload["interpretations"]:
        bindings = {
            item["slot_id"]: item["value"] for item in interpretation["bindings"]
        }
        assert bindings["person-identity"] == "person-alice-smith"
        assert bindings["time-lower-bound"] == "2026-08-01"
        assert bindings["amount-lower-bound"] == 50000


def test_readiness_is_deterministic_for_same_verified_bundle(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    first = audit_m15_semantic_execution_readiness(
        bundle=bundle,
        query_id=QUERY_ID,
        catalog=SEMANTIC_CATALOG,
    ).to_dict()
    second = audit_m15_semantic_execution_readiness(
        bundle=bundle.root,
        query_id=QUERY_ID,
        catalog=SEMANTIC_CATALOG,
    ).to_dict()

    assert first == second


def test_unknown_query_and_tampered_bundle_fail_closed(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    with pytest.raises(
        M15SemanticExecutionReadinessError, match="exactly one workload instance"
    ):
        audit_m15_semantic_execution_readiness(
            bundle=bundle,
            query_id="unknown-query",
            catalog=SEMANTIC_CATALOG,
        )

    target = bundle.path("parameterized_query_template.json")
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(M15ParameterizedWorkloadError, match="SHA-256 mismatch"):
        audit_m15_semantic_execution_readiness(
            bundle=bundle.root,
            query_id=QUERY_ID,
            catalog=SEMANTIC_CATALOG,
        )


def test_cli_writes_readiness_once(tmp_path: Path, capsys) -> None:
    bundle = _bundle(tmp_path)
    output = tmp_path / "readiness.json"
    arguments = [
        "--bundle-root",
        str(bundle.root),
        "--query-id",
        QUERY_ID,
        "--catalog",
        str(SEMANTIC_CATALOG),
        "--output",
        str(output),
    ]

    assert main(arguments) == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["status"] == "success"
    assert stdout["counts"]["blocked"] == 10
    assert json.loads(output.read_text(encoding="utf-8"))["counts"] == {
        "semantic_classes": 12,
        "bound_ready": 1,
        "overlay_generation_ready": 1,
        "blocked": 10,
    }

    assert main(arguments) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "configuration_error"
    assert "output exists" in failure["error"]
