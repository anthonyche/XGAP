from __future__ import annotations

import copy
from pathlib import Path

import pytest

from xgap.experiments import m15_finbench_family_memory as memory_module
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_family_memory import (
    FinBenchFamilyMemoryError,
    _distance,
    build_finbench_training_memory,
    predict_finbench_heldout_plans,
)


F1 = "f1_direct_transfer_control"
F2 = "f2_temporal_path_control"
F3 = "f3_aggregate_risk_ranking"
STRATEGIES = {
    F1: ("graph_first_hash", "control_first_bind"),
    F2: ("path_first_hash", "control_first_bound_path"),
    F3: ("aggregate_first_hash", "control_first_bound_aggregate"),
}


def _public_workload() -> dict[str, object]:
    instances: list[dict[str, object]] = []
    for family_id, prefix, feature_name in (
        (F1, "finbench-f1", "structural_degree"),
        (F2, "finbench-f2", "out_degree"),
    ):
        for position in range(1, 13):
            instances.append(
                {
                    "query_id": f"{prefix}-{position:02d}",
                    "family_id": family_id,
                    "split_role": (
                        "heldout_instance"
                        if position in {3, 6, 9, 12}
                        else "training"
                    ),
                    "selection_feature": {feature_name: position},
                }
            )
    for window_position in range(1, 5):
        for risk_position in range(1, 4):
            instances.append(
                {
                    "query_id": (
                        f"finbench-f3-w{window_position}-r{risk_position}"
                    ),
                    "family_id": F3,
                    "split_role": "heldout_family",
                    "selection_feature": {
                        "window_position": window_position,
                        "risk_position": risk_position,
                    },
                }
            )
    families = [
        {
            "family_id": family_id,
            "physical_strategies": list(strategies),
            **(
                {"cold_start_fallback": "aggregate_first_hash"}
                if family_id == F3
                else {}
            ),
        }
        for family_id, strategies in STRATEGIES.items()
    ]
    return {
        "manifest": {
            "workload_sha256": "a" * 64,
            "output_files": {
                "public_instances.json": {"sha256": "b" * 64},
                "family_contracts.json": {"sha256": "c" * 64},
            },
        },
        "public_instances": {"instances": instances},
        "family_contracts": {"families": families},
    }


def _raw_observations(public: dict[str, object]) -> list[dict[str, object]]:
    instances = public["public_instances"]["instances"]  # type: ignore[index]
    observations: list[dict[str, object]] = []
    for instance in instances:  # type: ignore[union-attr]
        if instance["split_role"] != "training":
            continue
        family_id = str(instance["family_id"])
        query_id = str(instance["query_id"])
        feature = next(iter(instance["selection_feature"].values()))
        for strategy_index, strategy in enumerate(STRATEGIES[family_id]):
            base_latency = (
                10.0
                if (family_id == F1 and strategy_index == 0)
                or (family_id == F2 and strategy_index == 1)
                else 20.0
            )
            repetitions = []
            for block in range(1, 5):
                first_index = 0 if block % 2 else 1
                position = 1 if strategy_index == first_index else 2
                repetitions.append(
                    {
                        "repetition_id": (
                            f"{query_id}-{strategy}-block-{block}"
                        ),
                        "block_index": block,
                        "order_position": position,
                        "elapsed_ms": base_latency + float(feature) / 100,
                        "total_bytes_moved": (
                            200 + int(feature)
                            if strategy_index == 0
                            else 100 + int(feature)
                        ),
                        "total_remote_calls": 2,
                        "execution_success": True,
                        "exact_answer": True,
                    }
                )
            observations.append(
                {
                    "query_id": query_id,
                    "family_id": family_id,
                    "physical_strategy": strategy,
                    "repetitions": repetitions,
                }
            )
    return observations


@pytest.fixture
def public_contract(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    public = _public_workload()
    monkeypatch.setattr(
        memory_module,
        "load_finbench_primary_public_workload",
        lambda _root: copy.deepcopy(public),
    )
    return public


def test_family_memory_predicts_known_queries_and_separates_cold_start(
    public_contract: dict[str, object], tmp_path: Path
) -> None:
    observations = _raw_observations(public_contract)
    memory = build_finbench_training_memory(
        workload_root=tmp_path,
        raw_observations=observations,
        measurement_source_id="native-training-run-001",
    )
    suite = predict_finbench_heldout_plans(
        workload_root=tmp_path,
        memory=memory,
    ).to_dict()

    assert memory.to_dict()["training_query_count"] == 16
    assert memory.to_dict()["training_plan_count"] == 32
    assert suite["heldout_query_count"] == 20
    assert suite["known_family_query_count"] == 8
    assert suite["cold_start_query_count"] == 12
    assert suite["current_query_profile_calls"] == 0
    known = [
        item for item in suite["predictions"]
        if item["evaluation_stratum"] == "heldout_instance"
    ]
    cold = [
        item for item in suite["predictions"]
        if item["evaluation_stratum"] == "heldout_family_cold_start"
    ]
    assert {item["selected_physical_strategy"] for item in known if item["family_id"] == F1} == {
        "graph_first_hash"
    }
    assert {item["selected_physical_strategy"] for item in known if item["family_id"] == F2} == {
        "control_first_bound_path"
    }
    assert all(item["physical_frontier_available"] is True for item in known)
    assert all(len(item["strategy_predictions"]) == 2 for item in known)
    assert all(item["physical_frontier_available"] is False for item in cold)
    assert all(item["predicted_physical_frontier"] == [] for item in cold)
    assert all(
        item["selected_physical_strategy"] == "aggregate_first_hash"
        for item in cold
    )
    assert all(item["current_query_profile_calls"] == 0 for item in suite["predictions"])


def test_memory_rejects_incomplete_or_heldout_observations(
    public_contract: dict[str, object], tmp_path: Path
) -> None:
    observations = _raw_observations(public_contract)
    with pytest.raises(FinBenchFamilyMemoryError, match="32 declared plans"):
        build_finbench_training_memory(
            workload_root=tmp_path,
            raw_observations=observations[:-1],
            measurement_source_id="native-training-run-001",
        )

    contaminated = copy.deepcopy(observations)
    contaminated[0]["query_id"] = "finbench-f1-03"
    with pytest.raises(FinBenchFamilyMemoryError, match="held-out"):
        build_finbench_training_memory(
            workload_root=tmp_path,
            raw_observations=contaminated,
            measurement_source_id="native-training-run-001",
        )


def test_prediction_revalidates_tampered_memory_semantics(
    public_contract: dict[str, object], tmp_path: Path
) -> None:
    memory = build_finbench_training_memory(
        workload_root=tmp_path,
        raw_observations=_raw_observations(public_contract),
        measurement_source_id="native-training-run-001",
    ).to_dict()
    observation = memory["observations"][0]
    observation["repetitions"][0]["exact_answer"] = False
    identity = {
        key: value
        for key, value in observation.items()
        if key != "observation_sha256"
    }
    observation["observation_sha256"] = content_hash(identity)
    body = {
        key: value
        for key, value in memory.items()
        if key != "training_memory_sha256"
    }
    memory["training_memory_sha256"] = content_hash(body)

    with pytest.raises(FinBenchFamilyMemoryError, match="inadmissible"):
        predict_finbench_heldout_plans(
            workload_root=tmp_path,
            memory=memory,
        )


def test_zero_width_training_range_does_not_create_false_exact_match() -> None:
    assert _distance({"x": 2.0}, {"x": 1.0}, {"x": (1.0, 1.0)}) == 1.0
    assert _distance({"x": 1.0}, {"x": 1.0}, {"x": (1.0, 1.0)}) == 0.0
