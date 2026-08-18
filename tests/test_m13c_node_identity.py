from pathlib import Path

import pytest

from xgap.algebra.conditions import NodeNotEquals, NodeRef
from xgap.algebra.evaluator import evaluate_pathset
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import RecursiveMode
from xgap.algebra.pretty import format_plan
from xgap.algebra.types import Path as GraphPath
from xgap.backends import registry
from xgap.compilers import compile_cypher, compile_sparql
from xgap.infrastructure.descriptors import load_yaml_mapping
from xgap.llm.parser import parse_path_pattern_query, path_pattern_query_to_dict
from xgap.pattern import (
    EdgePattern,
    NodePattern,
    PathPatternQuery,
    PatternTypeError,
    Rel,
    Selector,
    SelectorKind,
    Seq,
    Var,
    lower_to_logical_plan,
    type_check_path_pattern,
)


ROOT = Path(__file__).resolve().parents[1]


def _query(condition: NodeNotEquals) -> PathPatternQuery:
    return PathPatternQuery(
        path_var=Var("path"),
        source=NodePattern(var=Var("source")),
        expr=Seq(
            Rel(EdgePattern(label="OWNS")),
            Rel(EdgePattern(label="TRANSFER")),
        ),
        target=NodePattern(var=Var("answer")),
        selector=Selector(SelectorKind.ALL),
        restrictor=RecursiveMode.TRAIL,
        condition=condition,
    )


def _profile(backend_id: str):
    registry.load_descriptors(ROOT / "descriptors" / "backends")
    return registry.get_capability_profile(backend_id)


def test_node_not_equals_uses_graph_node_identity() -> None:
    graph = PropertyGraph()
    for node_id in ("n1", "n2", "n3"):
        graph.add_node(node_id)
    graph.add_edge("e1", "n1", "n2", label="OWNS")
    graph.add_edge("e2", "n2", "n1", label="TRANSFER")
    graph.add_edge("e3", "n2", "n3", label="TRANSFER")

    plan = lower_to_logical_plan(_query(NodeNotEquals(NodeRef(1), NodeRef(3))))

    assert evaluate_pathset(plan, graph).sorted() == (
        GraphPath(("n1", "e1", "n2", "e3", "n3")),
    )
    assert "node(1) != node(3)" in format_plan(plan)


def test_node_not_equals_rejects_out_of_range_fixed_position() -> None:
    with pytest.raises(PatternTypeError, match="outside fixed path node range"):
        type_check_path_pattern(_query(NodeNotEquals(NodeRef(1), NodeRef(4))))


def test_node_not_equals_controlled_json_round_trip() -> None:
    query = _query(NodeNotEquals(NodeRef.first(), NodeRef.last()))

    encoded = path_pattern_query_to_dict(query)
    decoded = parse_path_pattern_query(encoded)

    assert encoded["condition"] == {
        "kind": "node_not_equals",
        "left": {"kind": "node", "position": "first"},
        "right": {"kind": "node", "position": "last"},
    }
    assert decoded == query


def test_node_not_equals_compiles_for_both_m9_backends() -> None:
    query = _query(NodeNotEquals(NodeRef(1), NodeRef(3)))

    cypher = compile_cypher(query, profile=_profile("neo4j"))
    sparql = compile_sparql(
        query,
        profile=_profile("fuseki"),
        backend_mapping=load_yaml_mapping(
            ROOT / "datasets" / "financial_risk_dev" / "backend_mapping.yaml"
        ),
    )

    assert "n0 <> n2" in cypher.text
    assert "FILTER(?n0 != ?n2)" in sparql.text
    assert "graph_model.node_identity_predicates" in cypher.parameters["required_features"]
    assert "graph_model.node_identity_predicates" in sparql.parameters["required_features"]
