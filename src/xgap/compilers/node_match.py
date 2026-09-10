"""Native compilation of semantic Match, independent of the path sub-IR."""

import re

from xgap.algebra.ops import NodesOp, SelectionOp
from xgap.backends.mapping import RdfBackendMapping
from xgap.backends.rdf_terms import RDF_TERMS_V1, validate_iri
from xgap.compilers import compile_cypher, compile_sparql
from xgap.compilers.cypher import _cypher_identifier
from xgap.compilers.features import default_profile
from xgap.compilers.directed import _identifier_safe
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import NodePattern
from xgap.pattern.lowering import lower_source_descriptor


def compile_node_match(node: NodePattern, properties: dict[str, str], *, backend_id: str,
                       backend_mapping=None, rdf_node_classes=(), profile=None,
                       artifact_id="semantic-match", condition=None) -> QueryArtifact:
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name == "entity"
           for name in properties):
        raise ValueError("Match property aliases must be identifiers distinct from entity")
    profile = profile or default_profile(backend_id)
    for name in (*properties.values(), *node.properties, *((node.label,) if node.label else ())):
        _identifier_safe(name, profile)
    if profile.backend_id != backend_id:
        raise ValueError("Match backend profile does not match placement")
    plan = lower_source_descriptor(node, NodesOp())
    if condition is not None:
        plan = SelectionOp(condition, plan)
    language = profile.language.lower()
    columns = ["entity", *properties]
    if language == "cypher":
        base = compile_cypher(plan, profile=profile)
        text = "CALL {\n" + base.text + "\n}\nRETURN DISTINCT source AS entity"
        for name, prop in properties.items():
            text += f", source.{_cypher_identifier(prop)} AS {name}"
        extra = {}
    elif language == "sparql":
        if not rdf_node_classes:
            raise ValueError("Match requires an explicit RDF node domain")
        mapping = (backend_mapping if isinstance(backend_mapping, RdfBackendMapping)
                   else RdfBackendMapping.from_artifact(backend_mapping, backend_id=backend_id))
        base = compile_sparql(plan, profile=profile, backend_mapping=mapping)
        domain = " ".join(f"<{validate_iri(iri)}>" for iri in rdf_node_classes)
        text = "SELECT DISTINCT " + " ".join("?" + c for c in columns) + " WHERE { {\n" + base.text + "\n}\n"
        text += f"?source a ?nodeDomain . VALUES ?nodeDomain {{ {domain} }}\nBIND(?source AS ?entity)\n"
        for name, prop in properties.items():
            iri = validate_iri(mapping.resolve(prop, "properties").iri)
            text += f"OPTIONAL {{ ?source <{iri}> ?{name} . }}\n"
        text += "}"
        extra = {"rdf_result_encoding": RDF_TERMS_V1, "expected_result_columns": columns}
    else:
        raise ValueError("Match supports Cypher and SPARQL backends")
    return QueryArtifact(artifact_id, language, text, kind="compiled", parameters={
        **base.parameters, **extra, "compiler": "semantic_node_match_v1",
        "target_backend_id": backend_id, "output_columns": columns})
