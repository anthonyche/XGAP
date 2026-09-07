from __future__ import annotations

import copy

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_analysis import (
    FinBenchConfirmatoryAnalysisError,
    analyze_finbench_confirmatory_measurement_ledger,
    build_finbench_confirmatory_family_selection_seal,
    build_finbench_confirmatory_measurement_ledger,
    build_finbench_confirmatory_profile_selection_seal,
)
from xgap.experiments.m15_finbench_confirmatory_crossfit import (
    FINBENCH_CONFIRMATORY_CROSSFIT_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_schedule import (
    FINBENCH_CONFIRMATORY_SCHEDULE_SCHEMA_VERSION,
)


FAMILIES = (
    "f1_direct_transfer_control",
    "f2_temporal_path_control",
    "f3_aggregate_risk_ranking",
)
STRATEGIES = {
    FAMILIES[0]: ("graph_first_hash", "control_first_bind"),
    FAMILIES[1]: ("path_first_hash", "control_first_bound_path"),
    FAMILIES[2]: ("aggregate_first_hash", "control_first_bound_aggregate"),
}


def _record(
    *, phase: str, block: int, query_id: str, family_id: str, strategy: str
) -> dict[str, object]:
    return {
        "phase": phase,
        "measurement_block_id": f"{phase}-block-{block:02d}",
        "block_index": block,
        "query_id": query_id,
        "family_id": family_id,
        "evaluation_fold_id": (
            ((int(query_id[-2:]) - 1) % 4) + 1 if family_id != FAMILIES[2] else None
        ),
        "evaluation_stratum": (
            "crossfit_seen_family" if family_id != FAMILIES[2] else "heldout_family"
        ),
        "physical_strategy": strategy,
        "query_position": int(query_id[-2:]),
        "order_position": 1 if strategy == STRATEGIES[family_id][0] else 2,
        "selection_input": phase != "postselection_shadow_evaluation",
        "current_query_profile": phase == "current_query_profile_acquisition",
        "memory_write_allowed": phase == "crossfit_training_measurement",
        "oracle_inputs": [],
        "run_id": f"{phase}:{block}:{query_id}:{strategy}",
    }


def _fixture() -> tuple[dict, dict, list[dict]]:
    query_family = {
        f"q{index:02d}": FAMILIES[(index - 1) // 16] for index in range(1, 49)
    }
    seen = [query_id for query_id, family in query_family.items() if family != FAMILIES[2]]
    cold = [query_id for query_id, family in query_family.items() if family == FAMILIES[2]]
    training = [
        _record(
            phase="crossfit_training_measurement",
            block=block,
            query_id=query_id,
            family_id=query_family[query_id],
            strategy=strategy,
        )
        for block in range(1, 8)
        for query_id in seen
        for strategy in STRATEGIES[query_family[query_id]]
    ]
    profiles = [
        _record(
            phase="current_query_profile_acquisition",
            block=1,
            query_id=query_id,
            family_id=family,
            strategy=strategy,
        )
        for query_id, family in query_family.items()
        for strategy in STRATEGIES[family]
    ]
    shadows = [
        _record(
            phase="postselection_shadow_evaluation",
            block=block,
            query_id=query_id,
            family_id=family,
            strategy=strategy,
        )
        for block in range(1, 8)
        for query_id, family in query_family.items()
        for strategy in STRATEGIES[family]
    ]
    slots = []
    for block in range(1, 8):
        for query_id, family in query_family.items():
            family_method = (
                "family_memory_zero_profile"
                if family != FAMILIES[2]
                else "predeclared_family_fallback"
            )
            for position, method_id in enumerate(
                (family_method, "current_query_dual_profile"), start=1
            ):
                slots.append(
                    {
                        "phase": "paired_selected_serving",
                        "measurement_block_id": f"paired_selected_serving-block-{block:02d}",
                        "block_index": block,
                        "query_id": query_id,
                        "family_id": family,
                        "evaluation_fold_id": (
                            ((int(query_id[-2:]) - 1) % 4) + 1
                            if family != FAMILIES[2]
                            else None
                        ),
                        "evaluation_stratum": (
                            "crossfit_seen_family"
                            if family != FAMILIES[2]
                            else "heldout_family"
                        ),
                        "method_id": method_id,
                        "physical_strategy": None,
                        "query_position": int(query_id[-2:]),
                        "order_position": position,
                        "selection_input": False,
                        "current_query_profile": False,
                        "memory_write_allowed": False,
                        "oracle_inputs": [],
                        "slot_id": f"serving:{block}:{query_id}:{method_id}",
                    }
                )
    schedule = {
        "schema_version": FINBENCH_CONFIRMATORY_SCHEDULE_SCHEMA_VERSION,
        "workload_sha256": "a" * 64,
        "query_ids": sorted(query_family),
        "seen_family_query_ids": seen,
        "cold_family_query_ids": cold,
        "crossfit_training_runs": training,
        "profile_acquisition_runs": profiles,
        "selected_serving_slots": slots,
        "evaluation_shadow_runs": shadows,
        "measurement_block_ids": sorted(
            {
                item["measurement_block_id"]
                for item in training + profiles + slots + shadows
            }
        ),
        "measurement_block_count": 22,
        "expected_counts": {
            "seen_family_query_count": 32,
            "cold_family_query_count": 16,
            "inferential_query_count": 32,
            "training_plan_runs": 448,
            "profile_acquisition_plan_runs": 96,
            "selected_serving_plan_runs": 672,
            "evaluation_shadow_plan_runs": 672,
            "total_plan_runs": 1888,
            "total_backend_calls": 3776,
        },
        "execution_contract": {
            "backend_timeout_seconds": 60,
            "automatic_retries": 0,
            "infrastructure_replacement_limit": 1,
            "query_timeout_is_method_outcome": True,
            "query_timeout_is_not_replacement_eligible": True,
        },
        "query_instance_is_inferential_unit": True,
        "repetitions_are_not_independent_units": True,
        "current_query_profile_calls_for_family_memory": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    schedule["schedule_sha256"] = content_hash(schedule)
    predictions = []
    for query_id, family in query_family.items():
        strategies = STRATEGIES[family]
        selected = strategies[int(query_id[-2:]) % 2]
        if family != FAMILIES[2]:
            item = {
                "query_id": query_id,
                "family_id": family,
                "evaluation_fold_id": ((int(query_id[-2:]) - 1) % 4) + 1,
                "evaluation_stratum": "crossfit_seen_family",
                "selection_source": "crossfit_family_memory_knn",
                "selected_physical_strategy": selected,
                "predicted_physical_frontier": [selected],
                "strategy_predictions": [
                    {
                        "physical_strategy": strategy,
                        "predicted_elapsed_ms": 10.0 + offset * 5.0,
                        "predicted_total_bytes_moved": 1000.0 + offset * 500.0,
                    }
                    for offset, strategy in enumerate(strategies)
                ],
                "current_query_profile_calls": 0,
                "own_query_observation_used": False,
            }
        else:
            item = {
                "query_id": query_id,
                "family_id": family,
                "evaluation_fold_id": None,
                "evaluation_stratum": "heldout_family_cold_start",
                "selection_source": "predeclared_cold_start_fallback",
                "selected_physical_strategy": strategies[0],
                "predicted_physical_frontier": [],
                "strategy_predictions": [],
                "current_query_profile_calls": 0,
                "own_query_observation_used": False,
            }
        item["prediction_sha256"] = content_hash(item)
        predictions.append(item)
    suite = {
        "schema_version": FINBENCH_CONFIRMATORY_CROSSFIT_SCHEMA_VERSION,
        "workload_sha256": "a" * 64,
        "prediction_count": 48,
        "seen_family_prediction_count": 32,
        "cold_family_prediction_count": 16,
        "predictions": predictions,
        "current_query_profile_calls": 0,
        "current_query_measurements_used_for_own_prediction": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    suite["crossfit_prediction_suite_sha256"] = content_hash(suite)
    measurements = []
    for record in training + profiles + slots + shadows:
        identity = str(record.get("run_id") or record.get("slot_id"))
        query_number = int(record["query_id"][-2:])
        if record["physical_strategy"] is None:
            base = 12.0 if record["method_id"] != "current_query_dual_profile" else 11.0
        else:
            first = record["physical_strategy"] == STRATEGIES[record["family_id"]][0]
            base = 10.0 if first == (query_number % 2 == 0) else 20.0
        measurements.append(
            {
                "scheduled_identity": identity,
                "attempt_id": f"attempt:{record['measurement_block_id']}",
                "outcome": "success",
                "elapsed_ms": base + record["block_index"] / 10.0,
                "total_bytes_moved": 1000 + (0 if base < 15 else 500),
                "total_remote_calls": 2,
                "exact_answer": True,
                "physical_strategy": (
                    record["physical_strategy"]
                    if record["physical_strategy"] is not None
                    else (
                        (
                            STRATEGIES[record["family_id"]][0]
                            if record["family_id"] == FAMILIES[2]
                            else STRATEGIES[record["family_id"]][int(record["query_id"][-2:]) % 2]
                        )
                        if record["method_id"] != "current_query_dual_profile"
                        else STRATEGIES[record["family_id"]][0]
                    )
                ),
            }
        )
    return schedule, suite, measurements


def _ledger() -> tuple[dict, dict, dict, list[dict]]:
    schedule, suite, measurements = _fixture()
    family = build_finbench_confirmatory_family_selection_seal(
        schedule=schedule, crossfit_prediction_suite=suite
    )
    profile_ids = {item["run_id"] for item in schedule["profile_acquisition_runs"]}
    profile_measurements = [
        item for item in measurements if item["scheduled_identity"] in profile_ids
    ]
    profile = build_finbench_confirmatory_profile_selection_seal(
        schedule=schedule, profile_measurements=profile_measurements
    )
    profile_choices = {
        item["query_id"]: item["selected_physical_strategy"]
        for item in profile["selections"]
    }
    for item in measurements:
        if ":current_query_dual_profile" in item["scheduled_identity"]:
            query_id = item["scheduled_identity"].split(":")[2]
            item["physical_strategy"] = profile_choices[query_id]
    counts: dict[str, int] = {}
    for record in (
        schedule["crossfit_training_runs"]
        + schedule["profile_acquisition_runs"]
        + schedule["selected_serving_slots"]
        + schedule["evaluation_shadow_runs"]
    ):
        block = record["measurement_block_id"]
        counts[block] = counts.get(block, 0) + 1
    attempts = [
        {
            "attempt_id": f"attempt:{block}",
            "measurement_block_id": block,
            "attempt_index": 1,
            "status": "completed",
            "valid_measurement_count": count,
            "replacement_of_attempt_id": None,
            "failure_category": None,
        }
        for block, count in sorted(counts.items())
    ]
    ledger = build_finbench_confirmatory_measurement_ledger(
        schedule=schedule,
        crossfit_prediction_suite=suite,
        family_selection_seal=family,
        profile_selection_seal=profile,
        measurements=measurements,
        infrastructure_attempts=attempts,
    ).to_dict()
    return ledger, schedule, suite, measurements


def test_confirmatory_analysis_uses_32_queries_not_repetitions() -> None:
    ledger, _, _, _ = _ledger()
    first = analyze_finbench_confirmatory_measurement_ledger(ledger)
    second = analyze_finbench_confirmatory_measurement_ledger(ledger)

    assert first == second
    assert first["primary"]["inferential_query_count"] == 32
    assert first["primary"]["repetition_count_as_independent_n"] == 0
    assert first["primary"]["confidence_interval"]["resamples"] == 10_000
    assert first["primary"]["randomization_test"]["draws"] == 100_000
    assert first["cold_start"]["query_count"] == 16
    assert first["cold_start"]["family_memory_label_used"] is False
    assert first["offline_training_cost"]["plan_runs"] == 448
    assert first["confirmatory_statistics"] is True
    assert first["paper_result"] is False


def test_query_timeout_is_retained_and_bytes_are_not_imputed() -> None:
    source_ledger, schedule, suite, measurements = _ledger()
    changed = copy.deepcopy(measurements)
    target = next(
        item
        for item in changed
        if item["scheduled_identity"].startswith("serving:1:q01:family_memory")
    )
    target.update(
        {
            "outcome": "query_timeout",
            "elapsed_ms": 60_007.0,
            "total_bytes_moved": None,
            "total_remote_calls": 1,
            "exact_answer": None,
        }
    )
    family = build_finbench_confirmatory_family_selection_seal(
        schedule=schedule, crossfit_prediction_suite=suite
    )
    profile_ids = {item["run_id"] for item in schedule["profile_acquisition_runs"]}
    profile = build_finbench_confirmatory_profile_selection_seal(
        schedule=schedule,
        profile_measurements=[
            item for item in changed if item["scheduled_identity"] in profile_ids
        ],
    )
    attempts = copy.deepcopy(source_ledger["infrastructure_attempts"])
    ledger = build_finbench_confirmatory_measurement_ledger(
        schedule=schedule,
        crossfit_prediction_suite=suite,
        family_selection_seal=family,
        profile_selection_seal=profile,
        measurements=changed,
        infrastructure_attempts=attempts,
    ).to_dict()
    result = analyze_finbench_confirmatory_measurement_ledger(ledger)

    assert ledger["query_timeout_count"] == 1
    assert result["failure_accounting"]["query_timeout_count"] == 1
    assert result["failure_accounting"]["query_timeouts_retained_as_method_outcomes"] is True
    assert result["failure_accounting"]["missing_measurements"] == "no_imputation"


def test_infrastructure_failure_cannot_replace_a_valid_measurement() -> None:
    ledger, schedule, suite, measurements = _ledger()
    family = build_finbench_confirmatory_family_selection_seal(
        schedule=schedule, crossfit_prediction_suite=suite
    )
    profile_ids = {item["run_id"] for item in schedule["profile_acquisition_runs"]}
    profile = build_finbench_confirmatory_profile_selection_seal(
        schedule=schedule,
        profile_measurements=[
            item for item in measurements if item["scheduled_identity"] in profile_ids
        ],
    )
    block = schedule["measurement_block_ids"][0]
    with pytest.raises(
        FinBenchConfirmatoryAnalysisError, match="contains a valid measurement"
    ):
        build_finbench_confirmatory_measurement_ledger(
            schedule=schedule,
            crossfit_prediction_suite=suite,
            family_selection_seal=family,
            profile_selection_seal=profile,
            measurements=measurements,
            infrastructure_attempts=[
                {
                    "attempt_id": "failed-attempt",
                    "measurement_block_id": block,
                    "attempt_index": 1,
                    "status": "infrastructure_failed",
                    "valid_measurement_count": 1,
                    "replacement_of_attempt_id": None,
                    "failure_category": "node_failure",
                }
            ]
            + [
                item
                for item in ledger["infrastructure_attempts"]
                if item["measurement_block_id"] != block
            ],
        )
    assert ledger["infrastructure_replacement_count"] == 0


def test_schedule_and_ledger_tampering_fail_closed() -> None:
    ledger, schedule, suite, _ = _ledger()
    tampered_schedule = copy.deepcopy(schedule)
    tampered_schedule["seen_family_query_ids"][0] = "wrong"
    with pytest.raises(FinBenchConfirmatoryAnalysisError, match="hash mismatch"):
        build_finbench_confirmatory_family_selection_seal(
            schedule=tampered_schedule, crossfit_prediction_suite=suite
        )

    tampered_ledger = copy.deepcopy(ledger)
    tampered_ledger["measurements"][0]["analysis_elapsed_ms"] += 1.0
    with pytest.raises(FinBenchConfirmatoryAnalysisError, match="hash mismatch"):
        analyze_finbench_confirmatory_measurement_ledger(tampered_ledger)
