"""Compile answer-independent FinBench confirmatory population options.

The compiler reads only source-side identifiers, graph structure, timestamps,
and the declared risk-level parameter domain. It never inspects blocked flags,
answer rows, plan measurements, or profiles. All author-selectable population
sizes are compiled together so choosing a size later cannot depend on results.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_artifacts import (
    DEFAULT_LOCK_PATH,
    load_finbench_artifact_lock,
)
from xgap.experiments.m15_finbench_workload import (
    FinBenchQueryData,
    load_finbench_query_data,
)


FINBENCH_CONFIRMATORY_POPULATION_DESIGN_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-population-design-v1"
)
FINBENCH_CONFIRMATORY_POPULATION_REGISTRY_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-population-registry-v1"
)
DEFAULT_DESIGN_PATH = Path(
    "experiments/configs/m15_finbench_confirmatory_population_design_v1.json"
)
_FAMILY_IDS = (
    "f1_direct_transfer_control",
    "f2_temporal_path_control",
    "f3_aggregate_risk_ranking",
)
_SEEN_FAMILIES = frozenset(_FAMILY_IDS[:2])
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_ALLOWED_FIELDS = (
    "person.personId",
    "account.accountId",
    "person_own_account.personId",
    "person_own_account.accountId",
    "company_own_account.accountId",
    "account_transfer_account.fromId",
    "account_transfer_account.toId",
    "account_transfer_account.createTime",
    "medium.riskLevel",
)
_EXPECTED_FORBIDDEN_FIELDS = (
    "account.isBlocked",
    "medium.isBlocked",
    "sealed_oracles",
    "answer_rows",
    "elapsed_ms",
    "total_bytes_moved",
    "observed_winner",
    "profile_result",
)


class FinBenchConfirmatoryPopulationError(ValueError):
    """Raised when a population option or its result-blind boundary drifts."""


@dataclass(frozen=True)
class FinBenchConfirmatoryPopulationRegistry:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def _json_object(
    value: Mapping[str, Any] | str | Path, *, name: str
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise FinBenchConfirmatoryPopulationError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchConfirmatoryPopulationError(
            f"{name} is not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise FinBenchConfirmatoryPopulationError(f"{name} must be an object")
    return dict(payload)


def _validate_design(
    value: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    design = _json_object(value, name="confirmatory population design")
    expected_fields = {
        "schema_version",
        "design_id",
        "candidate_total_sizes",
        "family_ids",
        "equal_family_allocation",
        "strata_per_family",
        "crossfit_fold_count",
        "sampling_seed",
        "selection_rule",
        "nested_size_options",
        "f1_eligibility",
        "f1_stratification_feature",
        "f2_eligibility",
        "f2_stratification_feature",
        "f3_suffix_window_count",
        "f3_parameter_domain",
        "seen_family_ids",
        "cold_family_ids",
        "source_fields_allowed_for_sampling",
        "fields_forbidden_for_sampling",
        "query_instance_is_inferential_unit",
        "repetitions_are_not_independent_units",
        "selection_uses_answer_content",
        "selection_uses_observed_execution_cost",
        "current_query_profile_calls",
        "backend_calls",
        "llm_calls",
        "ontology_service_calls",
        "automatic_retries",
        "paper_result",
    }
    if set(design) != expected_fields:
        raise FinBenchConfirmatoryPopulationError("population design fields changed")
    if (
        design["schema_version"]
        != FINBENCH_CONFIRMATORY_POPULATION_DESIGN_SCHEMA_VERSION
        or design["design_id"]
        != "m15-finbench-answer-independent-crossfit-options-v1"
        or design["candidate_total_sizes"] != [36, 48, 60]
        or design["family_ids"] != list(_FAMILY_IDS)
        or design["equal_family_allocation"] is not True
        or design["strata_per_family"] != 4
        or design["crossfit_fold_count"] != 4
        or design["sampling_seed"]
        != "m15-sigmod2027-finbench-population-v1"
        or design["selection_rule"]
        != "within_public_structural_stratum_sha256_rank_without_replacement"
        or design["nested_size_options"] is not True
        or design["f1_eligibility"]
        != "person_with_at_least_one_transfer_from_person_owned_account_to_company_owned_account"
        or design["f1_stratification_feature"] != "structural_degree"
        or design["f2_eligibility"]
        != "account_with_out_degree_between_2_and_32_inclusive"
        or design["f2_stratification_feature"] != "out_degree"
        or design["f3_suffix_window_count"] != 10
        or design["f3_parameter_domain"]
        != "cartesian_product_of_source_risk_levels_and_predeclared_suffix_windows"
        or design["seen_family_ids"] != list(_FAMILY_IDS[:2])
        or design["cold_family_ids"] != [_FAMILY_IDS[2]]
        or tuple(design["source_fields_allowed_for_sampling"])
        != _EXPECTED_ALLOWED_FIELDS
        or tuple(design["fields_forbidden_for_sampling"])
        != _EXPECTED_FORBIDDEN_FIELDS
    ):
        raise FinBenchConfirmatoryPopulationError(
            "population design identity changed"
        )
    for field in (
        "query_instance_is_inferential_unit",
        "repetitions_are_not_independent_units",
    ):
        if design[field] is not True:
            raise FinBenchConfirmatoryPopulationError(
                "population inference boundary changed"
            )
    for field in (
        "selection_uses_answer_content",
        "selection_uses_observed_execution_cost",
    ):
        if design[field] is not False:
            raise FinBenchConfirmatoryPopulationError(
                "population leakage boundary changed"
            )
    if any(
        design[field] != 0
        for field in (
            "current_query_profile_calls",
            "backend_calls",
            "llm_calls",
            "ontology_service_calls",
            "automatic_retries",
        )
    ) or design["paper_result"] is not False:
        raise FinBenchConfirmatoryPopulationError(
            "population compiler must remain zero-call and non-result"
        )
    return design


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise FinBenchConfirmatoryPopulationError(
            f"{name} must be a safe identifier"
        )
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise FinBenchConfirmatoryPopulationError(
            f"{name} must be a lowercase SHA-256"
        )
    return value


def _sampling_score(seed: str, family_id: str, candidate_id: str) -> str:
    return hashlib.sha256(
        f"{seed}\x00{family_id}\x00{candidate_id}".encode("utf-8")
    ).hexdigest()


def _format_time(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds")


def _suffix_windows(
    minimum: str, maximum: str, *, count: int
) -> tuple[tuple[str, str], ...]:
    start = datetime.fromisoformat(minimum)
    finish = datetime.fromisoformat(maximum) + timedelta(milliseconds=1)
    if finish <= start:
        raise FinBenchConfirmatoryPopulationError("transfer time domain is invalid")
    span = finish - start
    return tuple(
        (_format_time(start + span * index / count), _format_time(finish))
        for index in range(count)
    )


def _candidate_frames(
    data: FinBenchQueryData, *, window_count: int
) -> dict[str, list[dict[str, Any]]]:
    f1_degree: dict[str, int] = {}
    for transfer in data.transfers:
        person_id = data.person_by_account.get(transfer.from_id)
        if person_id is None or transfer.to_id not in data.company_by_account:
            continue
        f1_degree[person_id] = f1_degree.get(person_id, 0) + 1
    f1 = [
        {
            "candidate_id": person_id,
            "parameters": {
                "person_id": person_id,
                "start_time": data.minimum_transfer_time,
                "end_time": data.maximum_transfer_time,
            },
            "selection_feature": {"structural_degree": degree},
        }
        for person_id, degree in sorted(f1_degree.items())
    ]

    f2 = [
        {
            "candidate_id": account_id,
            "parameters": {
                "start_account_id": account_id,
                "start_time": data.minimum_transfer_time,
                "end_time": data.maximum_transfer_time,
                "max_hops": 3,
            },
            "selection_feature": {"out_degree": len(outgoing)},
        }
        for account_id, outgoing in sorted(data.outgoing.items())
        if 2 <= len(outgoing) <= 32
    ]

    risk_levels = sorted(
        {
            str(row.get("riskLevel", "")).strip()
            for row in data.media.values()
            if str(row.get("riskLevel", "")).strip()
        }
    )
    if not risk_levels:
        raise FinBenchConfirmatoryPopulationError(
            "source risk-level parameter domain is empty"
        )
    windows = _suffix_windows(
        data.minimum_transfer_time,
        data.maximum_transfer_time,
        count=window_count,
    )
    f3: list[dict[str, Any]] = []
    for window_position, (start_time, end_time) in enumerate(windows, start=1):
        for risk_position, risk_level in enumerate(risk_levels, start=1):
            f3.append(
                {
                    "candidate_id": f"w{window_position}:r{risk_position}",
                    "parameters": {
                        "start_time": start_time,
                        "end_time": end_time,
                        "risk_level": risk_level,
                        "top_k": 10,
                    },
                    "selection_feature": {
                        "window_position": window_position,
                        "risk_position": risk_position,
                    },
                }
            )
    return {_FAMILY_IDS[0]: f1, _FAMILY_IDS[1]: f2, _FAMILY_IDS[2]: f3}


def _stratify(
    family_id: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    strata: int,
) -> list[dict[str, Any]]:
    if family_id == _FAMILY_IDS[0]:
        feature = "structural_degree"
    elif family_id == _FAMILY_IDS[1]:
        feature = "out_degree"
    else:
        feature = "window_position"
    ordered = sorted(
        (copy.deepcopy(dict(item)) for item in candidates),
        key=lambda item: (
            item["selection_feature"][feature],
            item["candidate_id"],
        ),
    )
    if not ordered:
        raise FinBenchConfirmatoryPopulationError(
            f"sampling frame is empty for {family_id}"
        )
    for index, item in enumerate(ordered):
        item["stratum"] = min(index * strata // len(ordered), strata - 1) + 1
    return ordered


def _select_family(
    family_id: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    count: int,
    strata: int,
    seed: str,
) -> list[dict[str, Any]]:
    if count % strata:
        raise FinBenchConfirmatoryPopulationError(
            "family allocation must divide evenly across strata"
        )
    per_stratum = count // strata
    selected: list[dict[str, Any]] = []
    stratified = _stratify(family_id, candidates, strata=strata)
    for stratum in range(1, strata + 1):
        eligible = [item for item in stratified if item["stratum"] == stratum]
        ranked = sorted(
            eligible,
            key=lambda item: (
                _sampling_score(seed, family_id, item["candidate_id"]),
                item["candidate_id"],
            ),
        )
        if len(ranked) < per_stratum:
            raise FinBenchConfirmatoryPopulationError(
                f"{family_id} stratum {stratum} needs {per_stratum} "
                f"candidates, found {len(ranked)}"
            )
        for rank, item in enumerate(ranked[:per_stratum], start=1):
            item["sampling_score"] = _sampling_score(
                seed, family_id, item["candidate_id"]
            )
            item["sampling_rank_within_stratum"] = rank
            selected.append(item)
    return sorted(
        selected,
        key=lambda item: (
            item["stratum"],
            item["sampling_score"],
            item["candidate_id"],
        ),
    )


def _population_option(
    frame: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    total_size: int,
    strata: int,
    folds: int,
    seed: str,
) -> dict[str, Any]:
    if total_size % len(_FAMILY_IDS):
        raise FinBenchConfirmatoryPopulationError(
            "population size must divide equally across families"
        )
    per_family = total_size // len(_FAMILY_IDS)
    if per_family % folds:
        raise FinBenchConfirmatoryPopulationError(
            "seen-family size must divide evenly across cross-fit folds"
        )
    instances: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    for family_position, family_id in enumerate(_FAMILY_IDS, start=1):
        chosen = _select_family(
            family_id,
            frame[family_id],
            count=per_family,
            strata=strata,
            seed=seed,
        )
        family_counts[family_id] = len(chosen)
        for selection_position, candidate in enumerate(chosen, start=1):
            query_id = (
                f"m15-fb-confirmatory-{total_size}-"
                f"f{family_position}-{selection_position:02d}"
            )
            item = {
                "query_id": query_id,
                "family_id": family_id,
                "candidate_id": candidate["candidate_id"],
                "selection_position": selection_position,
                "stratum": candidate["stratum"],
                "sampling_score": candidate["sampling_score"],
                "sampling_rank_within_stratum": candidate[
                    "sampling_rank_within_stratum"
                ],
                "selection_feature": candidate["selection_feature"],
                "parameters": candidate["parameters"],
            }
            if family_id in _SEEN_FAMILIES:
                evaluation_fold = (
                    candidate["stratum"]
                    + candidate["sampling_rank_within_stratum"]
                    - 2
                ) % folds + 1
                item.update(
                    {
                        "split_role": "crossfit_seen_family",
                        "evaluation_fold_id": evaluation_fold,
                        "training_fold_ids": [
                            fold
                            for fold in range(1, folds + 1)
                            if fold != evaluation_fold
                        ],
                    }
                )
            else:
                item.update(
                    {
                        "split_role": "heldout_family",
                        "evaluation_fold_id": None,
                        "training_fold_ids": [],
                    }
                )
            instances.append(item)
    option: dict[str, Any] = {
        "population_option_id": f"m15-finbench-confirmatory-{total_size}-v1",
        "total_instance_count": total_size,
        "per_family_instance_count": per_family,
        "family_counts": family_counts,
        "seen_family_instance_count": per_family * 2,
        "cold_family_instance_count": per_family,
        "crossfit_fold_count": folds,
        "instances": instances,
    }
    option["population_option_sha256"] = content_hash(option)
    return option


def compile_finbench_confirmatory_population_registry(
    data: FinBenchQueryData,
    *,
    source_artifact_id: str,
    source_archive_sha256: str,
    design: Mapping[str, Any] | str | Path = DEFAULT_DESIGN_PATH,
) -> FinBenchConfirmatoryPopulationRegistry:
    """Compile every author-selectable population without answers or costs."""

    selected = _validate_design(design)
    artifact_id = _safe_id(source_artifact_id, name="source_artifact_id")
    archive_sha256 = _sha256(
        source_archive_sha256, name="source_archive_sha256"
    )
    frame = _candidate_frames(
        data, window_count=selected["f3_suffix_window_count"]
    )
    frame_counts = {
        family_id: len(frame[family_id]) for family_id in _FAMILY_IDS
    }
    frame_identity = {
        family_id: [
            {
                "candidate_id": item["candidate_id"],
                "selection_feature": item["selection_feature"],
                "parameters": item["parameters"],
            }
            for item in frame[family_id]
        ]
        for family_id in _FAMILY_IDS
    }
    options = [
        _population_option(
            frame,
            total_size=size,
            strata=selected["strata_per_family"],
            folds=selected["crossfit_fold_count"],
            seed=selected["sampling_seed"],
        )
        for size in selected["candidate_total_sizes"]
    ]
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_POPULATION_REGISTRY_SCHEMA_VERSION,
        "design_id": selected["design_id"],
        "design_sha256": content_hash(selected),
        "source_artifact_id": artifact_id,
        "source_archive_sha256": archive_sha256,
        "source_time_domain": {
            "minimum": data.minimum_transfer_time,
            "maximum": data.maximum_transfer_time,
        },
        "sampling_frame_counts": frame_counts,
        "sampling_frame_identity_sha256": content_hash(frame_identity),
        "population_options": options,
        "author_selected_population_option_id": None,
        "sampling_provenance": {
            "source_fields_used_for_sampling": selected[
                "source_fields_allowed_for_sampling"
            ],
            "forbidden_fields_used_for_sampling": [],
            "answer_oracle_reads": 0,
            "observed_cost_reads": 0,
            "current_query_profile_calls": 0,
            "backend_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
        },
        "claim_boundary": {
            "artifact_class": "result_blind_population_option_registry",
            "contains_answer_rows": False,
            "contains_execution_measurements": False,
            "author_decision_inferred": False,
            "confirmatory_run_authorized": False,
            "paper_result": False,
        },
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["registry_sha256"] = content_hash(body)
    return FinBenchConfirmatoryPopulationRegistry(body)


def write_finbench_confirmatory_population_registry(
    registry: FinBenchConfirmatoryPopulationRegistry,
    output: str | Path,
) -> Path:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"population registry output exists: {destination}")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            registry.to_dict(),
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
    parser.add_argument("--archive", required=True)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--design", default=str(DEFAULT_DESIGN_PATH))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)
    try:
        lock = load_finbench_artifact_lock(arguments.lock)
        data = load_finbench_query_data(arguments.archive, lock)
        registry = compile_finbench_confirmatory_population_registry(
            data,
            source_artifact_id=lock.artifact.artifact_id,
            source_archive_sha256=lock.artifact.digest_value,
            design=arguments.design,
        )
        write_finbench_confirmatory_population_registry(
            registry, arguments.output
        )
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": "success", **registry.to_dict()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
