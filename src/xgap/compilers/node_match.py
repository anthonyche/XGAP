"""Native Match using the same total scalar truth as path traversal."""

from dataclasses import replace
import re

from xgap.backends.mapping import RdfBackendMapping
from xgap.backends.capabilities import SupportLevel
from xgap.backends.compatibility import check_backend_support
from xgap.backends.rdf_terms import RDF_TERMS_V1, validate_iri
from xgap.compilers.cypher import _cypher_identifier
from xgap.compilers.features import BoundCondition, default_profile
from xgap.compilers.directed import DirectedShape, _identifier_safe, _shape, _required, _cypher, _sparql, _fail
from xgap.compilers.boolean_conditions import PROFILE as BOOLEAN_PROFILE
from xgap.compilers.match_identity import identity_projection
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import NodePattern, EdgePattern, Rel, Bounded, PathPatternQuery, Selector, SelectorKind, PathMode
from xgap.pattern.semantic_validation import type_check_semantic_path_pattern


def compile_node_match(node: NodePattern, properties: dict[str, str], *, backend_id: str,
                       backend_mapping=None, rdf_node_classes=(), profile=None,
                       artifact_id="semantic-match", condition=None, identity_property=None) -> QueryArtifact:
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name == "entity"
           for name in properties):
        raise ValueError("Match property aliases must be identifiers distinct from entity")
    profile = profile or default_profile(backend_id)
    for name in (*properties.values(), *node.properties, *((node.label,) if node.label else ())):
        _identifier_safe(name, profile)
    if profile.backend_id != backend_id:
        raise ValueError("Match backend profile does not match placement")
    query = PathPatternQuery(None, node, Bounded(Rel(EdgePattern()), 0, 0), NodePattern(), Selector(SelectorKind.ALL), PathMode.WALK, condition=condition)
    type_check_semantic_path_pattern(query)
    shaped = _shape(replace(query, expr=Rel(EdgePattern())), profile)
    shape = DirectedShape((), tuple(BoundCondition(b.condition, 0, 0, 0) for b in shaped.conditions))
    node_features = ("path_algebra.Nodes",) + (("path_algebra.Selection",) if shape.conditions else ())
    for feature in node_features:
        if check_backend_support(profile, feature).level not in (SupportLevel.SUPPORTED, SupportLevel.CONDITIONAL):
            raise _fail(profile, feature, f"Backend profile does not admit required Match primitive {feature}.")
    required = tuple(sorted((*_required(shape, profile), *node_features)))
    language = profile.language.lower()
    columns = ["entity", *properties]
    if language == "cypher":
        base, extra = _cypher(shape, profile)
        base = "MATCH (n0)\n" + base
        entity = identity_projection('source', identity_property, profile)
        text = "CALL {\n" + base + "\n}\nRETURN DISTINCT " + entity + " AS entity"
        for name, prop in properties.items():
            text += f", source.{_cypher_identifier(prop)} AS {name}"
        extra = ({"native_identity_projection": "property-map-v1", "native_identity_property": identity_property}
                 if identity_property is not None else {})
    elif language == "sparql":
        if not rdf_node_classes:
            raise ValueError("Match requires an explicit RDF node domain")
        mapping = (backend_mapping if isinstance(backend_mapping, RdfBackendMapping)
                   else RdfBackendMapping.from_artifact(backend_mapping, backend_id=backend_id))
        base, extra = _sparql(shape, profile, mapping)
        domain = " ".join(f"<{validate_iri(iri)}>" for iri in rdf_node_classes)
        base = base.replace("WHERE {", f"WHERE {{\n?n0 a ?nodeDomain . VALUES ?nodeDomain {{ {domain} }}", 1)
        text = "SELECT DISTINCT " + " ".join("?" + c for c in columns) + " WHERE { {\n" + base + "\n}\n"
        text += "BIND(?source AS ?entity)\n"
        for name, prop in properties.items():
            iri = validate_iri(mapping.resolve(prop, "properties").iri)
            text += f"OPTIONAL {{ ?source <{iri}> ?{name} . }}\n"
        text += "}"
        extra = {**extra, "rdf_result_encoding": RDF_TERMS_V1, "expected_result_columns": columns}
    else:
        raise ValueError("Match supports Cypher and SPARQL backends")
    return QueryArtifact(artifact_id, language, text, kind="compiled", parameters={
        "required_features": list(required), **extra, "compiler": "semantic_node_match_v1",
        "condition_profile": BOOLEAN_PROFILE,
        "target_backend_id": backend_id, "output_columns": columns,
        "scalar_properties": dict(properties)})
