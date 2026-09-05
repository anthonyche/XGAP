from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.m15_query_contract import (
    QUERY_CONTRACT_SCHEMA_VERSION,
    QUERY_SPEC_SCHEMA_VERSION,
    M15ResolvedQuerySpec,
    compile_m15_query_contract,
    main,
)
from xgap.experiments.m15_workload import (
    M15WorkloadSpec,
    generate_m15_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_SPEC = REPO_ROOT / "experiments/configs/m15_f2_query_contract_dev.json"
SELECTIVE_SPEC = REPO_ROOT / "experiments/configs/m15_f0_selective.json"
BROAD_SPEC = REPO_ROOT / "experiments/configs/m15_f0_broad_hot.json"


def _bundle(tmp_path: Path, source: Path, name: str):
    return generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(source),
        tmp_path / name,
    )


def test_query_contract_binds_exact_artifacts_constraints_and_oracles(
    tmp_path: Path,
) -> None:
    first = _bundle(tmp_path, SELECTIVE_SPEC, "first")
    second = _bundle(tmp_path, SELECTIVE_SPEC, "second")

    one = compile_m15_query_contract(query_spec=QUERY_SPEC, workload_bundle=first)
    two = compile_m15_query_contract(query_spec=QUERY_SPEC, workload_bundle=second)
    payload = one.to_dict()

    assert one.query_contract_sha256 == two.query_contract_sha256
    assert payload["schema_version"] == QUERY_CONTRACT_SCHEMA_VERSION
    assert payload["query_spec_schema_version"] == QUERY_SPEC_SCHEMA_VERSION
    assert payload["query_id"] == "financial-risk-alice-high-risk"
    assert payload["workload"]["workload_id"] == "selective-dev-v1"
    assert {item["role"] for item in payload["artifacts"]} == {
        "neo4j_full",
        "neo4j_bound",
        "fuseki_risk",
    }
    assert all(
        item["sha256"] == first.source_hashes[item["filename"]]
        for item in payload["artifacts"]
    )
    assert all(item["relaxable"] is False for item in payload["hard_constraints"])
    assert payload["oracles"] == [
        {
            "role": "source_answers",
            "filename": "expected_source_results.json",
            "sha256": first.source_hashes["expected_source_results.json"],
            "row_count": 5020,
        },
        {
            "role": "final_answer",
            "filename": "expected_result.json",
            "sha256": first.source_hashes["expected_result.json"],
            "row_count": 120,
        },
    ]
    assert payload["automatic_retries"] == 0
    assert payload["llm_calls"] == 0
    assert payload["ontology_calls"] == 0
    assert payload["paper_result"] is False


def test_query_contract_changes_across_exact_workload_artifacts(tmp_path: Path) -> None:
    selective = _bundle(tmp_path, SELECTIVE_SPEC, "selective")
    broad = _bundle(tmp_path, BROAD_SPEC, "broad")

    selective_contract = compile_m15_query_contract(
        query_spec=QUERY_SPEC,
        workload_bundle=selective,
    )
    broad_contract = compile_m15_query_contract(
        query_spec=QUERY_SPEC,
        workload_bundle=broad,
    )

    assert selective_contract.query_contract_sha256 != broad_contract.query_contract_sha256
    assert selective_contract.body["workload"] != broad_contract.body["workload"]
    assert selective_contract.body["artifacts"] != broad_contract.body["artifacts"]


def test_query_contract_hash_is_portable_across_query_spec_paths(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path, SELECTIVE_SPEC, "bundle")
    copied_spec = tmp_path / "relocated" / "resolved-query.json"
    copied_spec.parent.mkdir()
    copied_spec.write_bytes(QUERY_SPEC.read_bytes())

    original = compile_m15_query_contract(
        query_spec=QUERY_SPEC,
        workload_bundle=bundle,
    )
    relocated = compile_m15_query_contract(
        query_spec=copied_spec,
        workload_bundle=bundle,
    )

    assert original.query_spec_path != relocated.query_spec_path
    assert original.query_contract_sha256 == relocated.query_contract_sha256
    assert original.body == relocated.body
    assert original.to_dict() == relocated.to_dict()


def test_query_spec_semantic_drift_changes_contract_hash(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, SELECTIVE_SPEC, "bundle")
    original = compile_m15_query_contract(
        query_spec=QUERY_SPEC,
        workload_bundle=bundle,
    )
    payload = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    payload["hard_constraints"][2]["value"] = 50001
    changed_spec = tmp_path / "changed-query.json"
    changed_spec.write_text(json.dumps(payload), encoding="utf-8")

    changed = compile_m15_query_contract(
        query_spec=changed_spec,
        workload_bundle=bundle,
    )

    assert changed.query_contract_sha256 != original.query_contract_sha256
    assert changed.body["query_spec_sha256"] != original.body["query_spec_sha256"]


def test_query_spec_rejects_relaxable_hard_constraint() -> None:
    payload = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    payload["hard_constraints"][0]["relaxable"] = True

    with pytest.raises(ValueError, match="cannot be relaxable"):
        M15ResolvedQuerySpec.from_dict(payload)


def test_query_contract_rejects_undeclared_bundle_member(tmp_path: Path) -> None:
    payload = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    payload["artifacts"][0]["filename"] = "unbound-query.cypher"
    changed_spec = tmp_path / "bad-query.json"
    changed_spec.write_text(json.dumps(payload), encoding="utf-8")
    bundle = _bundle(tmp_path, SELECTIVE_SPEC, "bundle")

    with pytest.raises(ValueError, match="identity contract is invalid"):
        compile_m15_query_contract(
            query_spec=changed_spec,
            workload_bundle=bundle,
        )


def test_query_spec_rejects_swapped_backend_role() -> None:
    payload = json.loads(QUERY_SPEC.read_text(encoding="utf-8"))
    payload["artifacts"][0]["role"] = "fuseki_risk"
    payload["artifacts"][2]["role"] = "neo4j_full"

    with pytest.raises(ValueError, match="identity contract is invalid"):
        M15ResolvedQuerySpec.from_dict(payload)


def test_query_contract_rejects_symlinked_query_spec(tmp_path: Path) -> None:
    linked_spec = tmp_path / "linked-query.json"
    linked_spec.symlink_to(QUERY_SPEC)
    bundle = _bundle(tmp_path, SELECTIVE_SPEC, "bundle")

    with pytest.raises(ValueError, match="non-symbolic-link"):
        compile_m15_query_contract(
            query_spec=linked_spec,
            workload_bundle=bundle,
        )


def test_query_contract_cli_emits_compiled_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _bundle(tmp_path, SELECTIVE_SPEC, "bundle")

    assert main(
        [
            "--query-spec",
            str(QUERY_SPEC),
            "--workload-bundle",
            str(bundle.root),
        ]
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "success"
    assert output["query_contract_sha256"]
    assert output["query_id"] == "financial-risk-alice-high-risk"
    assert output["paper_result"] is False
