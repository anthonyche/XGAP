from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xgap.experiments import (
    m15_finbench_confirmatory_selection_admission as admission,
)
from xgap.experiments.m15_finbench_correctness_evidence import (
    FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
)


COMMIT = "a" * 40
ARCHIVE_SHA256 = "b" * 64
CORRECTNESS_WORKLOAD_SHA256 = "c" * 64
CONFIRMATORY_WORKLOAD_SHA256 = "d" * 64


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _family_contracts() -> dict[str, object]:
    return {
        "families": [
            {
                "family_id": "f1_direct_transfer_control",
                "physical_strategies": [
                    "graph_first_hash",
                    "control_first_bind",
                ],
                "hard_constraints": [
                    "person_id",
                    "inclusive_time_window",
                    "company_account_ownership",
                    "destination_account_is_blocked_true",
                    "transfer_direction",
                    "sum_amount_by_company_and_account",
                    "output_schema",
                ],
            },
            {
                "family_id": "f2_temporal_path_control",
                "physical_strategies": [
                    "path_first_hash",
                    "control_first_bound_path",
                ],
                "hard_constraints": [
                    "start_account_id",
                    "inclusive_time_window",
                    "transfer_direction",
                    "strictly_increasing_transfer_timestamps",
                    "cycle_free_account_path",
                    "max_hops_3",
                    "medium_is_blocked_true",
                    "output_schema",
                ],
            },
            {
                "family_id": "f3_aggregate_risk_ranking",
                "physical_strategies": [
                    "aggregate_first_hash",
                    "control_first_bound_aggregate",
                ],
                "hard_constraints": ["output_schema"],
            },
        ]
    }


def _build_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path]:
    correctness_root = tmp_path / "correctness-run"
    confirmatory_root = tmp_path / "confirmatory-workload"
    audit_path = tmp_path / "correctness-audit.json"
    receipt_path = tmp_path / "correctness-receipt.json"
    manifest = {
        "status": "success",
        "summary": {
            "all_plans_exact": True,
            "all_physical_pairs_equivalent": True,
        },
        "manifest_sha256": "e" * 64,
        "automatic_retries": 0,
        "paper_result": False,
    }
    _write(
        correctness_root
        / "native-service-run/finbench-correctness-run/run_manifest.json",
        manifest,
    )
    saved_audit = {
        "schema_version": FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
        "success": True,
        "failed_check_ids": [],
        "run_tree_mutated": False,
    }
    _write(audit_path, saved_audit)
    _write(
        receipt_path,
        {
            "schema_version": (
                "m15-finbench-sf0-1-correctness-external-receipt-v1"
            ),
            "source_artifact": {"archive_sha256": ARCHIVE_SHA256},
            "producer": {"git_commit": COMMIT},
            "independent_audit": {
                "success": True,
                "failed_check_ids": [],
                "run_tree_mutated": False,
            },
            "paper_result": False,
        },
    )
    correctness_public = {
        "manifest": {
            "workload_sha256": CORRECTNESS_WORKLOAD_SHA256,
            "source_archive_sha256": ARCHIVE_SHA256,
        },
        "family_contracts": _family_contracts(),
    }
    confirmatory_public = {
        "manifest": {
            "workload_sha256": CONFIRMATORY_WORKLOAD_SHA256,
            "source_archive_sha256": ARCHIVE_SHA256,
        },
        "family_contracts": _family_contracts(),
    }

    def load_workload(root: str | Path) -> dict[str, object]:
        selected = Path(root)
        if selected == correctness_root / "finbench-primary-workload":
            return correctness_public
        if selected == confirmatory_root:
            return confirmatory_public
        raise AssertionError(f"unexpected workload root: {selected}")

    monkeypatch.setattr(
        admission,
        "audit_m15_finbench_correctness",
        lambda **_kwargs: SimpleNamespace(to_dict=lambda: saved_audit),
    )
    monkeypatch.setattr(
        admission, "load_finbench_primary_public_workload", load_workload
    )
    return correctness_root, confirmatory_root, audit_path, receipt_path


def test_selection_admission_replays_prior_correctness_without_current_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    correctness_root, confirmatory_root, audit_path, receipt_path = (
        _build_fixture(tmp_path, monkeypatch)
    )

    result = admission.build_finbench_confirmatory_selection_admission(
        confirmatory_workload_root=confirmatory_root,
        correctness_run_root=correctness_root,
        correctness_audit=audit_path,
        correctness_expected_commit=COMMIT,
        correctness_receipt=receipt_path,
    )
    validated = admission.validate_finbench_confirmatory_selection_admission(
        result, workload_sha256=CONFIRMATORY_WORKLOAD_SHA256
    )

    assert validated == result
    assert result["admitted_family_ids"] == [
        "f1_direct_transfer_control",
        "f2_temporal_path_control",
    ]
    assert result["development_correctness_evidence"][
        "correctness_workload_sha256"
    ] == CORRECTNESS_WORKLOAD_SHA256
    assert result["current_confirmatory_query_oracle_opened"] is False
    assert result["final_confirmatory_oracle_is_authoritative"] is True
    assert result["backend_calls"] == 0
    assert result["current_query_profile_calls"] == 0


def test_selection_admission_rejects_changed_source_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    correctness_root, confirmatory_root, audit_path, receipt_path = (
        _build_fixture(tmp_path, monkeypatch)
    )
    receipt = json.loads(receipt_path.read_text())
    receipt["source_artifact"]["archive_sha256"] = "f" * 64
    receipt_path.write_text(json.dumps(receipt))

    with pytest.raises(
        admission.FinBenchConfirmatorySelectionAdmissionError,
        match="receipt does not bind",
    ):
        admission.build_finbench_confirmatory_selection_admission(
            confirmatory_workload_root=confirmatory_root,
            correctness_run_root=correctness_root,
            correctness_audit=audit_path,
            correctness_expected_commit=COMMIT,
            correctness_receipt=receipt_path,
        )
