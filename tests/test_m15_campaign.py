from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from xgap.experiments.m15_campaign import (
    CAMPAIGN_PLAN_SCHEMA_VERSION,
    M15CampaignError,
    M15CampaignSpec,
    compile_m15_campaign,
    compile_m15_campaign_file,
    main,
    write_m15_campaign_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "experiments/configs/m15_f2_campaign_dev.json"


def _payload() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_campaign_compiles_balanced_schedule_without_external_calls() -> None:
    plan = compile_m15_campaign_file(CONFIG, repo_root=REPO_ROOT).to_dict()

    assert plan["schema_version"] == CAMPAIGN_PLAN_SCHEMA_VERSION
    assert plan["expected_counts"] == {
        "workloads": 2,
        "workload_query_contexts": 2,
        "blocks_per_workload": 1,
        "sessions": 12,
        "method_streams": 72,
        "common_calibration_profile_calls": 36,
        "warmup_query_attempts": 0,
        "measured_query_attempts": 72,
    }
    validation = plan["design_validation"]
    assert validation["passed"] is True
    for stratum in validation["strata"]:
        assert stratum["sequence_count"] == 6
        assert stratum["position_balance_passed"] is True
        assert stratum["first_order_carryover_balance_passed"] is True
        assert set(stratum["ordered_carryover_counts"].values()) == {1}
        assert all(
            counts == [1, 1, 1, 1, 1, 1]
            for counts in stratum["position_counts"].values()
        )

    boundary = plan["claim_boundary"]
    assert boundary["backend_calls_made"] == 0
    assert boundary["llm_calls_made"] == 0
    assert boundary["ontology_calls_made"] == 0
    assert boundary["contains_measurements"] is False
    assert boundary["paper_comparison_ready"] is False
    assert boundary["paper_result"] is False
    assert "fewer_than_30_distinct_workload_query_contexts" in (
        boundary["blocking_conditions"]
    )
    assert "inferential_analysis_not_preregistered" in (
        boundary["blocking_conditions"]
    )
    assert "at_least_one_workload_has_no_multi_task_memory_stream" in (
        boundary["blocking_conditions"]
    )
    assert plan["automatic_retries"] == 0
    assert plan["paper_result"] is False


def test_campaign_is_stable_and_seed_changes_only_the_valid_design() -> None:
    spec = M15CampaignSpec.from_json(CONFIG)
    first = compile_m15_campaign(spec, repo_root=REPO_ROOT).to_dict()
    second = compile_m15_campaign(spec, repo_root=REPO_ROOT).to_dict()
    changed = compile_m15_campaign(
        replace(spec, design_seed="xgap-m15-f2-alternate-seed"),
        repo_root=REPO_ROOT,
    ).to_dict()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["campaign_spec_sha256"] == second["campaign_spec_sha256"]
    assert first["schedule_sha256"] == second["schedule_sha256"]
    assert first["schedule_sha256"] != changed["schedule_sha256"]
    assert changed["design_validation"]["passed"] is True


def test_schedule_hash_binds_workload_spec_content(tmp_path: Path) -> None:
    config = tmp_path / "experiments/configs/m15_f2_campaign_dev.json"
    config.parent.mkdir(parents=True)
    shutil.copyfile(CONFIG, config)
    for name in ("m15_f0_selective.json", "m15_f0_broad_hot.json"):
        shutil.copyfile(
            REPO_ROOT / "experiments/configs" / name,
            config.parent / name,
        )
    before = compile_m15_campaign_file(config, repo_root=tmp_path).to_dict()
    selective = config.parent / "m15_f0_selective.json"
    payload = json.loads(selective.read_text(encoding="utf-8"))
    payload["seed"] = "content-drift-must-change-schedule-hash"
    selective.write_text(json.dumps(payload), encoding="utf-8")
    after = compile_m15_campaign_file(config, repo_root=tmp_path).to_dict()

    assert before["campaign_spec_sha256"] == after["campaign_spec_sha256"]
    assert before["schedule_sha256"] != after["schedule_sha256"]
    assert before["workload_inputs"] != after["workload_inputs"]


def test_campaign_ids_namespaces_and_dispatch_positions_are_unique() -> None:
    plan = compile_m15_campaign_file(CONFIG, repo_root=REPO_ROOT).to_dict()
    sessions = plan["sessions"]

    assert [item["dispatch_index"] for item in sessions] == list(range(1, 13))
    assert len({item["session_id"] for item in sessions}) == 12
    namespaces = [
        stream["memory_namespace"]
        for session in sessions
        for stream in session["method_streams"]
    ]
    measured = [
        run_id
        for session in sessions
        for stream in session["method_streams"]
        for run_id in stream["measured_run_ids"]
    ]
    assert len(namespaces) == len(set(namespaces)) == 72
    assert len(measured) == len(set(measured)) == 72
    assert all(session["automatic_retries"] == 0 for session in sessions)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["methods"].pop(),
            "six frozen M15 methods",
        ),
        (
            lambda value: value["protocol"].update(
                {"failure_policy": "retry_once"}
            ),
            "failure_policy",
        ),
        (
            lambda value: value.update({"paper_result": True}),
            "paper_result=false",
        ),
        (
            lambda value: value["protocol"].update(
                {"measured_runs_per_method_per_sequence": 2}
            ),
            "must be between 1 and 1",
        ),
        (
            lambda value: value["analysis"].update(
                {"inferential_analysis": "preregistered_external_artifact"}
            ),
            "unfrozen_requires_author_approval in the v1 schema",
        ),
    ],
)
def test_campaign_rejects_method_or_protocol_drift(mutate, message: str) -> None:
    value = _payload()
    mutate(value)
    with pytest.raises(M15CampaignError, match=message):
        M15CampaignSpec.from_dict(value)


def test_campaign_binds_workload_files_and_rejects_path_escape() -> None:
    plan = compile_m15_campaign_file(CONFIG, repo_root=REPO_ROOT).to_dict()
    assert all(
        len(item["spec_sha256"]) == 64 for item in plan["workload_inputs"]
    )
    assert all(
        len(item["bundle_spec_sha256"]) == 64
        for item in plan["workload_inputs"]
    )

    value = _payload()
    value["workloads"][0]["spec_path"] = "../outside.json"
    with pytest.raises(M15CampaignError, match="repository-relative"):
        M15CampaignSpec.from_dict(value)


def test_campaign_rejects_symlinked_workload_spec(tmp_path: Path) -> None:
    spec = M15CampaignSpec.from_json(CONFIG)
    linked = tmp_path / "linked-workload.json"
    linked.symlink_to(
        REPO_ROOT / spec.workloads[0].spec_path,
        target_is_directory=False,
    )
    isolated = replace(
        spec,
        workloads=(
            replace(spec.workloads[0], spec_path=linked.name),
        ),
    )

    with pytest.raises(M15CampaignError, match="must not be a symlink"):
        compile_m15_campaign(isolated, repo_root=tmp_path)


def test_campaign_respects_expansion_budget() -> None:
    spec = M15CampaignSpec.from_json(CONFIG)
    with pytest.raises(M15CampaignError, match="exceeding max_sessions"):
        compile_m15_campaign(
            replace(spec, max_sessions=11),
            repo_root=REPO_ROOT,
        )


def test_campaign_plan_write_is_immutable(tmp_path: Path) -> None:
    plan = compile_m15_campaign_file(CONFIG, repo_root=REPO_ROOT)
    destination = tmp_path / "campaign-plan.json"
    write_m15_campaign_plan(plan, destination)
    loaded = json.loads(destination.read_text(encoding="utf-8"))
    assert loaded["schedule_sha256"] == plan.schedule_hash

    with pytest.raises(FileExistsError, match="already exists"):
        write_m15_campaign_plan(plan, destination)


def test_campaign_cli_compiles_without_writing_by_default(capsys) -> None:
    assert main(
        ["--config", str(CONFIG), "--repo-root", str(REPO_ROOT)]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claim_boundary"]["backend_calls_made"] == 0
    assert payload["paper_result"] is False
