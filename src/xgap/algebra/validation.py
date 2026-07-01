"""Logical plan validation interface."""

from __future__ import annotations

from xgap.algebra.bindings import BindingField, BindingKind, BindingSchema
from xgap.algebra.ops import (
    AntiSemiJoinOp,
    BindEdgeOp,
    BindNodeOp,
    BindingJoinOp,
    BindingProjectOp,
    EdgesOp,
    FocusProjectionOp,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderByOp,
    OutputKind,
    ProjectionOp,
    QuantifiedCheckOp,
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

    if isinstance(plan, BindNodeOp):
        _require_path_set(plan.child, "BindNode child")
        _infer_binding_schema(plan)
        validate_plan(plan.child)
        return

    if isinstance(plan, BindEdgeOp):
        _require_path_set(plan.child, "BindEdge child")
        _infer_binding_schema(plan)
        validate_plan(plan.child)
        return

    if isinstance(plan, BindingJoinOp):
        _require_binding_relation(plan.left, "BindingJoin left child")
        _require_binding_relation(plan.right, "BindingJoin right child")
        _infer_binding_schema(plan)
        validate_plan(plan.left)
        validate_plan(plan.right)
        return

    if isinstance(plan, BindingProjectOp):
        _require_binding_relation(plan.child, "BindingProject child")
        _infer_binding_schema(plan)
        validate_plan(plan.child)
        return

    if isinstance(plan, QuantifiedCheckOp):
        _require_binding_relation(plan.candidates, "QuantifiedCheck candidates")
        _require_binding_relation(plan.witnesses, "QuantifiedCheck witnesses")
        if plan.domain is not None:
            _require_binding_relation(plan.domain, "QuantifiedCheck domain")
        _infer_binding_schema(plan)
        validate_plan(plan.candidates)
        validate_plan(plan.witnesses)
        if plan.domain is not None:
            validate_plan(plan.domain)
        return

    if isinstance(plan, AntiSemiJoinOp):
        _require_binding_relation(plan.left, "AntiSemiJoin left child")
        _require_binding_relation(plan.right, "AntiSemiJoin right child")
        _infer_binding_schema(plan)
        validate_plan(plan.left)
        validate_plan(plan.right)
        return

    if isinstance(plan, FocusProjectionOp):
        _require_binding_relation(plan.child, "FocusProjection child")
        _validate_focus_projection(plan)
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


def _require_binding_relation(plan: object, context: str) -> None:
    if not hasattr(plan, "output_kind"):
        raise ValidationError(f"{context} must be an algebra operator.")
    if plan.output_kind() is not OutputKind.BINDING_RELATION:
        raise ValidationError(f"{context} must output BINDING_RELATION.")


def _require_positive_limit(limit: int | None, context: str) -> None:
    if limit is not None and limit <= 0:
        raise ValidationError(f"{context} must be None or a positive integer.")


def infer_binding_schema(plan: object) -> BindingSchema:
    """Infer a BindingRelation schema for M6 validation without execution."""

    _require_binding_relation(plan, "Binding schema plan")
    return _infer_binding_schema(plan)


def _infer_binding_schema(plan: object) -> BindingSchema:
    if isinstance(plan, BindNodeOp):
        return BindingSchema((BindingField(plan.var, BindingKind.NODE),))

    if isinstance(plan, BindEdgeOp):
        fields = [
            BindingField(plan.source_var, BindingKind.NODE),
            BindingField(plan.target_var, BindingKind.NODE),
        ]
        if plan.edge_var is not None:
            fields.insert(1, BindingField(plan.edge_var, BindingKind.EDGE))
        return BindingSchema(tuple(fields))

    if isinstance(plan, BindingJoinOp):
        return _infer_binding_schema(plan.left).merge(_infer_binding_schema(plan.right))

    if isinstance(plan, BindingProjectOp):
        if not plan.vars:
            raise ValidationError("BindingProject vars must be non-empty.")
        try:
            return _infer_binding_schema(plan.child).project(plan.vars)
        except (KeyError, ValueError) as error:
            raise ValidationError(str(error)) from error

    if isinstance(plan, QuantifiedCheckOp):
        candidate_schema = _infer_binding_schema(plan.candidates)
        witness_schema = _infer_binding_schema(plan.witnesses)
        quantifier_kind = _quantifier_kind(plan.quantifier)
        is_ratio = quantifier_kind == "RATIO"

        if quantifier_kind == "NONE":
            raise ValidationError("QuantifiedCheck does not accept NONE quantifiers.")
        if is_ratio and plan.domain is None:
            raise ValidationError("Ratio QuantifiedCheck requires a domain relation.")
        if not is_ratio and plan.domain is not None:
            raise ValidationError("Non-ratio QuantifiedCheck must not have a domain relation.")

        _require_vars(candidate_schema, plan.correlation_vars, "QuantifiedCheck candidates")
        _require_vars(witness_schema, plan.correlation_vars, "QuantifiedCheck witnesses")
        _require_var_kind(witness_schema, plan.child_var, BindingKind.NODE, "QuantifiedCheck child_var")
        _require_same_kinds(candidate_schema, witness_schema, plan.correlation_vars)

        if plan.domain is not None:
            domain_schema = _infer_binding_schema(plan.domain)
            _require_vars(domain_schema, plan.correlation_vars, "QuantifiedCheck domain")
            _require_var_kind(domain_schema, plan.child_var, BindingKind.NODE, "QuantifiedCheck domain child_var")
            _require_same_kinds(candidate_schema, domain_schema, plan.correlation_vars)

        return candidate_schema

    if isinstance(plan, AntiSemiJoinOp):
        left_schema = _infer_binding_schema(plan.left)
        right_schema = _infer_binding_schema(plan.right)
        if not plan.on:
            raise ValidationError("AntiSemiJoin on keys must be non-empty.")
        _require_vars(left_schema, plan.on, "AntiSemiJoin left")
        _require_vars(right_schema, plan.on, "AntiSemiJoin right")
        _require_same_kinds(left_schema, right_schema, plan.on)
        return left_schema

    if isinstance(plan, FocusProjectionOp):
        raise ValidationError("FocusProjection outputs PATH_SET, not BINDING_RELATION.")

    raise ValidationError(f"Cannot infer binding schema for {type(plan).__name__}.")


def _require_vars(schema: BindingSchema, names: tuple[str, ...], context: str) -> None:
    if not names:
        raise ValidationError(f"{context} variables must be non-empty.")
    for name in names:
        if not schema.has(name):
            raise ValidationError(f"{context} missing variable {name!r}.")


def _require_var_kind(
    schema: BindingSchema,
    name: str,
    kind: BindingKind,
    context: str,
) -> None:
    if not schema.has(name):
        raise ValidationError(f"{context} missing variable {name!r}.")
    actual = schema.kind(name)
    if actual is not kind:
        raise ValidationError(
            f"{context} variable {name!r} must be {kind.value}, got {actual.value}."
        )


def _require_same_kinds(
    left: BindingSchema,
    right: BindingSchema,
    names: tuple[str, ...],
) -> None:
    for name in names:
        if left.kind(name) is not right.kind(name):
            raise ValidationError(f"Binding variable {name!r} has incompatible kinds.")


def _quantifier_kind(quantifier: object) -> str:
    kind = getattr(quantifier, "kind", None)
    value = getattr(kind, "value", kind)
    if not isinstance(value, str):
        raise ValidationError("QuantifiedCheck quantifier must expose a string kind.")
    return value


def _validate_focus_projection(plan: FocusProjectionOp) -> None:
    schema = _infer_binding_schema(plan.child)
    _require_var_kind(schema, plan.focus_var, BindingKind.NODE, "FocusProjection focus_var")
