from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from xgap.experiments.m15_query_bound_campaign import (
    QUERY_BOUND_CAMPAIGN_PLAN_SCHEMA_VERSION,
    M15QueryBoundCampaignError,
    M15QueryBoundCampaignRegistry,
    compile_m15_query_bound_campaign_file,
    main,
    write_m15_query_bound_campaign_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = (
    REPO_ROOT / "experiments/configs/m15_f2_query_bound_campaign_dev.json"
)


def _payload() -> dict[str, object]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_query_bound_campaign_freezes_every_workload_query_contract() -> None:
    plan = compile_m15_query_bound_campaign_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()

    assert plan["schema_version"] == QUERY_BOUND_CAMPAIGN_PLAN_SCHEMA_VERSION
    assert plan["base_campaign"] == {
        "config_path": "experiments/configs/m15_f2_campaign_dev.json",
        "campaign_spec_sha256": (
            "3669a8909943a4106a5f7a2bf0bd98d24715d08e53d3997336bb163bd2dd973a"
        ),
        "schedule_sha256": (
            "fbc3e216d532ae59c4ada45fe9605ff9e3ba4b86371ebddc46a8c76803f7e154"
        ),
        "plan_schema_version": "m15-f2-campaign-plan-v1",
    }
    assert len(plan["query_bindings"]) == 2
    assert plan["expected_counts"]["query_contract_bindings"] == 2
    assert len(plan["sessions"]) == 12
    assert all(
        len(session["query_contract_refs"]) == 1
        for session in plan["sessions"]
    )
    assert all(
        stream["query_contract_refs"] == session["query_contract_refs"]
        for session in plan["sessions"]
        for stream in session["method_streams"]
    )
    assert plan["design_validation"]["passed"] is True
    assert len(plan["query_binding_sha256"]) == 64
    assert len(plan["query_bound_schedule_sha256"]) == 64
    boundary = plan["claim_boundary"]
    assert boundary["query_specs_hash_bound"] is True
    assert boundary["expected_query_contract_hashes_frozen"] is True
    assert boundary["live_bundle_contracts_verified"] is False
    assert boundary["backend_calls_made"] == 0
    assert boundary["llm_calls_made"] == 0
    assert boundary["ontology_calls_made"] == 0
    assert boundary["paper_result"] is False
    assert plan["automatic_retries"] == 0
    assert plan["paper_result"] is False


def test_query_bound_campaign_is_deterministic() -> None:
    first = compile_m15_query_bound_campaign_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()
    second = compile_m15_query_bound_campaign_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()

    assert first == second


def test_bound_schedule_is_portable_across_query_spec_paths(
    tmp_path: Path,
) -> None:
    config_root = tmp_path / "experiments/configs"
    config_root.mkdir(parents=True)
    for filename in (
        "m15_f2_campaign_dev.json",
        "m15_f0_selective.json",
        "m15_f0_broad_hot.json",
    ):
        shutil.copyfile(
            REPO_ROOT / "experiments/configs" / filename,
            config_root / filename,
        )
    original_query = (
        REPO_ROOT / "experiments/configs/m15_f2_query_contract_dev.json"
    )
    shutil.copyfile(original_query, config_root / "query-one.json")
    shutil.copyfile(original_query, config_root / "query-two.json")

    payload = _payload()
    for binding in payload["bindings"]:
        binding["query_spec_path"] = "experiments/configs/query-one.json"
    first_registry = tmp_path / "first-registry.json"
    first_registry.write_text(json.dumps(payload), encoding="utf-8")
    first = compile_m15_query_bound_campaign_file(
        first_registry,
        repo_root=tmp_path,
    ).to_dict()

    for binding in payload["bindings"]:
        binding["query_spec_path"] = "experiments/configs/query-two.json"
    second_registry = tmp_path / "second-registry.json"
    second_registry.write_text(json.dumps(payload), encoding="utf-8")
    second = compile_m15_query_bound_campaign_file(
        second_registry,
        repo_root=tmp_path,
    ).to_dict()

    assert first["registry_spec_sha256"] != second["registry_spec_sha256"]
    assert first["query_binding_sha256"] == second["query_binding_sha256"]
    assert (
        first["query_bound_schedule_sha256"]
        == second["query_bound_schedule_sha256"]
    )
    assert first["sessions"] == second["sessions"]


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("expected_base_campaign_spec_sha256", "campaign spec hash drifted"),
        ("expected_base_schedule_sha256", "campaign schedule hash drifted"),
    ],
)
def test_query_bound_campaign_rejects_base_hash_drift(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    payload = _payload()
    payload[field] = "0" * 64
    registry = tmp_path / "drifted-registry.json"
    registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(M15QueryBoundCampaignError, match=message):
        compile_m15_query_bound_campaign_file(registry, repo_root=REPO_ROOT)


def test_query_bound_campaign_rejects_query_spec_hash_drift(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["bindings"][0]["expected_query_spec_sha256"] = "0" * 64
    registry = tmp_path / "drifted-registry.json"
    registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(M15QueryBoundCampaignError, match="query spec hash drifted"):
        compile_m15_query_bound_campaign_file(registry, repo_root=REPO_ROOT)


def test_query_bound_campaign_requires_exact_binding_coverage(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["bindings"].pop()
    registry = tmp_path / "incomplete-registry.json"
    registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(M15QueryBoundCampaignError, match="cover.*exactly"):
        compile_m15_query_bound_campaign_file(registry, repo_root=REPO_ROOT)


def test_query_bound_registry_rejects_retry_or_paper_promotion() -> None:
    retry = _payload()
    retry["automatic_retries"] = 1
    with pytest.raises(M15QueryBoundCampaignError, match="disable.*retries"):
        M15QueryBoundCampaignRegistry.from_dict(retry)

    paper = _payload()
    paper["paper_result"] = True
    with pytest.raises(M15QueryBoundCampaignError, match="paper_result=false"):
        M15QueryBoundCampaignRegistry.from_dict(paper)


def test_query_bound_campaign_rejects_symlinked_registry(tmp_path: Path) -> None:
    registry = tmp_path / "linked-registry.json"
    registry.symlink_to(REGISTRY)

    with pytest.raises(M15QueryBoundCampaignError, match="must not be a symlink"):
        compile_m15_query_bound_campaign_file(registry, repo_root=REPO_ROOT)


def test_query_bound_plan_write_is_immutable(tmp_path: Path) -> None:
    plan = compile_m15_query_bound_campaign_file(REGISTRY, repo_root=REPO_ROOT)
    output = tmp_path / "query-bound-plan.json"
    write_m15_query_bound_campaign_plan(plan, output)
    assert json.loads(output.read_text(encoding="utf-8")) == plan.to_dict()

    with pytest.raises(FileExistsError, match="exists"):
        write_m15_query_bound_campaign_plan(plan, output)


def test_query_bound_campaign_cli_is_side_effect_free_by_default(capsys) -> None:
    assert main(
        ["--registry", str(REGISTRY), "--repo-root", str(REPO_ROOT)]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claim_boundary"]["backend_calls_made"] == 0
    assert payload["claim_boundary"]["live_bundle_contracts_verified"] is False
    assert payload["paper_result"] is False
