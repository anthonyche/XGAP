"""Type checking and structural validation for M6 focused quantified patterns."""

from __future__ import annotations

from dataclasses import dataclass

from xgap.pattern.ast import Direction
from xgap.pattern.quantified_ast import (
    FocusedQuantifiedPatternQuery,
    QuantifiedPatternEdge,
    QuantifierKind,
)
from xgap.pattern.types import PatternVarType


class QuantifiedPatternTypeError(ValueError):
    """Raised when an M6 focused quantified pattern violates static rules."""


@dataclass(frozen=True)
class QuantifierBounds:
    max_non_existential_per_root_to_leaf_path: int = 2
    max_negated_edges_per_root_to_leaf_path: int = 1

    def __post_init__(self) -> None:
        if self.max_non_existential_per_root_to_leaf_path < 0:
            raise ValueError("max_non_existential_per_root_to_leaf_path must be non-negative.")
        if self.max_negated_edges_per_root_to_leaf_path < 0:
            raise ValueError("max_negated_edges_per_root_to_leaf_path must be non-negative.")


def type_check_focused_quantified_pattern(
    query: FocusedQuantifiedPatternQuery,
) -> dict[str, PatternVarType]:
    if not isinstance(query, FocusedQuantifiedPatternQuery):
        raise QuantifiedPatternTypeError("Expected FocusedQuantifiedPatternQuery.")

    node_patterns = _node_pattern_map(query)
    if query.focus.name not in node_patterns:
        raise QuantifiedPatternTypeError("Focus variable must be declared as a node.")

    schema: dict[str, PatternVarType] = {
        node.var.name: PatternVarType.NODE for node in query.node_patterns
    }
    edge_vars: set[str] = set()
    parents: dict[str, str] = {}
    adjacency: dict[str, list[str]] = {name: [] for name in node_patterns}

    for edge in query.edges:
        _check_edge(edge, node_patterns, schema, edge_vars)
        parent_name = edge.parent_var.name
        child_name = edge.child_var.name
        if child_name == query.focus.name:
            raise QuantifiedPatternTypeError("Focus node may not have incoming pattern edges.")
        existing_parent = parents.get(child_name)
        if existing_parent is not None:
            raise QuantifiedPatternTypeError(
                f"Node variable {child_name!r} has multiple structural parents."
            )
        parents[child_name] = parent_name
        adjacency[parent_name].append(child_name)
        if edge.edge.var is not None:
            schema[edge.edge.var.name] = PatternVarType.EDGE

    for node_name in node_patterns:
        if node_name == query.focus.name:
            continue
        if node_name not in parents:
            raise QuantifiedPatternTypeError(
                f"Node variable {node_name!r} is disconnected from the focus."
            )

    _check_acyclic_and_reachable(query.focus.name, adjacency, set(node_patterns))
    return schema


def validate_quantifier_bounds(
    query: FocusedQuantifiedPatternQuery,
    bounds: QuantifierBounds | None = None,
) -> None:
    type_check_focused_quantified_pattern(query)
    actual_bounds = bounds or QuantifierBounds()
    children: dict[str, list[QuantifiedPatternEdge]] = {
        node.var.name: [] for node in query.node_patterns
    }
    for edge in query.edges:
        children[edge.parent_var.name].append(edge)

    def walk(node_name: str, non_existential: int, negated: int) -> None:
        for edge in children[node_name]:
            quantifier = edge.quantifier.canonical()
            next_non_existential = non_existential + int(quantifier.is_non_existential())
            next_negated = negated + int(quantifier.kind is QuantifierKind.NONE)
            if next_non_existential > actual_bounds.max_non_existential_per_root_to_leaf_path:
                raise QuantifiedPatternTypeError(
                    "Quantifier bound exceeded: too many non-existential quantifiers "
                    "on one root-to-leaf path."
                )
            if next_negated > actual_bounds.max_negated_edges_per_root_to_leaf_path:
                raise QuantifiedPatternTypeError(
                    "Quantifier bound exceeded: too many NONE edges on one root-to-leaf path."
                )
            walk(edge.child_var.name, next_non_existential, next_negated)

    walk(query.focus.name, 0, 0)


def _node_pattern_map(query: FocusedQuantifiedPatternQuery):
    result = {}
    for node in query.node_patterns:
        if node.var.name in result:
            raise QuantifiedPatternTypeError(f"Duplicate node declaration {node.var.name!r}.")
        result[node.var.name] = node
    return result


def _check_edge(
    edge: QuantifiedPatternEdge,
    node_patterns: dict[str, object],
    schema: dict[str, PatternVarType],
    edge_vars: set[str],
) -> None:
    parent_name = edge.parent_var.name
    child_name = edge.child_var.name
    if parent_name not in node_patterns:
        raise QuantifiedPatternTypeError(f"Undeclared parent variable {parent_name!r}.")
    if child_name not in node_patterns:
        raise QuantifiedPatternTypeError(f"Undeclared child variable {child_name!r}.")
    if edge.direction is not Direction.OUT:
        raise QuantifiedPatternTypeError("M6 supports only OUT quantified edges.")
    if edge.edge.var is not None:
        edge_name = edge.edge.var.name
        existing = schema.get(edge_name)
        if existing is not None and existing is not PatternVarType.EDGE:
            raise QuantifiedPatternTypeError(
                f"Variable {edge_name!r} cannot be both {existing.name} and EDGE."
            )
        if edge_name in edge_vars:
            raise QuantifiedPatternTypeError(f"Duplicate edge variable {edge_name!r}.")
        edge_vars.add(edge_name)


def _check_acyclic_and_reachable(
    focus_name: str,
    adjacency: dict[str, list[str]],
    declared_nodes: set[str],
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_name: str) -> None:
        if node_name in visiting:
            raise QuantifiedPatternTypeError("Quantified pattern graph must be acyclic.")
        if node_name in visited:
            return
        visiting.add(node_name)
        for child in adjacency[node_name]:
            visit(child)
        visiting.remove(node_name)
        visited.add(node_name)

    visit(focus_name)
    if visited != declared_nodes:
        missing = sorted(declared_nodes - visited)
        raise QuantifiedPatternTypeError(
            f"Declared nodes must all be reachable from focus; unreachable={missing!r}."
        )
