from __future__ import annotations

import json
from pathlib import Path

import pytest
import xgap.experiments.m15_parameterized_federation as parameterized_federation

from xgap.agent import InMemoryStore, JsonlMemoryStore
from xgap.experiments.m15_family_memory import (
    FAMILY_TRANSFER_MODEL_VERSION,
    M15FamilyMemoryError,
    M15FamilyPlanMemory,
    M15FamilyPlanOutcome,
    build_m15_family_memory_context,
    build_m15_family_plan_observation,
    build_m15_family_query_features,
    select_m15_family_plan,
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
RUNTIME_HASH = "1" * 64


def _bundle(tmp_path: Path):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "bundle",
    )


def _context(bundle, *, method: str = "full_agent", runtime_hash=RUNTIME_HASH):
    return build_m15_family_memory_context(
        bundle,
        method_namespace=method,
        runtime_compatibility_sha256=runtime_hash,
    )


def _observation(
    bundle,
    context,
    *,
    query_id: str,
    task_id: str,
    sequence_index: int,
    parallel_ms: float,
    bind_ms: float,
):
    features = build_m15_family_query_features(
        bundle,
        query_id=query_id,
        context=context,
    )
    return build_m15_family_plan_observation(
        context=context,
        features=features,
        task_id=task_id,
        sequence_index=sequence_index,
        query_id=query_id,
        split_role="seed",
        outcomes=(
            M15FamilyPlanOutcome(
                "parallel_hash_join",
                f"{query_id}-parallel",
                parallel_ms,
                10_000,
                2,
            ),
            M15FamilyPlanOutcome(
                "risk_first_bind_join",
                f"{query_id}-bind",
                bind_ms,
                1_000,
                2,
            ),
        ),
        execution_success=True,
        exact_answer=True,
    )


def test_context_and_features_are_instance_transferable_but_oracle_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path)
    original = parameterized_federation._json_file

    def reject_oracle(bundle_value, path):
        if "expected_" in path:
            raise AssertionError("memory feature extraction opened an oracle")
        return original(bundle_value, path)

    monkeypatch.setattr(parameterized_federation, "_json_file", reject_oracle)
    context = _context(bundle)
    first = build_m15_family_query_features(
        bundle,
        query_id=bundle.instance_ids()[0],
        context=context,
    )
    heldout = build_m15_family_query_features(
        bundle,
        query_id=bundle.instance_ids()[-1],
        context=context,
    )

    assert first.family_compatibility_sha256 == heldout.family_compatibility_sha256
    assert first.query_instance_sha256 != heldout.query_instance_sha256
    assert first.features_sha256 != heldout.features_sha256
    assert context.candidate_strategy_ids == (
        "parallel_hash_join",
        "risk_first_bind_join",
    )
    assert context.to_dict()["memory_scope"] == "successful_exact_seed_only"


def test_family_memory_freezes_only_explicit_successful_predecessors(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    context = _context(bundle)
    memory = M15FamilyPlanMemory(InMemoryStore(), context)
    first = _observation(
        bundle,
        context,
        query_id=bundle.instance_ids()[0],
        task_id="seed-01",
        sequence_index=1,
        parallel_ms=30.0,
        bind_ms=10.0,
    )
    second = _observation(
        bundle,
        context,
        query_id=bundle.instance_ids()[1],
        task_id="seed-02",
        sequence_index=2,
        parallel_ms=25.0,
        bind_ms=12.0,
    )
    memory.commit(first, source="seed-01/exact-validation")
    memory.commit(second, source="seed-02/exact-validation")

    view = memory.freeze(
        current_sequence_index=5,
        eligible_task_ids=("seed-02", "seed-01"),
    )

    assert view.eligible_task_ids == ("seed-01", "seed-02")
    assert [item.sequence_index for item in view.observations] == [1, 2]
    assert view.to_dict()["writes_visible_from_current_task"] is False
    assert all(
        item.to_dict()["answer_rows_stored"] is False
        for item in view.observations
    )


def test_family_selector_transfers_seed_measurements_to_heldout_instance(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    context = _context(bundle)
    memory = M15FamilyPlanMemory(InMemoryStore(), context)
    for index, query_id in enumerate(bundle.instance_ids()[:4], start=1):
        observation = _observation(
            bundle,
            context,
            query_id=query_id,
            task_id=f"seed-{index:02d}",
            sequence_index=index,
            parallel_ms=40.0 + index,
            bind_ms=8.0 + index,
        )
        memory.commit(observation, source=f"seed-{index:02d}/exact-validation")
    view = memory.freeze(
        current_sequence_index=5,
        eligible_task_ids=tuple(f"seed-{index:02d}" for index in range(1, 5)),
    )
    features = build_m15_family_query_features(
        bundle,
        query_id=bundle.instance_ids()[4],
        context=context,
    )

    selection = select_m15_family_plan(
        context=context,
        features=features,
        memory_view=view,
        k=3,
    )

    assert selection.selected_strategy_id == "risk_first_bind_join"
    assert selection.selection_mode == "family_local_knn"
    assert selection.model_version == FAMILY_TRANSFER_MODEL_VERSION
    assert not selection.cold_start
    assert selection.to_dict()["oracle_inputs"] == []
    assert len(selection.predictions) == 2
    assert all(len(item["neighbors"]) == 3 for item in selection.predictions)


def test_family_selector_can_choose_other_strategy_from_different_history(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    context = _context(bundle)
    memory = M15FamilyPlanMemory(InMemoryStore(), context)
    for index, query_id in enumerate(bundle.instance_ids()[:3], start=1):
        memory.commit(
            _observation(
                bundle,
                context,
                query_id=query_id,
                task_id=f"seed-{index:02d}",
                sequence_index=index,
                parallel_ms=5.0 + index,
                bind_ms=50.0 + index,
            ),
            source="controlled-history",
        )
    view = memory.freeze(
        current_sequence_index=5,
        eligible_task_ids=("seed-01", "seed-02", "seed-03"),
    )
    features = build_m15_family_query_features(
        bundle,
        query_id=bundle.instance_ids()[4],
        context=context,
    )

    selection = select_m15_family_plan(
        context=context,
        features=features,
        memory_view=view,
    )

    assert selection.selected_strategy_id == "parallel_hash_join"


def test_empty_family_view_uses_declared_cold_start_fallback(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    context = _context(bundle)
    memory = M15FamilyPlanMemory(InMemoryStore(), context)
    view = memory.freeze(current_sequence_index=1, eligible_task_ids=())
    features = build_m15_family_query_features(
        bundle,
        query_id=bundle.instance_ids()[0],
        context=context,
    )

    selection = select_m15_family_plan(
        context=context,
        features=features,
        memory_view=view,
        cold_start_strategy_id="parallel_hash_join",
    )

    assert selection.cold_start
    assert selection.selection_mode == "cold_start_fallback"
    assert selection.selected_strategy_id == "parallel_hash_join"
    assert selection.predictions == ()


def test_evaluation_or_inexact_observation_cannot_enter_memory(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    context = _context(bundle)
    features = build_m15_family_query_features(
        bundle,
        query_id=bundle.instance_ids()[4],
        context=context,
    )
    outcomes = (
        M15FamilyPlanOutcome("parallel_hash_join", "parallel", 10.0, 100, 2),
        M15FamilyPlanOutcome("risk_first_bind_join", "bind", 9.0, 50, 2),
    )

    with pytest.raises(M15FamilyMemoryError, match="only seed"):
        build_m15_family_plan_observation(
            context=context,
            features=features,
            task_id="heldout-01",
            sequence_index=5,
            query_id=bundle.instance_ids()[4],
            split_role="heldout_instance",
            outcomes=outcomes,
            execution_success=True,
            exact_answer=True,
        )
    with pytest.raises(M15FamilyMemoryError, match="successful exact"):
        build_m15_family_plan_observation(
            context=context,
            features=features,
            task_id="bad-seed",
            sequence_index=5,
            query_id=bundle.instance_ids()[4],
            split_role="seed",
            outcomes=outcomes,
            execution_success=True,
            exact_answer=False,
        )


def test_memory_rejects_current_task_and_cross_runtime_reuse(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    context = _context(bundle)
    store = InMemoryStore()
    memory = M15FamilyPlanMemory(store, context)
    observation = _observation(
        bundle,
        context,
        query_id=bundle.instance_ids()[0],
        task_id="seed-01",
        sequence_index=1,
        parallel_ms=20.0,
        bind_ms=10.0,
    )
    memory.commit(observation, source="seed")

    with pytest.raises(M15FamilyMemoryError, match="current or future"):
        memory.freeze(current_sequence_index=1, eligible_task_ids=("seed-01",))

    other_context = _context(bundle, runtime_hash="2" * 64)
    other_memory = M15FamilyPlanMemory(store, other_context)
    with pytest.raises(M15FamilyMemoryError, match="missing"):
        other_memory.freeze(
            current_sequence_index=2,
            eligible_task_ids=("seed-01",),
        )


def test_jsonl_family_memory_reopens_without_storing_answers(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    context = _context(bundle)
    path = tmp_path / "family-memory.jsonl"
    memory = M15FamilyPlanMemory(JsonlMemoryStore(path), context)
    observation = _observation(
        bundle,
        context,
        query_id=bundle.instance_ids()[0],
        task_id="seed-01",
        sequence_index=1,
        parallel_ms=15.0,
        bind_ms=7.0,
    )
    memory.commit(observation, source="seed/exact-validation")

    reopened = M15FamilyPlanMemory(JsonlMemoryStore(path), context)
    view = reopened.freeze(
        current_sequence_index=2,
        eligible_task_ids=("seed-01",),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(view.observations) == 1
    assert payload["value"]["answer_rows_stored"] is False
    assert "final_rows" not in path.read_text(encoding="utf-8")
