from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from xgap.algebra.conditions import EdgeRef, LabelEquals
from xgap.algebra.ops import EdgesOp, SelectionOp
from xgap.compilers.sparql import compile_sparql
from xgap.experiments.backend_mapping_audit import audit_dataset_backend_mapping
from xgap.experiments.bundles import DatasetBundle
from xgap.experiments.readiness import (
    capture_environment_manifest,
    parse_backend_image_identity,
)
from xgap.infrastructure.descriptors import load_yaml_mapping


ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "datasets" / "financial_risk_dev" / "backend_mapping.yaml"


def _transfer_plan() -> SelectionOp:
    return SelectionOp(LabelEquals(EdgeRef(1), "TRANSFER"), EdgesOp())


def test_backend_mapping_is_source_of_truth_for_m9_fuseki_iris() -> None:
    mapping = load_yaml_mapping(MAPPING_PATH)
    artifact = compile_sparql(_transfer_plan(), backend_mapping=mapping)

    expected = "http://xgap.example.org/financial-risk/transfersTo"
    assert f"<{expected}>" in artifact.text
    assert artifact.parameters["backend_mapping"]["relevant_mapped_iris"] == [
        {
            "logical_token": "TRANSFER",
            "canonical_term_id": "Transfer",
            "kind": "relation",
            "iri": expected,
        }
    ]


def test_changing_mapping_changes_sparql_without_compiler_changes() -> None:
    mapping = load_yaml_mapping(MAPPING_PATH)
    changed = deepcopy(mapping)
    changed["term_mappings"]["fuseki"]["Transfer"]["representation"] = (
        "https://example.test/schema/transfer"
    )

    artifact = compile_sparql(_transfer_plan(), backend_mapping=changed)

    assert "<https://example.test/schema/transfer>" in artifact.text
    assert "financial-risk/transfersTo" not in artifact.text


def test_m9_sparql_source_has_no_financial_risk_namespace() -> None:
    source = (ROOT / "src" / "xgap" / "compilers" / "sparql.py").read_text()
    assert "financial-risk" not in source
    assert "xgap.example.org/graph" not in source


def test_financial_risk_data_mapping_and_m9_three_way_audit_passes() -> None:
    dataset = DatasetBundle.load(ROOT / "datasets" / "financial_risk_dev")
    report = audit_dataset_backend_mapping(dataset)

    assert report["status"] == "pass"
    assert not report["mismatches"]
    transfer = next(
        record
        for record in report["records"]
        if record["logical_token"] == "TRANSFER"
    )
    assert transfer["URI_data"] == transfer["URI_mapping"] == transfer["URI_m9"]

    mismatched_mapping = deepcopy(dataset.backend_mapping)
    mismatched_mapping["term_mappings"]["fuseki"]["Transfer"]["representation"] = (
        "https://example.test/schema/transfer"
    )
    mismatch = audit_dataset_backend_mapping(
        replace(dataset, backend_mapping=mismatched_mapping)
    )
    assert mismatch["status"] == "fail"
    assert any(
        record["logical_token"] == "TRANSFER" for record in mismatch["mismatches"]
    )


def test_backend_image_identity_distinguishes_floating_version_and_digest(
    monkeypatch,
) -> None:
    floating = parse_backend_image_identity("fuseki", "stain/jena-fuseki:latest")
    versioned = parse_backend_image_identity("neo4j", "neo4j:5.26.12-community")
    digest = parse_backend_image_identity(
        "neo4j", "neo4j@sha256:" + "a" * 64
    )

    assert not floating.pinned and not floating.immutable
    assert versioned.pinned and not versioned.immutable
    assert digest.pinned and digest.immutable
    assert digest.repository == "neo4j"
    assert digest.digest == "sha256:" + "a" * 64

    monkeypatch.setenv("NEO4J_SOFTWARE_VERSION", "validated-server-version")
    manifest = capture_environment_manifest(
        ROOT,
        images={"neo4j": digest.configured_reference},
    )
    recorded = manifest["backend_image_identities"]["neo4j"]
    assert recorded["repository"] == "neo4j"
    assert recorded["digest"] == "sha256:" + "a" * 64
    assert recorded["backend_reported_software_version"] == {
        "source": "NEO4J_SOFTWARE_VERSION",
        "value": "validated-server-version",
    }
