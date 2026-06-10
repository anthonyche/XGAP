import pytest

from xgap.algebra.ops import RecursiveMode
from xgap.pattern import (
    Alt,
    Direction,
    EdgePattern,
    NodePattern,
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
    infer_schema,
    type_check_path_pattern,
)


def query(
    *,
    path_var: Var | None = None,
    source: NodePattern | None = None,
    expr=None,
    target: NodePattern | None = None,
    selector: Selector | None = None,
    restrictor: PathMode = PathMode.TRAIL,
    max_depth: int | None = None,
) -> PathPatternQuery:
    return PathPatternQuery(
        path_var=path_var,
        source=source or NodePattern(),
        expr=expr or Rel(EdgePattern(label="Knows")),
        target=target or NodePattern(),
        selector=selector or Selector(SelectorKind.ALL),
        restrictor=restrictor,
        max_depth=max_depth,
    )


def test_var_rejects_empty_or_whitespace_names() -> None:
    with pytest.raises(ValueError):
        Var("")
    with pytest.raises(ValueError):
        Var("   ")


def test_node_edge_and_path_variables_infer_schema() -> None:
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


def test_same_variable_name_with_different_types_is_rejected() -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(
            query(source=NodePattern(var=Var("x")), expr=Rel(EdgePattern(var=Var("x"))))
        )

    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(path_var=Var("x"), source=NodePattern(var=Var("x"))))


def test_empty_labels_and_property_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        NodePattern(label="")
    with pytest.raises(ValueError):
        EdgePattern(label="")
    with pytest.raises(ValueError):
        NodePattern(properties={"": "Moe"})
    with pytest.raises(ValueError):
        EdgePattern(properties={"": "wire"})


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
def test_selectors_requiring_k_reject_missing_or_invalid_k(selector: Selector) -> None:
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
def test_selectors_without_k_reject_meaningless_k(selector: Selector) -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(selector=selector))


def test_repeated_expressions_reject_edge_variables() -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(expr=Plus(Rel(EdgePattern(var=Var("e"))))))

    with pytest.raises(PatternTypeError):
        type_check_path_pattern(query(expr=Star(Rel(EdgePattern(var=Var("e"))))))


def test_alt_asymmetric_variable_schema_is_rejected() -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(
            query(
                expr=Alt(
                    Rel(EdgePattern(var=Var("e"), label="Knows")),
                    Rel(EdgePattern(label="Likes")),
                )
            )
        )


def test_alt_matching_variable_schema_is_accepted() -> None:
    pattern = query(
        expr=Alt(
            Rel(EdgePattern(var=Var("e"), label="Knows")),
            Rel(EdgePattern(var=Var("e"), label="Likes")),
        )
    )

    assert type_check_path_pattern(pattern)["e"] is PatternVarType.EDGE


def test_direction_in_and_undirected_are_accepted_by_typecheck() -> None:
    for direction in (Direction.IN, Direction.UNDIRECTED):
        pattern = query(expr=Rel(EdgePattern(label="Knows", direction=direction)))
        assert type_check_path_pattern(pattern) == {}


def test_walk_recursive_regex_requires_positive_max_depth() -> None:
    with pytest.raises(PatternTypeError):
        type_check_path_pattern(
            query(expr=Plus(Rel(EdgePattern(label="Knows"))), restrictor=RecursiveMode.WALK)
        )

    pattern = query(
        expr=Plus(Rel(EdgePattern(label="Knows"))),
        restrictor=RecursiveMode.WALK,
        max_depth=2,
    )

    assert type_check_path_pattern(pattern) == {}
