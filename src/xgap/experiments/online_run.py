"""Configuration-driven, resumable M12-D online server experiment runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from xgap.backends import registry as backend_registry
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.experiments.bundles import DatasetBundle, FragmentSupport, ModelBundle
from xgap.experiments.calibration_contracts import CalibrationStatus
from xgap.experiments.calibration_io import load_calibrated_registry
from xgap.experiments.candidate_freeze import (
    FrozenCandidateArtifact,
    generate_frozen_candidate_artifact,
)
from xgap.experiments.contracts import ExperimentSpec
from xgap.experiments.cost_calibration import (
    MeasurementBatch,
    measure_complete_plan,
)
from xgap.experiments.failures import ExperimentFailureCategory
from xgap.experiments.hashing import content_hash
from xgap.experiments.method_planner import (
    MethodPlanningResult,
    plan_candidates_with_method,
)
from xgap.experiments.methods import RegistryCostEstimator, resolve_method_policy
from xgap.experiments.metrics import ExecutionOutcome, summarize_run_metrics
from xgap.experiments.online_cost import (
    OnlinePosteriorLifecycle,
    make_online_execution_observation,
)
from xgap.experiments.run import _budget_policy
from xgap.experiments.semantic import DirectionalOntologySemanticDeviationScorer
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.llm.openai_compatible import OpenAICompatibleTransport
from xgap.planning import (
    ConfidenceContext,
    DeterministicStateFeatureExtractor,
    ExchangeCatalog,
    ExecutionObservation,
    ExistingCompilerAdapter,
    MainPlannerResult,
    PlanningConfig,
    QueryPlanningContext,
)


@dataclass(frozen=True)
class OnlineRunResult:
    run_root: Path
    run_id: str
    status: str
    completed_task_count: int
    total_task_count: int
    resumed: bool
    inventory: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_root": str(self.run_root),
            "run_id": self.run_id,
            "status": self.status,
            "completed_task_count": self.completed_task_count,
            "total_task_count": self.total_task_count,
            "resumed": self.resumed,
            "inventory": list(self.inventory),
        }


class DeterministicOfflineExecutionClient:
    """Explicit fake execution boundary for offline matrix validation."""

    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id
        self._counter = 0

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(
            self.backend_id,
            True,
            "deterministic offline M12-D client",
            checked_at="deterministic",
            details={"measurement_source": "deterministic_offline_fake"},
        )

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self._counter += 1
        digest = hashlib.sha256(
            f"{self.backend_id}:{artifact.artifact_id}:{self._counter}".encode()
        ).hexdigest()
        latency = 3.0 + (int(digest[:8], 16) % 3000) / 1000.0
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[
                {
                    "company": "Redstone Analytics",
                    "amount": 125000,
                    "currency": "USD",
                    "occurred_on": "2026-03-12",
                }
            ],
            elapsed_ms=latency,
            started_at="deterministic",
            ended_at="deterministic",
            metadata={"measurement_source": "deterministic_offline_fake"},
        )


def run_online_experiment(
    config_path: str | Path,
    *,
    output_root_override: str | Path | None = None,
    calibration_root_override: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    offline: bool = False,
    resume: bool = False,
    transport_override: OpenAICompatibleTransport | None = None,
    stop_after_tasks: int | None = None,
) -> OnlineRunResult:
    repo_root = _repo_root()
    spec = ExperimentSpec.load(_resolve(config_path, repo_root))
    orchestration = dict(spec.orchestration)
    mode = str(orchestration.get("experiment_mode", "development"))
    if mode not in {"development", "pilot", "paper"}:
        raise ValueError("Experiment mode must be development, pilot, or paper.")
    running_python = tuple(int(item) for item in platform.python_version_tuple())
    if mode == "paper" and running_python < (3, 10, 0):
        raise RuntimeError("Paper experiments require Python 3.10+.")
    policy = resolve_method_policy(
        spec.baseline,
        spec.ablations,
        seed=spec.random_seed,
        options=_object(orchestration.get("method_options", {}), "method_options"),
    )
    if policy.search_strategy.value == "direct":
        raise ValueError(
            "Use xgap.experiments.direct_baseline for direct_text2graphquery."
        )

    dataset = DatasetBundle.load(_resolve(spec.dataset_bundle_ref, repo_root))
    model = ModelBundle.load(_resolve(spec.model_bundle_ref, repo_root))
    questions = tuple(dataset.question(item) for item in spec.question_ids)
    descriptor_dir = _resolve(spec.descriptor_dir, repo_root)
    backend_registry.load_descriptors(descriptor_dir)
    profiles = tuple(
        backend_registry.get_capability_profile(item) for item in spec.backend_ids
    )
    feature_backend_ids = tuple(
        str(item)
        for item in orchestration.get("feature_backend_ids", spec.backend_ids)
    )
    if not set(spec.backend_ids).issubset(set(feature_backend_ids)):
        raise ValueError("Active backends must be included in feature_backend_ids.")
    extractor = DeterministicStateFeatureExtractor(
        feature_backend_ids,
        optional_stat_names=spec.feature_schema.unavailable_statistics,
    )
    if extractor.schema_hash != spec.feature_schema.schema_hash:
        raise ValueError("Experiment feature schema does not match backend placement scope.")

    calibration_ref = calibration_root_override or orchestration.get("calibration_run")
    if not calibration_ref:
        raise ValueError("M12-D online runs require orchestration.calibration_run.")
    calibration_root = _resolve(str(calibration_ref), repo_root)
    d0_registry, _ = load_calibrated_registry(
        calibration_root,
        backend_ids=feature_backend_ids,
        feature_extractor=extractor,
    )
    output_root = (
        Path(output_root_override)
        if output_root_override is not None
        else _resolve(spec.output_root, repo_root)
    )
    run_root = output_root / spec.run_id
    resumed = _initialize_or_open_run(run_root, spec=spec, resume=resume)
    task_files = _completed_task_files(run_root)
    if len(task_files) > len(questions):
        raise ValueError("Resume state has more tasks than the configured workload.")

    current_registry = d0_registry
    if policy.online_update:
        prior_observations = tuple(
            ExecutionObservation.from_dict(item)
            for task_file in task_files
            for item in _load_json(task_file).get("online_observations", [])
        )
        if prior_observations:
            current_registry = current_registry.with_observation_batch(prior_observations)
    lifecycle = OnlinePosteriorLifecycle.restore(
        current_registry, next_task_index=len(task_files) + 1
    )
    execution_clients = _clients(
        spec=spec,
        offline=offline,
        injected=clients,
    )
    measurement_source = (
        "deterministic_offline_fake"
        if offline
        else "injected_client"
        if clients is not None
        else "real_backend"
    )
    completed_this_call = 0

    for task_index, question in enumerate(questions, 1):
        if task_index <= len(task_files):
            continue
        if stop_after_tasks is not None and completed_this_call >= stop_after_tasks:
            break
        task_id = f"{spec.run_id}-task-{task_index}"
        if question.fragment_support is not FragmentSupport.XGAP_SUPPORTED:
            failure_category = _fragment_failure_category(question.fragment_support)
            if policy.online_update:
                snapshot = lifecycle.begin_task(task_index=task_index, task_id=task_id)
                commit = lifecycle.complete_task(
                    snapshot=snapshot,
                    batch_id=f"{task_id}-atomic-empty-batch",
                    executed_plan_ids=(),
                    observations=(),
                )
                snapshot_data = snapshot.to_dict()
                posterior_updates = [item.to_dict() for item in commit.updates]
                current_registry = commit.registry
            else:
                snapshot_data = _frozen_d0_snapshot(
                    d0_registry, task_index=task_index, task_id=task_id
                )
                posterior_updates = [
                    {
                        "schema_version": "m12d-posterior-update-disabled-v1",
                        "task_index": task_index,
                        "task_id": task_id,
                        "status": "disabled",
                        "reason": "method_policy_freezes_D0",
                        "observation_count_recorded_for_evaluation": 0,
                    }
                ]
            _write_atomic_json(
                run_root / "tasks" / f"{task_index:06d}.json",
                {
                    "schema_version": "m12d-task-record-v1",
                    "task_index": task_index,
                    "task_id": task_id,
                    "question_id": question.question_id,
                    "status": failure_category,
                    "failure_category": failure_category,
                    "fragment_support": question.fragment_support.value,
                    "pre_task_posterior": snapshot_data,
                    "online_observations": [],
                    "posterior_updates": posterior_updates,
                    "posterior_change_diagnostics": {
                        "status": "not_available",
                        "reason": "Task was rejected before physical planning and execution.",
                        "records": [],
                    },
                    "execution_results": [],
                    "execution_measurements": [],
                    "posterior_commit_timing": "after_task_classification",
                    "within_task_update": False,
                },
            )
            completed_this_call += 1
            _rebuild_run_logs(run_root, spec)
            continue

        candidate_artifact, candidate_path = _candidate_artifact(
            spec=spec,
            dataset=dataset,
            model=model,
            question=question,
            task_id=task_id,
            run_root=run_root,
            repo_root=repo_root,
            transport_override=transport_override,
        )
        response = candidate_artifact.planner_response()
        if policy.online_update:
            snapshot = lifecycle.begin_task(task_index=task_index, task_id=task_id)
            planning_registry = snapshot.registry
            snapshot_data = snapshot.to_dict()
        else:
            planning_registry = d0_registry
            snapshot_data = _frozen_d0_snapshot(
                planning_registry, task_index=task_index, task_id=task_id
            )
            snapshot = None

        query_context = QueryPlanningContext(
            query_id=question.question_id,
            task_id=task_id,
            question=question.text,
            metadata={"dataset_id": dataset.dataset_id, "split": question.split},
        )
        planning_started = time.perf_counter()
        method_result = plan_candidates_with_method(
            policy=policy,
            query_context=query_context,
            candidates=response.candidates,
            config=PlanningConfig(
                run_id=spec.run_id,
                semantic_threshold=spec.epsilon,
                execution_threshold=spec.execution_threshold,
                top_k=spec.top_k,
                global_delta=spec.global_delta,
                task_index=task_index,
                deterministic_seed=spec.random_seed,
                metadata={
                    "experiment_spec_hash": spec.spec_hash,
                    "method": policy.method_id.value,
                    "ablations": list(spec.ablations.enabled),
                },
            ),
            alignment_provider=candidate_artifact.alignment_provider(),
            semantic_scorer=DirectionalOntologySemanticDeviationScorer(
                dataset.ontology, spec.semantic_deviation
            ),
            backend_profiles=profiles,
            exchange_catalog=ExchangeCatalog(strategies=()),
            budget_policy=_budget_policy(spec.budget),
            cost_estimator=RegistryCostEstimator(
                planning_registry,
                use_uncertainty=policy.use_gp_uncertainty,
            ),
            physical_compiler=ExistingCompilerAdapter(
                backend_mapping=dataset.backend_mapping
            ),
        )
        planning_latency = time.perf_counter() - planning_started
        outcomes, observations, measurement_rows = _execute_selected_plans(
            spec=spec,
            task_index=task_index,
            task_id=task_id,
            question_id=question.question_id,
            result=method_result,
            clients=execution_clients,
            extractor=extractor,
            registry=planning_registry,
            measurement_source=measurement_source,
        )
        if policy.online_update:
            assert snapshot is not None
            successful_plan_ids = tuple(
                item.physical_plan_id for item in observations
            )
            commit = lifecycle.complete_task(
                snapshot=snapshot,
                batch_id=f"{task_id}-atomic-batch",
                executed_plan_ids=successful_plan_ids,
                observations=observations,
            )
            posterior_updates = [item.to_dict() for item in commit.updates]
            current_registry = commit.registry
            posterior_change_diagnostics = _posterior_change_diagnostics(
                pre_registry=planning_registry,
                post_registry=current_registry,
                outcomes=outcomes,
                observations=observations,
                task_index=task_index,
            )
        else:
            posterior_updates = [
                {
                    "schema_version": "m12d-posterior-update-disabled-v1",
                    "task_index": task_index,
                    "task_id": task_id,
                    "status": "disabled",
                    "reason": "method_policy_freezes_D0",
                    "observation_count_recorded_for_evaluation": len(observations),
                }
            ]
            posterior_change_diagnostics = {
                "status": "disabled",
                "reason": "method_policy_freezes_D0",
                "records": [],
            }

        task_record = {
            "schema_version": "m12d-task-record-v1",
            "task_index": task_index,
            "task_id": task_id,
            "question_id": question.question_id,
            "status": "complete",
            "method": policy.to_dict(),
            "ablations": spec.ablations.to_dict(),
            "candidate_artifact": {
                "path": str(candidate_path),
                "artifact_hash": candidate_artifact.artifact_hash,
                "candidate_hash": candidate_artifact.candidate_hash,
                "prompt_hash": candidate_artifact.prompt_hash,
                "model_snapshot": candidate_artifact.model_snapshot,
                "grounding_hash": candidate_artifact.grounding_hash,
            },
            "pre_task_posterior": snapshot_data,
            "planning_latency_seconds": planning_latency,
            "planner_result": method_result.planner_result.to_dict(),
            "search_trace": [
                {
                    **event.to_dict(),
                    "method": policy.method_id.value,
                    "ablations": list(spec.ablations.enabled),
                    "budget": dict(spec.budget),
                    "seed": spec.random_seed,
                    "pre_task_posterior_hash": content_hash(snapshot_data),
                }
                for event in method_result.planner_result.traces
            ],
            "sampled_decisions": [dict(item) for item in method_result.sampled_decisions],
            "execution_results": [item.to_dict() for item in outcomes],
            "execution_measurements": measurement_rows,
            "online_observations": [item.to_dict() for item in observations],
            "posterior_updates": posterior_updates,
            "posterior_change_diagnostics": posterior_change_diagnostics,
            "posterior_commit_timing": "after_all_task_executions",
            "within_task_update": False,
        }
        _write_atomic_json(
            run_root / "tasks" / f"{task_index:06d}.json", task_record
        )
        _write_selected_plan_files(
            run_root, question.question_id, method_result.planner_result
        )
        completed_this_call += 1
        _rebuild_run_logs(run_root, spec)

    task_files = _completed_task_files(run_root)
    finished = len(task_files) == len(questions)
    status = "complete" if finished else "incomplete"
    _finalize_run(
        run_root=run_root,
        spec=spec,
        dataset=dataset,
        model=model,
        policy=policy.to_dict(),
        calibration_root=calibration_root,
        measurement_source=measurement_source,
        status=status,
    )
    inventory = tuple(
        str(path.relative_to(run_root))
        for path in sorted(run_root.rglob("*"))
        if path.is_file()
    )
    return OnlineRunResult(
        run_root=run_root,
        run_id=spec.run_id,
        status=status,
        completed_task_count=len(task_files),
        total_task_count=len(questions),
        resumed=resumed,
        inventory=inventory,
    )


def _candidate_artifact(
    *,
    spec: ExperimentSpec,
    dataset: DatasetBundle,
    model: ModelBundle,
    question: Any,
    task_id: str,
    run_root: Path,
    repo_root: Path,
    transport_override: OpenAICompatibleTransport | None,
) -> tuple[FrozenCandidateArtifact, Path]:
    orchestration = dict(spec.orchestration)
    mode = str(orchestration.get("candidate_mode", "generate_once"))
    shared_ref = orchestration.get("candidate_artifact_dir")
    directory = (
        _resolve(str(shared_ref), repo_root)
        if shared_ref
        else run_root / "candidate_artifacts"
    )
    freeze_key = content_hash(
        {
            "schema_version": "m12d-candidate-freeze-key-v1",
            "dataset_hash": dataset.bundle_hash,
            "model_config_hash": model.config.config_hash,
            "prompt_hash": model.prompt.prompt_hash,
            "question_id": question.question_id,
            "question": question.text,
            "candidate_cap": spec.candidate_cap,
            "experiment_seed": spec.random_seed,
        }
    )
    path = directory / freeze_key[:20] / f"{question.question_id}.json"
    if path.exists():
        artifact = FrozenCandidateArtifact.load(path)
        if artifact.question != question.text:
            raise ValueError("Frozen candidate question text does not match the workload.")
        if (
            artifact.dataset_id != dataset.dataset_id
            or artifact.dataset_version != dataset.version
        ):
            raise ValueError("Frozen candidate dataset identity mismatch.")
        if artifact.model_config_hash != model.config.config_hash:
            raise ValueError("Frozen candidate model configuration hash mismatch.")
        if artifact.prompt_hash != model.prompt.prompt_hash:
            raise ValueError("Frozen candidate prompt hash mismatch.")
        expected_max_candidates = (
            spec.candidate_cap
            if model.config.provider == "mock"
            else min(spec.candidate_cap, model.config.candidate_count)
        )
        if artifact.max_candidates != expected_max_candidates:
            raise ValueError("Frozen candidate cap mismatch.")
        if artifact.metadata.get("candidate_freeze_key") != freeze_key:
            raise ValueError("Frozen candidate comparison key mismatch.")
        return artifact, path
    if mode == "frozen":
        raise FileNotFoundError(f"Frozen candidate artifact is missing: {path}")
    artifact = generate_frozen_candidate_artifact(
        dataset=dataset,
        model=model,
        question=question,
        backend_ids=spec.backend_ids,
        max_candidates=spec.candidate_cap,
        task_id=task_id,
        runtime_grounding=spec.runtime_grounding,
        transport_override=transport_override,
    )
    artifact = replace(
        artifact,
        metadata={
            **dict(artifact.metadata),
            "candidate_freeze_key": freeze_key,
            "comparison_seed": spec.random_seed,
        },
    )
    artifact.write(path)
    return artifact, path


def _execute_selected_plans(
    *,
    spec: ExperimentSpec,
    task_index: int,
    task_id: str,
    question_id: str,
    result: MethodPlanningResult,
    clients: Mapping[str, BackendClient],
    extractor: DeterministicStateFeatureExtractor,
    registry: Any,
    measurement_source: str,
) -> tuple[
    tuple[ExecutionOutcome, ...],
    tuple[ExecutionObservation, ...],
    list[dict[str, Any]],
]:
    outcomes: list[ExecutionOutcome] = []
    observations: list[ExecutionObservation] = []
    measurement_rows: list[dict[str, Any]] = []
    protocol_hash = content_hash(spec.execution_protocol.to_dict())
    order = 0
    for selected in result.planner_result.selected_plans:
        plan = selected.physical_plan
        backend_ids = plan.state.selected_backend_ids
        compilation = plan.realization.compilation
        if len(backend_ids) != 1 or plan.state.exchanges or len(compilation.artifacts) != 1:
            raise NotImplementedError(
                "M12-D executes only one-backend, exchange-free complete plans with "
                "exactly one M9 native query artifact; distributed execution and "
                "movement measurement are unavailable."
            )
        backend_id = backend_ids[0]
        client = clients[backend_id]
        batch = measure_complete_plan(
            calibration_id=f"{spec.run_id}-online",
            query_id=question_id,
            plan=plan,
            backend_id=backend_id,
            client=client,
            protocol=spec.execution_protocol,
            feature_extractor=extractor,
            measurement_protocol_hash=protocol_hash,
            machine_metadata={
                "python_version": platform.python_version(),
                "measurement_source": measurement_source,
            },
            backend_metadata={"online_evaluation": True},
            start_order=order,
        )
        order += len(batch.measurements)
        measurement_rows.extend(item.to_dict() for item in batch.measurements)
        artifact = compilation.artifacts[0]
        failure = None
        if batch.status is not CalibrationStatus.SUCCESS:
            failure = _measurement_failure(batch.status)
        outcome = ExecutionOutcome(
            run_id=spec.run_id,
            task_index=task_index,
            task_id=task_id,
            question_id=question_id,
            candidate_id=selected.candidate_id,
            backend_id=backend_id,
            plan=plan,
            query_artifact=artifact,
            measurement_batch=batch,
            rows=batch.representative_rows,
            failure_category=failure,
            metadata={
                "measurement_source": measurement_source,
                "t_max_ms": spec.execution_threshold,
                "measured_t_max_passed": (
                    batch.aggregated_cost_ms < spec.execution_threshold
                    if batch.aggregated_cost_ms is not None
                    else None
                ),
            },
        )
        outcomes.append(outcome)
        if batch.status is CalibrationStatus.SUCCESS:
            estimator = registry.get(backend_id)
            observations.append(
                make_online_execution_observation(
                    task_id=task_id,
                    query_id=question_id,
                    batch_id=f"{task_id}-atomic-batch",
                    backend_id=backend_id,
                    plan=plan,
                    batch=batch,
                    feature_extractor=extractor,
                    estimator_version=estimator.model_version,
                    sequence=len(estimator.observations) + len(observations) + 1,
                    measurement_source=measurement_source,
                )
            )
    return tuple(outcomes), tuple(observations), measurement_rows


def _measurement_failure(status: CalibrationStatus) -> str:
    if status is CalibrationStatus.BACKEND_UNAVAILABLE:
        return ExperimentFailureCategory.BACKEND_UNAVAILABLE.value
    if status is CalibrationStatus.TIMEOUT:
        return ExperimentFailureCategory.TIMEOUT.value
    return ExperimentFailureCategory.BACKEND_ERROR.value


def _posterior_change_diagnostics(
    *,
    pre_registry: Any,
    post_registry: Any,
    outcomes: tuple[ExecutionOutcome, ...],
    observations: tuple[ExecutionObservation, ...],
    task_index: int,
) -> dict[str, Any]:
    outcomes_by_plan = {item.plan.plan_id: item for item in outcomes}
    confidence = ConfidenceContext(
        delta=0.05,
        state_space_bound=1,
        task_index=task_index,
        interpretation_count=1,
    )
    records = []
    for observation in observations:
        outcome = outcomes_by_plan.get(observation.physical_plan_id)
        if outcome is None:
            raise ValueError("Posterior diagnostic is missing its executed plan state.")
        backend_id = outcome.backend_id
        before = pre_registry.get(backend_id).predict(outcome.plan.state, confidence)
        after = post_registry.get(backend_id).predict(outcome.plan.state, confidence)
        mean_changed = not math.isclose(before.mu, after.mu, rel_tol=1e-12, abs_tol=1e-12)
        variance_changed = not math.isclose(
            before.sigma, after.sigma, rel_tol=1e-12, abs_tol=1e-12
        )
        records.append(
            {
                "backend_id": backend_id,
                "physical_plan_id": observation.physical_plan_id,
                "pre_mu_log_ms": before.mu,
                "post_mu_log_ms": after.mu,
                "pre_sigma": before.sigma,
                "post_sigma": after.sigma,
                "mean_changed": mean_changed,
                "variance_changed": variance_changed,
                "informative_change": mean_changed or variance_changed,
                "confidence_context": confidence.to_dict(),
            }
        )
    return {
        "status": "available" if records else "not_available",
        "reason": None if records else "No successful online observation was committed.",
        "records": records,
    }


def _fragment_failure_category(fragment: FragmentSupport) -> str:
    categories = {
        FragmentSupport.COMPILER_UNSUPPORTED: (
            ExperimentFailureCategory.COMPILER_UNSUPPORTED.value
        ),
        FragmentSupport.REPRESENTATION_UNSUPPORTED: (
            ExperimentFailureCategory.REPRESENTATION_UNSUPPORTED.value
        ),
        FragmentSupport.DATASET_MAPPING_FAILURE: (
            ExperimentFailureCategory.MISSING_MAPPING.value
        ),
    }
    try:
        return categories[fragment]
    except KeyError as error:
        raise ValueError(f"No failure category for fragment support '{fragment.value}'.") from error


def _clients(
    *,
    spec: ExperimentSpec,
    offline: bool,
    injected: Mapping[str, BackendClient] | None,
) -> dict[str, BackendClient]:
    if offline and injected is not None:
        raise ValueError("Use either offline clients or injected clients, not both.")
    if offline:
        return {
            backend_id: DeterministicOfflineExecutionClient(backend_id)
            for backend_id in spec.backend_ids
        }
    if injected is not None:
        missing = set(spec.backend_ids) - set(injected)
        if missing:
            raise ValueError(f"Missing injected clients: {sorted(missing)}")
        return {backend_id: injected[backend_id] for backend_id in spec.backend_ids}
    if os.environ.get("XGAP_RUN_BACKENDS") != "1":
        raise RuntimeError("Real M12-D execution requires XGAP_RUN_BACKENDS=1.")
    result: dict[str, BackendClient] = {}
    for backend_id in spec.backend_ids:
        descriptor = _descriptor_with_timeout(
            backend_registry.get(backend_id), spec.execution_protocol.timeout_seconds
        )
        if backend_id == "neo4j":
            result[backend_id] = Neo4jClient(descriptor)
        elif backend_id == "fuseki":
            result[backend_id] = FusekiClient(descriptor)
        else:
            raise NotImplementedError(
                f"M12-D has no real execution client for '{backend_id}'."
            )
    return result


def _descriptor_with_timeout(
    descriptor: BackendDescriptor, timeout_seconds: float
) -> BackendDescriptor:
    return BackendDescriptor(
        id=descriptor.id,
        engine=descriptor.engine,
        language=descriptor.language,
        data_model=descriptor.data_model,
        deployment=descriptor.deployment,
        capabilities=descriptor.capabilities,
        runtime={**dict(descriptor.runtime), "timeout_seconds": timeout_seconds},
    )


def _frozen_d0_snapshot(
    registry: Any, *, task_index: int, task_id: str
) -> dict[str, Any]:
    return {
        "schema_version": "m12d-frozen-d0-snapshot-v1",
        "task_index": task_index,
        "task_id": task_id,
        "posterior_source": "D0",
        "observation_counts": {
            backend_id: len(registry.get(backend_id).observations)
            for backend_id in registry.list_backends()
        },
        "model_hashes": {
            backend_id: registry.model_hash(backend_id)
            for backend_id in registry.list_backends()
        },
        "hyperparameter_hashes": {
            backend_id: registry.hyperparameter_hash(backend_id)
            for backend_id in registry.list_backends()
        },
        "online_update": False,
    }


def _initialize_or_open_run(
    run_root: Path, *, spec: ExperimentSpec, resume: bool
) -> bool:
    if run_root.exists() and any(run_root.iterdir()):
        existing = run_root / "experiment_spec.json"
        if not existing.exists():
            raise FileExistsError(f"Run collision without a spec artifact: {run_root}")
        stored = _load_json(existing)
        if stored.get("spec_hash") != spec.spec_hash:
            raise ValueError("Run collision: existing ExperimentSpec hash differs.")
        summary_path = run_root / "run_summary.json"
        if summary_path.exists() and _load_json(summary_path).get("status") == "complete":
            raise FileExistsError(f"Completed run will not be overwritten: {run_root}")
        if not resume:
            raise FileExistsError(f"Incomplete run requires explicit resume: {run_root}")
        return True
    for relative in (
        "tasks",
        "candidate_artifacts",
        "plans/logical",
        "plans/physical",
        "queries",
        "results/raw",
        "results/normalized",
    ):
        (run_root / relative).mkdir(parents=True, exist_ok=True)
    _write_atomic_json(run_root / "experiment_spec.json", spec.to_dict())
    return False


def _completed_task_files(run_root: Path) -> tuple[Path, ...]:
    files = tuple(sorted((run_root / "tasks").glob("*.json")))
    expected = [f"{index:06d}.json" for index in range(1, len(files) + 1)]
    if [item.name for item in files] != expected:
        raise ValueError("Task checkpoint sequence is not contiguous.")
    return files


def _rebuild_run_logs(run_root: Path, spec: ExperimentSpec) -> None:
    tasks = tuple(_load_json(path) for path in _completed_task_files(run_root))
    progress = []
    posterior = []
    observations = []
    executions = []
    measurements = []
    traces = []
    selected = []
    candidate_rows = []
    llm_requests = []
    raw_model_responses = []
    for task in tasks:
        progress.append(
            {
                "task_index": task["task_index"],
                "task_id": task["task_id"],
                "question_id": task["question_id"],
                "status": task["status"],
                "candidate_artifact": task.get("candidate_artifact"),
                "pre_task_posterior": task.get("pre_task_posterior"),
            }
        )
        posterior.extend(task.get("posterior_updates", []))
        observations.extend(task.get("online_observations", []))
        executions.extend(task.get("execution_results", []))
        measurements.extend(task.get("execution_measurements", []))
        traces.extend(task.get("search_trace", []))
        candidate_ref = task.get("candidate_artifact")
        if isinstance(candidate_ref, Mapping) and candidate_ref.get("path"):
            frozen = FrozenCandidateArtifact.load(str(candidate_ref["path"]))
            response = frozen.planner_response().to_dict()
            candidate_rows.extend(
                {
                    "question_id": frozen.question_id,
                    "candidate_artifact_hash": frozen.artifact_hash,
                    **candidate,
                }
                for candidate in response["candidates"]
            )
            llm_requests.extend(
                {"question_id": frozen.question_id, **dict(item)}
                for item in frozen.llm_requests
            )
            raw_model_responses.extend(
                {"question_id": frozen.question_id, **dict(item)}
                for item in frozen.raw_model_responses
            )
        planner = task.get("planner_result")
        if isinstance(planner, Mapping):
            selected.extend(planner.get("selected_plans", []))
    _write_atomic_jsonl(run_root / "task_progress.jsonl", progress)
    _write_atomic_jsonl(run_root / "posterior_updates.jsonl", posterior)
    _write_atomic_jsonl(run_root / "online_observations.jsonl", observations)
    _write_atomic_jsonl(run_root / "execution_results.jsonl", executions)
    _write_atomic_jsonl(run_root / "execution_measurements.jsonl", measurements)
    _write_atomic_jsonl(run_root / "plans/search_trace.jsonl", traces)
    _write_atomic_jsonl(run_root / "selected_plans.jsonl", selected)
    _write_atomic_jsonl(run_root / "candidates.jsonl", candidate_rows)
    _write_atomic_jsonl(run_root / "llm_requests.jsonl", llm_requests)
    _write_atomic_jsonl(
        run_root / "raw_model_responses.jsonl", raw_model_responses
    )
    _write_atomic_json(
        run_root / "checkpoint.json",
        {
            "schema_version": "m12d-checkpoint-v1",
            "spec_hash": spec.spec_hash,
            "completed_question_ids": [item["question_id"] for item in progress],
            "next_task_index": len(progress) + 1,
            "task_record_hashes": [content_hash(item) for item in tasks],
        },
    )


def _write_selected_plan_files(
    run_root: Path, question_id: str, result: MainPlannerResult
) -> None:
    for record in result.candidate_records:
        if record.formatted_logical_plan is not None:
            _write_atomic_json(
                run_root / "plans" / "logical" / f"{question_id}__{record.candidate_id}.json",
                {
                    "logical_plan_id": record.logical_plan_id,
                    "formatted_plan": record.formatted_logical_plan,
                },
            )
    for selected in result.selected_plans:
        stem = f"{question_id}__{selected.candidate_id}"
        _write_atomic_json(
            run_root / "plans" / "physical" / f"{stem}.json", selected.to_dict()
        )
        for index, artifact in enumerate(
            selected.physical_plan.realization.compilation.artifacts, 1
        ):
            extension = "cypher" if artifact.language.lower() == "cypher" else "rq"
            path = run_root / "queries" / f"{stem}__{index}.{extension}"
            path.write_text(artifact.text + "\n", encoding="utf-8")


def _finalize_run(
    *,
    run_root: Path,
    spec: ExperimentSpec,
    dataset: DatasetBundle,
    model: ModelBundle,
    policy: Mapping[str, Any],
    calibration_root: Path,
    measurement_source: str,
    status: str,
) -> None:
    tasks = tuple(_load_json(path) for path in _completed_task_files(run_root))
    planner_results = tuple(
        _planner_result_shell(item["planner_result"])
        for item in tasks
        if isinstance(item.get("planner_result"), Mapping)
    )
    outcomes = tuple(
        _outcome_shell(item)
        for task in tasks
        for item in task.get("execution_results", [])
        if isinstance(item, Mapping)
    )
    metrics = _summarize_serialized_metrics(tasks, planner_results, outcomes)
    _write_atomic_json(run_root / "metrics.json", metrics)
    _write_atomic_json(run_root / "method_config.json", policy)
    _write_atomic_json(run_root / "ablation_config.json", spec.ablations.to_dict())
    _write_atomic_json(
        run_root / "paper_freeze_manifest.json",
        {
            "schema_version": "m12d-paper-freeze-manifest-v1",
            "status": "contract_only" if spec.orchestration.get("experiment_mode") != "paper" else "candidate",
            "dataset_bundle_hash": dataset.bundle_hash,
            "ontology_hash": dataset.ontology.ontology_hash,
            "schema_snapshot_hash": dataset.schema_snapshot.content_hash,
            "model_bundle_hash": model.bundle_hash,
            "prompt_hash": model.prompt.prompt_hash,
            "structured_schema_hash": model.config.structured_schema_hash,
            "semantic_deviation_hash": spec.semantic_deviation.config_hash,
            "feature_schema_hash": spec.feature_schema.schema_hash,
            "calibration_artifact_hash": _directory_hash(calibration_root),
            "method_hash": content_hash(policy),
            "ablation_hash": content_hash(spec.ablations.to_dict()),
            "epsilon": spec.epsilon,
            "budget": dict(spec.budget),
            "top_k": spec.top_k,
            "candidate_cap": spec.candidate_cap,
            "execution_protocol_hash": content_hash(spec.execution_protocol.to_dict()),
            "seed_policy": {
                "planner_seed": spec.random_seed,
                "llm_seed": model.config.seed,
                "llm_seed_status": "supported" if model.config.seed_supported else "unsupported",
            },
            "backend_versions": {
                "status": "captured_by_readiness_manifest",
                "paper_requires_pinned_images": True,
            },
        },
    )
    from xgap.experiments.readiness import (
        capture_environment_manifest,
        configured_backend_images,
    )

    images = configured_backend_images(_repo_root() / "services" / "docker-compose.yml")
    environment = capture_environment_manifest(_repo_root(), images=images)
    environment["dataset_bundle_hash"] = dataset.bundle_hash
    environment["model_bundle_hash"] = model.bundle_hash
    environment["calibration_artifact_hash"] = _directory_hash(calibration_root)
    _write_atomic_json(run_root / "server_environment.json", environment)
    _write_atomic_json(
        run_root / "run_summary.json",
        {
            "schema_version": "m12d-run-summary-v1",
            "run_id": spec.run_id,
            "status": status,
            "completed_task_count": len(tasks),
            "configured_task_count": len(spec.question_ids),
            "method": spec.baseline.baseline_id.value,
            "ablations": list(spec.ablations.enabled),
            "measurement_source": measurement_source,
            "spec_hash": spec.spec_hash,
        },
    )


def _summarize_serialized_metrics(
    tasks: tuple[dict[str, Any], ...],
    planner_results: tuple[Any, ...],
    outcomes: tuple[Any, ...],
) -> dict[str, Any]:
    del planner_results, outcomes
    planning = [
        float(item["planning_latency_seconds"])
        for item in tasks
        if item.get("planning_latency_seconds") is not None
    ]
    execution_rows = [
        row
        for task in tasks
        for row in task.get("execution_results", [])
        if isinstance(row, Mapping)
    ]
    searches = [
        record["search"]
        for task in tasks
        if isinstance(task.get("planner_result"), Mapping)
        for record in task["planner_result"].get("candidate_records", [])
        if isinstance(record, Mapping) and isinstance(record.get("search"), Mapping)
    ]
    generated = sum(int(item.get("generated_count", 0)) for item in searches)
    processed = sum(int(item.get("processed_count", 0)) for item in searches)
    pruned = sum(int(item.get("pruned_count", 0)) for item in searches)
    successful = [row for row in execution_rows if row.get("result_status") != "execution_error"]
    empty = [row for row in successful if row.get("result_status") == "execution_success_empty"]
    prediction_rows = [
        row["prediction"]
        for row in successful
        if isinstance(row.get("prediction"), Mapping)
        and row["prediction"].get("status") == "available"
    ]
    return {
        "schema_version": "m12d-aggregate-ready-metrics-v1",
        "planning_latency_seconds": _numeric_summary(planning),
        "states_generated": generated,
        "states_processed": processed,
        "states_pruned": pruned,
        "pruning_ratio": pruned / max(1, generated),
        "search_reduction": 1.0 - processed / max(1, generated),
        "execution_count": len(execution_rows),
        "success_rate": len(successful) / max(1, len(execution_rows)),
        "empty_result_rate": len(empty) / max(1, len(successful)),
        "row_count": _numeric_summary(
            [float(row["row_count"]) for row in successful if row.get("row_count") is not None]
        ),
        "backend_latency_ms": _numeric_summary(
            [float(row["actual_cost_ms"]) for row in successful if row.get("actual_cost_ms") is not None]
        ),
        "cost_prediction_absolute_error_ms": _numeric_summary(
            [float(row["absolute_error_ms"]) for row in prediction_rows]
        ),
        "empirical_confidence_coverage": (
            sum(bool(row["confidence_covered"]) for row in prediction_rows)
            / max(1, len(prediction_rows))
        ),
        "confidence_coverage_is_theoretical_proof": False,
        "gold_answer_metrics": {
            "status": "not_available",
            "reason": "Only computed for authored compatible gold answer shapes.",
        },
    }


def _planner_result_shell(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return value


def _outcome_shell(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return value


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "stddev": None}
    ordered = sorted(values)
    mean = sum(ordered) / len(ordered)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    variance = sum((item - mean) ** 2 for item in ordered) / len(ordered)
    return {
        "count": len(ordered),
        "mean": mean,
        "median": median,
        "stddev": variance**0.5,
    }


def _write_atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_atomic_jsonl(path: Path, values: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
                + "\n"
            )
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} must contain a JSON object.")
    return dict(data)


def _directory_hash(path: Path) -> str:
    records = []
    for file_path in sorted(path.rglob("*")):
        if file_path.is_file():
            records.append(
                {
                    "path": str(file_path.relative_to(path)),
                    "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                }
            )
    return content_hash(records)


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object.")
    return dict(value)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve(path: str | Path, repo_root: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else repo_root / value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run resumable M12-D online tasks.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--calibration-root")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after-tasks", type=int)
    args = parser.parse_args(argv)
    result = run_online_experiment(
        args.config,
        output_root_override=args.output_root,
        calibration_root_override=args.calibration_root,
        offline=args.offline,
        resume=args.resume,
        stop_after_tasks=args.stop_after_tasks,
    )
    print(f"M12-D run status: {result.status}")
    print(f"Tasks: {result.completed_task_count}/{result.total_task_count}")
    print(f"Artifacts: {result.run_root}")
    return 0 if result.status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
