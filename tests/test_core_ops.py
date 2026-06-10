import pytest

from xgap.algebra import (
    EdgeRef,
    EdgesOp,
    GroupByOp,
    JoinOp,
    LabelEquals,
    NodesOp,
    OrderByOp,
    ProjectionOp,
    PropertyEquals,
    PropertyGraph,
    SelectionOp,
    UnionOp,
    evaluate,
)
from xgap.algebra.conditions import NodeRef
from xgap.algebra.types import Path


def build_sample_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Moe"})
    graph.add_node("n2", label="Person", properties={"name": "Bart"})
    graph.add_node("n3", label="Person", properties={"name": "Lisa"})
    graph.add_node("n4", label="Person", properties={"name": "Apu"})
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n2", "n3", label="Knows")
    graph.add_edge("e3", "n3", "n2", label="Knows")
    graph.add_edge("e4", "n2", "n4", label="Knows")
    return graph


def knows_edges() -> SelectionOp:
    return SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp())


def test_nodes_op_returns_all_zero_length_paths() -> None:
    graph = build_sample_graph()

    assert evaluate(NodesOp(), graph).sorted() == (
        Path.zero_length("n1"),
        Path.zero_length("n2"),
        Path.zero_length("n3"),
        Path.zero_length("n4"),
    )


def test_edges_op_returns_all_one_length_paths() -> None:
    graph = build_sample_graph()

    assert evaluate(EdgesOp(), graph).sorted() == (
        Path.one_length("n1", "e1", "n2"),
        Path.one_length("n2", "e2", "n3"),
        Path.one_length("n2", "e4", "n4"),
        Path.one_length("n3", "e3", "n2"),
    )


def test_selection_of_knows_edges_returns_knows_edges() -> None:
    graph = build_sample_graph()

    assert evaluate(knows_edges(), graph) == evaluate(EdgesOp(), graph)


def test_join_of_knows_edges_returns_valid_two_hop_paths() -> None:
    graph = build_sample_graph()

    assert evaluate(JoinOp(knows_edges(), knows_edges()), graph).sorted() == (
        Path(("n1", "e1", "n2", "e2", "n3")),
        Path(("n1", "e1", "n2", "e4", "n4")),
        Path(("n2", "e2", "n3", "e3", "n2")),
        Path(("n3", "e3", "n2", "e2", "n3")),
        Path(("n3", "e3", "n2", "e4", "n4")),
    )


def test_union_deduplicates_paths() -> None:
    graph = build_sample_graph()

    result = evaluate(UnionOp(EdgesOp(), EdgesOp()), graph)

    assert len(result) == 4
    assert result == evaluate(EdgesOp(), graph)


def test_selection_over_join_can_filter_by_first_name() -> None:
    graph = build_sample_graph()
    plan = SelectionOp(
        PropertyEquals(NodeRef.first(), "name", "Moe"),
        JoinOp(knows_edges(), knows_edges()),
    )

    assert evaluate(plan, graph).sorted() == (
        Path(("n1", "e1", "n2", "e2", "n3")),
        Path(("n1", "e1", "n2", "e4", "n4")),
    )


def test_selection_over_join_can_filter_by_last_name() -> None:
    graph = build_sample_graph()
    plan = SelectionOp(
        PropertyEquals(NodeRef.last(), "name", "Apu"),
        JoinOp(knows_edges(), knows_edges()),
    )

    assert evaluate(plan, graph).sorted() == (
        Path(("n1", "e1", "n2", "e4", "n4")),
        Path(("n3", "e3", "n2", "e4", "n4")),
    )


def test_unimplemented_operators_raise_not_implemented() -> None:
    graph = build_sample_graph()

    future_ops = [
        GroupByOp(EdgesOp(), keys=("first",)),
        OrderByOp(EdgesOp(), keys=("length",)),
        ProjectionOp(EdgesOp(), fields=("first", "last")),
    ]

    for op in future_ops:
        with pytest.raises(NotImplementedError):
            evaluate(op, graph)


def test_unknown_operator_raises_not_implemented() -> None:
    graph = build_sample_graph()

    with pytest.raises(NotImplementedError):
        evaluate(object(), graph)
