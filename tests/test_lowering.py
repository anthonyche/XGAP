import pytest

from xgap.algebra.conditions import EdgeRef, LabelEquals, NodeRef, PropertyEquals
from xgap.algebra.evaluator import evaluate_pathset
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import (
    EdgesOp,
    GroupKey,
    GroupByOp,
    JoinOp,
    OrderKey,
    OrderByOp,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)
from xgap.algebra.pretty import format_plan
from xgap.algebra.types import Path
from xgap.algebra.validation import validate_plan
from xgap.pattern import (
    Alt,
    Bounded,
    Direction,
    EdgePattern,
    LoweringError,
    NodePattern,
    OptionalExpr,
    PathPatternQuery,
    Plus,
    Rel,
    Selector,
    SelectorKind,
    Seq,
    Star,
    Var,
    apply_selector,
    lower_path_pattern,
    lower_regex,
)


def build_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Moe"})
    graph.add_node("n2", label="Person", properties={"name": "Bart"})
    graph.add_node("n3", label="Person", properties={"name": "Lisa"})
    graph.add_node("n4", label="Person", properties={"name": "Apu"})
    graph.add_edge("e1", "n1", "n2", label="Knows", properties={"kind": "casual"})
    graph.add_edge("e2", "n2", "n3", label="Knows", properties={"kind": "casual"})
    graph.add_edge("e3", "n3", "n2", label="Likes", properties={"kind": "social"})
    graph.add_edge("e4", "n2", "n4", label="Transfer", properties={"kind": "wire"})
    graph.add_edge("e5", "n1", "n3", label="Has_creator", properties={"kind": "metadata"})
    return graph


def pattern_query(
    *,
    source: NodePattern | None = None,
    expr=None,
    target: NodePattern | None = None,
    selector: Selector | None = None,
    restrictor: RecursiveMode = RecursiveMode.TRAIL,
    condition=None,
    max_depth: int | None = None,
) -> PathPatternQuery:
    return PathPatternQuery(
        path_var=Var("p"),
        source=source or NodePattern(var=Var("x")),
        expr=expr or Rel(EdgePattern(label="Knows")),
        target=target or NodePattern(var=Var("y")),
        selector=selector or Selector(SelectorKind.ALL),
        restrictor=restrictor,
        condition=condition,
        max_depth=max_depth,
    )


def test_rel_with_label_lowers_to_selection_over_edges() -> None:
    plan = lower_regex(Rel(EdgePattern(label="Knows")), RecursiveMode.TRAIL)

    assert isinstance(plan, SelectionOp)
    assert plan.condition == LabelEquals(EdgeRef(1), "Knows")
    assert isinstance(plan.child, EdgesOp)
    validate_plan(plan)
    assert evaluate_pathset(plan, build_graph()).sorted() == (
        Path.one_length("n1", "e1", "n2"),
        Path.one_length("n2", "e2", "n3"),
    )


def test_rel_without_constraints_lowers_to_edges() -> None:
    plan = lower_regex(Rel(EdgePattern()), RecursiveMode.TRAIL)

    assert isinstance(plan, EdgesOp)
    validate_plan(plan)


def test_rel_with_label_and_property_conjoins_conditions() -> None:
    plan = lower_regex(
        Rel(EdgePattern(label="Transfer", properties={"kind": "wire"})),
        RecursiveMode.TRAIL,
    )

    validate_plan(plan)
    assert evaluate_pathset(plan, build_graph()).sorted() == (
        Path.one_length("n2", "e4", "n4"),
    )


def test_seq_lowers_to_join_and_evaluates_two_step_paths() -> None:
    plan = lower_regex(
        Seq(
            Rel(EdgePattern(label="Knows")),
            Rel(EdgePattern(label="Transfer")),
        ),
        RecursiveMode.TRAIL,
    )

    assert isinstance(plan, JoinOp)
    assert evaluate_pathset(plan, build_graph()).sorted() == (
        Path(("n1", "e1", "n2", "e4", "n4")),
    )


def test_alt_lowers_to_union_and_evaluates_both_labels() -> None:
    plan = lower_regex(
        Alt(Rel(EdgePattern(label="Knows")), Rel(EdgePattern(label="Likes"))),
        RecursiveMode.TRAIL,
    )

    assert isinstance(plan, UnionOp)
    assert evaluate_pathset(plan, build_graph()).sorted() == (
        Path.one_length("n1", "e1", "n2"),
        Path.one_length("n2", "e2", "n3"),
        Path.one_length("n3", "e3", "n2"),
    )


def test_plus_lowers_to_recursive() -> None:
    plan = lower_regex(Plus(Rel(EdgePattern(label="Knows"))), RecursiveMode.TRAIL)

    assert isinstance(plan, RecursiveOp)
    validate_plan(plan)
    result = evaluate_pathset(plan, build_graph())
    assert Path(("n1", "e1", "n2", "e2", "n3")) in result


def test_star_lowers_to_union_nodes_recursive_and_includes_zero_length_paths() -> None:
    plan = lower_regex(Star(Rel(EdgePattern(label="Knows"))), RecursiveMode.TRAIL)

    assert isinstance(plan, UnionOp)
    validate_plan(plan)
    result = evaluate_pathset(plan, build_graph())
    assert Path.zero_length("n1") in result
    assert Path(("n1", "e1", "n2", "e2", "n3")) in result


def test_empty_relation_label_and_unsupported_regex_nodes_are_rejected() -> None:
    with pytest.raises(ValueError):
        EdgePattern(label="")

    with pytest.raises(LoweringError):
        lower_regex(OptionalExpr(Rel(EdgePattern(label="Knows"))), RecursiveMode.TRAIL)

    with pytest.raises(LoweringError):
        lower_regex(Bounded(Rel(EdgePattern(label="Knows")), 1, 2), RecursiveMode.TRAIL)


def test_in_and_undirected_directions_are_rejected_by_lowering() -> None:
    for direction in (Direction.IN, Direction.UNDIRECTED):
        with pytest.raises(LoweringError):
            lower_path_pattern(pattern_query(expr=Rel(EdgePattern(label="Knows", direction=direction))))


def test_descriptor_lowering_filters_source_and_target() -> None:
    plan = lower_path_pattern(
        pattern_query(
            source=NodePattern(var=Var("x"), label="Person", properties={"name": "Moe"}),
            expr=Plus(Rel(EdgePattern(label="Knows"))),
            target=NodePattern(var=Var("y"), label="Person", properties={"name": "Lisa"}),
            selector=Selector(SelectorKind.ALL),
        )
    )

    validate_plan(plan)
    assert evaluate_pathset(plan, build_graph()).sorted() == (
        Path(("n1", "e1", "n2", "e2", "n3")),
    )


def test_optional_path_level_condition_wraps_before_selector() -> None:
    plan = lower_path_pattern(
        pattern_query(
            expr=Plus(Rel(EdgePattern(label="Knows"))),
            selector=Selector(SelectorKind.ALL),
            condition=PropertyEquals(NodeRef.first(), "name", "Moe"),
        )
    )

    assert evaluate_pathset(plan, build_graph()).sorted() == (
        Path.one_length("n1", "e1", "n2"),
        Path(("n1", "e1", "n2", "e2", "n3")),
    )


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        (Selector(SelectorKind.ALL), (None, None, None, GroupKey.NONE, None)),
        (Selector(SelectorKind.ANY), (None, None, 1, GroupKey.SOURCE_TARGET, None)),
        (Selector(SelectorKind.ANY_K, 2), (None, None, 2, GroupKey.SOURCE_TARGET, None)),
        (Selector(SelectorKind.ANY_SHORTEST), (None, None, 1, GroupKey.SOURCE_TARGET, OrderKey.PATH)),
        (Selector(SelectorKind.ALL_SHORTEST), (None, 1, None, GroupKey.SOURCE_TARGET_LENGTH, OrderKey.GROUP)),
        (Selector(SelectorKind.SHORTEST_K, 2), (None, None, 2, GroupKey.SOURCE_TARGET, OrderKey.PATH)),
        (Selector(SelectorKind.SHORTEST_K_GROUP, 2), (None, 2, None, GroupKey.SOURCE_TARGET_LENGTH, OrderKey.GROUP)),
    ],
)
def test_selector_lowering(selector: Selector, expected: tuple[object, ...]) -> None:
    plan = apply_selector(EdgesOp(), selector)
    num_partitions, num_groups, num_paths, group_key, order_key = expected

    assert isinstance(plan, ProjectionOp)
    assert (plan.num_partitions, plan.num_groups, plan.num_paths) == (
        num_partitions,
        num_groups,
        num_paths,
    )
    child = plan.child
    if order_key is None:
        assert isinstance(child, GroupByOp)
        assert child.group_key() is group_key
    else:
        assert isinstance(child, OrderByOp)
        assert child.order_key() is order_key
        assert isinstance(child.child, GroupByOp)
        assert child.child.group_key() is group_key


def test_invalid_selector_k_values_are_rejected_by_lowering() -> None:
    with pytest.raises(LoweringError):
        apply_selector(EdgesOp(), Selector(SelectorKind.ANY_K, 0))
    with pytest.raises(LoweringError):
        apply_selector(EdgesOp(), Selector(SelectorKind.ALL, 1))


def test_full_any_shortest_trail_query_lowers_validates_and_evaluates() -> None:
    plan = lower_path_pattern(
        PathPatternQuery(
            path_var=Var("p"),
            source=NodePattern(var=Var("x")),
            expr=Plus(Rel(EdgePattern(label="Knows", direction=Direction.OUT))),
            target=NodePattern(var=Var("y")),
            selector=Selector(SelectorKind.ANY_SHORTEST),
            restrictor=RecursiveMode.TRAIL,
        )
    )

    assert format_plan(plan) == "\n".join(
        [
            "Projection [*, *, 1]",
            "  OrderBy [PATH]",
            "    GroupBy [SOURCE_TARGET]",
            "      Recursive [mode=TRAIL]",
            "        Selection [label(edge(1)) = \"Knows\"]",
            "          Edges",
        ]
    )
    validate_plan(plan)
    result = evaluate_pathset(plan, build_graph())
    assert Path.one_length("n1", "e1", "n2") in result
    assert Path(("n1", "e1", "n2", "e2", "n3")) in result
