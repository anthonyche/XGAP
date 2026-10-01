from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from xgap.experiments.m15_executable_family_registry import (
    EXECUTABLE_FAMILY_PACKAGE_SCHEMA_VERSION,
    EXECUTABLE_FAMILY_PLAN_SCHEMA_VERSION,
    M15ExecutableFamilyRegistryError,
    compile_m15_executable_family_registry,
    compile_m15_executable_family_registry_file,
    main,
    write_m15_executable_family_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = (
    REPO_ROOT / "experiments/configs/m15_f2c14_executable_family_registry_dev.json"
)


def _payload() -> dict[str, object]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _copy_sources(tmp_path: Path, payload: dict[str, object]) -> None:
    for source in payload["families"][0]["sources"].values():
        relative = Path(source["path"])
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)


def test_registry_reconstructs_current_executable_family() -> None:
    plan = compile_m15_executable_family_registry_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()

    assert plan["schema_version"] == EXECUTABLE_FAMILY_PLAN_SCHEMA_VERSION
    assert plan["summary"] == {
        "executable_family_count": 1,
        "seen_family_count": 1,
        "heldout_family_count": 0,
        "base_query_instance_count": 6,
        "direct_semantic_task_count": 28,
        "physical_candidate_count": 56,
    }
    package = plan["families"][0]
    assert package["schema_version"] == EXECUTABLE_FAMILY_PACKAGE_SCHEMA_VERSION
    assert package["family_id"] == "financial-risk-transfer-to-company"
    assert package["typed_semantic_program"]["operator_kind_counts"] == {
        "align": 2,
        "join": 1,
        "match": 2,
        "project": 1,
        "traverse": 1,
    }
    assert package["typed_semantic_program"]["hard_constraint_ids"] == [
        "amount-lower-bound",
        "resolved-person-identity",
        "time-lower-bound",
    ]
    assert package["typed_semantic_program"]["relaxable_constraint_ids"] == [
        "path-shape",
        "risk-level",
        "transfer-predicate",
    ]
    assert package["backend_artifacts"]["registered_templates_bound"] is True
    assert package["workload"]["per_instance_source_and_final_oracles_bound"] is True
    assert package["semantic_workload"]["counts"]["training_semantic_tasks"] == 18
    assert package["semantic_workload"]["counts"]["heldout_semantic_tasks"] == 10
    assert package["family_memory"]["current_query_observation_operations"] == []
    assert package["claim_boundary"]["backend_calls_made"] == 0
    assert package["claim_boundary"]["llm_calls_made"] == 0
    assert package["claim_boundary"]["ontology_service_calls_made"] == 0
    assert package["paper_result"] is False


def test_agent_environment_tools_and_actions_are_explicit() -> None:
    plan = compile_m15_executable_family_registry_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()
    contract = plan["agent_contract"]

    assert {item["backend_id"] for item in contract["environment"]["backends"]} == {
        "neo4j",
        "fuseki",
    }
    assert all(
        item["boundary"] == "black_box_public_interface"
        for item in contract["environment"]["backends"]
    )
    assert {"catalog", "llm", "ontology"}.issubset(
        contract["environment"]["optional_inputs"]
    )
    assert {item["tool_id"] for item in contract["tools"]} == {
        "backend.execute.neo4j",
        "backend.execute.fuseki",
        "coordinator.federate",
        "memory.family",
        "semantic.direct",
    }
    assert "inspect_backend_internals" in contract["forbidden_actions"]
    assert "change_hard_constraints" in contract["forbidden_actions"]
    assert "retry_automatically" in contract["forbidden_actions"]


def test_only_real_population_and_analysis_blockers_remain() -> None:
    plan = compile_m15_executable_family_registry_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    ).to_dict()

    assert plan["paper_readiness"] == {
        "ready": False,
        "blockers": [
            "fewer_than_target_executable_query_families",
            "fewer_than_target_base_query_instances",
            "no_executable_held_out_query_family",
            "inferential_analysis_not_preregistered",
        ],
    }
    stale_blockers = {
        "typed_semantic_operator_dag_not_yet_bound",
        "backend_query_template_structure_not_yet_bound",
        "query_instances_not_yet_bound_to_workload_contracts_and_oracles",
    }
    assert stale_blockers.isdisjoint(plan["paper_readiness"]["blockers"])
    assert plan["claim_boundary"]["future_domains_selected"] is False
    assert plan["paper_result"] is False


def test_source_drift_fails_before_reconstruction(tmp_path: Path) -> None:
    payload = _payload()
    _copy_sources(tmp_path, payload)
    workload_path = tmp_path / payload["families"][0]["sources"]["workload_spec"][
        "path"
    ]
    workload_path.write_text(
        workload_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(M15ExecutableFamilyRegistryError, match="source SHA-256"):
        compile_m15_executable_family_registry(payload, repo_root=tmp_path)


def test_generated_hash_or_count_drift_fails_closed() -> None:
    for field, changed in (
        ("direct_manifest_sha256", "0" * 64),
        ("direct_semantic_tasks", 29),
    ):
        payload = _payload()
        payload["families"][0]["expected"][field] = changed
        with pytest.raises(
            M15ExecutableFamilyRegistryError,
            match="generated package drift",
        ):
            compile_m15_executable_family_registry(payload, repo_root=REPO_ROOT)


def test_duplicate_family_and_false_heldout_family_fail_closed() -> None:
    duplicate = _payload()
    duplicate["families"].append(copy.deepcopy(duplicate["families"][0]))
    with pytest.raises(M15ExecutableFamilyRegistryError, match="family IDs"):
        compile_m15_executable_family_registry(duplicate, repo_root=REPO_ROOT)

    false_heldout = _payload()
    false_heldout["families"][0]["evaluation_role"] = "held_out_family"
    with pytest.raises(
        M15ExecutableFamilyRegistryError,
        match="must not expose family-local training tasks",
    ):
        compile_m15_executable_family_registry(false_heldout, repo_root=REPO_ROOT)


def test_plan_is_deterministic_and_output_never_overwrites(tmp_path: Path) -> None:
    first = compile_m15_executable_family_registry_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    )
    second = compile_m15_executable_family_registry_file(
        REGISTRY,
        repo_root=REPO_ROOT,
    )
    assert first.to_dict() == second.to_dict()
    assert len(first.plan_hash) == 64

    output = tmp_path / "plan.json"
    write_m15_executable_family_plan(first, output)
    assert json.loads(output.read_text(encoding="utf-8")) == first.to_dict()
    with pytest.raises(FileExistsError):
        write_m15_executable_family_plan(first, output)
    with pytest.raises(FileExistsError):
        main(
            [
                "--registry",
                str(REGISTRY),
                "--repo-root",
                str(REPO_ROOT),
                "--output",
                str(output),
            ]
        )
