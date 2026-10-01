from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.m15_parameterized_workload import (
    M15ParameterizedWorkloadError,
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_semantic_overlay import (
    SEMANTIC_OVERLAY_SCHEMA_VERSION,
    M15SemanticOverlayError,
    generate_m15_semantic_overlay_bundle,
    load_m15_semantic_overlay_bundle,
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
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
SEMANTIC_CATALOG = (
    REPO_ROOT / "experiments/configs/m15_f2c6_semantic_relaxation_dev.json"
)
BASE_QUERY_ID = "financial-risk-alice-aug-high-v2"


def _base_bundle(tmp_path: Path, name: str = "base"):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / name,
    )


def _overlay(tmp_path: Path, name: str = "overlay"):
    base = _base_bundle(tmp_path)
    overlay = generate_m15_semantic_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        destination=tmp_path / name,
    )
    return base, overlay


def test_overlay_materializes_only_currently_supported_relaxation(
    tmp_path: Path,
) -> None:
    base, overlay = _overlay(tmp_path)
    manifest = overlay.to_dict()

    assert manifest["schema_version"] == SEMANTIC_OVERLAY_SCHEMA_VERSION
    assert manifest["base_query_instance_count"] == 6
    assert manifest["overlay_query_instance_count"] == 1
    assert manifest["total_query_instance_count"] == 7
    assert manifest["blocked_semantic_class_count"] == 10
    assert manifest["blocked_classes_materialized"] is False
    assert len(manifest["overlay_sha256"]) == 64
    assert (
        manifest["base_workload_bundle_content_sha256"]
        == base.manifest["bundle_content_sha256"]
    )
    assert manifest["claim_boundary"] == {
        "artifact_class": "unexecuted_semantic_interpretation_overlay",
        "only_readiness_approved_classes_materialized": True,
        "base_bundle_mutated": False,
        "relaxed_backend_artifacts_bound": True,
        "relaxed_oracles_bound": True,
        "backend_calls_made": 0,
        "llm_calls_made": 0,
        "ontology_calls_made": 0,
        "contains_measurements": False,
        "paper_result": False,
    }
    assert manifest["paper_result"] is False


def test_risk_overlay_preserves_hard_bindings_and_has_bound_oracles(
    tmp_path: Path,
) -> None:
    _, overlay = _overlay(tmp_path)
    record = overlay.manifest["overlay_instances"][0]
    query_id = record["query_id"]
    contract = json.loads(
        overlay.workload_bundle.path(
            f"instances/{query_id}/parameterized_contract.json"
        ).read_text(encoding="utf-8")
    )
    bindings = {item["slot_id"]: item["value"] for item in contract["bindings"]}

    assert bindings == {
        "amount-lower-bound": 50000,
        "path-shape": "direct",
        "person-identity": "person-alice-smith",
        "risk-level": "MEDIUM",
        "time-lower-bound": "2026-08-01",
        "transfer-predicate": "transfer_to_company",
    }
    assert contract["query_instance_sha256"] == record[
        "query_instance_sha256"
    ]
    assert record["oracle_counts"]["final"] > 0
    risk_query = overlay.workload_bundle.path(
        f"instances/{query_id}/fuseki_risk.rq"
    ).read_text(encoding="utf-8")
    assert 'FILTER (?risk = "MEDIUM")' in risk_query
    expected = json.loads(
        overlay.workload_bundle.path(
            f"instances/{query_id}/expected_result.json"
        ).read_text(encoding="utf-8")
    )
    assert expected
    assert {item["risk"] for item in expected} == {"MEDIUM"}


def test_overlay_reuses_identical_base_data_and_templates(tmp_path: Path) -> None:
    base, overlay = _overlay(tmp_path)
    for relative_path in ("load_neo4j.cypher", "load_fuseki.ttl"):
        assert base.path(relative_path).read_bytes() == overlay.workload_bundle.path(
            relative_path
        ).read_bytes()
        assert overlay.manifest["shared_data_artifacts"][relative_path][
            "identical"
        ] is True
    assert base.manifest["input_hashes"]["backend_templates"] == (
        overlay.workload_bundle.manifest["input_hashes"]["backend_templates"]
    )


def test_overlay_is_deterministic_and_reloadable(tmp_path: Path) -> None:
    base = _base_bundle(tmp_path)
    first = generate_m15_semantic_overlay_bundle(
        base_bundle=base,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        destination=tmp_path / "first",
    )
    second = generate_m15_semantic_overlay_bundle(
        base_bundle=base.root,
        base_query_id=BASE_QUERY_ID,
        catalog=SEMANTIC_CATALOG,
        destination=tmp_path / "second",
    )
    loaded = load_m15_semantic_overlay_bundle(
        first.root,
        base_bundle=base,
        catalog=SEMANTIC_CATALOG,
    )

    assert first.manifest == second.manifest == loaded.manifest
    assert first.workload_bundle.manifest == second.workload_bundle.manifest


def test_overlay_loader_rejects_nested_tamper_and_wrong_base(
    tmp_path: Path,
) -> None:
    base, overlay = _overlay(tmp_path)
    query_id = overlay.manifest["overlay_instances"][0]["query_id"]
    target = overlay.workload_bundle.path(
        f"instances/{query_id}/fuseki_risk.rq"
    )
    target.write_text(target.read_text(encoding="utf-8") + "# tamper\n")
    with pytest.raises(M15ParameterizedWorkloadError, match="SHA-256 mismatch"):
        load_m15_semantic_overlay_bundle(
            overlay.root,
            base_bundle=base,
            catalog=SEMANTIC_CATALOG,
        )

    other_base = _base_bundle(tmp_path, "other-base")
    other_base.manifest["bundle_content_sha256"] = "0" * 64
    with pytest.raises((M15SemanticOverlayError, M15ParameterizedWorkloadError)):
        load_m15_semantic_overlay_bundle(
            overlay.root,
            base_bundle=other_base,
            catalog=SEMANTIC_CATALOG,
        )


def test_overlay_refuses_existing_destination(tmp_path: Path) -> None:
    base, _ = _overlay(tmp_path)
    with pytest.raises(FileExistsError, match="destination exists"):
        generate_m15_semantic_overlay_bundle(
            base_bundle=base,
            base_query_id=BASE_QUERY_ID,
            catalog=SEMANTIC_CATALOG,
            destination=tmp_path / "overlay",
        )


def test_cli_generates_overlay_once(tmp_path: Path, capsys) -> None:
    base = _base_bundle(tmp_path)
    output = tmp_path / "cli-overlay"
    arguments = [
        "--base-bundle-root",
        str(base.root),
        "--base-query-id",
        BASE_QUERY_ID,
        "--catalog",
        str(SEMANTIC_CATALOG),
        "--output",
        str(output),
    ]

    assert main(arguments) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["status"] == "success"
    assert success["overlay_query_instance_count"] == 1
    assert success["blocked_classes_materialized"] is False

    assert main(arguments) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["status"] == "configuration_error"
    assert "destination exists" in failure["error"]
