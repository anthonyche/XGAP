"""GPC-Lite path-pattern AST."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Mapping

from xgap.algebra.conditions import Condition
from xgap.algebra.ops import RecursiveMode

PathMode = RecursiveMode


@dataclass(frozen=True)
class Var:
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("Variable name must be a string.")
        if not self.name.strip():
            raise ValueError("Variable name must be non-empty.")


class Direction(Enum):
    OUT = auto()
    IN = auto()
    UNDIRECTED = auto()


@dataclass(frozen=True)
class NodePattern:
    var: Var | None = None
    label: str | None = None
    properties: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_label(self.label)
        properties = _validate_properties(self.properties)
        object.__setattr__(self, "properties", properties)


@dataclass(frozen=True)
class EdgePattern:
    var: Var | None = None
    label: str | None = None
    direction: Direction = Direction.OUT
    properties: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_label(self.label)
        if not isinstance(self.direction, Direction):
            raise TypeError("Edge direction must be a Direction value.")
        properties = _validate_properties(self.properties)
        object.__setattr__(self, "properties", properties)


class RegexExpr:
    """Base class for GPC-Lite regular path expressions."""


@dataclass(frozen=True)
class Rel(RegexExpr):
    edge: EdgePattern


@dataclass(frozen=True)
class Seq(RegexExpr):
    left: RegexExpr
    right: RegexExpr


@dataclass(frozen=True)
class Alt(RegexExpr):
    left: RegexExpr
    right: RegexExpr


@dataclass(frozen=True)
class Plus(RegexExpr):
    child: RegexExpr


@dataclass(frozen=True)
class Star(RegexExpr):
    child: RegexExpr


@dataclass(frozen=True)
class OptionalExpr(RegexExpr):
    child: RegexExpr


@dataclass(frozen=True)
class Bounded(RegexExpr):
    child: RegexExpr
    min_repeats: int
    max_repeats: int | None


class SelectorKind(Enum):
    ALL = auto()
    ANY = auto()
    ANY_K = auto()
    ANY_SHORTEST = auto()
    ALL_SHORTEST = auto()
    SHORTEST_K = auto()
    SHORTEST_K_GROUP = auto()


@dataclass(frozen=True)
class Selector:
    kind: SelectorKind
    k: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SelectorKind):
            raise TypeError("Selector kind must be a SelectorKind value.")


@dataclass(frozen=True)
class PathPatternQuery:
    path_var: Var | None
    source: NodePattern
    expr: RegexExpr
    target: NodePattern
    selector: Selector
    restrictor: PathMode
    condition: Condition | None = None
    max_depth: int | None = None


def _validate_label(label: str | None) -> None:
    if label is None:
        return
    if not isinstance(label, str):
        raise TypeError("Pattern label must be a string or None.")
    if not label:
        raise ValueError("Pattern label must be non-empty when provided.")


def _validate_properties(properties: Mapping[str, object]) -> dict[str, object]:
    result = dict(properties)
    for name in result:
        if not isinstance(name, str):
            raise TypeError("Property names must be strings.")
        if not name:
            raise ValueError("Property names must be non-empty.")
    return result
