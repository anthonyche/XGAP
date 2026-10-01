from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from xgap.experiments.m15_query_family import (
    QUERY_FAMILY_PLAN_SCHEMA_VERSION,
    M15QueryFamilyError,
    compile_m15_query_family_file,
    main,
    write_m15_query_family_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "experiments/configs/m15_f2c_query_families_dev.json"
QUERY_SPEC = REPO_ROOT / "experiments/configs/m15_f2_query_contract_dev.json"


def _payload() -> dict[str, object]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _temp_registry(tmp_path: Path) -> tuple[dict[str, object], Path]:
    payload = _payload()
    query_path = tmp_path / "queries/alice.json"
    query_path.parent.mkdir(parents=True)
    shutil.copyfile(QUERY_SPEC, query_path)
    instance = payload["families"][0]["instances"][0]
    instance["query_spec_path"] = "queries/alice.json"
    registry = tmp_path / "registry.json"
    return payload, registry


def test_development_registry_freezes_family_local_boundary() -> None:
    plan = compile_m15_query_family_file(REGISTRY, repo_root=REPO_ROOT).to_dict()

    assert plan["schema_version"] == QUERY_FAMILY_PLAN_SCHEMA_VERSION
    assert plan["expected_counts"] == {
        "families": 1,
        "seen_families": 1,
        "held_out_families": 0,
        "query_instances": 1,
        "memory_seed_instances": 1,
        "held_out_instances": 0,
        "held_out_family_instances": 0,
    }
    family = plan["families"][0]
    assert len(family["family_compatibility_sha256"]) == 64
    assert family["memory_protocol"]["cross_family_reads_allowed"] is False
    assert family["memory_protocol"]["evaluation_writes_allowed"] is False
    assert family["memory_protocol"]["seed_instance_ids"] == [
        "financial-risk-alice-high-risk-v1"
    ]
    validation = plan["design_validation"]
    assert validation["family_local_transfer_only"] is True
    assert validation["held_out_family_cold_start_required"] is True
    assert validation["paper_workload_ready"] is False
    assert validation["blocking_conditions"] == [
        "fewer_than_target_query_families",
        "no_held_out_query_family",
        "fewer_than_30_query_instances",
        "seen_family_without_held_out_instance",
        "typed_semantic_operator_dag_not_yet_bound",
        "backend_query_template_structure_not_yet_bound",
        "query_instances_not_yet_bound_to_workload_contracts_and_oracles",
        "family_split_and_inferential_analysis_not_preregistered",
    ]
    assert plan["claim_boundary"]["backend_calls_made"] == 0
    assert plan["paper_result"] is False


def test_changed_bindings_share_family_key_but_not_instance_identity(
    tmp_path: Path,
) -> None:
    payload, registry = _temp_registry(tmp_path)
    family = payload["families"][0]
    bob = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    bob["query_id"] = "financial-risk-bob-medium-risk"
    bob["resolved_intent"] = "Find Bob's recent transfers to medium-risk companies."
    bob["hard_constraints"][0]["value"] = "person-bob-jones"
    bob["hard_constraints"][3]["value"] = "MEDIUM"
    bob_sha = _write_json(tmp_path / "queries/bob.json", bob)
    family["instances"].append(
        {
            "instance_id": "financial-risk-bob-medium-risk-v1",
            "split": "held_out_instance",
            "query_spec_path": "queries/bob.json",
            "expected_query_spec_sha256": bob_sha,
        }
    )
    _write_json(registry, payload)

    plan = compile_m15_query_family_file(registry, repo_root=tmp_path).to_dict()
    compiled = plan["families"][0]
    assert len(compiled["instances"]) == 2
    assert (
        compiled["instances"][0]["hard_binding_sha256"]
        != compiled["instances"][1]["hard_binding_sha256"]
    )
    assert (
        compiled["instances"][0]["instance_sha256"]
        != compiled["instances"][1]["instance_sha256"]
    )
    assert compiled["memory_protocol"]["evaluation_snapshot"] == (
        "freeze_after_successful_exact_memory_seed_commits"
    )
    assert compiled["memory_protocol"]["held_out_instance_ids"] == [
        "financial-risk-bob-medium-risk-v1"
    ]
    assert compiled["memory_protocol"]["evaluation_writes_allowed"] is False


def test_family_plan_hash_ignores_query_spec_location(tmp_path: Path) -> None:
    first_payload, first_registry = _temp_registry(tmp_path / "first")
    _write_json(first_registry, first_payload)
    first = compile_m15_query_family_file(
        first_registry,
        repo_root=tmp_path / "first",
    ).to_dict()

    second_payload, second_registry = _temp_registry(tmp_path / "second")
    source = tmp_path / "second/queries/alice.json"
    relocated = tmp_path / "second/relocated/query.json"
    relocated.parent.mkdir(parents=True)
    shutil.move(source, relocated)
    second_payload["families"][0]["instances"][0]["query_spec_path"] = (
        "relocated/query.json"
    )
    _write_json(second_registry, second_payload)
    second = compile_m15_query_family_file(
        second_registry,
        repo_root=tmp_path / "second",
    ).to_dict()

    assert first["registry_spec_sha256"] != second["registry_spec_sha256"]
    assert first["provenance"] != second["provenance"]
    assert first["query_family_plan_sha256"] == second["query_family_plan_sha256"]
    assert first["families"] == second["families"]


def test_query_structure_drift_is_rejected(tmp_path: Path) -> None:
    payload, registry = _temp_registry(tmp_path)
    changed = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    changed["semantic_operator_ids"][0] = "unrelated-start"
    sha = _write_json(tmp_path / "queries/changed.json", changed)
    instance = payload["families"][0]["instances"][0]
    instance["query_spec_path"] = "queries/changed.json"
    instance["expected_query_spec_sha256"] = sha
    _write_json(registry, payload)

    with pytest.raises(M15QueryFamilyError, match="structure drifted outside family"):
        compile_m15_query_family_file(registry, repo_root=tmp_path)


def test_duplicate_bindings_cannot_masquerade_as_two_instances(
    tmp_path: Path,
) -> None:
    payload, registry = _temp_registry(tmp_path)
    duplicate = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    duplicate["query_id"] = "renamed-but-identical-bindings"
    sha = _write_json(tmp_path / "queries/duplicate.json", duplicate)
    payload["families"][0]["instances"].append(
        {
            "instance_id": "renamed-but-identical-bindings-v1",
            "split": "held_out_instance",
            "query_spec_path": "queries/duplicate.json",
            "expected_query_spec_sha256": sha,
        }
    )
    _write_json(registry, payload)

    with pytest.raises(M15QueryFamilyError, match="duplicate hard bindings"):
        compile_m15_query_family_file(registry, repo_root=tmp_path)


def test_held_out_family_is_forced_to_cold_start(tmp_path: Path) -> None:
    payload, registry = _temp_registry(tmp_path)
    family = copy.deepcopy(payload["families"][0])
    family["family_id"] = "ownership-compliance-path"
    family["evaluation_role"] = "held_out_family"
    family["semantic_operator_ids"][0] = "resolved-owner"
    held_out = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    held_out["query_id"] = "ownership-compliance-alice"
    held_out["semantic_operator_ids"][0] = "resolved-owner"
    sha = _write_json(tmp_path / "queries/held-out.json", held_out)
    family["instances"] = [
        {
            "instance_id": "ownership-compliance-alice-v1",
            "split": "held_out_family",
            "query_spec_path": "queries/held-out.json",
            "expected_query_spec_sha256": sha,
        }
    ]
    payload["families"].append(family)
    _write_json(registry, payload)

    plan = compile_m15_query_family_file(registry, repo_root=tmp_path).to_dict()
    compiled = next(
        item
        for item in plan["families"]
        if item["family_id"] == "ownership-compliance-path"
    )
    assert compiled["memory_protocol"]["seed_instance_ids"] == []
    assert compiled["memory_protocol"]["held_out_instance_ids"] == []
    assert compiled["memory_protocol"]["held_out_family_instance_ids"] == [
        "ownership-compliance-alice-v1"
    ]
    assert compiled["memory_protocol"]["evaluation_snapshot"] == "empty_cold_start"
    assert compiled["memory_protocol"]["cross_family_reads_allowed"] is False


def test_duplicate_structural_families_are_rejected(tmp_path: Path) -> None:
    payload, registry = _temp_registry(tmp_path)
    family = copy.deepcopy(payload["families"][0])
    family["family_id"] = "duplicate-family-label"
    family["evaluation_role"] = "held_out_family"
    duplicate = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    duplicate["query_id"] = "duplicate-family-query"
    sha = _write_json(tmp_path / "queries/duplicate-family.json", duplicate)
    family["instances"] = [
        {
            "instance_id": "duplicate-family-query-v1",
            "split": "held_out_family",
            "query_spec_path": "queries/duplicate-family.json",
            "expected_query_spec_sha256": sha,
        }
    ]
    payload["families"].append(family)
    _write_json(registry, payload)

    with pytest.raises(M15QueryFamilyError, match="cannot share one structural"):
        compile_m15_query_family_file(registry, repo_root=tmp_path)


def test_family_registry_rejects_runtime_version_drift(tmp_path: Path) -> None:
    payload, registry = _temp_registry(tmp_path)
    payload["compatibility_versions"]["query_stream_schema_version"] = (
        "future-stream-v2"
    )
    _write_json(registry, payload)

    with pytest.raises(M15QueryFamilyError, match="disagree with runtime"):
        compile_m15_query_family_file(registry, repo_root=tmp_path)


def test_family_plan_write_and_cli_are_side_effect_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = compile_m15_query_family_file(REGISTRY, repo_root=REPO_ROOT)
    output = tmp_path / "family-plan.json"
    write_m15_query_family_plan(plan, output)
    assert json.loads(output.read_text(encoding="utf-8")) == plan.to_dict()
    with pytest.raises(FileExistsError, match="exists"):
        write_m15_query_family_plan(plan, output)

    assert main(
        ["--registry", str(REGISTRY), "--repo-root", str(REPO_ROOT)]
    ) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli == plan.to_dict()
    assert cli["claim_boundary"]["backend_calls_made"] == 0
