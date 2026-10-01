"""Controlled JSON parser for M10 planner candidates."""

from __future__ import annotations

from typing import Any, Mapping

from xgap.algebra.conditions import (
    And,
    Condition,
    EdgeRef,
    LabelEquals,
    LengthEquals,
    NodeNotEquals,
    NodeRef,
    Not,
    Or,
    PropertyEquals,
    PropertyGreaterThan,
    PropertyGreaterThanOrEqual,
    PropertyLessThan,
    PropertyLessThanOrEqual,
    PropertyNotEquals,
)
from xgap.algebra.ops import RecursiveMode
from xgap.llm.schemas import PlannerCandidate, PlannerRequest, PlannerResponse
from xgap.pattern.ast import (
    Alt,
    Bounded,
    Direction,
    EdgePattern,
    NodePattern,
    OptionalExpr,
    PathPatternQuery,
    Rel,
    RegexExpr,
    Selector,
    SelectorKind,
    Seq,
    Star,
    Plus,
    Var,
)


class PlannerSchemaError(ValueError):
    """Raised when controlled planner JSON is malformed."""


def parse_planner_response(data: Mapping[str, Any], request: PlannerRequest) -> PlannerResponse:
    candidates_data = data.get("candidates")
    if not isinstance(candidates_data, list):
        raise PlannerSchemaError("Planner response must contain a candidates list.")
    candidates = tuple(
        _parse_candidate(item, request, index)
        for index, item in enumerate(candidates_data, start=1)
    )
    if len(candidates) > request.max_candidates:
        raise PlannerSchemaError(
            f"Planner response returned {len(candidates)} candidates, "
            f"but max_candidates is {request.max_candidates}."
        )
    return PlannerResponse(
        request=request,
        candidates=candidates,
        provider_id=str(data.get("provider_id", "unknown")),
        model=str(data["model"]) if data.get("model") is not None else None,
        raw=dict(data),
    )


def parse_path_pattern_query(data: Mapping[str, Any]) -> PathPatternQuery:
    return PathPatternQuery(
        path_var=_optional_var(data.get("path_var")),
        source=_parse_node_pattern(_mapping(data.get("source"), "source")),
        expr=_parse_regex(_mapping(data.get("expr"), "expr")),
        target=_parse_node_pattern(_mapping(data.get("target"), "target")),
        selector=_parse_selector(_mapping(data.get("selector"), "selector")),
        restrictor=_parse_restrictor(data.get("restrictor", "TRAIL")),
        condition=_parse_optional_condition(data.get("condition")),
        max_depth=_optional_positive_int(data.get("max_depth"), "max_depth"),
    )


def path_pattern_query_to_dict(query: PathPatternQuery) -> dict[str, Any]:
    return {
        "path_var": query.path_var.name if query.path_var is not None else None,
        "source": _node_pattern_to_dict(query.source),
        "expr": _regex_to_dict(query.expr),
        "target": _node_pattern_to_dict(query.target),
        "selector": {
            "kind": query.selector.kind.name,
            "k": query.selector.k,
        },
        "restrictor": query.restrictor.name,
        "condition": _condition_to_dict(query.condition),
        "max_depth": query.max_depth,
    }


def _parse_candidate(
    data: object,
    request: PlannerRequest,
    index: int,
) -> PlannerCandidate:
    item = _mapping(data, f"candidate[{index}]")
    forbidden_native_fields = {"native_query", "cypher", "sparql", "gql", "query_text"}
    present = forbidden_native_fields.intersection(item)
    if present:
        raise PlannerSchemaError(
            "Planner candidates must contain controlled PathPatternQuery JSON only; "
            f"native query field(s) are forbidden: {sorted(present)}."
        )
    pattern_query = parse_path_pattern_query(_mapping(item.get("pattern_query"), "pattern_query"))
    confidence = item.get("confidence")
    return PlannerCandidate(
        question=request.question,
        candidate_id=str(item.get("candidate_id", f"candidate-{index}")),
        pattern_query=pattern_query,
        confidence=float(confidence) if confidence is not None else None,
        rationale=str(item["rationale"]) if item.get("rationale") is not None else None,
        raw=dict(item),
        metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata"), Mapping) else {},
    )


def _parse_node_pattern(data: Mapping[str, Any]) -> NodePattern:
    return NodePattern(
        var=_optional_var(data.get("var")),
        label=_optional_string(data.get("label"), "node label"),
        properties=_properties(data.get("properties")),
    )


def _parse_edge_pattern(data: Mapping[str, Any]) -> EdgePattern:
    return EdgePattern(
        var=_optional_var(data.get("var")),
        label=_optional_string(data.get("label"), "edge label"),
        direction=_parse_direction(data.get("direction", "OUT")),
        properties=_properties(data.get("properties")),
    )


def _parse_regex(data: Mapping[str, Any]) -> RegexExpr:
    kind = _kind(data)
    if kind == "rel":
        return Rel(_parse_edge_pattern(_mapping(data.get("edge"), "edge")))
    if kind == "seq":
        return Seq(
            _parse_regex(_mapping(data.get("left"), "left")),
            _parse_regex(_mapping(data.get("right"), "right")),
        )
    if kind == "alt":
        return Alt(
            _parse_regex(_mapping(data.get("left"), "left")),
            _parse_regex(_mapping(data.get("right"), "right")),
        )
    if kind == "plus":
        return Plus(_parse_regex(_mapping(data.get("child"), "child")))
    if kind == "star":
        return Star(_parse_regex(_mapping(data.get("child"), "child")))
    if kind == "optional":
        return OptionalExpr(_parse_regex(_mapping(data.get("child"), "child")))
    if kind == "bounded":
        return Bounded(
            _parse_regex(_mapping(data.get("child"), "child")),
            min_repeats=_positive_or_zero_int(data.get("min_repeats"), "min_repeats"),
            max_repeats=(_positive_or_zero_int(data["max_repeats"], "max_repeats")
                         if data.get("max_repeats") is not None else None),
        )
    raise PlannerSchemaError(f"Unsupported regex kind {kind!r}.")


def _parse_selector(data: Mapping[str, Any]) -> Selector:
    kind_name = str(data.get("kind", "ALL")).upper()
    try:
        kind = SelectorKind[kind_name]
    except KeyError as error:
        raise PlannerSchemaError(f"Unsupported selector kind {kind_name!r}.") from error
    k = _optional_positive_int(data.get("k"), "selector.k")
    return Selector(kind, k)


def _parse_restrictor(value: object) -> RecursiveMode:
    name = str(value).upper()
    try:
        return RecursiveMode[name]
    except KeyError as error:
        raise PlannerSchemaError(f"Unsupported restrictor {name!r}.") from error


def _parse_direction(value: object) -> Direction:
    name = str(value).upper()
    try:
        return Direction[name]
    except KeyError as error:
        raise PlannerSchemaError(f"Unsupported edge direction {name!r}.") from error


def _parse_optional_condition(value: object) -> Condition | None:
    if value is None:
        return None
    return _parse_condition(_mapping(value, "condition"))


def _parse_condition(data: Mapping[str, Any]) -> Condition:
    kind = _kind(data)
    if kind == "label_equals":
        return LabelEquals(_parse_ref(_mapping(data.get("ref"), "ref")), data.get("value"))
    if kind == "property_equals":
        return PropertyEquals(
            _parse_ref(_mapping(data.get("ref"), "ref")),
            _required_string(data.get("property"), "property"),
            data.get("value"),
        )
    if kind == "property_not_equals":
        return PropertyNotEquals(
            _parse_ref(_mapping(data.get("ref"), "ref")),
            _required_string(data.get("property"), "property"),
            data.get("value"),
        )
    if kind == "node_not_equals":
        left = _parse_ref(_mapping(data.get("left"), "left"))
        right = _parse_ref(_mapping(data.get("right"), "right"))
        if not isinstance(left, NodeRef) or not isinstance(right, NodeRef):
            raise PlannerSchemaError("node_not_equals requires two node references.")
        return NodeNotEquals(left, right)
    if kind == "property_lt":
        return PropertyLessThan(_parse_ref(_mapping(data.get("ref"), "ref")), _required_string(data.get("property"), "property"), data.get("value"))
    if kind == "property_lte":
        return PropertyLessThanOrEqual(_parse_ref(_mapping(data.get("ref"), "ref")), _required_string(data.get("property"), "property"), data.get("value"))
    if kind == "property_gt":
        return PropertyGreaterThan(_parse_ref(_mapping(data.get("ref"), "ref")), _required_string(data.get("property"), "property"), data.get("value"))
    if kind == "property_gte":
        return PropertyGreaterThanOrEqual(_parse_ref(_mapping(data.get("ref"), "ref")), _required_string(data.get("property"), "property"), data.get("value"))
    if kind == "length_equals":
        return LengthEquals(_positive_or_zero_int(data.get("value"), "length value"))
    if kind == "and":
        return And(*_condition_list(data.get("conditions"), "and.conditions"))
    if kind == "or":
        return Or(*_condition_list(data.get("conditions"), "or.conditions"))
    if kind == "not":
        return Not(_parse_condition(_mapping(data.get("condition"), "not.condition")))
    raise PlannerSchemaError(f"Unsupported condition kind {kind!r}.")


def _parse_ref(data: Mapping[str, Any]) -> NodeRef | EdgeRef:
    kind = str(data.get("kind", "")).lower()
    if kind == "node":
        position = data.get("position")
        if position in ("first", "last"):
            return NodeRef(position)
        return NodeRef(_positive_int(position, "node position"))
    if kind == "edge":
        return EdgeRef(_positive_int(data.get("index"), "edge index"))
    raise PlannerSchemaError(f"Unsupported reference kind {kind!r}.")


def _condition_list(value: object, field_name: str) -> tuple[Condition, ...]:
    if not isinstance(value, list):
        raise PlannerSchemaError(f"{field_name} must be a list.")
    return tuple(_parse_condition(_mapping(item, field_name)) for item in value)


def _node_pattern_to_dict(pattern: NodePattern) -> dict[str, Any]:
    return {
        "var": pattern.var.name if pattern.var is not None else None,
        "label": pattern.label,
        "properties": dict(pattern.properties),
    }


def _edge_pattern_to_dict(pattern: EdgePattern) -> dict[str, Any]:
    return {
        "var": pattern.var.name if pattern.var is not None else None,
        "label": pattern.label,
        "direction": pattern.direction.name,
        "properties": dict(pattern.properties),
    }


def _regex_to_dict(regex: RegexExpr) -> dict[str, Any]:
    if isinstance(regex, Rel):
        return {"kind": "rel", "edge": _edge_pattern_to_dict(regex.edge)}
    if isinstance(regex, Seq):
        return {"kind": "seq", "left": _regex_to_dict(regex.left), "right": _regex_to_dict(regex.right)}
    if isinstance(regex, Alt):
        return {"kind": "alt", "left": _regex_to_dict(regex.left), "right": _regex_to_dict(regex.right)}
    if isinstance(regex, Plus):
        return {"kind": "plus", "child": _regex_to_dict(regex.child)}
    if isinstance(regex, Star):
        return {"kind": "star", "child": _regex_to_dict(regex.child)}
    if isinstance(regex, OptionalExpr):
        return {"kind": "optional", "child": _regex_to_dict(regex.child)}
    if isinstance(regex, Bounded):
        return {
            "kind": "bounded",
            "child": _regex_to_dict(regex.child),
            "min_repeats": regex.min_repeats,
            "max_repeats": regex.max_repeats,
        }
    raise PlannerSchemaError(f"Cannot serialize regex {type(regex).__name__}.")


def _condition_to_dict(condition: Condition | None) -> dict[str, Any] | None:
    if condition is None:
        return None
    if isinstance(condition, LabelEquals):
        return {"kind": "label_equals", "ref": _ref_to_dict(condition.ref), "value": condition.value}
    if isinstance(condition, PropertyEquals):
        return {"kind": "property_equals", "ref": _ref_to_dict(condition.ref), "property": condition.property_name, "value": condition.value}
    if isinstance(condition, PropertyNotEquals):
        return {"kind": "property_not_equals", "ref": _ref_to_dict(condition.ref), "property": condition.property_name, "value": condition.value}
    if isinstance(condition, NodeNotEquals):
        return {
            "kind": "node_not_equals",
            "left": _ref_to_dict(condition.left),
            "right": _ref_to_dict(condition.right),
        }
    if isinstance(condition, PropertyLessThan):
        return {"kind": "property_lt", "ref": _ref_to_dict(condition.ref), "property": condition.property_name, "value": condition.value}
    if isinstance(condition, PropertyLessThanOrEqual):
        return {"kind": "property_lte", "ref": _ref_to_dict(condition.ref), "property": condition.property_name, "value": condition.value}
    if isinstance(condition, PropertyGreaterThan):
        return {"kind": "property_gt", "ref": _ref_to_dict(condition.ref), "property": condition.property_name, "value": condition.value}
    if isinstance(condition, PropertyGreaterThanOrEqual):
        return {"kind": "property_gte", "ref": _ref_to_dict(condition.ref), "property": condition.property_name, "value": condition.value}
    if isinstance(condition, LengthEquals):
        return {"kind": "length_equals", "value": condition.value}
    if isinstance(condition, And):
        return {"kind": "and", "conditions": [_condition_to_dict(child) for child in condition.conditions]}
    if isinstance(condition, Or):
        return {"kind": "or", "conditions": [_condition_to_dict(child) for child in condition.conditions]}
    if isinstance(condition, Not):
        return {"kind": "not", "condition": _condition_to_dict(condition.condition)}
    raise PlannerSchemaError(f"Cannot serialize condition {type(condition).__name__}.")


def _ref_to_dict(ref: NodeRef | EdgeRef) -> dict[str, Any]:
    if isinstance(ref, NodeRef):
        return {"kind": "node", "position": ref.position}
    return {"kind": "edge", "index": ref.index}


def _kind(data: Mapping[str, Any]) -> str:
    return str(data.get("kind", "")).strip().lower()


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlannerSchemaError(f"{field_name} must be a mapping.")
    return value


def _properties(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PlannerSchemaError("properties must be a mapping.")
    return dict(value)


def _optional_var(value: object) -> Var | None:
    if value is None:
        return None
    return Var(_required_string(value, "var"))


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PlannerSchemaError(f"{field_name} must be a non-empty string.")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field_name)


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PlannerSchemaError(f"{field_name} must be a positive integer.")
    return value


def _positive_or_zero_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PlannerSchemaError(f"{field_name} must be a non-negative integer.")
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)
