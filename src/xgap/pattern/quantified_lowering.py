"""Deterministic lowering for M6 focused quantified patterns."""

from __future__ import annotations

from xgap.algebra.conditions import (
    And,
    Condition,
    EdgeRef,
    LabelEquals,
    NodeRef,
    PropertyEquals,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
    PropertyLessThan,
    PropertyLessThanOrEqual,
    PropertyNotEquals,
)
from xgap.algebra.ops import (
    AlgebraOp,
    AntiSemiJoinOp,
    BindEdgeOp,
    BindNodeOp,
    BindingJoinOp,
    BindingProjectOp,
    EdgesOp,
    FocusProjectionOp,
    NodesOp,
    QuantifiedCheckOp,
    SelectionOp,
)
from xgap.algebra.validation import infer_binding_schema, validate_plan
from xgap.pattern.quantified_ast import (
    FocusedEdgePattern,
    FocusedNodePattern,
    FocusedQuantifiedPatternQuery,
    PropertyPredicate,
    QuantifiedPatternEdge,
    QuantifierKind,
    ScalarComparator,
)
from xgap.pattern.quantified_typecheck import (
    QuantifierBounds,
    type_check_focused_quantified_pattern,
    validate_quantifier_bounds,
)


class QuantifiedLoweringError(ValueError):
    """Raised when an M6 focused quantified pattern cannot be lowered."""


def lower_focused_quantified_pattern(
    query: FocusedQuantifiedPatternQuery,
    bounds: QuantifierBounds | None = None,
) -> AlgebraOp:
    type_check_focused_quantified_pattern(query)
    validate_quantifier_bounds(query, bounds)

    lowering = _QuantifiedLowerer(query)
    focus_plan = lowering.lower_focus()
    validate_plan(focus_plan)
    return focus_plan


class _QuantifiedLowerer:
    def __init__(self, query: FocusedQuantifiedPatternQuery) -> None:
        self.query = query
        self.node_patterns = {node.var.name: node for node in query.node_patterns}
        self.children: dict[str, list[QuantifiedPatternEdge]] = {
            node.var.name: [] for node in query.node_patterns
        }
        for edge in query.edges:
            self.children[edge.parent_var.name].append(edge)

    def lower_focus(self) -> AlgebraOp:
        focus_name = self.query.focus.name
        root_nodes = _lower_node_descriptor(self.node_patterns[focus_name], NodesOp())
        candidates: AlgebraOp = BindNodeOp(focus_name, root_nodes)
        filtered = self.lower_node(focus_name, candidates)
        return FocusProjectionOp(focus_name, filtered)

    def lower_node(self, node_name: str, candidates: AlgebraOp) -> AlgebraOp:
        result = candidates
        for edge in sorted(self.children[node_name], key=_branch_key):
            result = self.lower_branch(result, edge)
        return result

    def lower_branch(self, candidates: AlgebraOp, edge: QuantifiedPatternEdge) -> AlgebraOp:
        candidate_schema = infer_binding_schema(candidates)
        correlation_vars = candidate_schema.names()
        parent_name = edge.parent_var.name
        child_name = edge.child_var.name
        edge_var = edge.edge.var.name if edge.edge.var is not None else None

        edge_paths = _lower_edge_descriptor(edge.edge, EdgesOp())
        edge_rows = BindEdgeOp(parent_name, edge_var, child_name, edge_paths)
        domain_rows = BindingJoinOp(candidates, edge_rows)

        child_nodes = _lower_node_descriptor(self.node_patterns[child_name], NodesOp())
        child_binding = BindNodeOp(child_name, child_nodes)
        child_rows = BindingJoinOp(domain_rows, child_binding)
        complete_witnesses = self.lower_node(child_name, child_rows)

        quantifier = edge.quantifier.canonical()
        if quantifier.kind is QuantifierKind.NONE:
            return AntiSemiJoinOp(candidates, complete_witnesses, on=correlation_vars)
        if quantifier.kind is QuantifierKind.RATIO:
            domain = BindingProjectOp((*correlation_vars, child_name), domain_rows)
            return QuantifiedCheckOp(
                candidates,
                complete_witnesses,
                quantifier,
                correlation_vars,
                child_name,
                domain=domain,
            )
        return QuantifiedCheckOp(
            candidates,
            complete_witnesses,
            quantifier,
            correlation_vars,
            child_name,
        )


def _lower_node_descriptor(pattern: FocusedNodePattern, base: AlgebraOp) -> AlgebraOp:
    condition = _descriptor_condition(pattern.label, pattern.predicates, NodeRef.first())
    if condition is None:
        return base
    return SelectionOp(condition, base)


def _lower_edge_descriptor(pattern: FocusedEdgePattern, base: AlgebraOp) -> AlgebraOp:
    condition = _descriptor_condition(pattern.label, pattern.predicates, EdgeRef(1))
    if condition is None:
        return base
    return SelectionOp(condition, base)


def _descriptor_condition(
    label: str | None,
    predicates: tuple[PropertyPredicate, ...],
    ref: NodeRef | EdgeRef,
) -> Condition | None:
    conditions: list[Condition] = []
    if label is not None:
        conditions.append(LabelEquals(ref, label))
    for predicate in predicates:
        conditions.append(_predicate_condition(predicate, ref))
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return And(*conditions)


def _predicate_condition(predicate: PropertyPredicate, ref: NodeRef | EdgeRef) -> Condition:
    if predicate.comparator is ScalarComparator.EQ:
        return PropertyEquals(ref, predicate.property_key, predicate.value)
    if predicate.comparator is ScalarComparator.NE:
        return PropertyNotEquals(ref, predicate.property_key, predicate.value)
    if predicate.comparator is ScalarComparator.LT:
        return PropertyLessThan(ref, predicate.property_key, predicate.value)
    if predicate.comparator is ScalarComparator.LE:
        return PropertyLessThanOrEqual(ref, predicate.property_key, predicate.value)
    if predicate.comparator is ScalarComparator.GT:
        return PropertyGreaterThan(ref, predicate.property_key, predicate.value)
    if predicate.comparator is ScalarComparator.GE:
        return PropertyGreaterThanOrEqual(ref, predicate.property_key, predicate.value)
    raise QuantifiedLoweringError(f"Unsupported scalar comparator {predicate.comparator!r}.")


def _branch_key(edge: QuantifiedPatternEdge) -> tuple[object, ...]:
    quantifier = edge.quantifier.canonical()
    edge_var = edge.edge.var.name if edge.edge.var is not None else ""
    comparator = quantifier.comparator.value if quantifier.comparator is not None else ""
    threshold = str(quantifier.threshold) if quantifier.threshold is not None else ""
    return (
        edge.parent_var.name,
        edge.child_var.name,
        edge.edge.label or "",
        edge_var,
        quantifier.kind.value,
        comparator,
        threshold,
        tuple(_predicate_key(predicate) for predicate in edge.edge.predicates),
    )


def _predicate_key(predicate: PropertyPredicate) -> tuple[str, str, str]:
    return (
        predicate.property_key,
        predicate.comparator.value,
        repr(predicate.value),
    )
