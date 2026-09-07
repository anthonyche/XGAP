from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path

import pytest

from xgap.experiments import m15_finbench_family_memory as memory_module
from xgap.experiments.m15_finbench_family_campaign import (
    FinBenchFamilyCampaignError,
    build_finbench_family_campaign_schedule,
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


@pytest.fixture
def public_contract(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    public = _public_workload()
    monkeypatch.setattr(
        memory_module,
        "load_finbench_primary_public_workload",
        lambda _root: copy.deepcopy(public),
    )
    return public


def test_campaign_freezes_all_result_blind_runs_and_slots(
    public_contract: dict[str, object], tmp_path: Path
) -> None:
    schedule = build_finbench_family_campaign_schedule(
        workload_root=tmp_path
    ).to_dict()

    assert schedule["expected_counts"] == {
        "training_plan_runs": 128,
        "profile_acquisition_plan_runs": 40,
        "paired_selected_plan_runs": 40,
        "evaluation_shadow_plan_runs": 160,
        "total_plan_runs": 368,
        "total_backend_calls": 736,
    }
    assert len(schedule["training_query_ids"]) == 16
    assert len(schedule["heldout_instance_query_ids"]) == 8
    assert len(schedule["heldout_family_query_ids"]) == 12
    assert schedule["family_selection_current_query_profile_calls"] == 0
    assert schedule["answer_oracle_opened"] is False
    assert schedule["backend_calls"] == 0
    assert schedule["paper_result"] is False
    assert all(
        run["current_query_profile"] is False
        and run["selection_input"] is True
        and run["memory_write_allowed"] is True
        for run in schedule["training_runs"]
    )
    assert all(
        run["current_query_profile"] is True
        and run["selection_input"] is True
        and run["memory_write_allowed"] is False
        for run in schedule["profile_acquisition_runs"]
    )
    assert all(
        run["selection_input"] is False
        and run["memory_write_allowed"] is False
        for run in schedule["evaluation_shadow_runs"]
    )
    slots = schedule["paired_selected_execution_slots"]
    assert all("physical_strategy" not in slot for slot in slots)
    assert sum(
        slot["method_id"] == "family_memory_zero_profile" for slot in slots
    ) == 8
    assert sum(
        slot["method_id"] == "predeclared_family_fallback" for slot in slots
    ) == 12
    assert sum(
        slot["method_id"] == "current_query_dual_profile" for slot in slots
    ) == 20
    assert all(
        slot["plan_binding"] == "profile_selection_seal"
        if slot["method_id"] == "current_query_dual_profile"
        else slot["plan_binding"] == "family_selection_seal"
        for slot in slots
    )


def test_training_and_shadow_are_per_query_ab_ba_counterbalanced(
    public_contract: dict[str, object], tmp_path: Path
) -> None:
    schedule = build_finbench_family_campaign_schedule(
        workload_root=tmp_path
    ).to_dict()
    for field in ("training_runs", "evaluation_shadow_runs"):
        positions: dict[tuple[str, str], list[int]] = defaultdict(list)
        for run in schedule[field]:
            positions[(run["query_id"], run["physical_strategy"])].append(
                run["order_position"]
            )
        assert positions
        assert all(sorted(value) == [1, 1, 2, 2] for value in positions.values())


def test_profile_and_paired_serving_orders_are_balanced_across_queries(
    public_contract: dict[str, object], tmp_path: Path
) -> None:
    schedule = build_finbench_family_campaign_schedule(
        workload_root=tmp_path
    ).to_dict()
    acquisition_first = [
        run
        for run in schedule["profile_acquisition_runs"]
        if run["order_position"] == 1
    ]
    route_a_first = sum(
        run["physical_strategy"] == STRATEGIES[run["family_id"]][0]
        for run in acquisition_first
    )
    slots_first = [
        slot
        for slot in schedule["paired_selected_execution_slots"]
        if slot["order_position"] == 1
    ]
    primary_first = sum(
        slot["method_id"]
        in {"family_memory_zero_profile", "predeclared_family_fallback"}
        for slot in slots_first
    )
    assert len(acquisition_first) == 20
    assert route_a_first == 10
    assert len(slots_first) == 20
    assert primary_first == 10


def test_campaign_is_deterministic_and_rejects_protocol_drift(
    public_contract: dict[str, object], tmp_path: Path
) -> None:
    first = build_finbench_family_campaign_schedule(workload_root=tmp_path)
    second = build_finbench_family_campaign_schedule(workload_root=tmp_path)
    assert first.to_dict() == second.to_dict()

    protocol_path = Path(
        "experiments/configs/m15_finbench_family_campaign_dev_v1.json"
    )
    changed = json.loads(protocol_path.read_text(encoding="utf-8"))
    changed["paper_result"] = True
    with pytest.raises(FinBenchFamilyCampaignError, match="protocol changed"):
        build_finbench_family_campaign_schedule(
            workload_root=tmp_path,
            protocol=changed,
        )
