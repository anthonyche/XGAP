"""Build leakage-safe cross-fit family-memory predictions for FinBench.

Every seen-family query is assigned one evaluation fold by the result-blind
population compiler.  Its prediction uses measurements from the other three
folds of the same family only.  The held-out family never enters memory and is
reported through its predeclared fallback.  This module reads the public
workload and supplied training observations; it never opens answer oracles or
profiles a current query.
"""

from __future__ import annotations

import copy
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_workload import (
    FINBENCH_CONFIRMATORY_WORKLOAD_GENERATOR_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_selection_admission import (
    validate_finbench_confirmatory_selection_admission,
)
from xgap.experiments.m15_finbench_family_memory import (
    DEFAULT_POLICY_PATH,
    FinBenchFamilyMemoryError,
    _feature_vector,
    _pareto_strategy_ids,
    _policy,
    _safe_id,
    _validate_repetitions,
    _weighted_prediction,
)
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
)


FINBENCH_CONFIRMATORY_CROSSFIT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-crossfit-prediction-suite-v1"
)
_F1 = "f1_direct_transfer_control"
_F2 = "f2_temporal_path_control"
_F3 = "f3_aggregate_risk_ranking"
_SEEN = (_F1, _F2)
_FAMILIES = (_F1, _F2, _F3)
_STRATEGIES = {
    _F1: ("graph_first_hash", "control_first_bind"),
    _F2: ("path_first_hash", "control_first_bound_path"),
    _F3: ("aggregate_first_hash", "control_first_bound_aggregate"),
}
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


class FinBenchConfirmatoryCrossfitError(ValueError):
    """Raised when a cross-fit split or observation boundary drifts."""


@dataclass(frozen=True)
class FinBenchConfirmatoryCrossfitSuite:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def suite_hash(self) -> str:
        return str(self.payload["crossfit_prediction_suite_sha256"])


def _contract(workload_root: str | Path) -> dict[str, Any]:
    loaded = load_finbench_primary_public_workload(workload_root)
    manifest = loaded["manifest"]
    public = loaded["public_instances"]
    contracts = loaded["family_contracts"]
    if (
        manifest.get("generator_version")
        != FINBENCH_CONFIRMATORY_WORKLOAD_GENERATOR_VERSION
        or manifest.get("confirmatory_workload_compilation_authorized") is not True
        or manifest.get("confirmatory_execution_authorized") is not False
        or manifest.get("backend_calls") != 0
        or manifest.get("current_query_profile_calls") != 0
        or manifest.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryCrossfitError(
            "confirmatory workload boundary changed"
        )
    raw_instances = public.get("instances")
    raw_families = contracts.get("families")
    if (
        not isinstance(raw_instances, list)
        or len(raw_instances) not in {36, 48, 60}
        or not isinstance(raw_families, list)
        or [item.get("family_id") for item in raw_families if isinstance(item, Mapping)]
        != list(_FAMILIES)
    ):
        raise FinBenchConfirmatoryCrossfitError("confirmatory population shape changed")
    instances: dict[str, dict[str, Any]] = {}
    for raw in raw_instances:
        if not isinstance(raw, Mapping):
            raise FinBenchConfirmatoryCrossfitError("public query instance is invalid")
        item = copy.deepcopy(dict(raw))
        query_id = _safe_id(item.get("query_id"), name="query_id")
        family_id = _safe_id(item.get("family_id"), name="family_id")
        if query_id in instances or family_id not in _FAMILIES:
            raise FinBenchConfirmatoryCrossfitError("query identity changed")
        _feature_vector(item)
        fold = item.get("evaluation_fold_id")
        if family_id in _SEEN:
            if (
                item.get("split_role") != "crossfit_seen_family"
                or fold not in {1, 2, 3, 4}
                or sorted(item.get("training_fold_ids", []))
                != [candidate for candidate in range(1, 5) if candidate != fold]
            ):
                raise FinBenchConfirmatoryCrossfitError("cross-fit assignment changed")
        elif (
            item.get("split_role") != "heldout_family"
            or fold is not None
            or item.get("training_fold_ids") != []
        ):
            raise FinBenchConfirmatoryCrossfitError("cold-family assignment changed")
        instances[query_id] = item
    families: dict[str, dict[str, Any]] = {}
    for raw in raw_families:
        if not isinstance(raw, Mapping):
            raise FinBenchConfirmatoryCrossfitError("family contract is invalid")
        item = copy.deepcopy(dict(raw))
        family_id = str(item["family_id"])
        strategies = item.get("physical_strategies")
        if (
            family_id in families
            or not isinstance(strategies, list)
            or tuple(strategies) != _STRATEGIES[family_id]
        ):
            raise FinBenchConfirmatoryCrossfitError("family strategies changed")
        families[family_id] = item
    per_family = {
        family_id: sum(item["family_id"] == family_id for item in instances.values())
        for family_id in _FAMILIES
    }
    if len(set(per_family.values())) != 1:
        raise FinBenchConfirmatoryCrossfitError("family allocation is not balanced")
    fold_counts = {
        (family_id, fold): sum(
            item["family_id"] == family_id
            and item.get("evaluation_fold_id") == fold
            for item in instances.values()
        )
        for family_id in _SEEN
        for fold in range(1, 5)
    }
    if len(set(fold_counts.values())) != 1:
        raise FinBenchConfirmatoryCrossfitError("cross-fit fold allocation is unbalanced")
    return {
        "loaded": loaded,
        "manifest": manifest,
        "instances": instances,
        "families": families,
        "per_family": per_family,
    }


def _observations(
    raw_observations: Sequence[Mapping[str, Any]],
    *,
    contract: Mapping[str, Any],
    policy: Mapping[str, Any],
    selection_admission: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    instances = contract["instances"]
    families = contract["families"]
    seen_instances = {
        query_id: item
        for query_id, item in instances.items()
        if item["family_id"] in _SEEN
    }
    expected_pairs = {
        (query_id, strategy)
        for query_id, item in seen_instances.items()
        for strategy in families[item["family_id"]]["physical_strategies"]
    }
    if len(raw_observations) != len(expected_pairs):
        raise FinBenchConfirmatoryCrossfitError(
            "cross-fit observations do not cover every seen-family plan"
        )
    normalized: list[dict[str, Any]] = []
    observed_pairs: set[tuple[str, str]] = set()
    repetition_ids: set[str] = set()
    positions: dict[tuple[str, int], dict[str, int]] = {}
    for raw in raw_observations:
        if not isinstance(raw, Mapping) or set(raw) != _RAW_OBSERVATION_FIELDS:
            raise FinBenchConfirmatoryCrossfitError("observation fields changed")
        query_id = _safe_id(raw["query_id"], name="query_id")
        family_id = _safe_id(raw["family_id"], name="family_id")
        strategy = _safe_id(raw["physical_strategy"], name="physical_strategy")
        pair = (query_id, strategy)
        instance = seen_instances.get(query_id)
        if (
            pair in observed_pairs
            or pair not in expected_pairs
            or instance is None
            or instance["family_id"] != family_id
        ):
            raise FinBenchConfirmatoryCrossfitError(
                "unknown, duplicate, cold-family, or mislabeled observation"
            )
        if selection_admission is None:
            try:
                repetitions, median_elapsed, median_bytes = _validate_repetitions(
                    raw["repetitions"],
                    query_id=query_id,
                    strategy=strategy,
                    minimum=policy["minimum_repetitions_per_plan"],
                )
            except FinBenchFamilyMemoryError as exc:
                raise FinBenchConfirmatoryCrossfitError(str(exc)) from exc
        else:
            repetitions, median_elapsed, median_bytes = (
                _validate_preoracle_repetitions(
                    raw["repetitions"],
                    query_id=query_id,
                    strategy=strategy,
                    minimum=policy["minimum_repetitions_per_plan"],
                )
            )
        for repetition in repetitions:
            repetition_id = str(repetition["repetition_id"])
            if repetition_id in repetition_ids:
                raise FinBenchConfirmatoryCrossfitError(
                    "repetition IDs are not globally unique"
                )
            repetition_ids.add(repetition_id)
            positions.setdefault(
                (query_id, int(repetition["block_index"])), {}
            )[strategy] = int(repetition["order_position"])
        item = {
            "query_id": query_id,
            "family_id": family_id,
            "evaluation_fold_id": instance["evaluation_fold_id"],
            "physical_strategy": strategy,
            "features": _feature_vector(instance),
            "repetitions": repetitions,
            "repetition_count": len(repetitions),
            "median_elapsed_ms": median_elapsed,
            "median_total_bytes_moved": median_bytes,
        }
        item["observation_sha256"] = content_hash(item)
        normalized.append(item)
        observed_pairs.add(pair)
    if observed_pairs != expected_pairs:
        raise FinBenchConfirmatoryCrossfitError("observation plan coverage changed")
    for (query_id, _block), by_strategy in positions.items():
        expected = set(
            families[seen_instances[query_id]["family_id"]]["physical_strategies"]
        )
        if set(by_strategy) != expected or set(by_strategy.values()) != {1, 2}:
            raise FinBenchConfirmatoryCrossfitError(
                f"measurement block is not counterbalanced for {query_id}"
            )
    return sorted(
        normalized,
        key=lambda item: (
            item["family_id"],
            item["query_id"],
            item["physical_strategy"],
        ),
    )


def _validate_preoracle_repetitions(
    repetitions: object,
    *,
    query_id: str,
    strategy: str,
    minimum: int,
) -> tuple[list[dict[str, Any]], float, float]:
    """Admit only observed costs whose answer content remains unopened."""

    if not isinstance(repetitions, list) or not (
        minimum <= len(repetitions) <= 7
    ):
        raise FinBenchConfirmatoryCrossfitError(
            "pre-oracle training repetitions are incomplete"
        )
    normalized: list[dict[str, Any]] = []
    repetition_ids: set[str] = set()
    block_ids: set[int] = set()
    for raw in repetitions:
        if not isinstance(raw, Mapping) or set(raw) != _RAW_REPETITION_FIELDS:
            raise FinBenchConfirmatoryCrossfitError(
                "pre-oracle training repetition fields changed"
            )
        item = copy.deepcopy(dict(raw))
        repetition_id = _safe_id(item["repetition_id"], name="repetition_id")
        block = item["block_index"]
        position = item["order_position"]
        elapsed = item["elapsed_ms"]
        moved = item["total_bytes_moved"]
        if (
            repetition_id in repetition_ids
            or isinstance(block, bool)
            or not isinstance(block, int)
            or block not in range(1, 8)
            or block in block_ids
            or position not in {1, 2}
            or item["execution_success"] is not True
            or item["exact_answer"] is not None
            or item["total_remote_calls"] != 2
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed))
            or float(elapsed) < 0
            or isinstance(moved, bool)
            or not isinstance(moved, int)
            or moved < 0
        ):
            raise FinBenchConfirmatoryCrossfitError(
                f"inadmissible pre-oracle repetition for {query_id}/{strategy}"
            )
        repetition_ids.add(repetition_id)
        block_ids.add(block)
        normalized.append(item)
    normalized.sort(key=lambda item: (item["block_index"], item["repetition_id"]))
    return (
        normalized,
        float(statistics.median(item["elapsed_ms"] for item in normalized)),
        float(
            statistics.median(
                item["total_bytes_moved"] for item in normalized
            )
        ),
    )


def build_finbench_confirmatory_crossfit_predictions(
    *,
    workload_root: str | Path,
    raw_observations: Sequence[Mapping[str, Any]],
    measurement_source_id: str,
    policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
    selection_admission: Mapping[str, Any] | None = None,
) -> FinBenchConfirmatoryCrossfitSuite:
    """Freeze four fold memories and out-of-sample predictions."""

    try:
        selected_policy = _policy(policy)
    except FinBenchFamilyMemoryError as exc:
        raise FinBenchConfirmatoryCrossfitError(str(exc)) from exc
    source_id = _safe_id(measurement_source_id, name="measurement_source_id")
    contract = _contract(workload_root)
    admission = (
        validate_finbench_confirmatory_selection_admission(
            selection_admission,
            workload_sha256=str(contract["manifest"]["workload_sha256"]),
        )
        if selection_admission is not None
        else None
    )
    if len(contract["instances"]) == 48 and admission is None:
        raise FinBenchConfirmatoryCrossfitError(
            "formal pre-oracle cross-fit requires selection admission"
        )
    observations = _observations(
        raw_observations,
        contract=contract,
        policy=selected_policy,
        selection_admission=admission,
    )
    instances = contract["instances"]
    families = contract["families"]
    fold_memories: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    for fold in range(1, 5):
        evaluation_ids = sorted(
            query_id
            for query_id, item in instances.items()
            if item["family_id"] in _SEEN and item["evaluation_fold_id"] == fold
        )
        training_ids = sorted(
            query_id
            for query_id, item in instances.items()
            if item["family_id"] in _SEEN and item["evaluation_fold_id"] != fold
        )
        fold_observations = [
            item for item in observations if item["query_id"] in training_ids
        ]
        memory_body: dict[str, Any] = {
            "fold_id": fold,
            "training_query_ids": training_ids,
            "evaluation_query_ids": evaluation_ids,
            "training_query_count": len(training_ids),
            "evaluation_query_count": len(evaluation_ids),
            "observations": fold_observations,
            "evaluation_query_observations_in_memory": [],
            "current_query_profile_calls": 0,
            "oracle_inputs": [],
        }
        memory = {**memory_body, "fold_memory_sha256": content_hash(memory_body)}
        fold_memories.append(memory)
        by_family_strategy: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for observation in fold_observations:
            by_family_strategy.setdefault(
                (
                    str(observation["family_id"]),
                    str(observation["physical_strategy"]),
                ),
                [],
            ).append(observation)
        for query_id in evaluation_ids:
            instance = instances[query_id]
            family_id = str(instance["family_id"])
            target = _feature_vector(instance)
            strategy_predictions: list[dict[str, Any]] = []
            for strategy in families[family_id]["physical_strategies"]:
                history = by_family_strategy[(family_id, strategy)]
                predicted = _weighted_prediction(
                    target,
                    history,
                    feature_names=tuple(target),
                    neighbor_count=selected_policy["neighbor_count"],
                )
                if query_id in predicted["neighbor_query_ids"] or any(
                    instances[neighbor]["evaluation_fold_id"] == fold
                    for neighbor in predicted["neighbor_query_ids"]
                ):
                    raise FinBenchConfirmatoryCrossfitError(
                        "evaluation fold leaked into prediction neighbors"
                    )
                strategy_predictions.append(
                    {"physical_strategy": strategy, **predicted}
                )
            ordered = sorted(
                strategy_predictions,
                key=lambda item: (
                    item["predicted_elapsed_ms"],
                    item["predicted_total_bytes_moved"],
                    item["physical_strategy"],
                ),
            )
            prediction = {
                "query_id": query_id,
                "family_id": family_id,
                "evaluation_fold_id": fold,
                "evaluation_stratum": "crossfit_seen_family",
                "features": target,
                "fold_memory_sha256": memory["fold_memory_sha256"],
                "selection_source": "crossfit_family_memory_knn",
                "selected_physical_strategy": ordered[0]["physical_strategy"],
                "predicted_physical_frontier": _pareto_strategy_ids(
                    strategy_predictions
                ),
                "physical_frontier_available": True,
                "strategy_predictions": strategy_predictions,
                "own_query_observation_used": False,
                "historical_training_measurements_used": True,
                "current_query_measurements_used": False,
                "current_query_profile_calls": 0,
                "oracle_inputs": [],
            }
            prediction["prediction_sha256"] = content_hash(prediction)
            predictions.append(prediction)
    for query_id in sorted(instances):
        instance = instances[query_id]
        if instance["family_id"] != _F3:
            continue
        fallback = families[_F3].get("cold_start_fallback")
        strategies = families[_F3]["physical_strategies"]
        if fallback not in strategies:
            raise FinBenchConfirmatoryCrossfitError("cold-family fallback changed")
        prediction = {
            "query_id": query_id,
            "family_id": _F3,
            "evaluation_fold_id": None,
            "evaluation_stratum": "heldout_family_cold_start",
            "features": _feature_vector(instance),
            "fold_memory_sha256": None,
            "selection_source": "predeclared_cold_start_fallback",
            "selected_physical_strategy": fallback,
            "predicted_physical_frontier": [],
            "physical_frontier_available": False,
            "strategy_predictions": [],
            "own_query_observation_used": False,
            "historical_training_measurements_used": False,
            "current_query_measurements_used": False,
            "current_query_profile_calls": 0,
            "oracle_inputs": [],
        }
        prediction["prediction_sha256"] = content_hash(prediction)
        predictions.append(prediction)
    predictions.sort(key=lambda item: item["query_id"])
    seen_count = sum(item["family_id"] in _SEEN for item in predictions)
    cold_count = len(predictions) - seen_count
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_CROSSFIT_SCHEMA_VERSION,
        "policy_sha256": content_hash(selected_policy),
        "workload_sha256": contract["manifest"]["workload_sha256"],
        "population_registry_sha256": contract["manifest"][
            "population_registry_sha256"
        ],
        "population_approval_sha256": contract["manifest"][
            "population_approval_sha256"
        ],
        "measurement_source_id": source_id,
        "selection_admission_sha256": (
            admission["selection_admission_sha256"]
            if admission is not None
            else None
        ),
        "training_exactness_semantics": (
            admission["training_exactness_semantics"]
            if admission is not None
            else "observed_development_query_oracle"
        ),
        "current_confirmatory_query_oracle_opened": False,
        "final_confirmatory_oracle_is_authoritative": True,
        "raw_observation_suite_sha256": content_hash(observations),
        "fold_count": 4,
        "fold_memories": fold_memories,
        "prediction_count": len(predictions),
        "seen_family_prediction_count": seen_count,
        "cold_family_prediction_count": cold_count,
        "predictions": predictions,
        "crossfit_exclusion_enforced": True,
        "historical_training_measurements_used": True,
        "current_query_measurements_used_for_own_prediction": False,
        "current_query_profile_calls": 0,
        "oracle_inputs": [],
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["crossfit_prediction_suite_sha256"] = content_hash(body)
    return FinBenchConfirmatoryCrossfitSuite(body)
