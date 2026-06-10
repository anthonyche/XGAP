"""Deterministic lowering from GPC-Lite path patterns to logical plans."""

from __future__ import annotations

from xgap.algebra.conditions import (
    And,
    Condition,
    EdgeRef,
    LabelEquals,
    NodeRef,
    PropertyEquals,
)
from xgap.algebra.ops import (
    AlgebraOp,
    EdgesOp,
    GroupKey,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderKey,
    OrderByOp,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)
from xgap.algebra.validation import validate_plan
from xgap.pattern.ast import (
    Alt,
    Bounded,
    Direction,
    EdgePattern,
    NodePattern,
    OptionalExpr,
    PathPatternQuery,
    Plus,
    RegexExpr,
    Rel,
    Selector,
    SelectorKind,
    Seq,
    Star,
)
from xgap.pattern.typecheck import type_check_path_pattern


class LoweringError(ValueError):
    """Raised when a GPC-Lite pattern cannot be lowered in M5."""


def lower_regex(
    regex: RegexExpr,
    restrictor: RecursiveMode,
    max_depth: int | None = None,
) -> AlgebraOp:
    if isinstance(regex, Rel):
        return _lower_rel(regex.edge)
    if isinstance(regex, Seq):
        return JoinOp(
            lower_regex(regex.left, restrictor, max_depth),
            lower_regex(regex.right, restrictor, max_depth),
        )
    if isinstance(regex, Alt):
        return UnionOp(
            lower_regex(regex.left, restrictor, max_depth),
            lower_regex(regex.right, restrictor, max_depth),
        )
    if isinstance(regex, Plus):
        _check_recursive_depth(restrictor, max_depth)
        return RecursiveOp(
            lower_regex(regex.child, restrictor, max_depth),
            restrictor,
            max_depth=max_depth,
        )
    if isinstance(regex, Star):
        _check_recursive_depth(restrictor, max_depth)
        return UnionOp(
            NodesOp(),
            RecursiveOp(
                lower_regex(regex.child, restrictor, max_depth),
                restrictor,
                max_depth=max_depth,
            ),
        )
    if isinstance(regex, OptionalExpr):
        raise LoweringError("OptionalExpr lowering is not implemented in M5.")
    if isinstance(regex, Bounded):
        raise LoweringError("Bounded regex lowering is not implemented in M5.")
    raise LoweringError(f"Unsupported regex expression {type(regex).__name__}.")


def lower_source_descriptor(source: NodePattern, base: AlgebraOp) -> AlgebraOp:
    condition = _node_descriptor_condition(source, NodeRef.first())
    if condition is None:
        return base
    return SelectionOp(condition, base)


def lower_target_descriptor(target: NodePattern, base: AlgebraOp) -> AlgebraOp:
    condition = _node_descriptor_condition(target, NodeRef.last())
    if condition is None:
        return base
    return SelectionOp(condition, base)


def apply_selector(base: AlgebraOp, selector: Selector) -> AlgebraOp:
    _check_selector(selector)
    if selector.kind is SelectorKind.ALL:
        return ProjectionOp(GroupByOp(base, GroupKey.NONE))
    if selector.kind is SelectorKind.ANY:
        return ProjectionOp(GroupByOp(base, GroupKey.SOURCE_TARGET), num_paths=1)
    if selector.kind is SelectorKind.ANY_K:
        return ProjectionOp(GroupByOp(base, GroupKey.SOURCE_TARGET), num_paths=selector.k)
    if selector.kind is SelectorKind.ANY_SHORTEST:
        return ProjectionOp(
            OrderByOp(GroupByOp(base, GroupKey.SOURCE_TARGET), OrderKey.PATH),
            num_paths=1,
        )
    if selector.kind is SelectorKind.ALL_SHORTEST:
        return ProjectionOp(
            OrderByOp(GroupByOp(base, GroupKey.SOURCE_TARGET_LENGTH), OrderKey.GROUP),
            num_groups=1,
        )
    if selector.kind is SelectorKind.SHORTEST_K:
        return ProjectionOp(
            OrderByOp(GroupByOp(base, GroupKey.SOURCE_TARGET), OrderKey.PATH),
            num_paths=selector.k,
        )
    if selector.kind is SelectorKind.SHORTEST_K_GROUP:
        return ProjectionOp(
            OrderByOp(GroupByOp(base, GroupKey.SOURCE_TARGET_LENGTH), OrderKey.GROUP),
            num_groups=selector.k,
        )
    raise LoweringError(f"Unsupported selector kind {selector.kind!r}.")


def lower_path_pattern(query: PathPatternQuery) -> AlgebraOp:
    type_check_path_pattern(query)
    base = lower_regex(query.expr, query.restrictor, query.max_depth)
    base = lower_source_descriptor(query.source, base)
    base = lower_target_descriptor(query.target, base)
    if query.condition is not None:
        base = SelectionOp(query.condition, base)
    plan = apply_selector(base, query.selector)
    validate_plan(plan)
    return plan


def lower_to_logical_plan(query: PathPatternQuery) -> AlgebraOp:
    return lower_path_pattern(query)


def _lower_rel(edge: EdgePattern) -> AlgebraOp:
    if edge.direction is not Direction.OUT:
        raise LoweringError(f"M5 lowering supports only OUT edges, got {edge.direction.name}.")
    conditions: list[Condition] = []
    if edge.label is not None:
        if not edge.label:
            raise LoweringError("Edge label must be non-empty when provided.")
        conditions.append(LabelEquals(EdgeRef(1), edge.label))
    for name, value in edge.properties.items():
        if not name:
            raise LoweringError("Edge property names must be non-empty.")
        conditions.append(PropertyEquals(EdgeRef(1), name, value))

    condition = _and_conditions(conditions)
    if condition is None:
        return EdgesOp()
    return SelectionOp(condition, EdgesOp())


def _node_descriptor_condition(pattern: NodePattern, ref: NodeRef) -> Condition | None:
    conditions: list[Condition] = []
    if pattern.label is not None:
        if not pattern.label:
            raise LoweringError("Node label must be non-empty when provided.")
        conditions.append(LabelEquals(ref, pattern.label))
    for name, value in pattern.properties.items():
        if not name:
            raise LoweringError("Node property names must be non-empty.")
        conditions.append(PropertyEquals(ref, name, value))
    return _and_conditions(conditions)


def _and_conditions(conditions: list[Condition]) -> Condition | None:
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return And(*conditions)


def _check_recursive_depth(restrictor: RecursiveMode, max_depth: int | None) -> None:
    if max_depth is not None and max_depth <= 0:
        raise LoweringError("Recursive max_depth must be positive when provided.")
    if restrictor is RecursiveMode.WALK and max_depth is None:
        raise LoweringError("WALK recursive path expressions require positive max_depth.")


def _check_selector(selector: Selector) -> None:
    requires_k = {
        SelectorKind.ANY_K,
        SelectorKind.SHORTEST_K,
        SelectorKind.SHORTEST_K_GROUP,
    }
    if selector.kind in requires_k:
        if selector.k is None or selector.k <= 0:
            raise LoweringError(f"{selector.kind.name} requires a positive k.")
        return
    if selector.k is not None:
        raise LoweringError(f"{selector.kind.name} does not accept k in M5.")
