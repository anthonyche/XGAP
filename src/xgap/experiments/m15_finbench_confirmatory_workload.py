"""Compile an author-selected, answer-independent FinBench workload.

The population registry is produced without answer or cost observations.  This
compiler accepts one explicit, hash-bound author approval for a registry option,
then materializes public instances, native templates, and a separately sealed
answer oracle.  Workload compilation makes no backend or model call and does
not authorize confirmatory execution.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_artifacts import (
    DEFAULT_LOCK_PATH,
    load_finbench_artifact_lock,
)
from xgap.experiments.m15_finbench_confirmatory_population import (
    FINBENCH_CONFIRMATORY_POPULATION_REGISTRY_SCHEMA_VERSION,
)
from xgap.experiments.m15_finbench_workload import (
    WORKLOAD_SCHEMA_VERSION,
    FinBenchQueryData,
    _canonical_sha256,
    _file_sha256,
    _json_text,
    _templates,
    load_finbench_query_data,
)


FINBENCH_CONFIRMATORY_FAMILY_CONTRACT_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-family-contract-v1"
)
FINBENCH_CONFIRMATORY_POPULATION_APPROVAL_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-population-approval-v1"
)
FINBENCH_CONFIRMATORY_WORKLOAD_GENERATOR_VERSION = (
    "m15-finbench-confirmatory-workload-generator-v1"
)
DEFAULT_FAMILY_CONTRACT_PATH = Path(
    "experiments/configs/m15_finbench_confirmatory_family_contract_v1.json"
)
_FAMILY_IDS = (
    "f1_direct_transfer_control",
    "f2_temporal_path_control",
    "f3_aggregate_risk_ranking",
)
_STRATEGIES = {
    _FAMILY_IDS[0]: ("graph_first_hash", "control_first_bind"),
    _FAMILY_IDS[1]: ("path_first_hash", "control_first_bound_path"),
    _FAMILY_IDS[2]: ("aggregate_first_hash", "control_first_bound_aggregate"),
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FinBenchConfirmatoryWorkloadError(ValueError):
    """Raised when selection authority, population, or workload drifts."""


def _json_object(
    value: Mapping[str, Any] | str | Path, *, name: str
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise FinBenchConfirmatoryWorkloadError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchConfirmatoryWorkloadError(f"{name} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise FinBenchConfirmatoryWorkloadError(f"{name} must be an object")
    return dict(payload)


def _safe_id(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise FinBenchConfirmatoryWorkloadError(f"{name} is not a safe identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise FinBenchConfirmatoryWorkloadError(f"{name} is not a SHA-256")
    return value


def _registry(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    registry = _json_object(value, name="confirmatory population registry")
    if (
        registry.get("schema_version")
        != FINBENCH_CONFIRMATORY_POPULATION_REGISTRY_SCHEMA_VERSION
        or registry.get("author_selected_population_option_id") is not None
        or registry.get("automatic_retries") != 0
        or registry.get("paper_result") is not False
    ):
        raise FinBenchConfirmatoryWorkloadError("population registry boundary changed")
    claimed = _sha256(registry.get("registry_sha256"), name="registry_sha256")
    body = {key: item for key, item in registry.items() if key != "registry_sha256"}
    if content_hash(body) != claimed:
        raise FinBenchConfirmatoryWorkloadError("population registry hash mismatch")
    provenance = registry.get("sampling_provenance")
    boundary = registry.get("claim_boundary")
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("answer_oracle_reads") != 0
        or provenance.get("observed_cost_reads") != 0
        or provenance.get("backend_calls") != 0
        or provenance.get("current_query_profile_calls") != 0
        or not isinstance(boundary, Mapping)
        or boundary.get("contains_answer_rows") is not False
        or boundary.get("contains_execution_measurements") is not False
        or boundary.get("author_decision_inferred") is not False
        or boundary.get("confirmatory_run_authorized") is not False
    ):
        raise FinBenchConfirmatoryWorkloadError("population registry is not result blind")
    options = registry.get("population_options")
    if not isinstance(options, list) or len(options) != 3:
        raise FinBenchConfirmatoryWorkloadError("population registry options changed")
    return registry


def _approval(
    value: Mapping[str, Any] | str | Path,
    *,
    registry: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    approval = _json_object(value, name="population approval")
    expected_fields = {
        "schema_version",
        "approval_id",
        "authority_source_id",
        "registry_sha256",
        "selected_population_option_id",
        "selected_population_option_sha256",
        "decision_basis",
        "confirmatory_workload_compilation_authorized",
        "confirmatory_execution_authorized",
        "paper_result",
        "approval_sha256",
    }
    if set(approval) != expected_fields:
        raise FinBenchConfirmatoryWorkloadError("population approval fields changed")
    if (
        approval["schema_version"]
        != FINBENCH_CONFIRMATORY_POPULATION_APPROVAL_SCHEMA_VERSION
        or approval["registry_sha256"] != registry["registry_sha256"]
        or approval["decision_basis"]
        != "explicit_author_choice_before_confirmatory_measurement"
        or approval["confirmatory_workload_compilation_authorized"] is not True
        or approval["confirmatory_execution_authorized"] is not False
        or approval["paper_result"] is not False
    ):
        raise FinBenchConfirmatoryWorkloadError("population approval boundary changed")
    _safe_id(approval["approval_id"], name="approval_id")
    _safe_id(approval["authority_source_id"], name="authority_source_id")
    option_id = _safe_id(
        approval["selected_population_option_id"],
        name="selected_population_option_id",
    )
    option_hash = _sha256(
        approval["selected_population_option_sha256"],
        name="selected_population_option_sha256",
    )
    claimed = _sha256(approval["approval_sha256"], name="approval_sha256")
    approval_body = {
        key: item for key, item in approval.items() if key != "approval_sha256"
    }
    if content_hash(approval_body) != claimed:
        raise FinBenchConfirmatoryWorkloadError("population approval hash mismatch")
    matches = [
        item
        for item in registry["population_options"]
        if isinstance(item, Mapping) and item.get("population_option_id") == option_id
    ]
    if len(matches) != 1 or matches[0].get("population_option_sha256") != option_hash:
        raise FinBenchConfirmatoryWorkloadError(
            "population approval does not identify one registry option"
        )
    return approval, copy.deepcopy(dict(matches[0]))


def build_finbench_confirmatory_population_approval(
    registry: Mapping[str, Any] | str | Path,
    *,
    selected_population_option_id: str,
    approval_id: str,
    authority_source_id: str,
) -> dict[str, Any]:
    """Build a deterministic author approval payload; writing it is separate."""

    selected_registry = _registry(registry)
    option_id = _safe_id(
        selected_population_option_id, name="selected_population_option_id"
    )
    matches = [
        item
        for item in selected_registry["population_options"]
        if isinstance(item, Mapping) and item.get("population_option_id") == option_id
    ]
    if len(matches) != 1:
        raise FinBenchConfirmatoryWorkloadError("selected population option is unknown")
    body: dict[str, Any] = {
        "schema_version": FINBENCH_CONFIRMATORY_POPULATION_APPROVAL_SCHEMA_VERSION,
        "approval_id": _safe_id(approval_id, name="approval_id"),
        "authority_source_id": _safe_id(
            authority_source_id, name="authority_source_id"
        ),
        "registry_sha256": selected_registry["registry_sha256"],
        "selected_population_option_id": option_id,
        "selected_population_option_sha256": matches[0][
            "population_option_sha256"
        ],
        "decision_basis": "explicit_author_choice_before_confirmatory_measurement",
        "confirmatory_workload_compilation_authorized": True,
        "confirmatory_execution_authorized": False,
        "paper_result": False,
    }
    return {**body, "approval_sha256": content_hash(body)}


def _family_contract(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    contract = _json_object(value, name="confirmatory family contract")
    expected_fields = {
        "schema_version",
        "contract_id",
        "benchmark_claim",
        "families",
        "query_instance_is_inferential_unit",
        "repetitions_are_not_independent_units",
        "automatic_retries",
        "backend_calls",
        "llm_calls",
        "ontology_service_calls",
        "paper_result",
    }
    if set(contract) != expected_fields or (
        contract["schema_version"]
        != FINBENCH_CONFIRMATORY_FAMILY_CONTRACT_SCHEMA_VERSION
        or contract["contract_id"]
        != "m15-finbench-confirmatory-three-family-v1"
        or contract["benchmark_claim"]
        != "finbench_derived_heterogeneous_workload_not_a_conformant_finbench_result"
        or contract["query_instance_is_inferential_unit"] is not True
        or contract["repetitions_are_not_independent_units"] is not True
        or contract["automatic_retries"] != 0
        or contract["paper_result"] is not False
        or any(
            contract[field] != 0
            for field in ("backend_calls", "llm_calls", "ontology_service_calls")
        )
    ):
        raise FinBenchConfirmatoryWorkloadError("family contract boundary changed")
    families = contract["families"]
    if (
        not isinstance(families, list)
        or [item.get("family_id") for item in families if isinstance(item, Mapping)]
        != list(_FAMILY_IDS)
    ):
        raise FinBenchConfirmatoryWorkloadError("family contract identity changed")
    for family in families:
        strategies = family.get("physical_strategies")
        if tuple(strategies) != _STRATEGIES[family["family_id"]]:
            raise FinBenchConfirmatoryWorkloadError("family strategies changed")
        if not isinstance(family.get("hard_constraints"), list) or not family[
            "hard_constraints"
        ]:
            raise FinBenchConfirmatoryWorkloadError("family constraints are missing")
    if families[2].get("cold_start_fallback") != _STRATEGIES[_FAMILY_IDS[2]][0]:
        raise FinBenchConfirmatoryWorkloadError("cold-family fallback changed")
    return contract


def _amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001')):.3f}"


def _natural_language(instance: Mapping[str, Any]) -> str:
    family_id = instance["family_id"]
    parameters = instance["parameters"]
    if family_id == _FAMILY_IDS[0]:
        return (
            "Within the inclusive benchmark time window, which blocked "
            f"company-owned accounts received transfers from person "
            f"{parameters['person_id']}, and what total amount did each "
            "company/account receive?"
        )
    if family_id == _FAMILY_IDS[1]:
        return (
            f"From account {parameters['start_account_id']}, find accounts "
            "reachable in one to three cycle-free outward transfers with "
            "strictly increasing timestamps inside the inclusive benchmark "
            "window and signed into by a blocked medium."
        )
    return (
        f"Between {parameters['start_time']} inclusive and "
        f"{parameters['end_time']} exclusive, rank the top "
        f"{parameters['top_k']} companies by total transfers into "
        "company-owned accounts signed into by a medium whose exact category "
        f"is {parameters['risk_level']}."
    )


def _f1_oracle(
    data: FinBenchQueryData, parameters: Mapping[str, Any]
) -> dict[str, Any]:
    blocked = {
        identifier
        for identifier, row in data.accounts.items()
        if row["isBlocked"] == "true"
    }
    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for transfer in data.transfers:
        if (
            data.person_by_account.get(transfer.from_id) != parameters["person_id"]
            or not parameters["start_time"]
            <= transfer.create_time
            <= parameters["end_time"]
        ):
            continue
        company_id = data.company_by_account.get(transfer.to_id)
        if company_id is not None:
            totals[(company_id, transfer.to_id)] += transfer.amount
    full = [
        {
            "company_id": company_id,
            "account_id": account_id,
            "total_amount": _amount(total),
        }
        for (company_id, account_id), total in sorted(totals.items())
    ]
    final = [item for item in full if item["account_id"] in blocked]
    return {
        "neo4j_full": full,
        "fuseki_control": [
            {"account_id": identifier} for identifier in sorted(blocked)
        ],
        "neo4j_bound": final,
        "final_rows": final,
    }


def _path_rows(
    data: FinBenchQueryData,
    *,
    start_id: str,
    start_time: str,
    end_time: str,
    max_hops: int,
    blocked_media: set[str] | None,
) -> list[dict[str, Any]]:
    rows: set[tuple[str, int, str]] = set()

    def visit(
        node: str, depth: int, last_time: str | None, visited: frozenset[str]
    ) -> None:
        if depth == max_hops:
            return
        for transfer in data.outgoing.get(node, ()):
            if (
                transfer.to_id in visited
                or not start_time <= transfer.create_time <= end_time
                or (last_time is not None and transfer.create_time <= last_time)
            ):
                continue
            next_depth = depth + 1
            for medium_id in data.media_by_account.get(transfer.to_id, ()):
                if blocked_media is None or medium_id in blocked_media:
                    rows.add((transfer.to_id, next_depth, medium_id))
            visit(
                transfer.to_id,
                next_depth,
                transfer.create_time,
                visited | {transfer.to_id},
            )

    visit(start_id, 0, None, frozenset({start_id}))
    return [
        {
            "other_id": other_id,
            "account_distance": distance,
            "medium_id": medium_id,
        }
        for other_id, distance, medium_id in sorted(
            rows, key=lambda item: (item[1], item[0], item[2])
        )
    ]


def _f2_oracle(
    data: FinBenchQueryData, parameters: Mapping[str, Any]
) -> dict[str, Any]:
    blocked = {
        identifier
        for identifier, row in data.media.items()
        if row["isBlocked"] == "true"
    }
    control = [
        {
            "medium_id": identifier,
            "medium_type": data.media[identifier]["mediumType"],
        }
        for identifier in sorted(blocked)
    ]
    medium_type = {item["medium_id"]: item["medium_type"] for item in control}
    common = {
        "start_id": str(parameters["start_account_id"]),
        "start_time": str(parameters["start_time"]),
        "end_time": str(parameters["end_time"]),
        "max_hops": int(parameters["max_hops"]),
    }
    full = _path_rows(data, blocked_media=None, **common)
    bound = _path_rows(data, blocked_media=blocked, **common)
    final = [{**item, "medium_type": medium_type[item["medium_id"]]} for item in bound]
    return {
        "neo4j_full": full,
        "fuseki_control": control,
        "neo4j_bound": bound,
        "final_rows": final,
    }


def _f3_oracle(
    data: FinBenchQueryData, parameters: Mapping[str, Any]
) -> dict[str, Any]:
    control_ids = {
        identifier
        for identifier, row in data.media.items()
        if row["riskLevel"] == parameters["risk_level"]
    }
    eligible_accounts = {
        account_id
        for account_id, media_ids in data.media_by_account.items()
        if control_ids.intersection(media_ids)
        and account_id in data.company_by_account
    }
    account_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    company_totals: dict[str, Decimal] = defaultdict(Decimal)
    for transfer in data.transfers:
        if not parameters["start_time"] <= transfer.create_time < parameters["end_time"]:
            continue
        company_id = data.company_by_account.get(transfer.to_id)
        if company_id is None or transfer.to_id not in data.media_by_account:
            continue
        account_totals[(company_id, transfer.to_id)] += transfer.amount
        if transfer.to_id in eligible_accounts:
            company_totals[company_id] += transfer.amount
    full = [
        {
            "company_id": company_id,
            "account_id": account_id,
            "medium_ids": list(data.media_by_account[account_id]),
            "account_amount": _amount(total),
        }
        for (company_id, account_id), total in sorted(account_totals.items())
    ]
    final = [
        {"company_id": company_id, "total_amount": _amount(total)}
        for company_id, total in sorted(
            company_totals.items(), key=lambda item: (-item[1], item[0])
        )[: int(parameters["top_k"])]
    ]
    return {
        "fuseki_control": [
            {"medium_id": identifier} for identifier in sorted(control_ids)
        ],
        "neo4j_full": full,
        "neo4j_bound": final,
        "final_rows": final,
    }


def _instance_and_oracle(
    data: FinBenchQueryData, raw: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {
        "query_id",
        "family_id",
        "candidate_id",
        "selection_position",
        "stratum",
        "sampling_score",
        "sampling_rank_within_stratum",
        "selection_feature",
        "parameters",
        "split_role",
        "evaluation_fold_id",
        "training_fold_ids",
    }
    if set(raw) != required:
        raise FinBenchConfirmatoryWorkloadError("population instance fields changed")
    item = copy.deepcopy(dict(raw))
    query_id = _safe_id(item["query_id"], name="query_id")
    family_id = _safe_id(item["family_id"], name="family_id")
    if family_id not in _FAMILY_IDS or not isinstance(item["parameters"], Mapping):
        raise FinBenchConfirmatoryWorkloadError("population instance is invalid")
    if family_id in _FAMILY_IDS[:2]:
        if (
            item["split_role"] != "crossfit_seen_family"
            or item["evaluation_fold_id"] not in {1, 2, 3, 4}
            or sorted(item["training_fold_ids"])
            != [fold for fold in range(1, 5) if fold != item["evaluation_fold_id"]]
        ):
            raise FinBenchConfirmatoryWorkloadError("cross-fit assignment changed")
    elif (
        item["split_role"] != "heldout_family"
        or item["evaluation_fold_id"] is not None
        or item["training_fold_ids"] != []
    ):
        raise FinBenchConfirmatoryWorkloadError("cold-family assignment changed")
    item["natural_language"] = _natural_language(item)
    if family_id == _FAMILY_IDS[0]:
        oracle = _f1_oracle(data, item["parameters"])
    elif family_id == _FAMILY_IDS[1]:
        oracle = _f2_oracle(data, item["parameters"])
    else:
        oracle = _f3_oracle(data, item["parameters"])
    if set(oracle) != {
        "neo4j_full",
        "fuseki_control",
        "neo4j_bound",
        "final_rows",
    }:
        raise FinBenchConfirmatoryWorkloadError(f"oracle shape changed for {query_id}")
    return item, oracle


def build_finbench_confirmatory_workload(
    *,
    archive_path: str | Path,
    population_registry: Mapping[str, Any] | str | Path,
    population_approval: Mapping[str, Any] | str | Path,
    output_root: str | Path,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    family_contract: Mapping[str, Any] | str | Path = DEFAULT_FAMILY_CONTRACT_PATH,
) -> dict[str, Any]:
    """Materialize one explicitly approved population without executing it."""

    archive_input = Path(archive_path)
    destination_input = Path(output_root)
    if archive_input.is_symlink() or not archive_input.is_file():
        raise FinBenchConfirmatoryWorkloadError(
            "archive must be a regular non-symbolic-link file"
        )
    if destination_input.exists() or destination_input.is_symlink():
        raise FinBenchConfirmatoryWorkloadError(
            f"output already exists: {destination_input}"
        )
    archive = archive_input.resolve()
    destination = destination_input.resolve()
    registry = _registry(population_registry)
    approval, option = _approval(population_approval, registry=registry)
    contract = _family_contract(family_contract)
    lock = load_finbench_artifact_lock(lock_path)
    if (
        lock.artifact.artifact_id != registry.get("source_artifact_id")
        or lock.artifact.digest_value != registry.get("source_archive_sha256")
    ):
        raise FinBenchConfirmatoryWorkloadError(
            "population registry source identity changed"
        )
    data = load_finbench_query_data(archive, lock)
    instances: list[dict[str, Any]] = []
    oracles: dict[str, dict[str, Any]] = {}
    for raw in option["instances"]:
        if not isinstance(raw, Mapping):
            raise FinBenchConfirmatoryWorkloadError("population instance is invalid")
        instance, oracle = _instance_and_oracle(data, raw)
        query_id = instance["query_id"]
        if query_id in oracles:
            raise FinBenchConfirmatoryWorkloadError("duplicate population query_id")
        instances.append(instance)
        oracles[query_id] = oracle
    if len(instances) != option["total_instance_count"]:
        raise FinBenchConfirmatoryWorkloadError("population option count changed")
    family_counts = Counter(item["family_id"] for item in instances)
    if dict(family_counts) != option["family_counts"]:
        raise FinBenchConfirmatoryWorkloadError("population family counts changed")
    split_counts = Counter(item["split_role"] for item in instances)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=destination.name + ".partial-", dir=destination.parent)
    )
    try:
        template_root = staging / "templates"
        template_root.mkdir()
        template_records: dict[str, Any] = {}
        for name, text in sorted(_templates().items()):
            path = template_root / name
            path.write_text(text.rstrip() + "\n", encoding="utf-8")
            template_records[name] = {
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        public_instances = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "population_id": option["population_option_id"],
            "instances": instances,
            "oracle_fields_present": False,
            "paper_result": False,
        }
        oracle_payload = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "population_id": option["population_option_id"],
            "selection_access": "forbidden_until_all_plan_runs_finish",
            "queries": oracles,
            "paper_result": False,
        }
        family_contracts = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "population_id": option["population_option_id"],
            "families": contract["families"],
            "paper_result": False,
        }
        for name, payload in (
            ("public_instances.json", public_instances),
            ("sealed_oracles.json", oracle_payload),
            ("family_contracts.json", family_contracts),
        ):
            (staging / name).write_text(_json_text(payload), encoding="utf-8")
        output_files = {
            name: {
                "sha256": _file_sha256(staging / name),
                "size_bytes": (staging / name).stat().st_size,
            }
            for name in (
                "public_instances.json",
                "sealed_oracles.json",
                "family_contracts.json",
            )
        }
        manifest: dict[str, Any] = {
            "schema_version": WORKLOAD_SCHEMA_VERSION,
            "generator_version": FINBENCH_CONFIRMATORY_WORKLOAD_GENERATOR_VERSION,
            "population_id": option["population_option_id"],
            "population_option_sha256": option["population_option_sha256"],
            "population_registry_sha256": registry["registry_sha256"],
            "population_approval_sha256": approval["approval_sha256"],
            "population_approval_id": approval["approval_id"],
            "authority_source_id": approval["authority_source_id"],
            "source_artifact_id": lock.artifact.artifact_id,
            "source_archive_sha256": lock.artifact.digest_value,
            "family_contract_sha256": content_hash(contract),
            "instance_count": len(instances),
            "family_counts": dict(sorted(family_counts.items())),
            "split_counts": dict(sorted(split_counts.items())),
            "time_domain": {
                "minimum": data.minimum_transfer_time,
                "maximum": data.maximum_transfer_time,
            },
            "template_files": template_records,
            "output_files": output_files,
            "oracle_isolation": {
                "separate_file": True,
                "selection_access": "forbidden_until_all_plan_runs_finish",
                "public_instances_contain_oracle_fields": False,
                "empty_answers_retained": True,
            },
            "inference_boundary": {
                "query_instance_is_inferential_unit": True,
                "repetitions_are_not_independent_units": True,
                "seen_family_predictions_are_crossfit": True,
                "cold_family_reported_separately": True,
            },
            "confirmatory_workload_compilation_authorized": True,
            "confirmatory_execution_authorized": False,
            "automatic_retries": 0,
            "backend_calls": 0,
            "current_query_profile_calls": 0,
            "llm_calls": 0,
            "ontology_service_calls": 0,
            "paper_result": False,
        }
        manifest["workload_sha256"] = _canonical_sha256(manifest)
        (staging / "workload_manifest.json").write_text(
            _json_text(manifest), encoding="utf-8"
        )
        os.replace(staging, destination)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--family-contract", default=str(DEFAULT_FAMILY_CONTRACT_PATH))
    args = parser.parse_args(argv)
    try:
        manifest = build_finbench_confirmatory_workload(
            archive_path=args.archive,
            population_registry=args.registry,
            population_approval=args.approval,
            output_root=args.output_root,
            lock_path=args.lock,
            family_contract=args.family_contract,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "success", **manifest}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
