"""Independent scalar/Boolean fixtures through normal semantic execution."""

import json
from pathlib import Path

from xgap.experiments.toy_semantic import execute_semantic_case, wrap_path_case


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_boolean_v1"


def load_boolean_cases():
    return json.loads((FIXTURE / "queries.json").read_text())


def load_boolean_matches():
    return json.loads((FIXTURE / "match.json").read_text())


def execute_boolean_case(case, mapping, *, client):
    wrapper = wrap_path_case(case, client.backend_id)
    wrapper["expected_remote_calls"] = case["expected_remote_calls"]
    result = execute_semantic_case(wrapper, mapping, clients={client.backend_id: client})
    return {**result, "backend": client.backend_id, "expected_paths": case["expected_paths"],
        "actual_paths": sorted("/".join(row["path"]) for row in result["actual_rows"])
        if result["actual_rows"] is not None else None}


def boolean_match_reference(case, backend):
    from xgap.backends.rdf_terms import RDF_TERMS_V1
    from xgap.infrastructure.runtime import QueryArtifact
    language = "cypher" if backend == "neo4j" else "sparql"
    suffix = ".cypher" if backend == "neo4j" else ".rq"
    return QueryArtifact(case["id"] + "-reference-" + backend, language,
        (FIXTURE / "targets" / (case["id"] + suffix)).read_text(), kind="native",
        parameters=({"rdf_result_encoding": RDF_TERMS_V1,
            "expected_result_columns": ["person", "score", "flag"]} if backend == "fuseki" else {}))


def boolean_match_reference_rows(result, backend):
    """Decode this fixture's explicitly declared types, independent of normalization."""
    from xgap.backends.rdf_terms import RdfTerm
    if not result.success:
        return []
    if backend == "neo4j":
        return list(result.rows)
    def scalar(value):
        if value is None:
            return None
        term = RdfTerm.from_binding(value)
        datatype = term.datatype.rsplit("#", 1)[-1]
        if datatype == "string":
            return term.value
        if datatype == "integer":
            return int(term.value)
        if datatype == "double":
            return float(term.value)
        if datatype == "boolean":
            return term.value in ("true", "1")
        raise ValueError("Independent Boolean fixture has an undeclared RDF scalar type")
    return [{field: scalar(row.get(field)) for field in ("person", "score", "flag")}
            for row in result.rows]
