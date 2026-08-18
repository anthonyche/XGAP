"""M9 feature inference and bounded path-shape analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from xgap.algebra.conditions import (
    And,
    Condition,
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
from xgap.algebra.validation import validate_plan
from xgap.backends import registry
from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    CompatibilityReport,
    SupportLevel,
    SupportReason,
    UnsupportedFeature,
)
from xgap.backends.compatibility import check_backend_support
from xgap.compilers.artifacts import make_compiler_input_spec
from xgap.compilers.errors import CompilerError, UnsupportedCompilationError
from xgap.compilers.errors import unsupported_compilation
from xgap.pattern.ast import PathPatternQuery, SelectorKind
from xgap.pattern.lowering import (
    lower_regex,
    lower_source_descriptor,
    lower_target_descriptor,
)
from xgap.pattern.typecheck import type_check_path_pattern


M9_CORE_FEATURES = (
    "graph_model.directed_edges",
    "result_model.row_bindings",
)

M9_ALLOWED_CONDITIONALS = frozenset(
    {
        "graph_model.node_labels",
        "graph_model.node_identity_predicates",
        "graph_model.scalar_property_predicates",
        "path_algebra.Nodes",
        "path_algebra.Edges",
        "path_algebra.Selection",
        "path_algebra.Join",
        "pattern.PathPatternQuery",
    }
)


@dataclass(frozen=True)
class BoundCondition:
    condition: Condition
    node_offset: int
    edge_offset: int
    edge_count: int

    def shift(self, path_offset: int) -> "BoundCondition":
        return BoundCondition(
            condition=self.condition,
            node_offset=self.node_offset + path_offset,
            edge_offset=self.edge_offset + path_offset,
            edge_count=self.edge_count,
        )

    def node_index(self, ref: NodeRef) -> int:
        if ref.position == "first":
            return self.node_offset
        if ref.position == "last":
            return self.node_offset + self.edge_count
        if ref.position < 1 or ref.position > self.edge_count + 1:
            raise CompilerError(
                f"Node reference {ref.position} is outside local path length {self.edge_count}."
            )
        return self.node_offset + ref.position - 1

    def edge_index(self, ref: EdgeRef) -> int:
        if ref.index < 1 or ref.index > self.edge_count:
            raise CompilerError(
                f"Edge reference {ref.index} is outside local path length {self.edge_count}."
            )
        return self.edge_offset + ref.index - 1


@dataclass(frozen=True)
class M9PathShape:
    edge_count: int
    conditions: tuple[BoundCondition, ...] = ()

    @property
    def node_count(self) -> int:
        return self.edge_count + 1

    def with_condition(self, condition: Condition) -> "M9PathShape":
        return M9PathShape(
            edge_count=self.edge_count,
            conditions=(
                *self.conditions,
                BoundCondition(condition, node_offset=0, edge_offset=0, edge_count=self.edge_count),
            ),
        )

    def join(self, right: "M9PathShape") -> "M9PathShape":
        return M9PathShape(
            edge_count=self.edge_count + right.edge_count,
            conditions=(
                *self.conditions,
                *(condition.shift(self.edge_count) for condition in right.conditions),
            ),
        )


def default_profile(backend_id: str) -> BackendCapabilityProfile:
    repo_root = Path(__file__).resolve().parents[3]
    registry.load_descriptors(repo_root / "descriptors" / "backends")
    return registry.get_capability_profile(backend_id)


def plan_from_compiler_input(
    input_plan: AlgebraOp | PathPatternQuery,
    *,
    backend_id: str,
    language: str,
) -> tuple[AlgebraOp, str, tuple[str, ...]]:
    if isinstance(input_plan, PathPatternQuery):
        type_check_path_pattern(input_plan)
        if input_plan.selector.kind is not SelectorKind.ALL:
            raise unsupported_compilation(
                backend_id=backend_id,
                language=language,
                feature_id="extended_path.Projection",
                message=(
                    "M9 compiles PathPatternQuery only when the selector is ALL; "
                    "selector-style SolutionSpace semantics are outside M9."
                ),
            )
        base = lower_regex(input_plan.expr, input_plan.restrictor, input_plan.max_depth)
        base = lower_source_descriptor(input_plan.source, base)
        base = lower_target_descriptor(input_plan.target, base)
        if input_plan.condition is not None:
            base = SelectionOp(input_plan.condition, base)
        validate_plan(base)
        return base, "PathPatternQuery.m9_all_path_fragment", ("pattern.PathPatternQuery",)

    validate_plan(input_plan)
    return input_plan, type(input_plan).__name__, ()


def infer_required_features(plan: AlgebraOp, *, input_features: Iterable[str] = ()) -> tuple[str, ...]:
    features = set(M9_CORE_FEATURES)
    features.update(input_features)
    features.update(_features_for_plan(plan))
    return tuple(sorted(features))


def ensure_m9_capability_support(
    *,
    profile: BackendCapabilityProfile,
    plan_kind: str,
    required_features: tuple[str, ...],
    language: str,
    allowed_conditionals: frozenset[str] = M9_ALLOWED_CONDITIONALS,
) -> CompatibilityReport:
    blocking: list[UnsupportedFeature] = []
    conditions: list[str] = []
    checked_features: list[str] = []

    for feature_id in sorted(required_features):
        report = check_backend_support(profile, feature_id)
        checked_features.append(feature_id)
        if report.level is SupportLevel.SUPPORTED:
            continue
        if report.level is SupportLevel.CONDITIONAL and feature_id in allowed_conditionals:
            conditions.extend(report.conditions)
            continue
        if report.unsupported_features:
            blocking.extend(report.unsupported_features)
        else:
            blocking.append(
                UnsupportedFeature(
                    feature_id=feature_id,
                    level=report.level,
                    reason=report.reason,
                    conditions=report.conditions,
                )
            )

    if blocking:
        first = blocking[0]
        input_spec = make_compiler_input_spec(
            plan_kind=plan_kind,
            profile=profile,
            required_features=required_features,
        )
        failure_reason = SupportReason(
            code="m9_capability_blocked",
            message=(
                f"M9 cannot compile feature '{first.feature_id}' for "
                f"backend '{profile.backend_id}'."
            ),
            future_milestone=first.reason.future_milestone,
        )
        raise UnsupportedCompilationError(
            message=failure_reason.message,
            failure=first_failure(
                profile=profile,
                language=language,
                unsupported=first,
                reason=failure_reason,
                metadata={
                    "compiler_input": input_spec.to_dict(),
                    "all_unsupported_features": [feature.to_dict() for feature in blocking],
                },
            ),
        )

    return CompatibilityReport(
        backend_id=profile.backend_id,
        feature_id="m9_minimal_compiler_fragment",
        level=SupportLevel.SUPPORTED,
        reason=SupportReason(
            code="m9_capability_checked",
            message=(
                f"M9 compiler accepted {len(checked_features)} feature(s) for "
                f"backend '{profile.backend_id}'."
            ),
        ),
        conditions=tuple(conditions),
        metadata={"checked_features": checked_features},
    )


def first_failure(
    *,
    profile: BackendCapabilityProfile,
    language: str,
    unsupported: UnsupportedFeature,
    reason: SupportReason,
    metadata: dict[str, object],
):
    from xgap.backends.capabilities import CompilerFailureSpec

    return CompilerFailureSpec(
        backend_id=profile.backend_id,
        language=language,
        unsupported_feature=unsupported,
        reason=reason,
        support_level=unsupported.level,
        future_milestone_hint=unsupported.reason.future_milestone,
        metadata=metadata,
    )


def extract_m9_path_shape(plan: AlgebraOp, *, backend_id: str, language: str) -> M9PathShape:
    if isinstance(plan, NodesOp):
        return M9PathShape(edge_count=0)
    if isinstance(plan, EdgesOp):
        return M9PathShape(edge_count=1)
    if isinstance(plan, SelectionOp):
        _ensure_m9_condition(plan.condition, backend_id=backend_id, language=language)
        return extract_m9_path_shape(
            plan.child,
            backend_id=backend_id,
            language=language,
        ).with_condition(plan.condition)
    if isinstance(plan, JoinOp):
        return extract_m9_path_shape(
            plan.left,
            backend_id=backend_id,
            language=language,
        ).join(
            extract_m9_path_shape(plan.right, backend_id=backend_id, language=language)
        )
    if isinstance(plan, UnionOp):
        raise unsupported_compilation(
            backend_id=backend_id,
            language=language,
            feature_id="path_algebra.Union",
            support_level=SupportLevel.CONDITIONAL,
            message="M9 does not compile Union because deterministic duplicate handling is not implemented.",
        )
    if isinstance(plan, RecursiveOp):
        raise unsupported_compilation(
            backend_id=backend_id,
            language=language,
            feature_id=f"path_algebra.Recursive.{plan.mode.value}",
            support_level=SupportLevel.CONDITIONAL,
            message="M9 does not compile Recursive path construction.",
        )
    if isinstance(plan, GroupByOp):
        _raise_unsupported_operator(backend_id, language, "extended_path.GroupBy")
    if isinstance(plan, OrderByOp):
        _raise_unsupported_operator(backend_id, language, "extended_path.OrderBy")
    if isinstance(plan, ProjectionOp):
        _raise_unsupported_operator(backend_id, language, "extended_path.Projection")
    if isinstance(plan, BindNodeOp):
        _raise_unsupported_operator(backend_id, language, "m6.BindNode")
    if isinstance(plan, BindEdgeOp):
        _raise_unsupported_operator(backend_id, language, "m6.BindEdge")
    if isinstance(plan, BindingJoinOp):
        _raise_unsupported_operator(backend_id, language, "m6.BindingJoin")
    if isinstance(plan, BindingProjectOp):
        _raise_unsupported_operator(backend_id, language, "m6.BindingProject")
    if isinstance(plan, QuantifiedCheckOp):
        _raise_unsupported_operator(backend_id, language, "m6.QuantifiedCheck")
    if isinstance(plan, AntiSemiJoinOp):
        _raise_unsupported_operator(backend_id, language, "m6.AntiSemiJoin")
    if isinstance(plan, FocusProjectionOp):
        _raise_unsupported_operator(backend_id, language, "m6.FocusProjection")
    raise unsupported_compilation(
        backend_id=backend_id,
        language=language,
        feature_id=f"xgap.unhandled.{type(plan).__name__}",
        message=f"M9 compilation is not implemented for {type(plan).__name__}.",
    )


def _features_for_plan(plan: AlgebraOp) -> tuple[str, ...]:
    if isinstance(plan, NodesOp):
        return ("path_algebra.Nodes",)
    if isinstance(plan, EdgesOp):
        return ("path_algebra.Edges",)
    if isinstance(plan, SelectionOp):
        return (
            "path_algebra.Selection",
            *_features_for_condition(plan.condition),
            *_features_for_plan(plan.child),
        )
    if isinstance(plan, JoinOp):
        return ("path_algebra.Join", *_features_for_plan(plan.left), *_features_for_plan(plan.right))
    if isinstance(plan, UnionOp):
        return ("path_algebra.Union", *_features_for_plan(plan.left), *_features_for_plan(plan.right))
    if isinstance(plan, RecursiveOp):
        return (f"path_algebra.Recursive.{plan.mode.value}", *_features_for_plan(plan.child))
    if isinstance(plan, GroupByOp):
        return ("extended_path.GroupBy", *_features_for_plan(plan.child))
    if isinstance(plan, OrderByOp):
        return ("extended_path.OrderBy", *_features_for_plan(plan.child))
    if isinstance(plan, ProjectionOp):
        return ("extended_path.Projection", *_features_for_plan(plan.child))
    if isinstance(plan, BindNodeOp):
        return ("m6.BindNode", *_features_for_plan(plan.child))
    if isinstance(plan, BindEdgeOp):
        return ("m6.BindEdge", *_features_for_plan(plan.child))
    if isinstance(plan, BindingJoinOp):
        return ("m6.BindingJoin", *_features_for_plan(plan.left), *_features_for_plan(plan.right))
    if isinstance(plan, BindingProjectOp):
        return ("m6.BindingProject", *_features_for_plan(plan.child))
    if isinstance(plan, QuantifiedCheckOp):
        features = [
            "m6.QuantifiedCheck",
            *_features_for_plan(plan.candidates),
            *_features_for_plan(plan.witnesses),
        ]
        if plan.domain is not None:
            features.extend(_features_for_plan(plan.domain))
        return tuple(features)
    if isinstance(plan, AntiSemiJoinOp):
        return ("m6.AntiSemiJoin", *_features_for_plan(plan.left), *_features_for_plan(plan.right))
    if isinstance(plan, FocusProjectionOp):
        return ("m6.FocusProjection", *_features_for_plan(plan.child))
    return (f"xgap.unhandled.{type(plan).__name__}",)


def _features_for_condition(condition: Condition) -> tuple[str, ...]:
    if isinstance(condition, LabelEquals):
        if isinstance(condition.ref, NodeRef):
            return ("graph_model.node_labels",)
        return ("graph_model.edge_labels",)
    if isinstance(
        condition,
        (
            PropertyEquals,
            PropertyNotEquals,
            PropertyLessThan,
            PropertyLessThanOrEqual,
            PropertyGreaterThan,
            PropertyGreaterThanOrEqual,
        ),
    ):
        return ("graph_model.scalar_property_predicates",)
    if isinstance(condition, NodeNotEquals):
        return ("graph_model.node_identity_predicates",)
    if isinstance(condition, LengthEquals):
        return ("condition.path_length",)
    if isinstance(condition, And):
        features: list[str] = []
        for child in condition.conditions:
            features.extend(_features_for_condition(child))
        return tuple(features)
    if isinstance(condition, Or):
        return ("condition.boolean_or",)
    if isinstance(condition, Not):
        return ("condition.boolean_not",)
    return (f"condition.unhandled.{type(condition).__name__}",)


def _ensure_m9_condition(condition: Condition, *, backend_id: str, language: str) -> None:
    if isinstance(
        condition,
        (
            LabelEquals,
            PropertyEquals,
            PropertyNotEquals,
            PropertyLessThan,
            PropertyLessThanOrEqual,
            PropertyGreaterThan,
            PropertyGreaterThanOrEqual,
            NodeNotEquals,
        ),
    ):
        return
    if isinstance(condition, And):
        for child in condition.conditions:
            _ensure_m9_condition(child, backend_id=backend_id, language=language)
        return
    if isinstance(condition, LengthEquals):
        raise unsupported_compilation(
            backend_id=backend_id,
            language=language,
            feature_id="condition.path_length",
            message="M9 does not compile path-length scalar conditions.",
        )
    if isinstance(condition, Or):
        raise unsupported_compilation(
            backend_id=backend_id,
            language=language,
            feature_id="condition.boolean_or",
            message="M9 does not compile OR conditions.",
        )
    if isinstance(condition, Not):
        raise unsupported_compilation(
            backend_id=backend_id,
            language=language,
            feature_id="condition.boolean_not",
            message="M9 does not compile NOT conditions.",
        )
    raise unsupported_compilation(
        backend_id=backend_id,
        language=language,
        feature_id=f"condition.unhandled.{type(condition).__name__}",
        message=f"M9 does not compile condition {type(condition).__name__}.",
    )


def _raise_unsupported_operator(backend_id: str, language: str, feature_id: str) -> None:
    raise unsupported_compilation(
        backend_id=backend_id,
        language=language,
        feature_id=feature_id,
        message=f"M9 does not compile {feature_id}.",
    )
