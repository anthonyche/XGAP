"""Set-valued binding relations for focused quantified patterns."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class BindingKind(Enum):
    NODE = "NODE"
    EDGE = "EDGE"


@dataclass(frozen=True)
class BindingField:
    name: str
    kind: BindingKind

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("Binding field name must be a string.")
        if not self.name.strip():
            raise ValueError("Binding field name must be non-empty.")
        if not isinstance(self.kind, BindingKind):
            raise TypeError("Binding field kind must be a BindingKind value.")


@dataclass(frozen=True)
class BindingSchema:
    fields: tuple[BindingField, ...]

    def __init__(self, fields: tuple[BindingField, ...] | list[BindingField]) -> None:
        object.__setattr__(self, "fields", tuple(fields))
        self._validate()

    @classmethod
    def from_pairs(cls, pairs: tuple[tuple[str, BindingKind], ...]) -> BindingSchema:
        return cls(tuple(BindingField(name, kind) for name, kind in pairs))

    def _validate(self) -> None:
        seen: set[str] = set()
        for field in self.fields:
            if not isinstance(field, BindingField):
                raise TypeError("BindingSchema fields must be BindingField values.")
            if field.name in seen:
                raise ValueError(f"Duplicate binding field {field.name!r}.")
            seen.add(field.name)

    def names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def has(self, name: str) -> bool:
        return name in self.names()

    def field(self, name: str) -> BindingField:
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(f"Unknown binding field {name!r}.")

    def kind(self, name: str) -> BindingKind:
        return self.field(name).kind

    def index(self, name: str) -> int:
        for index, field in enumerate(self.fields):
            if field.name == name:
                return index
        raise KeyError(f"Unknown binding field {name!r}.")

    def project(self, names: tuple[str, ...]) -> BindingSchema:
        return BindingSchema(tuple(self.field(name) for name in names))

    def merge(self, other: BindingSchema) -> BindingSchema:
        fields = list(self.fields)
        existing = {field.name: field.kind for field in fields}
        for field in other.fields:
            kind = existing.get(field.name)
            if kind is not None:
                if kind is not field.kind:
                    raise ValueError(
                        f"Binding field {field.name!r} has incompatible kinds "
                        f"{kind.value} and {field.kind.value}."
                    )
                continue
            fields.append(field)
            existing[field.name] = field.kind
        return BindingSchema(tuple(fields))


@dataclass(frozen=True)
class BindingRow:
    schema: BindingSchema
    values: tuple[str, ...]

    def __init__(self, schema: BindingSchema, values: tuple[str, ...] | list[str]) -> None:
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "values", tuple(values))
        if len(self.values) != len(self.schema.fields):
            raise ValueError("Binding row value count must match schema field count.")
        for value in self.values:
            if not isinstance(value, str):
                raise TypeError("Binding row values must be graph id strings.")

    @classmethod
    def from_mapping(
        cls,
        schema: BindingSchema,
        values: Mapping[str, str],
    ) -> BindingRow:
        missing = [name for name in schema.names() if name not in values]
        if missing:
            raise KeyError(f"Missing binding values for {missing!r}.")
        return cls(schema, tuple(values[name] for name in schema.names()))

    def value(self, name: str) -> str:
        return self.values[self.schema.index(name)]

    def as_mapping(self) -> dict[str, str]:
        return dict(zip(self.schema.names(), self.values, strict=True))

    def project(self, names: tuple[str, ...]) -> BindingRow:
        return BindingRow(self.schema.project(names), tuple(self.value(name) for name in names))

    def compatible_with(self, other: BindingRow) -> bool:
        shared = set(self.schema.names()).intersection(other.schema.names())
        return all(self.value(name) == other.value(name) for name in shared)

    def merge(self, other: BindingRow) -> BindingRow:
        if not self.compatible_with(other):
            raise ValueError("Cannot merge incompatible binding rows.")
        schema = self.schema.merge(other.schema)
        values = self.as_mapping()
        values.update(other.as_mapping())
        return BindingRow.from_mapping(schema, values)

    def sort_key(self) -> tuple[str, ...]:
        return self.values


class BindingRelation:
    """A deterministic set of binding rows with one ordered schema."""

    def __init__(
        self,
        schema: BindingSchema,
        rows: tuple[BindingRow, ...] | list[BindingRow] | None = None,
    ) -> None:
        self.schema = schema
        unique: set[BindingRow] = set()
        for row in rows or ():
            if row.schema != schema:
                raise ValueError("Binding relation rows must all use the relation schema.")
            unique.add(row)
        self.rows = tuple(sorted(unique, key=lambda row: row.sort_key()))

    @classmethod
    def from_mappings(
        cls,
        schema: BindingSchema,
        rows: tuple[Mapping[str, str], ...] | list[Mapping[str, str]],
    ) -> BindingRelation:
        return cls(schema, [BindingRow.from_mapping(schema, row) for row in rows])

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __contains__(self, row: object) -> bool:
        return row in self.rows

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BindingRelation):
            return NotImplemented
        return self.schema == other.schema and self.rows == other.rows
