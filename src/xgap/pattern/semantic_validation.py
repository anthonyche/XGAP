"""Closed typed path-intent validation, independent of logical lowering.

This explicit profile adds complete scalar/reference checks to M5's variable
and selector rules. It does not implement the M5 placeholder capabilities or
change the legacy checker. Numeric references require a fixed-length path;
endpoint references remain meaningful on variable-length paths.
"""

from __future__ import annotations

import math
from typing import Any

from xgap.algebra.conditions import (
    And, EdgeRef, LabelEquals, LengthEquals, NodeNotEquals, NodeRef, Not, Or,
    PropertyEquals, PropertyNotEquals, PropertyLessThan, PropertyLessThanOrEqual,
    PropertyGreaterThan, PropertyGreaterThanOrEqual,
)
from xgap.pattern.ast import (
    Alt, Bounded, OptionalExpr, PathPatternQuery, Plus, Rel, Seq, Star,
)
from xgap.pattern.typecheck import (
    PatternTypeError, _fixed_edge_count, type_check_path_pattern,
)
from xgap.pattern.types import PatternVarType


PROFILE = "typed_path_semantics_v1"
PROPERTY_CONDITIONS = (
    PropertyEquals, PropertyNotEquals, PropertyLessThan, PropertyLessThanOrEqual,
    PropertyGreaterThan, PropertyGreaterThanOrEqual,
)
NUMERIC_CONDITIONS = PROPERTY_CONDITIONS[2:]


def type_check_semantic_path_pattern(query: PathPatternQuery) -> dict[str, PatternVarType]:
    """Check the typed intent without consulting a compiler/backend or gold."""
    schema = type_check_path_pattern(query)
    for value, name in ((query.max_depth, "max_depth"), (query.selector.k, "selector.k")):
        if value is not None:
            _integer(value, name, minimum=1)
    _properties(query.source.properties)
    _properties(query.target.properties)
    _regex(query.expr)
    _condition(query.condition, _fixed_edge_count(query.expr))
    return schema


def _integer(value: Any, name: str, *, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise PatternTypeError(f"{name} must be an integer >= {minimum}, not a boolean/coercion.")


def _json_value(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise PatternTypeError("Property constants must be finite JSON values.")


def _properties(values) -> None:
    for key, value in values.items():
        if not isinstance(key, str) or not key:
            raise PatternTypeError("Property names must be nonempty strings.")
        _json_value(value)


def _regex(expr) -> None:
    if isinstance(expr, Rel):
        _properties(expr.edge.properties)
    elif isinstance(expr, (Seq, Alt)):
        _regex(expr.left)
        _regex(expr.right)
    elif isinstance(expr, (Plus, Star, OptionalExpr, Bounded)):
        if isinstance(expr, Bounded):
            _integer(expr.min_repeats, "min_repeats", minimum=0)
            if expr.max_repeats is not None:
                _integer(expr.max_repeats, "max_repeats", minimum=expr.min_repeats)
        _regex(expr.child)
    else:
        raise PatternTypeError(f"Unknown regex node: {type(expr).__name__}.")


def _ref(ref, edge_count: int | None, *, node_only: bool = False) -> None:
    if isinstance(ref, NodeRef):
        value = ref.position
        if isinstance(value, str) and value in ("first", "last"):
            return
        maximum = None if edge_count is None else edge_count + 1
    elif isinstance(ref, EdgeRef) and not node_only:
        value = ref.index
        maximum = edge_count
    else:
        raise PatternTypeError("Condition reference has the wrong node/edge kind.")
    _integer(value, "condition reference", minimum=1)
    if maximum is None:
        raise PatternTypeError("Numeric condition references require a fixed-length path expression.")
    if value > maximum:
        raise PatternTypeError(f"Condition reference {value} is outside the fixed path range 1..{maximum}.")


def _condition(item, edge_count: int | None) -> None:
    if item is None:
        return
    if type(item) in (And, Or):
        for child in item.conditions:
            if child is None:
                raise PatternTypeError("Boolean condition children cannot be null.")
            _condition(child, edge_count)
    elif type(item) is Not:
        if item.condition is None:
            raise PatternTypeError("NOT requires a condition.")
        _condition(item.condition, edge_count)
    elif type(item) is NodeNotEquals:
        _ref(item.left, edge_count, node_only=True)
        _ref(item.right, edge_count, node_only=True)
    elif type(item) is LengthEquals:
        _integer(item.value, "length", minimum=0)
    elif type(item) is LabelEquals:
        _ref(item.ref, edge_count)
        if item.value is not None and (not isinstance(item.value, str) or not item.value):
            raise PatternTypeError("Label conditions require a nonempty string or null label.")
    elif type(item) in PROPERTY_CONDITIONS:
        _ref(item.ref, edge_count)
        _properties({item.property_name: item.value})
        if type(item) in NUMERIC_CONDITIONS and (
            type(item.value) not in (int, float) or not math.isfinite(item.value)
        ):
            raise PatternTypeError("Numeric comparisons require a finite numeric constant, not a boolean.")
    else:
        raise PatternTypeError(f"Unknown condition node: {type(item).__name__}.")
