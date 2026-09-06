from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from xgap.experiments.m15_direct_semantic_frontier import (
    VARIABLE_DIRECT_SEMANTIC_CANDIDATE_SET_SCHEMA_VERSION,
    VARIABLE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION,
    VARIABLE_PREEXECUTION_ESTIMATE_SNAPSHOT_SCHEMA_VERSION,
    build_m15_preexecution_estimate_snapshot,
    build_m15_variable_direct_semantic_candidate_set,
    select_m15_direct_semantic_frontier,
)
from xgap.experiments.m15_direct_semantic_workload import (
    DIRECT_SEMANTIC_WORKLOAD_SCHEMA_VERSION,
    M15DirectSemanticWorkloadError,
    generate_m15_direct_semantic_workload_bundle,
    load_m15_direct_semantic_workload_bundle,
    main as direct_semantic_workload_main,
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
HIGH_QUERY_ID = "financial-risk-alice-aug-high-v2"
MEDIUM_QUERY_ID = "financial-risk-bob-jul-medium-v2"


def _bundle(tmp_path: Path, name: str = "direct"):
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / f"{name}-base",
    )
    direct = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
        policy=CARDINALITY_POLICY,
        destination=tmp_path / name,
    )
    return base, direct


def _candidate_set(tmp_path: Path, query_id: str):
    base, direct = _bundle(tmp_path, name=query_id)
    candidates = build_m15_variable_direct_semantic_candidate_set(
        direct_workload=direct,
        base_bundle=base,
        base_query_id=query_id,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
    )
    return base, direct, candidates


def _estimates(candidates):
    classes = {
        item["semantic_class_id"]: item
        for item in candidates.to_dict()["semantic_classes"]
    }
    result = []
    for plan in candidates.to_dict()["physical_candidates"]:
        semantic = classes[plan["semantic_class_id"]]
        deviation = float(semantic["semantic_deviation"])
        strategy_penalty = (
            0.0
            if plan["physical_strategy"] == "risk_first_bind_join"
            else 7.0
        )
        class_tie_break = int(plan["semantic_class_id"][-2:], 16) / 100.0
        result.append(
            {
                "plan_id": plan["plan_id"],
                "estimated_latency_ms": (
                    100.0 - 70.0 * deviation + strategy_penalty + class_tie_break
                ),
                "estimated_resource_cost_units": (
                    100.0 - 50.0 * deviation + strategy_penalty + class_tie_break
                ),
            }
        )
    return result


def test_preserve_all_workload_has_variable_catalog_cardinality(
    tmp_path: Path,
) -> None:
    _, direct = _bundle(tmp_path)

    assert direct.manifest["schema_version"] == (
        DIRECT_SEMANTIC_WORKLOAD_SCHEMA_VERSION
    )
    assert direct.manifest["counts"] == {
        "base_query_instances": 6,
        "exact_semantic_tasks": 6,
        "relaxed_semantic_tasks": 22,
        "direct_semantic_tasks": 28,
        "unavailable_multihop_semantic_classes": 56,
        "physical_candidates": 56,
        "training_base_queries": 4,
        "heldout_base_queries": 2,
        "training_semantic_tasks": 18,
        "heldout_semantic_tasks": 10,
        "augmented_query_instances": 28,
        "payment_edges": 720,
    }
    assert Counter(
        (item["base_risk_level"], item["direct_semantic_class_count"])
        for item in direct.manifest["base_queries"]
    ) == Counter({("HIGH", 4): 2, ("MEDIUM", 6): 2, ("LOW", 4): 2})
    assert direct.manifest["cardinality_policy"] == json.loads(
        CARDINALITY_POLICY.read_text(encoding="utf-8")
    )
    assert len(direct.manifest["cardinality_policy_sha256"]) == 64
    assert direct.manifest["paper_result"] is False


def test_selection_views_preserve_split_and_exclude_answer_artifacts(
    tmp_path: Path,
) -> None:
    _, direct = _bundle(tmp_path)
    training = direct.training_selection_view
    heldout = direct.heldout_selection_view

    assert training["semantic_task_count"] == 18
    assert heldout["semantic_task_count"] == 10
    assert training["physical_candidate_count"] == 36
    assert heldout["physical_candidate_count"] == 20
    assert set(training["base_query_ids"]).isdisjoint(heldout["base_query_ids"])
    assert all(item["split_role"] == "seed" for item in training["semantic_tasks"])
    assert all(
        item["split_role"] == "heldout_instance"
        for item in heldout["semantic_tasks"]
    )
    selection_text = json.dumps(
        {"training": training, "heldout": heldout}, sort_keys=True
    ).lower()
    assert "oracle" not in selection_text
    assert "expected_result" not in selection_text
    assert training["post_execution_measurements_used"] is False
    assert heldout["post_execution_measurements_used"] is False


def test_all_direct_tasks_preserve_hard_bindings_and_split_role(
    tmp_path: Path,
) -> None:
    base, direct = _bundle(tmp_path)
    base_by_id = {
        item["query_id"]: item for item in base.spec.query_instances
    }
    tasks = (
        list(direct.training_selection_view["semantic_tasks"])
        + list(direct.heldout_selection_view["semantic_tasks"])
    )

    assert len({item["semantic_task_id"] for item in tasks}) == 28
    assert len({item["executable_query_id"] for item in tasks}) == 28
    for task in tasks:
        source = base_by_id[task["base_query_id"]]
        assert task["split_role"] == source["split_role"]
        assert task["binding_values"]["path-shape"] == "direct"
        for slot_id in (
            "person-identity",
            "time-lower-bound",
            "amount-lower-bound",
        ):
            assert task["binding_values"][slot_id] == source[
                "binding_values"
            ][slot_id]
        assert len(task["physical_candidates"]) == 2


def test_evaluation_registry_is_complete_and_separate(tmp_path: Path) -> None:
    _, direct = _bundle(tmp_path)
    registry = direct.evaluation_registry
    selection_ids = {
        item["semantic_task_id"]
        for view in (
            direct.training_selection_view,
            direct.heldout_selection_view,
        )
        for item in view["semantic_tasks"]
    }

    assert registry["selection_input"] is False
    assert registry["opened_only_after_selection"] is True
    assert registry["semantic_task_count"] == 28
    assert {item["semantic_task_id"] for item in registry["records"]} == (
        selection_ids
    )
    assert all(item["final_oracle"]["row_count"] > 0 for item in registry["records"])
    assert all(
        len(item["final_oracle"]["sha256"]) == 64
        for item in registry["records"]
    )


@pytest.mark.parametrize(
    ("query_id", "direct_count", "declared_count", "unavailable_count"),
    [
        (HIGH_QUERY_ID, 4, 12, 8),
        (MEDIUM_QUERY_ID, 6, 18, 12),
    ],
)
def test_variable_candidate_and_frontier_contracts(
    tmp_path: Path,
    query_id: str,
    direct_count: int,
    declared_count: int,
    unavailable_count: int,
) -> None:
    _, _, candidates = _candidate_set(tmp_path, query_id)
    payload = candidates.to_dict()

    assert payload["schema_version"] == (
        VARIABLE_DIRECT_SEMANTIC_CANDIDATE_SET_SCHEMA_VERSION
    )
    assert payload["counts"] == {
        "declared_semantic_classes": declared_count,
        "executable_direct_semantic_classes": direct_count,
        "unavailable_semantic_classes": unavailable_count,
        "physical_candidates": 2 * direct_count,
        "physical_candidates_per_class": 2,
    }
    assert len(payload["semantic_classes"]) == direct_count
    assert len(payload["physical_candidates"]) == 2 * direct_count
    snapshot = build_m15_preexecution_estimate_snapshot(
        candidates,
        _estimates(candidates),
        evidence_kind="family_memory_prediction",
        evidence_id=f"m15-f2c10-test-{direct_count}",
    )
    assert snapshot.to_dict()["schema_version"] == (
        VARIABLE_PREEXECUTION_ESTIMATE_SNAPSHOT_SCHEMA_VERSION
    )
    frontier = select_m15_direct_semantic_frontier(
        candidates, snapshot
    ).to_dict()
    assert frontier["schema_version"] == (
        VARIABLE_DIRECT_SEMANTIC_FRONTIER_SCHEMA_VERSION
    )
    assert frontier["counts"]["executable_direct_semantic_classes"] == (
        direct_count
    )
    assert frontier["counts"]["physical_candidates"] == 2 * direct_count
    assert 1 <= frontier["counts"]["returned_semantic_plans"] <= 4
    assert frontier["returned_semantic_plans"][0]["semantic_deviation"] == 0


def test_medium_keeps_both_adjacent_risk_directions(tmp_path: Path) -> None:
    _, _, candidates = _candidate_set(tmp_path, MEDIUM_QUERY_ID)
    semantic_classes = candidates.to_dict()["semantic_classes"]
    risk_only = [
        item
        for item in semantic_classes
        if item["changed_slot_ids"] == ["risk-level"]
    ]
    combined = [
        item
        for item in semantic_classes
        if item["changed_slot_ids"]
        == ["risk-level", "transfer-predicate"]
    ]

    assert {item["binding_values"]["risk-level"] for item in risk_only} == {
        "HIGH",
        "LOW",
    }
    assert {item["binding_values"]["risk-level"] for item in combined} == {
        "HIGH",
        "LOW",
    }


def test_loader_reconstructs_and_rejects_selection_tampering(
    tmp_path: Path,
) -> None:
    base, direct = _bundle(tmp_path)
    loaded = load_m15_direct_semantic_workload_bundle(
        direct.root,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
    )
    assert loaded.manifest == direct.manifest

    path = direct.root / "heldout_selection_view.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["semantic_task_count"] -= 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(M15DirectSemanticWorkloadError, match="hash mismatch"):
        load_m15_direct_semantic_workload_bundle(
            direct.root,
            base_bundle=base,
            catalog=SEMANTIC_CATALOG,
            mapping=PREDICATE_MAPPING,
        )


def test_generator_refuses_existing_destination(tmp_path: Path) -> None:
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "base",
    )
    destination = tmp_path / "already-there"
    destination.mkdir()

    with pytest.raises(FileExistsError):
        generate_m15_direct_semantic_workload_bundle(
            base_bundle=base,
            catalog=SEMANTIC_CATALOG,
            mapping=PREDICATE_MAPPING,
            policy=CARDINALITY_POLICY,
            destination=destination,
        )


def test_cli_generates_a_reloadable_direct_workload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "cli-base",
    )
    destination = tmp_path / "cli-direct"

    assert direct_semantic_workload_main(
        [
            "--base-bundle-root",
            str(base.root),
            "--catalog",
            str(SEMANTIC_CATALOG),
            "--mapping",
            str(PREDICATE_MAPPING),
            "--policy",
            str(CARDINALITY_POLICY),
            "--output",
            str(destination),
        ]
    ) == 0

    emitted = json.loads(capsys.readouterr().out)
    loaded = load_m15_direct_semantic_workload_bundle(
        destination,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
        mapping=PREDICATE_MAPPING,
    )
    assert emitted == loaded.manifest
