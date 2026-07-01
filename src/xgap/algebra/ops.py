"""Logical path-algebra operator AST."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from xgap.algebra.conditions import Condition


class OutputKind(Enum):
    PATH_SET = "PATH_SET"
    SOLUTION_SPACE = "SOLUTION_SPACE"
    BINDING_RELATION = "BINDING_RELATION"


@dataclass(frozen=True)
class AlgebraOp:
    """Base class for logical-plan AST nodes."""

    def output_kind(self) -> OutputKind:
        raise NotImplementedError(f"{type(self).__name__} output kind is not implemented yet.")

    def children(self) -> tuple[AlgebraOp, ...]:
        raise NotImplementedError(f"{type(self).__name__} child metadata is not implemented yet.")

    def operator_name(self) -> str:
        raise NotImplementedError(f"{type(self).__name__} operator name is not implemented yet.")


@dataclass(frozen=True)
class NodesOp(AlgebraOp):
    """Logical `Nodes(G)` operator."""

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return ()

    def operator_name(self) -> str:
        return "Nodes"


@dataclass(frozen=True)
class EdgesOp(AlgebraOp):
    """Logical `Edges(G)` operator."""

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return ()

    def operator_name(self) -> str:
        return "Edges"


@dataclass(frozen=True)
class SelectionOp(AlgebraOp):
    condition: Condition
    child: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "Selection"


@dataclass(frozen=True)
class UnionOp(AlgebraOp):
    left: AlgebraOp
    right: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.left, self.right)

    def operator_name(self) -> str:
        return "Union"


@dataclass(frozen=True)
class JoinOp(AlgebraOp):
    left: AlgebraOp
    right: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.left, self.right)

    def operator_name(self) -> str:
        return "Join"


class RecursiveMode(Enum):
    WALK = "WALK"
    TRAIL = "TRAIL"
    ACYCLIC = "ACYCLIC"
    SIMPLE = "SIMPLE"
    SHORTEST = "SHORTEST"


class GroupKey(Enum):
    NONE = "NONE"
    SOURCE = "SOURCE"
    TARGET = "TARGET"
    LENGTH = "LENGTH"
    SOURCE_TARGET = "SOURCE_TARGET"
    SOURCE_LENGTH = "SOURCE_LENGTH"
    TARGET_LENGTH = "TARGET_LENGTH"
    SOURCE_TARGET_LENGTH = "SOURCE_TARGET_LENGTH"


class OrderKey(Enum):
    PARTITION = "PARTITION"
    GROUP = "GROUP"
    PATH = "PATH"
    PARTITION_GROUP = "PARTITION_GROUP"
    PARTITION_PATH = "PARTITION_PATH"
    GROUP_PATH = "GROUP_PATH"
    PARTITION_GROUP_PATH = "PARTITION_GROUP_PATH"


def _normalize_enum(value: object, enum_type: type[GroupKey] | type[OrderKey]) -> GroupKey | OrderKey:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type[value.upper()]
        except KeyError as error:
            raise NotImplementedError(
                f"Unsupported {enum_type.__name__} value {value!r}."
            ) from error
    raise NotImplementedError(f"Unsupported {enum_type.__name__} value {value!r}.")


@dataclass(frozen=True)
class RecursiveOp(AlgebraOp):
    child: AlgebraOp
    mode: RecursiveMode
    max_depth: int | None = None

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "Recursive"


@dataclass(frozen=True)
class GroupByOp(AlgebraOp):
    child: AlgebraOp
    keys: GroupKey | str | tuple[str, ...] = GroupKey.NONE
    aggregates: tuple[str, ...] = ()

    def output_kind(self) -> OutputKind:
        return OutputKind.SOLUTION_SPACE

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "GroupBy"

    def group_key(self) -> GroupKey:
        return _normalize_enum(self.keys, GroupKey)  # type: ignore[return-value]


@dataclass(frozen=True)
class OrderByOp(AlgebraOp):
    child: AlgebraOp
    keys: OrderKey | str | tuple[str, ...] = OrderKey.PATH

    def output_kind(self) -> OutputKind:
        return OutputKind.SOLUTION_SPACE

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "OrderBy"

    def order_key(self) -> OrderKey:
        return _normalize_enum(self.keys, OrderKey)  # type: ignore[return-value]


@dataclass(frozen=True)
class ProjectionOp(AlgebraOp):
    child: AlgebraOp
    num_partitions: int | None = None
    num_groups: int | None = None
    num_paths: int | None = None
    fields: tuple[str, ...] | None = None

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "Projection"


@dataclass(frozen=True)
class BindNodeOp(AlgebraOp):
    var: str
    child: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.BINDING_RELATION

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "BindNode"


@dataclass(frozen=True)
class BindEdgeOp(AlgebraOp):
    source_var: str
    edge_var: str | None
    target_var: str
    child: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.BINDING_RELATION

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "BindEdge"


@dataclass(frozen=True)
class BindingJoinOp(AlgebraOp):
    left: AlgebraOp
    right: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.BINDING_RELATION

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.left, self.right)

    def operator_name(self) -> str:
        return "BindingJoin"


@dataclass(frozen=True)
class BindingProjectOp(AlgebraOp):
    vars: tuple[str, ...]
    child: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.BINDING_RELATION

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "BindingProject"


@dataclass(frozen=True)
class QuantifiedCheckOp(AlgebraOp):
    candidates: AlgebraOp
    witnesses: AlgebraOp
    quantifier: object
    correlation_vars: tuple[str, ...]
    child_var: str
    domain: AlgebraOp | None = None

    def output_kind(self) -> OutputKind:
        return OutputKind.BINDING_RELATION

    def children(self) -> tuple[AlgebraOp, ...]:
        if self.domain is None:
            return (self.candidates, self.witnesses)
        return (self.candidates, self.witnesses, self.domain)

    def operator_name(self) -> str:
        return "QuantifiedCheck"


@dataclass(frozen=True)
class AntiSemiJoinOp(AlgebraOp):
    left: AlgebraOp
    right: AlgebraOp
    on: tuple[str, ...]

    def output_kind(self) -> OutputKind:
        return OutputKind.BINDING_RELATION

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.left, self.right)

    def operator_name(self) -> str:
        return "AntiSemiJoin"


@dataclass(frozen=True)
class FocusProjectionOp(AlgebraOp):
    focus_var: str
    child: AlgebraOp

    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return (self.child,)

    def operator_name(self) -> str:
        return "FocusProjection"
