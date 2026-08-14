"""M12-C across-task posterior lifecycle with atomic task batches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from xgap.experiments.cost_calibration import (
    BackendCostModelRegistry,
    MeasurementBatch,
    observation_backend_id,
)
from xgap.experiments.calibration_contracts import CalibrationStatus
from xgap.experiments.hashing import content_hash
from xgap.planning import ExecutionObservation, PhysicalPlan, make_execution_observation
from xgap.planning.protocols import StateFeatureExtractor


def make_online_execution_observation(
    *,
    task_id: str,
    query_id: str,
    batch_id: str,
    backend_id: str,
    plan: PhysicalPlan,
    batch: MeasurementBatch,
    feature_extractor: StateFeatureExtractor,
    estimator_version: str,
    sequence: int,
    measurement_source: str,
) -> ExecutionObservation:
    if batch.status is not CalibrationStatus.SUCCESS or batch.aggregated_cost_ms is None:
        raise ValueError("Online GP observations require successful execution batches.")
    measured_ids = tuple(
        item.measurement_id
        for item in batch.measurements
        if item.phase == "measured" and item.status is CalibrationStatus.SUCCESS
    )
    if not measured_ids:
        raise ValueError("Online GP observations require persisted measured repetitions.")
    if not measurement_source:
        raise ValueError("Online GP observations require measurement-source provenance.")
    placement_backends = {item.backend_id for item in plan.state.placements}
    if placement_backends != {backend_id} or plan.state.exchanges:
        raise ValueError("Online GP observations must be backend-local and exchange-free.")
    if any(
        item.physical_plan_id != plan.plan_id or item.backend_id != backend_id
        for item in batch.measurements
    ):
        raise ValueError("Online execution evidence must refer to the observed physical plan.")
    observed_at = next(
        (item.ended_at for item in reversed(batch.measurements) if item.ended_at),
        "not_available",
    )
    return make_execution_observation(
        plan=plan,
        raw_cost=batch.aggregated_cost_ms,
        query_id=query_id,
        task_id=task_id,
        alignment_ref=f"online:{task_id}",
        feature_vector=feature_extractor.features(plan.state),
        estimator_version=estimator_version,
        observed_at=observed_at,
        sequence=sequence,
        provenance={
            "observation_scope": "online_evaluation",
            "execution_status": "success",
            "execution_measurement_ids": list(measured_ids),
            "execution_evidence_hash": content_hash(list(measured_ids)),
            "measurement_source": measurement_source,
            "backend_id": backend_id,
            "batch_id": batch_id,
            "cost_unit": "milliseconds",
        },
    )


@dataclass(frozen=True)
class TaskPosteriorSnapshot:
    task_index: int
    task_id: str
    registry: BackendCostModelRegistry
    observation_counts: tuple[tuple[str, int], ...]
    model_hashes: tuple[tuple[str, str], ...]
    hyperparameter_hashes: tuple[tuple[str, str], ...]

    @property
    def snapshot_id(self) -> str:
        return "posterior-snapshot-" + content_hash(self.to_dict())[:20]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "m12c-task-posterior-snapshot-v1",
            "task_index": self.task_index,
            "task_id": self.task_id,
            "observation_counts": dict(self.observation_counts),
            "model_hashes": dict(self.model_hashes),
            "hyperparameter_hashes": dict(self.hyperparameter_hashes),
            "hyperparameters_frozen": True,
        }


@dataclass(frozen=True)
class PosteriorUpdateRecord:
    task_index: int
    task_id: str
    batch_id: str
    backend_id: str
    batch_size: int
    backend_observation_count: int
    pre_task_observation_count: int
    pre_task_model_hash: str
    executed_plan_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    observation_log_costs: tuple[float, ...]
    post_task_observation_count: int
    post_task_model_hash: str
    hyperparameter_hash: str
    hyperparameters_unchanged: bool
    schema_version: str = "m12c-posterior-update-v1"

    def __post_init__(self) -> None:
        if self.task_index <= 0 or not self.task_id or not self.batch_id:
            raise ValueError("Posterior update task and batch identifiers are required.")
        if self.backend_observation_count != len(self.executed_plan_ids):
            raise ValueError("Backend observation count must match backend plan count.")
        if self.batch_size < self.backend_observation_count:
            raise ValueError("Task batch size cannot be smaller than a backend-local batch.")
        if len(self.observation_ids) != len(self.observation_log_costs):
            raise ValueError("Posterior observation IDs and values must align.")
        if not self.hyperparameters_unchanged:
            raise ValueError("M12-C evaluation updates must preserve GP hyperparameters.")
        object.__setattr__(self, "executed_plan_ids", tuple(self.executed_plan_ids))
        object.__setattr__(self, "observation_ids", tuple(self.observation_ids))
        object.__setattr__(self, "observation_log_costs", tuple(self.observation_log_costs))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_index": self.task_index,
            "task_id": self.task_id,
            "batch_id": self.batch_id,
            "backend_id": self.backend_id,
            "batch_size": self.batch_size,
            "backend_observation_count": self.backend_observation_count,
            "pre_task_observation_count": self.pre_task_observation_count,
            "pre_task_model_hash": self.pre_task_model_hash,
            "executed_plan_ids": list(self.executed_plan_ids),
            "observation_ids": list(self.observation_ids),
            "observation_log_costs": list(self.observation_log_costs),
            "post_task_observation_count": self.post_task_observation_count,
            "post_task_model_hash": self.post_task_model_hash,
            "hyperparameter_hash": self.hyperparameter_hash,
            "hyperparameters_unchanged": self.hyperparameters_unchanged,
        }


@dataclass(frozen=True)
class PosteriorCommit:
    registry: BackendCostModelRegistry
    updates: tuple[PosteriorUpdateRecord, ...]
    observations: tuple[ExecutionObservation, ...]


class OnlinePosteriorLifecycle:
    """Own one immutable posterior snapshot per query-processing task."""

    def __init__(self, registry: BackendCostModelRegistry) -> None:
        self._registry = registry
        self._next_task_index = 1
        self._active: TaskPosteriorSnapshot | None = None

    @classmethod
    def restore(
        cls,
        registry: BackendCostModelRegistry,
        *,
        next_task_index: int,
    ) -> "OnlinePosteriorLifecycle":
        if next_task_index <= 0:
            raise ValueError("Restored next_task_index must be positive.")
        lifecycle = cls(registry)
        lifecycle._next_task_index = next_task_index
        return lifecycle

    @property
    def current_registry(self) -> BackendCostModelRegistry:
        return self._registry

    def begin_task(self, *, task_index: int, task_id: str) -> TaskPosteriorSnapshot:
        if self._active is not None:
            raise RuntimeError("A posterior task snapshot is already active.")
        if task_index != self._next_task_index:
            raise ValueError(
                f"Expected task index {self._next_task_index}, received {task_index}."
            )
        if not task_id:
            raise ValueError("Online posterior task_id must be non-empty.")
        backends = self._registry.list_backends()
        snapshot = TaskPosteriorSnapshot(
            task_index=task_index,
            task_id=task_id,
            registry=self._registry,
            observation_counts=tuple(
                (backend_id, len(self._registry.get(backend_id).observations))
                for backend_id in backends
            ),
            model_hashes=tuple(
                (backend_id, self._registry.model_hash(backend_id))
                for backend_id in backends
            ),
            hyperparameter_hashes=tuple(
                (backend_id, self._registry.hyperparameter_hash(backend_id))
                for backend_id in backends
            ),
        )
        self._active = snapshot
        return snapshot

    def complete_task(
        self,
        *,
        snapshot: TaskPosteriorSnapshot,
        batch_id: str,
        executed_plan_ids: Iterable[str],
        observations: Iterable[ExecutionObservation],
    ) -> PosteriorCommit:
        if self._active is None or snapshot is not self._active:
            raise RuntimeError("Posterior completion requires the active task snapshot.")
        if not batch_id:
            raise ValueError("Posterior batch_id must be non-empty.")
        executed = tuple(executed_plan_ids)
        if len(executed) != len(set(executed)):
            raise ValueError("Executed physical plan IDs must be unique within one task.")
        observed = tuple(observations)
        if any(item.task_id != snapshot.task_id for item in observed):
            raise ValueError("Online observations must belong to the active task only.")
        for observation in observed:
            provenance = observation.provenance
            if (
                provenance.get("observation_scope") != "online_evaluation"
                or provenance.get("execution_status") != "success"
                or provenance.get("batch_id") != batch_id
                or not provenance.get("execution_measurement_ids")
            ):
                raise ValueError(
                    "Online posterior updates require successful persisted execution evidence."
                )
        observed_plan_ids = tuple(item.physical_plan_id for item in observed)
        if len(observed_plan_ids) != len(set(observed_plan_ids)):
            raise ValueError("Each executed physical plan contributes at most one task observation.")
        if set(observed_plan_ids) != set(executed):
            raise ValueError(
                "Only actually executed plans may contribute observations, and each must contribute one."
            )

        by_backend: dict[str, list[ExecutionObservation]] = {
            backend_id: [] for backend_id in self._registry.list_backends()
        }
        for observation in observed:
            backend_id = observation_backend_id(observation)
            if backend_id not in by_backend:
                raise ValueError(f"No calibrated posterior exists for backend '{backend_id}'.")
            by_backend[backend_id].append(observation)

        updated_registry = self._registry.with_observation_batch(observed)
        pre_counts = dict(snapshot.observation_counts)
        pre_hashes = dict(snapshot.model_hashes)
        pre_hyperparameters = dict(snapshot.hyperparameter_hashes)
        updates: list[PosteriorUpdateRecord] = []
        for backend_id in self._registry.list_backends():
            backend_observations = tuple(by_backend[backend_id])
            backend_plan_ids = tuple(item.physical_plan_id for item in backend_observations)
            post_hyperparameter_hash = updated_registry.hyperparameter_hash(backend_id)
            updates.append(
                PosteriorUpdateRecord(
                    task_index=snapshot.task_index,
                    task_id=snapshot.task_id,
                    batch_id=batch_id,
                    backend_id=backend_id,
                    batch_size=len(executed),
                    backend_observation_count=len(backend_plan_ids),
                    pre_task_observation_count=pre_counts[backend_id],
                    pre_task_model_hash=pre_hashes[backend_id],
                    executed_plan_ids=backend_plan_ids,
                    observation_ids=tuple(
                        item.observation_id for item in backend_observations
                    ),
                    observation_log_costs=tuple(
                        item.log_cost for item in backend_observations
                    ),
                    post_task_observation_count=len(
                        updated_registry.get(backend_id).observations
                    ),
                    post_task_model_hash=updated_registry.model_hash(backend_id),
                    hyperparameter_hash=post_hyperparameter_hash,
                    hyperparameters_unchanged=(
                        pre_hyperparameters[backend_id] == post_hyperparameter_hash
                    ),
                )
            )

        self._registry = updated_registry
        self._active = None
        self._next_task_index += 1
        return PosteriorCommit(updated_registry, tuple(updates), observed)


def write_posterior_commit(
    commit: PosteriorCommit,
    *,
    posterior_updates_path: str | Path,
    online_observations_path: str | Path,
) -> None:
    updates_path = Path(posterior_updates_path)
    observations_path = Path(online_observations_path)
    updates_path.parent.mkdir(parents=True, exist_ok=True)
    observations_path.parent.mkdir(parents=True, exist_ok=True)
    with updates_path.open("a", encoding="utf-8") as handle:
        for update in commit.updates:
            handle.write(json.dumps(update.to_dict(), sort_keys=True) + "\n")
    with observations_path.open("a", encoding="utf-8") as handle:
        for observation in commit.observations:
            handle.write(json.dumps(observation.to_dict(), sort_keys=True) + "\n")
