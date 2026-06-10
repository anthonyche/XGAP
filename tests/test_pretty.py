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
)
from xgap.algebra.ops import EdgesOp, JoinOp, NodesOp, RecursiveMode, RecursiveOp, SelectionOp, UnionOp
from xgap.algebra.ops import GroupKey, GroupByOp, OrderKey, OrderByOp, ProjectionOp
from xgap.algebra.pretty import format_plan


def test_format_plan_stable_tree() -> None:
    knows_edges = SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp())
    plan = UnionOp(knows_edges, JoinOp(knows_edges, EdgesOp()))

    assert format_plan(plan) == "\n".join(
        [
            "Union",
            "  Selection [label(edge(1)) = \"Knows\"]",
            "    Edges",
            "  Join",
            "    Selection [label(edge(1)) = \"Knows\"]",
            "      Edges",
            "    Edges",
        ]
    )


def test_format_plan_node_and_property_conditions() -> None:
    condition = And(
        PropertyEquals(NodeRef.first(), "name", "Moe"),
        Or(
            LengthEquals(2),
            Not(LabelEquals(NodeRef.last(), "Person")),
        ),
    )
    plan = SelectionOp(condition, NodesOp())

    assert format_plan(plan) == "\n".join(
        [
            "Selection [(first.name = \"Moe\" AND (len() = 2 OR (NOT label(last) = \"Person\")))]",
            "  Nodes",
        ]
    )


def test_format_plan_edge_property_and_indexed_node_conditions() -> None:
    condition = And(
        PropertyEquals(EdgeRef(2), "since", 2002),
        LabelEquals(NodeRef(2), "Person"),
    )
    plan = SelectionOp(condition, EdgesOp())

    assert format_plan(plan) == "\n".join(
        [
            "Selection [(edge(2).since = 2002 AND label(node(2)) = \"Person\")]",
            "  Edges",
        ]
    )


def test_format_recursive_plan_includes_mode_and_max_depth() -> None:
    plan = RecursiveOp(EdgesOp(), RecursiveMode.WALK, max_depth=3)

    assert format_plan(plan) == "\n".join(
        [
            "Recursive [mode=WALK, max_depth=3]",
            "  Edges",
        ]
    )


def test_format_recursive_plan_without_max_depth() -> None:
    plan = RecursiveOp(EdgesOp(), RecursiveMode.TRAIL)

    assert format_plan(plan) == "\n".join(
        [
            "Recursive [mode=TRAIL]",
            "  Edges",
        ]
    )


def test_format_solution_space_plan() -> None:
    plan = ProjectionOp(
        OrderByOp(
            GroupByOp(
                RecursiveOp(EdgesOp(), RecursiveMode.TRAIL),
                GroupKey.SOURCE_TARGET,
            ),
            OrderKey.PATH,
        ),
        num_partitions=None,
        num_groups=None,
        num_paths=1,
    )

    assert format_plan(plan) == "\n".join(
        [
            "Projection [*, *, 1]",
            "  OrderBy [PATH]",
            "    GroupBy [SOURCE_TARGET]",
            "      Recursive [mode=TRAIL]",
            "        Edges",
        ]
    )


def test_format_plan_rejects_unknown_condition() -> None:
    class UnknownCondition:
        pass

    with pytest.raises(NotImplementedError):
        format_plan(SelectionOp(UnknownCondition(), EdgesOp()))  # type: ignore[arg-type]
