from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError

import pytest

from xgap.algebra.conditions import And, EdgeRef, LabelEquals, NodeRef, PropertyEquals
from xgap.algebra.evaluator import evaluate_pathset
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import (
    AlgebraOp,
    EdgesOp,
    GroupKey,
    GroupByOp,
    JoinOp,
    NodesOp,
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
    PathMode,
    PathPatternQuery,
    PatternTypeError,
    PatternVarType,
    Plus,
    Rel,
    Selector,
    SelectorKind,
    Seq,
    Star,
    Var,
    apply_selector,
    infer_schema,
    lower_path_pattern,
    lower_regex,
    type_check_path_pattern,
)
import xgap.pattern.lowering as lowering_module


ALLOWED_OPERATOR_NAMES = {
    "Nodes",
    "Edges",
    "Selection",
    "Union",
    "Join",
    "Recursive",
    "GroupBy",
    "OrderBy",
    "Projection",
}


def query(
    *,
    path_var: Var | None = None,
    source: NodePattern | None = None,
    expr=None,
    target: NodePattern | None = None,
    selector: Selector | None = None,
    restrictor: PathMode = PathMode.TRAIL,
    condition=None,
    max_depth: int | None = None,
) -> PathPatternQuery:
    return PathPatternQuery(
        path_var=path_var,
        source=source or NodePattern(),
        expr=expr or Rel(EdgePattern(label="Knows")),
        target=target or NodePattern(),
        selector=selector or Selector(SelectorKind.ALL),
        restrictor=restrictor,
        condition=condition,
        max_depth=max_depth,
    )


def build_knows_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Alice"})
    graph.add_node("n2", label="Person", properties={"name": "Bob"})
    graph.add_node("n3", label="Person", properties={"name": "Carol"})
    graph.add_node("n4", label="Person", properties={"name": "Dana"})
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n2", "n3", label="Knows")
    graph.add_edge("e3", "n3", "n2", label="Knows")
    graph.add_edge("e4", "n2", "n4", label="Knows")
    return graph


def build_multi_label_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Alice"})
    graph.add_node("n2", label="Work", properties={"title": "Notebook"})
    graph.add_node("n3", label="Person", properties={"name": "Carol"})
    graph.add_node("n4", label="Person", properties={"name": "Bob"})
    graph.add_node("n5", label="Company", properties={"risk": "High"})
    graph.add_edge("likes", "n1", "n2", label="Likes")
    graph.add_edge("has_creator", "n2", "n3", label="Has_creator")
    graph.add_edge("knows", "n1", "n4", label="Knows")
    graph.add_edge("knows_company", "n1", "n5", label="Knows")
    return graph


def operator_names(plan: AlgebraOp) -> set[str]:
    names = {plan.operator_name()}
    for child in plan.children():
        names.update(operator_names(child))
    return names


def test_ast_rejects_invalid_inputs_and_is_frozen() -> None:
    with pytest.raises(ValueError):
        Var("")
    with pytest.raises(ValueError):
        Var("   ")
    with pytest.raises(ValueError):
        NodePattern(label="")
    with pytest.raises(ValueError):
        EdgePattern(label="")
    with pytest.raises(ValueError):
        NodePattern(properties={"": "Alice"})
    with pytest.raises(ValueError):
        EdgePattern(properties={"": "wire"})

    node = NodePattern(var=Var("x"), label="Person")
    with pytest.raises(FrozenInstanceError):
        node.label = "Company"  # type: ignore[misc]


@pytest.mark.parametrize(
    "selector",
    [
        Selector(SelectorKind.ANY_K),
        Selector(SelectorKind.ANY_K, 0),
        Selector(SelectorKind.SHORTEST_K),
        Selector(SelectorKind.SHORTEST_K, -1),
        Selector(SelectorKind.SHORTEST_K_GROUP),
        Selector(SelectorKind.SHORTEST_K_GROUP, 0),
    ],
)
def test_invalid_selector_k_is_rejected(selector: Selector) -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(selector=selector))


@pytest.mark.parametrize(
    "selector",
    [
        Selector(SelectorKind.ALL, 1),
        Selector(SelectorKind.ANY, 1),
        Selector(SelectorKind.ANY_SHORTEST, 1),
        Selector(SelectorKind.ALL_SHORTEST, 1),
    ],
)
def test_meaningless_selector_k_is_rejected(selector: Selector) -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(selector=selector))


def test_optional_and_bounded_regex_lowering_remain_unsupported() -> None:
    expr = Rel(EdgePattern(label="Knows"))

    with pytest.raises(LoweringError, match="OptionalExpr"):
        lower_regex(OptionalExpr(expr), RecursiveMode.TRAIL)
    with pytest.raises(LoweringError, match="Bounded"):
        lower_regex(Bounded(expr, 1, 2), RecursiveMode.TRAIL)


def test_type_checker_infers_and_rejects_expected_variable_schemas() -> None:
    pattern = query(
        path_var=Var("p"),
        source=NodePattern(var=Var("x")),
        expr=Rel(EdgePattern(var=Var("e"), label="Knows")),
        target=NodePattern(var=Var("y")),
    )

    assert infer_schema(pattern) == {
        "p": PatternVarType.PATH,
        "x": PatternVarType.NODE,
        "e": PatternVarType.EDGE,
        "y": PatternVarType.NODE,
    }

    assert type_check_path_pattern(
        query(source=NodePattern(var=Var("x")), target=NodePattern(var=Var("x")))
    ) == {"x": PatternVarType.NODE}

    with pytest.raises(PatternTypeError):
        type_check_path_pattern(
            query(source=NodePattern(var=Var("x")), expr=Rel(EdgePattern(var=Var("x"))))
        )
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(path_var=Var("p"), expr=Rel(EdgePattern(var=Var("p")))))


def test_type_checker_rejects_repeated_edge_vars_and_alt_schema_mismatches() -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(expr=Plus(Rel(EdgePattern(var=Var("e"))))))
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(expr=Star(Rel(EdgePattern(var=Var("e"))))))

    with pytest.raises(PatternTypeError):
        type_check_path_pattern(
            query(
                expr=Alt(
                    Rel(EdgePattern(var=Var("e"), label="Knows")),
                    Rel(EdgePattern(label="Likes")),
                )
            )
        )

    accepted = query(
        expr=Alt(
            Rel(EdgePattern(var=Var("e"), label="Knows")),
            Rel(EdgePattern(var=Var("e"), label="Likes")),
        )
    )
    assert type_check_path_pattern(accepted) == {"e": PatternVarType.EDGE}


def test_type_checker_accepts_seq_shared_edge_vars_and_rejects_conflicts() -> None:
    accepted = query(
        expr=Seq(
            Rel(EdgePattern(var=Var("e"), label="Likes")),
            Rel(EdgePattern(var=Var("e"), label="Has_creator")),
        )
    )
    assert type_check_path_pattern(accepted) == {"e": PatternVarType.EDGE}

    with pytest.raises(PatternTypeError):
        type_check_path_pattern(
            query(
                source=NodePattern(var=Var("x")),
                expr=Seq(Rel(EdgePattern(var=Var("x"))), Rel(EdgePattern(label="Knows"))),
            )
        )


def test_walk_recursive_regex_requires_positive_max_depth() -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(
            query(expr=Plus(Rel(EdgePattern(label="Knows"))), restrictor=PathMode.WALK)
        )

    accepted = query(
        expr=Star(Rel(EdgePattern(label="Knows"))),
        restrictor=PathMode.WALK,
        max_depth=2,
    )
    assert type_check_path_pattern(accepted) == {}

    with pytest.raises(LoweringError):
        lower_regex(Plus(Rel(EdgePattern(label="Knows"))), RecursiveMode.WALK)


def test_direction_audit() -> None:
    out_plan = lower_path_pattern(query(expr=Rel(EdgePattern(label="Knows", direction=Direction.OUT))))
    validate_plan(out_plan)

    for direction in (Direction.IN, Direction.UNDIRECTED):
        pattern = query(expr=Rel(EdgePattern(label="Knows", direction=direction)))
        assert type_check_path_pattern(pattern) == {}
        with pytest.raises(LoweringError, match="supports only OUT"):
            lower_path_pattern(pattern)


def test_regex_lowering_canonical_shapes() -> None:
    rel = lower_regex(Rel(EdgePattern(label="Knows")), RecursiveMode.TRAIL)
    assert isinstance(rel, SelectionOp)
    assert rel.condition == LabelEquals(EdgeRef(1), "Knows")
    assert isinstance(rel.child, EdgesOp)

    unconstrained = lower_regex(Rel(EdgePattern()), RecursiveMode.TRAIL)
    assert isinstance(unconstrained, EdgesOp)

    joined = lower_regex(
        Seq(Rel(EdgePattern(label="Likes")), Rel(EdgePattern(label="Has_creator"))),
        RecursiveMode.TRAIL,
    )
    assert isinstance(joined, JoinOp)

    unioned = lower_regex(
        Alt(Rel(EdgePattern(label="Knows")), Rel(EdgePattern(label="Likes"))),
        RecursiveMode.TRAIL,
    )
    assert isinstance(unioned, UnionOp)

    plus = lower_regex(Plus(Rel(EdgePattern(label="Knows"))), RecursiveMode.TRAIL)
    assert isinstance(plus, RecursiveOp)
    assert plus.mode is RecursiveMode.TRAIL

    star = lower_regex(Star(Rel(EdgePattern(label="Knows"))), RecursiveMode.TRAIL)
    assert isinstance(star, UnionOp)
    assert isinstance(star.left, NodesOp)
    assert isinstance(star.right, RecursiveOp)

    for plan in (rel, unconstrained, joined, unioned, plus, star):
        validate_plan(plan)
        assert operator_names(plan) <= ALLOWED_OPERATOR_NAMES


def test_rel_label_and_properties_lower_to_conjoined_edge_conditions() -> None:
    plan = lower_regex(
        Rel(EdgePattern(label="Knows", properties={"since": 2020, "kind": "social"})),
        RecursiveMode.TRAIL,
    )

    assert isinstance(plan, SelectionOp)
    assert isinstance(plan.condition, And)
    assert plan.condition.conditions == (
        LabelEquals(EdgeRef(1), "Knows"),
        PropertyEquals(EdgeRef(1), "since", 2020),
        PropertyEquals(EdgeRef(1), "kind", "social"),
    )


def test_descriptor_lowering_uses_first_and_last_before_selector() -> None:
    plan = lower_path_pattern(
        query(
            source=NodePattern(label="Person", properties={"name": "Alice"}),
            expr=Plus(Rel(EdgePattern(label="Knows"))),
            target=NodePattern(label="Company", properties={"risk": "High"}),
            selector=Selector(SelectorKind.ANY_SHORTEST),
        )
    )

    assert isinstance(plan, ProjectionOp)
    assert isinstance(plan.child, OrderByOp)
    assert isinstance(plan.child.child, GroupByOp)
    target_selection = plan.child.child.child
    assert isinstance(target_selection, SelectionOp)
    assert target_selection.condition == And(
        LabelEquals(NodeRef.last(), "Company"),
        PropertyEquals(NodeRef.last(), "risk", "High"),
    )
    source_selection = target_selection.child
    assert isinstance(source_selection, SelectionOp)
    assert source_selection.condition == And(
        LabelEquals(NodeRef.first(), "Person"),
        PropertyEquals(NodeRef.first(), "name", "Alice"),
    )


@pytest.mark.parametrize(
    ("selector", "expected_format"),
    [
        (
            Selector(SelectorKind.ALL),
            "\n".join(["Projection [*, *, *]", "  GroupBy [NONE]", "    Edges"]),
        ),
        (
            Selector(SelectorKind.ANY),
            "\n".join(["Projection [*, *, 1]", "  GroupBy [SOURCE_TARGET]", "    Edges"]),
        ),
        (
            Selector(SelectorKind.ANY_K, 2),
            "\n".join(["Projection [*, *, 2]", "  GroupBy [SOURCE_TARGET]", "    Edges"]),
        ),
        (
            Selector(SelectorKind.ANY_SHORTEST),
            "\n".join(
                [
                    "Projection [*, *, 1]",
                    "  OrderBy [PATH]",
                    "    GroupBy [SOURCE_TARGET]",
                    "      Edges",
                ]
            ),
        ),
        (
            Selector(SelectorKind.ALL_SHORTEST),
            "\n".join(
                [
                    "Projection [*, 1, *]",
                    "  OrderBy [GROUP]",
                    "    GroupBy [SOURCE_TARGET_LENGTH]",
                    "      Edges",
                ]
            ),
        ),
        (
            Selector(SelectorKind.SHORTEST_K, 2),
            "\n".join(
                [
                    "Projection [*, *, 2]",
                    "  OrderBy [PATH]",
                    "    GroupBy [SOURCE_TARGET]",
                    "      Edges",
                ]
            ),
        ),
        (
            Selector(SelectorKind.SHORTEST_K_GROUP, 2),
            "\n".join(
                [
                    "Projection [*, 2, *]",
                    "  OrderBy [GROUP]",
                    "    GroupBy [SOURCE_TARGET_LENGTH]",
                    "      Edges",
                ]
            ),
        ),
    ],
)
def test_selector_mapping_is_deterministic(selector: Selector, expected_format: str) -> None:
    first = apply_selector(EdgesOp(), selector)
    second = apply_selector(EdgesOp(), selector)

    assert format_plan(first) == expected_format
    assert format_plan(second) == expected_format


def test_full_any_shortest_trail_pipeline_shape_and_evaluation() -> None:
    plan = lower_path_pattern(
        query(
            path_var=Var("p"),
            source=NodePattern(var=Var("x")),
            expr=Plus(Rel(EdgePattern(label="Knows", direction=Direction.OUT))),
            target=NodePattern(var=Var("y")),
            selector=Selector(SelectorKind.ANY_SHORTEST),
            restrictor=PathMode.TRAIL,
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
    result = evaluate_pathset(plan, build_knows_graph())
    assert Path.one_length("n1", "e1", "n2") in result
    assert Path(("n1", "e1", "n2", "e2", "n3")) in result


def test_full_all_shortest_acyclic_pipeline_shape_and_evaluation() -> None:
    plan = lower_path_pattern(
        query(
            expr=Plus(Rel(EdgePattern(label="Knows"))),
            selector=Selector(SelectorKind.ALL_SHORTEST),
            restrictor=PathMode.ACYCLIC,
        )
    )

    assert format_plan(plan) == "\n".join(
        [
            "Projection [*, 1, *]",
            "  OrderBy [GROUP]",
            "    GroupBy [SOURCE_TARGET_LENGTH]",
            "      Recursive [mode=ACYCLIC]",
            "        Selection [label(edge(1)) = \"Knows\"]",
            "          Edges",
        ]
    )
    validate_plan(plan)
    result = evaluate_pathset(plan, build_knows_graph())
    assert Path.one_length("n1", "e1", "n2") in result
    assert Path(("n1", "e1", "n2", "e2", "n3")) in result


def test_full_star_pipeline_shape_includes_nodes_union() -> None:
    plan = lower_path_pattern(
        query(
            expr=Star(Rel(EdgePattern(label="Knows"))),
            selector=Selector(SelectorKind.ALL),
            restrictor=PathMode.TRAIL,
        )
    )

    formatted = format_plan(plan)
    assert "Union\n      Nodes\n      Recursive [mode=TRAIL]" in formatted
    validate_plan(plan)
    assert Path.zero_length("n1") in evaluate_pathset(plan, build_knows_graph())


def test_lowering_is_deterministic_for_regex_and_full_queries() -> None:
    expressions = [
        Rel(EdgePattern(label="Knows")),
        Seq(Rel(EdgePattern(label="Likes")), Rel(EdgePattern(label="Has_creator"))),
        Alt(Rel(EdgePattern(label="Knows")), Rel(EdgePattern(label="Likes"))),
        Plus(Rel(EdgePattern(label="Knows"))),
        Star(Rel(EdgePattern(label="Knows"))),
    ]
    queries = [query(expr=expr) for expr in expressions]
    queries.extend(
        [
            query(
                expr=Plus(Rel(EdgePattern(label="Knows"))),
                selector=Selector(SelectorKind.ANY_SHORTEST),
            ),
            query(
                source=NodePattern(label="Person", properties={"name": "Alice"}),
                expr=Plus(Rel(EdgePattern(label="Knows"))),
                target=NodePattern(label="Company", properties={"risk": "High"}),
                selector=Selector(SelectorKind.ANY_SHORTEST),
            ),
        ]
    )

    for pattern in queries:
        expected = format_plan(lower_path_pattern(pattern))
        assert format_plan(lower_path_pattern(pattern)) == expected
        assert format_plan(lower_path_pattern(pattern)) == expected


def test_lowered_plans_reference_evaluation_audit() -> None:
    multi = build_multi_label_graph()
    knows = lower_regex(Rel(EdgePattern(label="Knows")), RecursiveMode.TRAIL)
    assert evaluate_pathset(knows, multi).sorted() == (
        Path.one_length("n1", "knows", "n4"),
        Path.one_length("n1", "knows_company", "n5"),
    )

    seq = lower_regex(
        Seq(Rel(EdgePattern(label="Likes")), Rel(EdgePattern(label="Has_creator"))),
        RecursiveMode.TRAIL,
    )
    assert evaluate_pathset(seq, multi).sorted() == (
        Path(("n1", "likes", "n2", "has_creator", "n3")),
    )

    alt = lower_regex(
        Alt(Rel(EdgePattern(label="Knows")), Rel(EdgePattern(label="Likes"))),
        RecursiveMode.TRAIL,
    )
    assert evaluate_pathset(alt, multi).sorted() == (
        Path.one_length("n1", "knows", "n4"),
        Path.one_length("n1", "knows_company", "n5"),
        Path.one_length("n1", "likes", "n2"),
    )

    star = lower_regex(Star(Rel(EdgePattern(label="Knows"))), RecursiveMode.TRAIL)
    assert Path.zero_length("n1") in evaluate_pathset(star, build_knows_graph())

    source_filtered = lower_path_pattern(
        query(
            source=NodePattern(label="Person", properties={"name": "Alice"}),
            expr=Rel(EdgePattern(label="Likes")),
            selector=Selector(SelectorKind.ALL),
        )
    )
    assert evaluate_pathset(source_filtered, multi).sorted() == (
        Path.one_length("n1", "likes", "n2"),
    )

    target_filtered = lower_path_pattern(
        query(
            expr=Rel(EdgePattern(label="Knows")),
            target=NodePattern(label="Company", properties={"risk": "High"}),
            selector=Selector(SelectorKind.ALL),
        )
    )
    assert evaluate_pathset(target_filtered, multi).sorted() == (
        Path.one_length("n1", "knows_company", "n5"),
    )


def test_lowering_layer_does_not_call_future_runtime_layers() -> None:
    source = inspect.getsource(lowering_module)

    assert "xgap.algebra.evaluator" not in source
    assert "xgap.llm" not in source
    assert "xgap.compilers" not in source
    assert "compile_" not in source
