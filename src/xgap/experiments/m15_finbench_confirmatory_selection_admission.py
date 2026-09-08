"""Bind result-blind confirmatory selection to prior semantic evidence.

The family-memory selector needs costs from the first seven measurement blocks
before the confirmatory answer oracle may be opened.  This contract prevents a
misleading shortcut: those costs are admitted because the two physical plan
families were compiler-bound to the same semantic query and independently
validated on the development SF0.1 workload, not because the current 48 query
answers have already been inspected.  The final confirmatory oracle remains
authoritative and can invalidate the campaign after all measurements finish.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_finbench_correctness_evidence import (
    FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
    audit_m15_finbench_correctness,
)
from xgap.experiments.m15_finbench_workload import (
    load_finbench_primary_public_workload,
)


FINBENCH_CONFIRMATORY_SELECTION_ADMISSION_SCHEMA_VERSION = (
    "m15-finbench-confirmatory-selection-admission-v1"
)
DEFAULT_CORRECTNESS_RECEIPT_PATH = Path(
    "experiments/artifacts/"
    "m15_finbench_sf0_1_cwru_correctness_3793698_receipt.json"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEEN_FAMILIES = (
    "f1_direct_transfer_control",
    "f2_temporal_path_control",
)
_SEEN_STRATEGIES = {
    "f1_direct_transfer_control": (
        "graph_first_hash",
        "control_first_bind",
    ),
    "f2_temporal_path_control": (
        "path_first_hash",
        "control_first_bound_path",
    ),
}
_SEEN_HARD_CONSTRAINTS = {
    "f1_direct_transfer_control": (
        "person_id",
        "inclusive_time_window",
        "company_account_ownership",
        "destination_account_is_blocked_true",
        "transfer_direction",
        "sum_amount_by_company_and_account",
        "output_schema",
    ),
    "f2_temporal_path_control": (
        "start_account_id",
        "inclusive_time_window",
        "transfer_direction",
        "strictly_increasing_transfer_timestamps",
        "cycle_free_account_path",
        "max_hops_3",
        "medium_is_blocked_true",
        "output_schema",
    ),
}


class FinBenchConfirmatorySelectionAdmissionError(ValueError):
    """Raised when the pre-oracle selection admission cannot be reproduced."""


def _read_json(path: str | Path, *, name: str) -> dict[str, Any]:
    selected = Path(path)
    if selected.is_symlink() or not selected.is_file():
        raise FinBenchConfirmatorySelectionAdmissionError(
            f"{name} must be a regular non-symbolic-link file"
        )
    try:
        value = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinBenchConfirmatorySelectionAdmissionError(
            f"{name} is not valid JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatorySelectionAdmissionError(
            f"{name} must contain a JSON object"
        )
    return copy.deepcopy(dict(value))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _family_signature(value: Mapping[str, Any]) -> dict[str, Any]:
    families = value.get("families")
    if not isinstance(families, list):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "family contracts are missing"
        )
    result: dict[str, Any] = {}
    for raw in families:
        if not isinstance(raw, Mapping):
            raise FinBenchConfirmatorySelectionAdmissionError(
                "family contract is invalid"
            )
        family_id = raw.get("family_id")
        if family_id not in _SEEN_FAMILIES:
            continue
        strategies = raw.get("physical_strategies")
        hard = raw.get("hard_constraints")
        if (
            not isinstance(strategies, list)
            or len(strategies) != 2
            or len(set(strategies)) != 2
            or not isinstance(hard, list)
            or not hard
        ):
            raise FinBenchConfirmatorySelectionAdmissionError(
                "seen-family semantic contract is invalid"
            )
        result[str(family_id)] = {
            "physical_strategies": copy.deepcopy(strategies),
            "hard_constraints": copy.deepcopy(hard),
        }
    if tuple(sorted(result)) != tuple(sorted(_SEEN_FAMILIES)):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "seen-family semantic contracts are incomplete"
        )
    return result


def validate_finbench_confirmatory_selection_admission(
    value: Mapping[str, Any], *, workload_sha256: str | None = None
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "selection admission must be an object"
        )
    result = copy.deepcopy(dict(value))
    claimed = result.get("selection_admission_sha256")
    body = {
        key: item
        for key, item in result.items()
        if key != "selection_admission_sha256"
    }
    evidence = result.get("development_correctness_evidence")
    semantic_contract = result.get("seen_family_semantic_contract")
    if (
        not isinstance(claimed, str)
        or _SHA256.fullmatch(claimed) is None
        or content_hash(body) != claimed
        or result.get("schema_version")
        != FINBENCH_CONFIRMATORY_SELECTION_ADMISSION_SCHEMA_VERSION
        or _SHA256.fullmatch(
            str(result.get("confirmatory_workload_sha256"))
        )
        is None
        or _SHA256.fullmatch(str(result.get("source_archive_sha256"))) is None
        or (
            workload_sha256 is not None
            and result.get("confirmatory_workload_sha256") != workload_sha256
        )
        or not isinstance(evidence, Mapping)
        or evidence.get("audit_success") is not True
        or evidence.get("audit_failed_check_ids") != []
        or evidence.get("run_tree_mutated") is not False
        or evidence.get("all_plans_exact") is not True
        or evidence.get("all_physical_pairs_equivalent") is not True
        or _COMMIT.fullmatch(str(evidence.get("producer_commit"))) is None
        or any(
            _SHA256.fullmatch(str(evidence.get(field))) is None
            for field in (
                "correctness_workload_sha256",
                "correctness_manifest_sha256",
                "correctness_audit_content_sha256",
                "correctness_receipt_file_sha256",
            )
        )
        or result.get("admitted_family_ids") != list(_SEEN_FAMILIES)
        or not isinstance(semantic_contract, Mapping)
        or tuple(sorted(semantic_contract)) != tuple(sorted(_SEEN_FAMILIES))
        or any(
            not isinstance(semantic_contract.get(family_id), Mapping)
            or semantic_contract[family_id].get("physical_strategies")
            != list(_SEEN_STRATEGIES[family_id])
            or not isinstance(
                semantic_contract[family_id].get("hard_constraints"), list
            )
            or semantic_contract[family_id]["hard_constraints"]
            != list(_SEEN_HARD_CONSTRAINTS[family_id])
            for family_id in _SEEN_FAMILIES
        )
        or result.get("training_cost_outcome_admission")
        != "successful_contract_bound_runs_only"
        or result.get("training_exactness_semantics")
        != "plan_family_semantic_contract_not_current_query_oracle"
        or result.get("current_confirmatory_query_oracle_opened") is not False
        or result.get("final_confirmatory_oracle_is_authoritative") is not True
        or result.get("current_query_profile_calls") != 0
        or result.get("backend_calls") != 0
        or result.get("llm_calls") != 0
        or result.get("ontology_service_calls") != 0
        or result.get("automatic_retries") != 0
        or result.get("paper_result") is not False
    ):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "selection admission boundary changed"
        )
    return result


def build_finbench_confirmatory_selection_admission(
    *,
    confirmatory_workload_root: str | Path,
    correctness_run_root: str | Path,
    correctness_audit: str | Path,
    correctness_expected_commit: str,
    correctness_receipt: str | Path = DEFAULT_CORRECTNESS_RECEIPT_PATH,
) -> dict[str, Any]:
    """Reconstruct the prior correctness gate and seal selection provenance."""

    if _COMMIT.fullmatch(correctness_expected_commit) is None:
        raise FinBenchConfirmatorySelectionAdmissionError(
            "correctness_expected_commit must be a full lowercase Git commit"
        )
    saved_audit = _read_json(correctness_audit, name="correctness audit")
    rebuilt_audit = audit_m15_finbench_correctness(
        run_root=correctness_run_root,
        expected_commit=correctness_expected_commit,
    ).to_dict()
    if saved_audit != rebuilt_audit or (
        saved_audit.get("schema_version")
        != FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION
        or saved_audit.get("success") is not True
        or saved_audit.get("failed_check_ids") != []
        or saved_audit.get("run_tree_mutated") is not False
    ):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "correctness audit failed independent replay"
        )
    correctness_root = Path(correctness_run_root).resolve()
    correctness_live = (
        correctness_root / "native-service-run/finbench-correctness-run"
    )
    correctness_manifest = _read_json(
        correctness_live / "run_manifest.json", name="correctness manifest"
    )
    correctness_workload = load_finbench_primary_public_workload(
        correctness_root / "finbench-primary-workload"
    )
    confirmatory_workload = load_finbench_primary_public_workload(
        confirmatory_workload_root
    )
    correctness_summary = correctness_manifest.get("summary")
    if (
        correctness_manifest.get("status") != "success"
        or not isinstance(correctness_summary, Mapping)
        or correctness_summary.get("all_plans_exact") is not True
        or correctness_summary.get("all_physical_pairs_equivalent") is not True
        or correctness_manifest.get("automatic_retries") != 0
        or correctness_manifest.get("paper_result") is not False
    ):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "development correctness evidence is not admissible"
        )
    correctness_public = correctness_workload["manifest"]
    confirmatory_public = confirmatory_workload["manifest"]
    if (
        correctness_public.get("source_archive_sha256")
        != confirmatory_public.get("source_archive_sha256")
    ):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "correctness and confirmatory workloads use different source archives"
        )
    correctness_signature = _family_signature(
        correctness_workload["family_contracts"]
    )
    confirmatory_signature = _family_signature(
        confirmatory_workload["family_contracts"]
    )
    if correctness_signature != confirmatory_signature:
        raise FinBenchConfirmatorySelectionAdmissionError(
            "seen-family physical semantic contracts changed"
        )
    receipt_path = Path(correctness_receipt)
    receipt = _read_json(receipt_path, name="correctness receipt")
    receipt_audit = receipt.get("independent_audit")
    receipt_source = receipt.get("source_artifact")
    receipt_producer = receipt.get("producer")
    if (
        receipt.get("schema_version")
        != "m15-finbench-sf0-1-correctness-external-receipt-v1"
        or receipt.get("paper_result") is not False
        or not isinstance(receipt_audit, Mapping)
        or receipt_audit.get("success") is not True
        or receipt_audit.get("failed_check_ids") != []
        or receipt_audit.get("run_tree_mutated") is not False
        or not isinstance(receipt_source, Mapping)
        or receipt_source.get("archive_sha256")
        != confirmatory_public.get("source_archive_sha256")
        or not isinstance(receipt_producer, Mapping)
        or receipt_producer.get("git_commit") != correctness_expected_commit
    ):
        raise FinBenchConfirmatorySelectionAdmissionError(
            "correctness receipt does not bind the accepted evidence"
        )
    body: dict[str, Any] = {
        "schema_version": (
            FINBENCH_CONFIRMATORY_SELECTION_ADMISSION_SCHEMA_VERSION
        ),
        "confirmatory_workload_sha256": confirmatory_public["workload_sha256"],
        "source_archive_sha256": confirmatory_public["source_archive_sha256"],
        "admitted_family_ids": list(_SEEN_FAMILIES),
        "seen_family_semantic_contract": confirmatory_signature,
        "development_correctness_evidence": {
            "producer_commit": correctness_expected_commit,
            "correctness_workload_sha256": correctness_public["workload_sha256"],
            "correctness_manifest_sha256": correctness_manifest[
                "manifest_sha256"
            ],
            "correctness_audit_content_sha256": content_hash(saved_audit),
            "correctness_receipt_file_sha256": _file_sha256(receipt_path),
            "audit_success": True,
            "audit_failed_check_ids": [],
            "run_tree_mutated": False,
            "all_plans_exact": True,
            "all_physical_pairs_equivalent": True,
        },
        "training_cost_outcome_admission": (
            "successful_contract_bound_runs_only"
        ),
        "training_exactness_semantics": (
            "plan_family_semantic_contract_not_current_query_oracle"
        ),
        "current_confirmatory_query_oracle_opened": False,
        "final_confirmatory_oracle_is_authoritative": True,
        "current_query_profile_calls": 0,
        "backend_calls": 0,
        "llm_calls": 0,
        "ontology_service_calls": 0,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["selection_admission_sha256"] = content_hash(body)
    return body


def _write_json(path: str | Path, value: Mapping[str, Any]) -> Path:
    selected = Path(path)
    if selected.exists() or selected.is_symlink():
        raise FileExistsError(f"output exists: {selected}")
    selected.parent.mkdir(parents=True, exist_ok=True)
    temporary = selected.with_name(selected.name + f".partial-{os.getpid()}")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, selected)
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirmatory-workload-root", required=True)
    parser.add_argument("--correctness-run-root", required=True)
    parser.add_argument("--correctness-audit", required=True)
    parser.add_argument("--correctness-expected-commit", required=True)
    parser.add_argument(
        "--correctness-receipt", default=str(DEFAULT_CORRECTNESS_RECEIPT_PATH)
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_finbench_confirmatory_selection_admission(
            confirmatory_workload_root=args.confirmatory_workload_root,
            correctness_run_root=args.correctness_run_root,
            correctness_audit=args.correctness_audit,
            correctness_expected_commit=args.correctness_expected_commit,
            correctness_receipt=args.correctness_receipt,
        )
        output = _write_json(args.output, result)
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "success",
                "selection_admission_sha256": result[
                    "selection_admission_sha256"
                ],
                "output": str(output.resolve()),
                "paper_result": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
