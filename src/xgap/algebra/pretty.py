"""Logical plan formatting interface."""

from __future__ import annotations

import json
from typing import Any

from xgap.algebra.conditions import (
    And,
    EdgeRef,
    LabelEquals,
    LengthEquals,
    NodeNotEquals,
    NodeRef,
    Not,
    Or,
    PropertyEquals,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
    PropertyLessThan,
    PropertyLessThanOrEqual,
    PropertyNotEquals,
)
from xgap.algebra.ops import AlgebraOp, RecursiveOp, SelectionOp
from xgap.algebra.ops import (
    AntiSemiJoinOp,
    BindEdgeOp,
    BindNodeOp,
    BindingJoinOp,
    BindingProjectOp,
    FocusProjectionOp,
    GroupByOp,
    OrderByOp,
    ProjectionOp,
    QuantifiedCheckOp,
)


def format_plan(plan: AlgebraOp) -> str:
    return "\n".join(_format_lines(plan, indent=0))


def _format_lines(plan: AlgebraOp, indent: int) -> list[str]:
    prefix = "  " * indent
    line = f"{prefix}{plan.operator_name()}"
    if isinstance(plan, SelectionOp):
        line = f"{line} [{_format_condition(plan.condition)}]"
    if isinstance(plan, RecursiveOp):
        line = f"{line} [{_format_recursive(plan)}]"
    if isinstance(plan, GroupByOp):
        line = f"{line} [{plan.group_key().value}]"
    if isinstance(plan, OrderByOp):
        line = f"{line} [{plan.order_key().value}]"
    if isinstance(plan, ProjectionOp):
        line = f"{line} [{_format_projection(plan)}]"
    if isinstance(plan, BindNodeOp):
        line = f"{line} [{plan.var}]"
    if isinstance(plan, BindEdgeOp):
        edge_var = plan.edge_var if plan.edge_var is not None else "*"
        line = f"{line} [{plan.source_var}, {edge_var}, {plan.target_var}]"
    if isinstance(plan, BindingProjectOp):
        line = f"{line} [{', '.join(plan.vars)}]"
    if isinstance(plan, QuantifiedCheckOp):
        line = f"{line} [{_format_quantified_check(plan)}]"
    if isinstance(plan, AntiSemiJoinOp):
        line = f"{line} [on={', '.join(plan.on)}]"
    if isinstance(plan, FocusProjectionOp):
        line = f"{line} [{plan.focus_var}]"

    lines = [line]
    for child in plan.children():
        lines.extend(_format_lines(child, indent + 1))
    return lines


def _format_condition(condition: object) -> str:
    if isinstance(condition, LabelEquals):
        return f"label({_format_ref(condition.ref)}) = {_format_value(condition.value)}"
    if isinstance(condition, PropertyEquals):
        return (
            f"{_format_ref(condition.ref)}.{condition.property_name} "
            f"= {_format_value(condition.value)}"
        )
    if isinstance(condition, PropertyNotEquals):
        return (
            f"{_format_ref(condition.ref)}.{condition.property_name} "
            f"!= {_format_value(condition.value)}"
        )
    if isinstance(condition, NodeNotEquals):
        return f"{_format_ref(condition.left)} != {_format_ref(condition.right)}"
    if isinstance(condition, PropertyLessThan):
        return (
            f"{_format_ref(condition.ref)}.{condition.property_name} "
            f"< {_format_value(condition.value)}"
        )
    if isinstance(condition, PropertyLessThanOrEqual):
        return (
            f"{_format_ref(condition.ref)}.{condition.property_name} "
            f"<= {_format_value(condition.value)}"
        )
    if isinstance(condition, PropertyGreaterThan):
        return (
            f"{_format_ref(condition.ref)}.{condition.property_name} "
            f"> {_format_value(condition.value)}"
        )
    if isinstance(condition, PropertyGreaterThanOrEqual):
        return (
            f"{_format_ref(condition.ref)}.{condition.property_name} "
            f">= {_format_value(condition.value)}"
        )
    if isinstance(condition, LengthEquals):
        return f"len() = {condition.value}"
    if isinstance(condition, And):
        return "(" + " AND ".join(_format_condition(child) for child in condition.conditions) + ")"
    if isinstance(condition, Or):
        return "(" + " OR ".join(_format_condition(child) for child in condition.conditions) + ")"
    if isinstance(condition, Not):
        return f"(NOT {_format_condition(condition.condition)})"
    raise NotImplementedError(f"Condition formatting is not implemented for {type(condition).__name__}.")


def _format_recursive(plan: RecursiveOp) -> str:
    parts = [f"mode={plan.mode.value}"]
    if plan.max_depth is not None:
        parts.append(f"max_depth={plan.max_depth}")
    return ", ".join(parts)


def _format_projection(plan: ProjectionOp) -> str:
    if plan.fields is not None:
        raise NotImplementedError("Field-based projection formatting is not implemented.")
    return ", ".join(
        _format_projection_limit(limit)
        for limit in (plan.num_partitions, plan.num_groups, plan.num_paths)
    )


def _format_projection_limit(limit: int | None) -> str:
    if limit is None:
        return "*"
    return str(limit)


def _format_quantified_check(plan: QuantifiedCheckOp) -> str:
    quantifier = _format_quantifier(plan.quantifier)
    domain = "yes" if plan.domain is not None else "no"
    return (
        f"{quantifier}; corr={','.join(plan.correlation_vars)}; "
        f"child={plan.child_var}; domain={domain}"
    )


def _format_quantifier(quantifier: object) -> str:
    kind = _format_attr_value(getattr(quantifier, "kind", None))
    comparator = _format_attr_value(getattr(quantifier, "comparator", None))
    threshold = getattr(quantifier, "threshold", None)
    parts = [kind]
    if comparator is not None:
        parts.append(comparator)
    if threshold is not None:
        parts.append(str(threshold))
    return " ".join(parts)


def _format_attr_value(value: object) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", value)
    if enum_value == ">=":
        return "GE"
    if enum_value == "=":
        return "EQ"
    return str(enum_value)


def _format_ref(ref: NodeRef | EdgeRef) -> str:
    if isinstance(ref, NodeRef):
        if ref.position == "first":
            return "first"
        if ref.position == "last":
            return "last"
        return f"node({ref.position})"
    return f"edge({ref.index})"


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    return repr(value)
