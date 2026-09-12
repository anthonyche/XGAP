"""One directed edge plus its scalar attributes, using audited path predicates."""

from dataclasses import replace
import re

from xgap.backends.mapping import RdfBackendMapping
from xgap.backends.rdf_terms import RDF_TERMS_V1, validate_iri
from xgap.compilers.cypher import _cypher_identifier
from xgap.compilers.directed import compile_directed_rows, _identifier_safe
from xgap.compilers.features import default_profile
from xgap.pattern.ast import EdgePattern, NodePattern, Rel, PathPatternQuery, Selector, SelectorKind, PathMode


def compile_edge_match(edge: EdgePattern, properties: dict[str, str], *, backend_id,
        source=None, target=None, backend_mapping=None, rdf_edge_encoding=None,
        profile=None, artifact_id="semantic-edge-match", condition=None):
    reserved = {"entity", "source", "target", "n0", "n1", "e1"}
    if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
           or name in reserved for name in properties):
        raise ValueError("Edge Match property aliases must be identifiers distinct from native identity columns")
    profile = profile or default_profile(backend_id)
    for prop in properties.values():
        _identifier_safe(prop, profile)
    if profile.language.lower() == "sparql" and rdf_edge_encoding is None:
        raise ValueError("Edge Match requires an explicit reified RDF edge encoding")
    query = PathPatternQuery(None, source or NodePattern(), Rel(edge), target or NodePattern(),
        Selector(SelectorKind.ALL), PathMode.WALK, condition=condition)
    base = compile_directed_rows(query, backend_id=backend_id, profile=profile,
        backend_mapping=backend_mapping, rdf_edge_encoding=rdf_edge_encoding,
        artifact_id=artifact_id)
    columns = ["entity", "source", "target", *properties]
    extra = {}
    if base.language == "cypher":
        text = "CALL {\n" + base.text + "\n}\nRETURN DISTINCT e1 AS entity, source, target"
        text += "".join(f", e1.{_cypher_identifier(prop)} AS {alias}" for alias, prop in properties.items())
    else:
        mapping = (backend_mapping if isinstance(backend_mapping, RdfBackendMapping)
                   else RdfBackendMapping.from_artifact(backend_mapping, backend_id=backend_id))
        text = "SELECT DISTINCT " + " ".join("?" + c for c in columns) + " WHERE { {\n" + base.text + "\n}\n"
        text += "BIND(?e1 AS ?entity)\n"
        for alias, prop in properties.items():
            iri = validate_iri(mapping.resolve(prop, "properties").iri)
            text += f"OPTIONAL {{ ?e1 <{iri}> ?{alias} . }}\n"
        text += "}"
        extra = {"rdf_result_encoding": RDF_TERMS_V1, "expected_result_columns": columns}
    return replace(base, text=text, parameters={**base.parameters, **extra,
        "compiler": "semantic_edge_match_v1", "output_columns": columns,
        "branch_edge_counts": [1], "workload_lowering": "edge_match_as_one_edge_path_v1"})
