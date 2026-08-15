"""Minimal M9 SPARQL compiler."""

from __future__ import annotations

import json
import math
from numbers import Real
from typing import Any, Iterable, Mapping

from xgap.algebra.conditions import (
    And,
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
from xgap.algebra.ops import AlgebraOp
from xgap.backends.capabilities import BackendCapabilityProfile
from xgap.backends.mapping import (
    BackendMappingError,
    MappedNativeTerm,
    RdfBackendMapping,
)
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


_SPARQL_ASSUMPTIONS = (
    "M9 emits row bindings for a fixed OUT path fragment, not native XGAP PathSet objects.",
    "DatasetBundle backend mappings provide all RDF class, predicate, and property IRIs.",
    "RDF type triples represent XGAP node-label predicates.",
    "Edge property predicates are unsupported because M9 does not define RDF edge reification.",
)


def compile_sparql(
    plan: AlgebraOp | PathPatternQuery,
    *,
    profile: BackendCapabilityProfile | None = None,
    artifact_id: str = "m9-sparql-query",
    backend_mapping: Mapping[str, Any] | RdfBackendMapping | None = None,
) -> QueryArtifact:
    """Compile the bounded M9 path fragment to a SPARQL query artifact."""

    profile = profile or default_profile("fuseki")
    if profile.language.lower() != "sparql":
        raise unsupported_compilation(
            backend_id=profile.backend_id,
            language=profile.language,
            feature_id="native.sparql",
            message=f"Backend '{profile.backend_id}' does not use SPARQL.",
        )
    if backend_mapping is None:
        raise unsupported_compilation(
            backend_id=profile.backend_id,
            language="sparql",
            feature_id="rdf_mapping.missing",
            message="M9 SPARQL compilation requires a DatasetBundle backend mapping.",
        )
    try:
        rdf_mapping = (
            backend_mapping
            if isinstance(backend_mapping, RdfBackendMapping)
            else RdfBackendMapping.from_artifact(
                backend_mapping, backend_id=profile.backend_id
            )
        )
    except BackendMappingError as error:
        raise unsupported_compilation(
            backend_id=profile.backend_id,
            language="sparql",
            feature_id="rdf_mapping.invalid",
            message=str(error),
        ) from error

    logical_plan, plan_kind, input_features = plan_from_compiler_input(
        plan,
        backend_id=profile.backend_id,
        language="sparql",
    )
    required_features = infer_required_features(
        logical_plan,
        input_features=(
            *input_features,
            "graph_model.rdf_graph",
            "native.sparql",
        ),
    )
    ensure_m9_capability_support(
        profile=profile,
        plan_kind=plan_kind,
        required_features=required_features,
        language="sparql",
    )
    shape = extract_m9_path_shape(
        logical_plan,
        backend_id=profile.backend_id,
        language="sparql",
    )
    text, mapped_terms = _emit_sparql(shape, profile.backend_id, rdf_mapping)
    return make_query_artifact(
        artifact_id=artifact_id,
        language="sparql",
        text=text,
        profile=profile,
        required_features=required_features,
        semantic_assumptions=_SPARQL_ASSUMPTIONS,
        extra_parameters={
            "backend_mapping": {
                "mapping_id": rdf_mapping.mapping_id,
                "version": rdf_mapping.version,
                "mapping_hash": rdf_mapping.mapping_hash,
                "relevant_mapped_iris": [
                    item.to_dict() for item in mapped_terms
                ],
            }
        },
    )


def _emit_sparql(
    shape,
    backend_id: str,
    mapping: RdfBackendMapping,
) -> tuple[str, tuple[MappedNativeTerm, ...]]:
    atoms = _iter_atomic_bound_conditions(shape.conditions)
    edge_labels = _edge_label_terms(atoms, backend_id)
    body: list[str] = []
    used_terms: dict[tuple[str, str], MappedNativeTerm] = {}

    if shape.edge_count == 0:
        body.extend(_zero_length_node_body())
    else:
        for edge_index in range(shape.edge_count):
            predicate = edge_labels.get(edge_index)
            if predicate is None:
                body.append(f"?n{edge_index} ?e{edge_index + 1} ?n{edge_index + 1} .")
            else:
                term = _mapped_iri(
                    predicate, "edge_labels", mapping, used_terms, backend_id
                )
                body.append(f"?n{edge_index} {term} ?n{edge_index + 1} .")
                body.append(f"BIND({term} AS ?e{edge_index + 1})")

    value_counter = 0
    for bound in atoms:
        condition = bound.condition
        if isinstance(condition, LabelEquals) and isinstance(condition.ref, EdgeRef):
            continue
        clauses, value_counter = _condition_to_sparql(
            bound,
            value_counter,
            backend_id,
            mapping,
            used_terms,
        )
        body.extend(clauses)

    body.append("BIND(?n0 AS ?source)")
    body.append(f"BIND(?n{shape.edge_count} AS ?target)")

    select_terms = ["?source", "?target"]
    select_terms.extend(f"?n{index}" for index in range(shape.node_count))
    select_terms.extend(f"?e{index + 1}" for index in range(shape.edge_count))

    lines = [f"SELECT DISTINCT {' '.join(select_terms)} WHERE {{"]
    lines.extend(f"  {clause}" for clause in body)
    lines.append("}")
    return "\n".join(lines), tuple(
        used_terms[key] for key in sorted(used_terms)
    )


def _zero_length_node_body() -> list[str]:
    return [
        "{ ?n0 ?_p0 ?_o0 . }",
        "UNION",
        "{ ?_s0 ?_p1 ?n0 . }",
    ]


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


def _edge_label_terms(atoms: tuple[BoundCondition, ...], backend_id: str) -> dict[int, str]:
    labels: dict[int, str] = {}
    for bound in atoms:
        condition = bound.condition
        if not isinstance(condition, LabelEquals) or not isinstance(condition.ref, EdgeRef):
            continue
        if condition.value is None:
            raise unsupported_compilation(
                backend_id=backend_id,
                language="sparql",
                feature_id="condition.null_label",
                message="M9 SPARQL compilation does not support null edge-label predicates.",
            )
        edge_index = bound.edge_index(condition.ref)
        existing = labels.get(edge_index)
        if existing is not None and existing != condition.value:
            raise unsupported_compilation(
                backend_id=backend_id,
                language="sparql",
                feature_id="condition.conflicting_edge_labels",
                message="M9 SPARQL compilation does not support conflicting labels on one edge.",
            )
        labels[edge_index] = condition.value
    return labels


def _condition_to_sparql(
    bound: BoundCondition,
    value_counter: int,
    backend_id: str,
    mapping: RdfBackendMapping,
    used_terms: dict[tuple[str, str], MappedNativeTerm],
) -> tuple[list[str], int]:
    condition = bound.condition
    if isinstance(condition, LabelEquals):
        if condition.value is None:
            raise unsupported_compilation(
                backend_id=backend_id,
                language="sparql",
                feature_id="condition.null_label",
                message="M9 SPARQL compilation does not support null node-label predicates.",
            )
        if isinstance(condition.ref, NodeRef):
            term = _mapped_iri(
                condition.value, "node_labels", mapping, used_terms, backend_id
            )
            return [f"{_node_var(bound, condition.ref)} a {term} ."], value_counter
        return [], value_counter

    if isinstance(condition, PropertyEquals):
        return _property_condition(
            bound,
            condition.ref,
            condition.property_name,
            "=",
            condition.value,
            value_counter,
            backend_id,
            mapping,
            used_terms,
        )
    if isinstance(condition, PropertyNotEquals):
        return _property_condition(
            bound,
            condition.ref,
            condition.property_name,
            "!=",
            condition.value,
            value_counter,
            backend_id,
            mapping,
            used_terms,
        )
    if isinstance(condition, PropertyLessThan):
        _require_numeric(condition.value, backend_id, "sparql")
        return _property_condition(
            bound,
            condition.ref,
            condition.property_name,
            "<",
            condition.value,
            value_counter,
            backend_id,
            mapping,
            used_terms,
        )
    if isinstance(condition, PropertyLessThanOrEqual):
        _require_numeric(condition.value, backend_id, "sparql")
        return _property_condition(
            bound,
            condition.ref,
            condition.property_name,
            "<=",
            condition.value,
            value_counter,
            backend_id,
            mapping,
            used_terms,
        )
    if isinstance(condition, PropertyGreaterThan):
        _require_numeric(condition.value, backend_id, "sparql")
        return _property_condition(
            bound,
            condition.ref,
            condition.property_name,
            ">",
            condition.value,
            value_counter,
            backend_id,
            mapping,
            used_terms,
        )
    if isinstance(condition, PropertyGreaterThanOrEqual):
        _require_numeric(condition.value, backend_id, "sparql")
        return _property_condition(
            bound,
            condition.ref,
            condition.property_name,
            ">=",
            condition.value,
            value_counter,
            backend_id,
            mapping,
            used_terms,
        )

    raise unsupported_compilation(
        backend_id=backend_id,
        language="sparql",
        feature_id=f"condition.unhandled.{type(condition).__name__}",
        message=f"M9 SPARQL compilation does not support {type(condition).__name__}.",
    )


def _property_condition(
    bound: BoundCondition,
    ref: NodeRef | EdgeRef,
    property_name: str,
    operator: str,
    value: object,
    value_counter: int,
    backend_id: str,
    mapping: RdfBackendMapping,
    used_terms: dict[tuple[str, str], MappedNativeTerm],
) -> tuple[list[str], int]:
    if isinstance(ref, EdgeRef):
        raise unsupported_compilation(
            backend_id=backend_id,
            language="sparql",
            feature_id="graph_model.edge_properties",
            message="M9 SPARQL compilation does not support edge property predicates.",
        )
    if value is None:
        raise unsupported_compilation(
            backend_id=backend_id,
            language="sparql",
            feature_id="condition.null_property_literal",
            message="M9 SPARQL compilation does not support null property literals.",
        )
    value_var = f"?v{value_counter}"
    property_term = _mapped_iri(
        property_name, "properties", mapping, used_terms, backend_id
    )
    clauses = [
        f"{_node_var(bound, ref)} {property_term} {value_var} .",
        f"FILTER({value_var} {operator} {_sparql_literal(value, backend_id)})",
    ]
    return clauses, value_counter + 1


def _node_var(bound: BoundCondition, ref: NodeRef) -> str:
    return f"?n{bound.node_index(ref)}"


def _mapped_iri(
    value: str,
    token_kind: str,
    mapping: RdfBackendMapping,
    used_terms: dict[tuple[str, str], MappedNativeTerm],
    backend_id: str,
) -> str:
    try:
        term = mapping.resolve(value, token_kind)
    except BackendMappingError as error:
        raise unsupported_compilation(
            backend_id=backend_id,
            language="sparql",
            feature_id="rdf_mapping.unresolved_term",
            message=str(error),
        ) from error
    used_terms[(token_kind, value)] = term
    return f"<{term.iri}>"


def _sparql_literal(value: object, backend_id: str) -> str:
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
        language="sparql",
        feature_id="condition.unsupported_literal",
        message=f"M9 SPARQL compilation does not support literal {value!r}.",
    )


def _require_numeric(value: object, backend_id: str, language: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise unsupported_compilation(
            backend_id=backend_id,
            language=language,
            feature_id="condition.non_numeric_ordering_literal",
            message="M9 numeric ordering requires a finite numeric non-bool literal.",
        )
