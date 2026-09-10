"""Explicit fixed directed row compilation, independent of M5 path lowering.

No legacy entry point selects this compiler automatically. This is not a new
algebra operator, PathSet encoder, grounding policy or backend execution claim.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from xgap.algebra.conditions import (
    And,
    Condition,
    EdgeRef,
    LabelEquals,
    LengthEquals,
    NodeNotEquals,
    NodeRef,
    PropertyEquals,
    PropertyNotEquals,
    PropertyLessThan,
    PropertyLessThanOrEqual,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
)
from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    CompilerFailureSpec,
    SupportLevel,
    SupportReason,
    UnsupportedFeature,
)
from xgap.backends.compatibility import check_backend_support
from xgap.backends.mapping import (
    BackendMappingError,
    MappedNativeTerm,
    RdfBackendMapping,
)
from xgap.compilers import cypher, sparql
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.compilers.features import BoundCondition, default_profile
from xgap.compilers.rdf_encoding import RdfEdgeEncoding, RdfRowEncoding
from xgap.backends.rdf_terms import RDF_TERMS_V1
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import (
    Direction,
    EdgePattern,
    PathPatternQuery,
    Rel,
    SelectorKind,
    Seq,
)
from xgap.pattern.semantic_validation import (
    NUMERIC_CONDITIONS,
    PROPERTY_CONDITIONS,
    type_check_semantic_path_pattern,
)
from xgap.pattern.typecheck import PatternTypeError


PROFILE = "typed_fixed_directed_rows_v1"
MAX_EDGES = 64
_OPERATORS = {
    PropertyEquals: "=",
    PropertyNotEquals: "!=",
    PropertyLessThan: "<",
    PropertyLessThanOrEqual: "<=",
    PropertyGreaterThan: ">",
    PropertyGreaterThanOrEqual: ">=",
}


@dataclass(frozen=True)
class DirectedShape:
    edges: tuple[EdgePattern, ...]
    conditions: tuple[BoundCondition, ...]

    @property
    def edge_count(self) -> int:
        return len(self.edges)


def _fail(
    profile: BackendCapabilityProfile, feature: str, message: str
) -> UnsupportedCompilationError:
    reason = SupportReason(PROFILE, message)
    issue = UnsupportedFeature(feature, reason)
    return UnsupportedCompilationError(
        message,
        CompilerFailureSpec(
            backend_id=profile.backend_id,
            language=profile.language,
            unsupported_feature=issue,
            reason=reason,
            support_level=SupportLevel.UNSUPPORTED,
            metadata={"compiler": PROFILE},
        ),
    )


def _identity(value: Any) -> Any:
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            **{f.name: _identity(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, Mapping):
        return {key: _identity(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_identity(item) for item in value]
    return value


def _shape(query: PathPatternQuery, profile: BackendCapabilityProfile) -> DirectedShape:
    if not isinstance(query, PathPatternQuery):
        raise _fail(
            profile,
            "input.typed_path",
            "This profile requires a typed PathPatternQuery, not native text or a logical plan.",
        )
    try:
        type_check_semantic_path_pattern(query)
    except PatternTypeError as error:
        raise _fail(profile, "input.semantic_type_check", str(error)) from error
    if query.selector.kind is not SelectorKind.ALL:
        raise _fail(profile, "selector", "Only ALL row selection is supported.")
    edges: list[EdgePattern] = []
    pending = [query.expr]
    while pending:
        item = pending.pop()
        if isinstance(item, Seq):
            pending.extend((item.right, item.left))
        elif isinstance(item, Rel):
            if item.edge.direction not in (Direction.OUT, Direction.IN):
                raise _fail(
                    profile,
                    "direction",
                    "Only explicit OUT and IN directions are supported.",
                )
            edges.append(item.edge)
            if len(edges) > MAX_EDGES:
                raise _fail(
                    profile,
                    "path.size",
                    f"Fixed paths must not exceed {MAX_EDGES} edges.",
                )
        else:
            raise _fail(
                profile, "regex", f"{type(item).__name__} is not a fixed Rel/Seq path."
            )
    count = len(edges)
    atoms: list[Condition] = []
    for node, ref in ((query.source, NodeRef.first()), (query.target, NodeRef.last())):
        if node.label is not None:
            atoms.append(LabelEquals(ref, node.label))
        atoms.extend(
            PropertyEquals(ref, name, value)
            for name, value in sorted(node.properties.items())
        )
    for index, edge in enumerate(edges, 1):
        if edge.label is not None:
            atoms.append(LabelEquals(EdgeRef(index), edge.label))
        atoms.extend(
            PropertyEquals(EdgeRef(index), name, value)
            for name, value in sorted(edge.properties.items())
        )
    pending = [query.condition] if query.condition is not None else []
    while pending:
        item = pending.pop()
        if type(item) is And:
            pending.extend(reversed(item.conditions))
        elif type(item) in (
            LabelEquals,
            NodeNotEquals,
            LengthEquals,
            *PROPERTY_CONDITIONS,
        ):
            atoms.append(item)
        else:
            raise _fail(
                profile,
                "condition",
                f"{type(item).__name__} is outside the conjunctive fixed-row profile.",
            )
    for item in atoms:
        if type(item) in PROPERTY_CONDITIONS:
            value = item.value
            if value is None or type(value) not in (str, bool, int, float):
                raise _fail(
                    profile,
                    "literal",
                    "Only non-null scalar property constants are supported.",
                )
            if type(value) is int and not -(2**63) <= value < 2**63:
                raise _fail(
                    profile,
                    "literal.integer_range",
                    "Native portable integer literals require signed 64-bit range.",
                )
            if isinstance(value, str):
                _unicode_safe(value, profile)
            _identifier_safe(item.property_name, profile)
        if isinstance(item, LabelEquals):
            if item.value is None:
                raise _fail(
                    profile, "label.null", "Null label predicates are not supported."
                )
            _identifier_safe(item.value, profile)
    return DirectedShape(
        tuple(edges), tuple(BoundCondition(item, 0, 0, count) for item in atoms)
    )


def _identifier_safe(value: str, profile: BackendCapabilityProfile) -> None:
    # In Cypher backslash-unicode escapes can introduce backticks after escaping.
    if "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _fail(
            profile,
            "identifier",
            "Identifiers must not contain backslash escapes or controls.",
        )
    _unicode_safe(value, profile)


def _unicode_safe(value: str, profile: BackendCapabilityProfile) -> None:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise _fail(
            profile,
            "literal.unicode",
            "Native terms require Unicode scalar values, not unpaired surrogates.",
        )


def _literal(value: object) -> str:
    # JSON's UTF-16 surrogate escapes are not portable SPARQL Unicode escapes.
    # Keep scalar Unicode characters intact while escaping quotes/controls.
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _required(
    shape: DirectedShape, profile: BackendCapabilityProfile,
    rdf_edge_encoding: RdfEdgeEncoding | None = None,
) -> tuple[str, ...]:
    language = profile.language.lower()
    features = {
        "graph_model.directed_edges",
        "result_model.row_bindings",
        f"native.{language}",
        (
            "graph_model.rdf_graph"
            if language == "sparql"
            else "graph_model.labeled_property_graph"
        ),
    }
    for bound in shape.conditions:
        item = bound.condition
        if isinstance(item, LabelEquals):
            features.add(
                "graph_model.node_labels"
                if isinstance(item.ref, NodeRef)
                else "graph_model.edge_labels"
            )
        elif isinstance(item, NodeNotEquals):
            features.add("graph_model.node_identity_predicates")
        elif type(item) in PROPERTY_CONDITIONS:
            features.add("graph_model.scalar_property_predicates")
            if (language == "sparql" and isinstance(item.ref, EdgeRef)
                    and rdf_edge_encoding is None):
                raise _fail(
                    profile,
                    "graph_model.edge_properties",
                    "RDF edge reification is not defined by this profile.",
                )
    for feature in sorted(features):
        report = check_backend_support(profile, feature)
        mapped_conditional = language == "sparql" and feature in (
            "graph_model.node_labels",
            "graph_model.scalar_property_predicates",
        )
        if report.level is not SupportLevel.SUPPORTED and not (
            mapped_conditional and report.level is SupportLevel.CONDITIONAL
        ):
            raise _fail(
                profile,
                feature,
                f"Backend profile does not admit required primitive {feature}.",
            )
    return tuple(sorted(features))


def _cypher(
    shape: DirectedShape, profile: BackendCapabilityProfile
) -> tuple[str, dict[str, Any]]:
    lines = []
    for index, edge in enumerate(shape.edges):
        middle = (
            f"-[e{index + 1}]->"
            if edge.direction is Direction.OUT
            else f"<-[e{index + 1}]-"
        )
        lines.append(f"MATCH (n{index}){middle}(n{index + 1})")
    filters = []
    for bound in shape.conditions:
        item = bound.condition
        if isinstance(item, LengthEquals):
            filters.append("true" if item.value == shape.edge_count else "false")
            continue
        if type(item) in PROPERTY_CONDITIONS:
            subject = (
                cypher._node_var(bound, item.ref)
                if isinstance(item.ref, NodeRef)
                else cypher._edge_var(bound, item.ref)
            )
            prop = f"{subject}.{cypher._cypher_identifier(item.property_name)}"
            operator = (
                "<>" if type(item) is PropertyNotEquals else _OPERATORS[type(item)]
            )
            term = f"{prop} {operator} {_literal(item.value)}"
            if type(item) in NUMERIC_CONDITIONS:
                term = f"(({prop} IS :: INTEGER NOT NULL OR {prop} IS :: FLOAT NOT NULL) AND {term})"
        elif isinstance(item, LabelEquals) and isinstance(item.ref, EdgeRef):
            term = f"type({cypher._edge_var(bound, item.ref)}) = {_literal(item.value)}"
        else:
            term = cypher._condition_to_cypher(bound, profile.backend_id)
        filters.append(term)
    if filters:
        lines.append("WHERE " + "\n  AND ".join(filters))
    terms = ["n0 AS source", f"n{shape.edge_count} AS target"]
    terms.extend(f"n{i} AS n{i}" for i in range(shape.edge_count + 1))
    terms.extend(f"e{i} AS e{i}" for i in range(1, shape.edge_count + 1))
    lines.append("RETURN DISTINCT " + ", ".join(terms))
    return "\n".join(lines), {}


def _sparql(
    shape: DirectedShape,
    profile: BackendCapabilityProfile,
    backend_mapping: Mapping[str, Any] | RdfBackendMapping | None,
    rdf_encoding: RdfRowEncoding | None = None,
    rdf_edge_encoding: RdfEdgeEncoding | None = None,
) -> tuple[str, dict[str, Any]]:
    if backend_mapping is None:
        raise _fail(
            profile,
            "rdf_mapping.missing",
            "SPARQL requires an explicit backend mapping.",
        )
    try:
        mapping = (
            backend_mapping
            if isinstance(backend_mapping, RdfBackendMapping)
            else RdfBackendMapping.from_artifact(
                backend_mapping, backend_id=profile.backend_id
            )
        )
        if mapping.backend_id != profile.backend_id:
            raise BackendMappingError("RDF mapping belongs to a different backend.")
        mapping.validate()
    except BackendMappingError as error:
        raise _fail(profile, "rdf_mapping.invalid", str(error)) from error
    used: dict[tuple[str, str], MappedNativeTerm] = {}
    labels = sparql._edge_label_terms(shape.conditions, profile.backend_id)
    body = []
    for index, edge in enumerate(shape.edges):
        left, right = (
            (index, index + 1)
            if edge.direction is Direction.OUT
            else (index + 1, index)
        )
        if rdf_edge_encoding is not None:
            encoding = rdf_edge_encoding
            variable = f"?e{index + 1}"
            body.extend((
                f"{variable} <{encoding.class_predicate_iri}> <{encoding.edge_class_iri}> .",
                f"{variable} <{encoding.source_predicate_iri}> ?n{left} .",
                f"{variable} <{encoding.target_predicate_iri}> ?n{right} .",
            ))
            if index in labels:
                term = (
                    _literal(labels[index])
                    if encoding.label_encoding == "logical_string"
                    else sparql._mapped_iri(labels[index], "edge_labels", mapping,
                                            used, profile.backend_id)
                )
                body.append(f"{variable} <{encoding.label_predicate_iri}> {term} .")
            continue
        predicate = f"?e{index + 1}"
        if index in labels:
            predicate = sparql._mapped_iri(
                labels[index], "edge_labels", mapping, used, profile.backend_id
            )
            body.append(f"BIND({predicate} AS ?e{index + 1})")
        body.append(f"?n{left} {predicate} ?n{right} .")
    counter = 0
    for bound in shape.conditions:
        item = bound.condition
        if isinstance(item, LabelEquals) and isinstance(item.ref, EdgeRef):
            continue
        if isinstance(item, LengthEquals):
            body.append(
                "FILTER(true)" if item.value == shape.edge_count else "FILTER(false)"
            )
            continue
        if type(item) in PROPERTY_CONDITIONS:
            if (
                rdf_encoding is not None
                and item.property_name == rdf_encoding.identity_property
                and isinstance(item.ref, NodeRef)
            ):
                if type(item) not in (
                    PropertyEquals,
                    PropertyNotEquals,
                ) or not isinstance(item.ref, NodeRef):
                    raise _fail(
                        profile,
                        "rdf_identity",
                        "Resource identity supports node equality/inequality only.",
                    )
                try:
                    iri = rdf_encoding.resource_iri(item.value)
                except ValueError as error:
                    raise _fail(profile, "rdf_identity", str(error)) from error
                node = sparql._node_var(bound, item.ref)
                comparison = f"sameTerm({node}, <{iri}>)"
                if type(item) is PropertyNotEquals:
                    # A literal or an unmapped resource has no logical ID.
                    # Negating sameTerm alone would incorrectly admit it.
                    namespace = _literal(rdf_encoding.resource_namespace)
                    body.append(
                        f"FILTER(isIRI({node}) && STRSTARTS(STR({node}), {namespace}) "
                        f"&& REGEX(SUBSTR(STR({node}), {len(rdf_encoding.resource_namespace) + 1}), "
                        f'"^[A-Za-z0-9_][A-Za-z0-9_.-]*$") && !{comparison})'
                    )
                else:
                    body.append(f"FILTER({comparison})")
                continue
            predicate = sparql._mapped_iri(
                item.property_name, "properties", mapping, used, profile.backend_id
            )
            variable = f"?v{counter}"
            subject = (sparql._node_var(bound, item.ref)
                       if isinstance(item.ref, NodeRef)
                       else f"?e{bound.edge_index(item.ref) + 1}")
            body.append(f"{subject} {predicate} {variable} .")
            body.append(
                f"FILTER({variable} {_OPERATORS[type(item)]} {_literal(item.value)})"
            )
            if type(item) in NUMERIC_CONDITIONS:
                body.append(f"FILTER(isNumeric({variable}))")
            counter += 1
        elif (
            isinstance(item, LabelEquals)
            and isinstance(item.ref, NodeRef)
            and rdf_encoding is not None
        ):
            term = sparql._mapped_iri(
                item.value, "node_labels", mapping, used, profile.backend_id
            )
            body.append(
                f"{sparql._node_var(bound, item.ref)} <{rdf_encoding.class_predicate_iri}> {term} ."
            )
        else:
            clauses, counter = sparql._condition_to_sparql(
                bound, counter, profile.backend_id, mapping, used
            )
            body.extend(clauses)
    # Validate the expanded term, including compact-prefix expansions, at the
    # native text boundary. No SERVICE/GRAPH/native fragment can be injected.
    for term in used.values():
        _unicode_safe(term.iri, profile)
        if any(
            char in '<>"{}|^`\\' or ord(char) <= 32 or ord(char) == 127
            for char in term.iri
        ):
            raise _fail(
                profile,
                "rdf_mapping.unsafe_iri",
                "Mapped IRI contains illegal SPARQL IRIREF characters.",
            )
    body.extend(("BIND(?n0 AS ?source)", f"BIND(?n{shape.edge_count} AS ?target)"))
    columns = [
        "source",
        "target",
        *(f"n{i}" for i in range(shape.edge_count + 1)),
        *(f"e{i}" for i in range(1, shape.edge_count + 1)),
    ]
    text = "SELECT DISTINCT " + " ".join("?" + name for name in columns) + " WHERE {\n"
    text += "\n".join("  " + line for line in body) + "\n}"
    return text, {
        **({
            "rdf_edge_encoding_id": rdf_edge_encoding.encoding_id,
            "rdf_edge_encoding_sha256": rdf_edge_encoding.identity,
            "rdf_edge_identity": "resource_iri",
        } if rdf_edge_encoding is not None else {}),
        **(
            {
                "rdf_row_encoding_sha256": rdf_encoding.identity,
                "rdf_row_encoding_id": rdf_encoding.encoding_id,
            }
            if rdf_encoding is not None
            else {}
        ),
        **({"rdf_result_encoding": RDF_TERMS_V1,
            "expected_result_columns": list(columns)}
           if rdf_encoding is not None or rdf_edge_encoding is not None else {}),
        "backend_mapping": {
            "mapping_id": mapping.mapping_id,
            "version": mapping.version,
            "mapping_hash": mapping.mapping_hash,
            "relevant_mapped_iris": [used[key].to_dict() for key in sorted(used)],
        },
    }


def compile_directed_rows(
    query: PathPatternQuery,
    *,
    backend_id: str,
    profile: BackendCapabilityProfile | None = None,
    backend_mapping: Mapping[str, Any] | RdfBackendMapping | None = None,
    artifact_id: str = "typed-directed-rows",
    rdf_encoding: RdfRowEncoding | None = None,
    rdf_edge_encoding: RdfEdgeEncoding | None = None,
) -> QueryArtifact:
    """Compile one explicitly opted-in typed fragment; no network or fallback."""
    profile = profile or default_profile(backend_id)
    if profile.backend_id != backend_id or profile.language.lower() not in (
        "cypher",
        "sparql",
    ):
        raise _fail(
            profile,
            "backend",
            "Backend identity/language does not match the requested target.",
        )
    shape = _shape(query, profile)
    language = profile.language.lower()
    if rdf_encoding is not None and (
        not isinstance(rdf_encoding, RdfRowEncoding) or language != "sparql"
    ):
        raise _fail(
            profile,
            "rdf_encoding",
            "Explicit RDF encoding requires an RDF target and a typed encoding.",
        )
    if rdf_edge_encoding is not None and (
        not isinstance(rdf_edge_encoding, RdfEdgeEncoding) or language != "sparql"
    ):
        raise _fail(profile, "rdf_edge_encoding",
                    "Explicit RDF edge encoding requires an RDF target and a typed encoding.")
    required = _required(shape, profile, rdf_edge_encoding)
    text, extra = (
        _cypher(shape, profile)
        if language == "cypher"
        else _sparql(shape, profile, backend_mapping, rdf_encoding, rdf_edge_encoding)
    )
    source = _identity(query)
    source_hash = hashlib.sha256(
        json.dumps(
            source, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return QueryArtifact(
        artifact_id=artifact_id,
        language=language,
        kind="compiled",
        text=text,
        parameters={
            "compiler": PROFILE,
            "target_backend_id": backend_id,
            "result_model": "row_bindings",
            "required_features": list(required),
            "input_pattern_sha256": source_hash,
            "backend_profile_sha256": hashlib.sha256(
                profile.to_json().encode()
            ).hexdigest(),
            "directions": [edge.direction.name for edge in shape.edges],
            "output_columns": [
                "source",
                "target",
                *(f"n{i}" for i in range(shape.edge_count + 1)),
                *(f"e{i}" for i in range(1, shape.edge_count + 1)),
            ],
            "backend_execution_verified": False,
            "semantic_assumptions": [
                "Fixed Rel/Seq descriptor/concatenation semantics; no implicit variable assignments or uniqueness.",
                "Restrictions on fixed paths must be explicit conditions; recursive nodes and non-ALL selectors are rejected.",
                "Positions follow traversal, not stored edge orientation; no legacy M5 lowering is performed.",
                ("RDF edge columns denote stable edge-resource IRIs; source, target and label must be functional on each resource. Cross-backend equality requires explicit identity alignment."
                 if rdf_edge_encoding is not None else
                 "RDF edge columns denote predicate IRIs; no cross-backend edge-identity equality is claimed."),
                "Node properties use dataset-owned scalar encodings; entity IDs are not guessed as RDF IRIs.",
                "Mapped scalar properties must be functional and type-consistent, with finite numeric data.",
                "Cypher numeric type predicates require Neo4j 5.10+; target version needs deployment verification.",
            ],
            **extra,
        },
    )
