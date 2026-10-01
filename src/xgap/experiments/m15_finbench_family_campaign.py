"""Freeze the leakage-safe FinBench family-memory comparison schedule.

The schedule is compiled only from the public workload and frozen policies. It
contains every training, current-query acquisition, paired serving, and shadow
slot before any native observation or answer oracle is available. Selected
serving slots deliberately carry method identities rather than physical plans;
those plans may be attached only after their respective selection seals exist.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_family_memory import (
    DEFAULT_POLICY_PATH,
    _policy,
    _public_contract,
)


FINBENCH_FAMILY_CAMPAIGN_PROTOCOL_SCHEMA_VERSION = (
    "m15-finbench-family-campaign-protocol-v1"
)
FINBENCH_FAMILY_CAMPAIGN_SCHEDULE_SCHEMA_VERSION = (
    "m15-finbench-family-campaign-schedule-v1"
)
DEFAULT_CAMPAIGN_PROTOCOL_PATH = Path(
    "experiments/configs/m15_finbench_family_campaign_dev_v1.json"
)
_PHASE_ORDER = (
    "training_measurement",
    "family_memory_freeze",
    "family_memory_prediction",
    "family_selection_seal",
    "current_query_profile_acquisition",
    "profile_selection_seal",
    "paired_selected_execution",
    "postselection_shadow_evaluation",
    "analysis",
)
_METHODS = (
    "family_memory_zero_profile",
    "predeclared_family_fallback",
    "family_global_no_instance_features",
    "fixed_route_a",
    "fixed_route_b",
    "current_query_dual_profile",
    "observed_oracle_upper_bound",
)
_METRICS = (
    "physical_winner_accuracy",
    "latency_regret_ms",
    "bytes_regret",
    "prediction_error",
    "predicted_observed_frontier_overlap",
    "selection_and_serving_end_to_end_cost",
)


class FinBenchFamilyCampaignError(ValueError):
    """Raised when the public population or frozen campaign drifts."""


@dataclass(frozen=True)
class FinBenchFamilyCampaignSchedule:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def schedule_hash(self) -> str:
        return str(self.payload["schedule_sha256"])


def _json_object(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise FinBenchFamilyCampaignError(
            "campaign protocol must be a regular non-symbolic-link file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchFamilyCampaignError(
            "campaign protocol is not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise FinBenchFamilyCampaignError("campaign protocol must be an object")
    return dict(payload)


def _validate_protocol(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    protocol = _json_object(value)
    if protocol.get("schema_version") != FINBENCH_FAMILY_CAMPAIGN_PROTOCOL_SCHEMA_VERSION:
        raise FinBenchFamilyCampaignError("campaign protocol schema changed")
    expected = {
        "schema_version",
        "protocol_id",
        "phase_order",
        "population",
        "training",
        "family_memory",
        "current_query_profile",
        "paired_selected_execution",
        "shadow",
        "analysis_methods",
        "analysis",
        "execution",
        "expected_counts",
        "claim_boundary",
        "paper_result",
    }
    if set(protocol) != expected:
        raise FinBenchFamilyCampaignError("campaign protocol fields changed")
    if (
        protocol["protocol_id"]
        != "m15-finbench-family-campaign-development-v1"
        or tuple(protocol["phase_order"]) != _PHASE_ORDER
        or protocol["population"]
        != {
            "query_count": 36,
            "training_query_count": 16,
            "heldout_instance_query_count": 8,
            "heldout_family_query_count": 12,
        }
        or protocol["training"]
        != {
            "strategies_per_query": 2,
            "repetitions_per_plan": 4,
            "query_order": "sha256_seeded_per_block",
            "strategy_order": "per_query_ab_ba_counterbalanced",
            "schedule_seed": "m15-finbench-family-campaign-training-v1",
        }
        or protocol["family_memory"]
        != {
            "known_family_method_id": "family_memory_zero_profile",
            "cold_start_method_id": "predeclared_family_fallback",
            "current_query_profile_calls": 0,
            "oracle_inputs": [],
            "post_execution_measurements_used": False,
            "selected_execution_repetitions": 1,
        }
        or protocol["current_query_profile"]
        != {
            "method_id": "current_query_dual_profile",
            "profiles_per_strategy": 1,
            "query_order": "sha256_seeded",
            "strategy_order": "balanced_across_queries",
            "schedule_seed": "m15-finbench-family-campaign-profile-v1",
            "selection_order": [
                "observed_elapsed_ms",
                "observed_total_bytes_moved",
                "physical_strategy",
            ],
            "selected_execution_repetitions": 1,
            "acquisition_cost_included": True,
        }
        or protocol["paired_selected_execution"]
        != {
            "method_order": "sha256_seeded_ab_ba_balanced",
            "schedule_seed": "m15-finbench-family-campaign-serving-v1",
            "selection_input": False,
            "memory_writes_allowed": False,
        }
        or protocol["shadow"]
        != {
            "strategies_per_query": 2,
            "repetitions_per_plan": 4,
            "starts_after_all_selection_seals": True,
            "query_order": "sha256_seeded_per_block",
            "strategy_order": "per_query_ab_ba_counterbalanced",
            "selection_input": False,
            "memory_writes_allowed": False,
            "schedule_seed": "m15-finbench-family-campaign-shadow-v1",
        }
        or tuple(protocol["analysis_methods"]) != _METHODS
        or protocol["analysis"]
        != {
            "known_family_and_cold_start_reported_separately": True,
            "per_plan_aggregation": "median_over_four_shadow_repetitions",
            "metrics": list(_METRICS),
            "confirmatory_statistics": False,
        }
        or protocol["execution"]
        != {
            "remote_calls_per_plan": 2,
            "backend_timeout_seconds": 60,
            "slurm_timeout_minutes": 90,
            "failure_policy": "stop_on_first_failure",
            "automatic_retries": 0,
            "single_allocation": True,
        }
        or protocol["expected_counts"]
        != {
            "training_plan_runs": 128,
            "profile_acquisition_plan_runs": 40,
            "paired_selected_plan_runs": 40,
            "evaluation_shadow_plan_runs": 160,
            "total_plan_runs": 368,
            "total_backend_calls": 736,
        }
        or protocol["claim_boundary"]
        != {
            "development_campaign_only": True,
            "benchmark_conformance_claim": False,
            "paper_result": False,
        }
        or protocol["paper_result"] is not False
    ):
        raise FinBenchFamilyCampaignError("campaign protocol changed")
    return protocol


def _hash_order(query_ids: Sequence[str], *, seed: str, block: int) -> list[str]:
    return sorted(
        query_ids,
        key=lambda query_id: (
            content_hash(
                {"schedule_seed": seed, "block": block, "query_id": query_id}
            ),
            query_id,
        ),
    )


def _physical_runs(
    *,
    phase: str,
    query_ids: Sequence[str],
    instances: Mapping[str, Mapping[str, Any]],
    families: Mapping[str, Mapping[str, Any]],
    repetitions: int,
    seed: str,
    selection_input: bool,
    current_query_profile: bool,
    memory_write_allowed: bool,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for block in range(1, repetitions + 1):
        for query_id in _hash_order(query_ids, seed=seed, block=block):
            instance = instances[query_id]
            family_id = str(instance["family_id"])
            strategies = list(families[family_id]["physical_strategies"])
            ordered = strategies if block % 2 else list(reversed(strategies))
            for position, strategy in enumerate(ordered, start=1):
                item: dict[str, Any] = {
                    "phase": phase,
                    "query_id": query_id,
                    "family_id": family_id,
                    "split_role": instance["split_role"],
                    "physical_strategy": strategy,
                    "block_index": block,
                    "order_position": position,
                    "selection_input": selection_input,
                    "current_query_profile": current_query_profile,
                    "memory_write_allowed": memory_write_allowed,
                }
                item["run_id"] = "finbench-run-" + content_hash(item)[:24]
                runs.append(item)
    return runs


def _paired_serving_slots(
    *,
    query_ids: Sequence[str],
    instances: Mapping[str, Mapping[str, Any]],
    seed: str,
) -> list[dict[str, Any]]:
    ordered_queries = _hash_order(query_ids, seed=seed, block=1)
    slots: list[dict[str, Any]] = []
    for query_position, query_id in enumerate(ordered_queries, start=1):
        instance = instances[query_id]
        primary_method = (
            "family_memory_zero_profile"
            if instance["split_role"] == "heldout_instance"
            else "predeclared_family_fallback"
        )
        methods = (primary_method, "current_query_dual_profile")
        ordered_methods = methods if query_position % 2 else tuple(reversed(methods))
        for order_position, method_id in enumerate(ordered_methods, start=1):
            plan_binding = (
                "profile_selection_seal"
                if method_id == "current_query_dual_profile"
                else "family_selection_seal"
            )
            item: dict[str, Any] = {
                "phase": "paired_selected_execution",
                "query_id": query_id,
                "family_id": instance["family_id"],
                "split_role": instance["split_role"],
                "method_id": method_id,
                "plan_binding": plan_binding,
                "query_position": query_position,
                "order_position": order_position,
                "selection_input": False,
                "current_query_profile": False,
                "memory_write_allowed": False,
            }
            item["slot_id"] = "finbench-slot-" + content_hash(item)[:24]
            slots.append(item)
    return slots


def _balanced_profile_acquisition_runs(
    *,
    query_ids: Sequence[str],
    instances: Mapping[str, Mapping[str, Any]],
    families: Mapping[str, Mapping[str, Any]],
    seed: str,
) -> list[dict[str, Any]]:
    ordered_queries = _hash_order(query_ids, seed=seed, block=1)
    runs: list[dict[str, Any]] = []
    for query_position, query_id in enumerate(ordered_queries, start=1):
        instance = instances[query_id]
        family_id = str(instance["family_id"])
        strategies = list(families[family_id]["physical_strategies"])
        ordered = strategies if query_position % 2 else list(reversed(strategies))
        for order_position, strategy in enumerate(ordered, start=1):
            item: dict[str, Any] = {
                "phase": "current_query_profile_acquisition",
                "query_id": query_id,
                "family_id": family_id,
                "split_role": instance["split_role"],
                "physical_strategy": strategy,
                "block_index": 1,
                "query_position": query_position,
                "order_position": order_position,
                "selection_input": True,
                "current_query_profile": True,
                "memory_write_allowed": False,
            }
            item["run_id"] = "finbench-run-" + content_hash(item)[:24]
            runs.append(item)
    return runs


def build_finbench_family_campaign_schedule(
    *,
    workload_root: str | Path,
    protocol: Mapping[str, Any] | str | Path = DEFAULT_CAMPAIGN_PROTOCOL_PATH,
    family_memory_policy: Mapping[str, Any] | str | Path = DEFAULT_POLICY_PATH,
) -> FinBenchFamilyCampaignSchedule:
    """Compile all result-blind campaign runs and selected-plan slots."""

    selected_protocol = _validate_protocol(protocol)
    selected_memory_policy = _policy(family_memory_policy)
    contract = _public_contract(workload_root)
    instances = contract["instances"]
    families = contract["families"]
    training_ids = sorted(
        query_id
        for query_id, item in instances.items()
        if item["split_role"] == "training"
    )
    heldout_ids = sorted(
        query_id
        for query_id, item in instances.items()
        if item["split_role"] in {"heldout_instance", "heldout_family"}
    )
    known_ids = sorted(
        query_id
        for query_id in heldout_ids
        if instances[query_id]["split_role"] == "heldout_instance"
    )
    cold_ids = sorted(set(heldout_ids) - set(known_ids))
    if (len(training_ids), len(known_ids), len(cold_ids)) != (16, 8, 12):
        raise FinBenchFamilyCampaignError("FinBench campaign split changed")

    training_runs = _physical_runs(
        phase="training_measurement",
        query_ids=training_ids,
        instances=instances,
        families=families,
        repetitions=4,
        seed=selected_protocol["training"]["schedule_seed"],
        selection_input=True,
        current_query_profile=False,
        memory_write_allowed=True,
    )
    acquisition_runs = _balanced_profile_acquisition_runs(
        query_ids=heldout_ids,
        instances=instances,
        families=families,
        seed=selected_protocol["current_query_profile"]["schedule_seed"],
    )
    serving_slots = _paired_serving_slots(
        query_ids=heldout_ids,
        instances=instances,
        seed=selected_protocol["paired_selected_execution"]["schedule_seed"],
    )
    shadow_runs = _physical_runs(
        phase="postselection_shadow_evaluation",
        query_ids=heldout_ids,
        instances=instances,
        families=families,
        repetitions=4,
        seed=selected_protocol["shadow"]["schedule_seed"],
        selection_input=False,
        current_query_profile=False,
        memory_write_allowed=False,
    )
    fixed_runs = [*training_runs, *acquisition_runs, *shadow_runs]
    if len({item["run_id"] for item in fixed_runs}) != len(fixed_runs):
        raise FinBenchFamilyCampaignError("campaign run IDs are not unique")
    if len({item["slot_id"] for item in serving_slots}) != len(serving_slots):
        raise FinBenchFamilyCampaignError("campaign serving slot IDs are not unique")
    counts = {
        "training_plan_runs": len(training_runs),
        "profile_acquisition_plan_runs": len(acquisition_runs),
        "paired_selected_plan_runs": len(serving_slots),
        "evaluation_shadow_plan_runs": len(shadow_runs),
        "total_plan_runs": len(fixed_runs) + len(serving_slots),
        "total_backend_calls": 2 * (len(fixed_runs) + len(serving_slots)),
    }
    if counts != selected_protocol["expected_counts"]:
        raise FinBenchFamilyCampaignError("campaign schedule counts changed")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_FAMILY_CAMPAIGN_SCHEDULE_SCHEMA_VERSION,
        "protocol_sha256": content_hash(selected_protocol),
        "family_memory_policy_sha256": content_hash(selected_memory_policy),
        "workload_sha256": contract["manifest"]["workload_sha256"],
        "public_instances_sha256": contract["manifest"]["output_files"]
        ["public_instances.json"]["sha256"],
        "family_contracts_sha256": contract["manifest"]["output_files"]
        ["family_contracts.json"]["sha256"],
        "phase_order": list(_PHASE_ORDER),
        "training_query_ids": training_ids,
        "heldout_instance_query_ids": known_ids,
        "heldout_family_query_ids": cold_ids,
        "training_runs": training_runs,
        "profile_acquisition_runs": acquisition_runs,
        "paired_selected_execution_slots": serving_slots,
        "evaluation_shadow_runs": shadow_runs,
        "expected_counts": counts,
        "family_selection_current_query_profile_calls": 0,
        "answer_oracle_opened": False,
        "backend_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["schedule_sha256"] = content_hash(body)
    return FinBenchFamilyCampaignSchedule(body)
