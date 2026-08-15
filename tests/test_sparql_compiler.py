from pathlib import Path

import pytest

from xgap.algebra.conditions import (
    And,
    EdgeRef,
    LabelEquals,
    NodeRef,
    PropertyEquals,
    PropertyGreaterThanOrEqual,
)
from xgap.algebra.ops import EdgesOp, JoinOp, SelectionOp
from xgap.backends import registry
from xgap.compilers import compile_sparql
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.infrastructure.descriptors import load_yaml_mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_DIR = REPO_ROOT / "descriptors" / "backends"
BACKEND_MAPPING = load_yaml_mapping(
    REPO_ROOT / "datasets" / "financial_risk_dev" / "backend_mapping.yaml"
)


def _profile():
    registry.load_descriptors(DESCRIPTOR_DIR)
    return registry.get_capability_profile("fuseki")


def test_sparql_compiler_emits_deterministic_one_edge_query() -> None:
    plan = SelectionOp(
        And(
            LabelEquals(NodeRef.first(), "Person"),
            PropertyEquals(NodeRef.first(), "name", "Alice"),
            LabelEquals(EdgeRef(1), "OWNS"),
            LabelEquals(NodeRef.last(), "Company"),
            PropertyGreaterThanOrEqual(NodeRef.last(), "riskScore", 80),
        ),
        EdgesOp(),
    )

    artifact = compile_sparql(
        plan, profile=_profile(), backend_mapping=BACKEND_MAPPING
    )

    assert artifact.kind == "compiled"
    assert artifact.language == "sparql"
    assert artifact.text == "\n".join(
        [
            "SELECT DISTINCT ?source ?target ?n0 ?n1 ?e1 WHERE {",
            "  ?n0 <http://xgap.example.org/financial-risk/owns> ?n1 .",
            "  BIND(<http://xgap.example.org/financial-risk/owns> AS ?e1)",
            "  ?n0 a <http://xgap.example.org/financial-risk/Person> .",
            '  ?n0 <http://xgap.example.org/financial-risk/name> ?v0 .',
            '  FILTER(?v0 = "Alice")',
            "  ?n1 a <http://xgap.example.org/financial-risk/Company> .",
            "  ?n1 <http://xgap.example.org/financial-risk/riskLevel> ?v1 .",
            "  FILTER(?v1 >= 80)",
            "  BIND(?n0 AS ?source)",
            "  BIND(?n1 AS ?target)",
            "}",
        ]
    )
    assert artifact.parameters["target_backend_id"] == "fuseki"
    assert artifact.parameters["backend_mapping"]["mapping_id"] == (
        "financial-risk-dev-source-map"
    )


def test_sparql_compiler_offsets_edge_labels_across_join() -> None:
    plan = JoinOp(
        SelectionOp(LabelEquals(EdgeRef(1), "OWNS"), EdgesOp()),
        SelectionOp(LabelEquals(EdgeRef(1), "TRANSFER"), EdgesOp()),
    )

    artifact = compile_sparql(
        plan, profile=_profile(), backend_mapping=BACKEND_MAPPING
    )

    assert artifact.text == "\n".join(
        [
            "SELECT DISTINCT ?source ?target ?n0 ?n1 ?n2 ?e1 ?e2 WHERE {",
            "  ?n0 <http://xgap.example.org/financial-risk/owns> ?n1 .",
            "  BIND(<http://xgap.example.org/financial-risk/owns> AS ?e1)",
            "  ?n1 <http://xgap.example.org/financial-risk/transfersTo> ?n2 .",
            "  BIND(<http://xgap.example.org/financial-risk/transfersTo> AS ?e2)",
            "  BIND(?n0 AS ?source)",
            "  BIND(?n2 AS ?target)",
            "}",
        ]
    )


def test_sparql_compiler_rejects_edge_property_predicates() -> None:
    plan = SelectionOp(PropertyEquals(EdgeRef(1), "amount", 1000), EdgesOp())

    with pytest.raises(UnsupportedCompilationError) as exc_info:
        compile_sparql(
            plan, profile=_profile(), backend_mapping=BACKEND_MAPPING
        )

    assert exc_info.value.failure.unsupported_feature.feature_id == "graph_model.edge_properties"


def test_sparql_compiler_requires_backend_mapping() -> None:
    with pytest.raises(UnsupportedCompilationError) as exc_info:
        compile_sparql(EdgesOp(), profile=_profile())

    assert exc_info.value.failure.unsupported_feature.feature_id == "rdf_mapping.missing"
