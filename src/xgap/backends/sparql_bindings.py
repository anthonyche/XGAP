"""Opt-in, finite resource-IRI VALUES binding for native SPARQL artifacts."""

from __future__ import annotations

import re
from typing import Any, Mapping

from xgap.backends.rdf_terms import validate_iri


IRI_VALUES_MARKER = "{{XGAP_IRI_VALUES}}"
IRI_ROWS_MARKER = "{{XGAP_IRI_ROWS}}"
IRI_SINGLETON_MARKER = "{{XGAP_IRI_SINGLETON}}"


def bind_sparql_iris(text: str, parameters: Mapping[str, Any]) -> str:
    if "sparql_iri_rows" in parameters:
        if "sparql_iri_binding" in parameters:
            raise ValueError("Conflicting SPARQL binding profiles")
        return _bind_iri_rows(text, parameters)
    spec = parameters.get("sparql_iri_binding")
    if spec is None:
        return text
    if not isinstance(spec, Mapping) or set(spec)-{'singleton_anchor','per_key_limit','projection','inline_singleton'} != {
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
    if 'per_key_limit' in spec or 'projection' in spec:
        if (type(spec.get('per_key_limit')) is not int or spec['per_key_limit']!=1
                or spec.get('projection')!=['entity','source','target']):
            raise ValueError('Unknown representative leaf binding profile')
        single={k:v for k,v in spec.items() if k not in ('per_key_limit','projection')}
        branches=[];expanded_bytes=0
        for value in sorted({validate_iri(v) for v in values}):
            bound=bind_sparql_iris(text,{**parameters,'sparql_iri_binding':single,spec['parameter']:[value]})
            branches.append('{\n'+bound+'\nLIMIT 1\n}')
            expanded_bytes+=len(branches[-1].encode('utf-8'))
            if expanded_bytes>spec['max_bytes']:
                raise ValueError('SPARQL representative request byte budget exceeded')
        # SPARQL's flat UNION syntax builds a left-deep algebra tree. Hundreds
        # of per-key subqueries can exhaust ARQ's optimizer heap before any
        # source work. UNION is associative (including bag multiplicities);
        # explicitly balanced groups retain every independently sliced branch
        # and keep generated union depth logarithmic in the key count.
        while len(branches)>1:
            branches=[('{ '+branches[i]+' UNION '+branches[i+1]+' }'
                       if i+1<len(branches) else branches[i])
                      for i in range(0,len(branches),2)]
        body=branches[0] if branches else 'FILTER(false)'
        result='SELECT DISTINCT ?entity ?source ?target WHERE {\n'+body+'\n}'
        if len(result.encode('utf-8'))>spec['max_bytes']:
            raise ValueError('SPARQL representative request byte budget exceeded')
        return result
    # Only resource IRIs are accepted; strings that resemble literal or native
    # query syntax cannot change the declared VALUES column or query structure.
    encoded = " ".join(f"<{value}>" for value in sorted({validate_iri(v) for v in values}))
    clause = f"VALUES ?{spec['variable']} {{ {encoded} }}"
    if 'inline_singleton' in spec:
        if spec['inline_singleton'] is not True or len(set(values))!=1 or IRI_SINGLETON_MARKER not in text:
            raise ValueError('Inline endpoint binding requires one resource and a compiler marker')
        # Only compiler-emitted term positions carry this marker. Keep VALUES
        # for the projected boundary column; make the BGP's endpoint constant
        # independently of source-engine propagation through a table join.
        text=text.replace(IRI_SINGLETON_MARKER,encoded)
    if 'singleton_anchor' in spec:
        anchor=spec['singleton_anchor']
        if (not isinstance(anchor,Mapping) or set(anchor)!={'subject','predicate'}
                or not isinstance(anchor['subject'],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',anchor['subject'])):
            raise ValueError('Invalid singleton endpoint anchor')
        predicate=validate_iri(anchor['predicate'])
        if len(set(values))==1:
            # Compiler-owned redundant consequence of the original endpoint
            # triple plus VALUES. No path parsing, truncation or new semantics.
            clause+=f"\n?{anchor['subject']} <{predicate}> {encoded} ."
    if len(clause.encode("utf-8")) > spec["max_bytes"]:
        raise ValueError("SPARQL IRI binding byte budget exceeded")
    return text.replace(IRI_VALUES_MARKER, clause)


def _bind_iri_rows(text: str, parameters: Mapping[str, Any]) -> str:
    spec = parameters["sparql_iri_rows"]
    if not isinstance(spec, Mapping) or set(spec) != {"parameter", "columns", "max_bindings", "max_bytes"}:
        raise ValueError("Invalid SPARQL correlated IRI row specification")
    names = spec["columns"]
    if (not isinstance(names, list) or not names
            or any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n) for n in names)
            or len(set(names)) != len(names)
            or not isinstance(spec["parameter"], str) or not spec["parameter"]):
        raise ValueError("Invalid SPARQL correlated binding columns")
    for key in ("max_bindings", "max_bytes"):
        if type(spec[key]) is not int or spec[key] <= 0:
            raise ValueError("Correlated SPARQL binding budgets must be positive integers")
    rows = parameters.get(spec["parameter"])
    if not isinstance(rows, list) or len(rows) > spec["max_bindings"]:
        raise ValueError("Missing or excessive correlated SPARQL bindings")
    if text.count(IRI_ROWS_MARKER) != 1:
        raise ValueError("Correlated SPARQL binding requires one row marker")
    encoded: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != set(names):
            raise ValueError("Correlated SPARQL row columns disagree")
        encoded.add("(" + " ".join(f"<{validate_iri(row[n])}>" for n in names) + ")")
    clause = "VALUES (" + " ".join("?"+n for n in names) + ") { " + " ".join(sorted(encoded)) + " }"
    if len(clause.encode("utf-8")) > spec["max_bytes"]:
        raise ValueError("Correlated SPARQL binding byte budget exceeded")
    return text.replace(IRI_ROWS_MARKER, clause)
