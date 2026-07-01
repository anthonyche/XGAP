from xgap.algebra.conditions import EdgeRef, LabelEquals
from xgap.algebra.ops import (
    AntiSemiJoinOp,
    BindEdgeOp,
    BindNodeOp,
    BindingJoinOp,
    BindingProjectOp,
    EdgesOp,
    FocusProjectionOp,
    GroupKey,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderKey,
    OrderByOp,
    OutputKind,
    ProjectionOp,
    QuantifiedCheckOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)


class FakeQuantifier:
    kind = "EXISTS"
    comparator = None
    threshold = None


def test_nodes_metadata() -> None:
    op = NodesOp()

    assert op.output_kind() is OutputKind.PATH_SET
    assert op.children() == ()
    assert op.operator_name() == "Nodes"


def test_edges_metadata() -> None:
    op = EdgesOp()

    assert op.output_kind() is OutputKind.PATH_SET
    assert op.children() == ()
    assert op.operator_name() == "Edges"


def test_selection_metadata() -> None:
    child = EdgesOp()
    op = SelectionOp(LabelEquals(EdgeRef(1), "Knows"), child)

    assert op.output_kind() is OutputKind.PATH_SET
    assert op.children() == (child,)
    assert op.operator_name() == "Selection"


def test_union_metadata() -> None:
    left = NodesOp()
    right = EdgesOp()
    op = UnionOp(left, right)

    assert op.output_kind() is OutputKind.PATH_SET
    assert op.children() == (left, right)
    assert op.operator_name() == "Union"


def test_join_metadata() -> None:
    left = EdgesOp()
    right = EdgesOp()
    op = JoinOp(left, right)

    assert op.output_kind() is OutputKind.PATH_SET
    assert op.children() == (left, right)
    assert op.operator_name() == "Join"


def test_recursive_metadata() -> None:
    child = EdgesOp()
    op = RecursiveOp(child, RecursiveMode.TRAIL, max_depth=3)

    assert op.output_kind() is OutputKind.PATH_SET
    assert op.children() == (child,)
    assert op.operator_name() == "Recursive"


def test_group_by_metadata() -> None:
    child = EdgesOp()
    op = GroupByOp(child, GroupKey.SOURCE_TARGET)

    assert op.output_kind() is OutputKind.SOLUTION_SPACE
    assert op.children() == (child,)
    assert op.operator_name() == "GroupBy"
    assert op.group_key() is GroupKey.SOURCE_TARGET


def test_order_by_metadata() -> None:
    child = GroupByOp(EdgesOp(), GroupKey.SOURCE_TARGET)
    op = OrderByOp(child, OrderKey.PATH)

    assert op.output_kind() is OutputKind.SOLUTION_SPACE
    assert op.children() == (child,)
    assert op.operator_name() == "OrderBy"
    assert op.order_key() is OrderKey.PATH


def test_projection_metadata() -> None:
    child = OrderByOp(GroupByOp(EdgesOp(), GroupKey.SOURCE_TARGET), OrderKey.PATH)
    op = ProjectionOp(child, num_partitions=None, num_groups=None, num_paths=1)

    assert op.output_kind() is OutputKind.PATH_SET
    assert op.children() == (child,)
    assert op.operator_name() == "Projection"


def test_focused_binding_operator_metadata() -> None:
    edges = EdgesOp()
    nodes = NodesOp()
    bind_node = BindNodeOp("x", nodes)
    bind_edge = BindEdgeOp("x", "e", "y", edges)
    joined = BindingJoinOp(bind_node, bind_edge)
    projected = BindingProjectOp(("x",), joined)
    checked = QuantifiedCheckOp(projected, joined, FakeQuantifier(), ("x",), "y")
    anti = AntiSemiJoinOp(projected, joined, ("x",))
    focused = FocusProjectionOp("x", projected)

    assert bind_node.output_kind() is OutputKind.BINDING_RELATION
    assert bind_node.children() == (nodes,)
    assert bind_node.operator_name() == "BindNode"
    assert bind_edge.output_kind() is OutputKind.BINDING_RELATION
    assert bind_edge.children() == (edges,)
    assert bind_edge.operator_name() == "BindEdge"
    assert joined.output_kind() is OutputKind.BINDING_RELATION
    assert joined.children() == (bind_node, bind_edge)
    assert joined.operator_name() == "BindingJoin"
    assert checked.output_kind() is OutputKind.BINDING_RELATION
    assert checked.children() == (projected, joined)
    assert anti.output_kind() is OutputKind.BINDING_RELATION
    assert anti.children() == (projected, joined)
    assert focused.output_kind() is OutputKind.PATH_SET
    assert focused.children() == (projected,)
