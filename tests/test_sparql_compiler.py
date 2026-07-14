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


REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_DIR = REPO_ROOT / "descriptors" / "backends"


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

    artifact = compile_sparql(plan, profile=_profile())

    assert artifact.kind == "compiled"
    assert artifact.language == "sparql"
    assert artifact.text == "\n".join(
        [
            "PREFIX xgap: <http://xgap.example.org/graph/>",
            "",
            "SELECT DISTINCT ?source ?target ?n0 ?n1 ?e1 WHERE {",
            "  ?n0 xgap:OWNS ?n1 .",
            "  BIND(xgap:OWNS AS ?e1)",
            "  ?n0 a xgap:Person .",
            '  ?n0 xgap:name ?v0 .',
            '  FILTER(?v0 = "Alice")',
            "  ?n1 a xgap:Company .",
            "  ?n1 xgap:riskScore ?v1 .",
            "  FILTER(?v1 >= 80)",
            "  BIND(?n0 AS ?source)",
            "  BIND(?n1 AS ?target)",
            "}",
        ]
    )
    assert artifact.parameters["target_backend_id"] == "fuseki"


def test_sparql_compiler_offsets_edge_labels_across_join() -> None:
    plan = JoinOp(
        SelectionOp(LabelEquals(EdgeRef(1), "OWNS"), EdgesOp()),
        SelectionOp(LabelEquals(EdgeRef(1), "TRANSFER"), EdgesOp()),
    )

    artifact = compile_sparql(plan, profile=_profile())

    assert artifact.text == "\n".join(
        [
            "PREFIX xgap: <http://xgap.example.org/graph/>",
            "",
            "SELECT DISTINCT ?source ?target ?n0 ?n1 ?n2 ?e1 ?e2 WHERE {",
            "  ?n0 xgap:OWNS ?n1 .",
            "  BIND(xgap:OWNS AS ?e1)",
            "  ?n1 xgap:TRANSFER ?n2 .",
            "  BIND(xgap:TRANSFER AS ?e2)",
            "  BIND(?n0 AS ?source)",
            "  BIND(?n2 AS ?target)",
            "}",
        ]
    )


def test_sparql_compiler_rejects_edge_property_predicates() -> None:
    plan = SelectionOp(PropertyEquals(EdgeRef(1), "amount", 1000), EdgesOp())

    with pytest.raises(UnsupportedCompilationError) as exc_info:
        compile_sparql(plan, profile=_profile())

    assert exc_info.value.failure.unsupported_feature.feature_id == "graph_model.edge_properties"
