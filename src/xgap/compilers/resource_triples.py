"""Fixed resource paths over a declared RDF set and its Neo4j mirror.

Compiles complete path rows, never answer-only rows. Term IDs map exactly to
encoding.resource_namespace + ID; arbitrary backend term remapping is not used.
"""

from itertools import combinations

from xgap.algebra.conditions import (
    EdgeRef, LabelEquals, LengthEquals, NodeNotEquals, NodeRef,
    PropertyEquals, PropertyNotEquals,
)
from xgap.algebra.ops import RecursiveMode as PathMode
from xgap.compilers.directed import _fail, _shape, compile_directed_rows
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfResourceTripleEncoding
from xgap.infrastructure.runtime import QueryArtifact
from xgap.pattern.ast import Direction


def compile_resource_triple_paths(query, *, backend_id, encoding, profile=None,
                                 artifact_id="resource-triple-paths"):
    profile = profile or default_profile(backend_id)
    if not isinstance(encoding, RdfResourceTripleEncoding):
        raise ValueError("Resource paths require an explicit triple encoding")
    shape = _shape(query, profile)
    count = shape.edge_count
    if not 1 <= count <= 3:
        raise _fail(profile, "resource_path.bound", "Resource paths require one to three fixed edges")
    if query.max_depth is not None and query.max_depth < count:
        raise _fail(profile, "resource_path.depth", "The fixed path exceeds its declared depth")
    if query.restrictor is PathMode.SIMPLE:
        unequal = {frozenset((b.node_index(c.left), b.node_index(c.right)))
                   for b in shape.conditions if isinstance(c := b.condition, NodeNotEquals)}
        if any(frozenset(pair) not in unequal for pair in combinations(range(count + 1), 2)):
            raise _fail(profile, "resource_path.restrictor", "SIMPLE requires explicit node inequalities")
    elif query.restrictor is not PathMode.WALK:
        raise _fail(profile, "resource_path.restrictor", "Resource paths require WALK or explicitly constrained SIMPLE")

    terms, filters, parameters = {}, [], {}

    def parameter(value):
        key = f"p{len(parameters)}"
        parameters[key] = value
        return "$" + key

    for bound in shape.conditions:
        c = bound.condition
        if isinstance(c, LabelEquals):
            kind = "relation" if isinstance(c.ref, EdgeRef) else "class"
            iri = encoding.rdf.resource_iri(c.value)
            if c.value in terms and terms[c.value]["kind"] != kind:
                raise _fail(profile, "resource_path.term_role", "A canonical term has conflicting roles")
            terms[c.value] = {"kind": kind, "representation": iri}
            if isinstance(c.ref, EdgeRef):
                filters.append(f"e{bound.edge_index(c.ref)+1}.predicate = {parameter(iri)}")
            else:
                n = f"n{bound.node_index(c.ref)}"
                filters.append(f"EXISTS {{ MATCH ({n})-[:XGAP_RDF_RESOURCE_EDGE "
                    f"{{predicate: {parameter(encoding.class_predicate_iri)}}}]->"
                    f"(:XgapRdfResource {{iri: {parameter(iri)}}}) }}")
        elif isinstance(c, NodeNotEquals):
            filters.append(f"n{bound.node_index(c.left)}.iri <> n{bound.node_index(c.right)}.iri")
        elif isinstance(c, LengthEquals):
            filters.append("true" if c.value == count else "false")
        elif type(c) in (PropertyEquals, PropertyNotEquals) and isinstance(c.ref, NodeRef) \
                and c.property_name == encoding.identity_property:
            op = "=" if type(c) is PropertyEquals else "<>"
            node = f"n{bound.node_index(c.ref)}"
            filters.append(f"{node}.iri {op} {parameter(encoding.rdf.resource_iri(c.value))}")
            if type(c) is PropertyNotEquals:
                # Match RDF logical-ID inequality's domain, as in the frozen mirror adapter.
                filters.append(f"{node}.iri STARTS WITH {parameter(encoding.resource_namespace)}")
                filters.append(f"substring({node}.iri, {len(encoding.resource_namespace)}) =~ '[A-Za-z0-9_][A-Za-z0-9_.-]*'")
        else:
            raise _fail(profile, "resource_path.condition", "Resource paths require conjunctive type/identity/node-inequality/length conditions")
    mapped = {"mapping_id": encoding.encoding_id, "version": encoding.identity,
              "backends": {backend_id: {"namespace": encoding.resource_namespace}},
              "term_mappings": {backend_id: terms}}
    language = profile.language.lower()
    # Reuse native type/capability/mapping admission; only replace representation.
    base = compile_directed_rows(query, backend_id=backend_id, profile=profile,
        backend_mapping=mapped if language == "sparql" else None,
        rdf_encoding=encoding.rdf if language == "sparql" else None)
    columns = ["length", *(f"n{i}" for i in range(count + 1)), *(f"e{i}" for i in range(1, count + 1))]
    if language == "sparql":
        uris = " && ".join(f"isIRI(?{c})" for c in columns if c != "length")
        text = "SELECT DISTINCT " + " ".join("?"+c for c in columns) + " WHERE { {\n" + base.text
        text += f"\n}} BIND({count} AS ?length) FILTER({uris}) }} LIMIT {encoding.max_rows+1}"
        parameters = {}
    elif language == "cypher":
        matches = []
        for i, edge in enumerate(shape.edges):
            rel = f"-[e{i+1}:XGAP_RDF_RESOURCE_EDGE]->" if edge.direction is Direction.OUT else f"<-[e{i+1}:XGAP_RDF_RESOURCE_EDGE]-"
            matches.append(f"MATCH (n{i}:XgapRdfResource){rel}(n{i+1}:XgapRdfResource)")
        text = "\n".join(matches) + ("\nWHERE " + " AND ".join(filters) if filters else "")
        values = [f"{count} AS length", *(f"n{i}.iri AS n{i}" for i in range(count+1)),
                  *(f"e{i}.predicate AS e{i}" for i in range(1,count+1))]
        text += "\nRETURN DISTINCT " + ", ".join(values) + f" LIMIT {encoding.max_rows+1}"
    else:
        raise _fail(profile, "resource_path.language", "Resource paths require Cypher or SPARQL")
    selection = {"input_model": "rdf-resource-triples-v1", "language": language,
        "max_edges": count, "resource_namespace": encoding.resource_namespace,
        "identity_property": encoding.identity_property, "max_rows": encoding.max_rows,
        "directions": [edge.direction.name for edge in shape.edges], "selector": "ALL"}
    return QueryArtifact(artifact_id, language, text, kind="compiled", parameters={
        **base.parameters, **parameters, "compiler": "resource_triple_paths_v1",
        "output_columns": columns, "expected_result_columns": columns,
        "result_model": "resource_triple_rows", "path_selection": selection,
        "resource_triple_encoding_sha256": encoding.identity,
        "resource_snapshot_id": encoding.snapshot_id, "branch_count": 1,
        "semantic_assumptions": ["Default RDF graph set of canonical URI resource triples; Neo4j mirror preserves that set",
            "Fixed one-to-three-hop ALL; explicit constraints; triple edge identity is constructed by the shared decoder",
            "LIMIT plus one detects overflow; no truncated success"],
    })
