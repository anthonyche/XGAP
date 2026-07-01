import pytest

from xgap.pattern import (
    Direction,
    FocusedEdgePattern,
    FocusedNodePattern,
    FocusedQuantifiedPatternQuery,
    QuantifiedPatternEdge,
    QuantifiedPatternTypeError,
    Var,
    count_eq,
    count_ge,
    exists,
    none,
    ratio_ge,
    validate_quantifier_bounds,
)


def node(name: str) -> FocusedNodePattern:
    return FocusedNodePattern(Var(name))


def edge(parent: str, child: str, quantifier) -> QuantifiedPatternEdge:
    return QuantifiedPatternEdge(
        Var(parent),
        Var(child),
        FocusedEdgePattern(label="Link"),
        Direction.OUT,
        quantifier,
    )


def query(edges) -> FocusedQuantifiedPatternQuery:
    names = sorted({name for e in edges for name in (e.parent_var.name, e.child_var.name)})
    return FocusedQuantifiedPatternQuery(Var("x"), tuple(node(name) for name in names), tuple(edges))


def test_two_nested_non_existential_quantifiers_are_allowed() -> None:
    pattern = query((edge("x", "y", count_eq(2)), edge("y", "z", ratio_ge("1/2"))))

    validate_quantifier_bounds(pattern)


def test_three_nested_non_existential_quantifiers_are_rejected() -> None:
    pattern = query(
        (
            edge("x", "y", count_eq(2)),
            edge("y", "z", ratio_ge("1/2")),
            edge("z", "w", count_eq(1)),
        )
    )

    with pytest.raises(QuantifiedPatternTypeError, match="non-existential"):
        validate_quantifier_bounds(pattern)


def test_count_ge_one_canonicalizes_to_exists_before_bounds() -> None:
    pattern = query(
        (
            edge("x", "y", count_ge(1)),
            edge("y", "z", count_eq(2)),
            edge("z", "w", ratio_ge("1/2")),
        )
    )

    validate_quantifier_bounds(pattern)


def test_one_nested_none_is_allowed_but_two_are_rejected() -> None:
    validate_quantifier_bounds(query((edge("x", "y", none()), edge("y", "z", exists()))))

    with pytest.raises(QuantifiedPatternTypeError, match="NONE"):
        validate_quantifier_bounds(query((edge("x", "y", none()), edge("y", "z", none()))))


def test_multiple_nonexistential_and_none_sibling_branches_are_allowed() -> None:
    pattern = query(
        (
            edge("x", "a", count_eq(2)),
            edge("x", "b", ratio_ge("1/2")),
            edge("x", "c", none()),
            edge("x", "d", none()),
        )
    )

    validate_quantifier_bounds(pattern)
