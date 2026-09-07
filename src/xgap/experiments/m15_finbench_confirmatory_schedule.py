"""Freeze the author-approved FinBench confirmatory measurement schedule.

The schedule is compiled from the public workload, the result-blind protocol,
and the author's hash-bound option selection.  It contains every training,
profile-acquisition, selected-serving, and shadow slot before any measurement
or answer oracle is opened.  Selected-serving slots name methods, not physical
plans; physical strategies are attached only after their selection seals.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_confirmatory_crossfit import _contract
from xgap.experiments.m15_finbench_paper_protocol import (
    DEFAULT_AUTHOR_SELECTION_PATH,
    DEFAULT_PROTOCOL_PATH,
    FinBenchPaperProtocolError,
    _approval_subject,
    _decisions,
    _load_json_object,
    _validate_scientific_contract,
    apply_finbench_paper_protocol_author_selection,
)


FINBENCH_CONFIRMATORY_SCHEDULE_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-measurement-schedule-v1"
)
_F1 = "f1_direct_transfer_control"
_F2 = "f2_temporal_path_control"
_F3 = "f3_aggregate_risk_ranking"
_SEEN = (_F1, _F2)
_FAMILIES = (_F1, _F2, _F3)
_PHASE_ORDER = (
    "crossfit_training_measurement",
    "crossfit_memory_freeze",
    "crossfit_prediction",
    "family_selection_seal",
    "current_query_profile_acquisition",
    "profile_selection_seal",
    "paired_selected_serving",
    "postselection_shadow_evaluation",
    "oracle_open",
    "confirmatory_analysis",
)
_METHODS = (
    "family_memory_zero_profile",
    "predeclared_family_fallback",
    "current_query_dual_profile",
)
_SEEDS = {
    "training": "m15-sigmod2027-finbench-confirmatory-training-v1",
    "profile": "m15-sigmod2027-finbench-confirmatory-profile-v1",
    "serving": "m15-sigmod2027-finbench-confirmatory-serving-v1",
    "shadow": "m15-sigmod2027-finbench-confirmatory-shadow-v1",
}


class FinBenchConfirmatoryScheduleError(ValueError):
    """Raised when an approved protocol or frozen schedule boundary drifts."""


@dataclass(frozen=True)
class FinBenchConfirmatorySchedule:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))

    @property
    def schedule_hash(self) -> str:
        return str(self.payload["schedule_sha256"])


def _order_key(seed: str, block: int, identity: str) -> str:
    return hashlib.sha256(
        f"{seed}\x00{block}\x00{identity}".encode("utf-8")
    ).hexdigest()


def _query_order(query_ids: Sequence[str], *, seed: str, block: int) -> list[str]:
    return sorted(query_ids, key=lambda item: (_order_key(seed, block, item), item))


def _ab_order(values: Sequence[str], *, seed: str, block: int, query_id: str) -> list[str]:
    if len(values) != 2:
        raise FinBenchConfirmatoryScheduleError("counterbalance requires two values")
    ordered = list(values)
    parity = int(_order_key(seed, block, query_id)[-1], 16) + block
    return ordered if parity % 2 == 0 else list(reversed(ordered))


def _approved_protocol(
    protocol: Mapping[str, Any] | str | Path,
    author_selection: Mapping[str, Any] | str | Path,
) -> tuple[dict[str, Any], dict[str, str], str]:
    try:
        approved = apply_finbench_paper_protocol_author_selection(
            protocol, author_selection
        )
        _validate_scientific_contract(approved)
        decisions, physical_blockers, paper_blockers = _decisions(approved)
    except FinBenchPaperProtocolError as exc:
        raise FinBenchConfirmatoryScheduleError(str(exc)) from exc
    if physical_blockers or paper_blockers:
        raise FinBenchConfirmatoryScheduleError(
            "confirmatory schedule requires every author decision"
        )
    approval = approved.get("approval")
    if (
        not isinstance(approval, Mapping)
        or approval.get("status") != "approved"
        or approval.get("approved_subject_sha256")
        != content_hash(_approval_subject(approved))
    ):
        raise FinBenchConfirmatoryScheduleError("author approval is not bound")
    selection = (
        copy.deepcopy(dict(author_selection))
        if isinstance(author_selection, Mapping)
        else _load_json_object(Path(author_selection), name="author selection")
    )
    selection_sha256 = selection.get("selection_sha256")
    if not isinstance(selection_sha256, str):
        raise FinBenchConfirmatoryScheduleError("author selection hash is missing")
    return approved, {
        str(item["decision_id"]): str(item["selected_value"])
        for item in decisions
    }, selection_sha256


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
        block_id = f"{phase}-block-{block:02d}"
        for query_position, query_id in enumerate(
            _query_order(query_ids, seed=seed, block=block), start=1
        ):
            instance = instances[query_id]
            strategies = families[str(instance["family_id"])]["physical_strategies"]
            for order_position, strategy in enumerate(
                _ab_order(strategies, seed=seed, block=block, query_id=query_id),
                start=1,
            ):
                identity = {
                    "phase": phase,
                    "measurement_block_id": block_id,
                    "block_index": block,
                    "query_id": query_id,
                    "family_id": instance["family_id"],
                    "evaluation_fold_id": instance.get("evaluation_fold_id"),
                    "evaluation_stratum": instance["split_role"],
                    "physical_strategy": strategy,
                    "query_position": query_position,
                    "order_position": order_position,
                    "selection_input": selection_input,
                    "current_query_profile": current_query_profile,
                    "memory_write_allowed": memory_write_allowed,
                    "oracle_inputs": [],
                }
                identity["run_id"] = "finbench-confirmatory-run-" + content_hash(
                    identity
                )[:24]
                runs.append(identity)
    return runs


def _serving_slots(
    *,
    query_ids: Sequence[str],
    instances: Mapping[str, Mapping[str, Any]],
    repetitions: int,
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for block in range(1, repetitions + 1):
        phase = "paired_selected_serving"
        block_id = f"{phase}-block-{block:02d}"
        for query_position, query_id in enumerate(
            _query_order(query_ids, seed=_SEEDS["serving"], block=block), start=1
        ):
            instance = instances[query_id]
            family_method = (
                "predeclared_family_fallback"
                if instance["family_id"] == _F3
                else "family_memory_zero_profile"
            )
            for order_position, method_id in enumerate(
                _ab_order(
                    (family_method, "current_query_dual_profile"),
                    seed=_SEEDS["serving"],
                    block=block,
                    query_id=query_id,
                ),
                start=1,
            ):
                identity = {
                    "phase": phase,
                    "measurement_block_id": block_id,
                    "block_index": block,
                    "query_id": query_id,
                    "family_id": instance["family_id"],
                    "evaluation_fold_id": instance.get("evaluation_fold_id"),
                    "evaluation_stratum": instance["split_role"],
                    "method_id": method_id,
                    "physical_strategy": None,
                    "query_position": query_position,
                    "order_position": order_position,
                    "selection_input": False,
                    "current_query_profile": False,
                    "memory_write_allowed": False,
                    "oracle_inputs": [],
                }
                identity["slot_id"] = "finbench-confirmatory-slot-" + content_hash(
                    identity
                )[:24]
                slots.append(identity)
    return slots


def build_finbench_confirmatory_schedule(
    *,
    workload_root: str | Path,
    protocol: Mapping[str, Any] | str | Path = DEFAULT_PROTOCOL_PATH,
    author_selection: Mapping[str, Any] | str | Path = DEFAULT_AUTHOR_SELECTION_PATH,
) -> FinBenchConfirmatorySchedule:
    """Compile the complete 48-query Option-A schedule without measurements."""

    approved, decisions, author_selection_sha256 = _approved_protocol(
        protocol, author_selection
    )
    expected = {
        "confirmatory_population": "48_answer_independent_crossfit",
        "primary_scale": "sf0_1",
        "robustness_scale": "sf1_if_feasible_by_2026-09-12_else_omit",
        "training_repetitions_per_plan": "7",
        "selected_serving_repetitions": "7",
        "shadow_repetitions_per_plan": "7",
        "infrastructure_replacement_limit": "1",
        "semantic_track": "grailqa_primary",
        "external_validation": "fedshop_if_ready_by_2026-09-24_else_omit",
    }
    if decisions != expected:
        raise FinBenchConfirmatoryScheduleError("Option-A decision bundle changed")
    contract = _contract(workload_root)
    instances = contract["instances"]
    families = contract["families"]
    if len(instances) != 48 or contract["per_family"] != {
        family_id: 16 for family_id in _FAMILIES
    }:
        raise FinBenchConfirmatoryScheduleError("Option-A population is not 48")
    query_ids = sorted(instances)
    seen_ids = sorted(
        query_id
        for query_id, item in instances.items()
        if item["family_id"] in _SEEN
    )
    cold_ids = sorted(set(query_ids) - set(seen_ids))
    training_runs = _physical_runs(
        phase="crossfit_training_measurement",
        query_ids=seen_ids,
        instances=instances,
        families=families,
        repetitions=7,
        seed=_SEEDS["training"],
        selection_input=True,
        current_query_profile=False,
        memory_write_allowed=True,
    )
    profile_runs = _physical_runs(
        phase="current_query_profile_acquisition",
        query_ids=query_ids,
        instances=instances,
        families=families,
        repetitions=1,
        seed=_SEEDS["profile"],
        selection_input=True,
        current_query_profile=True,
        memory_write_allowed=False,
    )
    serving_slots = _serving_slots(
        query_ids=query_ids,
        instances=instances,
        repetitions=7,
    )
    shadow_runs = _physical_runs(
        phase="postselection_shadow_evaluation",
        query_ids=query_ids,
        instances=instances,
        families=families,
        repetitions=7,
        seed=_SEEDS["shadow"],
        selection_input=False,
        current_query_profile=False,
        memory_write_allowed=False,
    )
    fixed_ids = [
        str(item["run_id"])
        for item in (*training_runs, *profile_runs, *shadow_runs)
    ]
    slot_ids = [str(item["slot_id"]) for item in serving_slots]
    if len(fixed_ids) != len(set(fixed_ids)) or len(slot_ids) != len(set(slot_ids)):
        raise FinBenchConfirmatoryScheduleError("schedule identities are not unique")
    counts = {
        "seen_family_query_count": len(seen_ids),
        "cold_family_query_count": len(cold_ids),
        "inferential_query_count": len(seen_ids),
        "training_plan_runs": len(training_runs),
        "profile_acquisition_plan_runs": len(profile_runs),
        "selected_serving_plan_runs": len(serving_slots),
        "evaluation_shadow_plan_runs": len(shadow_runs),
        "total_plan_runs": (
            len(training_runs)
            + len(profile_runs)
            + len(serving_slots)
            + len(shadow_runs)
        ),
    }
    counts["total_backend_calls"] = counts["total_plan_runs"] * 2
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
    if counts != expected_counts:
        raise FinBenchConfirmatoryScheduleError("Option-A schedule counts changed")
    block_ids = [
        str(item["measurement_block_id"])
        for item in (*training_runs, *profile_runs, *serving_slots, *shadow_runs)
    ]
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_SCHEDULE_SCHEMA_VERSION,
        "protocol_subject_sha256": content_hash(_approval_subject(approved)),
        "author_selection_sha256": author_selection_sha256,
        "workload_sha256": contract["manifest"]["workload_sha256"],
        "population_approval_sha256": contract["manifest"][
            "population_approval_sha256"
        ],
        "population_id": contract["manifest"]["population_id"],
        "phase_order": list(_PHASE_ORDER),
        "query_ids": query_ids,
        "seen_family_query_ids": seen_ids,
        "cold_family_query_ids": cold_ids,
        "crossfit_training_runs": training_runs,
        "profile_acquisition_runs": profile_runs,
        "selected_serving_slots": serving_slots,
        "evaluation_shadow_runs": shadow_runs,
        "measurement_block_ids": sorted(set(block_ids)),
        "measurement_block_count": len(set(block_ids)),
        "expected_counts": counts,
        "execution_contract": {
            "backend_boundary": "black_box_public_interfaces_only",
            "remote_calls_per_complete_plan": 2,
            "fresh_job_owned_services_per_measurement_block": True,
            "backend_timeout_seconds": 60,
            "automatic_retries": 0,
            "infrastructure_replacement_limit": 1,
            "query_timeout_is_method_outcome": True,
            "query_timeout_is_not_replacement_eligible": True,
            "replacement_reuses_frozen_schedule": True,
        },
        "seal_contract": {
            "candidate_catalog_before_first_backend_call": True,
            "crossfit_prediction_before_profile_acquisition": True,
            "family_selection_before_profile_acquisition": True,
            "profile_selection_before_selected_serving": True,
            "all_selection_seals_before_shadow": True,
            "oracle_opened_after_all_plan_runs": True,
        },
        "query_instance_is_inferential_unit": True,
        "repetitions_are_not_independent_units": True,
        "current_query_profile_calls_for_family_memory": 0,
        "oracle_inputs": [],
        "confirmatory_execution_authorized": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["schedule_sha256"] = content_hash(body)
    return FinBenchConfirmatorySchedule(body)


def write_finbench_confirmatory_schedule(
    schedule: FinBenchConfirmatorySchedule, output: str | Path
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"confirmatory schedule output exists: {destination}")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            schedule.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-root", required=True)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL_PATH))
    parser.add_argument(
        "--author-selection", default=str(DEFAULT_AUTHOR_SELECTION_PATH)
    )
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        schedule = build_finbench_confirmatory_schedule(
            workload_root=arguments.workload_root,
            protocol=arguments.protocol,
            author_selection=arguments.author_selection,
        )
        write_finbench_confirmatory_schedule(schedule, arguments.output)
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error": str(exc)}))
        return 2
    print(json.dumps({"status": "success", **schedule.to_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
