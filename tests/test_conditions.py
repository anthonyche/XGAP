import pytest

from xgap.algebra.conditions import (
    And,
    EdgeRef,
    LabelEquals,
    LengthEquals,
    NodeRef,
    Not,
    Or,
    PropertyEquals,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
    PropertyLessThan,
    PropertyLessThanOrEqual,
    PropertyNotEquals,
)
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.types import Path


def build_sample_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Moe", "score": 0.9})
    graph.add_node("n2", label="Person", properties={"name": "Bart", "score": 0.4})
    graph.add_node("n3", label="Person", properties={"name": "Lisa"})
    graph.add_node("n4", label="Person", properties={"name": "Apu"})
    graph.add_edge("e1", "n1", "n2", label="Knows", properties={"since": 2001, "flag": True})
    graph.add_edge("e2", "n2", "n3", label="Knows", properties={"since": 2002, "amount": 1000})
    graph.add_edge("e3", "n3", "n2", label="Knows", properties={"since": 2003})
    graph.add_edge("e4", "n2", "n4", label="Knows", properties={"since": 2004})
    return graph


def test_label_edge_equals() -> None:
    graph = build_sample_graph()
    path = Path.one_length("n1", "e1", "n2")

    assert LabelEquals(EdgeRef(1), "Knows").evaluate(path, graph)
    assert not LabelEquals(EdgeRef(1), "Likes").evaluate(path, graph)


def test_label_node_equals_first_and_last() -> None:
    graph = build_sample_graph()
    path = Path.one_length("n1", "e1", "n2")

    assert LabelEquals(NodeRef.first(), "Person").evaluate(path, graph)
    assert LabelEquals(NodeRef.last(), "Person").evaluate(path, graph)


def test_first_name_equals() -> None:
    graph = build_sample_graph()
    path = Path.one_length("n1", "e1", "n2")

    assert PropertyEquals(NodeRef.first(), "name", "Moe").evaluate(path, graph)
    assert not PropertyEquals(NodeRef.first(), "name", "Apu").evaluate(path, graph)


def test_last_name_equals() -> None:
    graph = build_sample_graph()
    path = Path.one_length("n2", "e4", "n4")

    assert PropertyEquals(NodeRef.last(), "name", "Apu").evaluate(path, graph)
    assert not PropertyEquals(NodeRef.last(), "name", "Moe").evaluate(path, graph)


def test_indexed_node_and_edge_property_equals() -> None:
    graph = build_sample_graph()
    path = Path(("n1", "e1", "n2", "e2", "n3"))

    assert PropertyEquals(NodeRef(2), "name", "Bart").evaluate(path, graph)
    assert PropertyEquals(EdgeRef(2), "since", 2002).evaluate(path, graph)


def test_property_not_equals_requires_existing_property() -> None:
    graph = build_sample_graph()
    path = Path.one_length("n1", "e1", "n2")

    assert PropertyNotEquals(NodeRef.first(), "name", "Apu").evaluate(path, graph)
    assert not PropertyNotEquals(NodeRef.first(), "name", "Moe").evaluate(path, graph)
    assert not PropertyNotEquals(NodeRef.first(), "missing", "value").evaluate(path, graph)


def test_numeric_property_ordering() -> None:
    graph = build_sample_graph()
    path = Path(("n1", "e1", "n2", "e2", "n3"))

    assert PropertyGreaterThan(NodeRef.first(), "score", 0.8).evaluate(path, graph)
    assert PropertyGreaterThanOrEqual(EdgeRef(2), "amount", 1000).evaluate(path, graph)
    assert PropertyLessThan(NodeRef(2), "score", 0.5).evaluate(path, graph)
    assert PropertyLessThanOrEqual(EdgeRef(1), "since", 2001).evaluate(path, graph)


def test_numeric_property_ordering_rejects_missing_non_numeric_bool_and_non_finite() -> None:
    graph = build_sample_graph()
    path = Path.one_length("n1", "e1", "n2")

    assert not PropertyGreaterThan(NodeRef.first(), "missing", 0).evaluate(path, graph)
    assert not PropertyGreaterThan(NodeRef.first(), "name", 0).evaluate(path, graph)
    assert not PropertyGreaterThan(EdgeRef(1), "flag", 0).evaluate(path, graph)
    assert not PropertyGreaterThan(NodeRef.first(), "score", True).evaluate(path, graph)
    assert not PropertyGreaterThan(NodeRef.first(), "score", float("nan")).evaluate(path, graph)
    assert not PropertyGreaterThan(NodeRef.first(), "score", float("inf")).evaluate(path, graph)


def test_length_equals() -> None:
    graph = build_sample_graph()
    path = Path(("n1", "e1", "n2", "e2", "n3"))

    assert LengthEquals(2).evaluate(path, graph)
    assert not LengthEquals(1).evaluate(path, graph)


def test_and_or_not() -> None:
    graph = build_sample_graph()
    path = Path(("n1", "e1", "n2", "e4", "n4"))
    starts_with_moe = PropertyEquals(NodeRef.first(), "name", "Moe")
    ends_with_apu = PropertyEquals(NodeRef.last(), "name", "Apu")
    has_three_edges = LengthEquals(3)

    assert And(starts_with_moe, ends_with_apu).evaluate(path, graph)
    assert Or(has_three_edges, ends_with_apu).evaluate(path, graph)
    assert Not(has_three_edges).evaluate(path, graph)
    assert (starts_with_moe & ends_with_apu).evaluate(path, graph)
    assert (has_three_edges | ends_with_apu).evaluate(path, graph)
    assert (~has_three_edges).evaluate(path, graph)


def test_conditions_return_false_for_missing_references() -> None:
    graph = build_sample_graph()
    path = Path.zero_length("n1")

    assert not LabelEquals(EdgeRef(1), "Knows").evaluate(path, graph)
    assert not PropertyEquals(NodeRef.first(), "missing", "value").evaluate(path, graph)


def test_boolean_conditions_require_children_and_length_is_non_negative() -> None:
    with pytest.raises(ValueError):
        And()
    with pytest.raises(ValueError):
        Or()
    with pytest.raises(ValueError):
        LengthEquals(-1)
