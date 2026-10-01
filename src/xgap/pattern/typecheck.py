"""Lightweight type checking for GPC-Lite path patterns."""

from __future__ import annotations

from xgap.algebra.conditions import And, NodeNotEquals, Not, Or
from xgap.algebra.ops import RecursiveMode
from xgap.pattern.ast import (
    Alt,
    Bounded,
    EdgePattern,
    NodePattern,
    OptionalExpr,
    PathPatternQuery,
    Plus,
    RegexExpr,
    Rel,
    SelectorKind,
    Seq,
    Star,
    Var,
)
from xgap.pattern.types import PatternVarType


class PatternTypeError(ValueError):
    """Raised when a GPC-Lite pattern violates M5 type rules."""


def infer_schema(query: PathPatternQuery) -> dict[str, PatternVarType]:
    schema: dict[str, PatternVarType] = {}
    _add_var(schema, query.path_var, PatternVarType.PATH)
    _merge_schema(schema, _infer_node_pattern(query.source))
    _merge_schema(schema, _infer_regex(query.expr, repeated=False))
    _merge_schema(schema, _infer_node_pattern(query.target))
    return schema


def type_check_path_pattern(query: PathPatternQuery) -> dict[str, PatternVarType]:
    schema = infer_schema(query)
    _check_selector(query)
    _check_condition_refs(query)
    if not isinstance(query.restrictor, RecursiveMode):
        raise PatternTypeError("PathPatternQuery restrictor must be a PathMode value.")
    if query.max_depth is not None and query.max_depth <= 0:
        raise PatternTypeError("PathPatternQuery max_depth must be positive when provided.")
    if query.restrictor is RecursiveMode.WALK and _contains_plus_or_star(query.expr):
        if query.max_depth is None or query.max_depth <= 0:
            raise PatternTypeError("WALK recursive path expressions require positive max_depth.")
    return schema


def _check_condition_refs(query: PathPatternQuery) -> None:
    if query.condition is None:
        return
    edge_count = _fixed_edge_count(query.expr)

    def visit(condition: object) -> None:
        if isinstance(condition, NodeNotEquals):
            if edge_count is None and any(
                isinstance(ref.position, int) for ref in (condition.left, condition.right)
            ):
                raise PatternTypeError(
                    "Numeric NodeNotEquals references require a fixed-length path expression."
                )
            if edge_count is not None:
                for ref in (condition.left, condition.right):
                    if isinstance(ref.position, int) and not 1 <= ref.position <= edge_count + 1:
                        raise PatternTypeError(
                            f"NodeNotEquals reference {ref.position} is outside fixed path "
                            f"node range 1..{edge_count + 1}."
                        )
            return
        if isinstance(condition, (And, Or)):
            for child in condition.conditions:
                visit(child)
            return
        if isinstance(condition, Not):
            visit(condition.condition)

    visit(query.condition)


def _fixed_edge_count(regex: RegexExpr) -> int | None:
    if isinstance(regex, Rel):
        return 1
    if isinstance(regex, Seq):
        left = _fixed_edge_count(regex.left)
        right = _fixed_edge_count(regex.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(regex, Alt):
        left = _fixed_edge_count(regex.left)
        right = _fixed_edge_count(regex.right)
        return left if left is not None and left == right else None
    if isinstance(regex, Bounded):
        child = _fixed_edge_count(regex.child)
        if child == 0:
            return 0
        if type(regex.min_repeats) is int and regex.min_repeats == regex.max_repeats:
            return regex.min_repeats * child if child is not None else (0 if regex.min_repeats == 0 else None)
    if isinstance(regex, OptionalExpr) and _fixed_edge_count(regex.child) == 0:
        return 0
    return None


def _infer_node_pattern(node: NodePattern) -> dict[str, PatternVarType]:
    schema: dict[str, PatternVarType] = {}
    _add_var(schema, node.var, PatternVarType.NODE)
    return schema


def _infer_edge_pattern(edge: EdgePattern, repeated: bool) -> dict[str, PatternVarType]:
    schema: dict[str, PatternVarType] = {}
    if repeated and edge.var is not None:
        raise PatternTypeError("Repeated expressions may not contain edge variables in M5.")
    _add_var(schema, edge.var, PatternVarType.EDGE)
    return schema


def _infer_regex(regex: RegexExpr, repeated: bool) -> dict[str, PatternVarType]:
    if isinstance(regex, Rel):
        return _infer_edge_pattern(regex.edge, repeated)
    if isinstance(regex, Seq):
        schema = _infer_regex(regex.left, repeated)
        _merge_schema(schema, _infer_regex(regex.right, repeated))
        return schema
    if isinstance(regex, Alt):
        left = _infer_regex(regex.left, repeated)
        right = _infer_regex(regex.right, repeated)
        if left != right:
            raise PatternTypeError("Alt branches must infer the same variable schema in M5.")
        return left
    if isinstance(regex, (Plus, Star, OptionalExpr)):
        return _infer_regex(regex.child, repeated=True)
    if isinstance(regex, Bounded):
        _check_bounded(regex)
        return _infer_regex(regex.child, repeated=True)
    raise PatternTypeError(f"Unsupported regex expression {type(regex).__name__}.")


def _add_var(
    schema: dict[str, PatternVarType],
    var: Var | None,
    var_type: PatternVarType,
) -> None:
    if var is None:
        return
    existing = schema.get(var.name)
    if existing is not None and existing is not var_type:
        raise PatternTypeError(
            f"Variable {var.name!r} cannot have both {existing.name} and {var_type.name} type."
        )
    schema[var.name] = var_type


def _merge_schema(
    target: dict[str, PatternVarType],
    source: dict[str, PatternVarType],
) -> None:
    for name, var_type in source.items():
        existing = target.get(name)
        if existing is not None and existing is not var_type:
            raise PatternTypeError(
                f"Variable {name!r} cannot have both {existing.name} and {var_type.name} type."
            )
        target[name] = var_type


def _check_selector(query: PathPatternQuery) -> None:
    selector = query.selector
    requires_k = {
        SelectorKind.ANY_K,
        SelectorKind.SHORTEST_K,
        SelectorKind.SHORTEST_K_GROUP,
    }
    if selector.kind in requires_k:
        if selector.k is None or selector.k <= 0:
            raise PatternTypeError(f"{selector.kind.name} requires a positive k.")
        return
    if selector.k is not None:
        raise PatternTypeError(f"{selector.kind.name} does not accept k in M5.")


def _contains_plus_or_star(regex: RegexExpr) -> bool:
    if isinstance(regex, (Plus, Star)):
        return True
    if isinstance(regex, (Rel,)):
        return False
    if isinstance(regex, (Seq, Alt)):
        return _contains_plus_or_star(regex.left) or _contains_plus_or_star(regex.right)
    if isinstance(regex, Bounded) and regex.max_repeats is None:
        return True
    if isinstance(regex, (OptionalExpr, Bounded)):
        return _contains_plus_or_star(regex.child)
    raise PatternTypeError(f"Unsupported regex expression {type(regex).__name__}.")


def _check_bounded(regex: Bounded) -> None:
    if type(regex.min_repeats) is not int or regex.min_repeats < 0:
        raise PatternTypeError("Bounded min_repeats must be non-negative.")
    if regex.max_repeats is not None and (type(regex.max_repeats) is not int
                                        or regex.max_repeats < regex.min_repeats):
        raise PatternTypeError("Bounded max_repeats must be at least min_repeats.")
