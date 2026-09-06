from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction import (
    DIRECT_FAMILY_PREDICTION_SOURCE_SCHEMA_VERSION,
    DIRECT_FAMILY_PREDICTION_SUITE_SCHEMA_VERSION,
    DIRECT_TRAINING_MEMORY_SCHEMA_VERSION,
    M15DirectFamilyPredictionError,
    M15DirectTrainingMemoryView,
    build_m15_controlled_training_observations,
    build_m15_direct_family_prediction_suite,
    build_m15_direct_training_memory_view,
)
from xgap.experiments.m15_direct_semantic_frontier import (
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
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
COMPACT_ARTIFACT = (
    REPO_ROOT
    / "experiments/artifacts/m15_f2c10b_local_family_memory_prediction_20260906.json"
)
RUNTIME_HASH = content_hash(
    {
        "runtime": "f2c10-local-controlled-runtime",
        "neo4j": "controlled",
        "fuseki": "controlled",
    }
)


def _workload(tmp_path: Path):
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "base",
    )
    direct = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        policy=CARDINALITY_POLICY,
        destination=tmp_path / "direct",
    )
    return base, direct


def _memory(tmp_path: Path):
    base, direct = _workload(tmp_path)
    controlled = build_m15_controlled_training_observations(direct)
    memory = build_m15_direct_training_memory_view(
        workload=direct,
        raw_observations=controlled["observations"],
        runtime_compatibility_sha256=RUNTIME_HASH,
        policy=PREDICTOR_POLICY,
        measurement_source_kind="controlled_local_nonmeasurement_fixture",
    )
    return base, direct, controlled, memory


def _suite(tmp_path: Path):
    base, direct, controlled, memory = _memory(tmp_path)
    suite = build_m15_direct_family_prediction_suite(
        workload=direct,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        memory=memory,
        policy=PREDICTOR_POLICY,
    )
    return base, direct, controlled, memory, suite


def test_training_memory_is_complete_raw_and_training_only(tmp_path: Path) -> None:
    _, direct, controlled, memory = _memory(tmp_path)
    payload = memory.to_dict()

    assert controlled["backend_calls_made"] == 0
    assert payload["schema_version"] == DIRECT_TRAINING_MEMORY_SCHEMA_VERSION
    assert payload["training_semantic_task_count"] == 18
    assert payload["training_physical_plan_count"] == 36
    assert len(payload["observations"]) == 36
    assert sum(item["repetition_count"] for item in payload["observations"]) == 72
    assert all(len(item["repetitions"]) == 2 for item in payload["observations"])
    training_ids = {
        item["semantic_task_id"]
        for item in direct.training_selection_view["semantic_tasks"]
    }
    heldout_ids = {
        item["semantic_task_id"]
        for item in direct.heldout_selection_view["semantic_tasks"]
    }
    observed_ids = {
        item["semantic_task_id"] for item in payload["observations"]
    }
    assert observed_ids == training_ids
    assert observed_ids.isdisjoint(heldout_ids)
    assert payload["heldout_task_ids_observed"] == []
    assert payload["answer_rows_stored"] is False
    assert payload["oracle_inputs"] == []


def test_prediction_suite_covers_every_heldout_plan_without_profiles(
    tmp_path: Path,
) -> None:
    _, direct, _, memory, suite = _suite(tmp_path)
    payload = suite.to_dict()

    assert payload["schema_version"] == (
        DIRECT_FAMILY_PREDICTION_SUITE_SCHEMA_VERSION
    )
    assert payload["heldout_base_query_count"] == 2
    assert payload["heldout_semantic_task_count"] == 10
    assert payload["heldout_physical_plan_count"] == 20
    assert payload["heldout_queries_executed"] == 0
    assert payload["backend_calls_made"] == 0
    assert payload["current_query_profile_calls"] == 0
    assert payload["llm_calls_made"] == 0
    assert payload["ontology_service_calls_made"] == 0
    assert payload["oracle_inputs"] == []
    assert set(suite.sources) == set(
        direct.heldout_selection_view["base_query_ids"]
    )
    observed = {
        observation["observation_id"]: observation
        for observation in memory.payload["observations"]
    }
    for query_id, source in suite.sources.items():
        source_payload = source.to_dict()
        assert source_payload["schema_version"] == (
            DIRECT_FAMILY_PREDICTION_SOURCE_SCHEMA_VERSION
        )
        assert source_payload["base_query_id"] == query_id
        assert source_payload["current_query_observation_operations"] == []
        assert source_payload["post_execution_measurements_used"] is False
        assert source_payload["oracle_inputs"] == []
        assert source_payload["cold_start"] is False
        candidate_set = suite.candidate_sets[query_id]
        assert source_payload["prediction_count"] == len(candidate_set.plans)
        for prediction in source_payload["predictions"]:
            assert prediction["neighbor_observation_ids"]
            assert prediction["oracle_inputs"] == []
            assert prediction["post_execution_measurements_used"] is False
            assert all(
                observed[item]["physical_strategy"]
                == prediction["physical_strategy"]
                for item in prediction["neighbor_observation_ids"]
            )


def test_medium_and_low_sources_keep_variable_cardinality_and_feed_frontier(
    tmp_path: Path,
) -> None:
    _, _, _, _, suite = _suite(tmp_path)
    expected = {
        "financial-risk-alice-jun-medium-v2": (12, 6),
        "financial-risk-bob-may-low-v2": (8, 4),
    }

    for query_id, (plan_count, semantic_count) in expected.items():
        candidates = suite.candidate_sets[query_id]
        source = suite.sources[query_id]
        assert source.payload["prediction_count"] == plan_count
        snapshot = source.to_snapshot(candidates)
        assert snapshot.payload["evidence_kind"] == "family_memory_prediction"
        assert len(snapshot.payload["estimates"]) == plan_count
        frontier = select_m15_direct_semantic_frontier(
            candidates, snapshot
        ).to_dict()
        assert frontier["counts"]["executable_direct_semantic_classes"] == (
            semantic_count
        )
        assert 1 <= frontier["counts"]["returned_semantic_plans"] <= 4
        assert frontier["returned_semantic_plans"][0]["semantic_deviation"] == 0


def test_predictions_are_deterministic_and_bind_training_memory(tmp_path: Path) -> None:
    base, direct, _, memory = _memory(tmp_path)
    first = build_m15_direct_family_prediction_suite(
        workload=direct,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        memory=memory,
        policy=PREDICTOR_POLICY,
    )
    second = build_m15_direct_family_prediction_suite(
        workload=direct,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        memory=memory,
        policy=PREDICTOR_POLICY,
    )

    assert first.to_dict() == second.to_dict()
    assert {
        key: value.to_dict() for key, value in first.sources.items()
    } == {key: value.to_dict() for key, value in second.sources.items()}
    assert all(
        source.payload["training_memory_view_sha256"]
        == memory.memory_view_hash
        for source in first.sources.values()
    )


def test_training_memory_rejects_heldout_failed_and_unbalanced_inputs(
    tmp_path: Path,
) -> None:
    _, direct = _workload(tmp_path)
    raw = build_m15_controlled_training_observations(direct)["observations"]
    heldout_task = direct.heldout_selection_view["semantic_tasks"][0]

    contaminated = copy.deepcopy(raw)
    contaminated[0]["semantic_task_id"] = heldout_task["semantic_task_id"]
    with pytest.raises(M15DirectFamilyPredictionError):
        build_m15_direct_training_memory_view(
            workload=direct,
            raw_observations=contaminated,
            runtime_compatibility_sha256=RUNTIME_HASH,
            policy=PREDICTOR_POLICY,
            measurement_source_kind="controlled_local_nonmeasurement_fixture",
        )

    failed = copy.deepcopy(raw)
    failed[0]["repetitions"][0]["exact_answer"] = False
    with pytest.raises(M15DirectFamilyPredictionError):
        build_m15_direct_training_memory_view(
            workload=direct,
            raw_observations=failed,
            runtime_compatibility_sha256=RUNTIME_HASH,
            policy=PREDICTOR_POLICY,
            measurement_source_kind="controlled_local_nonmeasurement_fixture",
        )

    unbalanced = copy.deepcopy(raw)
    task_id = unbalanced[0]["semantic_task_id"]
    same_task = [item for item in unbalanced if item["semantic_task_id"] == task_id]
    assert len(same_task) == 2
    same_task[0]["repetitions"][0]["order_position"] = 1
    same_task[1]["repetitions"][0]["order_position"] = 1
    with pytest.raises(M15DirectFamilyPredictionError):
        build_m15_direct_training_memory_view(
            workload=direct,
            raw_observations=unbalanced,
            runtime_compatibility_sha256=RUNTIME_HASH,
            policy=PREDICTOR_POLICY,
            measurement_source_kind="controlled_local_nonmeasurement_fixture",
        )


def test_memory_and_policy_tampering_fail_before_prediction(tmp_path: Path) -> None:
    base, direct, _, memory = _memory(tmp_path)
    tampered = copy.deepcopy(memory.to_dict())
    tampered["observations"][0]["median_elapsed_ms"] += 1
    with pytest.raises(M15DirectFamilyPredictionError):
        build_m15_direct_family_prediction_suite(
            workload=direct,
            base_bundle=base,
            catalog=SEMANTIC_CATALOG,
            mapping=PREDICATE_MAPPING,
            memory=M15DirectTrainingMemoryView(tampered),
            policy=PREDICTOR_POLICY,
        )

    policy = json.loads(PREDICTOR_POLICY.read_text(encoding="utf-8"))
    policy["current_query_observation_operations"] = ["profile"]
    with pytest.raises(M15DirectFamilyPredictionError):
        build_m15_direct_family_prediction_suite(
            workload=direct,
            base_bundle=base,
            catalog=SEMANTIC_CATALOG,
            mapping=PREDICATE_MAPPING,
            memory=memory,
            policy=policy,
        )


def test_training_memory_rejects_answer_oracle_fields(tmp_path: Path) -> None:
    _, direct = _workload(tmp_path)
    raw = build_m15_controlled_training_observations(direct)["observations"]
    contaminated = copy.deepcopy(raw)
    contaminated[0]["answer_rows"] = []

    with pytest.raises(M15DirectFamilyPredictionError):
        build_m15_direct_training_memory_view(
            workload=direct,
            raw_observations=contaminated,
            runtime_compatibility_sha256=RUNTIME_HASH,
            policy=PREDICTOR_POLICY,
            measurement_source_kind="controlled_local_nonmeasurement_fixture",
        )


def test_compact_artifact_matches_deterministic_local_outputs(
    tmp_path: Path,
) -> None:
    _, _, controlled, memory, suite = _suite(tmp_path)
    artifact = json.loads(COMPACT_ARTIFACT.read_text(encoding="utf-8"))

    assert artifact["artifact_hashes"] == {
        "controlled_training_fixture_sha256": controlled["fixture_sha256"],
        "training_memory_view_sha256": memory.memory_view_hash,
        "prediction_suite_sha256": suite.payload["prediction_suite_sha256"],
    }
    assert artifact["heldout_prediction_suite"][
        "physical_plan_prediction_count"
    ] == suite.payload["heldout_physical_plan_count"]
    for query_id, source in suite.sources.items():
        assert artifact["heldout_queries"][query_id][
            "prediction_source_sha256"
        ] == source.source_hash
        assert artifact["heldout_queries"][query_id][
            "candidate_set_sha256"
        ] == suite.candidate_sets[query_id].candidate_set_hash
