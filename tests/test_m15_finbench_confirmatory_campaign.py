from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from xgap.experiments.hashing import content_hash
from xgap.experiments import m15_finbench_confirmatory_campaign as campaign
from xgap.experiments import m15_finbench_confirmatory_campaign_evidence as evidence


PHASES = {
    "crossfit_training_measurement": [
        f"crossfit_training_measurement-block-{index:02d}"
        for index in range(1, 8)
    ],
    "current_query_profile_acquisition": [
        "current_query_profile_acquisition-block-01"
    ],
    "paired_selected_serving": [
        f"paired_selected_serving-block-{index:02d}"
        for index in range(1, 8)
    ],
    "postselection_shadow_evaluation": [
        f"postselection_shadow_evaluation-block-{index:02d}"
        for index in range(1, 8)
    ],
}
COMMIT = "d" * 40


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _base_manifest() -> dict:
    body = {
        "schema_version": campaign.FINBENCH_CONFIRMATORY_CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": "m15-finbench-confirmatory-test",
        "schedule_sha256": "a" * 64,
        "workload_sha256": "b" * 64,
        "selection_admission_sha256": "c" * 64,
        "execution_request_sha256": "e" * 64,
        "execution_authority_sha256": "f" * 64,
        "runner_commit": COMMIT,
        "measurement_blocks": copy.deepcopy(PHASES),
        "measurement_block_count": 22,
        "total_plan_runs": 1888,
        "maximum_backend_calls": 3776,
        "staging_order": [
            [
                "crossfit_training_measurement",
                "current_query_profile_acquisition",
            ],
            ["selection_assembly"],
            [
                "paired_selected_serving",
                "postselection_shadow_evaluation",
            ],
            ["delayed_oracle"],
            ["independent_campaign_audit"],
        ],
        "fresh_job_owned_services_per_measurement_block": True,
        "current_confirmatory_query_oracle_opened": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    body["campaign_manifest_sha256"] = content_hash(body)
    return body


def _context(block_id: str, *, sealed: bool) -> dict:
    phase = block_id.rsplit("-block-", maxsplit=1)[0]
    body = {
        "block_attempt": {
            "attempt_id": "attempt-" + content_hash(block_id)[:16],
            "measurement_block_id": block_id,
            "phase": phase,
            "attempt_index": 1,
            "replacement_of_attempt_id": None,
        },
        "sealed": sealed,
    }
    body["execution_context_sha256"] = content_hash(body)
    return body


def _accepted(block_id: str) -> tuple[dict, dict]:
    count = 64 if block_id.startswith("crossfit") else 96
    audit = {
        "success": True,
        "failed_check_ids": [],
        "attempt_status": "completed",
        "replacement_eligible": False,
        "audit_sha256": content_hash({"block_id": block_id, "audit": True}),
    }
    accepted = {
        "execution_context": {
            "block_attempt": {"attempt_index": 1},
        },
        "raw_measurements": {"measurement_count": count},
        "accepted_block_sha256": content_hash(
            {"block_id": block_id, "accepted": True}
        ),
    }
    return audit, accepted


def _patch_builders(monkeypatch) -> tuple[dict, dict]:
    base = _base_manifest()
    monkeypatch.setattr(
        campaign,
        "build_finbench_confirmatory_campaign_manifest",
        lambda **_kwargs: copy.deepcopy(base),
    )
    monkeypatch.setattr(
        campaign,
        "_git_state",
        lambda _root: {"commit": COMMIT, "clean": True},
    )
    monkeypatch.setattr(
        campaign,
        "validate_finbench_confirmatory_block_execution_envelope",
        lambda value: copy.deepcopy(value),
    )
    monkeypatch.setattr(
        campaign,
        "_build_context",
        lambda *, block_id, family_selection_seal=None,
        profile_selection_seal=None, **_kwargs: _context(
            block_id,
            sealed=(
                family_selection_seal is not None
                and profile_selection_seal is not None
            ),
        ),
    )
    training = {
        "family_selection_seal": {"sealed": "family"},
        "crossfit_prediction_suite": {"measurement_source_id": "source"},
    }
    training["training_phase_sha256"] = content_hash(training)
    profile = {"profile_selection_seal": {"sealed": "profile"}}
    profile["profile_phase_sha256"] = content_hash(profile)
    monkeypatch.setattr(
        campaign,
        "build_finbench_confirmatory_training_phase",
        lambda **_kwargs: copy.deepcopy(training),
    )
    monkeypatch.setattr(
        campaign,
        "build_finbench_confirmatory_profile_phase",
        lambda **_kwargs: copy.deepcopy(profile),
    )
    monkeypatch.setattr(
        campaign,
        "reconstruct_finbench_confirmatory_completed_block",
        lambda *, block_id, **_kwargs: copy.deepcopy(_accepted(block_id)),
    )
    return training, profile


def _workspace(tmp_path: Path, monkeypatch) -> tuple[Path, Path, dict, dict]:
    training, profile = _patch_builders(monkeypatch)
    repo = tmp_path / "repo"
    freeze = tmp_path / "freeze"
    root = tmp_path / "campaign"
    _json(repo / "pyproject.toml", {})
    values = {
        "run_manifest.json": {"freeze": "manifest"},
        "measurement_schedule.json": {"schedule": True},
    }
    for filename, value in values.items():
        _json(freeze / filename, value)
    external = {}
    for name in (
        "freeze-audit",
        "selection-admission",
        "execution-request",
        "execution-authority",
    ):
        path = tmp_path / f"{name}.json"
        _json(path, {name: True})
        external[name] = path
    campaign.initialize_finbench_confirmatory_campaign_workspace(
        campaign_root=root,
        freeze_run_root=freeze,
        freeze_audit_path=external["freeze-audit"],
        selection_admission_path=external["selection-admission"],
        execution_request_path=external["execution-request"],
        execution_authority_path=external["execution-authority"],
        repo_root=repo,
    )
    return root, repo, training, profile


def test_campaign_stages_selection_before_later_contexts(
    tmp_path: Path, monkeypatch
) -> None:
    root, _repo, _training, _profile = _workspace(tmp_path, monkeypatch)
    initial_contexts = sorted((root / "contexts").glob("*.json"))
    assert len(initial_contexts) == 8
    assert all(
        "paired_selected" not in item.name
        and "postselection_shadow" not in item.name
        for item in initial_contexts
    )

    checkpoint = campaign.assemble_finbench_confirmatory_selection_workspace(
        campaign_root=root
    )

    assert len(list((root / "accepted-blocks").glob("*.json"))) == 8
    assert len(list((root / "contexts").glob("*.json"))) == 22
    assert len(checkpoint["postselection_execution_context_sha256s"]) == 14
    assert checkpoint["current_confirmatory_query_oracle_opened"] is False
    assert checkpoint["backend_calls_during_assembly"] == 0


def test_complete_campaign_is_admitted_only_by_independent_audit(
    tmp_path: Path, monkeypatch
) -> None:
    root, repo, training, profile = _workspace(tmp_path, monkeypatch)
    checkpoint = campaign.assemble_finbench_confirmatory_selection_workspace(
        campaign_root=root
    )
    manifest = json.loads((root / "campaign_manifest.json").read_text())
    oracle = {
        "schedule_sha256": manifest["schedule_sha256"],
        "workload_sha256": manifest["workload_sha256"],
        "selection_admission_sha256": manifest[
            "selection_admission_sha256"
        ],
        "execution_request_sha256": manifest["execution_request_sha256"],
        "execution_authority_sha256": manifest[
            "execution_authority_sha256"
        ],
        "training_phase_sha256": training["training_phase_sha256"],
        "profile_phase_sha256": profile["profile_phase_sha256"],
        "status": "success",
        "all_successful_measurements_exact": True,
        "query_timeout_count": 0,
        "analysis": {"confirmatory_statistics": True},
        "paper_result": False,
    }
    oracle["oracle_gate_sha256"] = content_hash(oracle)
    monkeypatch.setattr(
        campaign,
        "open_finbench_confirmatory_oracle",
        lambda **_kwargs: copy.deepcopy(oracle),
    )
    result = campaign.finalize_finbench_confirmatory_campaign_workspace(
        campaign_root=root
    )
    assert result["status"] == "success"
    assert result["paper_result"] is False
    assert len(list((root / "accepted-blocks").glob("*.json"))) == 22
    campaign.record_finbench_confirmatory_submission(
        campaign_root=root,
        training_job_id="1001",
        profile_job_id="1002",
        selection_job_id="1003",
        serving_job_id="1004",
        shadow_job_id="1005",
        finalize_job_id="1006",
        audit_job_id="1007",
    )

    inputs = {
        name: json.loads((root / "inputs" / filename).read_text())
        for name, filename in campaign._INPUT_FILES.items()
    }
    monkeypatch.setattr(
        evidence,
        "_load_workspace",
        lambda _root: (copy.deepcopy(manifest), copy.deepcopy(inputs)),
    )
    monkeypatch.setattr(
        evidence,
        "_git_state",
        lambda _root: {"commit": COMMIT, "clean": True},
    )
    monkeypatch.setattr(
        evidence,
        "build_finbench_confirmatory_campaign_manifest",
        lambda **_kwargs: copy.deepcopy(_base_manifest()),
    )
    monkeypatch.setattr(evidence, "_build_context", campaign._build_context)
    monkeypatch.setattr(
        evidence,
        "reconstruct_finbench_confirmatory_completed_block",
        campaign.reconstruct_finbench_confirmatory_completed_block,
    )
    monkeypatch.setattr(
        evidence,
        "build_finbench_confirmatory_training_phase",
        lambda **_kwargs: copy.deepcopy(training),
    )
    monkeypatch.setattr(
        evidence,
        "build_finbench_confirmatory_profile_phase",
        lambda **_kwargs: copy.deepcopy(profile),
    )
    monkeypatch.setattr(
        evidence,
        "open_finbench_confirmatory_oracle",
        lambda **_kwargs: copy.deepcopy(oracle),
    )
    audit = evidence.audit_finbench_confirmatory_campaign(
        campaign_root=root,
        repo_root=repo,
        expected_commit=COMMIT,
    ).to_dict()

    assert audit["success"] is True
    assert audit["failed_check_ids"] == []
    assert audit["run_tree_mutated"] is False
    assert audit["confirmatory_result_admitted"] is True
    assert audit["paper_result"] is True
    accepted_check = next(
        item
        for item in audit["checks"]
        if item["check_id"].endswith("accepted_reconstruction")
    )
    assert accepted_check["expected"]["value_type"] == "mapping"
    assert accepted_check["observed"]["value_type"] == "mapping"
    assert "raw_measurements" not in json.dumps(accepted_check)


def test_invalidated_campaign_never_becomes_paper_result() -> None:
    audit = evidence.FinBenchConfirmatoryCampaignAudit(
        campaign_root=Path("/tmp/campaign"),
        expected_commit=COMMIT,
        campaign_id="campaign",
        campaign_status="invalidated_by_answer_oracle",
        source_campaign_result_sha256="a" * 64,
        checks=(),
        run_tree_mutated=False,
    ).to_dict()
    assert audit["success"] is True
    assert audit["confirmatory_result_admitted"] is False
    assert audit["paper_result"] is False


def test_campaign_audit_checks_do_not_retain_large_equal_payloads() -> None:
    payload = {
        "schema_version": "large-test-v1",
        "raw_measurements_sha256": "a" * 64,
        "measurements": [
            {"canonical_rows": [{"value": "x" * 4096}]} for _ in range(16)
        ],
    }

    compact = evidence._compact_check_value(payload)

    assert compact == {
        "value_type": "mapping",
        "entry_count": 3,
        "identity_fields": {
            "raw_measurements_sha256": "a" * 64,
            "schema_version": "large-test-v1",
        },
    }
    assert "measurements" not in compact


def test_later_auditor_keeps_code_and_frozen_evidence_checkouts_separate() -> None:
    script = (
        Path(__file__).parents[1]
        / "scripts/slurm/run_m15_finbench_confirmatory_campaign_later_audit.sbatch"
    ).read_text(encoding="utf-8")

    assert "#SBATCH --mem=32G" in script
    assert "XGAP_AUDITOR_REPO_ROOT" in script
    assert "XGAP_EVIDENCE_REPO_ROOT" in script
    assert "XGAP_CONFIRMATORY_AUDITOR_COMMIT" in script
    assert 'PYTHONPATH="$AUDITOR_ROOT/src"' in script
    assert '--repo-root "$EVIDENCE_ROOT"' in script
    assert 'git -C "$AUDITOR_ROOT" rev-parse HEAD' in script
    assert 'git -C "$EVIDENCE_ROOT" rev-parse HEAD' in script


def test_only_audited_zero_measurement_failure_can_mint_attempt_two(
    tmp_path: Path, monkeypatch
) -> None:
    root, _repo, _training, _profile = _workspace(tmp_path, monkeypatch)
    block_id = PHASES["crossfit_training_measurement"][0]
    initial = json.loads((root / "contexts" / f"{block_id}.json").read_text())
    attempt_root = (
        root
        / "block-runs"
        / block_id
        / "attempt-1"
        / "native-service-run"
        / initial["block_attempt"]["attempt_id"]
    )
    _json(attempt_root / "raw_measurements.json", {"measurements": []})
    audit = {
        "success": True,
        "failed_check_ids": [],
        "attempt_status": "infrastructure_failed",
        "replacement_eligible": True,
        "valid_measurement_count": 0,
        "failure_category": "infrastructure_failure",
        "audit_sha256": "1" * 64,
    }
    monkeypatch.setattr(
        campaign,
        "audit_finbench_confirmatory_block",
        lambda **_kwargs: SimpleNamespace(to_dict=lambda: copy.deepcopy(audit)),
    )
    failed = {"failed_attempt_sha256": "2" * 64}
    monkeypatch.setattr(
        campaign,
        "build_finbench_confirmatory_failed_attempt_bundle",
        lambda **_kwargs: copy.deepcopy(failed),
    )
    attempt_two = {
        "attempt_id": "attempt-two",
        "measurement_block_id": block_id,
        "phase": "crossfit_training_measurement",
        "attempt_index": 2,
        "replacement_of_attempt_id": initial["block_attempt"]["attempt_id"],
    }
    monkeypatch.setattr(
        campaign,
        "compile_finbench_confirmatory_block_attempt",
        lambda **_kwargs: copy.deepcopy(attempt_two),
    )
    replacement_context = {"block_attempt": attempt_two}
    replacement_context["execution_context_sha256"] = content_hash(
        replacement_context
    )
    monkeypatch.setattr(
        campaign,
        "build_finbench_confirmatory_block_execution_envelope",
        lambda **_kwargs: copy.deepcopy(replacement_context),
    )

    replacement = campaign.prepare_finbench_confirmatory_replacement_workspace(
        campaign_root=root, block_id=block_id
    )

    assert replacement["replacement_limit_consumed"] == 1
    assert replacement["automatic_retries"] == 0
    assert (root / "contexts" / f"{block_id}-attempt-2.json").is_file()
    record, selected, prior = campaign._replacement(
        root, block_id, expected_commit=COMMIT
    )
    assert record == replacement
    assert selected == replacement_context
    assert prior == [failed]
    try:
        campaign.prepare_finbench_confirmatory_replacement_workspace(
            campaign_root=root, block_id=block_id
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("a second replacement must be rejected")


def test_submission_scripts_encode_one_way_dependencies_and_no_retry() -> None:
    root = Path(__file__).resolve().parents[1]
    submit = (
        root / "scripts/server/submit_m15_finbench_confirmatory_campaign.sh"
    ).read_text(encoding="utf-8")
    block = (
        root
        / "scripts/slurm/run_m15_finbench_confirmatory_campaign_block.sbatch"
    ).read_text(encoding="utf-8")

    assert "--array=1-7%1" in submit
    assert "--dependency=afterok:" in submit
    assert "--dependency=afterany:" in submit
    assert "--begin=now+2minutes" in submit
    assert "--requeue" not in submit
    assert "retry" not in submit.lower()
    assert "SLURM_ARRAY_TASK_ID" in block
    assert "attempt-$ATTEMPT_INDEX" in block
    assert "XGAP_CONFIRMATORY_ATTEMPT_INDEX" in block
    assert "run_m15_native_finbench_confirmatory_block.sbatch" in block
