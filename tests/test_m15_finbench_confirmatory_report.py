from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_analysis import (
    FINBENCH_CONFIRMATORY_ANALYSIS_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_campaign import (
    FINBENCH_CONFIRMATORY_RESULT_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_campaign_evidence import (
    FINBENCH_CONFIRMATORY_CAMPAIGN_AUDIT_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_oracle import (
    FINBENCH_CONFIRMATORY_ORACLE_GATE_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_report import (
    FinBenchConfirmatoryPaperReportError,
    build_finbench_confirmatory_paper_report,
    main,
    render_finbench_confirmatory_paper_markdown,
)


SEEN_METHODS = (
    "family_memory_zero_profile",
    "current_query_dual_profile",
    "family_global_no_instance_features",
    "fixed_route_a",
    "fixed_route_b",
    "observed_oracle_upper_bound",
)
COLD_METHODS = (
    "predeclared_family_fallback",
    "current_query_dual_profile",
    "fixed_route_a",
    "fixed_route_b",
    "observed_oracle_upper_bound",
)


def _hash(value: dict, field: str) -> dict:
    result = copy.deepcopy(value)
    result[field] = content_hash(result)
    return result


def _summary(count: int, value: float) -> dict:
    return {
        "count": count,
        "mean": value,
        "median": value,
        "minimum": value,
        "maximum": value,
    }


def _metric(count: int, value: float, *, cold: bool) -> dict:
    result = {
        "query_count": count,
        "physical_winner_accuracy": 0.75,
        "latency_regret_ms": _summary(count, value),
        "end_to_end_latency_ms": _summary(count, value + 20.0),
    }
    if not cold:
        result["bytes_regret"] = {
            **_summary(count, value * 100.0),
            "missing_query_count": 0,
        }
        result["serving_latency_ms"] = _summary(count, value + 10.0)
    return result


def _inputs() -> tuple[dict, dict, dict]:
    analysis = {
        "schema_version": FINBENCH_CONFIRMATORY_ANALYSIS_SCHEMA_VERSION,
        "ledger_sha256": "1" * 64,
        "primary": {
            "rq_id": "RQ-P1",
            "inferential_query_count": 32,
            "repetition_count_as_independent_n": 0,
            "within_query_repetition_aggregation": "median",
            "geometric_mean_end_to_end_latency_ratio": 0.81,
            "paired_median_difference_ms": -4.5,
            "confidence_interval": {
                "method": "query_cluster_bootstrap_percentile",
                "confidence_level": 0.95,
                "resamples": 10_000,
                "seed": "test",
                "geometric_mean_ratio_ci": [0.72, 0.93],
                "paired_median_difference_ms_ci": [-7.0, -1.0],
            },
            "randomization_test": {
                "method": "two_sided_paired_sign_flip_on_query_values",
                "mode": "monte_carlo_plus_one",
                "draws": 100_000,
                "seed": "test",
                "observed_absolute_mean": 0.2,
                "extreme_count": 99,
                "p_value": 0.001,
            },
            "per_query": [],
        },
        "secondary": {
            "rq_id": "RQ-P2",
            "method_metrics": {
                method: _metric(32, float(index), cold=False)
                for index, method in enumerate(SEEN_METHODS, start=1)
            },
            "method_records": [],
            "prediction_error": {
                "plan_count": 64,
                "latency_absolute_error_ms": _summary(64, 2.5),
                "bytes_absolute_error": {
                    **_summary(64, 300.0),
                    "missing_plan_count": 0,
                },
                "records": [],
            },
            "predicted_observed_frontier_overlap": {
                "query_count": 32,
                "available_query_count": 32,
                "missing_query_count": 0,
                "mean_jaccard": 0.7,
                "per_query": [],
            },
            "holm_adjusted_secondary_tests": [
                {
                    "comparison_id": f"family_memory_vs_{name}",
                    "metric": "query_level_latency_regret_difference_ms",
                    "query_count": 32,
                    "p_value": 0.01 * index,
                    "test": {},
                    "holm_rank": index,
                    "holm_adjusted_p_value": 0.04,
                }
                for index, name in enumerate(
                    (
                        "current_query_dual_profile",
                        "family_global_no_instance_features",
                        "fixed_route_a",
                        "fixed_route_b",
                    ),
                    start=1,
                )
            ],
        },
        "cold_start": {
            "rq_id": "RQ-P3",
            "query_count": 16,
            "family_id": "f3_aggregate_risk_ranking",
            "family_memory_label_used": False,
            "inferential_test": None,
            "method_metrics": {
                method: _metric(16, float(index), cold=True)
                for index, method in enumerate(COLD_METHODS, start=1)
            },
            "method_records": [],
        },
        "offline_training_cost": {
            "plan_runs": 448,
            "backend_calls": 896,
            "latency_ms": 12345.0,
            "bytes": 456789,
            "excluded_from_primary_end_to_end_estimand": True,
            "amortized_latency_ms_per_primary_query": 385.78125,
        },
        "failure_accounting": {
            "query_timeout_count": 0,
            "query_timeouts_retained_as_method_outcomes": True,
            "infrastructure_replacement_count": 0,
            "automatic_retries": 0,
            "missing_measurements": "no_imputation",
        },
        "query_instance_is_inferential_unit": True,
        "repetitions_are_not_independent_units": True,
        "confirmatory_statistics": True,
        "independent_evidence_audit_required": True,
        "paper_result": False,
    }
    analysis = _hash(analysis, "analysis_sha256")
    oracle = _hash(
        {
            "schema_version": FINBENCH_CONFIRMATORY_ORACLE_GATE_SCHEMA_VERSION,
            "status": "success",
            "accepted_block_count": 22,
            "measurement_count_before_oracle_open": 1888,
            "backend_calls_after_oracle_open": 0,
            "answer_oracle_opened_after_all_measurements": True,
            "answer_oracle_used_for_selection": False,
            "all_successful_measurements_exact": True,
            "automatic_retries": 0,
            "paper_result": False,
            "analysis": analysis,
        },
        "oracle_gate_sha256",
    )
    result = _hash(
        {
            "schema_version": FINBENCH_CONFIRMATORY_RESULT_SCHEMA_VERSION,
            "campaign_id": "confirmatory-test",
            "status": "success",
            "oracle_gate_sha256": oracle["oracle_gate_sha256"],
            "measurement_block_count": 22,
            "total_plan_runs": 1888,
            "maximum_backend_calls": 3776,
            "all_successful_measurements_exact": True,
            "confirmatory_statistics_computed": True,
            "independent_campaign_audit_required": True,
            "automatic_retries": 0,
            "paper_result": False,
        },
        "campaign_result_sha256",
    )
    audit = _hash(
        {
            "schema_version": FINBENCH_CONFIRMATORY_CAMPAIGN_AUDIT_SCHEMA_VERSION,
            "success": True,
            "campaign_id": "confirmatory-test",
            "campaign_status": "success",
            "expected_commit": "a" * 40,
            "source_campaign_result_sha256": result[
                "campaign_result_sha256"
            ],
            "check_count": 1,
            "failed_check_ids": [],
            "checks": [
                {
                    "check_id": "test.complete",
                    "passed": True,
                    "expected": True,
                    "observed": True,
                }
            ],
            "run_tree_mutated": False,
            "confirmatory_result_admitted": True,
            "paper_result": True,
        },
        "audit_sha256",
    )
    return audit, result, oracle


def test_report_projects_admitted_statistics_without_recomputation() -> None:
    audit, result, oracle = _inputs()
    report = build_finbench_confirmatory_paper_report(
        campaign_audit=audit,
        campaign_result=result,
        oracle_gate=oracle,
        source_campaign_tree_sha256="b" * 64,
    )

    assert report["paper_result"] is True
    assert report["rq_p1_primary"][
        "geometric_mean_end_to_end_latency_ratio"
    ] == 0.81
    assert report["rq_p1_primary"]["inferential_query_count"] == 32
    assert len(report["rq_p2_seen_family_method_table"]) == 6
    assert len(report["rq_p2_holm_secondary_tests"]) == 4
    assert len(report["rq_p3_cold_start_method_table"]) == 5
    assert report["claim_boundary"]["cold_start_inferential_claim"] is False
    assert (
        report["claim_boundary"][
            "supports_semantic_ambiguity_or_ontology_claim"
        ]
        is False
    )


def test_markdown_labels_effect_direction_and_claim_boundary() -> None:
    audit, result, oracle = _inputs()
    report = build_finbench_confirmatory_paper_report(
        campaign_audit=audit,
        campaign_result=result,
        oracle_gate=oracle,
        source_campaign_tree_sha256="b" * 64,
    )

    text = render_finbench_confirmatory_paper_markdown(report)

    assert text.count(
        "## RQ-P1: zero-profile family memory versus current-query profiling"
    ) == 1
    assert "A ratio below 1 and a negative difference favor XGAP" in text
    assert "held-out-family cold start (descriptive)" in text
    assert "does not establish semantic-ambiguity, ontology" in text
    assert "Current-query dual profiling" in text


@pytest.mark.parametrize(
    ("target", "field", "value", "message"),
    (
        ("audit", "confirmatory_result_admitted", False, "final admission"),
        ("analysis", "repetitions_are_not_independent_units", False, "analysis boundary"),
        ("cold", "family_memory_label_used", True, "cold-start boundary"),
    ),
)
def test_report_rejects_claim_boundary_drift(
    target: str, field: str, value: object, message: str
) -> None:
    audit, result, oracle = _inputs()
    if target == "audit":
        audit[field] = value
        audit["audit_sha256"] = content_hash(
            {key: item for key, item in audit.items() if key != "audit_sha256"}
        )
    else:
        analysis = oracle["analysis"]
        if target == "analysis":
            analysis[field] = value
        else:
            analysis["cold_start"][field] = value
        analysis["analysis_sha256"] = content_hash(
            {
                key: item
                for key, item in analysis.items()
                if key != "analysis_sha256"
            }
        )
        oracle["oracle_gate_sha256"] = content_hash(
            {
                key: item
                for key, item in oracle.items()
                if key != "oracle_gate_sha256"
            }
        )
        result["oracle_gate_sha256"] = oracle["oracle_gate_sha256"]
        result["campaign_result_sha256"] = content_hash(
            {
                key: item
                for key, item in result.items()
                if key != "campaign_result_sha256"
            }
        )
        audit["source_campaign_result_sha256"] = result[
            "campaign_result_sha256"
        ]
        audit["audit_sha256"] = content_hash(
            {key: item for key, item in audit.items() if key != "audit_sha256"}
        )
    with pytest.raises(FinBenchConfirmatoryPaperReportError, match=message):
        build_finbench_confirmatory_paper_report(
            campaign_audit=audit,
            campaign_result=result,
            oracle_gate=oracle,
            source_campaign_tree_sha256="b" * 64,
        )


def test_cli_writes_outside_campaign_without_mutating_source(
    tmp_path: Path,
) -> None:
    audit, result, oracle = _inputs()
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign_result.json").write_text(json.dumps(result))
    (root / "oracle_gate.json").write_text(json.dumps(oracle))
    audit_path = tmp_path / "campaign-audit.json"
    audit_path.write_text(json.dumps(audit))
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.iterdir()
    }
    output_json = tmp_path / "paper/report.json"
    output_markdown = tmp_path / "paper/report.md"

    exit_code = main(
        [
            "--campaign-root",
            str(root),
            "--campaign-audit",
            str(audit_path),
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        ]
    )

    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.iterdir()
    }
    assert exit_code == 0
    assert before == after
    assert json.loads(output_json.read_text())["paper_result"] is True
    assert "# FinBench Confirmatory Results" in output_markdown.read_text()


def test_cli_rejects_output_inside_immutable_campaign(tmp_path: Path) -> None:
    audit, result, oracle = _inputs()
    root = tmp_path / "campaign"
    root.mkdir()
    (root / "campaign_result.json").write_text(json.dumps(result))
    (root / "oracle_gate.json").write_text(json.dumps(oracle))
    audit_path = tmp_path / "campaign-audit.json"
    audit_path.write_text(json.dumps(audit))

    assert (
        main(
            [
                "--campaign-root",
                str(root),
                "--campaign-audit",
                str(audit_path),
                "--output-json",
                str(root / "report.json"),
                "--output-markdown",
                str(tmp_path / "report.md"),
            ]
        )
        == 2
    )
    assert not (root / "report.json").exists()
