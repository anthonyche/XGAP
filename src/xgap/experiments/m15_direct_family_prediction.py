"""Leakage-safe family-memory predictions for F2C10 direct semantic plans.

The compiler consumes only the frozen F2C10 training selection view and a
complete set of successful, exact, counterbalanced training observations.  It
uses the held-out selection view only for target features and plan identities;
answer oracles and current-query backend observations are not inputs.

The weighted KNN model is a transparent development reference mechanism.  It
is not a frozen paper estimator and the controlled fixture helper in this
module never produces experimental evidence.
"""

from __future__ import annotations

import copy
import json
import math
import re
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_semantic_frontier import (
    M15DirectSemanticCandidateSet,
    M15PreexecutionEstimateSnapshot,
    build_m15_preexecution_estimate_snapshot,
    build_m15_variable_direct_semantic_candidate_set,
)
from xgap.experiments.m15_direct_semantic_workload import (
    M15DirectSemanticWorkloadBundle,
)
from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadBundle,
)
from xgap.experiments.m15_predicate_overlay import M15PredicateMappingSpec
from xgap.experiments.m15_semantic_frontier import (
    M15SemanticRelaxationCatalog,
)


DIRECT_FAMILY_PREDICTOR_POLICY_SCHEMA_VERSION = (
    "m15-f2c10-family-memory-predictor-policy-v1"
)
DIRECT_TRAINING_MEMORY_SCHEMA_VERSION = (
    "m15-f2c10-direct-training-memory-view-v1"
)
DIRECT_FAMILY_PREDICTION_SOURCE_SCHEMA_VERSION = (
    "m15-f2c10-family-memory-prediction-source-v1"
)
DIRECT_FAMILY_PREDICTION_SUITE_SCHEMA_VERSION = (
    "m15-f2c10-family-memory-prediction-suite-v1"
)
CONTROLLED_TRAINING_FIXTURE_SCHEMA_VERSION = (
    "m15-f2c10-controlled-training-observations-v1"
)
_FEATURE_SCHEMA = (
    ("amount-lower-bound", "integer"),
    ("person-identity", "entity_id"),
    ("risk-level", "ordinal"),
    ("time-lower-bound", "date"),
    ("transfer-predicate", "enum"),
)
_RISK_ORDINAL = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_STRATEGIES = ("parallel_hash_join", "risk_first_bind_join")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RAW_OBSERVATION_FIELDS = {
    "semantic_task_id",
    "plan_id",
    "physical_strategy",
    "repetitions",
}
_RAW_REPETITION_FIELDS = {
    "repetition_id",
    "block_index",
    "order_position",
    "elapsed_ms",
    "total_bytes_moved",
    "total_remote_calls",
    "execution_success",
    "exact_answer",
}


class M15DirectFamilyPredictionError(ValueError):
    """Raised before prediction when memory, provenance, or split drifts."""


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise M15DirectFamilyPredictionError(f"{name} is not a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M15DirectFamilyPredictionError(f"{name} is not a SHA-256 digest")
    return value


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise M15DirectFamilyPredictionError(f"{name} must be a positive integer")
    return value


def _finite_nonnegative(value: object, *, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise M15DirectFamilyPredictionError(
            f"{name} must be finite and nonnegative"
        )
    return float(value)


def _json_object(value: Mapping[str, Any] | str | Path, *, name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise M15DirectFamilyPredictionError(
            f"{name} must be a regular non-symbolic-link file"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise M15DirectFamilyPredictionError(f"{name} must be an object")
    return dict(payload)


def _predictor_policy(
    value: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    raw = _json_object(value, name="family predictor policy")
    fields = {
        "schema_version",
        "policy_id",
        "model_version",
        "neighbor_count",
        "feature_weights",
        "metric_aggregation",
        "uncertainty",
        "resource_cost_metric",
        "training_admission",
        "minimum_repetitions_per_plan",
        "cold_start_policy",
        "current_query_observation_operations",
        "oracle_inputs",
        "post_execution_measurements_used",
        "automatic_retries",
        "paper_result",
    }
    if set(raw) != fields:
        raise M15DirectFamilyPredictionError(
            "family predictor policy fields do not match the contract"
        )
    if raw["schema_version"] != DIRECT_FAMILY_PREDICTOR_POLICY_SCHEMA_VERSION:
        raise M15DirectFamilyPredictionError(
            "family predictor policy schema is unsupported"
        )
    if raw["policy_id"] != "direct-semantic-family-memory-knn-dev-v1":
        raise M15DirectFamilyPredictionError("family predictor policy ID changed")
    _safe_id(raw["model_version"], name="model_version")
    _positive_int(raw["neighbor_count"], name="neighbor_count")
    expected_feature_ids = [slot_id for slot_id, _ in _FEATURE_SCHEMA]
    weights = raw["feature_weights"]
    if not isinstance(weights, Mapping) or sorted(weights) != expected_feature_ids:
        raise M15DirectFamilyPredictionError("feature weights are incomplete")
    for slot_id in expected_feature_ids:
        weight = _finite_nonnegative(weights[slot_id], name=f"weight {slot_id}")
        if weight == 0:
            raise M15DirectFamilyPredictionError("feature weights must be positive")
    expected = {
        "metric_aggregation": "median_per_plan_over_raw_repetitions",
        "uncertainty": "neighbor_weighted_mean_absolute_deviation",
        "resource_cost_metric": "total_bytes_moved",
        "training_admission": (
            "successful_exact_counterbalanced_repetitions_only"
        ),
        "cold_start_policy": "fail_closed",
        "current_query_observation_operations": [],
        "oracle_inputs": [],
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    for key, expected_value in expected.items():
        if raw[key] != expected_value:
            raise M15DirectFamilyPredictionError(
                f"family predictor policy field '{key}' changed"
            )
    _positive_int(
        raw["minimum_repetitions_per_plan"],
        name="minimum_repetitions_per_plan",
    )
    return raw


def _hash_bound(
    value: Mapping[str, Any],
    *,
    schema_version: str,
    hash_field: str,
    name: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(dict(value))
    if payload.get("schema_version") != schema_version:
        raise M15DirectFamilyPredictionError(f"{name} schema is unsupported")
    observed = payload.get(hash_field)
    _sha256(observed, name=f"{name} hash")
    body = {key: item for key, item in payload.items() if key != hash_field}
    if content_hash(body) != observed:
        raise M15DirectFamilyPredictionError(f"{name} hash mismatch")
    return payload


def _training_tasks(
    workload: M15DirectSemanticWorkloadBundle,
) -> dict[str, dict[str, Any]]:
    view = workload.training_selection_view
    return {
        str(item["semantic_task_id"]): copy.deepcopy(dict(item))
        for item in view["semantic_tasks"]
    }


def _heldout_tasks(
    workload: M15DirectSemanticWorkloadBundle,
) -> dict[str, dict[str, Any]]:
    view = workload.heldout_selection_view
    return {
        str(item["semantic_task_id"]): copy.deepcopy(dict(item))
        for item in view["semantic_tasks"]
    }


def _features(task: Mapping[str, Any]) -> dict[str, Any]:
    bindings = task.get("binding_values")
    if not isinstance(bindings, Mapping):
        raise M15DirectFamilyPredictionError("semantic task bindings are invalid")
    expected_ids = {slot_id for slot_id, _ in _FEATURE_SCHEMA} | {"path-shape"}
    if set(bindings) != expected_ids or bindings["path-shape"] != "direct":
        raise M15DirectFamilyPredictionError("semantic task feature shape drifted")
    amount = bindings["amount-lower-bound"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise M15DirectFamilyPredictionError("amount feature is invalid")
    person = _safe_id(bindings["person-identity"], name="person feature")
    risk = bindings["risk-level"]
    if risk not in _RISK_ORDINAL:
        raise M15DirectFamilyPredictionError("risk feature is invalid")
    try:
        parsed_date = date.fromisoformat(bindings["time-lower-bound"])
    except (TypeError, ValueError) as exc:
        raise M15DirectFamilyPredictionError("date feature is invalid") from exc
    if parsed_date.isoformat() != bindings["time-lower-bound"]:
        raise M15DirectFamilyPredictionError("date feature is not canonical")
    predicate = _safe_id(
        bindings["transfer-predicate"], name="predicate feature"
    )
    return {
        "amount-lower-bound": amount,
        "person-identity": person,
        "risk-level": risk,
        "time-lower-bound": parsed_date.isoformat(),
        "transfer-predicate": predicate,
    }


@dataclass(frozen=True)
class M15DirectTrainingMemoryView:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def memory_view_hash(self) -> str:
        return str(self.payload["training_memory_view_sha256"])


def _validated_memory(
    memory: M15DirectTrainingMemoryView,
    *,
    workload: M15DirectSemanticWorkloadBundle,
) -> dict[str, Any]:
    payload = _hash_bound(
        memory.payload,
        schema_version=DIRECT_TRAINING_MEMORY_SCHEMA_VERSION,
        hash_field="training_memory_view_sha256",
        name="training memory view",
    )
    expected_fields = {
        "schema_version",
        "direct_semantic_workload_sha256",
        "training_selection_view_sha256",
        "runtime_compatibility_sha256",
        "predictor_policy_sha256",
        "measurement_source_kind",
        "feature_schema",
        "metric_schema",
        "training_base_query_ids",
        "training_semantic_task_count",
        "training_physical_plan_count",
        "ordered_observation_ids",
        "observations",
        "heldout_task_ids_observed",
        "answer_rows_stored",
        "oracle_inputs",
        "current_query_observation_operations",
        "post_execution_measurements_used",
        "automatic_retries",
        "paper_result",
        "training_memory_view_sha256",
    }
    if set(payload) != expected_fields:
        raise M15DirectFamilyPredictionError(
            "training memory view fields do not match the contract"
        )
    if payload["direct_semantic_workload_sha256"] != workload.manifest[
        "manifest_sha256"
    ] or payload["training_selection_view_sha256"] != (
        workload.training_selection_view["selection_view_sha256"]
    ):
        raise M15DirectFamilyPredictionError(
            "training memory is bound to a different workload or split"
        )
    _sha256(
        payload["runtime_compatibility_sha256"],
        name="runtime_compatibility_sha256",
    )
    _sha256(
        payload["predictor_policy_sha256"], name="predictor_policy_sha256"
    )
    if payload["feature_schema"] != [
        {"slot_id": slot_id, "kind": kind} for slot_id, kind in _FEATURE_SCHEMA
    ]:
        raise M15DirectFamilyPredictionError("training feature schema drifted")
    if payload["metric_schema"] != [
        "elapsed_ms",
        "total_bytes_moved",
        "total_remote_calls",
    ]:
        raise M15DirectFamilyPredictionError("training metric schema drifted")
    if any(
        (
            payload["heldout_task_ids_observed"],
            payload["answer_rows_stored"] is not False,
            payload["oracle_inputs"],
            payload["current_query_observation_operations"],
            payload["post_execution_measurements_used"] is not False,
            payload["automatic_retries"] != 0,
            payload["paper_result"] is not False,
        )
    ):
        raise M15DirectFamilyPredictionError(
            "training memory leakage or claim boundary changed"
        )
    tasks = _training_tasks(workload)
    expected_plan_ids = {
        item["plan_id"]
        for task in tasks.values()
        for item in task["physical_candidates"]
    }
    observations = payload["observations"]
    if not isinstance(observations, list) or len(observations) != len(
        expected_plan_ids
    ):
        raise M15DirectFamilyPredictionError(
            "training memory plan coverage is incomplete"
        )
    observed_ids = [item.get("observation_id") for item in observations]
    if observed_ids != payload["ordered_observation_ids"] or len(
        observed_ids
    ) != len(set(observed_ids)):
        raise M15DirectFamilyPredictionError(
            "training memory observation IDs are invalid"
        )
    if {item.get("plan_id") for item in observations} != expected_plan_ids:
        raise M15DirectFamilyPredictionError(
            "training memory physical plans do not match the training split"
        )
    if payload["training_semantic_task_count"] != len(tasks) or payload[
        "training_physical_plan_count"
    ] != len(expected_plan_ids):
        raise M15DirectFamilyPredictionError("training memory counts drifted")
    if payload["training_base_query_ids"] != list(
        workload.training_selection_view["base_query_ids"]
    ):
        raise M15DirectFamilyPredictionError("training base query IDs drifted")
    heldout_ids = set(_heldout_tasks(workload))
    stored_positions: dict[tuple[str, int], dict[str, int]] = {}
    stored_repetition_ids: set[str] = set()
    for item in observations:
        task_id = item.get("semantic_task_id")
        if task_id in heldout_ids or task_id not in tasks:
            raise M15DirectFamilyPredictionError(
                "held-out or unknown observation entered training memory"
            )
        task = tasks[task_id]
        expected_plan = {
            plan["plan_id"]: plan for plan in task["physical_candidates"]
        }.get(item.get("plan_id"))
        if expected_plan is None or item.get("physical_strategy") != expected_plan[
            "physical_strategy"
        ]:
            raise M15DirectFamilyPredictionError(
                "training observation plan identity drifted"
            )
        if (
            item.get("base_query_id") != task["base_query_id"]
            or item.get("executable_query_id") != task["executable_query_id"]
            or item.get("semantic_class_id") != task["semantic_class_id"]
            or item.get("target_query_instance_sha256")
            != task["target_query_instance_sha256"]
        ):
            raise M15DirectFamilyPredictionError(
                "training observation semantic identity drifted"
            )
        expected_item_fields = {
            "observation_id",
            "semantic_task_id",
            "base_query_id",
            "executable_query_id",
            "semantic_class_id",
            "target_query_instance_sha256",
            "plan_id",
            "physical_strategy",
            "features",
            "repetitions",
            "repetition_ids",
            "repetition_count",
            "median_elapsed_ms",
            "median_total_bytes_moved",
            "total_remote_calls",
        }
        if set(item) != expected_item_fields:
            raise M15DirectFamilyPredictionError(
                "training observation fields do not match the contract"
            )
        identity = {
            key: value for key, value in item.items() if key != "observation_id"
        }
        if content_hash(identity) != item["observation_id"]:
            raise M15DirectFamilyPredictionError(
                "training observation content hash mismatch"
            )
        if item["features"] != _features(task):
            raise M15DirectFamilyPredictionError(
                "training observation features drifted"
            )
        repetitions = item["repetitions"]
        if (
            not isinstance(repetitions, list)
            or len(repetitions) != item["repetition_count"]
            or sorted(rep["repetition_id"] for rep in repetitions)
            != item["repetition_ids"]
        ):
            raise M15DirectFamilyPredictionError(
                "stored training repetitions are invalid"
            )
        for repetition in repetitions:
            if set(repetition) != _RAW_REPETITION_FIELDS:
                raise M15DirectFamilyPredictionError(
                    "stored repetition fields do not match the contract"
                )
            repetition_id = _safe_id(
                repetition["repetition_id"], name="stored repetition_id"
            )
            block = _positive_int(
                repetition["block_index"], name="stored block_index"
            )
            position = _positive_int(
                repetition["order_position"], name="stored order_position"
            )
            if repetition_id in stored_repetition_ids:
                raise M15DirectFamilyPredictionError(
                    "stored repetition IDs are not unique"
                )
            stored_repetition_ids.add(repetition_id)
            if (
                repetition["execution_success"] is not True
                or repetition["exact_answer"] is not True
                or repetition["total_remote_calls"] != 2
                or position not in {1, 2}
            ):
                raise M15DirectFamilyPredictionError(
                    "stored repetition violates the admission contract"
                )
            _finite_nonnegative(
                repetition["elapsed_ms"], name="stored elapsed_ms"
            )
            bytes_moved = repetition["total_bytes_moved"]
            if (
                isinstance(bytes_moved, bool)
                or not isinstance(bytes_moved, int)
                or bytes_moved < 0
            ):
                raise M15DirectFamilyPredictionError(
                    "stored total_bytes_moved is invalid"
                )
            stored_positions.setdefault((task_id, block), {})[
                item["physical_strategy"]
            ] = position
        if item["repetition_count"] < 2:
            raise M15DirectFamilyPredictionError(
                "stored training observation has too few repetitions"
            )
        if item["median_elapsed_ms"] != float(
            statistics.median(rep["elapsed_ms"] for rep in repetitions)
        ) or item["median_total_bytes_moved"] != float(
            statistics.median(rep["total_bytes_moved"] for rep in repetitions)
        ):
            raise M15DirectFamilyPredictionError(
                "stored training aggregates do not match raw repetitions"
            )
        if item["total_remote_calls"] != 2:
            raise M15DirectFamilyPredictionError(
                "stored training remote-call count drifted"
            )
    for (task_id, _), positions in stored_positions.items():
        if set(positions) != set(_STRATEGIES) or set(positions.values()) != {1, 2}:
            raise M15DirectFamilyPredictionError(
                f"stored task '{task_id}' is not counterbalanced by block"
            )
    return payload


def build_m15_direct_training_memory_view(
    *,
    workload: M15DirectSemanticWorkloadBundle,
    raw_observations: Sequence[Mapping[str, Any]],
    runtime_compatibility_sha256: str,
    policy: Mapping[str, Any] | str | Path,
    measurement_source_kind: str,
) -> M15DirectTrainingMemoryView:
    """Admit complete successful/exact training history and freeze it."""

    selected_policy = _predictor_policy(policy)
    runtime_hash = _sha256(
        runtime_compatibility_sha256,
        name="runtime_compatibility_sha256",
    )
    source_kind = _safe_id(
        measurement_source_kind, name="measurement_source_kind"
    )
    tasks = _training_tasks(workload)
    expected_by_plan = {
        plan["plan_id"]: (task, plan)
        for task in tasks.values()
        for plan in task["physical_candidates"]
    }
    if len(raw_observations) != len(expected_by_plan):
        raise M15DirectFamilyPredictionError(
            "raw training observations must cover every training plan"
        )
    normalized: list[dict[str, Any]] = []
    seen_plans: set[str] = set()
    positions_by_task_block: dict[tuple[str, int], dict[str, int]] = {}
    repetition_ids: set[str] = set()
    minimum = selected_policy["minimum_repetitions_per_plan"]
    for raw in raw_observations:
        if not isinstance(raw, Mapping) or set(raw) != _RAW_OBSERVATION_FIELDS:
            raise M15DirectFamilyPredictionError(
                "raw training observation fields do not match the contract"
            )
        plan_id = _safe_id(raw["plan_id"], name="plan_id")
        if plan_id in seen_plans or plan_id not in expected_by_plan:
            raise M15DirectFamilyPredictionError(
                "raw training plan is duplicate or outside the training split"
            )
        seen_plans.add(plan_id)
        task, plan = expected_by_plan[plan_id]
        if raw["semantic_task_id"] != task["semantic_task_id"] or raw[
            "physical_strategy"
        ] != plan["physical_strategy"]:
            raise M15DirectFamilyPredictionError(
                "raw training observation identity drifted"
            )
        repetitions = raw["repetitions"]
        if not isinstance(repetitions, list) or len(repetitions) < minimum:
            raise M15DirectFamilyPredictionError(
                "raw training observation has too few repetitions"
            )
        elapsed_values: list[float] = []
        byte_values: list[int] = []
        call_values: list[int] = []
        current_ids: list[str] = []
        normalized_repetitions: list[dict[str, Any]] = []
        seen_blocks: set[int] = set()
        for repetition in repetitions:
            if not isinstance(repetition, Mapping) or set(repetition) != (
                _RAW_REPETITION_FIELDS
            ):
                raise M15DirectFamilyPredictionError(
                    "raw repetition fields do not match the contract"
                )
            repetition_id = _safe_id(
                repetition["repetition_id"], name="repetition_id"
            )
            block = _positive_int(repetition["block_index"], name="block_index")
            position = _positive_int(
                repetition["order_position"], name="order_position"
            )
            if position not in {1, 2}:
                raise M15DirectFamilyPredictionError(
                    "strategy order_position must be one or two"
                )
            if repetition_id in repetition_ids or block in seen_blocks:
                raise M15DirectFamilyPredictionError(
                    "training repetition or block is duplicated"
                )
            repetition_ids.add(repetition_id)
            seen_blocks.add(block)
            current_ids.append(repetition_id)
            positions_by_task_block.setdefault(
                (task["semantic_task_id"], block), {}
            )[plan["physical_strategy"]] = position
            if repetition["execution_success"] is not True or repetition[
                "exact_answer"
            ] is not True:
                raise M15DirectFamilyPredictionError(
                    "only successful exact repetitions enter family memory"
                )
            elapsed_values.append(
                _finite_nonnegative(repetition["elapsed_ms"], name="elapsed_ms")
            )
            bytes_moved = repetition["total_bytes_moved"]
            if (
                isinstance(bytes_moved, bool)
                or not isinstance(bytes_moved, int)
                or bytes_moved < 0
            ):
                raise M15DirectFamilyPredictionError(
                    "total_bytes_moved must be a nonnegative integer"
                )
            byte_values.append(bytes_moved)
            call_values.append(
                _positive_int(
                    repetition["total_remote_calls"],
                    name="total_remote_calls",
                )
            )
            normalized_repetitions.append(
                {
                    "repetition_id": repetition_id,
                    "block_index": block,
                    "order_position": position,
                    "elapsed_ms": elapsed_values[-1],
                    "total_bytes_moved": byte_values[-1],
                    "total_remote_calls": call_values[-1],
                    "execution_success": True,
                    "exact_answer": True,
                }
            )
        if set(call_values) != {2}:
            raise M15DirectFamilyPredictionError(
                "direct training plans require exactly two remote calls"
            )
        identity = {
            "semantic_task_id": task["semantic_task_id"],
            "base_query_id": task["base_query_id"],
            "executable_query_id": task["executable_query_id"],
            "semantic_class_id": task["semantic_class_id"],
            "target_query_instance_sha256": task[
                "target_query_instance_sha256"
            ],
            "plan_id": plan_id,
            "physical_strategy": plan["physical_strategy"],
            "features": _features(task),
            "repetitions": sorted(
                normalized_repetitions, key=lambda item: item["block_index"]
            ),
            "repetition_ids": sorted(current_ids),
            "repetition_count": len(current_ids),
            "median_elapsed_ms": float(statistics.median(elapsed_values)),
            "median_total_bytes_moved": float(statistics.median(byte_values)),
            "total_remote_calls": 2,
        }
        normalized.append(
            {"observation_id": content_hash(identity), **identity}
        )
    for (task_id, _), positions in positions_by_task_block.items():
        if set(positions) != set(_STRATEGIES) or set(positions.values()) != {1, 2}:
            raise M15DirectFamilyPredictionError(
                f"training task '{task_id}' is not counterbalanced by block"
            )
    normalized.sort(key=lambda item: item["observation_id"])
    body = {
        "schema_version": DIRECT_TRAINING_MEMORY_SCHEMA_VERSION,
        "direct_semantic_workload_sha256": workload.manifest["manifest_sha256"],
        "training_selection_view_sha256": workload.training_selection_view[
            "selection_view_sha256"
        ],
        "runtime_compatibility_sha256": runtime_hash,
        "predictor_policy_sha256": content_hash(selected_policy),
        "measurement_source_kind": source_kind,
        "feature_schema": [
            {"slot_id": slot_id, "kind": kind}
            for slot_id, kind in _FEATURE_SCHEMA
        ],
        "metric_schema": [
            "elapsed_ms",
            "total_bytes_moved",
            "total_remote_calls",
        ],
        "training_base_query_ids": list(
            workload.training_selection_view["base_query_ids"]
        ),
        "training_semantic_task_count": len(tasks),
        "training_physical_plan_count": len(normalized),
        "ordered_observation_ids": [
            item["observation_id"] for item in normalized
        ],
        "observations": normalized,
        "heldout_task_ids_observed": [],
        "answer_rows_stored": False,
        "oracle_inputs": [],
        "current_query_observation_operations": [],
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    memory = M15DirectTrainingMemoryView(
        {**body, "training_memory_view_sha256": content_hash(body)}
    )
    _validated_memory(memory, workload=workload)
    return memory


def build_m15_controlled_training_observations(
    workload: M15DirectSemanticWorkloadBundle,
) -> dict[str, Any]:
    """Create deterministic non-measured observations for local contract tests."""

    observations: list[dict[str, Any]] = []
    tasks = sorted(
        workload.training_selection_view["semantic_tasks"],
        key=lambda item: item["semantic_task_id"],
    )
    for task_index, task in enumerate(tasks, start=1):
        plans = sorted(
            task["physical_candidates"],
            key=lambda item: item["physical_strategy"],
        )
        for strategy_index, plan in enumerate(plans):
            repetitions: list[dict[str, Any]] = []
            for block_index in (1, 2):
                first_strategy = (task_index + block_index) % 2
                order_position = 1 if strategy_index == first_strategy else 2
                strategy_penalty = 9 if strategy_index == 0 else 3
                elapsed = 40.0 + task_index * 1.75 + strategy_penalty + block_index
                bytes_moved = 1800 + task_index * 113 + strategy_penalty * 31
                repetitions.append(
                    {
                        "repetition_id": (
                            f"controlled-{task_index:02d}-{strategy_index + 1}-"
                            f"b{block_index}"
                        ),
                        "block_index": block_index,
                        "order_position": order_position,
                        "elapsed_ms": elapsed,
                        "total_bytes_moved": bytes_moved,
                        "total_remote_calls": 2,
                        "execution_success": True,
                        "exact_answer": True,
                    }
                )
            observations.append(
                {
                    "semantic_task_id": task["semantic_task_id"],
                    "plan_id": plan["plan_id"],
                    "physical_strategy": plan["physical_strategy"],
                    "repetitions": repetitions,
                }
            )
    body = {
        "schema_version": CONTROLLED_TRAINING_FIXTURE_SCHEMA_VERSION,
        "direct_semantic_workload_sha256": workload.manifest["manifest_sha256"],
        "evidence_kind": "controlled_local_nonmeasurement_fixture",
        "observations": observations,
        "backend_calls_made": 0,
        "paper_result": False,
    }
    return {**body, "fixture_sha256": content_hash(body)}


def _distance(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    weights: Mapping[str, Any],
) -> float:
    components = {
        "amount-lower-bound": min(
            1.0,
            abs(left["amount-lower-bound"] - right["amount-lower-bound"])
            / max(
                abs(left["amount-lower-bound"]),
                abs(right["amount-lower-bound"]),
                1,
            ),
        ),
        "person-identity": (
            0.0 if left["person-identity"] == right["person-identity"] else 1.0
        ),
        "risk-level": abs(
            _RISK_ORDINAL[left["risk-level"]]
            - _RISK_ORDINAL[right["risk-level"]]
        )
        / 2.0,
        "time-lower-bound": min(
            1.0,
            abs(
                date.fromisoformat(left["time-lower-bound"]).toordinal()
                - date.fromisoformat(right["time-lower-bound"]).toordinal()
            )
            / 365.0,
        ),
        "transfer-predicate": (
            0.0
            if left["transfer-predicate"] == right["transfer-predicate"]
            else 1.0
        ),
    }
    denominator = sum(float(weights[key]) for key in components)
    return sum(
        components[key] * float(weights[key]) for key in components
    ) / denominator


@dataclass(frozen=True)
class M15DirectFamilyPredictionSource:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def source_hash(self) -> str:
        return str(self.payload["prediction_source_sha256"])

    def to_snapshot(
        self,
        candidate_set: M15DirectSemanticCandidateSet,
    ) -> M15PreexecutionEstimateSnapshot:
        source = _validated_prediction_source(
            self, candidate_set=candidate_set
        )
        return build_m15_preexecution_estimate_snapshot(
            candidate_set,
            [
                {
                    "plan_id": item["plan_id"],
                    "estimated_latency_ms": item["estimated_latency_ms"],
                    "estimated_resource_cost_units": item[
                        "estimated_total_bytes_moved"
                    ],
                }
                for item in source["predictions"]
            ],
            evidence_kind="family_memory_prediction",
            evidence_id=source["source_id"],
        )


def _validated_prediction_source(
    source: M15DirectFamilyPredictionSource,
    *,
    candidate_set: M15DirectSemanticCandidateSet,
) -> dict[str, Any]:
    payload = _hash_bound(
        source.payload,
        schema_version=DIRECT_FAMILY_PREDICTION_SOURCE_SCHEMA_VERSION,
        hash_field="prediction_source_sha256",
        name="family prediction source",
    )
    expected_fields = {
        "schema_version",
        "source_id",
        "model_version",
        "model_configuration_sha256",
        "training_memory_view_sha256",
        "training_selection_view_sha256",
        "heldout_selection_view_sha256",
        "candidate_set_sha256",
        "base_query_id",
        "feature_schema_sha256",
        "ordered_training_observation_ids",
        "prediction_count",
        "predictions",
        "sealed_before_execution",
        "oracle_inputs",
        "current_query_observation_operations",
        "post_execution_measurements_used",
        "cold_start",
        "automatic_retries",
        "paper_result",
        "prediction_source_sha256",
    }
    if set(payload) != expected_fields:
        raise M15DirectFamilyPredictionError(
            "family prediction source fields do not match the contract"
        )
    if payload["candidate_set_sha256"] != candidate_set.candidate_set_hash or payload[
        "base_query_id"
    ] != candidate_set.payload["base_query_id"]:
        raise M15DirectFamilyPredictionError(
            "family prediction source targets a different candidate set"
        )
    if any(
        (
            payload["sealed_before_execution"] is not True,
            payload["oracle_inputs"],
            payload["current_query_observation_operations"],
            payload["post_execution_measurements_used"] is not False,
            payload["cold_start"] is not False,
            payload["automatic_retries"] != 0,
            payload["paper_result"] is not False,
        )
    ):
        raise M15DirectFamilyPredictionError(
            "family prediction source leakage or claim boundary changed"
        )
    _safe_id(payload["source_id"], name="prediction source_id")
    _safe_id(payload["model_version"], name="prediction model_version")
    _sha256(
        payload["model_configuration_sha256"],
        name="model_configuration_sha256",
    )
    _sha256(
        payload["training_memory_view_sha256"],
        name="training_memory_view_sha256",
    )
    _sha256(
        payload["training_selection_view_sha256"],
        name="training_selection_view_sha256",
    )
    _sha256(
        payload["heldout_selection_view_sha256"],
        name="heldout_selection_view_sha256",
    )
    _sha256(payload["feature_schema_sha256"], name="feature_schema_sha256")
    ordered_observations = payload["ordered_training_observation_ids"]
    if (
        not isinstance(ordered_observations, list)
        or not ordered_observations
        or len(ordered_observations) != len(set(ordered_observations))
    ):
        raise M15DirectFamilyPredictionError(
            "ordered training observation IDs are invalid"
        )
    for observation_id in ordered_observations:
        _sha256(observation_id, name="training observation_id")
    predictions = payload["predictions"]
    expected_plan_ids = set(candidate_set.plans)
    if not isinstance(predictions, list) or payload["prediction_count"] != len(
        predictions
    ) or {item.get("plan_id") for item in predictions} != expected_plan_ids:
        raise M15DirectFamilyPredictionError(
            "family predictions do not cover every physical plan"
        )
    prediction_fields = {
        "plan_id",
        "semantic_class_id",
        "target_query_instance_sha256",
        "physical_strategy",
        "estimated_latency_ms",
        "estimated_total_bytes_moved",
        "uncertainty",
        "neighbor_observation_ids",
        "neighbor_distances",
        "oracle_inputs",
        "post_execution_measurements_used",
    }
    candidate_plans = {
        item["plan_id"]: item
        for item in candidate_set.payload["physical_candidates"]
    }
    semantic_classes = {
        item["semantic_class_id"]: item
        for item in candidate_set.payload["semantic_classes"]
    }
    for item in predictions:
        if set(item) != prediction_fields:
            raise M15DirectFamilyPredictionError(
                "family prediction fields do not match the contract"
            )
        _finite_nonnegative(
            item["estimated_latency_ms"], name="estimated_latency_ms"
        )
        _finite_nonnegative(
            item["estimated_total_bytes_moved"],
            name="estimated_total_bytes_moved",
        )
        if item["oracle_inputs"] or item["post_execution_measurements_used"] is not False:
            raise M15DirectFamilyPredictionError("prediction leaks evaluation data")
        if not item["neighbor_observation_ids"] or len(
            item["neighbor_observation_ids"]
        ) != len(item["neighbor_distances"]):
            raise M15DirectFamilyPredictionError("prediction neighbors are invalid")
        plan = candidate_plans[item["plan_id"]]
        semantic = semantic_classes[plan["semantic_class_id"]]
        if (
            item["semantic_class_id"] != plan["semantic_class_id"]
            or item["physical_strategy"] != plan["physical_strategy"]
            or item["target_query_instance_sha256"]
            != semantic["query_instance_sha256"]
        ):
            raise M15DirectFamilyPredictionError(
                "prediction target identity drifted"
            )
        if (
            len(item["neighbor_observation_ids"])
            != len(set(item["neighbor_observation_ids"]))
            or not set(item["neighbor_observation_ids"]).issubset(
                ordered_observations
            )
        ):
            raise M15DirectFamilyPredictionError(
                "prediction references an unknown or duplicate neighbor"
            )
        for distance in item["neighbor_distances"]:
            _finite_nonnegative(distance, name="neighbor distance")
        uncertainty = item["uncertainty"]
        if not isinstance(uncertainty, Mapping) or set(uncertainty) != {
            "kind",
            "latency_mad_ms",
            "bytes_moved_mad",
        }:
            raise M15DirectFamilyPredictionError(
                "prediction uncertainty fields are invalid"
            )
        _safe_id(uncertainty["kind"], name="uncertainty kind")
        _finite_nonnegative(
            uncertainty["latency_mad_ms"], name="latency uncertainty"
        )
        _finite_nonnegative(
            uncertainty["bytes_moved_mad"], name="byte uncertainty"
        )
    return payload


def build_m15_direct_family_prediction_source(
    *,
    workload: M15DirectSemanticWorkloadBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
    base_query_id: str,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    memory: M15DirectTrainingMemoryView,
    policy: Mapping[str, Any] | str | Path,
) -> tuple[M15DirectSemanticCandidateSet, M15DirectFamilyPredictionSource]:
    """Predict every plan for one held-out base query with zero profiling."""

    selected_policy = _predictor_policy(policy)
    memory_payload = _validated_memory(memory, workload=workload)
    if memory_payload["predictor_policy_sha256"] != content_hash(selected_policy):
        raise M15DirectFamilyPredictionError(
            "training memory and predictor policy identities differ"
        )
    selected_query_id = _safe_id(base_query_id, name="base_query_id")
    if selected_query_id not in workload.heldout_selection_view["base_query_ids"]:
        raise M15DirectFamilyPredictionError(
            "predictions may target only the frozen held-out split"
        )
    candidate_set = build_m15_variable_direct_semantic_candidate_set(
        direct_workload=workload,
        base_bundle=base_bundle,
        base_query_id=selected_query_id,
        catalog=catalog,
        mapping=mapping,
    )
    tasks_by_class = {
        item["semantic_class_id"]: item
        for item in _heldout_tasks(workload).values()
        if item["base_query_id"] == selected_query_id
    }
    training = memory_payload["observations"]
    weights = selected_policy["feature_weights"]
    k = selected_policy["neighbor_count"]
    predictions: list[dict[str, Any]] = []
    for plan in candidate_set.payload["physical_candidates"]:
        task = tasks_by_class[plan["semantic_class_id"]]
        target_features = _features(task)
        eligible = [
            item
            for item in training
            if item["physical_strategy"] == plan["physical_strategy"]
        ]
        if not eligible:
            raise M15DirectFamilyPredictionError(
                "cold start is forbidden for the primary family predictor"
            )
        ranked = sorted(
            (
                (_distance(target_features, item["features"], weights=weights), item)
                for item in eligible
            ),
            key=lambda pair: (pair[0], pair[1]["observation_id"]),
        )
        neighbors = ranked[: min(k, len(ranked))]
        zero_distance = [pair for pair in neighbors if pair[0] == 0]
        used = zero_distance or neighbors
        weighted: list[tuple[float, Mapping[str, Any], float]] = []
        for distance, observation in used:
            weight = 1.0 if zero_distance else 1.0 / max(distance, 1e-12)
            weighted.append((distance, observation, weight))
        total_weight = sum(item[2] for item in weighted)
        latency = sum(
            item[1]["median_elapsed_ms"] * item[2] for item in weighted
        ) / total_weight
        bytes_moved = sum(
            item[1]["median_total_bytes_moved"] * item[2]
            for item in weighted
        ) / total_weight
        latency_mad = sum(
            abs(item[1]["median_elapsed_ms"] - latency) * item[2]
            for item in weighted
        ) / total_weight
        bytes_mad = sum(
            abs(item[1]["median_total_bytes_moved"] - bytes_moved) * item[2]
            for item in weighted
        ) / total_weight
        predictions.append(
            {
                "plan_id": plan["plan_id"],
                "semantic_class_id": plan["semantic_class_id"],
                "target_query_instance_sha256": task[
                    "target_query_instance_sha256"
                ],
                "physical_strategy": plan["physical_strategy"],
                "estimated_latency_ms": latency,
                "estimated_total_bytes_moved": bytes_moved,
                "uncertainty": {
                    "kind": selected_policy["uncertainty"],
                    "latency_mad_ms": latency_mad,
                    "bytes_moved_mad": bytes_mad,
                },
                "neighbor_observation_ids": [
                    item[1]["observation_id"] for item in weighted
                ],
                "neighbor_distances": [item[0] for item in weighted],
                "oracle_inputs": [],
                "post_execution_measurements_used": False,
            }
        )
    predictions.sort(key=lambda item: item["plan_id"])
    policy_hash = content_hash(selected_policy)
    feature_schema_hash = content_hash(
        [{"slot_id": slot_id, "kind": kind} for slot_id, kind in _FEATURE_SCHEMA]
    )
    source_id = "m15-f2c10-family-" + content_hash(
        {
            "base_query_id": selected_query_id,
            "candidate_set_sha256": candidate_set.candidate_set_hash,
            "training_memory_view_sha256": memory.memory_view_hash,
            "model_configuration_sha256": policy_hash,
        }
    )[:24]
    body = {
        "schema_version": DIRECT_FAMILY_PREDICTION_SOURCE_SCHEMA_VERSION,
        "source_id": source_id,
        "model_version": selected_policy["model_version"],
        "model_configuration_sha256": policy_hash,
        "training_memory_view_sha256": memory.memory_view_hash,
        "training_selection_view_sha256": workload.training_selection_view[
            "selection_view_sha256"
        ],
        "heldout_selection_view_sha256": workload.heldout_selection_view[
            "selection_view_sha256"
        ],
        "candidate_set_sha256": candidate_set.candidate_set_hash,
        "base_query_id": selected_query_id,
        "feature_schema_sha256": feature_schema_hash,
        "ordered_training_observation_ids": list(
            memory_payload["ordered_observation_ids"]
        ),
        "prediction_count": len(predictions),
        "predictions": predictions,
        "sealed_before_execution": True,
        "oracle_inputs": [],
        "current_query_observation_operations": [],
        "post_execution_measurements_used": False,
        "cold_start": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    source = M15DirectFamilyPredictionSource(
        {**body, "prediction_source_sha256": content_hash(body)}
    )
    _validated_prediction_source(source, candidate_set=candidate_set)
    return candidate_set, source


@dataclass(frozen=True)
class M15DirectFamilyPredictionSuite:
    payload: Mapping[str, Any]
    candidate_sets: Mapping[str, M15DirectSemanticCandidateSet]
    sources: Mapping[str, M15DirectFamilyPredictionSource]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def build_m15_direct_family_prediction_suite(
    *,
    workload: M15DirectSemanticWorkloadBundle,
    base_bundle: M15ParameterizedWorkloadBundle,
    catalog: M15SemanticRelaxationCatalog | str | Path,
    mapping: M15PredicateMappingSpec | str | Path,
    memory: M15DirectTrainingMemoryView,
    policy: Mapping[str, Any] | str | Path,
) -> M15DirectFamilyPredictionSuite:
    """Compile sealed family-memory sources for every held-out base query."""

    selected_policy = _predictor_policy(policy)
    memory_payload = _validated_memory(memory, workload=workload)
    if memory_payload["predictor_policy_sha256"] != content_hash(selected_policy):
        raise M15DirectFamilyPredictionError(
            "training memory and predictor policy identities differ"
        )
    candidate_sets: dict[str, M15DirectSemanticCandidateSet] = {}
    sources: dict[str, M15DirectFamilyPredictionSource] = {}
    for query_id in workload.heldout_selection_view["base_query_ids"]:
        candidates, source = build_m15_direct_family_prediction_source(
            workload=workload,
            base_bundle=base_bundle,
            base_query_id=query_id,
            catalog=catalog,
            mapping=mapping,
            memory=memory,
            policy=selected_policy,
        )
        candidate_sets[query_id] = candidates
        sources[query_id] = source
    records = [
        {
            "base_query_id": query_id,
            "candidate_set_sha256": candidate_sets[query_id].candidate_set_hash,
            "prediction_source_sha256": sources[query_id].source_hash,
            "prediction_count": sources[query_id].payload["prediction_count"],
        }
        for query_id in sorted(sources)
    ]
    body = {
        "schema_version": DIRECT_FAMILY_PREDICTION_SUITE_SCHEMA_VERSION,
        "direct_semantic_workload_sha256": workload.manifest["manifest_sha256"],
        "training_memory_view_sha256": memory.memory_view_hash,
        "model_configuration_sha256": content_hash(selected_policy),
        "heldout_base_query_count": len(records),
        "heldout_semantic_task_count": workload.heldout_selection_view[
            "semantic_task_count"
        ],
        "heldout_physical_plan_count": sum(
            item["prediction_count"] for item in records
        ),
        "prediction_sources": records,
        "selection_input_only": True,
        "heldout_queries_executed": 0,
        "backend_calls_made": 0,
        "current_query_profile_calls": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
        "oracle_inputs": [],
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    payload = {**body, "prediction_suite_sha256": content_hash(body)}
    _hash_bound(
        payload,
        schema_version=DIRECT_FAMILY_PREDICTION_SUITE_SCHEMA_VERSION,
        hash_field="prediction_suite_sha256",
        name="family prediction suite",
    )
    return M15DirectFamilyPredictionSuite(
        payload=payload,
        candidate_sets=candidate_sets,
        sources=sources,
    )
