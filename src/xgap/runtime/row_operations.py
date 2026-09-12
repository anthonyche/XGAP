"""Small row adapters for executable semantic DAGs; no native text evaluation."""

import json
import math
import re
from datetime import datetime
from numbers import Real
from decimal import Decimal, InvalidOperation

from xgap.backends.rdf_terms import RdfTerm, XSD_STRING
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.runtime.scalars import numeric, value_key, distinct_rows as _typed_distinct


def distinct_rows(rows, *, preserve_order=False):
    return _typed_distinct(rows, preserve_order=preserve_order)


def condition_fields(condition):
    if not isinstance(condition, dict):
        raise ValueError("Row filter requires a structured condition")
    op = condition.get("op")
    if op in ("and", "or"):
        if set(condition) != {"op", "args"} or not isinstance(condition["args"], list) or not condition["args"]:
            raise ValueError("Boolean row filters require a nonempty args list")
        return set().union(*(condition_fields(c) for c in condition["args"]))
    if op == "not":
        if set(condition) != {"op", "arg"}:
            raise ValueError("not requires one arg")
        return condition_fields(condition["arg"])
    unary = op in ("is_null", "is_not_null")
    rhs = "right_field" if "right_field" in condition else "value"
    keys = {"op", "field"} if unary else {"op", "field", rhs}
    if "value_type" in condition:
        if unary or condition["value_type"] != "timestamp_ms":
            raise ValueError("Unsupported row comparison value_type")
        keys.add("value_type")
    if (op not in ("eq", "ne", "lt", "le", "gt", "ge", "is_null", "is_not_null")
            or set(condition) != keys or not isinstance(condition.get("field"), str)):
        raise ValueError("Invalid row comparison")
    if "value" in condition:
        value = condition["value"]
        if value is not None and type(value) not in (str, bool, int, float):
            raise ValueError("Row comparison constants must be scalar")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Row comparison constants must be finite")
    if rhs == "right_field" and (not isinstance(condition[rhs], str) or not condition[rhs]):
        raise ValueError("Row comparison right_field must name a field")
    return {condition["field"], condition[rhs]} if rhs == "right_field" else {condition["field"]}


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}", value):
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
    return value


def _matches(row, c):
    op = c["op"]
    if op == "and":
        return all(_matches(row, a) for a in c["args"])
    if op == "or":
        return any(_matches(row, a) for a in c["args"])
    if op == "not":
        return not _matches(row, c["arg"])
    left = row[c["field"]]
    if op == "is_null":
        return left is None
    if op == "is_not_null":
        return left is not None
    right = row[c["right_field"]] if "right_field" in c else c["value"]
    if left is None or right is None:
        return False
    if c.get("value_type") == "timestamp_ms":
        left, right = _timestamp(left), _timestamp(right)
        if left is None or right is None:
            return False
        return {"eq": left == right, "ne": left != right, "lt": left < right,
                "le": left <= right, "gt": left > right, "ge": left >= right}[op]
    numbers = [_number(x) for x in (left, right)]
    numeric = all(x is not None for x in numbers)
    if numeric:
        left, right = numbers
    if op in ("eq", "ne"):
        equal = value_key(left) == value_key(right)
        return equal if op == "eq" else not equal
    if not numeric:
        return False
    return {"lt": left < right, "le": left <= right, "gt": left > right, "ge": left >= right}[op]


def _number(value):
    number = numeric(value)
    return number.value if number is not None else None


def filter_rows(rows, condition):
    fields = condition_fields(condition)
    if any(not fields <= row.keys() for row in rows):
        raise ValueError("Row filter references a missing field")
    return tuple(dict(row) for row in rows if _matches(row, condition))


def project_rows(rows, projections, *, namespace=None):
    output = []
    encoding = RdfRowEncoding("semantic-path-identity", "urn:xgap:class", "id", namespace) if namespace else None
    for row in rows:
        projected = {}
        for name, spec in projections.items():
            kind = spec["kind"]
            if kind == "field":
                value = row[spec["field"]]
            elif kind == "literal":
                value = spec["value"]
            elif kind == "path_length":
                value = (len(row["path"]) - 1) // 2
            elif kind in ("path_node", "path_edge"):
                path = row["path"]
                position = spec["position"]
                if kind == "path_node":
                    index = 0 if position == "first" else len(path) - 1 if position == "last" else 2 * (position - 1)
                else:
                    index = 2 * position - 1
                if index < 0 or index >= len(path) or encoding is None:
                    raise ValueError("Path projection has no position or identity encoding")
                value = encoding.resource_iri(path[index])
            else:
                raise ValueError("Unsupported semantic row projection")
            projected[name] = value
        output.append(projected)
    return distinct_rows(output, preserve_order=True)


def _rdf_scalar(value):
    if value is None:
        return None
    term = RdfTerm.from_binding(value)
    if term.kind != "literal":
        return term.to_binding()
    local = term.datatype.removeprefix("http://www.w3.org/2001/XMLSchema#")
    if term.datatype == XSD_STRING:
        return term.value
    number = numeric(value)  # Validate the declared datatype before erasing its tag.
    if number is not None and number.kind == "integer":
        return int(number.value)
    if number is not None and number.kind == "float":
        return float(number.value)
    if local == "boolean":
        if term.value not in ("true", "false", "1", "0"):
            raise ValueError("Invalid RDF boolean")
        return term.value in ("true", "1")
    return term.to_binding()  # Keep language/date/other RDF types, never erase the tag.


def normalize_node_bindings(rows, parameters):
    ids = RdfRowEncoding("semantic-node-identity", "urn:xgap:class",
                         parameters["identity_property"], parameters["resource_namespace"])
    result = []
    identities = parameters.get("identity_fields", {"entity": parameters["entity_field"]})
    for row in rows:
        normalized = {}
        if parameters["language"] == "sparql":
            for source, target in identities.items():
                term = RdfTerm.from_binding(row[source])
                if term.kind != "uri":
                    raise ValueError("Matched nodes/edges require global resource identity")
                normalized[target] = term.value
            values = {field: _rdf_scalar(row.get(field)) for field in parameters["scalar_fields"]}
        else:
            normalized = {target: ids.resource_iri(row[source][ids.identity_property])
                          for source, target in identities.items()}
            values = {field: row.get(field) for field in parameters["scalar_fields"]}
        result.append({**normalized, **values})
    return distinct_rows(result)
