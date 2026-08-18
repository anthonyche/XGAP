"""Minimal M9 Cypher compiler."""

from __future__ import annotations

import json
import math
import re
from numbers import Real
from typing import Iterable

from xgap.algebra.conditions import (
    And,
    Condition,
    EdgeRef,
    LabelEquals,
    NodeNotEquals,
    NodeRef,
    PropertyEquals,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
    PropertyLessThan,
    PropertyLessThanOrEqual,
    PropertyNotEquals,
)
from xgap.algebra.ops import AlgebraOp
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.compilers.artifacts import make_query_artifact
from xgap.compilers.errors import unsupported_compilation
from xgap.compilers.features import (
    BoundCondition,
    default_profile,
    ensure_m9_capability_support,
    extract_m9_path_shape,
    infer_required_features,
    plan_from_compiler_input,
)
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import PathPatternQuery


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_CYPHER_ASSUMPTIONS = (
    "M9 emits row bindings for a fixed OUT path fragment, not native XGAP PathSet objects.",
    "Neo4j node labels represent XGAP node-label predicates.",
    "Neo4j relationship types represent XGAP edge-label predicates.",
    "Missing properties and non-numeric values follow Cypher WHERE null-elimination for this fragment.",
)


def compile_cypher(
    plan: AlgebraOp | PathPatternQuery,
    *,
    profile: BackendCapabilityProfile | None = None,
    artifact_id: str = "m9-cypher-query",
) -> QueryArtifact:
    """Compile the bounded M9 path fragment to a Cypher query artifact."""

    profile = profile or default_profile("neo4j")
    if profile.language.lower() != "cypher":
        raise unsupported_compilation(
            backend_id=profile.backend_id,
            language=profile.language,
            feature_id="native.cypher",
            message=f"Backend '{profile.backend_id}' does not use Cypher.",
        )

    logical_plan, plan_kind, input_features = plan_from_compiler_input(
        plan,
        backend_id=profile.backend_id,
        language="cypher",
    )
    required_features = infer_required_features(
        logical_plan,
        input_features=(
            *input_features,
            "graph_model.labeled_property_graph",
            "native.cypher",
        ),
    )
    ensure_m9_capability_support(
        profile=profile,
        plan_kind=plan_kind,
        required_features=required_features,
        language="cypher",
    )
    shape = extract_m9_path_shape(
        logical_plan,
        backend_id=profile.backend_id,
        language="cypher",
    )
    text = _emit_cypher(shape, profile.backend_id)
    return make_query_artifact(
        artifact_id=artifact_id,
        language="cypher",
        text=text,
        profile=profile,
        required_features=required_features,
        semantic_assumptions=_CYPHER_ASSUMPTIONS,
    )


def _emit_cypher(shape, backend_id: str) -> str:
    where_terms: list[str] = []
    for bound in _iter_atomic_bound_conditions(shape.conditions):
        where_terms.append(_condition_to_cypher(bound, backend_id))

    lines = [f"MATCH {_path_pattern(shape.edge_count)}"]
    if where_terms:
        lines.append("WHERE " + "\n  AND ".join(where_terms))
    lines.append("RETURN DISTINCT " + ", ".join(_return_terms(shape.edge_count)))
    return "\n".join(lines)


def _path_pattern(edge_count: int) -> str:
    if edge_count == 0:
        return "(n0)"
    parts = ["(n0)"]
    for edge_index in range(edge_count):
        parts.append(f"-[e{edge_index + 1}]->(n{edge_index + 1})")
    return "".join(parts)


def _return_terms(edge_count: int) -> tuple[str, ...]:
    nodes = ", ".join(f"n{index}" for index in range(edge_count + 1))
    edges = ", ".join(f"e{index + 1}" for index in range(edge_count))
    return (
        "n0 AS source",
        f"n{edge_count} AS target",
        f"[{nodes}] AS nodes",
        f"[{edges}] AS edges",
    )


def _iter_atomic_bound_conditions(
    conditions: Iterable[BoundCondition],
) -> tuple[BoundCondition, ...]:
    atoms: list[BoundCondition] = []
    for bound in conditions:
        atoms.extend(_flatten_bound_condition(bound))
    return tuple(atoms)


def _flatten_bound_condition(bound: BoundCondition) -> tuple[BoundCondition, ...]:
    if isinstance(bound.condition, And):
        return tuple(
            BoundCondition(
                condition=condition,
                node_offset=bound.node_offset,
                edge_offset=bound.edge_offset,
                edge_count=bound.edge_count,
            )
            for condition in bound.condition.conditions
        )
    return (bound,)


def _condition_to_cypher(bound: BoundCondition, backend_id: str) -> str:
    condition = bound.condition
    if isinstance(condition, LabelEquals):
        if condition.value is None:
            raise unsupported_compilation(
                backend_id=backend_id,
                language="cypher",
                feature_id="condition.null_label",
                message="M9 Cypher compilation does not support null label predicates.",
            )
        if isinstance(condition.ref, NodeRef):
            return f"{_node_var(bound, condition.ref)}:{_cypher_identifier(condition.value)}"
        return f"type({_edge_var(bound, condition.ref)}) = {_cypher_literal(condition.value, backend_id)}"

    if isinstance(condition, PropertyEquals):
        return _property_comparison(bound, condition.ref, condition.property_name, "=", condition.value, backend_id)
    if isinstance(condition, PropertyNotEquals):
        return _property_comparison(bound, condition.ref, condition.property_name, "<>", condition.value, backend_id)
    if isinstance(condition, NodeNotEquals):
        return f"{_node_var(bound, condition.left)} <> {_node_var(bound, condition.right)}"
    if isinstance(condition, PropertyLessThan):
        _require_numeric(condition.value, backend_id, "cypher")
        return _property_comparison(bound, condition.ref, condition.property_name, "<", condition.value, backend_id)
    if isinstance(condition, PropertyLessThanOrEqual):
        _require_numeric(condition.value, backend_id, "cypher")
        return _property_comparison(bound, condition.ref, condition.property_name, "<=", condition.value, backend_id)
    if isinstance(condition, PropertyGreaterThan):
        _require_numeric(condition.value, backend_id, "cypher")
        return _property_comparison(bound, condition.ref, condition.property_name, ">", condition.value, backend_id)
    if isinstance(condition, PropertyGreaterThanOrEqual):
        _require_numeric(condition.value, backend_id, "cypher")
        return _property_comparison(bound, condition.ref, condition.property_name, ">=", condition.value, backend_id)

    raise unsupported_compilation(
        backend_id=backend_id,
        language="cypher",
        feature_id=f"condition.unhandled.{type(condition).__name__}",
        message=f"M9 Cypher compilation does not support {type(condition).__name__}.",
    )


def _property_comparison(
    bound: BoundCondition,
    ref: NodeRef | EdgeRef,
    property_name: str,
    operator: str,
    value: object,
    backend_id: str,
) -> str:
    if value is None:
        raise unsupported_compilation(
            backend_id=backend_id,
            language="cypher",
            feature_id="condition.null_property_literal",
            message="M9 Cypher compilation does not support null property literals.",
        )
    if isinstance(ref, NodeRef):
        subject = _node_var(bound, ref)
    else:
        subject = _edge_var(bound, ref)
    return (
        f"{subject}.{_cypher_identifier(property_name)} "
        f"{operator} {_cypher_literal(value, backend_id)}"
    )


def _node_var(bound: BoundCondition, ref: NodeRef) -> str:
    return f"n{bound.node_index(ref)}"


def _edge_var(bound: BoundCondition, ref: EdgeRef) -> str:
    return f"e{bound.edge_index(ref) + 1}"


def _cypher_identifier(value: str) -> str:
    if _IDENTIFIER_RE.match(value):
        return value
    return "`" + value.replace("`", "``") + "`"


def _cypher_literal(value: object, backend_id: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    raise unsupported_compilation(
        backend_id=backend_id,
        language="cypher",
        feature_id="condition.unsupported_literal",
        message=f"M9 Cypher compilation does not support literal {value!r}.",
    )


def _require_numeric(value: object, backend_id: str, language: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise unsupported_compilation(
            backend_id=backend_id,
            language=language,
            feature_id="condition.non_numeric_ordering_literal",
            message="M9 numeric ordering requires a finite numeric non-bool literal.",
        )
