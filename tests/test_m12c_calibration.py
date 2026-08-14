import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from xgap.algebra.ops import NodesOp
from xgap.backends import registry
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.experiments.calibrate import run_calibration
from xgap.experiments.calibration_contracts import (
    CalibratedGPModelArtifact,
    CalibrationCase,
    CalibrationRunConfig,
    CalibrationStatus,
)
from xgap.experiments.contracts import ExecutionProtocol
from xgap.experiments.cost_calibration import (
    BackendCostModelRegistry,
    aggregate_latencies,
    measure_complete_plan,
    observation_backend_id,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.online_cost import (
    OnlinePosteriorLifecycle,
    make_online_execution_observation,
    write_posterior_commit,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.planning import (
    ConfidenceContext,
    CostPrediction,
    DeterministicStateFeatureExtractor,
    ExchangeDecision,
    ExecutionObservationStore,
    PhysicalCompilationResult,
    PhysicalPlan,
    PhysicalRealization,
    PlacementDecision,
    index_logical_plan,
    make_execution_observation,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments" / "configs" / "financial_risk_gp_calibration_dev.json"


@pytest.fixture(scope="module")
def calibrated_run(tmp_path_factory):
    output = tmp_path_factory.mktemp("m12c-calibration")
    return run_calibration(CONFIG, output_root_override=output, offline=True)


def _extractor() -> DeterministicStateFeatureExtractor:
    return DeterministicStateFeatureExtractor(
        ("neo4j", "fuseki"),
        optional_stat_names=("estimated_cardinality",),
    )


def _complete_plan(backend_id: str, extractor, *, cost=4.0) -> PhysicalPlan:
    indexed = index_logical_plan(NodesOp())
    root = indexed.root_state(f"online-{backend_id}")
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
                support_level="conditional",
            ),
        ),
    )
    artifact = QueryArtifact(
        artifact_id=f"online-{backend_id}",
        language="cypher" if backend_id == "neo4j" else "sparql",
        text="RETURN 1" if backend_id == "neo4j" else "SELECT * WHERE {}",
        kind="compiled",
    )
    compilation = PhysicalCompilationResult(
        feasible=True,
        executable=True,
        status="compiled_native_query",
        artifacts=(artifact,),
    )
    realization = PhysicalRealization(
        state_id=state.state_id,
        placements=state.placements,
        exchanges=(),
        compilation=compilation,
    )
    return PhysicalPlan(
        interpretation_id=state.interpretation_id,
        logical_plan_id=state.logical_plan_id,
        state=state,
        realization=realization,
        cost=CostPrediction(
            mu=math.log(cost),
            sigma=0.1,
            lower=cost / 2,
            upper=cost * 2,
            beta=1.0,
            estimator_id="test",
            model_version="1",
            feature_vector=extractor.features(state),
        ),
    )


def _registry_from_run(calibrated_run) -> BackendCostModelRegistry:
    extractor = _extractor()
    return BackendCostModelRegistry.from_calibration(
        model_artifacts=calibrated_run.model_artifacts,
        d0_records=calibrated_run.d0_records,
        feature_extractors={"neo4j": extractor, "fuseki": extractor},
    )


def test_calibration_config_freezes_split_backend_and_execution_protocol() -> None:
    config = CalibrationRunConfig.load(CONFIG)

    assert config.backend_ids == ("neo4j", "fuseki")
    assert config.calibration_split == "calibration"
    assert config.evaluation_split == "dev"
    assert config.execution_protocol.warmup_runs == 2
    assert config.execution_protocol.measured_repetitions == 5
    assert ExecutionProtocol.from_dict(config.execution_protocol.to_dict()) == config.execution_protocol
    assert config.config_hash == content_hash(config.to_hash_dict())
    with pytest.raises(ValueError, match="distinct"):
        replace(config, evaluation_split="calibration")


def test_calibration_cases_reject_evaluation_gold() -> None:
    with pytest.raises(ValueError, match="evaluation-only"):
        CalibrationCase.from_dict(
            {
                "case_id": "bad",
                "query_id": "bad",
                "interpretation_id": "bad",
                "split": "calibration",
                "stratum": "bad",
                "question": "bad",
                "pattern_query": {},
                "gold_answers": ["leak"],
            }
        )


def test_offline_calibration_writes_backend_specific_reproducible_d0(
    calibrated_run, tmp_path
) -> None:
    assert calibrated_run.status == "ok"
    assert calibrated_run.measurement_source == "deterministic_offline_fake"
    assert set(calibrated_run.model_artifacts) == {"neo4j", "fuseki"}
    neo4j = calibrated_run.d0_records["neo4j"]
    fuseki = calibrated_run.d0_records["fuseki"]
    assert len(neo4j) == len(fuseki) == 2
    assert {item.backend_id for item in neo4j} == {"neo4j"}
    assert {item.backend_id for item in fuseki} == {"fuseki"}
    assert not {item.observation.observation_id for item in neo4j}.intersection(
        item.observation.observation_id for item in fuseki
    )
    assert all(item.observation.complete for item in (*neo4j, *fuseki))
    assert all(item.raw_execution_cost_ms > 0 for item in (*neo4j, *fuseki))
    assert all(
        math.isclose(item.log_execution_cost, math.log(item.raw_execution_cost_ms))
        for item in (*neo4j, *fuseki)
    )
    for backend_id in ("neo4j", "fuseki"):
        d0_path = calibrated_run.run_root / "calibration" / backend_id / "D0.jsonl"
        assert len(ExecutionObservationStore(d0_path).snapshot()) == 2
        assert (
            calibrated_run.run_root / "cost_models" / backend_id / "model.json"
        ).exists()

    repeated = run_calibration(CONFIG, output_root_override=tmp_path, offline=True)
    assert {
        key: value.d0_hash for key, value in calibrated_run.model_artifacts.items()
    } == {key: value.d0_hash for key, value in repeated.model_artifacts.items()}
    assert {
        key: value.model_hash for key, value in calibrated_run.model_artifacts.items()
    } == {key: value.model_hash for key, value in repeated.model_artifacts.items()}


def test_calibrated_models_round_trip_and_keep_positive_execution_noise(calibrated_run) -> None:
    for artifact in calibrated_run.model_artifacts.values():
        rebuilt = CalibratedGPModelArtifact.from_dict(artifact.to_dict())
        assert rebuilt == artifact
        assert artifact.kernel_type == "rbf"
        assert artifact.config.noise_variance > 0
        assert artifact.feature_normalization["method"] == "none"
        assert artifact.hyperparameter_hash == rebuilt.hyperparameter_hash
    for backend_id in ("neo4j", "fuseki"):
        diagnostics = json.loads(
            (
                calibrated_run.run_root
                / "calibration"
                / backend_id
                / "cost_diagnostics.json"
            ).read_text(encoding="utf-8")
        )
        assert diagnostics["before_after_pipeline_check"]["changed"]
        assert diagnostics["before_after_pipeline_check"]["accuracy_claim"] is False


def test_registry_is_backend_local_and_feeds_existing_confidence_bounds(calibrated_run) -> None:
    models = _registry_from_run(calibrated_run)
    extractor = _extractor()
    plan = _complete_plan("neo4j", extractor)
    prediction = models.get("neo4j").predict(
        plan.state, ConfidenceContext(delta=0.05, state_space_bound=4)
    )

    assert models.list_backends() == ("fuseki", "neo4j")
    assert prediction.beta > 0
    assert 0 < prediction.lower <= prediction.upper
    assert models.hyperparameter_hash("neo4j") != ""


class _SequenceClient:
    def __init__(self, reports):
        self.reports = list(reports)

    def healthcheck(self):
        return BackendStatus("neo4j", True, "ok")

    def execute(self, artifact):
        return self.reports.pop(0)


def test_measurement_aggregation_and_failure_taxonomy() -> None:
    extractor = _extractor()
    plan = _complete_plan("neo4j", extractor)
    reports = [
        ExecutionReport("neo4j", "online-neo4j", "cypher", False, error="timed out"),
        ExecutionReport("neo4j", "online-neo4j", "cypher", True, elapsed_ms=4.0),
    ]
    batch = measure_complete_plan(
        calibration_id="cal",
        query_id="q",
        plan=plan,
        backend_id="neo4j",
        client=_SequenceClient(reports),
        protocol=ExecutionProtocol(warmup_runs=0, measured_repetitions=2),
        feature_extractor=extractor,
        measurement_protocol_hash="protocol",
        machine_metadata={},
        backend_metadata={},
    )

    assert aggregate_latencies((5.0, 1.0, 3.0), "median") == 3.0
    assert batch.status is CalibrationStatus.INSUFFICIENT_REPETITIONS
    assert [item.status for item in batch.measurements] == [
        CalibrationStatus.TIMEOUT,
        CalibrationStatus.SUCCESS,
        CalibrationStatus.INSUFFICIENT_REPETITIONS,
    ]


def test_existing_backend_clients_execute_compiled_native_artifacts(monkeypatch) -> None:
    registry.load_descriptors(ROOT / "descriptors" / "backends")
    neo4j = Neo4jClient(registry.get("neo4j"))
    fuseki = FusekiClient(registry.get("fuseki"))
    monkeypatch.setattr(
        neo4j,
        "_post_statement",
        lambda text, parameters: {
            "results": [{"columns": ["ok"], "data": [{"row": [1]}]}],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        fuseki,
        "_post_query",
        lambda text: {
            "head": {"vars": ["ok"]},
            "results": {"bindings": [{"ok": {"type": "literal", "value": "1"}}]},
        },
    )

    assert neo4j.execute(QueryArtifact("n", "cypher", "RETURN 1", kind="compiled")).success
    assert fuseki.execute(
        QueryArtifact("f", "sparql", "SELECT * WHERE {}", kind="compiled")
    ).success


def test_online_posterior_updates_only_after_task_batch_and_only_one_backend(
    calibrated_run, tmp_path
) -> None:
    models = _registry_from_run(calibrated_run)
    lifecycle = OnlinePosteriorLifecycle(models)
    extractor = _extractor()
    plan = _complete_plan("neo4j", extractor, cost=7.0)
    confidence = ConfidenceContext(delta=0.05, state_space_bound=4)
    task_one = lifecycle.begin_task(task_index=1, task_id="task-1")
    before = task_one.registry.get("neo4j").predict(plan.state, confidence)
    pre_neo4j = len(task_one.registry.get("neo4j").observations)
    pre_fuseki = len(task_one.registry.get("fuseki").observations)
    with pytest.raises(RuntimeError, match="already active"):
        lifecycle.begin_task(task_index=2, task_id="task-2")
    assert len(lifecycle.current_registry.get("neo4j").observations) == pre_neo4j

    batch = measure_complete_plan(
        calibration_id="online",
        query_id="q1",
        plan=plan,
        backend_id="neo4j",
        client=_SequenceClient(
            [
                ExecutionReport(
                    "neo4j", "online-neo4j", "cypher", True, elapsed_ms=value
                )
                for value in (6.0, 7.0)
            ]
        ),
        protocol=ExecutionProtocol(warmup_runs=0, measured_repetitions=2),
        feature_extractor=extractor,
        measurement_protocol_hash="online-protocol",
        machine_metadata={},
        backend_metadata={},
    )
    observation = make_online_execution_observation(
        task_id="task-1",
        query_id="q1",
        batch_id="batch-1",
        backend_id="neo4j",
        plan=plan,
        batch=batch,
        feature_extractor=extractor,
        estimator_version=models.get("neo4j").model_version,
        sequence=1,
        measurement_source="controlled_test_backend",
    )
    commit = lifecycle.complete_task(
        snapshot=task_one,
        batch_id="batch-1",
        executed_plan_ids=(plan.plan_id,),
        observations=(observation,),
    )
    after = commit.registry.get("neo4j").predict(plan.state, confidence)
    updates = {item.backend_id: item for item in commit.updates}

    assert len(commit.registry.get("neo4j").observations) == pre_neo4j + 1
    assert len(commit.registry.get("fuseki").observations) == pre_fuseki
    assert updates["neo4j"].batch_size == 1
    assert updates["neo4j"].backend_observation_count == 1
    assert updates["fuseki"].backend_observation_count == 0
    assert all(item.hyperparameters_unchanged for item in commit.updates)
    assert before != after

    task_two = lifecycle.begin_task(task_index=2, task_id="task-2")
    assert len(task_two.registry.get("neo4j").observations) == pre_neo4j + 1
    updates_path = tmp_path / "posterior_updates.jsonl"
    observations_path = tmp_path / "online_observations.jsonl"
    write_posterior_commit(
        commit,
        posterior_updates_path=updates_path,
        online_observations_path=observations_path,
    )
    assert len(updates_path.read_text(encoding="utf-8").splitlines()) == 2
    assert len(observations_path.read_text(encoding="utf-8").splitlines()) == 1


def test_online_lifecycle_rejects_future_and_cross_backend_observations(calibrated_run) -> None:
    models = _registry_from_run(calibrated_run)
    lifecycle = OnlinePosteriorLifecycle(models)
    extractor = _extractor()
    plan = _complete_plan("neo4j", extractor)
    task = lifecycle.begin_task(task_index=1, task_id="task-1")
    future = make_execution_observation(
        plan=plan,
        raw_cost=4.0,
        query_id="future",
        task_id="task-2",
        alignment_ref="runtime",
        feature_vector=extractor.features(plan.state),
        estimator_version="1",
        observed_at="2026-08-14T00:00:00Z",
        sequence=1,
    )
    with pytest.raises(ValueError, match="active task"):
        lifecycle.complete_task(
            snapshot=task,
            batch_id="bad",
            executed_plan_ids=(plan.plan_id,),
            observations=(future,),
        )
    cross_backend = replace(
        future,
        task_id="task-1",
        exchanges=(
            ExchangeDecision(
                dependency_id="dep",
                source_operator_id="source",
                target_operator_id="target",
                source_backend_id="neo4j",
                target_backend_id="fuseki",
                strategy_id="unsupported-test-transfer",
            ),
        ),
    )
    with pytest.raises(ValueError, match="cross_backend_measurement_unavailable"):
        observation_backend_id(cross_backend)
