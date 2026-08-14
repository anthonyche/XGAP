"""M12-D execution, prediction, confidence, and search metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from xgap.experiments.calibration_contracts import CalibrationStatus
from xgap.experiments.cost_calibration import MeasurementBatch
from xgap.infrastructure.runtime import QueryArtifact
from xgap.planning import MainPlannerResult, PhysicalPlan


@dataclass(frozen=True)
class ExecutionOutcome:
    run_id: str
    task_index: int
    task_id: str
    question_id: str
    candidate_id: str
    backend_id: str
    plan: PhysicalPlan
    query_artifact: QueryArtifact
    measurement_batch: MeasurementBatch
    rows: tuple[Mapping[str, Any], ...] = ()
    failure_category: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "m12d-execution-outcome-v1"

    def __post_init__(self) -> None:
        if self.task_index <= 0:
            raise ValueError("Execution task_index must be positive.")
        object.__setattr__(self, "rows", tuple(dict(item) for item in self.rows))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def row_count(self) -> int | None:
        if self.measurement_batch.status is not CalibrationStatus.SUCCESS:
            return None
        return len(self.rows)

    @property
    def result_status(self) -> str:
        if self.measurement_batch.status is not CalibrationStatus.SUCCESS:
            return "execution_error"
        return "execution_success_nonempty" if self.row_count else "execution_success_empty"

    @property
    def actual_cost_ms(self) -> float | None:
        return self.measurement_batch.aggregated_cost_ms

    def prediction_metrics(self) -> dict[str, Any]:
        prediction = self.plan.cost
        actual = self.actual_cost_ms
        predicted_raw = math.exp(max(-700.0, min(700.0, prediction.mu)))
        if actual is None:
            return {
                "status": "not_available",
                "reason": "No successful complete-plan execution cost was observed.",
            }
        absolute_error = abs(predicted_raw - actual)
        return {
            "status": "available",
            "predicted_mu_log_ms": prediction.mu,
            "predicted_sigma": prediction.sigma,
            "predicted_raw_cost_ms": predicted_raw,
            "lower_bound_ms": prediction.lower,
            "upper_bound_ms": prediction.upper,
            "actual_raw_cost_ms": actual,
            "actual_log_cost": math.log(actual),
            "absolute_error_ms": absolute_error,
            "relative_error": absolute_error / actual,
            "absolute_log_error": abs(prediction.mu - math.log(actual)),
            "confidence_covered": prediction.lower <= actual <= prediction.upper,
            "empirical_not_theoretical_proof": True,
            "observation_count": prediction.metadata.get("observation_count"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "task_index": self.task_index,
            "task_id": self.task_id,
            "question_id": self.question_id,
            "candidate_id": self.candidate_id,
            "backend_id": self.backend_id,
            "physical_plan_id": self.plan.plan_id,
            "state_id": self.plan.state.state_id,
            "query_artifact": self.query_artifact.to_dict(),
            "measurement_status": self.measurement_batch.status.value,
            "result_status": self.result_status,
            "row_count": self.row_count,
            "rows": [dict(item) for item in self.rows],
            "latencies_ms": list(self.measurement_batch.successful_latencies_ms),
            "actual_cost_ms": self.actual_cost_ms,
            "failure_category": self.failure_category,
            "prediction": self.prediction_metrics(),
            "metadata": dict(self.metadata),
        }


def summarize_run_metrics(
    *,
    planner_results: Sequence[MainPlannerResult],
    outcomes: Sequence[ExecutionOutcome],
    planning_latencies_seconds: Sequence[float],
    llm_latencies_seconds: Sequence[float] = (),
) -> dict[str, Any]:
    records = tuple(
        record for result in planner_results for record in result.candidate_records
    )
    searches = tuple(record.search for record in records if record.search is not None)
    generated = sum(item.generated_count for item in searches)
    processed = sum(item.processed_count for item in searches)
    pruned = sum(item.pruned_count for item in searches)
    predictions = tuple(
        outcome.prediction_metrics()
        for outcome in outcomes
        if outcome.prediction_metrics().get("status") == "available"
    )
    successful = tuple(
        item for item in outcomes if item.result_status != "execution_error"
    )
    nonempty = tuple(
        item for item in outcomes if item.result_status == "execution_success_nonempty"
    )
    empty = tuple(
        item for item in outcomes if item.result_status == "execution_success_empty"
    )
    backend_errors = tuple(
        item for item in outcomes if item.result_status == "execution_error"
    )
    candidate_count = len(records)
    mapping_failures = sum(item.status.startswith("mapping_") for item in records)
    semantic_failures = sum(
        item.status.startswith("semantic_") for item in records
    )
    return {
        "schema_version": "m12d-aggregate-ready-metrics-v1",
        "interpretation": {
            "candidate_count": candidate_count,
            "supported_question_count": len(planner_results),
            "mapping_failure_rate": mapping_failures / max(1, candidate_count),
            "semantic_inadmissibility_rate": semantic_failures / max(1, candidate_count),
            "gold_metrics": {
                "status": "not_available",
                "reason": "Computed only when authored compatible gold is available.",
            },
        },
        "physical_planning": {
            "planning_latency_seconds": _summary(planning_latencies_seconds),
            "states_generated": generated,
            "states_processed": processed,
            "states_pruned": pruned,
            "pruning_ratio": pruned / max(1, generated),
            "search_reduction": 1.0 - processed / max(1, generated),
            "selected_estimated_costs_ms": [
                selected.physical_plan.cost.upper
                for result in planner_results
                for selected in result.selected_plans
            ],
            "cost_prediction": {
                "count": len(predictions),
                "absolute_error_ms": _summary(
                    [float(item["absolute_error_ms"]) for item in predictions]
                ),
                "relative_error": _summary(
                    [float(item["relative_error"]) for item in predictions]
                ),
                "absolute_log_error": _summary(
                    [float(item["absolute_log_error"]) for item in predictions]
                ),
                "empirical_confidence_coverage": (
                    sum(bool(item["confidence_covered"]) for item in predictions)
                    / max(1, len(predictions))
                ),
                "theoretical_proof_claimed": False,
            },
            "oracle": {
                "status": "not_available",
                "reason": "Oracle-only metrics require controlled true-cost enumeration.",
            },
        },
        "end_to_end": {
            "execution_count": len(outcomes),
            "success_rate": len(successful) / max(1, len(outcomes)),
            "backend_error_rate": len(backend_errors) / max(1, len(outcomes)),
            "empty_result_rate": len(empty) / max(1, len(successful)),
            "nonempty_result_rate": len(nonempty) / max(1, len(successful)),
            "backend_latency_ms": _summary(
                [item.actual_cost_ms for item in successful if item.actual_cost_ms is not None]
            ),
            "llm_latency_seconds": _summary(llm_latencies_seconds),
            "row_count": _summary(
                [item.row_count for item in successful if item.row_count is not None]
            ),
            "answer_metrics": {
                "status": "not_available",
                "reason": "Empty/nonempty execution is not answer correctness.",
            },
        },
    }


def _summary(values: Sequence[float | int]) -> dict[str, float | int | None]:
    clean = tuple(float(item) for item in values if math.isfinite(float(item)))
    if not clean:
        return {"count": 0, "mean": None, "median": None, "stddev": None}
    ordered = sorted(clean)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    mean = sum(ordered) / len(ordered)
    variance = sum((item - mean) ** 2 for item in ordered) / len(ordered)
    return {
        "count": len(ordered),
        "mean": mean,
        "median": median,
        "stddev": math.sqrt(variance),
    }
