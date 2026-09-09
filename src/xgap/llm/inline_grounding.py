"""Materialize explicit inline slot choices; never infer missing semantics.

The model keeps its original path tree, labels, directions and conditions.
Only structural component references and the list of entity IDs already used
in that tree are generated. Anchors and slot choices remain model inputs.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


INLINE_GROUNDING_V1 = "inline_grounding_v1"
SCHEMA_CONTRACT_KEY = "x-xgap-response-contract"


def validate_response_contract(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    item = _object(value, "response_contract", {"kind", "entity_identity_property"})
    if item.get("kind") != INLINE_GROUNDING_V1:
        raise ValueError("Unknown response materialization contract.")
    identity = _string(item.get("entity_identity_property"), "entity_identity_property")
    return {"kind": INLINE_GROUNDING_V1, "entity_identity_property": identity}


def materialize_inline_response(
    raw: Mapping[str, Any], *, entity_identity_property: str
) -> dict[str, Any]:
    """Expand one closed, explicitly selected wire format without changing raw.

    A label_slot annotates that node/edge label. property_slots maps existing
    property keys to slots; condition_slot selects the single property common
    to a condition tree. Missing or ambiguous choices are never filled in.
    The ordinary parser, grounding and typed validation still run afterwards.
    """
    _string(entity_identity_property, "entity_identity_property")
    root = _object(
        raw, "response", {"provider_id", "model", "query_slots", "candidates"}
    )
    result = json.loads(json.dumps(root, allow_nan=False))
    if not isinstance(result.get("candidates"), list):
        raise ValueError("Inline response requires a candidates array.")
    for index, candidate in enumerate(result["candidates"]):
        _materialize_candidate(candidate, entity_identity_property, index)
    return result


def _materialize_candidate(
    candidate: object, identity_property: str, index: int
) -> None:
    item = _object(
        candidate,
        f"candidate[{index}]",
        {"candidate_id", "confidence", "rationale", "pattern_query"},
    )
    pattern = _object(
        item.get("pattern_query"),
        "pattern_query",
        {
            "path_var",
            "source",
            "expr",
            "target",
            "selector",
            "restrictor",
            "condition",
            "condition_slot",
            "max_depth",
        },
    )
    realizations: list[dict[str, Any]] = []
    entity_ids: dict[str, Any] = {}

    def assign(slot: object, term: object, component: str) -> None:
        if slot is None:
            return
        slot_id = _string(slot, "slot_id")
        # Preserve missing terms and duplicate semantic choices for the existing
        # per-candidate grounder. One bad sibling must not discard a good one.
        realizations.append(
            {
                "slot_id": slot_id,
                "ontology_term_id": term,
                "component_ref": component,
            }
        )

    def entity(name: str, value: object) -> None:
        if name == identity_property:
            entity_ids[json.dumps(value, sort_keys=True, allow_nan=False)] = value

    def component(value: object, path: str, *, edge: bool = False) -> None:
        fields = {"var", "label", "properties", "label_slot", "property_slots"}
        if edge:
            fields.add("direction")
        node = _object(value, path, fields)
        assign(node.pop("label_slot", None), node.get("label"), path)
        props = node.get("properties", {})
        if not isinstance(props, dict) or any(
            not isinstance(key, str) or not key for key in props
        ):
            raise ValueError(
                f"{path}.properties must map nonempty property IDs to values."
            )
        slots = node.pop("property_slots", {})
        if not isinstance(slots, dict) or any(
            not isinstance(key, str) or not key for key in slots
        ):
            raise ValueError(f"{path}.property_slots must map property IDs to slots.")
        for name, value in props.items():
            entity(name, value)
        for name, slot in slots.items():
            assign(slot, name, f"{path}.properties.{name}")

    def regex(value: object, path: str, depth: int = 0) -> None:
        if depth > 64:
            raise ValueError("Inline expression nesting exceeds 64 levels.")
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an expression object.")
        kind = value.get("kind")
        if kind == "rel":
            _object(value, path, {"kind", "edge"})
            component(value.get("edge"), path + ".edge", edge=True)
        elif kind in ("seq", "alt"):
            _object(value, path, {"kind", "left", "right"})
            regex(value.get("left"), path + ".left", depth + 1)
            regex(value.get("right"), path + ".right", depth + 1)
        elif kind in ("plus", "star", "optional", "bounded"):
            fields = {"kind", "child"}
            if kind == "bounded":
                fields |= {"min_repeats", "max_repeats"}
            _object(value, path, fields)
            regex(value.get("child"), path + ".child", depth + 1)
        else:
            raise ValueError(f"Unknown inline expression kind at {path}.")

    condition_properties: set[str] = set()

    def condition(value: object, depth: int = 0) -> None:
        if depth > 64:
            raise ValueError("Inline condition nesting exceeds 64 levels.")
        if value is None:
            return
        if not isinstance(value, dict):
            raise ValueError("Inline condition must be an object or null.")
        kind = value.get("kind")
        if kind in ("and", "or"):
            _object(value, "condition", {"kind", "conditions"})
            children = value.get("conditions")
            if not isinstance(children, list):
                raise ValueError("Boolean condition requires a conditions array.")
            for child in children:
                condition(child, depth + 1)
        elif kind == "not":
            _object(value, "condition", {"kind", "condition"})
            condition(value.get("condition"), depth + 1)
        elif kind in (
            "property_equals",
            "property_not_equals",
            "property_lt",
            "property_lte",
            "property_gt",
            "property_gte",
        ):
            _object(value, "condition", {"kind", "ref", "property", "value"})
            name = _string(value.get("property"), "condition property")
            condition_properties.add(name)
            entity(name, value.get("value"))
        elif kind == "label_equals":
            _object(value, "condition", {"kind", "ref", "value"})
        elif kind == "length_equals":
            _object(value, "condition", {"kind", "value"})
        else:
            raise ValueError("Unknown or generated canonical inline condition.")

    component(pattern.get("source"), "source")
    regex(pattern.get("expr"), "expr")
    component(pattern.get("target"), "target")
    condition(pattern.get("condition"))
    condition_slot = pattern.pop("condition_slot", None)
    if condition_slot is not None:
        # No arbitrary property is chosen for an ambiguous condition. A null
        # declaration cannot pass canonical grounding against the actual tree.
        term = (
            next(iter(condition_properties)) if len(condition_properties) == 1 else None
        )
        assign(condition_slot, term, "condition")
    item["grounding"] = {
        "slot_realizations": realizations,
        "entity_ids": [entity_ids[key] for key in sorted(entity_ids)],
    }


def _object(value: object, name: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError(f"{name} must be an object containing only {sorted(fields)}.")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string.")
    return value
