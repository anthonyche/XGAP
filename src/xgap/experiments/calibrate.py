"""Server-friendly M12-C backend-local cost calibration runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from xgap.algebra.validation import validate_plan
from xgap.backends import registry
from xgap.backends.capabilities import SupportLevel
from xgap.backends.compatibility import check_backend_support
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.neo4j_client import Neo4jClient
from xgap.backends.protocol import BackendClient
from xgap.compilers.features import plan_from_compiler_input
from xgap.experiments.bundles import DatasetBundle
from xgap.experiments.calibration_contracts import (
    CalibratedGPModelArtifact,
    CalibrationCase,
    CalibrationPlanRecord,
    CalibrationRunConfig,
    CalibrationStatus,
    CalibrationWorkload,
    D0Record,
)
from xgap.experiments.cost_calibration import (
    BackendCostModelRegistry,
    aggregate_latencies,
    backend_unavailable_batch,
    deterministic_stratified_sample,
    fit_backend_gp,
    make_d0_record,
    measure_complete_plan,
)
from xgap.experiments.hashing import content_hash
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern import type_check_path_pattern
from xgap.planning import (
    ConfidenceContext,
    DeterministicStateFeatureExtractor,
    ExistingCompilerAdapter,
    GaussianProcessCostEstimator,
    PhysicalPlan,
    PhysicalRealization,
    PhysicalState,
    PlacementDecision,
    index_logical_plan,
)


@dataclass(frozen=True)
class PreparedCalibrationPlan:
    record: CalibrationPlanRecord
    plan: PhysicalPlan


@dataclass(frozen=True)
class CalibrationRunResult:
    run_root: Path
    status: str
    backend_statuses: Mapping[str, str]
    model_artifacts: Mapping[str, CalibratedGPModelArtifact]
    d0_records: Mapping[str, tuple[D0Record, ...]]
    inventory: tuple[str, ...]
    measurement_source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_root": str(self.run_root),
            "status": self.status,
            "backend_statuses": dict(self.backend_statuses),
            "model_hashes": {
                backend_id: artifact.model_hash
                for backend_id, artifact in self.model_artifacts.items()
            },
            "d0_counts": {
                backend_id: len(records)
                for backend_id, records in self.d0_records.items()
            },
            "inventory": list(self.inventory),
            "measurement_source": self.measurement_source,
        }


class DeterministicOfflineCalibrationClient:
    """Explicit fake client for offline tests and the development demo."""

    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id
        self._execution_index = 0

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(
            backend_id=self.backend_id,
            ok=True,
            message="deterministic offline calibration client",
            checked_at="deterministic",
            details={"measurement_source": "deterministic_offline_fake"},
        )

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self._execution_index += 1
        digest = hashlib.sha256(
            f"{self.backend_id}:{artifact.artifact_id}:{self._execution_index}".encode(
                "utf-8"
            )
        ).hexdigest()
        backend_offset = 2.0 if self.backend_id == "neo4j" else 5.0
        elapsed_ms = backend_offset + (int(digest[:8], 16) % 2000) / 1000.0
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[],
            elapsed_ms=elapsed_ms,
            started_at="deterministic",
            ended_at="deterministic",
            metadata={"measurement_source": "deterministic_offline_fake"},
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve(path: str | Path, repo_root: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else repo_root / value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
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


def _load_cases(path: Path, expected_split: str) -> tuple[CalibrationCase, ...]:
    cases: list[CalibrationCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, Mapping):
            raise ValueError(f"Calibration case line {line_number} must be an object.")
        case = CalibrationCase.from_dict(raw)
        if case.split != expected_split:
            raise ValueError(
                f"Calibration case '{case.case_id}' uses split '{case.split}', "
                f"expected '{expected_split}'."
            )
        cases.append(case)
    if not cases:
        raise ValueError("Calibration cases artifact must be non-empty.")
    if len({item.case_id for item in cases}) != len(cases):
        raise ValueError("Calibration case IDs must be unique.")
    return tuple(cases)


def _prepare_plan(
    *,
    case: CalibrationCase,
    backend_id: str,
    extractor: DeterministicStateFeatureExtractor,
    prior_estimator: GaussianProcessCostEstimator,
    compiler: ExistingCompilerAdapter,
) -> tuple[CalibrationPlanRecord, PreparedCalibrationPlan | None]:
    profile = registry.get_capability_profile(backend_id)
    operator_names: tuple[str, ...] = ()
    try:
        query = parse_path_pattern_query(case.pattern_query)
        type_check_path_pattern(query)
        logical_plan, _, _ = plan_from_compiler_input(
            query,
            backend_id=backend_id,
            language=profile.language,
        )
        validate_plan(logical_plan)
        indexed = index_logical_plan(logical_plan)
        operator_names = tuple(item.operator_name for item in indexed.operators)
        placements: list[PlacementDecision] = []
        for operator in indexed.operators:
            support = check_backend_support(profile, operator.feature_id)
            if support.level is SupportLevel.UNSUPPORTED:
                return (
                    CalibrationPlanRecord(
                        case_id=case.case_id,
                        query_id=case.query_id,
                        interpretation_id=case.interpretation_id,
                        backend_id=backend_id,
                        split=case.split,
                        stratum=case.stratum,
                        status=CalibrationStatus.COMPILE_UNSUPPORTED,
                        logical_plan_id=indexed.logical_plan_id,
                        operator_names=operator_names,
                        reason=support.reason.message,
                    ),
                    None,
                )
            placements.append(
                PlacementDecision(
                    operator_id=operator.operator_id,
                    backend_id=backend_id,
                    feature_id=operator.feature_id,
                    support_level=support.level.value,
                    conditions=support.conditions,
                )
            )
        state = PhysicalState(
            interpretation_id=case.interpretation_id,
            logical_plan_id=indexed.logical_plan_id,
            operators=indexed.operators,
            dependencies=indexed.dependencies,
            placements=tuple(placements),
            exchanges=(),
        )
        if not state.is_complete:
            raise ValueError("Backend-local calibration state did not become complete.")
        feature = extractor.features(state)
        prediction = prior_estimator.predict(
            state,
            ConfidenceContext(delta=0.05, state_space_bound=1),
        )
        compilation = compiler.compile(
            logical_plan,
            state,
            {backend_id: profile},
            pattern_query=query,
        )
        if not compilation.executable or len(compilation.artifacts) != 1:
            reason = compilation.reason_code or compilation.message or compilation.status
            return (
                CalibrationPlanRecord(
                    case_id=case.case_id,
                    query_id=case.query_id,
                    interpretation_id=case.interpretation_id,
                    backend_id=backend_id,
                    split=case.split,
                    stratum=case.stratum,
                    status=CalibrationStatus.COMPILE_UNSUPPORTED,
                    state_id=state.state_id,
                    logical_plan_id=indexed.logical_plan_id,
                    operator_names=operator_names,
                    feature_vector=feature,
                    reason=reason,
                ),
                None,
            )
        realization = PhysicalRealization(
            state_id=state.state_id,
            placements=state.placements,
            exchanges=state.exchanges,
            compilation=compilation,
        )
        physical_plan = PhysicalPlan(
            interpretation_id=case.interpretation_id,
            logical_plan_id=indexed.logical_plan_id,
            state=state,
            realization=realization,
            cost=prediction,
        )
        record = CalibrationPlanRecord(
            case_id=case.case_id,
            query_id=case.query_id,
            interpretation_id=case.interpretation_id,
            backend_id=backend_id,
            split=case.split,
            stratum=case.stratum,
            status=CalibrationStatus.SUCCESS,
            state_id=state.state_id,
            physical_plan_id=physical_plan.plan_id,
            logical_plan_id=indexed.logical_plan_id,
            operator_names=operator_names,
            feature_vector=feature,
            query_artifact=compilation.artifacts[0],
        )
        return record, PreparedCalibrationPlan(record, physical_plan)
    except Exception as error:  # noqa: BLE001 - artifact boundary records the stage.
        record = CalibrationPlanRecord(
            case_id=case.case_id,
            query_id=case.query_id,
            interpretation_id=case.interpretation_id,
            backend_id=backend_id,
            split=case.split,
            stratum=case.stratum,
            status=CalibrationStatus.FEATURE_ERROR,
            operator_names=operator_names,
            reason=str(error),
        )
        return record, None


def _descriptor_with_timeout(
    descriptor: BackendDescriptor,
    timeout_seconds: float,
) -> BackendDescriptor:
    runtime = dict(descriptor.runtime)
    runtime["timeout_seconds"] = timeout_seconds
    return BackendDescriptor(
        id=descriptor.id,
        engine=descriptor.engine,
        language=descriptor.language,
        data_model=descriptor.data_model,
        deployment=descriptor.deployment,
        capabilities=descriptor.capabilities,
        runtime=runtime,
    )


def _live_client(descriptor: BackendDescriptor) -> BackendClient:
    if descriptor.id == "neo4j":
        return Neo4jClient(descriptor)
    if descriptor.id == "fuseki":
        return FusekiClient(descriptor)
    raise NotImplementedError(
        f"M12-C live calibration has no native client for '{descriptor.id}'."
    )


def _machine_metadata() -> dict[str, object]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
    }


def _cost_diagnostics(
    *,
    d0_records: tuple[D0Record, ...],
    selected_plans: tuple[PreparedCalibrationPlan, ...],
    calibrated: GaussianProcessCostEstimator,
    prior: GaussianProcessCostEstimator,
    measurement_rows: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    latencies = tuple(item.raw_execution_cost_ms for item in d0_records)
    repeated_variances = tuple(
        statistics_variance(item.repetition_latencies_ms) for item in d0_records
    )
    confidence = ConfidenceContext(delta=0.05, state_space_bound=1)
    plan_by_id = {item.plan.plan_id: item.plan for item in selected_plans}
    log_errors: list[float] = []
    raw_errors: list[float] = []
    posterior_variances: list[float] = []
    covered = 0
    for held_out in d0_records:
        remaining = tuple(
            item.observation
            for item in d0_records
            if item.d0_record_id != held_out.d0_record_id
        )
        loo = GaussianProcessCostEstimator(
            config=calibrated.config,
            feature_extractor=calibrated.feature_extractor,
            observations=remaining,
        )
        state = plan_by_id[held_out.observation.physical_plan_id].state
        prediction = loo.predict(state, confidence)
        log_errors.append(abs(prediction.mu - held_out.log_execution_cost))
        predicted_raw = math.exp(prediction.mu)
        raw_errors.append(abs(predicted_raw - held_out.raw_execution_cost_ms))
        posterior_variances.append(prediction.sigma**2)
        covered += prediction.lower <= held_out.raw_execution_cost_ms <= prediction.upper
    first_state = plan_by_id[d0_records[0].observation.physical_plan_id].state
    before = prior.predict(first_state, confidence)
    after = calibrated.predict(first_state, confidence)
    return {
        "schema_version": "m12c-cost-diagnostics-v1",
        "observation_count": len(d0_records),
        "successful_measurement_count": sum(
            row.get("phase") == "measured" and row.get("status") == "success"
            for row in measurement_rows
        ),
        "failed_measurement_count": sum(
            row.get("phase") == "measured" and row.get("status") != "success"
            for row in measurement_rows
        ),
        "latency_ms": {
            "min": min(latencies),
            "median": aggregate_latencies(latencies, "median"),
            "max": max(latencies),
            "mean": sum(latencies) / len(latencies),
        },
        "repeated_run_variance_ms2": {
            "values": list(repeated_variances),
            "mean": sum(repeated_variances) / len(repeated_variances),
        },
        "fitted_noise_variance": calibrated.config.noise_variance,
        "leave_one_out": {
            "mean_absolute_error_ms": sum(raw_errors) / len(raw_errors),
            "mean_absolute_log_cost_error": sum(log_errors) / len(log_errors),
            "mean_posterior_variance": sum(posterior_variances)
            / len(posterior_variances),
            "empirical_confidence_coverage": covered / len(d0_records),
        },
        "before_after_pipeline_check": {
            "prior_mu": before.mu,
            "calibrated_mu": after.mu,
            "prior_sigma": before.sigma,
            "calibrated_sigma": after.sigma,
            "changed": not (
                math.isclose(before.mu, after.mu)
                and math.isclose(before.sigma, after.sigma)
            ),
            "accuracy_claim": False,
        },
        "small_sample_warning": (
            "Development calibration diagnostics are pipeline checks and do not "
            "establish statistical significance."
        ),
    }


def statistics_variance(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    average = sum(values) / len(values)
    return sum((value - average) ** 2 for value in values) / (len(values) - 1)


def run_calibration(
    config_path: str | Path,
    *,
    output_root_override: str | Path | None = None,
    clients: Mapping[str, BackendClient] | None = None,
    offline: bool = False,
) -> CalibrationRunResult:
    repo_root = _repo_root()
    config_file = _resolve(config_path, repo_root)
    config = CalibrationRunConfig.load(config_file)
    dataset = DatasetBundle.load(_resolve(config.dataset_bundle_ref, repo_root))
    if dataset.dataset_id != config.dataset_id or dataset.version != config.dataset_version:
        raise ValueError("Calibration config dataset identity does not match DatasetBundle.")
    cases = _load_cases(
        _resolve(config.cases_artifact_ref, repo_root), config.calibration_split
    )
    descriptor_dir = _resolve(config.descriptor_dir, repo_root)
    registry.load_descriptors(descriptor_dir)
    extractor = DeterministicStateFeatureExtractor(
        config.backend_ids,
        optional_stat_names=config.optional_stat_names,
    )
    if extractor.extractor_id != config.feature_extractor_id:
        raise ValueError("Calibration feature extractor ID does not match M11.")
    if extractor.schema_version != config.feature_schema_version:
        raise ValueError("Calibration feature schema version does not match M11.")
    if extractor.schema_hash != config.feature_schema_hash:
        raise ValueError("Calibration feature schema hash does not match M11.")
    prior = GaussianProcessCostEstimator(
        config=config.initial_gp_config,
        feature_extractor=extractor,
        observations=(),
    )
    compiler = ExistingCompilerAdapter()
    output_root = (
        Path(output_root_override)
        if output_root_override is not None
        else _resolve(config.output_root, repo_root)
    )
    run_root = output_root / config.run_id
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"Calibration run directory is not empty: {run_root}")
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "posterior_updates.jsonl").touch()
    (run_root / "online_observations.jsonl").touch()
    _write_json(run_root / "calibration_config.json", config.to_dict())

    if clients is not None and offline:
        raise ValueError("Use either injected clients or offline mode, not both.")
    if clients is None and not offline and os.environ.get("XGAP_RUN_BACKENDS") != "1":
        raise RuntimeError(
            "Real calibration requires XGAP_RUN_BACKENDS=1; use --offline only for fake development measurements."
        )
    if offline:
        measurement_source = "deterministic_offline_fake"
    elif clients is not None:
        measurement_source = "injected_client"
    else:
        measurement_source = "real_backend"
    machine = _machine_metadata()
    protocol_hash = content_hash(config.execution_protocol.to_dict())
    backend_statuses: dict[str, str] = {}
    model_artifacts: dict[str, CalibratedGPModelArtifact] = {}
    d0_by_backend: dict[str, tuple[D0Record, ...]] = {}
    estimators: dict[str, GaussianProcessCostEstimator] = {}
    backend_hashes: dict[str, str] = {}

    for backend_id in config.backend_ids:
        backend_root = run_root / "calibration" / backend_id
        backend_root.mkdir(parents=True, exist_ok=True)
        descriptor = registry.get(backend_id)
        descriptor_hash = content_hash(descriptor.to_dict())
        backend_hashes[backend_id] = descriptor_hash
        records: list[CalibrationPlanRecord] = []
        prepared: dict[str, PreparedCalibrationPlan] = {}
        for case in cases:
            record, ready = _prepare_plan(
                case=case,
                backend_id=backend_id,
                extractor=extractor,
                prior_estimator=prior,
                compiler=compiler,
            )
            records.append(record)
            if ready is not None:
                prepared[ready.plan.plan_id] = ready
        _write_jsonl(
            backend_root / "calibration_plans.jsonl",
            [item.to_dict() for item in records],
        )
        selected_records = deterministic_stratified_sample(
            records,
            sample_count=config.sample_count_per_backend,
            seed=config.random_seed,
        )
        selected = tuple(prepared[str(item.physical_plan_id)] for item in selected_records)
        workload = CalibrationWorkload(
            calibration_id=config.calibration_id,
            dataset_id=config.dataset_id,
            dataset_version=config.dataset_version,
            backend_id=backend_id,
            calibration_split=config.calibration_split,
            evaluation_split=config.evaluation_split,
            sampling_policy_id=config.sampling_policy_id,
            sample_count=config.sample_count_per_backend,
            seed=config.random_seed,
            eligible_physical_plan_ids=tuple(
                str(item.physical_plan_id)
                for item in records
                if item.status is CalibrationStatus.SUCCESS
            ),
            selected_physical_plan_ids=tuple(item.plan.plan_id for item in selected),
            execution_protocol_hash=protocol_hash,
            feature_schema_hash=extractor.schema_hash,
            compiler_id=compiler.compiler_id,
            backend_descriptor_hash=descriptor_hash,
        )
        _write_json(backend_root / "calibration_manifest.json", workload.to_dict())
        _write_json(backend_root / "feature_schema.json", extractor.to_dict())
        for item in selected:
            artifact = item.plan.realization.compilation.artifacts[0]
            extension = "cypher" if artifact.language.lower() == "cypher" else "rq"
            query_path = backend_root / "queries" / f"{item.record.case_id}.{extension}"
            query_path.parent.mkdir(parents=True, exist_ok=True)
            query_path.write_text(artifact.text + "\n", encoding="utf-8")

        if clients is not None:
            if backend_id not in clients:
                raise ValueError(f"No injected calibration client for '{backend_id}'.")
            client = clients[backend_id]
        elif offline:
            client = DeterministicOfflineCalibrationClient(backend_id)
        else:
            client = _live_client(
                _descriptor_with_timeout(
                    descriptor, config.execution_protocol.timeout_seconds
                )
            )
        health = client.healthcheck()
        measurement_rows: list[dict[str, object]] = []
        d0_records: list[D0Record] = []
        order = 0
        for sequence, item in enumerate(selected, 1):
            if health.ok:
                batch = measure_complete_plan(
                    calibration_id=config.calibration_id,
                    query_id=item.record.query_id,
                    plan=item.plan,
                    backend_id=backend_id,
                    client=client,
                    protocol=config.execution_protocol,
                    feature_extractor=extractor,
                    measurement_protocol_hash=protocol_hash,
                    machine_metadata=machine,
                    backend_metadata={
                        "descriptor_hash": descriptor_hash,
                        "healthcheck": health.to_dict(),
                    },
                    start_order=order,
                )
            else:
                batch = backend_unavailable_batch(
                    calibration_id=config.calibration_id,
                    query_id=item.record.query_id,
                    plan=item.plan,
                    backend_id=backend_id,
                    protocol=config.execution_protocol,
                    feature_extractor=extractor,
                    measurement_protocol_hash=protocol_hash,
                    machine_metadata=machine,
                    backend_metadata={
                        "descriptor_hash": descriptor_hash,
                        "healthcheck": health.to_dict(),
                    },
                    order=order,
                    reason=health.message,
                )
            order += len(batch.measurements)
            measurement_rows.extend(record.to_dict() for record in batch.measurements)
            if batch.status is CalibrationStatus.SUCCESS:
                d0_records.append(
                    make_d0_record(
                        calibration_id=config.calibration_id,
                        query_id=item.record.query_id,
                        backend_id=backend_id,
                        split=config.calibration_split,
                        plan=item.plan,
                        feature_extractor=extractor,
                        batch=batch,
                        aggregation_statistic=config.execution_protocol.aggregation_statistic,
                        measurement_protocol_hash=protocol_hash,
                        sequence=sequence,
                        measurement_source=measurement_source,
                    )
                )
        _write_jsonl(backend_root / "execution_measurements.jsonl", measurement_rows)
        _write_jsonl(backend_root / "D0.jsonl", [item.to_dict() for item in d0_records])
        d0_tuple = tuple(d0_records)
        d0_by_backend[backend_id] = d0_tuple
        if not d0_tuple:
            backend_statuses[backend_id] = CalibrationStatus.CALIBRATION_FIT_ERROR.value
            _write_json(
                backend_root / "cost_diagnostics.json",
                {
                    "status": CalibrationStatus.CALIBRATION_FIT_ERROR.value,
                    "reason": "No successful complete-plan measurements were available.",
                    "measurement_statuses": [row["status"] for row in measurement_rows],
                },
            )
            continue
        estimator, artifact = fit_backend_gp(
            backend_id=backend_id,
            d0_records=d0_tuple,
            initial_config=config.initial_gp_config,
            feature_extractor=extractor,
            execution_protocol_hash=protocol_hash,
            backend_descriptor_hash=descriptor_hash,
            random_seed=config.random_seed,
        )
        estimators[backend_id] = estimator
        model_artifacts[backend_id] = artifact
        backend_statuses[backend_id] = CalibrationStatus.SUCCESS.value
        _write_json(run_root / "cost_models" / backend_id / "model.json", artifact.to_dict())
        _write_json(
            backend_root / "cost_diagnostics.json",
            _cost_diagnostics(
                d0_records=d0_tuple,
                selected_plans=selected,
                calibrated=estimator,
                prior=prior,
                measurement_rows=tuple(measurement_rows),
            ),
        )

    if set(model_artifacts) == set(config.backend_ids):
        registry_snapshot = BackendCostModelRegistry(
            estimators,
            {
                backend_id: model_artifacts[backend_id].hyperparameter_hash
                for backend_id in config.backend_ids
            },
        )
        _write_json(run_root / "cost_model_registry.json", registry_snapshot.to_dict())
        status = "ok"
    else:
        status = "incomplete"
    manifest = {
        "schema_version": "m12c-calibration-run-manifest-v1",
        "run_id": config.run_id,
        "calibration_id": config.calibration_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "measurement_source": measurement_source,
        "config_hash": config.config_hash,
        "execution_protocol_hash": protocol_hash,
        "feature_schema_hash": extractor.schema_hash,
        "backend_descriptor_hashes": backend_hashes,
        "backend_statuses": backend_statuses,
        "d0_hashes": {
            backend_id: artifact.d0_hash
            for backend_id, artifact in model_artifacts.items()
        },
        "model_hashes": {
            backend_id: artifact.model_hash
            for backend_id, artifact in model_artifacts.items()
        },
        "hyperparameter_hashes": {
            backend_id: artifact.hyperparameter_hash
            for backend_id, artifact in model_artifacts.items()
        },
        "cross_backend_movement_cost": {
            "status": "not_available",
            "reason": "No distributed cross-backend measurement runtime exists in M12-C.",
        },
        "status": status,
    }
    manifest["manifest_hash"] = content_hash(manifest)
    _write_json(run_root / "calibration_manifest.json", manifest)
    inventory = tuple(
        str(path.relative_to(run_root))
        for path in sorted(run_root.rglob("*"))
        if path.is_file()
    )
    result = CalibrationRunResult(
        run_root=run_root,
        status=status,
        backend_statuses=backend_statuses,
        model_artifacts=model_artifacts,
        d0_records=d0_by_backend,
        inventory=inventory,
        measurement_source=measurement_source,
    )
    _write_json(run_root / "run_summary.json", result.to_dict())
    final_inventory = tuple(
        str(path.relative_to(run_root))
        for path in sorted(run_root.rglob("*"))
        if path.is_file()
    )
    if final_inventory != result.inventory:
        result = CalibrationRunResult(
            run_root=result.run_root,
            status=result.status,
            backend_statuses=result.backend_statuses,
            model_artifacts=result.model_artifacts,
            d0_records=result.d0_records,
            inventory=final_inventory,
            measurement_source=result.measurement_source,
        )
        _write_json(run_root / "run_summary.json", result.to_dict())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate M12-C backend-local GP models.")
    parser.add_argument("--config", required=True, help="Repository-relative calibration JSON config.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use explicit deterministic fake measurements for development only.",
    )
    args = parser.parse_args()
    result = run_calibration(args.config, offline=args.offline)
    print(f"M12-C calibration status: {result.status}")
    print(f"Measurement source: {result.measurement_source}")
    print(f"Artifacts: {result.run_root}")
    for backend_id in sorted(result.backend_statuses):
        count = len(result.d0_records.get(backend_id, ()))
        print(f"{backend_id}: {result.backend_statuses[backend_id]}, D0={count}")
    if result.status != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
