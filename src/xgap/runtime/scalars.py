"""Shared typed value identity for binding rows, separate from path predicates."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import math
import re
from typing import Any, Iterable, Mapping

from xgap.backends.rdf_terms import RdfTerm, XSD_STRING


PROFILE = "typed_binding_values_v1"
XSD = "http://www.w3.org/2001/XMLSchema#"
INTEGER_TYPES = frozenset(("integer", "int", "long", "short", "byte", "nonNegativeInteger",
    "positiveInteger", "nonPositiveInteger", "negativeInteger", "unsignedLong", "unsignedInt",
    "unsignedShort", "unsignedByte"))


@dataclass(frozen=True)
class Number:
    kind: str
    value: Decimal


def rdf_term(value: Any) -> RdfTerm | None:
    if isinstance(value, Mapping) and value.get("type") in ("literal", "typed-literal", "uri", "bnode"):
        return RdfTerm.from_binding(value)
    return None


def numeric(value: Any) -> Number | None:
    """Interpret declared numeric values, never numeric-looking strings/bools."""
    if type(value) is int:
        return Number("integer", Decimal(value))
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Binding numeric values must be finite")
        return Number("float", Decimal(str(value)))
    if isinstance(value, Decimal):
        result = Number("decimal", value)
    else:
        term = rdf_term(value)
        if term is None or term.kind != "literal" or not term.datatype.startswith(XSD):
            return None
        datatype = term.datatype[len(XSD):]
        if datatype in INTEGER_TYPES:
            if not re.fullmatch(r"[+-]?[0-9]+", term.value):
                raise ValueError("Invalid RDF integer lexical form")
            number = Decimal(term.value)
            ranges = {"long": (-(2**63), 2**63-1), "int": (-(2**31), 2**31-1),
                "short": (-(2**15), 2**15-1), "byte": (-128, 127),
                "unsignedLong": (0, 2**64-1), "unsignedInt": (0, 2**32-1),
                "unsignedShort": (0, 65535), "unsignedByte": (0, 255),
                "nonNegativeInteger": (0, None), "positiveInteger": (1, None),
                "nonPositiveInteger": (None, 0), "negativeInteger": (None, -1)}
            low, high = ranges.get(datatype, (None, None))
            if (low is not None and number < low) or (high is not None and number > high):
                raise ValueError("RDF integer is outside its declared datatype range")
            result = Number("integer", number)
        elif datatype in ("decimal", "double", "float"):
            pattern = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
            if datatype != "decimal":
                pattern += r"(?:[eE][+-]?[0-9]+)?"
            if not re.fullmatch(pattern, term.value):
                raise ValueError("Invalid or nonfinite RDF numeric lexical form")
            try:
                number = Decimal(term.value)
            except InvalidOperation as error:
                raise ValueError("Invalid RDF numeric lexical form") from error
            result = Number("decimal" if datatype == "decimal" else "float", number)
        else:
            return None
    if not result.value.is_finite() or (result.kind == "float" and not math.isfinite(float(result.value))):
        raise ValueError("Binding numeric values must be finite")
    return result


def decimal_binding(value: Decimal) -> dict[str, str]:
    if not value.is_finite():
        raise ValueError("Binding decimal values must be finite")
    lexical = format(value, "f")
    if "." in lexical:
        lexical = lexical.rstrip("0").rstrip(".")
    if not value:
        lexical = "0"
    return {"type": "literal", "datatype": XSD + "decimal", "value": lexical}


def value_key(value: Any) -> tuple:
    """Hashable, totally ordered identity; RDF term identity remains explicit."""
    if value is None:
        return ("0-null",)
    number = numeric(value)
    if number is not None:
        return ("1-number", number.value)
    if type(value) is str:
        return ("2-string", value)
    if type(value) is bool:
        return ("3-boolean", value)
    term = rdf_term(value)
    if term is not None:
        if term.kind == "literal" and term.datatype == XSD_STRING:
            return ("2-string", term.value)
        if term.kind == "literal" and term.datatype == XSD + "boolean":
            if term.value not in ("true", "false", "1", "0"):
                raise ValueError("Invalid RDF boolean lexical form")
            return ("3-boolean", term.value in ("true", "1"))
        return ("4-rdf", term.kind, term.datatype or "", term.language or "", term.value)
    if isinstance(value, (list, tuple)):
        return ("5-array", tuple(value_key(item) for item in value))
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return ("6-object", tuple((key, value_key(value[key])) for key in sorted(value)))
    raise ValueError("Binding values require JSON scalars, structured payloads or RDF terms")


def scalar_order_key(value: Any) -> tuple:
    key = value_key(value)
    if key[0] in ("5-array", "6-object"):
        raise ValueError("Ordering requires scalar values, not structured payloads")
    return key


def stable_text(value: Any) -> str:
    def encode(item):
        if isinstance(item, Decimal):
            return decimal_binding(item)
        raise TypeError("Non-JSON binding payload")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=encode, allow_nan=False)


def representative_key(value: Any) -> tuple:
    number = numeric(value)
    if number is not None:
        rank = {"integer": 0, "decimal": 1, "float": 2}[number.kind]
    else:
        rank = 0 if type(value) in (str, bool) or value is None else 1
    return rank, stable_text(value)


def row_key(row: Mapping[str, Any]) -> tuple:
    if not all(isinstance(key, str) for key in row):
        raise ValueError("Binding row fields must be strings")
    return tuple((key, value_key(row[key])) for key in sorted(row))


def distinct_rows(rows: Iterable[Mapping[str, Any]], *, preserve_order: bool = False) -> tuple[dict, ...]:
    unique = {}
    for row in rows:
        candidate = dict(row)
        key = row_key(candidate)
        if key not in unique or (not preserve_order and stable_text(candidate) < stable_text(unique[key])):
            unique[key] = candidate
    values = list(unique.values())
    return tuple(values if preserve_order else sorted(values, key=stable_text))
