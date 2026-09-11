"""Independent typed binding fixtures with explicit property source views."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from xgap.backends.rdf_terms import RDF_TERMS_V1, RdfTerm
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.semantic_planning import LogicalSource


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_typed_v1"


def load_typed_fixture():
    return tuple(json.loads((FIXTURE / name).read_text())
                 for name in ("graph.json", "cases.json", "mapping.json"))


def typed_sources():
    views = json.loads((FIXTURE / "sources.json").read_text())
    return {name: LogicalSource(name,
        hashlib.sha256(json.dumps(view["graph"], sort_keys=True).encode()).hexdigest(),
        tuple(view["replicas"])) for name, view in views.items()}


def typed_reference(case, backend):
    return QueryArtifact(case["id"] + "-reference-" + backend,
        "cypher" if backend == "neo4j" else "sparql",
        (FIXTURE / case["reference_target_queries"][backend]).read_text(), kind="native",
        parameters=({"rdf_result_encoding": RDF_TERMS_V1,
            "expected_result_columns": case["reference_columns"]} if backend == "fuseki" else {}))


def typed_reference_rows(result, backend, columns):
    """Fixture-only decoding, independent of runtime normalization/aggregation."""
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
        if datatype in ("float", "double"):
            return float(term.value)
        if datatype == "boolean":
            return term.value in ("true", "1")
        if datatype == "decimal":
            text = format(Decimal(term.value), "f")
            text = text.rstrip("0").rstrip(".") if "." in text else text
            return {"type": "literal", "datatype": term.datatype,
                    "value": "0" if Decimal(term.value) == 0 else text}
        raise ValueError("Independent typed fixture has an undeclared RDF scalar type")

    return [{field: scalar(row.get(field)) for field in columns} for row in result.rows]


def typed_rows_match(case, actual):
    canonical = lambda rows: [json.dumps(row, sort_keys=True, allow_nan=False) for row in rows]
    a, b = canonical(actual), canonical(case["expected_rows"])
    return a == b if case.get("ordered") else sorted(a) == sorted(b)
