"""Build and analyze the FinBench confirmatory measurement ledger.

This module is deliberately independent of the live runner.  It accepts only
measurements whose identities were frozen in the Option-A schedule, resolves
the two online methods from pre-execution selection seals, retains query
timeouts as method outcomes, and computes query-level paired statistics.
Repeated executions are aggregated within a query and never become independent
inferential units.  The held-out F3 family is reported as cold start only.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import math
import random
import re
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_crossfit import (
    FINBENCH_CONFIRMATORY_CROSSFIT_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_confirmatory_schedule import (
    FINBENCH_CONFIRMATORY_SCHEDULE_SCHEMA_VERSION,
)


FINBENCH_CONFIRMATORY_FAMILY_SELECTION_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-family-selection-seal-v1"
)
FINBENCH_CONFIRMATORY_PROFILE_SELECTION_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-profile-selection-seal-v1"
)
FINBENCH_CONFIRMATORY_MEASUREMENT_LEDGER_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-measurement-ledger-v1"
)
FINBENCH_CONFIRMATORY_ANALYSIS_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-analysis-v1"
)

_F1 = "f1_direct_transfer_control"
_F2 = "f2_temporal_path_control"
_F3 = "f3_aggregate_risk_ranking"
_SEEN = (_F1, _F2)
_STRATEGIES = {
    _F1: ("graph_first_hash", "control_first_bind"),
    _F2: ("path_first_hash", "control_first_bound_path"),
    _F3: ("aggregate_first_hash", "control_first_bound_aggregate"),
}
_TIMEOUT_MS = 60_000.0
_BOOTSTRAP_DRAWS = 10_000
_RANDOMIZATION_DRAWS = 100_000
_CI_SEED = "m15-sigmod2027-finbench-ci-v1"
_TEST_SEED = "m15-sigmod2027-finbench-randomization-v1"
_MEASUREMENT_FIELDS = {
    "scheduled_identity",
    "attempt_id",
    "outcome",
    "elapsed_ms",
    "total_bytes_moved",
    "total_remote_calls",
    "exact_answer",
    "physical_strategy",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FinBenchConfirmatoryAnalysisError(ValueError):
    """Raised when a frozen identity, seal, or analysis boundary drifts."""


@dataclass(frozen=True)
class FinBenchConfirmatoryLedger:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def ledger_hash(self) -> str:
        return str(self.payload["ledger_sha256"])


def _hashed_object(
    value: Mapping[str, Any], *, hash_field: str, name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatoryAnalysisError(f"{name} must be an object")
    payload = copy.deepcopy(dict(value))
    claimed = payload.get(hash_field)
    if not isinstance(claimed, str) or _SHA256.fullmatch(claimed) is None:
        raise FinBenchConfirmatoryAnalysisError(f"{name} hash is missing")
    body = {key: item for key, item in payload.items() if key != hash_field}
    if content_hash(body) != claimed:
        raise FinBenchConfirmatoryAnalysisError(f"{name} hash mismatch")
    return payload


def _schedule(value: Mapping[str, Any]) -> dict[str, Any]:
    schedule = _hashed_object(
        value, hash_field="schedule_sha256", name="measurement schedule"
    )
    expected_counts = {
        "seen_family_query_count": 32,
        "cold_family_query_count": 16,
        "inferential_query_count": 32,
        "training_plan_runs": 448,
        "profile_acquisition_plan_runs": 96,
        "selected_serving_plan_runs": 672,
        "evaluation_shadow_plan_runs": 672,
        "total_plan_runs": 1888,
        "total_backend_calls": 3776,
    }
    contract = schedule.get("execution_contract")
    if (
        schedule.get("schema_version")
        != FINBENCH_CONFIRMATORY_SCHEDULE_SCHEMA_VERSION
        or schedule.get("expected_counts") != expected_counts
        or schedule.get("query_instance_is_inferential_unit") is not True
        or schedule.get("repetitions_are_not_independent_units") is not True
        or schedule.get("current_query_profile_calls_for_family_memory") != 0
        or schedule.get("automatic_retries") != 0
        or schedule.get("paper_result") is not False
        or schedule.get("measurement_block_count") != 22
        or not isinstance(contract, Mapping)
        or contract.get("backend_timeout_seconds") != 60
        or contract.get("automatic_retries") != 0
        or contract.get("infrastructure_replacement_limit") != 1
        or contract.get("query_timeout_is_method_outcome") is not True
        or contract.get("query_timeout_is_not_replacement_eligible") is not True
    ):
        raise FinBenchConfirmatoryAnalysisError("Option-A schedule boundary changed")
    seen = schedule.get("seen_family_query_ids")
    cold = schedule.get("cold_family_query_ids")
    queries = schedule.get("query_ids")
    if (
        not isinstance(seen, list)
        or len(seen) != 32
        or len(set(seen)) != 32
        or not isinstance(cold, list)
        or len(cold) != 16
        or len(set(cold)) != 16
        or not isinstance(queries, list)
        or set(queries) != set(seen) | set(cold)
        or set(seen) & set(cold)
    ):
        raise FinBenchConfirmatoryAnalysisError("query strata changed")
    return schedule


def _suite(
    value: Mapping[str, Any], *, schedule: Mapping[str, Any]
) -> dict[str, Any]:
    suite = _hashed_object(
        value,
        hash_field="crossfit_prediction_suite_sha256",
        name="crossfit prediction suite",
    )
    predictions = suite.get("predictions")
    if (
        suite.get("schema_version")
        != FINBENCH_CONFIRMATORY_CROSSFIT_SCHEMA_VERSION
        or suite.get("workload_sha256") != schedule.get("workload_sha256")
        or suite.get("prediction_count") != 48
        or suite.get("seen_family_prediction_count") != 32
        or suite.get("cold_family_prediction_count") != 16
        or suite.get("current_query_profile_calls") != 0
        or suite.get("current_query_measurements_used_for_own_prediction") is not False
        or suite.get("automatic_retries") != 0
        or suite.get("paper_result") is not False
        or not isinstance(predictions, list)
        or len(predictions) != 48
    ):
        raise FinBenchConfirmatoryAnalysisError("crossfit prediction boundary changed")
    by_query = {
        str(item.get("query_id")): item
        for item in predictions
        if isinstance(item, Mapping)
    }
    if set(by_query) != set(schedule["query_ids"]):
        raise FinBenchConfirmatoryAnalysisError("prediction query coverage changed")
    for query_id in schedule["seen_family_query_ids"]:
        item = by_query[query_id]
        if (
            item.get("family_id") not in _SEEN
            or item.get("evaluation_stratum") != "crossfit_seen_family"
            or item.get("selection_source") != "crossfit_family_memory_knn"
            or item.get("current_query_profile_calls") != 0
            or item.get("own_query_observation_used") is not False
            or not isinstance(item.get("strategy_predictions"), list)
            or len(item["strategy_predictions"]) != 2
        ):
            raise FinBenchConfirmatoryAnalysisError("seen-family prediction changed")
        claimed = item.get("prediction_sha256")
        prediction_body = {
            key: value for key, value in item.items() if key != "prediction_sha256"
        }
        if claimed != content_hash(prediction_body):
            raise FinBenchConfirmatoryAnalysisError("prediction hash mismatch")
    for query_id in schedule["cold_family_query_ids"]:
        item = by_query[query_id]
        if (
            item.get("family_id") != _F3
            or item.get("evaluation_stratum") != "heldout_family_cold_start"
            or item.get("selection_source") != "predeclared_cold_start_fallback"
            or item.get("strategy_predictions") != []
        ):
            raise FinBenchConfirmatoryAnalysisError("cold-family prediction changed")
        claimed = item.get("prediction_sha256")
        prediction_body = {
            key: value for key, value in item.items() if key != "prediction_sha256"
        }
        if claimed != content_hash(prediction_body):
            raise FinBenchConfirmatoryAnalysisError("prediction hash mismatch")
    return suite


def build_finbench_confirmatory_family_selection_seal(
    *, schedule: Mapping[str, Any], crossfit_prediction_suite: Mapping[str, Any]
) -> dict[str, Any]:
    """Seal family-memory/fallback physical choices before profiling."""

    frozen = _schedule(schedule)
    suite = _suite(crossfit_prediction_suite, schedule=frozen)
    selections = []
    for prediction in sorted(suite["predictions"], key=lambda item: item["query_id"]):
        family_id = str(prediction["family_id"])
        method_id = (
            "family_memory_zero_profile"
            if family_id in _SEEN
            else "predeclared_family_fallback"
        )
        selections.append(
            {
                "query_id": prediction["query_id"],
                "family_id": family_id,
                "evaluation_stratum": prediction["evaluation_stratum"],
                "method_id": method_id,
                "selected_physical_strategy": prediction[
                    "selected_physical_strategy"
                ],
                "prediction_sha256": prediction["prediction_sha256"],
            }
        )
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_FAMILY_SELECTION_SCHEMA_VERSION,
        "schedule_sha256": frozen["schedule_sha256"],
        "crossfit_prediction_suite_sha256": suite[
            "crossfit_prediction_suite_sha256"
        ],
        "selections": selections,
        "selection_count": len(selections),
        "selection_source": "sealed_crossfit_family_memory_or_predeclared_fallback",
        "current_query_profile_calls_before_seal": 0,
        "oracle_inputs": [],
        "paper_result": False,
    }
    body["selection_seal_sha256"] = content_hash(body)
    return body


def _measurement(
    raw: Mapping[str, Any], *, expected: Mapping[str, Any], strategy: str
) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != _MEASUREMENT_FIELDS:
        raise FinBenchConfirmatoryAnalysisError("measurement fields changed")
    identity = str(raw["scheduled_identity"])
    expected_identity = str(expected.get("run_id") or expected.get("slot_id"))
    if identity != expected_identity or raw["physical_strategy"] != strategy:
        raise FinBenchConfirmatoryAnalysisError(
            "measurement identity mismatch: "
            f"expected ({expected_identity}, {strategy}), "
            f"received ({identity}, {raw['physical_strategy']})"
        )
    attempt_id = raw["attempt_id"]
    if not isinstance(attempt_id, str) or not attempt_id:
        raise FinBenchConfirmatoryAnalysisError("measurement attempt_id is invalid")
    elapsed = raw["elapsed_ms"]
    calls = raw["total_remote_calls"]
    moved = raw["total_bytes_moved"]
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(float(elapsed))
        or float(elapsed) <= 0
        or isinstance(calls, bool)
        or not isinstance(calls, int)
        or calls < 0
        or calls > 2
            or (
                moved is not None
                and (
                    isinstance(moved, bool)
                    or not isinstance(moved, int)
                    or moved < 0
                )
            )
    ):
        raise FinBenchConfirmatoryAnalysisError("measurement cost is invalid")
    outcome = raw["outcome"]
    if outcome == "success":
        if calls != 2 or moved is None or raw["exact_answer"] is not True:
            raise FinBenchConfirmatoryAnalysisError("successful measurement is invalid")
        analysis_elapsed = float(elapsed)
    elif outcome == "query_timeout":
        if float(elapsed) < _TIMEOUT_MS or raw["exact_answer"] is not None:
            raise FinBenchConfirmatoryAnalysisError("query timeout is invalid")
        analysis_elapsed = _TIMEOUT_MS
    else:
        raise FinBenchConfirmatoryAnalysisError(
            "infrastructure failure is not a measurement outcome"
        )
    return {
        **copy.deepcopy(dict(expected)),
        "scheduled_identity": identity,
        "attempt_id": attempt_id,
        "physical_strategy": strategy,
        "outcome": outcome,
        "observed_elapsed_ms": float(elapsed),
        "analysis_elapsed_ms": analysis_elapsed,
        "total_bytes_moved": moved,
        "total_remote_calls": calls,
        "exact_answer": raw["exact_answer"],
        "query_timeout_is_method_outcome": outcome == "query_timeout",
    }


def _measurement_index(
    raw_measurements: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for raw in raw_measurements:
        if not isinstance(raw, Mapping):
            raise FinBenchConfirmatoryAnalysisError("measurement is not an object")
        identity = raw.get("scheduled_identity")
        if not isinstance(identity, str) or identity in result:
            raise FinBenchConfirmatoryAnalysisError(
                "measurement identity is missing or duplicated"
            )
        result[identity] = raw
    return result


def _expected_records(schedule: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "crossfit_training_runs",
        "profile_acquisition_runs",
        "selected_serving_slots",
        "evaluation_shadow_runs",
    )
    records: list[dict[str, Any]] = []
    for field in fields:
        values = schedule.get(field)
        if not isinstance(values, list):
            raise FinBenchConfirmatoryAnalysisError(f"{field} is invalid")
        records.extend(copy.deepcopy(values))
    if len(records) != 1888:
        raise FinBenchConfirmatoryAnalysisError("schedule measurement count changed")
    identities = [str(item.get("run_id") or item.get("slot_id")) for item in records]
    if any(identity == "None" for identity in identities) or len(set(identities)) != 1888:
        raise FinBenchConfirmatoryAnalysisError("schedule identities changed")
    return records


def build_finbench_confirmatory_profile_selection_seal(
    *,
    schedule: Mapping[str, Any],
    profile_measurements: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose one physical strategy per query from the two frozen profiles."""

    frozen = _schedule(schedule)
    expected = frozen["profile_acquisition_runs"]
    raw = _measurement_index(profile_measurements)
    expected_ids = {str(item["run_id"]) for item in expected}
    if set(raw) != expected_ids:
        raise FinBenchConfirmatoryAnalysisError("profile measurement coverage changed")
    by_query: dict[str, list[dict[str, Any]]] = {}
    for item in expected:
        normalized = _measurement(
            raw[str(item["run_id"])],
            expected=item,
            strategy=str(item["physical_strategy"]),
        )
        by_query.setdefault(str(item["query_id"]), []).append(normalized)
    selections = []
    for query_id in sorted(by_query):
        values = by_query[query_id]
        if len(values) != 2 or len({item["physical_strategy"] for item in values}) != 2:
            raise FinBenchConfirmatoryAnalysisError("profile pair changed")
        chosen = min(
            values,
            key=lambda item: (
                item["analysis_elapsed_ms"],
                math.inf if item["total_bytes_moved"] is None else item["total_bytes_moved"],
                item["physical_strategy"],
            ),
        )
        selections.append(
            {
                "query_id": query_id,
                "family_id": chosen["family_id"],
                "evaluation_stratum": chosen["evaluation_stratum"],
                "selected_physical_strategy": chosen["physical_strategy"],
                "source_run_ids": sorted(item["run_id"] for item in values),
                "acquisition_latency_ms": sum(
                    item["analysis_elapsed_ms"] for item in values
                ),
                "acquisition_bytes": (
                    sum(item["total_bytes_moved"] for item in values)
                    if all(item["total_bytes_moved"] is not None for item in values)
                    else None
                ),
            }
        )
    if len(selections) != 48:
        raise FinBenchConfirmatoryAnalysisError("profile selection count changed")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_PROFILE_SELECTION_SCHEMA_VERSION,
        "schedule_sha256": frozen["schedule_sha256"],
        "selections": selections,
        "selection_count": len(selections),
        "profile_acquisition_plan_runs": 96,
        "selection_source": "sealed_current_query_dual_profile_costs_only",
        "oracle_inputs": [],
        "paper_result": False,
    }
    body["selection_seal_sha256"] = content_hash(body)
    return body


def _selection_map(
    value: Mapping[str, Any],
    *,
    schema_version: str,
    schedule_hash: str,
    name: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    seal = _hashed_object(value, hash_field="selection_seal_sha256", name=name)
    selections = seal.get("selections")
    if (
        seal.get("schema_version") != schema_version
        or seal.get("schedule_sha256") != schedule_hash
        or seal.get("selection_count") != 48
        or seal.get("paper_result") is not False
        or not isinstance(selections, list)
        or len(selections) != 48
    ):
        raise FinBenchConfirmatoryAnalysisError(f"{name} boundary changed")
    by_query = {
        str(item.get("query_id")): copy.deepcopy(dict(item))
        for item in selections
        if isinstance(item, Mapping)
    }
    if len(by_query) != 48:
        raise FinBenchConfirmatoryAnalysisError(f"{name} query coverage changed")
    return seal, by_query


def _attempts(
    values: Sequence[Mapping[str, Any]], *, block_ids: set[str]
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    by_block: dict[str, list[dict[str, Any]]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise FinBenchConfirmatoryAnalysisError("infrastructure attempt is invalid")
        item = copy.deepcopy(dict(raw))
        required = {
            "attempt_id",
            "measurement_block_id",
            "attempt_index",
            "status",
            "valid_measurement_count",
            "replacement_of_attempt_id",
            "failure_category",
        }
        if set(item) != required:
            raise FinBenchConfirmatoryAnalysisError("infrastructure attempt fields changed")
        attempt_id = item["attempt_id"]
        block = item["measurement_block_id"]
        if (
            not isinstance(attempt_id, str)
            or not attempt_id
            or attempt_id in seen
            or block not in block_ids
            or item["attempt_index"] not in {1, 2}
            or item["status"] not in {"completed", "infrastructure_failed"}
            or isinstance(item["valid_measurement_count"], bool)
            or not isinstance(item["valid_measurement_count"], int)
            or item["valid_measurement_count"] < 0
        ):
            raise FinBenchConfirmatoryAnalysisError("infrastructure attempt changed")
        if item["status"] == "infrastructure_failed":
            if item["valid_measurement_count"] != 0 or not isinstance(item["failure_category"], str):
                raise FinBenchConfirmatoryAnalysisError(
                    "failed infrastructure attempt contains a valid measurement"
                )
        elif item["failure_category"] is not None:
            raise FinBenchConfirmatoryAnalysisError("completed attempt has a failure")
        seen.add(attempt_id)
        by_block.setdefault(str(block), []).append(item)
        normalized.append(item)
    for block, attempts in by_block.items():
        attempts.sort(key=lambda item: item["attempt_index"])
        if len(attempts) > 2 or [item["attempt_index"] for item in attempts] != list(
            range(1, len(attempts) + 1)
        ):
            raise FinBenchConfirmatoryAnalysisError(
                f"replacement limit or attempt order changed for {block}"
            )
        if len(attempts) == 2 and (
            attempts[0]["status"] != "infrastructure_failed"
            or attempts[1]["replacement_of_attempt_id"] != attempts[0]["attempt_id"]
        ):
            raise FinBenchConfirmatoryAnalysisError("replacement provenance changed")
        if attempts[0]["replacement_of_attempt_id"] is not None:
            raise FinBenchConfirmatoryAnalysisError("first attempt is a replacement")
        if attempts[-1]["status"] != "completed":
            raise FinBenchConfirmatoryAnalysisError("measurement block did not complete")
    if set(by_block) != block_ids:
        raise FinBenchConfirmatoryAnalysisError("infrastructure attempt block coverage changed")
    return sorted(
        normalized,
        key=lambda item: (item["measurement_block_id"], item["attempt_index"]),
    )


def build_finbench_confirmatory_measurement_ledger(
    *,
    schedule: Mapping[str, Any],
    crossfit_prediction_suite: Mapping[str, Any],
    family_selection_seal: Mapping[str, Any],
    profile_selection_seal: Mapping[str, Any],
    measurements: Sequence[Mapping[str, Any]],
    infrastructure_attempts: Sequence[Mapping[str, Any]] = (),
) -> FinBenchConfirmatoryLedger:
    """Bind exactly one valid method outcome to every frozen schedule identity."""

    frozen = _schedule(schedule)
    suite = _suite(crossfit_prediction_suite, schedule=frozen)
    family_seal, family = _selection_map(
        family_selection_seal,
        schema_version=FINBENCH_CONFIRMATORY_FAMILY_SELECTION_SCHEMA_VERSION,
        schedule_hash=frozen["schedule_sha256"],
        name="family selection seal",
    )
    profile_seal, profile = _selection_map(
        profile_selection_seal,
        schema_version=FINBENCH_CONFIRMATORY_PROFILE_SELECTION_SCHEMA_VERSION,
        schedule_hash=frozen["schedule_sha256"],
        name="profile selection seal",
    )
    if set(family) != set(frozen["query_ids"]) or set(profile) != set(
        frozen["query_ids"]
    ):
        raise FinBenchConfirmatoryAnalysisError("selection seal coverage changed")
    expected_family_seal = build_finbench_confirmatory_family_selection_seal(
        schedule=frozen, crossfit_prediction_suite=suite
    )
    if family_seal != expected_family_seal:
        raise FinBenchConfirmatoryAnalysisError("family selection seal reconstruction failed")
    expected = _expected_records(frozen)
    raw = _measurement_index(measurements)
    expected_ids = {
        str(item.get("run_id") or item.get("slot_id")) for item in expected
    }
    if set(raw) != expected_ids:
        raise FinBenchConfirmatoryAnalysisError("measurement coverage changed")
    profile_ids = {str(item["run_id"]) for item in frozen["profile_acquisition_runs"]}
    expected_profile_seal = build_finbench_confirmatory_profile_selection_seal(
        schedule=frozen,
        profile_measurements=[raw[identity] for identity in sorted(profile_ids)],
    )
    if profile_seal != expected_profile_seal:
        raise FinBenchConfirmatoryAnalysisError("profile selection seal reconstruction failed")
    normalized = []
    for item in expected:
        query_id = str(item["query_id"])
        method_id = item.get("method_id")
        if method_id == "current_query_dual_profile":
            strategy = str(profile[query_id]["selected_physical_strategy"])
        elif method_id in {"family_memory_zero_profile", "predeclared_family_fallback"}:
            if method_id != family[query_id].get("method_id"):
                raise FinBenchConfirmatoryAnalysisError("serving method stratum changed")
            strategy = str(family[query_id]["selected_physical_strategy"])
        else:
            strategy = str(item["physical_strategy"])
        normalized.append(
            _measurement(
                raw[str(item.get("run_id") or item.get("slot_id"))],
                expected=item,
                strategy=strategy,
            )
        )
    attempts = _attempts(
        infrastructure_attempts, block_ids=set(frozen["measurement_block_ids"])
    )
    completed_attempts = {
        str(item["attempt_id"]): item
        for item in attempts
        if item["status"] == "completed"
    }
    measurements_by_attempt: dict[str, list[dict[str, Any]]] = {}
    for item in normalized:
        attempt = completed_attempts.get(str(item["attempt_id"]))
        if attempt is None or attempt["measurement_block_id"] != item["measurement_block_id"]:
            raise FinBenchConfirmatoryAnalysisError(
                "measurement is not bound to its completed block attempt"
            )
        measurements_by_attempt.setdefault(str(item["attempt_id"]), []).append(item)
    if any(
        attempt["valid_measurement_count"]
        != len(measurements_by_attempt.get(attempt_id, []))
        for attempt_id, attempt in completed_attempts.items()
    ):
        raise FinBenchConfirmatoryAnalysisError("valid measurement count changed")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_MEASUREMENT_LEDGER_SCHEMA_VERSION,
        "schedule_sha256": frozen["schedule_sha256"],
        "workload_sha256": frozen["workload_sha256"],
        "crossfit_prediction_suite_sha256": suite[
            "crossfit_prediction_suite_sha256"
        ],
        "family_selection_seal_sha256": family_seal["selection_seal_sha256"],
        "profile_selection_seal_sha256": profile_seal["selection_seal_sha256"],
        "seen_family_query_ids": copy.deepcopy(frozen["seen_family_query_ids"]),
        "cold_family_query_ids": copy.deepcopy(frozen["cold_family_query_ids"]),
        "family_selections": copy.deepcopy(family_seal["selections"]),
        "profile_selections": copy.deepcopy(profile_seal["selections"]),
        "crossfit_predictions": copy.deepcopy(suite["predictions"]),
        "measurements": normalized,
        "measurement_count": len(normalized),
        "query_timeout_count": sum(
            item["outcome"] == "query_timeout" for item in normalized
        ),
        "infrastructure_attempts": attempts,
        "infrastructure_replacement_count": sum(
            item["attempt_index"] == 2 for item in attempts
        ),
        "query_instance_is_inferential_unit": True,
        "repetitions_are_not_independent_units": True,
        "missing_measurements": "no_imputation",
        "query_timeout_analysis_latency_ms": _TIMEOUT_MS,
        "automatic_retries": 0,
        "oracle_opened_after_all_plan_runs": True,
        "confirmatory_statistics_ready": True,
        "paper_result": False,
    }
    body["ledger_sha256"] = content_hash(body)
    return FinBenchConfirmatoryLedger(body)


def _median(values: Sequence[float]) -> float:
    if not values or any(not math.isfinite(value) for value in values):
        raise FinBenchConfirmatoryAnalysisError("median input is invalid")
    return float(statistics.median(values))


def _summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "minimum": None, "maximum": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "median": _median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _seed(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bootstrap(rows: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    generator = random.Random(_seed(_CI_SEED))
    ratios: list[float] = []
    differences: list[float] = []
    count = len(rows)
    for _ in range(_BOOTSTRAP_DRAWS):
        sample = [rows[generator.randrange(count)] for _ in range(count)]
        ratios.append(math.exp(sum(item["log_ratio"] for item in sample) / count))
        differences.append(_median([item["difference_ms"] for item in sample]))
    return {
        "method": "query_cluster_bootstrap_percentile",
        "confidence_level": 0.95,
        "resamples": _BOOTSTRAP_DRAWS,
        "seed": _CI_SEED,
        "geometric_mean_ratio_ci": [
            _percentile(ratios, 0.025),
            _percentile(ratios, 0.975),
        ],
        "paired_median_difference_ms_ci": [
            _percentile(differences, 0.025),
            _percentile(differences, 0.975),
        ],
    }


def _sign_flip(values: Sequence[float], *, seed_suffix: str = "primary") -> dict[str, Any]:
    observed = abs(sum(values) / len(values))
    exact_count = 2 ** len(values)
    extreme = 0
    if exact_count <= _RANDOMIZATION_DRAWS:
        draws = exact_count
        for signs in itertools.product((-1.0, 1.0), repeat=len(values)):
            statistic = abs(sum(sign * value for sign, value in zip(signs, values)) / len(values))
            extreme += statistic >= observed - 1e-15
        p_value = extreme / draws
        mode = "exact"
    else:
        draws = _RANDOMIZATION_DRAWS
        effective_seed = f"{_TEST_SEED}:{seed_suffix}"
        generator = random.Random(_seed(effective_seed))
        for _ in range(draws):
            statistic = abs(
                sum((1.0 if generator.getrandbits(1) else -1.0) * value for value in values)
                / len(values)
            )
            extreme += statistic >= observed - 1e-15
        p_value = (extreme + 1) / (draws + 1)
        mode = "monte_carlo_plus_one"
    if exact_count <= _RANDOMIZATION_DRAWS:
        effective_seed = None
    return {
        "method": "two_sided_paired_sign_flip_on_query_values",
        "mode": mode,
        "draws": draws,
        "seed": effective_seed,
        "observed_absolute_mean": observed,
        "extreme_count": extreme,
        "p_value": p_value,
    }


def _holm(tests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(tests, key=lambda item: (item["p_value"], item["comparison_id"]))
    adjusted = 0.0
    result = []
    count = len(ordered)
    for rank, item in enumerate(ordered, start=1):
        adjusted = max(adjusted, min(1.0, (count - rank + 1) * float(item["p_value"])))
        result.append({**dict(item), "holm_rank": rank, "holm_adjusted_p_value": adjusted})
    return sorted(result, key=lambda item: item["comparison_id"])


def _pareto(costs: Mapping[str, Mapping[str, Any]]) -> list[str] | None:
    if any(item["total_bytes_moved"] is None for item in costs.values()):
        return None
    return sorted(
        candidate
        for candidate in costs
        if not any(
            other != candidate
            and costs[other]["latency_ms"] <= costs[candidate]["latency_ms"]
            and costs[other]["total_bytes_moved"] <= costs[candidate]["total_bytes_moved"]
            and (
                costs[other]["latency_ms"] < costs[candidate]["latency_ms"]
                or costs[other]["total_bytes_moved"] < costs[candidate]["total_bytes_moved"]
            )
            for other in costs
        )
    )


def _ledger(value: Mapping[str, Any]) -> dict[str, Any]:
    ledger = _hashed_object(value, hash_field="ledger_sha256", name="measurement ledger")
    if (
        ledger.get("schema_version")
        != FINBENCH_CONFIRMATORY_MEASUREMENT_LEDGER_SCHEMA_VERSION
        or ledger.get("measurement_count") != 1888
        or ledger.get("query_instance_is_inferential_unit") is not True
        or ledger.get("repetitions_are_not_independent_units") is not True
        or ledger.get("missing_measurements") != "no_imputation"
        or ledger.get("query_timeout_analysis_latency_ms") != _TIMEOUT_MS
        or ledger.get("automatic_retries") != 0
        or ledger.get("oracle_opened_after_all_plan_runs") is not True
        or ledger.get("confirmatory_statistics_ready") is not True
        or ledger.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryAnalysisError("measurement ledger boundary changed")
    return ledger


def _group_measurements(ledger: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in ledger["measurements"]:
        grouped.setdefault(str(item["phase"]), []).append(item)
    expected = {
        "crossfit_training_measurement": 448,
        "current_query_profile_acquisition": 96,
        "paired_selected_serving": 672,
        "postselection_shadow_evaluation": 672,
    }
    if {key: len(value) for key, value in grouped.items()} != expected:
        raise FinBenchConfirmatoryAnalysisError("ledger phase counts changed")
    return grouped


def _shadow_costs(
    values: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in values:
        grouped.setdefault(
            (str(item["query_id"]), str(item["physical_strategy"])), []
        ).append(item)
    if len(grouped) != 96 or any(len(items) != 7 for items in grouped.values()):
        raise FinBenchConfirmatoryAnalysisError("shadow repetitions changed")
    by_query: dict[str, dict[str, dict[str, Any]]] = {}
    for (query_id, strategy), items in grouped.items():
        moved = [item["total_bytes_moved"] for item in items]
        by_query.setdefault(query_id, {})[strategy] = {
            "latency_ms": _median([item["analysis_elapsed_ms"] for item in items]),
            "total_bytes_moved": (
                _median([float(item) for item in moved])
                if all(item is not None for item in moved)
                else None
            ),
            "query_timeout_count": sum(item["outcome"] == "query_timeout" for item in items),
        }
    return by_query


def _serving_costs(
    values: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for item in values:
        grouped.setdefault((str(item["query_id"]), str(item["method_id"])), []).append(item)
    if len(grouped) != 96 or any(len(items) != 7 for items in grouped.values()):
        raise FinBenchConfirmatoryAnalysisError("serving repetitions changed")
    result = {}
    for key, items in grouped.items():
        moved = [item["total_bytes_moved"] for item in items]
        result[key] = {
            "latency_ms": _median([item["analysis_elapsed_ms"] for item in items]),
            "total_bytes_moved": (
                _median([float(item) for item in moved])
                if all(item is not None for item in moved)
                else None
            ),
            "query_timeout_count": sum(item["outcome"] == "query_timeout" for item in items),
        }
    return result


def _latency_winner(costs: Mapping[str, Mapping[str, Any]]) -> str:
    return min(
        costs,
        key=lambda strategy: (
            costs[strategy]["latency_ms"],
            (
                math.inf
                if costs[strategy]["total_bytes_moved"] is None
                else costs[strategy]["total_bytes_moved"]
            ),
            strategy,
        ),
    )


def _profile_costs(
    values: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in values:
        grouped.setdefault(str(item["query_id"]), []).append(item)
    if len(grouped) != 48 or any(len(items) != 2 for items in grouped.values()):
        raise FinBenchConfirmatoryAnalysisError("profile acquisition pairs changed")
    return {
        query_id: {
            "latency_ms": sum(item["analysis_elapsed_ms"] for item in items),
            "total_bytes_moved": (
                sum(float(item["total_bytes_moved"]) for item in items)
                if all(item["total_bytes_moved"] is not None for item in items)
                else None
            ),
            "query_timeout_count": sum(item["outcome"] == "query_timeout" for item in items),
        }
        for query_id, items in grouped.items()
    }


def _family_global_choices(
    ledger: Mapping[str, Any],
    training: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    predictions = {str(item["query_id"]): item for item in ledger["crossfit_predictions"]}
    by_query_strategy: dict[tuple[str, str], list[float]] = {}
    for item in training:
        by_query_strategy.setdefault(
            (str(item["query_id"]), str(item["physical_strategy"])), []
        ).append(float(item["analysis_elapsed_ms"]))
    observed = {
        key: _median(values) for key, values in by_query_strategy.items()
    }
    result = {}
    for query_id in ledger["seen_family_query_ids"]:
        prediction = predictions[query_id]
        fold = prediction["evaluation_fold_id"]
        family = prediction["family_id"]
        candidates = {
            str(item["physical_strategy"])
            for item in prediction["strategy_predictions"]
        }
        training_query_ids = {
            str(item["query_id"])
            for item in ledger["crossfit_predictions"]
            if item["family_id"] == family
            and item.get("evaluation_fold_id") != fold
        }
        medians = {
            strategy: _median(
                [observed[(candidate, strategy)] for candidate in sorted(training_query_ids)]
            )
            for strategy in candidates
        }
        result[query_id] = min(medians, key=lambda strategy: (medians[strategy], strategy))
    return result


def _method_record(
    *,
    query_id: str,
    family_id: str,
    stratum: str,
    method_id: str,
    strategy: str,
    serving_cost: Mapping[str, Any],
    acquisition_cost: Mapping[str, Any] | None,
    observed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    latency_winner = _latency_winner(observed)
    bytes_complete = all(
        item["total_bytes_moved"] is not None for item in observed.values()
    )
    bytes_winner = (
        min(
            observed,
            key=lambda item: (
                observed[item]["total_bytes_moved"],
                observed[item]["latency_ms"],
                item,
            ),
        )
        if bytes_complete
        else None
    )
    acquisition_latency = (
        float(acquisition_cost["latency_ms"]) if acquisition_cost else 0.0
    )
    acquisition_bytes = (
        acquisition_cost["total_bytes_moved"] if acquisition_cost else 0.0
    )
    serving_bytes = serving_cost["total_bytes_moved"]
    return {
        "query_id": query_id,
        "family_id": family_id,
        "evaluation_stratum": stratum,
        "method_id": method_id,
        "selected_physical_strategy": strategy,
        "observed_latency_winner": latency_winner,
        "observed_bytes_winner": bytes_winner,
        "physical_winner_correct": strategy == latency_winner,
        "serving_latency_ms": float(serving_cost["latency_ms"]),
        "serving_bytes": serving_bytes,
        "acquisition_latency_ms": acquisition_latency,
        "acquisition_bytes": acquisition_bytes,
        "end_to_end_latency_ms": acquisition_latency
        + float(serving_cost["latency_ms"]),
        "end_to_end_bytes": (
            float(acquisition_bytes) + float(serving_bytes)
            if acquisition_bytes is not None and serving_bytes is not None
            else None
        ),
        "latency_regret_ms": float(observed[strategy]["latency_ms"])
        - float(observed[latency_winner]["latency_ms"]),
        "bytes_regret": (
            float(observed[strategy]["total_bytes_moved"])
            - float(observed[bytes_winner]["total_bytes_moved"])
            if bytes_winner is not None
            else None
        ),
    }


def analyze_finbench_confirmatory_measurement_ledger(
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute the frozen RQ-P1/P2/P3 analysis from a complete ledger."""

    frozen = _ledger(ledger)
    grouped = _group_measurements(frozen)
    shadow = _shadow_costs(grouped["postselection_shadow_evaluation"])
    serving = _serving_costs(grouped["paired_selected_serving"])
    profile = _profile_costs(grouped["current_query_profile_acquisition"])
    family = {str(item["query_id"]): item for item in frozen["family_selections"]}
    profile_selections = {
        str(item["query_id"]): item for item in frozen["profile_selections"]
    }
    predictions = {
        str(item["query_id"]): item for item in frozen["crossfit_predictions"]
    }
    global_choices = _family_global_choices(
        frozen, grouped["crossfit_training_measurement"]
    )
    method_records: list[dict[str, Any]] = []
    prediction_errors = []
    frontier_rows = []
    for query_id in frozen["seen_family_query_ids"]:
        family_id = str(family[query_id]["family_id"])
        costs = shadow[query_id]
        strategies = _STRATEGIES[family_id]
        if set(costs) != set(strategies):
            raise FinBenchConfirmatoryAnalysisError("family strategies changed")
        latency_winner = _latency_winner(costs)
        choices = {
            "family_memory_zero_profile": str(
                family[query_id]["selected_physical_strategy"]
            ),
            "current_query_dual_profile": str(
                profile_selections[query_id]["selected_physical_strategy"]
            ),
            "family_global_no_instance_features": global_choices[query_id],
            "fixed_route_a": strategies[0],
            "fixed_route_b": strategies[1],
            "observed_oracle_upper_bound": latency_winner,
        }
        for method_id, strategy in choices.items():
            selected = serving.get((query_id, method_id))
            selected_cost = selected if selected is not None else costs[strategy]
            method_records.append(
                _method_record(
                    query_id=query_id,
                    family_id=family_id,
                    stratum="crossfit_seen_family",
                    method_id=method_id,
                    strategy=strategy,
                    serving_cost=selected_cost,
                    acquisition_cost=(
                        profile[query_id]
                        if method_id == "current_query_dual_profile"
                        else None
                    ),
                    observed=costs,
                )
            )
        prediction = predictions[query_id]
        for estimate in prediction["strategy_predictions"]:
            strategy = str(estimate["physical_strategy"])
            prediction_errors.append(
                {
                    "query_id": query_id,
                    "physical_strategy": strategy,
                    "latency_error_ms": float(estimate["predicted_elapsed_ms"])
                    - float(costs[strategy]["latency_ms"]),
                    "bytes_error": (
                        float(estimate["predicted_total_bytes_moved"])
                        - float(costs[strategy]["total_bytes_moved"])
                        if costs[strategy]["total_bytes_moved"] is not None
                        else None
                    ),
                }
            )
        predicted = set(prediction["predicted_physical_frontier"])
        observed = _pareto(costs)
        frontier_rows.append(
            {
                "query_id": query_id,
                "predicted_frontier": sorted(predicted),
                "observed_frontier": observed,
                "jaccard": (
                    len(predicted & set(observed)) / len(predicted | set(observed))
                    if observed is not None and predicted | set(observed)
                    else None
                ),
            }
        )
    cold_records = []
    for query_id in frozen["cold_family_query_ids"]:
        costs = shadow[query_id]
        strategies = _STRATEGIES[_F3]
        if set(costs) != set(strategies):
            raise FinBenchConfirmatoryAnalysisError("cold-family strategies changed")
        latency_winner = _latency_winner(costs)
        choices = {
            "predeclared_family_fallback": str(
                family[query_id]["selected_physical_strategy"]
            ),
            "current_query_dual_profile": str(
                profile_selections[query_id]["selected_physical_strategy"]
            ),
            "fixed_route_a": strategies[0],
            "fixed_route_b": strategies[1],
            "observed_oracle_upper_bound": latency_winner,
        }
        for method_id, strategy in choices.items():
            selected = serving.get((query_id, method_id))
            selected_cost = selected if selected is not None else costs[strategy]
            cold_records.append(
                _method_record(
                    query_id=query_id,
                    family_id=_F3,
                    stratum="heldout_family_cold_start",
                    method_id=method_id,
                    strategy=strategy,
                    serving_cost=selected_cost,
                    acquisition_cost=(
                        profile[query_id]
                        if method_id == "current_query_dual_profile"
                        else None
                    ),
                    observed=costs,
                )
            )
    by_query_method = {
        (item["query_id"], item["method_id"]): item for item in method_records
    }
    primary_rows = []
    for query_id in frozen["seen_family_query_ids"]:
        memory = by_query_method[(query_id, "family_memory_zero_profile")]
        current = by_query_method[(query_id, "current_query_dual_profile")]
        ratio = memory["end_to_end_latency_ms"] / current["end_to_end_latency_ms"]
        primary_rows.append(
            {
                "query_id": query_id,
                "family_id": memory["family_id"],
                "family_memory_end_to_end_latency_ms": memory["end_to_end_latency_ms"],
                "current_query_profile_end_to_end_latency_ms": current[
                    "end_to_end_latency_ms"
                ],
                "ratio": ratio,
                "log_ratio": math.log(ratio),
                "difference_ms": memory["end_to_end_latency_ms"]
                - current["end_to_end_latency_ms"],
            }
        )
    ratio = math.exp(
        sum(item["log_ratio"] for item in primary_rows) / len(primary_rows)
    )
    difference = _median([item["difference_ms"] for item in primary_rows])
    primary = {
        "rq_id": "RQ-P1",
        "inferential_query_count": len(primary_rows),
        "repetition_count_as_independent_n": 0,
        "within_query_repetition_aggregation": "median",
        "geometric_mean_end_to_end_latency_ratio": ratio,
        "paired_median_difference_ms": difference,
        "confidence_interval": _bootstrap(primary_rows),
        "randomization_test": _sign_flip(
            [item["log_ratio"] for item in primary_rows]
        ),
        "per_query": primary_rows,
    }
    methods = sorted({item["method_id"] for item in method_records})
    method_metrics = {}
    for method_id in methods:
        rows = [item for item in method_records if item["method_id"] == method_id]
        byte_regrets = [
            float(item["bytes_regret"])
            for item in rows
            if item["bytes_regret"] is not None
        ]
        method_metrics[method_id] = {
            "query_count": len(rows),
            "physical_winner_accuracy": sum(
                item["physical_winner_correct"] for item in rows
            )
            / len(rows),
            "latency_regret_ms": _summary(
                [float(item["latency_regret_ms"]) for item in rows]
            ),
            "bytes_regret": {
                **_summary(byte_regrets),
                "missing_query_count": len(rows) - len(byte_regrets),
            },
            "serving_latency_ms": _summary(
                [float(item["serving_latency_ms"]) for item in rows]
            ),
            "end_to_end_latency_ms": _summary(
                [float(item["end_to_end_latency_ms"]) for item in rows]
            ),
        }
    secondary_tests = []
    for comparator in (
        "current_query_dual_profile",
        "family_global_no_instance_features",
        "fixed_route_a",
        "fixed_route_b",
    ):
        values = [
            by_query_method[(query_id, "family_memory_zero_profile")][
                "latency_regret_ms"
            ]
            - by_query_method[(query_id, comparator)]["latency_regret_ms"]
            for query_id in frozen["seen_family_query_ids"]
        ]
        test = _sign_flip(values, seed_suffix=f"secondary:{comparator}")
        secondary_tests.append(
            {
                "comparison_id": f"family_memory_vs_{comparator}",
                "metric": "query_level_latency_regret_difference_ms",
                "query_count": len(values),
                "p_value": test["p_value"],
                "test": test,
            }
        )
    latency_errors = [
        abs(float(item["latency_error_ms"])) for item in prediction_errors
    ]
    bytes_errors = [
        abs(float(item["bytes_error"]))
        for item in prediction_errors
        if item["bytes_error"] is not None
    ]
    jaccards = [
        float(item["jaccard"])
        for item in frontier_rows
        if item["jaccard"] is not None
    ]
    secondary = {
        "rq_id": "RQ-P2",
        "method_metrics": method_metrics,
        "method_records": method_records,
        "prediction_error": {
            "plan_count": len(prediction_errors),
            "latency_absolute_error_ms": _summary(latency_errors),
            "bytes_absolute_error": {
                **_summary(bytes_errors),
                "missing_plan_count": len(prediction_errors) - len(bytes_errors),
            },
            "records": prediction_errors,
        },
        "predicted_observed_frontier_overlap": {
            "query_count": len(frontier_rows),
            "available_query_count": len(jaccards),
            "missing_query_count": len(frontier_rows) - len(jaccards),
            "mean_jaccard": sum(jaccards) / len(jaccards) if jaccards else None,
            "per_query": frontier_rows,
        },
        "holm_adjusted_secondary_tests": _holm(secondary_tests),
    }
    cold_metrics = {}
    for method_id in sorted({item["method_id"] for item in cold_records}):
        rows = [item for item in cold_records if item["method_id"] == method_id]
        cold_metrics[method_id] = {
            "query_count": len(rows),
            "physical_winner_accuracy": sum(
                item["physical_winner_correct"] for item in rows
            )
            / len(rows),
            "latency_regret_ms": _summary(
                [float(item["latency_regret_ms"]) for item in rows]
            ),
            "end_to_end_latency_ms": _summary(
                [float(item["end_to_end_latency_ms"]) for item in rows]
            ),
        }
    training = grouped["crossfit_training_measurement"]
    training_bytes = [item["total_bytes_moved"] for item in training]
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_ANALYSIS_SCHEMA_VERSION,
        "ledger_sha256": frozen["ledger_sha256"],
        "primary": primary,
        "secondary": secondary,
        "cold_start": {
            "rq_id": "RQ-P3",
            "query_count": 16,
            "family_id": _F3,
            "family_memory_label_used": False,
            "inferential_test": None,
            "method_metrics": cold_metrics,
            "method_records": cold_records,
        },
        "offline_training_cost": {
            "plan_runs": len(training),
            "backend_calls": sum(item["total_remote_calls"] for item in training),
            "latency_ms": sum(item["analysis_elapsed_ms"] for item in training),
            "bytes": (
                sum(training_bytes) if all(item is not None for item in training_bytes) else None
            ),
            "excluded_from_primary_end_to_end_estimand": True,
            "amortized_latency_ms_per_primary_query": sum(
                item["analysis_elapsed_ms"] for item in training
            ) / 32,
        },
        "failure_accounting": {
            "query_timeout_count": frozen["query_timeout_count"],
            "query_timeouts_retained_as_method_outcomes": True,
            "infrastructure_replacement_count": frozen[
                "infrastructure_replacement_count"
            ],
            "automatic_retries": 0,
            "missing_measurements": "no_imputation",
        },
        "query_instance_is_inferential_unit": True,
        "repetitions_are_not_independent_units": True,
        "confirmatory_statistics": True,
        "independent_evidence_audit_required": True,
        "paper_result": False,
    }
    body["analysis_sha256"] = content_hash(body)
    return body
