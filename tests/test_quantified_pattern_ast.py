from fractions import Fraction

import pytest

from xgap.pattern import (
    Direction,
    FocusedEdgePattern,
    FocusedNodePattern,
    FocusedQuantifiedPatternQuery,
    PropertyPredicate,
    QuantifiedPatternEdge,
    QuantifiedPatternTypeError,
    QuantifierComparator,
    QuantifierKind,
    ScalarComparator,
    Var,
    all_matches,
    count_eq,
    count_ge,
    exists,
    none,
    ratio_eq,
    ratio_ge,
    type_check_focused_quantified_pattern,
)
from xgap.pattern.types import PatternVarType


def node(name: str, label: str | None = None) -> FocusedNodePattern:
    return FocusedNodePattern(Var(name), label)


def edge(parent: str, child: str, edge_var: str | None = None, quantifier=None) -> QuantifiedPatternEdge:
    return QuantifiedPatternEdge(
        Var(parent),
        Var(child),
        FocusedEdgePattern(Var(edge_var) if edge_var else None, label="Transfer"),
        Direction.OUT,
        quantifier or exists(),
    )


def query(*nodes, edges=(), focus: str = "x") -> FocusedQuantifiedPatternQuery:
    return FocusedQuantifiedPatternQuery(Var(focus), tuple(nodes), tuple(edges))


def test_scalar_predicate_validation() -> None:
    assert PropertyPredicate("amount", ScalarComparator.GE, 100).value == 100
    assert PropertyPredicate("status", ScalarComparator.NE, "Cancelled").value == "Cancelled"

    with pytest.raises(ValueError):
        PropertyPredicate("", ScalarComparator.EQ, 1)
    with pytest.raises(ValueError):
        PropertyPredicate("amount", ScalarComparator.GE, True)
    with pytest.raises(ValueError):
        PropertyPredicate("amount", ScalarComparator.LT, "large")
    with pytest.raises(ValueError):
        PropertyPredicate("amount", ScalarComparator.GT, float("inf"))
    with pytest.raises(ValueError):
        PropertyPredicate("status", ScalarComparator.EQ, None)


def test_focused_descriptor_validation() -> None:
    with pytest.raises(ValueError):
        FocusedNodePattern(Var("x"), label="")
    with pytest.raises(ValueError):
        FocusedEdgePattern(label="")
    with pytest.raises(TypeError):
        FocusedNodePattern("x")  # type: ignore[arg-type]


def test_quantifier_constructors_and_canonicalization() -> None:
    assert exists().kind is QuantifierKind.EXISTS
    assert count_eq(1).kind is QuantifierKind.COUNT
    assert count_eq(1).comparator is QuantifierComparator.EQ
    assert count_ge(1) == exists()
    assert ratio_eq(1) == all_matches()
    assert ratio_ge(1) == all_matches()
    assert ratio_ge(0.8).threshold == Fraction(4, 5)
    assert ratio_eq("1/4").threshold == Fraction(1, 4)
    assert none().kind is QuantifierKind.NONE

    with pytest.raises(ValueError):
        count_eq(0)
    with pytest.raises(ValueError):
        count_ge(-1)
    with pytest.raises(TypeError):
        ratio_eq(True)
    with pytest.raises(ValueError):
        ratio_ge(0)
    with pytest.raises(ValueError):
        ratio_ge(Fraction(6, 5))


def test_valid_focused_rooted_tree_type_checks() -> None:
    pattern = query(
        node("x", "Account"),
        node("y", "Account"),
        node("z", "Risk"),
        edges=(edge("x", "y", "e", count_ge(2)), edge("y", "z", "e2", exists())),
    )

    assert type_check_focused_quantified_pattern(pattern) == {
        "x": PatternVarType.NODE,
        "y": PatternVarType.NODE,
        "z": PatternVarType.NODE,
        "e": PatternVarType.EDGE,
        "e2": PatternVarType.EDGE,
    }


def test_focus_only_query_is_valid() -> None:
    pattern = query(node("x", "Account"))

    assert type_check_focused_quantified_pattern(pattern) == {"x": PatternVarType.NODE}


def test_typecheck_rejects_missing_focus_and_undeclared_variables() -> None:
    with pytest.raises(QuantifiedPatternTypeError, match="Focus"):
        type_check_focused_quantified_pattern(query(node("y"), focus="x"))
    with pytest.raises(QuantifiedPatternTypeError, match="Undeclared parent"):
        type_check_focused_quantified_pattern(query(node("x"), node("y"), edges=(edge("z", "y"),)))
    with pytest.raises(QuantifiedPatternTypeError, match="Undeclared child"):
        type_check_focused_quantified_pattern(query(node("x"), edges=(edge("x", "y"),)))


def test_typecheck_rejects_duplicate_nodes_edge_vars_and_variable_kind_conflicts() -> None:
    with pytest.raises(QuantifiedPatternTypeError, match="Duplicate node"):
        type_check_focused_quantified_pattern(query(node("x"), node("x")))
    with pytest.raises(QuantifiedPatternTypeError, match="Duplicate edge"):
        type_check_focused_quantified_pattern(
            query(node("x"), node("y"), node("z"), edges=(edge("x", "y", "e"), edge("y", "z", "e")))
        )
    with pytest.raises(QuantifiedPatternTypeError, match="cannot be both"):
        type_check_focused_quantified_pattern(query(node("x"), node("y"), edges=(edge("x", "y", "x"),)))


def test_typecheck_rejects_non_tree_topologies() -> None:
    with pytest.raises(QuantifiedPatternTypeError, match="disconnected"):
        type_check_focused_quantified_pattern(query(node("x"), node("y")))
    with pytest.raises(QuantifiedPatternTypeError, match="multiple structural parents"):
        type_check_focused_quantified_pattern(
            query(
                node("x"),
                node("y"),
                node("z"),
                edges=(edge("x", "z"), edge("y", "z")),
            )
        )
    with pytest.raises(QuantifiedPatternTypeError, match="incoming"):
        type_check_focused_quantified_pattern(query(node("x"), node("y"), edges=(edge("y", "x"),)))


def test_typecheck_rejects_reverse_and_undirected_edges() -> None:
    for direction in (Direction.IN, Direction.UNDIRECTED):
        pattern_edge = QuantifiedPatternEdge(
            Var("x"),
            Var("y"),
            FocusedEdgePattern(label="Transfer"),
            direction,
            exists(),
        )
        with pytest.raises(QuantifiedPatternTypeError, match="OUT"):
            type_check_focused_quantified_pattern(query(node("x"), node("y"), edges=(pattern_edge,)))
