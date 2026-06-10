"""Condition AST for filtering paths."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from xgap.algebra.graph import PropertyGraph
from xgap.algebra.types import Path


@dataclass(frozen=True)
class NodeRef:
    """Reference to a path node by 1-based index, first, or last."""

    position: int | Literal["first", "last"]

    @classmethod
    def first(cls) -> NodeRef:
        return cls("first")

    @classmethod
    def last(cls) -> NodeRef:
        return cls("last")

    def resolve(self, path: Path) -> str:
        if self.position == "first":
            return path.first()
        if self.position == "last":
            return path.last()
        return path.node(self.position)


@dataclass(frozen=True)
class EdgeRef:
    """Reference to a path edge by 1-based index."""

    index: int

    def resolve(self, path: Path) -> str:
        return path.edge(self.index)


class Condition(ABC):
    """Base class for path predicates."""

    @abstractmethod
    def evaluate(self, path: Path, graph: PropertyGraph) -> bool:
        raise NotImplementedError

    def __and__(self, other: Condition) -> And:
        return And(self, other)

    def __or__(self, other: Condition) -> Or:
        return Or(self, other)

    def __invert__(self) -> Not:
        return Not(self)


@dataclass(frozen=True)
class LabelEquals(Condition):
    ref: NodeRef | EdgeRef
    value: str | None

    def evaluate(self, path: Path, graph: PropertyGraph) -> bool:
        try:
            if isinstance(self.ref, NodeRef):
                return graph.node_label(self.ref.resolve(path)) == self.value
            return graph.edge_label(self.ref.resolve(path)) == self.value
        except (IndexError, KeyError):
            return False


@dataclass(frozen=True)
class PropertyEquals(Condition):
    ref: NodeRef | EdgeRef
    property_name: str
    value: Any

    def evaluate(self, path: Path, graph: PropertyGraph) -> bool:
        try:
            if isinstance(self.ref, NodeRef):
                return graph.node_property(self.ref.resolve(path), self.property_name) == self.value
            return graph.edge_property(self.ref.resolve(path), self.property_name) == self.value
        except (IndexError, KeyError):
            return False


@dataclass(frozen=True)
class LengthEquals(Condition):
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("Path length comparison must use a non-negative integer.")

    def evaluate(self, path: Path, graph: PropertyGraph) -> bool:
        return len(path) == self.value


@dataclass(frozen=True, init=False)
class And(Condition):
    conditions: tuple[Condition, ...]

    def __init__(self, *conditions: Condition) -> None:
        if not conditions:
            raise ValueError("And requires at least one condition.")
        object.__setattr__(self, "conditions", tuple(conditions))

    def evaluate(self, path: Path, graph: PropertyGraph) -> bool:
        return all(condition.evaluate(path, graph) for condition in self.conditions)


@dataclass(frozen=True, init=False)
class Or(Condition):
    conditions: tuple[Condition, ...]

    def __init__(self, *conditions: Condition) -> None:
        if not conditions:
            raise ValueError("Or requires at least one condition.")
        object.__setattr__(self, "conditions", tuple(conditions))

    def evaluate(self, path: Path, graph: PropertyGraph) -> bool:
        return any(condition.evaluate(path, graph) for condition in self.conditions)


@dataclass(frozen=True)
class Not(Condition):
    condition: Condition

    def evaluate(self, path: Path, graph: PropertyGraph) -> bool:
        return not self.condition.evaluate(path, graph)
