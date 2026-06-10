"""Logical plan validation interface."""

from __future__ import annotations

from xgap.algebra.ops import (
    EdgesOp,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderByOp,
    OutputKind,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)


class ValidationError(ValueError):
    """Raised when a logical plan violates implemented M2.5 invariants."""


def validate_plan(plan: object) -> None:
    if isinstance(plan, (NodesOp, EdgesOp)):
        return

    if isinstance(plan, SelectionOp):
        _require_path_set(plan.child, "Selection child")
        validate_plan(plan.child)
        return

    if isinstance(plan, UnionOp):
        _require_path_set(plan.left, "Union left child")
        _require_path_set(plan.right, "Union right child")
        validate_plan(plan.left)
        validate_plan(plan.right)
        return

    if isinstance(plan, JoinOp):
        _require_path_set(plan.left, "Join left child")
        _require_path_set(plan.right, "Join right child")
        validate_plan(plan.left)
        validate_plan(plan.right)
        return

    if isinstance(plan, RecursiveOp):
        _require_path_set(plan.child, "Recursive child")
        if plan.max_depth is not None and plan.max_depth <= 0:
            raise ValidationError("Recursive max_depth must be positive when provided.")
        if plan.mode is RecursiveMode.WALK and plan.max_depth is None:
            raise ValidationError("Recursive WALK mode requires a positive max_depth.")
        validate_plan(plan.child)
        return

    if isinstance(plan, GroupByOp):
        plan.group_key()
        _require_path_set(plan.child, "GroupBy child")
        validate_plan(plan.child)
        return

    if isinstance(plan, OrderByOp):
        plan.order_key()
        _require_solution_space(plan.child, "OrderBy child")
        validate_plan(plan.child)
        return

    if isinstance(plan, ProjectionOp):
        if plan.fields is not None:
            raise NotImplementedError("Field-based projection validation is not implemented.")
        _require_solution_space(plan.child, "Projection child")
        _require_positive_limit(plan.num_partitions, "Projection num_partitions")
        _require_positive_limit(plan.num_groups, "Projection num_groups")
        _require_positive_limit(plan.num_paths, "Projection num_paths")
        validate_plan(plan.child)
        return

    raise NotImplementedError(f"Plan validation is not implemented for {type(plan).__name__}.")


def _require_path_set(plan: object, context: str) -> None:
    if not hasattr(plan, "output_kind"):
        raise ValidationError(f"{context} must be an algebra operator.")
    if plan.output_kind() is not OutputKind.PATH_SET:
        raise ValidationError(f"{context} must output PATH_SET.")


def _require_solution_space(plan: object, context: str) -> None:
    if not hasattr(plan, "output_kind"):
        raise ValidationError(f"{context} must be an algebra operator.")
    if plan.output_kind() is not OutputKind.SOLUTION_SPACE:
        raise ValidationError(f"{context} must output SOLUTION_SPACE.")


def _require_positive_limit(limit: int | None, context: str) -> None:
    if limit is not None and limit <= 0:
        raise ValidationError(f"{context} must be None or a positive integer.")
