"""Leakage-safe family-memory prediction for the FinBench-derived workload.

This module sits above the black-box federated runtime. It admits only complete
successful/exact measurements from the declared training split, freezes a
content-addressed memory view, and predicts one physical strategy for each
held-out query without observing that query's backends. The entirely held-out
family is reported separately and uses only its predeclared cold-start route.
"""

from __future__ import annotations

import copy
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
)


FINBENCH_FAMILY_MEMORY_POLICY_SCHEMA_VERSION = (
    "m15-finbench-family-memory-policy-v1"
)
FINBENCH_TRAINING_MEMORY_SCHEMA_VERSION = (
    "m15-finbench-training-memory-v1"
)
FINBENCH_PREDICTION_SUITE_SCHEMA_VERSION = (
    "m15-finbench-family-prediction-suite-v1"
)
DEFAULT_POLICY_PATH = Path(
    "experiments/configs/m15_finbench_family_memory_policy_v1.json"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FEATURES = {
    "f1_direct_transfer_control": ("structural_degree",),
    "f2_temporal_path_control": ("out_degree",),
    "f3_aggregate_risk_ranking": ("window_position", "risk_position"),
}
_TRAINING_ROLES = frozenset({"training"})
_HELDOUT_ROLES = frozenset({"heldout_instance", "heldout_family"})
_RAW_OBSERVATION_FIELDS = {
    "query_id",
    "family_id",
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
_MEMORY_OBSERVATION_FIELDS = {
    "query_id",
    "family_id",
    "physical_strategy",
    "features",
    "repetitions",
    "repetition_count",
    "median_elapsed_ms",
    "median_total_bytes_moved",
    "observation_sha256",
}
_MEMORY_FIELDS = {
    "schema_version",
    "policy_sha256",
    "workload_sha256",
    "public_instances_sha256",
    "family_contracts_sha256",
    "measurement_source_id",
    "training_query_ids",
    "training_query_count",
    "training_plan_count",
    "known_family_ids",
    "observations",
    "heldout_query_ids_observed",
    "answer_rows_stored",
    "current_query_profile_calls",
    "oracle_inputs",
    "post_execution_measurements_used",
    "automatic_retries",
    "paper_result",
    "training_memory_sha256",
}


class FinBenchFamilyMemoryError(ValueError):
    """Raised before prediction when policy, split, or memory drifts."""


@dataclass(frozen=True)
class FinBenchTrainingMemory:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def memory_hash(self) -> str:
        return str(self.payload["training_memory_sha256"])


@dataclass(frozen=True)
class FinBenchPredictionSuite:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def prediction_hash(self) -> str:
        return str(self.payload["prediction_suite_sha256"])


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise FinBenchFamilyMemoryError(f"{name} is not a safe identifier")
    return value


def _finite_nonnegative(value: object, *, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise FinBenchFamilyMemoryError(
            f"{name} must be finite and nonnegative"
        )
    return float(value)


def _json_object(
    value: Mapping[str, Any] | str | Path, *, name: str
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise FinBenchFamilyMemoryError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchFamilyMemoryError(f"{name} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise FinBenchFamilyMemoryError(f"{name} must be an object")
    return dict(payload)


def _policy(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    raw = _json_object(value, name="FinBench family-memory policy")
    expected_fields = {
        "schema_version",
        "policy_id",
        "model_version",
        "neighbor_count",
        "feature_source",
        "feature_schema_by_family",
        "normalization",
        "distance",
        "zero_distance_policy",
        "neighbor_weight",
        "metric_aggregation",
        "uncertainty",
        "selection_order",
        "training_admission",
        "minimum_repetitions_per_plan",
        "cold_start",
        "current_query_profile_calls",
        "oracle_inputs",
        "post_execution_measurements_used",
        "automatic_retries",
        "paper_result",
    }
    if set(raw) != expected_fields:
        raise FinBenchFamilyMemoryError("family-memory policy fields changed")
    if raw["schema_version"] != FINBENCH_FAMILY_MEMORY_POLICY_SCHEMA_VERSION:
        raise FinBenchFamilyMemoryError("family-memory policy schema is unsupported")
    if (
        raw["policy_id"] != "m15-finbench-family-memory-knn-development-v1"
        or raw["model_version"]
        != "m15-finbench-normalized-knn-development-v1"
    ):
        raise FinBenchFamilyMemoryError("family-memory policy identity changed")
    count = raw["neighbor_count"]
    minimum = raw["minimum_repetitions_per_plan"]
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count <= 0
        or isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum < 2
    ):
        raise FinBenchFamilyMemoryError("family-memory count policy is invalid")
    expected_schema = {
        family_id: list(features) for family_id, features in _FEATURES.items()
    }
    expected = {
        "feature_source": "public_selection_feature_only",
        "feature_schema_by_family": expected_schema,
        "normalization": "within_family_training_range",
        "distance": "normalized_manhattan",
        "zero_distance_policy": "exact_feature_matches_only",
        "neighbor_weight": "inverse_distance",
        "metric_aggregation": "median_per_plan_over_raw_repetitions",
        "uncertainty": "neighbor_weighted_mean_absolute_deviation",
        "selection_order": [
            "predicted_elapsed_ms",
            "predicted_total_bytes_moved",
            "physical_strategy",
        ],
        "training_admission": (
            "successful_exact_counterbalanced_repetitions_only"
        ),
        "cold_start": {
            "source": "family_contract_predeclared_fallback",
            "report_as_separate_stratum": True,
            "predicted_metrics_available": False,
        },
        "current_query_profile_calls": 0,
        "oracle_inputs": [],
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    for key, expected_value in expected.items():
        if raw[key] != expected_value:
            raise FinBenchFamilyMemoryError(
                f"family-memory policy field '{key}' changed"
            )
    return raw


def _public_contract(workload_root: str | Path) -> dict[str, Any]:
    loaded = load_finbench_primary_public_workload(workload_root)
    manifest = loaded.get("manifest")
    public = loaded.get("public_instances")
    contracts = loaded.get("family_contracts")
    if not all(isinstance(item, Mapping) for item in (manifest, public, contracts)):
        raise FinBenchFamilyMemoryError("FinBench public workload is invalid")
    instances = public.get("instances")
    families = contracts.get("families")
    if (
        not isinstance(instances, list)
        or len(instances) != 36
        or any(not isinstance(item, Mapping) for item in instances)
        or not isinstance(families, list)
        or len(families) != 3
        or any(not isinstance(item, Mapping) for item in families)
    ):
        raise FinBenchFamilyMemoryError("FinBench population shape changed")
    by_query: dict[str, dict[str, Any]] = {}
    for raw in instances:
        item = copy.deepcopy(dict(raw))
        query_id = _safe_id(item.get("query_id"), name="query_id")
        family_id = _safe_id(item.get("family_id"), name="family_id")
        role = item.get("split_role")
        if query_id in by_query or family_id not in _FEATURES or role not in (
            _TRAINING_ROLES | _HELDOUT_ROLES
        ):
            raise FinBenchFamilyMemoryError("FinBench query split is invalid")
        _feature_vector(item)
        by_query[query_id] = item
    roles = {role: 0 for role in (*_TRAINING_ROLES, *_HELDOUT_ROLES)}
    for item in by_query.values():
        roles[str(item["split_role"])] += 1
    if roles != {"training": 16, "heldout_instance": 8, "heldout_family": 12}:
        raise FinBenchFamilyMemoryError("FinBench split counts changed")
    by_family: dict[str, dict[str, Any]] = {}
    for raw in families:
        item = copy.deepcopy(dict(raw))
        family_id = _safe_id(item.get("family_id"), name="family contract ID")
        strategies = item.get("physical_strategies")
        if (
            family_id in by_family
            or family_id not in _FEATURES
            or not isinstance(strategies, list)
            or len(strategies) != 2
            or len(set(strategies)) != 2
            or any(not isinstance(strategy, str) for strategy in strategies)
        ):
            raise FinBenchFamilyMemoryError("FinBench family strategies changed")
        for strategy in strategies:
            _safe_id(strategy, name="physical strategy")
        by_family[family_id] = item
    if set(by_family) != set(_FEATURES):
        raise FinBenchFamilyMemoryError("FinBench family contracts are incomplete")
    output_files = manifest.get("output_files")
    if not isinstance(output_files, Mapping):
        raise FinBenchFamilyMemoryError("FinBench workload file identities are missing")
    for name in ("public_instances.json", "family_contracts.json"):
        record = output_files.get(name)
        if (
            not isinstance(record, Mapping)
            or not isinstance(record.get("sha256"), str)
            or _SHA256.fullmatch(str(record["sha256"])) is None
        ):
            raise FinBenchFamilyMemoryError(
                f"FinBench workload identity is missing: {name}"
            )
    workload_hash = manifest.get("workload_sha256")
    if not isinstance(workload_hash, str) or _SHA256.fullmatch(workload_hash) is None:
        raise FinBenchFamilyMemoryError("FinBench workload SHA-256 is invalid")
    return {
        "loaded": loaded,
        "manifest": dict(manifest),
        "instances": by_query,
        "families": by_family,
    }


def _feature_vector(instance: Mapping[str, Any]) -> dict[str, float]:
    family_id = instance.get("family_id")
    feature = instance.get("selection_feature")
    if family_id not in _FEATURES or not isinstance(feature, Mapping):
        raise FinBenchFamilyMemoryError("FinBench selection feature is invalid")
    expected = _FEATURES[str(family_id)]
    if set(feature) != set(expected):
        raise FinBenchFamilyMemoryError("FinBench selection feature schema changed")
    return {
        name: _finite_nonnegative(feature[name], name=f"feature {name}")
        for name in expected
    }


def _validate_repetitions(
    repetitions: object,
    *,
    query_id: str,
    strategy: str,
    minimum: int,
) -> tuple[list[dict[str, Any]], float, float]:
    if not isinstance(repetitions, list) or len(repetitions) < minimum:
        raise FinBenchFamilyMemoryError("training repetitions are incomplete")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_blocks: set[int] = set()
    for raw in repetitions:
        if not isinstance(raw, Mapping) or set(raw) != _RAW_REPETITION_FIELDS:
            raise FinBenchFamilyMemoryError("training repetition fields changed")
        item = copy.deepcopy(dict(raw))
        repetition_id = _safe_id(item["repetition_id"], name="repetition_id")
        block = item["block_index"]
        position = item["order_position"]
        if (
            repetition_id in seen
            or block in seen_blocks
            or isinstance(block, bool)
            or not isinstance(block, int)
            or block <= 0
            or position not in {1, 2}
            or item["execution_success"] is not True
            or item["exact_answer"] is not True
            or item["total_remote_calls"] != 2
        ):
            raise FinBenchFamilyMemoryError(
                f"inadmissible training repetition for {query_id}/{strategy}"
            )
        seen.add(repetition_id)
        seen_blocks.add(block)
        _finite_nonnegative(item["elapsed_ms"], name="elapsed_ms")
        bytes_moved = item["total_bytes_moved"]
        if (
            isinstance(bytes_moved, bool)
            or not isinstance(bytes_moved, int)
            or bytes_moved < 0
        ):
            raise FinBenchFamilyMemoryError("total_bytes_moved is invalid")
        normalized.append(item)
    if sorted(seen_blocks) != list(range(1, len(normalized) + 1)):
        raise FinBenchFamilyMemoryError(
            f"training blocks for {query_id}/{strategy} are not consecutive"
        )
    normalized.sort(key=lambda item: (item["block_index"], item["repetition_id"]))
    return (
        normalized,
        float(statistics.median(item["elapsed_ms"] for item in normalized)),
        float(
            statistics.median(item["total_bytes_moved"] for item in normalized)
        ),
    )


def build_finbench_training_memory(
    *,
    workload_root: str | Path,
    raw_observations: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
    measurement_source_id: str,
) -> FinBenchTrainingMemory:
    """Admit the complete training split and freeze a hash-bound memory view."""

    selected_policy = _policy(policy)
    source_id = _safe_id(measurement_source_id, name="measurement_source_id")
    contract = _public_contract(workload_root)
    instances = contract["instances"]
    families = contract["families"]
    training = {
        query_id: item
        for query_id, item in instances.items()
        if item["split_role"] == "training"
    }
    expected_pairs = {
        (query_id, strategy)
        for query_id, item in training.items()
        for strategy in families[item["family_id"]]["physical_strategies"]
    }
    if len(expected_pairs) != 32 or len(raw_observations) != len(expected_pairs):
        raise FinBenchFamilyMemoryError(
            "training observations must cover all 32 declared plans"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    positions: dict[tuple[str, int], dict[str, int]] = {}
    repetition_ids: set[str] = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping) or set(raw) != _RAW_OBSERVATION_FIELDS:
            raise FinBenchFamilyMemoryError("training observation fields changed")
        query_id = _safe_id(raw["query_id"], name="training query_id")
        family_id = _safe_id(raw["family_id"], name="training family_id")
        strategy = _safe_id(
            raw["physical_strategy"], name="training physical strategy"
        )
        pair = (query_id, strategy)
        instance = training.get(query_id)
        if (
            pair in seen
            or pair not in expected_pairs
            or instance is None
            or instance["family_id"] != family_id
        ):
            raise FinBenchFamilyMemoryError(
                "held-out, duplicate, or unknown observation entered memory"
            )
        repetitions, median_elapsed, median_bytes = _validate_repetitions(
            raw["repetitions"],
            query_id=query_id,
            strategy=strategy,
            minimum=selected_policy["minimum_repetitions_per_plan"],
        )
        for repetition in repetitions:
            repetition_id = repetition["repetition_id"]
            if repetition_id in repetition_ids:
                raise FinBenchFamilyMemoryError(
                    "training repetition IDs are not globally unique"
                )
            repetition_ids.add(repetition_id)
            positions.setdefault(
                (query_id, int(repetition["block_index"])), {}
            )[strategy] = int(repetition["order_position"])
        observation = {
            "query_id": query_id,
            "family_id": family_id,
            "physical_strategy": strategy,
            "features": _feature_vector(instance),
            "repetitions": repetitions,
            "repetition_count": len(repetitions),
            "median_elapsed_ms": median_elapsed,
            "median_total_bytes_moved": median_bytes,
        }
        observation["observation_sha256"] = content_hash(observation)
        normalized.append(observation)
        seen.add(pair)
    if seen != expected_pairs:
        raise FinBenchFamilyMemoryError("training plan coverage is incomplete")
    for (query_id, _block), by_strategy in positions.items():
        expected_strategies = set(
            families[training[query_id]["family_id"]]["physical_strategies"]
        )
        if set(by_strategy) != expected_strategies or set(by_strategy.values()) != {
            1,
            2,
        }:
            raise FinBenchFamilyMemoryError(
                f"training block for {query_id} is not counterbalanced"
            )
    normalized.sort(
        key=lambda item: (item["family_id"], item["query_id"], item["physical_strategy"])
    )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_TRAINING_MEMORY_SCHEMA_VERSION,
        "policy_sha256": content_hash(selected_policy),
        "workload_sha256": contract["manifest"]["workload_sha256"],
        "public_instances_sha256": contract["manifest"]["output_files"][
            "public_instances.json"
        ]["sha256"],
        "family_contracts_sha256": contract["manifest"]["output_files"][
            "family_contracts.json"
        ]["sha256"],
        "measurement_source_id": source_id,
        "training_query_ids": sorted(training),
        "training_query_count": len(training),
        "training_plan_count": len(normalized),
        "known_family_ids": sorted(
            {item["family_id"] for item in normalized}
        ),
        "observations": normalized,
        "heldout_query_ids_observed": [],
        "answer_rows_stored": False,
        "current_query_profile_calls": 0,
        "oracle_inputs": [],
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["training_memory_sha256"] = content_hash(body)
    return FinBenchTrainingMemory(body)


def _validated_memory(
    value: FinBenchTrainingMemory | Mapping[str, Any] | str | Path,
    *,
    contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(value, FinBenchTrainingMemory):
        raw = value.to_dict()
    else:
        raw = _json_object(value, name="FinBench training memory")
    if set(raw) != _MEMORY_FIELDS:
        raise FinBenchFamilyMemoryError("training memory fields changed")
    observed = raw.get("training_memory_sha256")
    if not isinstance(observed, str) or _SHA256.fullmatch(observed) is None:
        raise FinBenchFamilyMemoryError("training memory hash is invalid")
    body = {key: item for key, item in raw.items() if key != "training_memory_sha256"}
    if content_hash(body) != observed:
        raise FinBenchFamilyMemoryError("training memory hash mismatch")
    if (
        raw.get("schema_version") != FINBENCH_TRAINING_MEMORY_SCHEMA_VERSION
        or raw.get("policy_sha256") != content_hash(policy)
        or raw.get("workload_sha256")
        != contract["manifest"]["workload_sha256"]
        or raw.get("public_instances_sha256")
        != contract["manifest"]["output_files"]["public_instances.json"]["sha256"]
        or raw.get("family_contracts_sha256")
        != contract["manifest"]["output_files"]["family_contracts.json"]["sha256"]
        or raw.get("training_query_count") != 16
        or raw.get("training_plan_count") != 32
        or raw.get("known_family_ids")
        != ["f1_direct_transfer_control", "f2_temporal_path_control"]
        or raw.get("heldout_query_ids_observed") != []
        or raw.get("answer_rows_stored") is not False
        or raw.get("current_query_profile_calls") != 0
        or raw.get("oracle_inputs") != []
        or raw.get("post_execution_measurements_used") is not False
        or raw.get("automatic_retries") != 0
        or raw.get("paper_result") is not False
    ):
        raise FinBenchFamilyMemoryError("training memory boundary changed")
    expected_training = sorted(
        query_id
        for query_id, item in contract["instances"].items()
        if item["split_role"] == "training"
    )
    if raw.get("training_query_ids") != expected_training:
        raise FinBenchFamilyMemoryError("training memory split identity changed")
    observations = raw.get("observations")
    if not isinstance(observations, list) or len(observations) != 32:
        raise FinBenchFamilyMemoryError("training memory observations are incomplete")
    expected_pairs = {
        (query_id, strategy)
        for query_id in expected_training
        for strategy in contract["families"][
            contract["instances"][query_id]["family_id"]
        ]["physical_strategies"]
    }
    observed_pairs: set[tuple[str, str]] = set()
    repetition_ids: set[str] = set()
    positions: dict[tuple[str, int], dict[str, int]] = {}
    _safe_id(raw.get("measurement_source_id"), name="measurement_source_id")
    for item in observations:
        if not isinstance(item, Mapping) or set(item) != _MEMORY_OBSERVATION_FIELDS:
            raise FinBenchFamilyMemoryError("training memory observation is invalid")
        identity = {key: value for key, value in item.items() if key != "observation_sha256"}
        if item.get("observation_sha256") != content_hash(identity):
            raise FinBenchFamilyMemoryError("training observation hash mismatch")
        query_id = _safe_id(item.get("query_id"), name="training query_id")
        family_id = _safe_id(item.get("family_id"), name="training family_id")
        strategy = _safe_id(
            item.get("physical_strategy"), name="training physical strategy"
        )
        pair = (query_id, strategy)
        if pair in observed_pairs or pair not in expected_pairs:
            raise FinBenchFamilyMemoryError("training observation identity changed")
        instance = contract["instances"][query_id]
        if (
            family_id != instance["family_id"]
            or strategy
            not in contract["families"][family_id]["physical_strategies"]
        ):
            raise FinBenchFamilyMemoryError("training observation family changed")
        if item.get("features") != _feature_vector(contract["instances"][query_id]):
            raise FinBenchFamilyMemoryError("training observation features changed")
        repetitions, median_elapsed, median_bytes = _validate_repetitions(
            item.get("repetitions"),
            query_id=query_id,
            strategy=strategy,
            minimum=policy["minimum_repetitions_per_plan"],
        )
        if (
            item.get("repetitions") != repetitions
            or item.get("repetition_count") != len(repetitions)
            or item.get("median_elapsed_ms") != median_elapsed
            or item.get("median_total_bytes_moved") != median_bytes
        ):
            raise FinBenchFamilyMemoryError(
                "training observation aggregate changed"
            )
        for repetition in repetitions:
            repetition_id = str(repetition["repetition_id"])
            if repetition_id in repetition_ids:
                raise FinBenchFamilyMemoryError(
                    "training repetition IDs are not globally unique"
                )
            repetition_ids.add(repetition_id)
            positions.setdefault(
                (query_id, int(repetition["block_index"])), {}
            )[strategy] = int(repetition["order_position"])
        observed_pairs.add(pair)
    if observed_pairs != expected_pairs:
        raise FinBenchFamilyMemoryError("training memory plan coverage changed")
    for (query_id, _block), by_strategy in positions.items():
        expected_strategies = set(
            contract["families"][
                contract["instances"][query_id]["family_id"]
            ]["physical_strategies"]
        )
        if set(by_strategy) != expected_strategies or set(by_strategy.values()) != {
            1,
            2,
        }:
            raise FinBenchFamilyMemoryError(
                f"training block for {query_id} is not counterbalanced"
            )
    return raw


def _distance(
    left: Mapping[str, float],
    right: Mapping[str, float],
    ranges: Mapping[str, tuple[float, float]],
) -> float:
    total = 0.0
    for name, (minimum, maximum) in ranges.items():
        width = maximum - minimum
        if width == 0:
            total += 0.0 if left[name] == right[name] else 1.0
        else:
            total += abs(left[name] - right[name]) / width
    return total


def _weighted_prediction(
    target: Mapping[str, float],
    observations: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str],
    neighbor_count: int,
) -> dict[str, Any]:
    ranges = {
        name: (
            min(float(item["features"][name]) for item in observations),
            max(float(item["features"][name]) for item in observations),
        )
        for name in feature_names
    }
    distances = [
        (
            _distance(target, item["features"], ranges),
            str(item["query_id"]),
            item,
        )
        for item in observations
    ]
    distances.sort(key=lambda item: (item[0], item[1]))
    exact = [item for item in distances if item[0] == 0]
    selected = exact if exact else distances[:neighbor_count]
    weights = [1.0 if exact else 1.0 / item[0] for item in selected]
    weight_sum = sum(weights)
    latency = sum(
        weight * float(item[2]["median_elapsed_ms"])
        for weight, item in zip(weights, selected, strict=True)
    ) / weight_sum
    moved = sum(
        weight * float(item[2]["median_total_bytes_moved"])
        for weight, item in zip(weights, selected, strict=True)
    ) / weight_sum
    latency_uncertainty = sum(
        weight * abs(float(item[2]["median_elapsed_ms"]) - latency)
        for weight, item in zip(weights, selected, strict=True)
    ) / weight_sum
    bytes_uncertainty = sum(
        weight * abs(float(item[2]["median_total_bytes_moved"]) - moved)
        for weight, item in zip(weights, selected, strict=True)
    ) / weight_sum
    return {
        "predicted_elapsed_ms": latency,
        "predicted_total_bytes_moved": moved,
        "elapsed_uncertainty_ms": latency_uncertainty,
        "bytes_uncertainty": bytes_uncertainty,
        "neighbor_query_ids": [item[1] for item in selected],
        "neighbor_distances": [item[0] for item in selected],
    }


def _pareto_strategy_ids(predictions: Sequence[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for candidate in predictions:
        dominated = any(
            other is not candidate
            and float(other["predicted_elapsed_ms"])
            <= float(candidate["predicted_elapsed_ms"])
            and float(other["predicted_total_bytes_moved"])
            <= float(candidate["predicted_total_bytes_moved"])
            and (
                float(other["predicted_elapsed_ms"])
                < float(candidate["predicted_elapsed_ms"])
                or float(other["predicted_total_bytes_moved"])
                < float(candidate["predicted_total_bytes_moved"])
            )
            for other in predictions
        )
        if not dominated:
            result.append(str(candidate["physical_strategy"]))
    return sorted(result)


def predict_finbench_heldout_plans(
    *,
    workload_root: str | Path,
    memory: FinBenchTrainingMemory | Mapping[str, Any] | str | Path,
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
) -> FinBenchPredictionSuite:
    """Predict held-out physical routes with zero current-query observations."""

    selected_policy = _policy(policy)
    contract = _public_contract(workload_root)
    memory_payload = _validated_memory(
        memory, contract=contract, policy=selected_policy
    )
    by_family_strategy: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in memory_payload["observations"]:
        item = dict(raw)
        by_family_strategy.setdefault(
            (str(item["family_id"]), str(item["physical_strategy"])), []
        ).append(item)
    heldout = {
        query_id: item
        for query_id, item in contract["instances"].items()
        if item["split_role"] in _HELDOUT_ROLES
    }
    if len(heldout) != 20:
        raise FinBenchFamilyMemoryError("held-out FinBench split changed")
    predictions: list[dict[str, Any]] = []
    for query_id in sorted(heldout):
        instance = heldout[query_id]
        family_id = str(instance["family_id"])
        family = contract["families"][family_id]
        strategies = list(family["physical_strategies"])
        target = _feature_vector(instance)
        strategy_predictions: list[dict[str, Any]] = []
        for strategy in strategies:
            history = by_family_strategy.get((family_id, strategy), [])
            if history:
                predicted = _weighted_prediction(
                    target,
                    history,
                    feature_names=_FEATURES[family_id],
                    neighbor_count=selected_policy["neighbor_count"],
                )
                strategy_predictions.append(
                    {"physical_strategy": strategy, **predicted}
                )
        if strategy_predictions:
            if len(strategy_predictions) != 2:
                raise FinBenchFamilyMemoryError(
                    "known-family strategy memory is incomplete"
                )
            ordered = sorted(
                strategy_predictions,
                key=lambda item: (
                    item["predicted_elapsed_ms"],
                    item["predicted_total_bytes_moved"],
                    item["physical_strategy"],
                ),
            )
            selected_strategy = str(ordered[0]["physical_strategy"])
            source = "family_memory_knn"
            stratum = "heldout_instance"
            frontier = _pareto_strategy_ids(strategy_predictions)
            frontier_available = True
        else:
            fallback = family.get("cold_start_fallback")
            if fallback not in strategies or instance["split_role"] != "heldout_family":
                raise FinBenchFamilyMemoryError(
                    "cold-start family fallback is missing or invalid"
                )
            selected_strategy = str(fallback)
            source = "predeclared_cold_start_fallback"
            stratum = "heldout_family_cold_start"
            frontier = []
            frontier_available = False
        prediction = {
            "query_id": query_id,
            "family_id": family_id,
            "split_role": instance["split_role"],
            "evaluation_stratum": stratum,
            "features": target,
            "selection_source": source,
            "selected_physical_strategy": selected_strategy,
            "predicted_physical_frontier": frontier,
            "physical_frontier_available": frontier_available,
            "strategy_predictions": strategy_predictions,
            "current_query_profile_calls": 0,
            "oracle_inputs": [],
            "post_execution_measurements_used": False,
        }
        prediction["prediction_sha256"] = content_hash(prediction)
        predictions.append(prediction)
    known = sum(item["selection_source"] == "family_memory_knn" for item in predictions)
    cold = len(predictions) - known
    if known != 8 or cold != 12:
        raise FinBenchFamilyMemoryError("known/cold-start evaluation strata changed")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_PREDICTION_SUITE_SCHEMA_VERSION,
        "policy_sha256": content_hash(selected_policy),
        "workload_sha256": contract["manifest"]["workload_sha256"],
        "training_memory_sha256": memory_payload["training_memory_sha256"],
        "heldout_query_count": len(predictions),
        "known_family_query_count": known,
        "cold_start_query_count": cold,
        "predictions": predictions,
        "current_query_profile_calls": 0,
        "oracle_inputs": [],
        "post_execution_measurements_used": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["prediction_suite_sha256"] = content_hash(body)
    return FinBenchPredictionSuite(body)
