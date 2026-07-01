from xgap.algebra.ops import AntiSemiJoinOp, FocusProjectionOp, QuantifiedCheckOp
from xgap.algebra.pretty import format_plan
from xgap.algebra.validation import validate_plan
from xgap.pattern import (
    Direction,
    FocusedEdgePattern,
    FocusedNodePattern,
    FocusedQuantifiedPatternQuery,
    PropertyPredicate,
    QuantifiedPatternEdge,
    ScalarComparator,
    Var,
    count_ge,
    none,
    ratio_ge,
)
from xgap.pattern.quantified_lowering import lower_focused_quantified_pattern


def node(name: str, label: str | None = None) -> FocusedNodePattern:
    return FocusedNodePattern(Var(name), label)


def edge(parent: str, child: str, label: str, quantifier, edge_var: str | None = None):
    return QuantifiedPatternEdge(
        Var(parent),
        Var(child),
        FocusedEdgePattern(Var(edge_var) if edge_var else None, label),
        Direction.OUT,
        quantifier,
    )


def query(edges) -> FocusedQuantifiedPatternQuery:
    labels = {"x": "Account", "a": "HighRisk", "b": "Blocked"}
    names = sorted({"x"} | {item.parent_var.name for item in edges} | {item.child_var.name for item in edges})
    return FocusedQuantifiedPatternQuery(
        Var("x"),
        tuple(node(name, labels.get(name)) for name in names),
        tuple(edges),
    )


def test_count_lowering_uses_quantified_check_and_full_candidate_correlation() -> None:
    plan = lower_focused_quantified_pattern(query((edge("x", "a", "Transfer", count_ge(2), "e"),)))

    assert isinstance(plan, FocusProjectionOp)
    assert "QuantifiedCheck [COUNT GE 2; corr=x; child=a; domain=no]" in format_plan(plan)
    validate_plan(plan)


def test_ratio_lowering_has_domain_and_is_deterministic() -> None:
    pattern = query((edge("x", "a", "Transfer", ratio_ge("4/5"), "e"),))

    first = lower_focused_quantified_pattern(pattern)
    second = lower_focused_quantified_pattern(pattern)

    formatted = format_plan(first)
    assert formatted == format_plan(second)
    assert "QuantifiedCheck [RATIO GE 4/5; corr=x; child=a; domain=yes]" in formatted
    validate_plan(first)


def test_none_lowering_uses_anti_semi_join_not_scalar_not() -> None:
    plan = lower_focused_quantified_pattern(query((edge("x", "b", "Transfer", none(), "e"),)))

    assert isinstance(plan.child, AntiSemiJoinOp)
    assert "AntiSemiJoin [on=x]" in format_plan(plan)
    assert "NOT" not in format_plan(plan)
    validate_plan(plan)


def test_branch_sorting_is_independent_of_input_order() -> None:
    first_pattern = query(
        (
            edge("x", "b", "Transfer", none(), "bad"),
            edge("x", "a", "Transfer", count_ge(2), "good"),
        )
    )
    second_pattern = query(
        (
            edge("x", "a", "Transfer", count_ge(2), "good"),
            edge("x", "b", "Transfer", none(), "bad"),
        )
    )

    assert format_plan(lower_focused_quantified_pattern(first_pattern)) == format_plan(
        lower_focused_quantified_pattern(second_pattern)
    )


def test_nested_correlation_uses_full_candidate_schema() -> None:
    pattern = FocusedQuantifiedPatternQuery(
        Var("x"),
        (node("x", "Account"), node("y", "HighRisk"), node("z", "Normal")),
        (
            edge("x", "y", "Transfer", count_ge(1), "e1"),
            QuantifiedPatternEdge(
                Var("y"),
                Var("z"),
                FocusedEdgePattern(
                    Var("e2"),
                    "Reviews",
                    (PropertyPredicate("score", ScalarComparator.GE, 0.8),),
                ),
                Direction.OUT,
                count_ge(1),
            ),
        ),
    )

    formatted = format_plan(lower_focused_quantified_pattern(pattern))

    assert "QuantifiedCheck [EXISTS; corr=x,e1,y; child=z; domain=no]" in formatted
    assert "QuantifiedCheck [EXISTS; corr=x; child=y; domain=no]" in formatted
