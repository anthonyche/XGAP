import math

import pytest

from xgap.algebra.ops import NodesOp
from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    FeatureSupport,
    SupportLevel,
    SupportReason,
)
from xgap.planning import (
    ConfidenceContext,
    CostPrediction,
    DeterministicStateFeatureExtractor,
    ExchangeCatalog,
    ExecutionObservation,
    ExecutionObservationStore,
    GaussianProcessConfig,
    GaussianProcessCostEstimator,
    PhysicalCompilationResult,
    PhysicalPlan,
    PhysicalRealization,
    PlacementDecision,
    PlanningTraceEvent,
    StateSpaceBound,
    across_task_confidence_context,
    across_task_delta,
    confidence_beta,
    conservative_state_space_bound,
    index_logical_plan,
    make_execution_observation,
    read_search_trace,
    write_search_trace,
)


def _complete_plan(backend_id: str, upper: float = 5.0) -> PhysicalPlan:
    indexed = index_logical_plan(NodesOp())
    root = indexed.root_state("candidate-1")
    operator = root.operators[0]
    state = type(root)(
        interpretation_id=root.interpretation_id,
        logical_plan_id=root.logical_plan_id,
        operators=root.operators,
        dependencies=root.dependencies,
        placements=(
            PlacementDecision(
                operator_id=operator.operator_id,
                backend_id=backend_id,
                feature_id=operator.feature_id,
                support_level="supported",
            ),
        ),
    )
    compilation = PhysicalCompilationResult(
        feasible=True,
        executable=False,
        status="controlled",
        reason_code="controlled_test_artifact",
    )
    realization = PhysicalRealization(
        state_id=state.state_id,
        placements=state.placements,
        exchanges=(),
        compilation=compilation,
    )
    return PhysicalPlan(
        interpretation_id="candidate-1",
        logical_plan_id=state.logical_plan_id,
        state=state,
        realization=realization,
        cost=CostPrediction(
            mu=0.0,
            sigma=0.0,
            lower=upper,
            upper=upper,
            beta=0.0,
            estimator_id="controlled",
            model_version="1",
        ),
    )


def _profile(backend_id: str) -> BackendCapabilityProfile:
    feature_id = "path_algebra.Nodes"
    return BackendCapabilityProfile(
        backend_id=backend_id,
        engine=backend_id,
        language="controlled",
        data_model="controlled",
        version=1,
        feature_namespace="xgap.path_gpc",
        features={
            feature_id: FeatureSupport(
                feature_id=feature_id,
                level=SupportLevel.SUPPORTED,
                reason=SupportReason(code="controlled", message="controlled"),
            )
        },
    )


def _observation(plan, extractor, raw_cost, sequence):
    return make_execution_observation(
        plan=plan,
        raw_cost=raw_cost,
        query_id="query-1",
        task_id=f"task-{sequence}",
        alignment_ref="ontology@1/mapping@1",
        feature_vector=extractor.features(plan.state),
        estimator_version="m11-gp-v1",
        observed_at=f"2026-08-11T00:00:0{sequence}Z",
        sequence=sequence,
        provenance={"kind": "controlled_test_observation"},
    )


def test_observation_store_requires_positive_complete_costs_and_round_trips(tmp_path) -> None:
    extractor = DeterministicStateFeatureExtractor(("a", "b"))
    plan = _complete_plan("a")
    observation = _observation(plan, extractor, 2.5, 1)
    store = ExecutionObservationStore(tmp_path / "observations.jsonl")

    store.append(observation)
    loaded = store.snapshot()

    assert loaded == (observation,)
    assert loaded[0].log_cost == math.log(2.5)
    with pytest.raises(ValueError, match="positive"):
        _observation(plan, extractor, 0.0, 2)
    with pytest.raises(ValueError, match="Duplicate"):
        store.append(observation)


def test_feature_extraction_is_deterministic_and_marks_missing_statistics() -> None:
    state = index_logical_plan(NodesOp()).root_state("candidate-1")
    extractor = DeterministicStateFeatureExtractor(
        ("b", "a"),
        optional_stat_names=("estimated_cardinality", "backend_latency"),
        optional_statistics={"backend_latency": 4.0},
    )

    first = extractor.features(state)
    second = extractor.features(state)
    missing_index = first.names.index("stat.estimated_cardinality.value")
    presence_index = first.names.index("stat.estimated_cardinality.present")

    assert first == second
    assert first.schema_hash == extractor.schema_hash
    assert first.missing[missing_index]
    assert first.values[presence_index] == 0.0


def test_gp_posterior_and_bounds_are_positive_deterministic_and_immutable() -> None:
    extractor = DeterministicStateFeatureExtractor(("a", "b"))
    plan_a = _complete_plan("a")
    plan_b = _complete_plan("b")
    observation_a = _observation(plan_a, extractor, 2.0, 1)
    config = GaussianProcessConfig(
        length_scale=2.0,
        signal_variance=1.5,
        noise_variance=0.001,
        prior_log_cost=math.log(4.0),
    )
    snapshot_one = GaussianProcessCostEstimator(
        config=config,
        feature_extractor=extractor,
        observations=(observation_a,),
    )
    confidence = ConfidenceContext(delta=0.05, state_space_bound=10)

    first = snapshot_one.predict(plan_b.state, confidence)
    repeated = snapshot_one.predict(plan_b.state, confidence)
    observation_b = _observation(plan_b, extractor, 8.0, 2)
    snapshot_two = snapshot_one.with_observations(
        (observation_a, observation_b),
        model_version="m11-gp-v2",
    )

    assert first == repeated
    assert first.sigma >= 0
    assert 0 < first.lower <= first.upper
    assert len(snapshot_one.observations) == 1
    assert len(snapshot_two.observations) == 2
    assert snapshot_one.model_version == "m11-gp-v1"
    assert snapshot_two.model_version == "m11-gp-v2"
    assert snapshot_one.predict(plan_b.state, confidence) == first


def test_confidence_schedule_and_combinatorial_bound_do_not_enumerate_states() -> None:
    indexed = index_logical_plan(NodesOp())
    state = indexed.root_state("candidate-1")
    bound = conservative_state_space_bound(
        state,
        (_profile("a"), _profile("b")),
        ExchangeCatalog(),
    )
    scheduled = across_task_confidence_context(
        global_delta=0.05,
        task_index=2,
        interpretation_count=3,
        state_space_bound=bound.value,
    )

    assert isinstance(bound, StateSpaceBound)
    assert bound.value == 3
    assert scheduled.delta == across_task_delta(0.05, 2, 3)
    assert confidence_beta(bound.value, scheduled.delta) > 0
    assert across_task_delta(0.05, 2, 3) < across_task_delta(0.05, 1, 3)

    blocked_after_prefix = conservative_state_space_bound(
        index_logical_plan(NodesOp()).root_state("candidate-1"),
        (),
        ExchangeCatalog(),
    )
    assert blocked_after_prefix.value == 1


def test_search_trace_jsonl_persists_model_and_feature_references(tmp_path) -> None:
    plan = _complete_plan("a")
    extractor = DeterministicStateFeatureExtractor(("a",))
    estimator = GaussianProcessCostEstimator(
        config=GaussianProcessConfig(),
        feature_extractor=extractor,
    )
    prediction = estimator.predict(
        plan.state,
        ConfidenceContext(delta=0.05, state_space_bound=2),
    )
    event = PlanningTraceEvent(
        run_id="run-1",
        query_id="query-1",
        task_id="task-1",
        interpretation_id="candidate-1",
        alignment_ref="ontology@1/mapping@1",
        state_id=plan.state.state_id,
        parent_state_id=None,
        processed_index=1,
        action_id="root",
        action="root",
        placement_delta=None,
        exchange_delta=(),
        open_size=0,
        budget=1,
        budget_used=1,
        feasible=True,
        complete=True,
        prediction=prediction,
        pruned=False,
        prune_reason=None,
        incumbent_before=None,
        incumbent_after=prediction.upper,
        termination_reason="open_empty",
    )
    path = write_search_trace(tmp_path / "trace.jsonl", (event,))
    records = read_search_trace(path)

    assert records[0]["prediction"]["model_version"] == "m11-gp-v1"
    assert records[0]["feature_ref"] == prediction.feature_ref
