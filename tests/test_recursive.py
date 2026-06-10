import pytest

from xgap.algebra import EdgesOp, GroupByOp, JoinOp, OrderByOp, ProjectionOp, PropertyGraph, evaluate
from xgap.algebra.ops import RecursiveMode, RecursiveOp
from xgap.algebra.types import Path


def build_cycle_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Node")
    graph.add_node("n2", label="Node")
    graph.add_node("n3", label="Node")
    graph.add_edge("e1", "n1", "n2", label="Link")
    graph.add_edge("e2", "n2", "n1", label="Link")
    graph.add_edge("e3", "n2", "n3", label="Link")
    return graph


def build_shortest_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1")
    graph.add_node("n2")
    graph.add_node("n3")
    graph.add_edge("e1", "n1", "n2")
    graph.add_edge("e2", "n1", "n2")
    graph.add_edge("e3", "n1", "n3")
    graph.add_edge("e4", "n3", "n2")
    return graph


def test_walk_requires_max_depth() -> None:
    graph = build_cycle_graph()

    with pytest.raises(ValueError, match="WALK mode requires"):
        evaluate(RecursiveOp(EdgesOp(), RecursiveMode.WALK), graph)


def test_walk_allows_repeated_nodes_and_edges() -> None:
    graph = build_cycle_graph()
    plan = RecursiveOp(EdgesOp(), RecursiveMode.WALK, max_depth=3)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2", "e2", "n1", "e1", "n2")) in result


def test_trail_rejects_repeated_edges_but_allows_repeated_nodes() -> None:
    graph = build_cycle_graph()
    plan = RecursiveOp(EdgesOp(), RecursiveMode.TRAIL, max_depth=3)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2", "e2", "n1")) in result
    assert Path(("n1", "e1", "n2", "e2", "n1", "e1", "n2")) not in result


def test_trail_without_max_depth_terminates_by_frontier_exhaustion() -> None:
    graph = build_cycle_graph()
    plan = RecursiveOp(EdgesOp(), RecursiveMode.TRAIL)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2", "e2", "n1")) in result
    assert len(result) == 7


def test_acyclic_rejects_repeated_nodes() -> None:
    graph = build_cycle_graph()
    plan = RecursiveOp(EdgesOp(), RecursiveMode.ACYCLIC)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2")) in result
    assert Path(("n1", "e1", "n2", "e3", "n3")) in result
    assert Path(("n1", "e1", "n2", "e2", "n1")) not in result


def test_simple_allows_only_closing_repeat_of_first_node() -> None:
    graph = build_cycle_graph()
    plan = RecursiveOp(EdgesOp(), RecursiveMode.SIMPLE, max_depth=3)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2", "e2", "n1")) in result
    assert Path(("n1", "e1", "n2", "e2", "n1", "e1", "n2")) not in result


def test_shortest_returns_all_tied_shortest_paths_per_source_target_pair() -> None:
    graph = build_shortest_graph()
    plan = RecursiveOp(EdgesOp(), RecursiveMode.SHORTEST, max_depth=2)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2")) in result
    assert Path(("n1", "e2", "n2")) in result
    assert Path(("n1", "e3", "n3")) in result
    assert Path(("n3", "e4", "n2")) in result
    assert Path(("n1", "e3", "n3", "e4", "n2")) not in result


def test_shortest_without_max_depth_terminates_on_finite_graph() -> None:
    graph = build_cycle_graph()
    plan = RecursiveOp(EdgesOp(), RecursiveMode.SHORTEST)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2")) in result
    assert Path(("n2", "e2", "n1")) in result
    assert Path(("n2", "e3", "n3")) in result
    assert Path(("n1", "e1", "n2", "e3", "n3")) in result


def test_max_depth_counts_child_paths_not_graph_edges() -> None:
    graph = build_cycle_graph()
    two_edge_child = JoinOp(EdgesOp(), EdgesOp())
    plan = RecursiveOp(two_edge_child, RecursiveMode.WALK, max_depth=1)

    result = evaluate(plan, graph)

    assert Path(("n1", "e1", "n2", "e3", "n3")) in result


def test_max_depth_must_be_positive() -> None:
    graph = build_cycle_graph()

    with pytest.raises(ValueError, match="max_depth must be positive"):
        evaluate(RecursiveOp(EdgesOp(), RecursiveMode.TRAIL, max_depth=0), graph)


def test_solution_space_operators_remain_unimplemented() -> None:
    graph = build_cycle_graph()

    future_ops = [
        GroupByOp(EdgesOp(), keys=("first",)),
        OrderByOp(EdgesOp(), keys=("length",)),
        ProjectionOp(EdgesOp(), fields=("first", "last")),
    ]

    for op in future_ops:
        with pytest.raises(NotImplementedError):
            evaluate(op, graph)
