"""Render an admitted FinBench confirmatory campaign as paper-ready tables.

This presentation layer never measures, selects, or recomputes inferential
statistics.  It accepts only a successful campaign result admitted by the
independent final audit, then projects the frozen analysis into a compact JSON
record and deterministic Markdown tables.  Repetitions remain within-query
measurements and the held-out F3 family remains a cold-start report.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

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


FINBENCH_CONFIRMATORY_PAPER_REPORT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-paper-report-v1"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEEN_METHODS = (
    "family_memory_zero_profile",
    "current_query_dual_profile",
    "family_global_no_instance_features",
    "fixed_route_a",
    "fixed_route_b",
    "observed_oracle_upper_bound",
)
_COLD_METHODS = (
    "predeclared_family_fallback",
    "current_query_dual_profile",
    "fixed_route_a",
    "fixed_route_b",
    "observed_oracle_upper_bound",
)
_METHOD_LABELS = {
    "family_memory_zero_profile": "XGAP family memory (zero profile)",
    "current_query_dual_profile": "Current-query dual profiling",
    "family_global_no_instance_features": "Family-global ablation",
    "predeclared_family_fallback": "Predeclared cold-start fallback",
    "fixed_route_a": "Fixed route A",
    "fixed_route_b": "Fixed route B",
    "observed_oracle_upper_bound": "Post-execution oracle upper bound",
}


class FinBenchConfirmatoryPaperReportError(ValueError):
    """Raised when a result is not admissible for paper presentation."""


def _hashed(
    value: Mapping[str, Any], *, field: str, name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryPaperReportError(f"{name} must be an object")
    result = copy.deepcopy(dict(value))
    claimed = result.get(field)
    if (
        not isinstance(claimed, str)
        or _SHA256.fullmatch(claimed) is None
        or claimed
        != content_hash(
            {key: item for key, item in result.items() if key != field}
        )
    ):
        raise FinBenchConfirmatoryPaperReportError(f"{name} hash mismatch")
    return result


def _finite(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FinBenchConfirmatoryPaperReportError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise FinBenchConfirmatoryPaperReportError(f"{name} must be finite")
    return result


def _nullable_finite(value: object, *, name: str) -> float | None:
    return None if value is None else _finite(value, name=name)


def _summary(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryPaperReportError(f"{name} is missing")
    count = value.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise FinBenchConfirmatoryPaperReportError(f"{name}.count is invalid")
    result: dict[str, Any] = {"count": count}
    for field in ("mean", "median", "minimum", "maximum"):
        result[field] = _nullable_finite(
            value.get(field), name=f"{name}.{field}"
        )
    if count and any(result[field] is None for field in result if field != "count"):
        raise FinBenchConfirmatoryPaperReportError(
            f"{name} has missing values for a nonempty summary"
        )
    return result


def _method_table(
    raw: object, *, methods: Sequence[str], query_count: int, cold: bool
) -> list[dict[str, Any]]:
    if not isinstance(raw, Mapping) or set(raw) != set(methods):
        raise FinBenchConfirmatoryPaperReportError("method metric set changed")
    rows = []
    for method_id in methods:
        value = raw[method_id]
        if not isinstance(value, Mapping) or value.get("query_count") != query_count:
            raise FinBenchConfirmatoryPaperReportError(
                f"method query count changed: {method_id}"
            )
        accuracy = _finite(
            value.get("physical_winner_accuracy"),
            name=f"{method_id}.physical_winner_accuracy",
        )
        if not 0.0 <= accuracy <= 1.0:
            raise FinBenchConfirmatoryPaperReportError(
                f"method accuracy is outside [0, 1]: {method_id}"
            )
        latency = _summary(
            value.get("latency_regret_ms"),
            name=f"{method_id}.latency_regret_ms",
        )
        end_to_end = _summary(
            value.get("end_to_end_latency_ms"),
            name=f"{method_id}.end_to_end_latency_ms",
        )
        if latency["count"] != query_count or end_to_end["count"] != query_count:
            raise FinBenchConfirmatoryPaperReportError(
                f"method summary count changed: {method_id}"
            )
        row: dict[str, Any] = {
            "method_id": method_id,
            "method_label": _METHOD_LABELS[method_id],
            "query_count": query_count,
            "physical_winner_accuracy": accuracy,
            "latency_regret_ms": latency,
            "end_to_end_latency_ms": end_to_end,
        }
        if not cold:
            bytes_regret = _summary(
                value.get("bytes_regret"),
                name=f"{method_id}.bytes_regret",
            )
            missing = value.get("bytes_regret", {}).get("missing_query_count")
            if (
                isinstance(missing, bool)
                or not isinstance(missing, int)
                or missing < 0
                or bytes_regret["count"] + missing != query_count
            ):
                raise FinBenchConfirmatoryPaperReportError(
                    f"method byte accounting changed: {method_id}"
                )
            row["bytes_regret"] = {
                **bytes_regret,
                "missing_query_count": missing,
            }
        rows.append(row)
    return rows


def build_finbench_confirmatory_paper_report(
    *,
    campaign_audit: Mapping[str, Any],
    campaign_result: Mapping[str, Any],
    oracle_gate: Mapping[str, Any],
    source_campaign_tree_sha256: str,
) -> dict[str, Any]:
    """Project already-computed confirmatory statistics into paper tables."""

    if _SHA256.fullmatch(source_campaign_tree_sha256) is None:
        raise FinBenchConfirmatoryPaperReportError(
            "source campaign tree SHA-256 is invalid"
        )
    audit = _hashed(
        campaign_audit, field="audit_sha256", name="campaign audit"
    )
    result = _hashed(
        campaign_result,
        field="campaign_result_sha256",
        name="campaign result",
    )
    oracle = _hashed(oracle_gate, field="oracle_gate_sha256", name="oracle gate")
    analysis_raw = oracle.get("analysis")
    if not isinstance(analysis_raw, Mapping):
        raise FinBenchConfirmatoryPaperReportError(
            "successful oracle analysis is missing"
        )
    analysis = _hashed(
        analysis_raw, field="analysis_sha256", name="confirmatory analysis"
    )
    checks = audit.get("checks")
    if (
        audit.get("schema_version")
        != FINBENCH_CONFIRMATORY_CAMPAIGN_AUDIT_SCHEMA_VERSION
        or audit.get("success") is not True
        or audit.get("confirmatory_result_admitted") is not True
        or audit.get("paper_result") is not True
        or audit.get("failed_check_ids") != []
        or audit.get("run_tree_mutated") is not False
        or not isinstance(checks, list)
        or audit.get("check_count") != len(checks)
        or not checks
        or any(
            not isinstance(item, Mapping) or item.get("passed") is not True
            for item in checks
        )
    ):
        raise FinBenchConfirmatoryPaperReportError(
            "campaign has not passed independent final admission"
        )
    if (
        result.get("schema_version")
        != FINBENCH_CONFIRMATORY_RESULT_SCHEMA_VERSION
        or result.get("status") != "success"
        or result.get("campaign_id") != audit.get("campaign_id")
        or result.get("campaign_result_sha256")
        != audit.get("source_campaign_result_sha256")
        or result.get("measurement_block_count") != 22
        or result.get("total_plan_runs") != 1888
        or result.get("maximum_backend_calls") != 3776
        or result.get("all_successful_measurements_exact") is not True
        or result.get("confirmatory_statistics_computed") is not True
        or result.get("independent_campaign_audit_required") is not True
        or result.get("automatic_retries") != 0
        or result.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryPaperReportError(
            "campaign result boundary changed"
        )
    if (
        oracle.get("schema_version")
        != FINBENCH_CONFIRMATORY_ORACLE_GATE_SCHEMA_VERSION
        or oracle.get("status") != "success"
        or oracle.get("oracle_gate_sha256") != result.get("oracle_gate_sha256")
        or oracle.get("accepted_block_count") != 22
        or oracle.get("measurement_count_before_oracle_open") != 1888
        or oracle.get("backend_calls_after_oracle_open") != 0
        or oracle.get("answer_oracle_opened_after_all_measurements") is not True
        or oracle.get("answer_oracle_used_for_selection") is not False
        or oracle.get("all_successful_measurements_exact") is not True
        or oracle.get("automatic_retries") != 0
        or oracle.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryPaperReportError("oracle boundary changed")
    if (
        analysis.get("schema_version")
        != FINBENCH_CONFIRMATORY_ANALYSIS_SCHEMA_VERSION
        or analysis.get("confirmatory_statistics") is not True
        or analysis.get("query_instance_is_inferential_unit") is not True
        or analysis.get("repetitions_are_not_independent_units") is not True
        or analysis.get("independent_evidence_audit_required") is not True
        or analysis.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryPaperReportError("analysis boundary changed")

    primary = analysis.get("primary")
    secondary = analysis.get("secondary")
    cold = analysis.get("cold_start")
    failures = analysis.get("failure_accounting")
    offline = analysis.get("offline_training_cost")
    if not all(
        isinstance(value, Mapping)
        for value in (primary, secondary, cold, failures, offline)
    ):
        raise FinBenchConfirmatoryPaperReportError("analysis sections are missing")
    confidence = primary.get("confidence_interval")
    randomization = primary.get("randomization_test")
    if (
        primary.get("rq_id") != "RQ-P1"
        or primary.get("inferential_query_count") != 32
        or primary.get("repetition_count_as_independent_n") != 0
        or primary.get("within_query_repetition_aggregation") != "median"
        or not isinstance(confidence, Mapping)
        or confidence.get("method") != "query_cluster_bootstrap_percentile"
        or confidence.get("confidence_level") != 0.95
        or confidence.get("resamples") != 10_000
        or not isinstance(randomization, Mapping)
        or randomization.get("method")
        != "two_sided_paired_sign_flip_on_query_values"
    ):
        raise FinBenchConfirmatoryPaperReportError("primary estimand changed")
    ratio_ci = confidence.get("geometric_mean_ratio_ci")
    difference_ci = confidence.get("paired_median_difference_ms_ci")
    if (
        not isinstance(ratio_ci, list)
        or len(ratio_ci) != 2
        or not isinstance(difference_ci, list)
        or len(difference_ci) != 2
    ):
        raise FinBenchConfirmatoryPaperReportError("primary interval changed")
    primary_table = {
        "comparison": "XGAP family memory / current-query dual profiling",
        "inferential_query_count": 32,
        "repetition_aggregation": "within-query median",
        "geometric_mean_end_to_end_latency_ratio": _finite(
            primary.get("geometric_mean_end_to_end_latency_ratio"),
            name="primary latency ratio",
        ),
        "geometric_mean_ratio_95pct_ci": [
            _finite(item, name="primary ratio CI") for item in ratio_ci
        ],
        "paired_median_difference_ms": _finite(
            primary.get("paired_median_difference_ms"),
            name="primary median difference",
        ),
        "paired_median_difference_ms_95pct_ci": [
            _finite(item, name="primary difference CI")
            for item in difference_ci
        ],
        "paired_randomization_p_value": _finite(
            randomization.get("p_value"), name="primary p-value"
        ),
        "ratio_below_one_favors": "XGAP family memory",
        "negative_difference_favors": "XGAP family memory",
    }
    if (
        primary_table["geometric_mean_end_to_end_latency_ratio"] <= 0
        or any(
            item <= 0
            for item in primary_table["geometric_mean_ratio_95pct_ci"]
        )
        or primary_table["geometric_mean_ratio_95pct_ci"][0]
        > primary_table["geometric_mean_ratio_95pct_ci"][1]
        or primary_table["paired_median_difference_ms_95pct_ci"][0]
        > primary_table["paired_median_difference_ms_95pct_ci"][1]
        or not 0.0 <= primary_table["paired_randomization_p_value"] <= 1.0
    ):
        raise FinBenchConfirmatoryPaperReportError(
            "primary estimate or interval is invalid"
        )
    seen_table = _method_table(
        secondary.get("method_metrics"),
        methods=_SEEN_METHODS,
        query_count=32,
        cold=False,
    )
    tests = secondary.get("holm_adjusted_secondary_tests")
    if not isinstance(tests, list) or len(tests) != 4:
        raise FinBenchConfirmatoryPaperReportError(
            "Holm secondary comparison set changed"
        )
    expected_comparisons = {
        "family_memory_vs_current_query_dual_profile",
        "family_memory_vs_family_global_no_instance_features",
        "family_memory_vs_fixed_route_a",
        "family_memory_vs_fixed_route_b",
    }
    if {
        str(item.get("comparison_id"))
        for item in tests
        if isinstance(item, Mapping)
    } != expected_comparisons:
        raise FinBenchConfirmatoryPaperReportError(
            "Holm secondary comparison identities changed"
        )
    holm_table = []
    for value in sorted(tests, key=lambda item: str(item.get("comparison_id"))):
        if not isinstance(value, Mapping) or value.get("query_count") != 32:
            raise FinBenchConfirmatoryPaperReportError(
                "Holm secondary comparison is invalid"
            )
        rank = value.get("holm_rank")
        row = {
            "comparison_id": str(value.get("comparison_id")),
            "query_count": 32,
            "unadjusted_p_value": _finite(
                value.get("p_value"), name="secondary p-value"
            ),
            "holm_rank": rank,
            "holm_adjusted_p_value": _finite(
                value.get("holm_adjusted_p_value"),
                name="Holm-adjusted p-value",
            ),
        }
        if (
            isinstance(rank, bool)
            or not isinstance(rank, int)
            or not 1 <= rank <= 4
            or not 0.0 <= row["unadjusted_p_value"] <= 1.0
            or not 0.0 <= row["holm_adjusted_p_value"] <= 1.0
            or row["holm_adjusted_p_value"] < row["unadjusted_p_value"]
        ):
            raise FinBenchConfirmatoryPaperReportError(
                "Holm secondary comparison value is invalid"
            )
        holm_table.append(row)
    if {item["holm_rank"] for item in holm_table} != {1, 2, 3, 4}:
        raise FinBenchConfirmatoryPaperReportError(
            "Holm secondary ranks changed"
        )
    frontier = secondary.get("predicted_observed_frontier_overlap")
    prediction = secondary.get("prediction_error")
    if not isinstance(frontier, Mapping) or not isinstance(prediction, Mapping):
        raise FinBenchConfirmatoryPaperReportError(
            "prediction diagnostics are missing"
        )
    prediction_table = {
        "plan_count": prediction.get("plan_count"),
        "latency_absolute_error_ms": _summary(
            prediction.get("latency_absolute_error_ms"),
            name="prediction latency error",
        ),
        "bytes_absolute_error": {
            **_summary(
                prediction.get("bytes_absolute_error"),
                name="prediction byte error",
            ),
            "missing_plan_count": prediction.get(
                "bytes_absolute_error", {}
            ).get("missing_plan_count"),
        },
        "frontier_query_count": frontier.get("query_count"),
        "frontier_available_query_count": frontier.get(
            "available_query_count"
        ),
        "frontier_missing_query_count": frontier.get("missing_query_count"),
        "mean_frontier_jaccard": _nullable_finite(
            frontier.get("mean_jaccard"), name="mean frontier Jaccard"
        ),
    }
    if (
        prediction_table["plan_count"] != 64
        or prediction_table["latency_absolute_error_ms"]["count"] != 64
        or not isinstance(
            prediction_table["bytes_absolute_error"]["missing_plan_count"],
            int,
        )
        or prediction_table["bytes_absolute_error"]["missing_plan_count"] < 0
        or prediction_table["bytes_absolute_error"]["count"]
        + prediction_table["bytes_absolute_error"]["missing_plan_count"]
        != 64
        or prediction_table["frontier_query_count"] != 32
        or not isinstance(
            prediction_table["frontier_available_query_count"], int
        )
        or not isinstance(
            prediction_table["frontier_missing_query_count"], int
        )
        or prediction_table["frontier_available_query_count"]
        + prediction_table["frontier_missing_query_count"]
        != 32
        or (
            prediction_table["mean_frontier_jaccard"] is not None
            and not 0.0
            <= prediction_table["mean_frontier_jaccard"]
            <= 1.0
        )
    ):
        raise FinBenchConfirmatoryPaperReportError(
            "prediction diagnostic population changed"
        )
    if (
        cold.get("rq_id") != "RQ-P3"
        or cold.get("query_count") != 16
        or cold.get("family_id") != "f3_aggregate_risk_ranking"
        or cold.get("family_memory_label_used") is not False
        or cold.get("inferential_test") is not None
    ):
        raise FinBenchConfirmatoryPaperReportError("cold-start boundary changed")
    cold_table = _method_table(
        cold.get("method_metrics"),
        methods=_COLD_METHODS,
        query_count=16,
        cold=True,
    )
    if (
        failures.get("query_timeouts_retained_as_method_outcomes") is not True
        or failures.get("automatic_retries") != 0
        or failures.get("missing_measurements") != "no_imputation"
        or offline.get("plan_runs") != 448
        or offline.get("excluded_from_primary_end_to_end_estimand") is not True
    ):
        raise FinBenchConfirmatoryPaperReportError(
            "failure or training-cost accounting changed"
        )
    accounting = {
        "measurement_blocks": 22,
        "total_plan_runs": 1888,
        "maximum_backend_calls": 3776,
        "query_timeout_count": failures.get("query_timeout_count"),
        "infrastructure_replacement_count": failures.get(
            "infrastructure_replacement_count"
        ),
        "automatic_retries": 0,
        "missing_measurements": "no_imputation",
        "offline_training_plan_runs": 448,
        "offline_training_backend_calls": offline.get("backend_calls"),
        "offline_training_latency_ms": offline.get("latency_ms"),
        "offline_training_bytes": offline.get("bytes"),
        "offline_training_excluded_from_primary_end_to_end_estimand": True,
    }
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_PAPER_REPORT_SCHEMA_VERSION,
        "source": {
            "campaign_id": result["campaign_id"],
            "runner_commit": audit["expected_commit"],
            "source_campaign_tree_sha256": source_campaign_tree_sha256,
            "campaign_result_sha256": result["campaign_result_sha256"],
            "oracle_gate_sha256": oracle["oracle_gate_sha256"],
            "analysis_sha256": analysis["analysis_sha256"],
            "campaign_audit_sha256": audit["audit_sha256"],
        },
        "rq_p1_primary": primary_table,
        "rq_p2_seen_family_method_table": seen_table,
        "rq_p2_holm_secondary_tests": holm_table,
        "rq_p2_prediction_diagnostics": prediction_table,
        "rq_p3_cold_start_method_table": cold_table,
        "resource_and_failure_accounting": accounting,
        "claim_boundary": {
            "independent_campaign_audit_passed": True,
            "all_successful_measurements_exact": True,
            "query_instance_is_inferential_unit": True,
            "repetitions_are_independent_units": False,
            "seen_family_inferential_query_count": 32,
            "cold_family_descriptive_query_count": 16,
            "cold_start_inferential_claim": False,
            "supports_real_heterogeneous_finbench_physical_optimization_claim": True,
            "supports_semantic_ambiguity_or_ontology_claim": False,
            "supports_general_kgqa_claim": False,
            "source_run_tree_mutated": False,
        },
        "paper_result": True,
    }
    body["report_sha256"] = content_hash(body)
    return body


def _fmt(value: object, *, digits: int = 3) -> str:
    if value is None:
        return "NA"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{digits}f}"


def render_finbench_confirmatory_paper_markdown(
    report: Mapping[str, Any],
) -> str:
    """Render a validated paper report without changing any statistic."""

    frozen = _hashed(report, field="report_sha256", name="paper report")
    if (
        frozen.get("schema_version")
        != FINBENCH_CONFIRMATORY_PAPER_REPORT_SCHEMA_VERSION
        or frozen.get("paper_result") is not True
    ):
        raise FinBenchConfirmatoryPaperReportError("paper report boundary changed")
    primary = frozen["rq_p1_primary"]
    lines = [
        "# FinBench Confirmatory Results",
        "",
        f"Campaign: `{frozen['source']['campaign_id']}`  ",
        f"Runner commit: `{frozen['source']['runner_commit']}`  ",
        f"Independent audit: `{frozen['source']['campaign_audit_sha256']}`",
        "",
        "## RQ-P1: zero-profile family memory versus current-query profiling",
        "",
        "| Inferential queries | Geometric E2E latency ratio | 95% CI | Paired median difference (ms) | 95% CI (ms) | Paired p-value |",
        "|---:|---:|:---:|---:|:---:|---:|",
        "| "
        + " | ".join(
            (
                str(primary["inferential_query_count"]),
                _fmt(primary["geometric_mean_end_to_end_latency_ratio"]),
                "["
                + ", ".join(
                    _fmt(item)
                    for item in primary["geometric_mean_ratio_95pct_ci"]
                )
                + "]",
                _fmt(primary["paired_median_difference_ms"]),
                "["
                + ", ".join(
                    _fmt(item)
                    for item in primary[
                        "paired_median_difference_ms_95pct_ci"
                    ]
                )
                + "]",
                _fmt(primary["paired_randomization_p_value"], digits=4),
            )
        )
        + " |",
        "",
        "A ratio below 1 and a negative difference favor XGAP family memory.",
        "",
        "## RQ-P2: physical methods and ablations on seen families",
        "",
        "| Method | n | Winner accuracy | Mean latency regret (ms) | Median latency regret (ms) | Mean byte regret | Mean E2E latency (ms) |",
        "|:---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in frozen["rq_p2_seen_family_method_table"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    row["method_label"],
                    str(row["query_count"]),
                    _fmt(row["physical_winner_accuracy"]),
                    _fmt(row["latency_regret_ms"]["mean"]),
                    _fmt(row["latency_regret_ms"]["median"]),
                    _fmt(row["bytes_regret"]["mean"]),
                    _fmt(row["end_to_end_latency_ms"]["mean"]),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "### Holm-adjusted paired secondary tests",
            "",
            "| Comparison | n | Unadjusted p | Holm-adjusted p |",
            "|:---|---:|---:|---:|",
        ]
    )
    for row in frozen["rq_p2_holm_secondary_tests"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    row["comparison_id"],
                    str(row["query_count"]),
                    _fmt(row["unadjusted_p_value"], digits=4),
                    _fmt(row["holm_adjusted_p_value"], digits=4),
                )
            )
            + " |"
        )
    prediction = frozen["rq_p2_prediction_diagnostics"]
    lines.extend(
        [
            "",
            "### Prediction diagnostics",
            "",
            f"- Latency prediction MAE: {_fmt(prediction['latency_absolute_error_ms']['mean'])} ms",
            f"- Byte prediction MAE: {_fmt(prediction['bytes_absolute_error']['mean'])}",
            f"- Predicted/observed frontier mean Jaccard: {_fmt(prediction['mean_frontier_jaccard'])}",
            "",
            "## RQ-P3: held-out-family cold start (descriptive)",
            "",
            "| Method | n | Winner accuracy | Mean latency regret (ms) | Mean E2E latency (ms) |",
            "|:---|---:|---:|---:|---:|",
        ]
    )
    for row in frozen["rq_p3_cold_start_method_table"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    row["method_label"],
                    str(row["query_count"]),
                    _fmt(row["physical_winner_accuracy"]),
                    _fmt(row["latency_regret_ms"]["mean"]),
                    _fmt(row["end_to_end_latency_ms"]["mean"]),
                )
            )
            + " |"
        )
    accounting = frozen["resource_and_failure_accounting"]
    lines.extend(
        [
            "",
            "## Execution accounting",
            "",
            f"- Plan runs: {accounting['total_plan_runs']}",
            f"- Maximum backend calls: {accounting['maximum_backend_calls']}",
            f"- Query timeouts: {accounting['query_timeout_count']}",
            f"- Infrastructure replacements: {accounting['infrastructure_replacement_count']}",
            "- Automatic retries: 0",
            "- Missing measurements: no imputation",
            "- Offline training cost is reported separately from the primary end-to-end estimand.",
            "",
            "## Claim boundary",
            "",
            "This admitted result supports the real heterogeneous FinBench physical-optimization comparison. The cold F3 family is descriptive and is not labeled family memory. This report does not establish semantic-ambiguity, ontology, or general KGQA effectiveness.",
            "",
        ]
    )
    return "\n".join(lines)


def _read(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FinBenchConfirmatoryPaperReportError(
            f"{name} must be a regular non-symbolic-link file"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryPaperReportError(f"{name} must be an object")
    return copy.deepcopy(dict(value))


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise FinBenchConfirmatoryPaperReportError(
                f"campaign tree contains a symbolic link: {path}"
            )
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _write_pair(*, json_path: Path, markdown_path: Path, report: Mapping[str, Any]) -> None:
    if json_path.resolve() == markdown_path.resolve():
        raise FinBenchConfirmatoryPaperReportError(
            "JSON and Markdown outputs must be different files"
        )
    for path in (json_path, markdown_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"output exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        json_path: json.dumps(
            report,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        markdown_path: render_finbench_confirmatory_paper_markdown(report),
    }
    temporary: dict[Path, Path] = {}
    try:
        for path, text in values.items():
            candidate = path.with_name(path.name + f".partial-{os.getpid()}")
            candidate.write_text(text, encoding="utf-8")
            temporary[path] = candidate
        for path, candidate in temporary.items():
            os.replace(candidate, path)
    finally:
        for candidate in temporary.values():
            if candidate.exists():
                candidate.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--campaign-audit", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-markdown", required=True)
    args = parser.parse_args(argv)
    try:
        root = Path(args.campaign_root)
        if root.is_symlink() or not root.is_dir():
            raise FinBenchConfirmatoryPaperReportError(
                "campaign root is missing or unsafe"
            )
        root = root.resolve()
        outputs = (Path(args.output_json).resolve(), Path(args.output_markdown).resolve())
        if any(path == root or root in path.parents for path in outputs):
            raise FinBenchConfirmatoryPaperReportError(
                "paper outputs must remain outside the immutable campaign tree"
            )
        before = _tree_digest(root)
        report = build_finbench_confirmatory_paper_report(
            campaign_audit=_read(Path(args.campaign_audit), name="campaign audit"),
            campaign_result=_read(
                root / "campaign_result.json", name="campaign result"
            ),
            oracle_gate=_read(root / "oracle_gate.json", name="oracle gate"),
            source_campaign_tree_sha256=before,
        )
        after = _tree_digest(root)
        if after != before:
            raise FinBenchConfirmatoryPaperReportError(
                "source campaign tree changed during report construction"
            )
        _write_pair(
            json_path=outputs[0], markdown_path=outputs[1], report=report
        )
    except (
        FileExistsError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "success",
                "report_sha256": report["report_sha256"],
                "output_json": str(outputs[0]),
                "output_markdown": str(outputs[1]),
                "paper_result": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
