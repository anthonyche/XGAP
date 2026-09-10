"""Opt-in, finite resource-IRI VALUES binding for native SPARQL artifacts."""

from __future__ import annotations

import re
from typing import Any, Mapping

from xgap.backends.rdf_terms import validate_iri


IRI_VALUES_MARKER = "{{XGAP_IRI_VALUES}}"


def bind_sparql_iris(text: str, parameters: Mapping[str, Any]) -> str:
    spec = parameters.get("sparql_iri_binding")
    if spec is None:
        return text
    if not isinstance(spec, Mapping) or set(spec) != {
        "parameter", "variable", "max_bindings", "max_bytes"
    }:
        raise ValueError("Invalid SPARQL IRI binding specification")
    for name in ("parameter", "variable"):
        if not isinstance(spec[name], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", spec[name]):
            raise ValueError("Invalid SPARQL IRI binding identifier")
    for name in ("max_bindings", "max_bytes"):
        if type(spec[name]) is not int or spec[name] <= 0:
            raise ValueError("SPARQL binding budgets must be positive integers")
    values = parameters.get(spec["parameter"])
    if not isinstance(values, list) or len(values) > spec["max_bindings"]:
        raise ValueError("Missing or excessive SPARQL IRI bindings")
    if text.count(IRI_VALUES_MARKER) != 1:
        raise ValueError("SPARQL binding requires exactly one VALUES marker")
    # Only resource IRIs are accepted; strings that resemble literal or native
    # query syntax cannot change the declared VALUES column or query structure.
    encoded = " ".join(f"<{value}>" for value in sorted({validate_iri(v) for v in values}))
    clause = f"VALUES ?{spec['variable']} {{ {encoded} }}"
    if len(clause.encode("utf-8")) > spec["max_bytes"]:
        raise ValueError("SPARQL IRI binding byte budget exceeded")
    return text.replace(IRI_VALUES_MARKER, clause)
