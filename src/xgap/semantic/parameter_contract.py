"""The finite v2 Interpretation parameter profile, shared with its wire schema.

This validates only the existing nine semantic operators' JSON structure before
grounding. It does not repair fields, resolve holes, lower plans or prove query
meaning/capability. Historical single-program admission remains unchanged.
"""

from copy import deepcopy
import json
import math

from xgap.semantic.program import SemanticProgramError


PARAMETER_CONTRACT = "xgap-semantic-parameters-v1"
_TEXT = {"type": "string", "minLength": 1}
_NULL = {"type": "null"}
_POSITIVE = {"type": "integer", "minimum": 1}
_NONNEGATIVE = {"type": "integer", "minimum": 0}


def _object(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def _array(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": 64}


def _ref(name):
    return {"$ref": "#/$defs/" + name}


def _alternatives(*schemas):
    return {"anyOf": list(schemas)}


def _tagged(tag, value, fields, required=None):
    return _object({tag: {"const": value}, **fields},
                   (tag, *(fields if required is None else required)))


def _dictionary(values, minimum=0):
    return {"type": "object", "additionalProperties": values, "minProperties": minimum}


_DEFS = {
    "hole": _object({"$hole": _TEXT}, ("$hole",)),
    "scalar": _alternatives({"type": "string"}, {"type": "number"}, {"type": "boolean"}, _NULL, _ref("hole")),
    "label": _alternatives(_TEXT, _NULL, _ref("hole")),
    "node": _object({"var": _alternatives(_TEXT, _NULL), "label": _ref("label"),
                     "properties": _dictionary(_ref("scalar"))}),
    "match_node": _object({"label": _ref("label"), "properties": _dictionary(_ref("scalar"))}),
    "edge": _object({"var": _alternatives(_TEXT, _NULL), "label": _ref("label"),
        "direction": {"enum": ["OUT", "IN", "UNDIRECTED"]}, "properties": _dictionary(_ref("scalar"))}),
    "node_ref": _tagged("kind", "node", {"position": _alternatives(_POSITIVE, {"enum": ["first", "last"]})}),
    "edge_ref": _tagged("kind", "edge", {"index": _POSITIVE}),
}
_DEFS["path_ref"] = _alternatives(_ref("node_ref"), _ref("edge_ref"))
_DEFS["regex"] = _alternatives(
    _tagged("kind", "rel", {"edge": _ref("edge")}),
    *(_tagged("kind", kind, {"left": _ref("regex"), "right": _ref("regex")}) for kind in ("seq", "alt")),
    *(_tagged("kind", kind, {"child": _ref("regex")}) for kind in ("plus", "star", "optional")),
    _tagged("kind", "bounded", {"child": _ref("regex"), "min_repeats": _NONNEGATIVE,
        "max_repeats": _alternatives(_NONNEGATIVE, _NULL)}, ("child", "min_repeats")),
)
_DEFS["path_condition"] = _alternatives(
    _tagged("kind", "label_equals", {"ref": _ref("path_ref"), "value": _ref("label")}),
    *(_tagged("kind", kind, {"ref": _ref("path_ref"), "property": _TEXT, "value": _ref("scalar")})
      for kind in ("property_equals", "property_not_equals", "property_lt", "property_lte", "property_gt", "property_gte")),
    _tagged("kind", "node_not_equals", {"left": _ref("node_ref"), "right": _ref("node_ref")}),
    _tagged("kind", "length_equals", {"value": _alternatives(_NONNEGATIVE, _ref("hole"))}),
    *(_tagged("kind", kind, {"conditions": _array(_ref("path_condition"))}) for kind in ("and", "or")),
    _tagged("kind", "not", {"condition": _ref("path_condition")}),
)
_DEFS["row_condition"] = _alternatives(
    *(_tagged("op", op, {"field": _TEXT, "value": _ref("scalar")}) for op in ("eq", "ne", "lt", "le", "gt", "ge")),
    *(_tagged("op", op, {"field": _TEXT}) for op in ("is_null", "is_not_null")),
    *(_tagged("op", op, {"args": _array(_ref("row_condition"), 1)}) for op in ("and", "or")),
    _tagged("op", "not", {"arg": _ref("row_condition")}),
)
_DEFS["path_pattern"] = _object({
    "path_var": _alternatives(_TEXT, _NULL), "source": _ref("node"), "expr": _ref("regex"),
    "target": _ref("node"), "selector": _object({"kind": {"enum": ["ALL", "ANY", "ANY_K",
        "ANY_SHORTEST", "ALL_SHORTEST", "SHORTEST_K", "SHORTEST_K_GROUP"]}, "k": _alternatives(_POSITIVE, _NULL)}),
    "restrictor": {"enum": ["WALK", "TRAIL", "ACYCLIC", "SIMPLE", "SHORTEST"]},
    "condition": _alternatives(_ref("path_condition"), _NULL), "max_depth": _alternatives(_POSITIVE, _NULL),
}, ("source", "expr", "target", "selector"))
_DEFS["projection"] = _alternatives(
    _tagged("kind", "field", {"field": _TEXT}), _tagged("kind", "path_length", {}),
    _tagged("kind", "path_node", {"position": _alternatives(_POSITIVE, {"enum": ["first", "last"]})}),
    _tagged("kind", "path_edge", {"position": _POSITIVE}),
)
_DEFS["aggregation"] = _alternatives(
    _tagged("op", "count", {"field": _alternatives(_TEXT, _NULL), "distinct": {"type": "boolean"}}, ()),
    *(_tagged("op", op, {"field": _TEXT, "distinct": {"type": "boolean"}}, ("field",))
      for op in ("sum", "min", "max")),
)
_PARAMETERS = {
    "match": _object({"node": _ref("match_node"), "entity_field": _TEXT, "properties": _dictionary(_TEXT)}),
    "traverse": _object({"path_pattern": _ref("path_pattern"), "anchor_field": _TEXT,
        "anchor_position": {"enum": ["first", "last"]}}, ("path_pattern",)),
    "project": _object({"projections": _dictionary(_ref("projection"), 1)}, ("projections",)),
    "filter": _object({"condition": _ref("row_condition")}),
    "join": _object({"left_on": _TEXT, "right_on": _TEXT, "right_prefix": {"type": "string"}}, ("left_on", "right_on")),
    "union": _object({}),
    "aggregate": _object({"group_by": {**_array(_TEXT), "uniqueItems": True},
        "aggregations": _dictionary(_ref("aggregation"), 1)}, ("group_by", "aggregations")),
    "order_limit": _object({"order_by": _array(_object({"field": _TEXT,
        "direction": {"enum": ["asc", "desc"]}, "nulls": {"enum": ["first", "last"]}}, ("field",)), 1),
        "limit": _alternatives(_POSITIVE, _ref("hole"))}, ("order_by", "limit")),
    "align": _object({"field": _TEXT, "output_field": _TEXT, "mapping": _dictionary(_ref("scalar")),
        "on_missing": {"enum": ["error", "drop", "keep"]}}, ("field",)),
}


def _constraints(kind):
    if kind not in ("match", "traverse", "filter"):
        return {"type": "array", "maxItems": 0, "items": {"type": "object"}}
    predicate = (_alternatives(_ref("path_condition"), _ref("row_condition")) if kind == "match"
                 else _ref("row_condition" if kind == "filter" else "path_condition"))
    return _array(_object({"constraint_id": _TEXT, "expression": _TEXT,
        "policy": {"enum": ["hard", "relaxable"]}, "predicate": predicate},
        ("constraint_id", "expression", "predicate")))


def typed_operator_schema(base_operator):
    """Return the nine tagged operator alternatives and their shared definitions."""
    alternatives = []
    for kind, parameters in _PARAMETERS.items():
        item = deepcopy(base_operator)
        item["properties"].update(kind={"const": kind}, parameters=deepcopy(parameters), constraints=_constraints(kind))
        alternatives.append(item)
    return {"anyOf": alternatives}, deepcopy(_DEFS)


_KEYWORDS = frozenset({"$ref", "anyOf", "type", "const", "enum", "properties", "required",
    "additionalProperties", "items", "minItems", "maxItems", "minProperties", "minLength",
    "minimum", "uniqueItems"})


def _issues(schema, value, path, *, depth=0):
    """Validate only the finite internal keyword subset above, not arbitrary schemas."""
    if set(schema) - _KEYWORDS:
        raise RuntimeError("Unsupported keyword in the internal parameter contract")
    if depth > 64:
        return [path + ": parameter nesting exceeds the typed profile depth 64"]
    if "$ref" in schema:
        reference = schema["$ref"]
        if set(schema) != {"$ref"} or not reference.startswith("#/$defs/") or reference[8:] not in _DEFS:
            raise RuntimeError("Invalid reference in the internal parameter contract")
        return _issues(_DEFS[reference[8:]], value, path, depth=depth)
    if "anyOf" in schema:
        choices = schema["anyOf"]
        if isinstance(value, dict):
            for discriminator in ("kind", "op"):
                matching = [choice for choice in choices
                    if choice.get("properties", {}).get(discriminator, {}).get("const") == value.get(discriminator)
                    and discriminator in choice.get("properties", {})]
                if matching:
                    choices = matching
                    break
        failures = []
        for choice in choices:
            issues = _issues(choice, value, path, depth=depth)
            if not issues:
                return []
            failures.append(issues)
        return min(failures, key=len)
    errors = []
    expected = schema.get("type")
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "integer": type(value) is int,
        "number": type(value) in (int, float) and math.isfinite(value),
        "boolean": type(value) is bool, "null": value is None}
    if expected is not None and expected not in checks:
        raise RuntimeError("Unsupported internal parameter type")
    if expected is not None and not checks[expected]:
        return [path + ": expected " + expected]
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        errors.append(path + ": unexpected discriminator")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(path + ": value outside supported enum")
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(path + ": number below supported minimum")
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(path + ": empty string")
    if expected == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", ())) - set(value)
        if missing:
            errors.append(path + ": missing fields " + repr(sorted(missing)))
        if len(value) < schema.get("minProperties", 0):
            errors.append(path + ": object must not be empty")
        extra = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if extra and additional is False:
            errors.append(path + ": unknown fields " + repr(sorted(extra)))
        for name, child in value.items():
            rule = properties.get(name, additional)
            if isinstance(rule, dict):
                errors.extend(_issues(rule, child, path + "." + name, depth=depth + 1))
    if expected == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", len(value)):
            errors.append(path + ": array outside supported size")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            errors.append(path + ": duplicate array items")
        if "items" in schema:
            for index, child in enumerate(value):
                errors.extend(_issues(schema["items"], child, path + f"[{index}]", depth=depth + 1))
    return errors


def validate_program_parameters(program):
    """Reject malformed parameter nesting without mutating the supplied program."""
    if not isinstance(program, dict) or not isinstance(program.get("operators"), list):
        raise SemanticProgramError("Typed parameter admission requires a program operator list")
    issues = []
    for index, operator in enumerate(program["operators"]):
        if not isinstance(operator, dict) or operator.get("kind") not in _PARAMETERS:
            issues.append(f"program.operators[{index}]: unsupported operator kind")
            continue
        kind = operator["kind"]
        path = f"program.operators[{index}]({operator.get('operator_id', '?')})"
        issues.extend(_issues(_PARAMETERS[kind], operator.get("parameters", {}), path + ".parameters"))
        issues.extend(_issues(_constraints(kind), operator.get("constraints", []), path + ".constraints"))
    if issues:
        raise SemanticProgramError("; ".join(issues[:12]))
