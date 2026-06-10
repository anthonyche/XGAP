"""Logical plan formatting interface."""

from __future__ import annotations

import json
from typing import Any

from xgap.algebra.conditions import (
    And,
    EdgeRef,
    LabelEquals,
    LengthEquals,
    NodeRef,
    Not,
    Or,
    PropertyEquals,
)
from xgap.algebra.ops import AlgebraOp, RecursiveOp, SelectionOp
from xgap.algebra.ops import GroupByOp, OrderByOp, ProjectionOp


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
