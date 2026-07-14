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
from xgap.algebra.ops import EdgesOp, JoinOp, SelectionOp, UnionOp
from xgap.backends import registry
from xgap.compilers import compile_cypher
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.pattern import (
    EdgePattern,
    NodePattern,
    PathPatternQuery,
    Rel,
    Selector,
    SelectorKind,
    Var,
)
from xgap.algebra.ops import RecursiveMode


REPO_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_DIR = REPO_ROOT / "descriptors" / "backends"


def _profile():
    registry.load_descriptors(DESCRIPTOR_DIR)
    return registry.get_capability_profile("neo4j")


def test_cypher_compiler_emits_deterministic_one_edge_query() -> None:
    plan = SelectionOp(
        And(
            LabelEquals(NodeRef.first(), "Person"),
            PropertyEquals(NodeRef.first(), "name", "Alice"),
            LabelEquals(EdgeRef(1), "OWNS"),
            PropertyGreaterThanOrEqual(EdgeRef(1), "amount", 1000),
        ),
        EdgesOp(),
    )

    artifact = compile_cypher(plan, profile=_profile())

    assert artifact.kind == "compiled"
    assert artifact.language == "cypher"
    assert artifact.text == "\n".join(
        [
            "MATCH (n0)-[e1]->(n1)",
            'WHERE n0:Person\n  AND n0.name = "Alice"\n  AND type(e1) = "OWNS"\n  AND e1.amount >= 1000',
            "RETURN DISTINCT n0 AS source, n1 AS target, [n0, n1] AS nodes, [e1] AS edges",
        ]
    )
    assert artifact.parameters["target_backend_id"] == "neo4j"
    assert "path_algebra.Selection" in artifact.parameters["required_features"]


def test_cypher_compiler_offsets_conditions_across_join() -> None:
    plan = SelectionOp(
        PropertyEquals(NodeRef.last(), "risk", "high"),
        JoinOp(
            SelectionOp(LabelEquals(EdgeRef(1), "OWNS"), EdgesOp()),
            SelectionOp(LabelEquals(EdgeRef(1), "TRANSFER"), EdgesOp()),
        ),
    )

    artifact = compile_cypher(plan, profile=_profile())

    assert artifact.text == "\n".join(
        [
            "MATCH (n0)-[e1]->(n1)-[e2]->(n2)",
            'WHERE type(e1) = "OWNS"\n  AND type(e2) = "TRANSFER"\n  AND n2.risk = "high"',
            "RETURN DISTINCT n0 AS source, n2 AS target, [n0, n1, n2] AS nodes, [e1, e2] AS edges",
        ]
    )


def test_cypher_compiler_accepts_all_selector_path_pattern_core() -> None:
    query = PathPatternQuery(
        path_var=Var("p"),
        source=NodePattern(var=Var("a"), label="Person", properties={"name": "Alice"}),
        expr=Rel(EdgePattern(label="OWNS")),
        target=NodePattern(var=Var("c"), label="Company"),
        selector=Selector(SelectorKind.ALL),
        restrictor=RecursiveMode.TRAIL,
    )

    artifact = compile_cypher(query, profile=_profile())

    assert artifact.text == "\n".join(
        [
            "MATCH (n0)-[e1]->(n1)",
            'WHERE type(e1) = "OWNS"\n  AND n0:Person\n  AND n0.name = "Alice"\n  AND n1:Company',
            "RETURN DISTINCT n0 AS source, n1 AS target, [n0, n1] AS nodes, [e1] AS edges",
        ]
    )
    assert "pattern.PathPatternQuery" in artifact.parameters["required_features"]


def test_cypher_compiler_rejects_union_until_dedup_semantics_are_implemented() -> None:
    with pytest.raises(UnsupportedCompilationError) as exc_info:
        compile_cypher(UnionOp(EdgesOp(), EdgesOp()), profile=_profile())

    assert exc_info.value.failure.unsupported_feature.feature_id == "path_algebra.Union"
