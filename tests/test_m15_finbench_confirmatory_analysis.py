from __future__ import annotations

import copy
import json
from pathlib import Path

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
from xgap.experiments.m15_finbench_confirmatory_block_evidence import (
    audit_finbench_confirmatory_block,
)
from xgap.experiments.m15_finbench_confirmatory_schedule import (
    FINBENCH_CONFIRMATORY_SCHEDULE_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_execution import (
    FinBenchConfirmatoryExecutionError,
    build_finbench_confirmatory_execution_authority,
    build_finbench_confirmatory_execution_request,
    build_finbench_confirmatory_block_execution_envelope,
    compile_finbench_confirmatory_block_attempt,
    validate_finbench_confirmatory_block_execution_envelope,
)
from xgap.experiments.m15_finbench_confirmatory_freeze_evidence import (
    FINBENCH_CONFIRMATORY_FREEZE_AUDIT_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_freeze_job import (
    FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_phase import (
    build_finbench_confirmatory_accepted_block,
    build_finbench_confirmatory_failed_attempt_bundle,
    extract_finbench_confirmatory_training_observations,
)
from xgap.experiments.m15_finbench_confirmatory_selection_admission import (
    FINBENCH_CONFIRMATORY_SELECTION_ADMISSION_SCHEMA_VERSION,
)
from xgap.experiments import m15_live_finbench_confirmatory_block as live_block
from xgap.experiments import m15_finbench_confirmatory_oracle as oracle_gate
from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.runtime import (
    FederatedExecutionPlan,
    FederatedPlanCandidate,
    RuntimeNode,
    RuntimeNodeKind,
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
TIMEOUT_POLICY = {
    "method_timeout_seconds": 60.0,
    "transport_timeout_seconds": 65.0,
    "neo4j": {
        "setting": "db.transaction.timeout",
        "value": "60s",
        "monitor_check_interval": "1s",
    },
    "fuseki": {
        "setting": "arq:queryTimeout",
        "value_milliseconds": 60000,
        "configuration": "FUSEKI_BASE/config.ttl",
    },
    "timeout_is_method_outcome": True,
    "automatic_retries": 0,
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
        "selection_admission_sha256": "f" * 64,
        "training_exactness_semantics": (
            "plan_family_semantic_contract_not_current_query_oracle"
        ),
        "current_confirmatory_query_oracle_opened": False,
        "final_confirmatory_oracle_is_authoritative": True,
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
        schedule=schedule,
        profile_measurements=profile_measurements,
        allow_opened_oracle_reconstruction=True,
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


def _execution_boundary(schedule: dict) -> tuple[dict, dict, dict, dict]:
    manifest = {
        "schema_version": FINBENCH_CONFIRMATORY_FREEZE_MANIFEST_SCHEMA_VERSION,
        "status": "success",
        "git": {"commit": "a" * 40, "clean": True},
        "expected_counts": schedule["expected_counts"],
        "schedule_sha256": schedule["schedule_sha256"],
        "workload_sha256": schedule["workload_sha256"],
        "author_selection_sha256": "b" * 64,
        "population_approval_sha256": "c" * 64,
        "external_call_counts": {
            "backend_calls": 0,
            "current_query_profile_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        },
        "confirmatory_workload_compilation_authorized": True,
        "confirmatory_execution_authorized": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    manifest["manifest_sha256"] = content_hash(manifest)
    checks = [
        {
            "check_id": f"check-{index:02d}",
            "passed": True,
            "expected": True,
            "observed": True,
        }
        for index in range(44)
    ]
    audit = {
        "schema_version": FINBENCH_CONFIRMATORY_FREEZE_AUDIT_SCHEMA_VERSION,
        "success": True,
        "run_root": "/sealed/freeze",
        "expected_commit": "a" * 40,
        "check_count": 44,
        "failed_check_ids": [],
        "checks": checks,
        "run_tree_mutated": False,
    }
    admission = {
        "schema_version": (
            FINBENCH_CONFIRMATORY_SELECTION_ADMISSION_SCHEMA_VERSION
        ),
        "confirmatory_workload_sha256": schedule["workload_sha256"],
        "source_archive_sha256": "e" * 64,
        "admitted_family_ids": list(FAMILIES[:2]),
        "seen_family_semantic_contract": {
            FAMILIES[0]: {
                "physical_strategies": list(STRATEGIES[FAMILIES[0]]),
                "hard_constraints": [
                    "person_id",
                    "inclusive_time_window",
                    "company_account_ownership",
                    "destination_account_is_blocked_true",
                    "transfer_direction",
                    "sum_amount_by_company_and_account",
                    "output_schema",
                ],
            },
            FAMILIES[1]: {
                "physical_strategies": list(STRATEGIES[FAMILIES[1]]),
                "hard_constraints": [
                    "start_account_id",
                    "inclusive_time_window",
                    "transfer_direction",
                    "strictly_increasing_transfer_timestamps",
                    "cycle_free_account_path",
                    "max_hops_3",
                    "medium_is_blocked_true",
                    "output_schema",
                ],
            },
        },
        "development_correctness_evidence": {
            "producer_commit": "f" * 40,
            "correctness_workload_sha256": "1" * 64,
            "correctness_manifest_sha256": "2" * 64,
            "correctness_audit_content_sha256": "3" * 64,
            "correctness_receipt_file_sha256": "4" * 64,
            "audit_success": True,
            "audit_failed_check_ids": [],
            "run_tree_mutated": False,
            "all_plans_exact": True,
            "all_physical_pairs_equivalent": True,
        },
        "training_cost_outcome_admission": (
            "successful_contract_bound_runs_only"
        ),
        "training_exactness_semantics": (
            "plan_family_semantic_contract_not_current_query_oracle"
        ),
        "current_confirmatory_query_oracle_opened": False,
        "final_confirmatory_oracle_is_authoritative": True,
        "current_query_profile_calls": 0,
        "backend_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    admission["selection_admission_sha256"] = content_hash(admission)
    request = build_finbench_confirmatory_execution_request(
        freeze_manifest=manifest,
        freeze_audit=audit,
        selection_admission=admission,
        runner_commit="d" * 40,
    )
    authority = build_finbench_confirmatory_execution_authority(
        execution_request=request,
        authority_source_id="author:test:confirmatory-v1",
        decision="authorize_exact_confirmatory_execution",
    )
    return manifest, audit, request, authority


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


def test_profile_selection_is_sealed_without_current_answer_oracle() -> None:
    schedule, _, measurements = _fixture()
    profile_ids = {
        item["run_id"] for item in schedule["profile_acquisition_runs"]
    }
    preoracle = [
        {**item, "exact_answer": None}
        for item in measurements
        if item["scheduled_identity"] in profile_ids
    ]

    seal = build_finbench_confirmatory_profile_selection_seal(
        schedule=schedule,
        profile_measurements=preoracle,
    )

    assert seal["selection_count"] == 48
    assert seal["current_confirmatory_query_oracle_opened"] is False
    assert seal["final_confirmatory_oracle_is_authoritative"] is True
    with pytest.raises(
        FinBenchConfirmatoryAnalysisError,
        match="opened the current confirmatory oracle",
    ):
        build_finbench_confirmatory_profile_selection_seal(
            schedule=schedule,
            profile_measurements=[
                item
                for item in measurements
                if item["scheduled_identity"] in profile_ids
            ],
        )


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
        allow_opened_oracle_reconstruction=True,
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


def test_delayed_oracle_stays_closed_until_all_blocks_are_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule, _, _ = _fixture()
    opened = False

    def forbidden_oracle_open(_root: object) -> dict:
        nonlocal opened
        opened = True
        raise AssertionError("answer oracle opened before block completeness")

    monkeypatch.setattr(
        oracle_gate,
        "validate_finbench_confirmatory_selection_admission",
        lambda value, *, workload_sha256: dict(value),
    )
    monkeypatch.setattr(
        oracle_gate, "load_finbench_primary_workload", forbidden_oracle_open
    )

    with pytest.raises(ValueError, match="does not cover its frozen measurement blocks"):
        oracle_gate.open_finbench_confirmatory_oracle(
            workload_root="/sealed/workload",
            schedule=schedule,
            selection_admission={"selection_admission_sha256": "f" * 64},
            accepted_blocks=[],
            training_phase={},
            profile_phase={},
        )

    assert opened is False


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
        allow_opened_oracle_reconstruction=True,
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


def test_execution_authority_is_separate_from_population_selection() -> None:
    schedule, _, _ = _fixture()
    manifest, audit, request, authority = _execution_boundary(schedule)

    assert request["confirmatory_execution_authorized"] is False
    assert request["execution_scope"]["total_plan_runs"] == 1888
    assert request["execution_scope"]["maximum_backend_calls"] == 3776
    assert authority["confirmatory_execution_authorized"] is True
    assert authority["execution_request_sha256"] == request["execution_request_sha256"]

    changed_audit = copy.deepcopy(audit)
    changed_audit["checks"][0]["passed"] = False
    with pytest.raises(
        FinBenchConfirmatoryExecutionError,
        match="independent freeze audit is not accepted",
    ):
        build_finbench_confirmatory_execution_request(
            freeze_manifest=manifest,
            freeze_audit=changed_audit,
            selection_admission={
                **request,
            },
            runner_commit="d" * 40,
        )
    with pytest.raises(FinBenchConfirmatoryExecutionError, match="does not authorize"):
        build_finbench_confirmatory_execution_authority(
            execution_request=request,
            authority_source_id="author:test:confirmatory-v1",
            decision="select_population_option_a",
        )


def test_block_attempt_resolves_only_its_frozen_measurements() -> None:
    schedule, suite, measurements = _fixture()
    _, _, request, authority = _execution_boundary(schedule)
    family = build_finbench_confirmatory_family_selection_seal(
        schedule=schedule, crossfit_prediction_suite=suite
    )
    profile_ids = {item["run_id"] for item in schedule["profile_acquisition_runs"]}
    profile = build_finbench_confirmatory_profile_selection_seal(
        schedule=schedule,
        profile_measurements=[
            item for item in measurements if item["scheduled_identity"] in profile_ids
        ],
        allow_opened_oracle_reconstruction=True,
    )

    training = compile_finbench_confirmatory_block_attempt(
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
        measurement_block_id="crossfit_training_measurement-block-01",
    )
    assert training["phase"] == "crossfit_training_measurement"
    assert training["expected_plan_run_count"] == 64
    assert training["maximum_backend_calls"] == 128
    assert all(item["method_id"] is None for item in training["measurements"])

    with pytest.raises(
        FinBenchConfirmatoryExecutionError, match="requires both pre-execution"
    ):
        compile_finbench_confirmatory_block_attempt(
            schedule=schedule,
            execution_request=request,
            execution_authority=authority,
            measurement_block_id="paired_selected_serving-block-01",
        )

    serving = compile_finbench_confirmatory_block_attempt(
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
        measurement_block_id="paired_selected_serving-block-01",
        family_selection_seal=family,
        profile_selection_seal=profile,
    )
    family_choices = {
        item["query_id"]: item["selected_physical_strategy"]
        for item in family["selections"]
    }
    profile_choices = {
        item["query_id"]: item["selected_physical_strategy"]
        for item in profile["selections"]
    }
    assert serving["expected_plan_run_count"] == 96
    assert all(item["physical_strategy"] for item in serving["measurements"])
    assert {
        item["physical_strategy"]
        for item in serving["measurements"]
        if item["query_id"] == "q01"
    } == {family_choices["q01"], profile_choices["q01"]}

    envelope = build_finbench_confirmatory_block_execution_envelope(
        block_attempt=training,
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
    )
    forged = copy.deepcopy(envelope)
    forged_attempt = forged["block_attempt"]
    forged_attempt["measurements"][0]["query_id"] = "q02"
    attempt_identity = {
        key: value
        for key, value in forged_attempt.items()
        if key not in {"attempt_id", "block_attempt_sha256"}
    }
    forged_attempt["attempt_id"] = (
        "finbench-confirmatory-attempt-"
        + content_hash(attempt_identity)[:24]
    )
    forged_attempt["block_attempt_sha256"] = content_hash(
        {
            key: value
            for key, value in forged_attempt.items()
            if key != "block_attempt_sha256"
        }
    )
    forged["execution_context_sha256"] = content_hash(
        {
            key: value
            for key, value in forged.items()
            if key != "execution_context_sha256"
        }
    )
    with pytest.raises(
        FinBenchConfirmatoryExecutionError,
        match="exact authorized schedule projection",
    ):
        validate_finbench_confirmatory_block_execution_envelope(forged)


def test_replacement_attempt_requires_explicit_provenance() -> None:
    schedule, _, _ = _fixture()
    _, _, request, authority = _execution_boundary(schedule)
    with pytest.raises(FinBenchConfirmatoryExecutionError, match="provenance"):
        compile_finbench_confirmatory_block_attempt(
            schedule=schedule,
            execution_request=request,
            execution_authority=authority,
            measurement_block_id="crossfit_training_measurement-block-01",
            attempt_index=2,
        )
    replacement = compile_finbench_confirmatory_block_attempt(
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
        measurement_block_id="crossfit_training_measurement-block-01",
        attempt_index=2,
        replacement_of_attempt_id="finbench-confirmatory-attempt-original",
    )
    assert replacement["attempt_index"] == 2
    assert replacement["replacement_of_attempt_id"].endswith("original")


def test_live_block_retains_timeout_without_retry_or_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schedule, _, _ = _fixture()
    _, _, request, authority = _execution_boundary(schedule)
    attempt = compile_finbench_confirmatory_block_attempt(
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
        measurement_block_id="crossfit_training_measurement-block-01",
    )
    execution_context = build_finbench_confirmatory_block_execution_envelope(
        block_attempt=attempt,
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
    )
    partition_root = tmp_path / "partition"
    partition_root.mkdir()
    (partition_root / "load_neo4j_batches.jsonl").write_text("{}\n")
    (partition_root / "load_fuseki.ttl").write_text("# fixture\n")
    monkeypatch.setattr(
        live_block,
        "load_finbench_source_partition",
        lambda _root: {
            "partition_sha256": "e" * 64,
            "source_archive": {"sha256": "f" * 64},
            "neo4j_load": {"filename": "load_neo4j_batches.jsonl"},
        },
    )
    monkeypatch.setattr(
        live_block,
        "load_finbench_primary_public_workload",
        lambda _root: {
            "manifest": {
                "workload_sha256": schedule["workload_sha256"],
                "source_archive_sha256": "f" * 64,
            }
        },
    )
    monkeypatch.setattr(
        live_block, "_git_state", lambda _root: {"commit": "d" * 40, "clean": True}
    )

    def candidates(_root: object, *, query_id: str):
        family = FAMILIES[0] if int(query_id[-2:]) <= 16 else FAMILIES[1]
        values = []
        for strategy in STRATEGIES[family]:
            plan = FederatedExecutionPlan(
                plan_id=f"{query_id}-{strategy}",
                nodes=(
                    RuntimeNode(
                        "remote",
                        RuntimeNodeKind.REMOTE_QUERY,
                        parameters={
                            "backend_id": "neo4j",
                            "artifact": {
                                "artifact_id": f"{query_id}-{strategy}",
                                "language": "cypher",
                                "text": "RETURN 1",
                            },
                        },
                    ),
                ),
                roots=("remote",),
                metadata={
                    "physical_strategy": strategy,
                    "workload_sha256": schedule["workload_sha256"],
                },
            )
            values.append(FederatedPlanCandidate(plan, f"{query_id}:exact"))
        return tuple(values)

    monkeypatch.setattr(live_block, "build_finbench_plan_candidates", candidates)
    monkeypatch.setattr(
        live_block, "canonicalize_finbench_rows", lambda _family, rows: list(rows)
    )

    class Result:
        def __init__(self, *, timeout: bool):
            self.success = not timeout
            self.elapsed_ms = 60_003.0 if timeout else 3.0
            self.total_remote_calls = 1 if timeout else 2
            self.total_bytes_moved = 0 if timeout else 17
            self.final_rows = () if timeout else ({"ok": True},)
            self._timeout = timeout

        def to_dict(self):
            return {
                "success": self.success,
                "elapsed_ms": self.elapsed_ms,
                "total_remote_calls": self.total_remote_calls,
                "total_bytes_moved": self.total_bytes_moved,
                "final_rows": list(self.final_rows),
                "node_results": [
                    {
                        "status": "error" if self._timeout else "success",
                        "error": "timed out" if self._timeout else None,
                    }
                ],
            }

    class Scheduler:
        calls = 0

        def __init__(self, _tool):
            pass

        def execute(self, _plan, *, goal_id: str):
            del goal_id
            type(self).calls += 1
            return Result(timeout=type(self).calls == 1)

    monkeypatch.setattr(live_block, "FederatedScheduler", Scheduler)

    class Loader:
        def __init__(self, backend_id: str):
            self.backend_id = backend_id

        def load(self, path: Path):
            return BackendLoadReport(
                backend_id=self.backend_id,
                success=True,
                operations_attempted=1,
                bytes_sent=path.stat().st_size,
                elapsed_ms=1.0,
            )

    record = live_block.run_m15_live_finbench_confirmatory_block(
        execution_context=execution_context,
        workload_root=tmp_path / "workload",
        partition_root=partition_root,
        clients={"neo4j": object(), "fuseki": object()},
        loaders={
            "neo4j": Loader("neo4j"),
            "fuseki": Loader("fuseki"),
        },
        output_root=tmp_path / "runs",
        query_timeout_policy=TIMEOUT_POLICY,
        repo_root=tmp_path,
    )

    assert record.success is True
    assert record.replacement_eligible is False
    raw = json.loads((record.run_root / "raw_measurements.json").read_text())
    manifest = json.loads(record.manifest_path.read_text())
    assert raw["measurement_count"] == 64
    assert raw["query_timeout_count"] == 1
    assert raw["measurements"][0]["outcome"] == "query_timeout"
    assert raw["measurements"][0]["total_bytes_moved"] is None
    assert raw["measurements"][0]["exact_answer"] is None
    assert manifest["oracle_content_parsed"] is False
    assert manifest["automatic_retries"] == 0
    assert Scheduler.calls == 64
    audit = audit_finbench_confirmatory_block(
        attempt_root=record.run_root,
        execution_context=execution_context,
        expected_commit="d" * 40,
    )
    assert audit.success is True
    assert audit.failed_check_ids == ()
    assert audit.run_tree_mutated is False
    assert audit.attempt_status == "completed"
    assert audit.replacement_eligible is False
    accepted = build_finbench_confirmatory_accepted_block(
        execution_context=execution_context,
        raw_measurements=raw,
        block_audit=audit.to_dict(),
    )
    assert accepted["execution_context"] == execution_context
    assert accepted["raw_measurements"] == raw
    assert accepted["prior_failed_attempts"] == []
    assert accepted["accepted_block_sha256"] == content_hash(
        {
            key: value
            for key, value in accepted.items()
            if key != "accepted_block_sha256"
        }
    )

    class FailingLoader(Loader):
        def load(self, path: Path):
            return BackendLoadReport(
                backend_id=self.backend_id,
                success=False,
                operations_attempted=1,
                bytes_sent=path.stat().st_size,
                elapsed_ms=1.0,
                error="allocation storage unavailable",
            )

    failed = live_block.run_m15_live_finbench_confirmatory_block(
        execution_context=execution_context,
        workload_root=tmp_path / "workload",
        partition_root=partition_root,
        clients={"neo4j": object(), "fuseki": object()},
        loaders={
            "neo4j": FailingLoader("neo4j"),
            "fuseki": FailingLoader("fuseki"),
        },
        output_root=tmp_path / "failed-runs",
        query_timeout_policy=TIMEOUT_POLICY,
        repo_root=tmp_path,
    )
    assert failed.success is False
    assert failed.replacement_eligible is True
    failed_raw = json.loads(
        (failed.run_root / "raw_measurements.json").read_text()
    )
    failed_audit = audit_finbench_confirmatory_block(
        attempt_root=failed.run_root,
        execution_context=execution_context,
        expected_commit="d" * 40,
    )
    assert failed_audit.success is True
    assert failed_audit.attempt_status == "infrastructure_failed"
    assert failed_audit.replacement_eligible is True
    failed_bundle = build_finbench_confirmatory_failed_attempt_bundle(
        execution_context=execution_context,
        raw_measurements=failed_raw,
        block_audit=failed_audit.to_dict(),
    )

    replacement_attempt = compile_finbench_confirmatory_block_attempt(
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
        measurement_block_id="crossfit_training_measurement-block-01",
        attempt_index=2,
        replacement_of_attempt_id=attempt["attempt_id"],
    )
    replacement_context = build_finbench_confirmatory_block_execution_envelope(
        block_attempt=replacement_attempt,
        schedule=schedule,
        execution_request=request,
        execution_authority=authority,
    )
    Scheduler.calls = 0
    replacement = live_block.run_m15_live_finbench_confirmatory_block(
        execution_context=replacement_context,
        workload_root=tmp_path / "workload",
        partition_root=partition_root,
        clients={"neo4j": object(), "fuseki": object()},
        loaders={"neo4j": Loader("neo4j"), "fuseki": Loader("fuseki")},
        output_root=tmp_path / "replacement-runs",
        query_timeout_policy=TIMEOUT_POLICY,
        repo_root=tmp_path,
    )
    replacement_raw = json.loads(
        (replacement.run_root / "raw_measurements.json").read_text()
    )
    replacement_audit = audit_finbench_confirmatory_block(
        attempt_root=replacement.run_root,
        execution_context=replacement_context,
        expected_commit="d" * 40,
    )
    accepted_replacement = build_finbench_confirmatory_accepted_block(
        execution_context=replacement_context,
        raw_measurements=replacement_raw,
        block_audit=replacement_audit.to_dict(),
        prior_failed_attempts=[failed_bundle],
    )
    assert accepted_replacement["prior_failed_attempts"] == [failed_bundle]

    with pytest.raises(ValueError, match="one prior infrastructure failure"):
        build_finbench_confirmatory_accepted_block(
            execution_context=replacement_context,
            raw_measurements=replacement_raw,
            block_audit=replacement_audit.to_dict(),
        )

    class BackendFailureResult(Result):
        def __init__(self):
            super().__init__(timeout=False)
            self.success = False

        def to_dict(self):
            body = super().to_dict()
            body["success"] = False
            body["node_results"] = [
                {"status": "error", "error": "invalid physical plan"}
            ]
            return body

    class BackendFailureScheduler:
        def __init__(self, _tool):
            pass

        def execute(self, _plan, *, goal_id: str):
            del goal_id
            return BackendFailureResult()

    monkeypatch.setattr(
        live_block, "FederatedScheduler", BackendFailureScheduler
    )
    rejected = live_block.run_m15_live_finbench_confirmatory_block(
        execution_context=execution_context,
        workload_root=tmp_path / "workload",
        partition_root=partition_root,
        clients={"neo4j": object(), "fuseki": object()},
        loaders={"neo4j": Loader("neo4j"), "fuseki": Loader("fuseki")},
        output_root=tmp_path / "backend-failure-runs",
        query_timeout_policy=TIMEOUT_POLICY,
        repo_root=tmp_path,
    )
    rejected_attempt = json.loads(
        (rejected.run_root / "attempt_record.json").read_text()
    )
    assert rejected.success is False
    assert rejected.replacement_eligible is False
    assert rejected_attempt == {
        "attempt_id": attempt["attempt_id"],
        "measurement_block_id": attempt["measurement_block_id"],
        "attempt_index": 1,
        "status": "partial_measurement_failure",
        "valid_measurement_count": 0,
        "replacement_of_attempt_id": None,
        "failure_category": "backend_or_plan_failure",
    }
    rejected_audit = audit_finbench_confirmatory_block(
        attempt_root=rejected.run_root,
        execution_context=execution_context,
        expected_commit="d" * 40,
    )
    assert rejected_audit.success is False
    assert "attempt.accepted_status" in rejected_audit.failed_check_ids


def test_training_extraction_drops_unpaired_timeout_without_imputation() -> None:
    blocks = []
    for block_index in range(1, 8):
        expected = []
        measured = []
        for position, strategy in enumerate(STRATEGIES[FAMILIES[0]], start=1):
            identity = f"train:{block_index}:q01:{strategy}"
            expected.append(
                {
                    "scheduled_identity": identity,
                    "query_id": "q01",
                    "family_id": FAMILIES[0],
                    "physical_strategy": strategy,
                    "order_position": position,
                }
            )
            timeout = block_index == 2 and position == 1
            measured.append(
                {
                    "scheduled_identity": identity,
                    "outcome": "query_timeout" if timeout else "success",
                    "elapsed_ms": 60_000.0 if timeout else 5.0,
                    "total_bytes_moved": None if timeout else 100,
                    "total_remote_calls": 1 if timeout else 2,
                }
            )
        blocks.append(
            {
                "block_id": (
                    f"crossfit_training_measurement-block-{block_index:02d}"
                ),
                "attempt": {"measurements": expected},
                "measurements": measured,
            }
        )

    observations, summary = extract_finbench_confirmatory_training_observations(
        blocks
    )

    assert len(observations) == 2
    assert {len(item["repetitions"]) for item in observations} == {6}
    assert all(
        repetition["exact_answer"] is None
        for item in observations
        for repetition in item["repetitions"]
    )
    assert summary["query_timeout_count"] == 1
    assert summary["dropped_unpaired_plan_outcomes"] == 2
    assert summary["minimum_paired_successful_blocks_per_query"] == 6
    assert summary["missing_measurements"] == "no_imputation"
