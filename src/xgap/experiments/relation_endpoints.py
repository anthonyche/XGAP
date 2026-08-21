"""Deterministic relation-endpoint type evidence for bounded path grounding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from xgap.pattern.ast import Direction


RELATION_ENDPOINT_CONTRACT_VERSION = "m13e3b4-relation-endpoint-grounding-v1"


class EndpointRole(str, Enum):
    SOURCE = "source"
    TARGET = "target"


@dataclass(frozen=True)
class RelationEndpointSelection:
    """One selected, ordered relation hop and its prompt-visible metadata."""

    slot_id: str
    component_ref: str
    relation_id: str
    direction: Direction
    domain: str | None
    range: str | None

    def __post_init__(self) -> None:
        if not self.slot_id or not self.component_ref or not self.relation_id:
            raise ValueError("Relation endpoint selections require IDs and a component ref.")
        if not isinstance(self.direction, Direction):
            raise TypeError("Relation endpoint direction must be a Direction value.")


@dataclass(frozen=True)
class RelationEndpointTypeEvidence:
    role: EndpointRole
    type_id: str
    relation_slot_id: str
    relation_component_ref: str
    relation_id: str
    direction: Direction
    provenance: str = RELATION_ENDPOINT_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "type_id": self.type_id,
            "relation_slot_id": self.relation_slot_id,
            "relation_component_ref": self.relation_component_ref,
            "relation_id": self.relation_id,
            "direction": self.direction.name,
            "provenance": self.provenance,
        }


def derive_relation_endpoint_types(
    selections: Sequence[RelationEndpointSelection],
) -> tuple[RelationEndpointTypeEvidence, ...]:
    """Derive exact outer endpoint types for one ordered linear path.

    No hierarchy expansion or lexical matching occurs here. Callers are responsible
    for proving that every selection is prompt-visible and corresponds to the path
    component named by ``component_ref``.
    """

    ordered = tuple(selections)
    if not ordered:
        return ()
    evidence: list[RelationEndpointTypeEvidence] = []
    for role, selection in (
        (EndpointRole.SOURCE, ordered[0]),
        (EndpointRole.TARGET, ordered[-1]),
    ):
        for type_id in _role_type_ids(selection, role):
            evidence.append(
                RelationEndpointTypeEvidence(
                    role=role,
                    type_id=type_id,
                    relation_slot_id=selection.slot_id,
                    relation_component_ref=selection.component_ref,
                    relation_id=selection.relation_id,
                    direction=selection.direction,
                )
            )
    return tuple(evidence)


def _role_type_ids(
    selection: RelationEndpointSelection, role: EndpointRole
) -> tuple[str, ...]:
    if selection.direction is Direction.OUT:
        value = selection.domain if role is EndpointRole.SOURCE else selection.range
        return () if value is None else (value,)
    if selection.direction is Direction.IN:
        value = selection.range if role is EndpointRole.SOURCE else selection.domain
        return () if value is None else (value,)
    if selection.direction is Direction.UNDIRECTED:
        return tuple(
            dict.fromkeys(
                value for value in (selection.domain, selection.range) if value is not None
            )
        )
    raise TypeError(f"Unsupported relation direction {selection.direction!r}.")
