"""Request-owned output fields, checked without rewriting a semantic program."""

from dataclasses import dataclass
from typing import Any, Mapping

from xgap.semantic.program import (
    SemanticGraphProgram, SemanticOperatorKind, SemanticValueKind,
)


def _valid_field(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


@dataclass(frozen=True)
class RequestedOutput:
    kind: str
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.kind != "binding_set":
            raise ValueError("Requested output supports only binding_set")
        if (not isinstance(self.fields, tuple) or not 1 <= len(self.fields) <= 64
                or not all(_valid_field(name) for name in self.fields)
                or len(set(self.fields)) != len(self.fields)):
            raise ValueError("Requested output requires 1–64 unique nonblank fields of at most 256 characters")

    @classmethod
    def from_dict(cls, value: Any) -> "RequestedOutput":
        if not isinstance(value, Mapping) or set(value) != {"kind", "fields"}:
            raise ValueError("Requested output must contain exactly kind and fields")
        if not isinstance(value["fields"], list):
            raise ValueError("Requested output fields must be a JSON array")
        return cls(kind=value["kind"], fields=tuple(value["fields"]))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "fields": list(self.fields)}

    def validate_program(self, program: SemanticGraphProgram) -> None:
        if not isinstance(program, SemanticGraphProgram) or len(program.roots) != 1:
            raise ValueError("Requested output requires exactly one semantic root")
        root = next((operator for operator in program.operators
                     if operator.operator_id == program.roots[0]), None)
        if root is None or not isinstance(root.parameters, Mapping):
            raise ValueError("Requested output requires an explicit semantic root")
        if root.output_kind is not SemanticValueKind.BINDING_SET:
            raise ValueError("Requested output requires a binding_set root")
        if root.kind is SemanticOperatorKind.PROJECT:
            projections = root.parameters.get("projections")
            if not isinstance(projections, Mapping) or not projections:
                raise ValueError("Requested output requires explicit Project projections")
            fields = set(projections)
        elif root.kind is SemanticOperatorKind.MATCH:
            entity = root.parameters.get("entity_field", "entity")
            properties = root.parameters.get("properties", {})
            if not _valid_field(entity) or not isinstance(properties, Mapping):
                raise ValueError("Requested output requires explicit Match output fields")
            fields = {entity, *properties}
        else:
            raise ValueError("Requested output supports only Project or Match roots")
        if not all(_valid_field(name) for name in fields):
            raise ValueError("Requested output root has invalid field names")
        if fields != set(self.fields):
            raise ValueError("Semantic root fields do not match requested output fields")
