from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.m15_fixture_loader import split_cypher_statements
from xgap.experiments.m15_parameterized_workload import (
    PARAMETERIZED_WORKLOAD_BUNDLE_SCHEMA_VERSION,
    M15ParameterizedWorkloadError,
    M15ParameterizedWorkloadSpec,
    generate_m15_parameterized_workload_bundle,
    load_m15_parameterized_workload_bundle,
    main,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SPEC = (
    REPO_ROOT / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
)
QUERY_TEMPLATE = (
    REPO_ROOT
    / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
)
BACKEND_TEMPLATES = (
    REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
)
EXPECTED_FAMILY = "34d432efccebd8d4000d52f910a25746b01e6d884f99eb41de6cbe846c13dfec"


def _generate(tmp_path: Path, name: str = "bundle"):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / name,
    )


def _workload_payload() -> dict[str, object]:
    return json.loads(WORKLOAD_SPEC.read_text(encoding="utf-8"))


def test_bundle_is_deterministic_hash_bound_and_unexecuted(tmp_path: Path) -> None:
    first = _generate(tmp_path, "first")
    second = _generate(tmp_path, "second")

    assert first.manifest == second.manifest
    assert (
        first.manifest["schema_version"]
        == PARAMETERIZED_WORKLOAD_BUNDLE_SCHEMA_VERSION
    )
    assert first.manifest["family_compatibility_sha256"] == EXPECTED_FAMILY
    assert len(first.manifest["bundle_content_sha256"]) == 64
    assert first.manifest["counts"] == {
        "persons": 4,
        "companies": 30,
        "transfers": 720,
        "query_instances": 6,
        "split_roles": {"heldout_instance": 2, "seed": 4},
    }
    assert first.manifest["claim_boundary"] == {
        "artifact_class": "unexecuted_parameterized_workload_bundle",
        "backend_query_templates_bound": True,
        "workload_bundle_bound": True,
        "oracles_bound": True,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_calls_made": 0,
        "contains_measurements": False,
        "paper_result": False,
    }
    for relative_path, digest in first.manifest["files_sha256"].items():
        assert first.path(relative_path).read_bytes() == second.path(
            relative_path
        ).read_bytes()
        assert hashlib.sha256(first.path(relative_path).read_bytes()).hexdigest() == (
            digest
        )


def test_instances_share_family_but_have_unique_binding_identity(
    tmp_path: Path,
) -> None:
    bundle = _generate(tmp_path)
    records = bundle.manifest["instances"]

    assert len({item["query_instance_sha256"] for item in records}) == 6
    assert len({item["binding_sha256"] for item in records}) == 6
    for query_id in bundle.instance_ids():
        contract = json.loads(
            bundle.path(
                f"instances/{query_id}/parameterized_contract.json"
            ).read_text(encoding="utf-8")
        )
        assert contract["family_compatibility_sha256"] == EXPECTED_FAMILY
        assert contract["query_id"] == query_id


def test_backend_templates_are_literal_free_and_render_typed_bindings(
    tmp_path: Path,
) -> None:
    bundle = _generate(tmp_path)
    templates = {
        path.name: path.read_text(encoding="utf-8")
        for path in (bundle.root / "templates").iterdir()
    }
    joined = "\n".join(templates.values())
    assert "person-alice-smith" not in joined
    assert "2026-08-01" not in joined
    assert '"HIGH"' not in joined
    assert "$person_id" in templates["neo4j_full.cypher.tmpl"]
    assert "$occurred_on_gte" in templates["neo4j_full.cypher.tmpl"]
    assert "$amount_gte" in templates["neo4j_full.cypher.tmpl"]
    assert "$company_ids" in templates["neo4j_bound.cypher.tmpl"]

    query_id = "financial-risk-alice-aug-high-v2"
    full = bundle.path(f"instances/{query_id}/neo4j_full.cypher").read_text(
        encoding="utf-8"
    )
    risk = bundle.path(f"instances/{query_id}/fuseki_risk.rq").read_text(
        encoding="utf-8"
    )
    assert "{{compile:" not in full + risk
    assert "TRANSFER_TO_COMPANY" in full
    assert 'FILTER (?risk = "HIGH")' in risk
    assert "person-alice-smith" not in full


def test_shared_load_contains_all_entities_and_fixed_batches(tmp_path: Path) -> None:
    bundle = _generate(tmp_path)
    load = bundle.path("load_neo4j.cypher").read_text(encoding="utf-8")
    statements = split_cypher_statements(load)

    assert len(statements) == 13
    assert sum(statement.startswith("UNWIND ") for statement in statements) == 10
    assert "person-alice-smith" in load
    assert "person-bob-jones" in load
    assert "person-carol-lee" in load
    assert "person-diego-garcia" in load
    assert "TRANSFER_TO_COMPANY" in load
    assert '{"amount"' not in load


def test_binding_artifact_separates_three_binding_stages(tmp_path: Path) -> None:
    bundle = _generate(tmp_path)
    query_id = "financial-risk-alice-aug-high-v2"
    binding = json.loads(
        bundle.path(f"instances/{query_id}/bindings.json").read_text(
            encoding="utf-8"
        )
    )

    assert binding["runtime_parameters"]["neo4j_full"] == {
        "person_id": "person-alice-smith",
        "occurred_on_gte": "2026-08-01",
        "amount_gte": 50000,
    }
    assert binding["compile_time_parameters"]["neo4j_full"] == {
        "transfer_predicate": "transfer_to_company",
        "path_shape": "direct",
    }
    assert binding["compile_time_parameters"]["fuseki_risk"] == {
        "risk_level": "HIGH"
    }
    assert binding["runtime_intermediates"] == {
        "neo4j_bound": {
            "company_ids": {
                "source": "align(fuseki_risk.company_id)",
                "representation": "backend_local_company_id",
            }
        }
    }


def test_oracles_are_nonempty_and_bound_plan_is_exact_subset(tmp_path: Path) -> None:
    bundle = _generate(tmp_path)
    for record in bundle.manifest["instances"]:
        query_id = record["query_id"]
        sources = json.loads(
            bundle.path(
                f"instances/{query_id}/expected_source_results.json"
            ).read_text(encoding="utf-8")
        )
        final = json.loads(
            bundle.path(f"instances/{query_id}/expected_result.json").read_text(
                encoding="utf-8"
            )
        )
        assert sources["neo4j_full"]
        assert sources["fuseki_risk"]
        assert sources["neo4j_bound"]
        assert len(sources["neo4j_bound"]) == len(final)
        assert len(sources["neo4j_bound"]) <= len(sources["neo4j_full"])
        assert record["oracle_counts"]["final"] == len(final)


def test_loader_rejects_tamper_even_if_attacker_updates_manifest_hash(
    tmp_path: Path,
) -> None:
    bundle = _generate(tmp_path)
    target_name = (
        "instances/financial-risk-alice-aug-high-v2/neo4j_full.cypher"
    )
    target = bundle.path(target_name)
    target.write_text(target.read_text(encoding="utf-8") + "// changed\n")
    with pytest.raises(M15ParameterizedWorkloadError, match="SHA-256 mismatch"):
        load_m15_parameterized_workload_bundle(bundle.root)

    manifest_path = bundle.root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files_sha256"][target_name] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(M15ParameterizedWorkloadError, match="not deterministic"):
        load_m15_parameterized_workload_bundle(bundle.root)


def test_instance_binding_coverage_and_exact_fragment_fail_closed(
    tmp_path: Path,
) -> None:
    missing = _workload_payload()
    del missing["query_instances"][0]["binding_values"]["amount-lower-bound"]
    missing_spec = M15ParameterizedWorkloadSpec.from_dict(missing)
    with pytest.raises(M15ParameterizedWorkloadError, match="coverage mismatch"):
        generate_m15_parameterized_workload_bundle(
            workload_spec=missing_spec,
            query_template_spec=QUERY_TEMPLATE,
            backend_template_root=BACKEND_TEMPLATES,
            destination=tmp_path / "missing",
        )

    unsupported = _workload_payload()
    unsupported["query_instances"][0]["binding_values"]["path-shape"] = (
        "bounded-two-hop"
    )
    unsupported_spec = M15ParameterizedWorkloadSpec.from_dict(unsupported)
    with pytest.raises(M15ParameterizedWorkloadError, match="cannot compile"):
        generate_m15_parameterized_workload_bundle(
            workload_spec=unsupported_spec,
            query_template_spec=QUERY_TEMPLATE,
            backend_template_root=BACKEND_TEMPLATES,
            destination=tmp_path / "unsupported",
        )


def test_duplicate_semantic_instance_cannot_be_created_by_renaming() -> None:
    payload = _workload_payload()
    duplicate = json.loads(json.dumps(payload["query_instances"][0]))
    duplicate["query_id"] = "renamed-duplicate"
    duplicate["resolved_intent"] = "Different prose, identical bindings."
    duplicate["split_role"] = "heldout_instance"
    payload["query_instances"].append(duplicate)
    spec = M15ParameterizedWorkloadSpec.from_dict(payload)

    with pytest.raises(M15ParameterizedWorkloadError, match="unique semantic"):
        generate_m15_parameterized_workload_bundle(
            workload_spec=spec,
            query_template_spec=QUERY_TEMPLATE,
            backend_template_root=BACKEND_TEMPLATES,
            destination=Path("unused"),
        )


def test_symlinked_inputs_and_existing_destination_are_rejected(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "query-template.json"
    linked.symlink_to(QUERY_TEMPLATE)
    with pytest.raises(M15ParameterizedWorkloadError, match="non-symbolic-link"):
        generate_m15_parameterized_workload_bundle(
            workload_spec=WORKLOAD_SPEC,
            query_template_spec=linked,
            backend_template_root=BACKEND_TEMPLATES,
            destination=tmp_path / "linked",
        )

    _generate(tmp_path, "existing")
    with pytest.raises(FileExistsError, match="destination exists"):
        _generate(tmp_path, "existing")


def test_cli_generates_and_refuses_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "bundle"
    arguments = [
        "--workload-spec",
        str(WORKLOAD_SPEC),
        "--query-template-spec",
        str(QUERY_TEMPLATE),
        "--backend-template-root",
        str(BACKEND_TEMPLATES),
        "--output",
        str(output),
    ]
    assert main(arguments) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["status"] == "success"
    assert success["counts"]["query_instances"] == 6

    assert main(arguments) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "configuration_error"
    assert "destination exists" in failure["error"]
