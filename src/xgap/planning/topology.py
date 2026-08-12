"""Deterministic logical-plan indexing for physical planning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from xgap.algebra.ops import (
    AlgebraOp,
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
    ProjectionOp,
    QuantifiedCheckOp,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)
from xgap.algebra.pretty import format_plan
from xgap.planning.contracts import (
    LogicalDependency,
    LogicalOperatorSpec,
    PhysicalState,
)


@dataclass(frozen=True)
class IndexedLogicalPlan:
    logical_plan_id: str
    root_operator_id: str
    operators: tuple[LogicalOperatorSpec, ...]
    dependencies: tuple[LogicalDependency, ...]
    operator_nodes: tuple[tuple[str, AlgebraOp], ...]

    def operator(self, operator_id: str) -> AlgebraOp:
        for current_id, operator in self.operator_nodes:
            if current_id == operator_id:
                return operator
        raise KeyError(operator_id)

    def root_state(self, interpretation_id: str) -> PhysicalState:
        return PhysicalState(
            interpretation_id=interpretation_id,
            logical_plan_id=self.logical_plan_id,
            operators=self.operators,
            dependencies=self.dependencies,
        )


def index_logical_plan(plan: AlgebraOp) -> IndexedLogicalPlan:
    """Index logical-tree occurrences in deterministic child-before-parent order."""

    entries: list[tuple[AlgebraOp, tuple[int, ...], tuple[tuple[int, ...], ...]]] = []

    def visit(operator: AlgebraOp, path: tuple[int, ...]) -> tuple[int, ...]:
        child_paths = tuple(visit(child, (*path, index)) for index, child in enumerate(operator.children()))
        entries.append((operator, path, child_paths))
        return path

    visit(plan, ())
    id_by_path = {path: f"op{index:04d}" for index, (_, path, _) in enumerate(entries)}
    operators: list[LogicalOperatorSpec] = []
    dependencies: list[LogicalDependency] = []
    nodes: list[tuple[str, AlgebraOp]] = []

    for operator, path, child_paths in entries:
        operator_id = id_by_path[path]
        nodes.append((operator_id, operator))
        operators.append(
            LogicalOperatorSpec(
                operator_id=operator_id,
                operator_name=operator.operator_name(),
                feature_id=operator_feature_id(operator),
                output_kind=operator.output_kind().value,
            )
        )
        for child_index, child_path in enumerate(child_paths):
            source_id = id_by_path[child_path]
            dependencies.append(
                LogicalDependency(
                    dependency_id=f"dep-{source_id}-{operator_id}-{child_index}",
                    source_operator_id=source_id,
                    target_operator_id=operator_id,
                    result_kind=entries_by_path(entries, child_path).output_kind().value,
                )
            )

    digest = hashlib.sha256(format_plan(plan).encode("utf-8")).hexdigest()[:20]
    return IndexedLogicalPlan(
        logical_plan_id=f"logical-plan-{digest}",
        root_operator_id=id_by_path[()],
        operators=tuple(operators),
        dependencies=tuple(sorted(dependencies, key=lambda item: item.dependency_id)),
        operator_nodes=tuple(nodes),
    )


def entries_by_path(
    entries: list[tuple[AlgebraOp, tuple[int, ...], tuple[tuple[int, ...], ...]]],
    path: tuple[int, ...],
) -> AlgebraOp:
    for operator, current_path, _ in entries:
        if current_path == path:
            return operator
    raise KeyError(path)


def operator_feature_id(operator: AlgebraOp) -> str:
    if isinstance(operator, NodesOp):
        return "path_algebra.Nodes"
    if isinstance(operator, EdgesOp):
        return "path_algebra.Edges"
    if isinstance(operator, SelectionOp):
        return "path_algebra.Selection"
    if isinstance(operator, UnionOp):
        return "path_algebra.Union"
    if isinstance(operator, JoinOp):
        return "path_algebra.Join"
    if isinstance(operator, RecursiveOp):
        return f"path_algebra.Recursive.{operator.mode.value}"
    if isinstance(operator, GroupByOp):
        return "extended_path.GroupBy"
    if isinstance(operator, OrderByOp):
        return "extended_path.OrderBy"
    if isinstance(operator, ProjectionOp):
        return "extended_path.Projection"
    if isinstance(operator, BindNodeOp):
        return "m6.BindNode"
    if isinstance(operator, BindEdgeOp):
        return "m6.BindEdge"
    if isinstance(operator, BindingJoinOp):
        return "m6.BindingJoin"
    if isinstance(operator, BindingProjectOp):
        return "m6.BindingProject"
    if isinstance(operator, QuantifiedCheckOp):
        return "m6.QuantifiedCheck"
    if isinstance(operator, AntiSemiJoinOp):
        return "m6.AntiSemiJoin"
    if isinstance(operator, FocusProjectionOp):
        return "m6.FocusProjection"
    raise NotImplementedError(
        f"Physical planning has no capability feature for {type(operator).__name__}."
    )
