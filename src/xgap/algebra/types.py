"""Core path-algebra data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping


@dataclass(frozen=True)
class Path:
    """An alternating node, edge, node sequence."""

    sequence: tuple[str, ...]

    def __post_init__(self) -> None:
        sequence = tuple(self.sequence)
        if not sequence:
            raise ValueError("A path must contain at least one node.")
        if len(sequence) % 2 == 0:
            raise ValueError("A path sequence must alternate node, edge, node and end at a node.")
        object.__setattr__(self, "sequence", sequence)

    @classmethod
    def zero_length(cls, node_id: str) -> Path:
        return cls((node_id,))

    @classmethod
    def one_length(cls, source_id: str, edge_id: str, target_id: str) -> Path:
        return cls((source_id, edge_id, target_id))

    def __len__(self) -> int:
        return (len(self.sequence) - 1) // 2

    def first(self) -> str:
        return self.sequence[0]

    def last(self) -> str:
        return self.sequence[-1]

    def node(self, index: int) -> str:
        if index < 1 or index > len(self) + 1:
            raise IndexError(f"Node index {index} is out of range for path length {len(self)}.")
        return self.sequence[(index - 1) * 2]

    def edge(self, index: int) -> str:
        if index < 1 or index > len(self):
            raise IndexError(f"Edge index {index} is out of range for path length {len(self)}.")
        return self.sequence[(index * 2) - 1]

    def node_ids(self) -> tuple[str, ...]:
        return self.sequence[0::2]

    def edge_ids(self) -> tuple[str, ...]:
        return self.sequence[1::2]

    def can_concatenate(self, other: Path) -> bool:
        return self.last() == other.first()

    def concatenate(self, other: Path) -> Path:
        if not self.can_concatenate(other):
            raise ValueError(
                f"Cannot concatenate paths ending at {self.last()!r} and starting at {other.first()!r}."
            )
        return Path(self.sequence + other.sequence[1:])


class PathSet:
    """A small set-like wrapper over paths."""

    def __init__(self, paths: Iterable[Path] | None = None) -> None:
        self._paths: set[Path] = set()
        for path in paths or ():
            self.add(path)

    def add(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise TypeError("PathSet can only contain Path instances.")
        self._paths.add(path)

    def union(self, other: PathSet) -> PathSet:
        return PathSet((*self._paths, *other._paths))

    def sorted(self) -> tuple[Path, ...]:
        return tuple(sorted(self._paths, key=lambda path: path.sequence))

    def __iter__(self) -> Iterator[Path]:
        return iter(self.sorted())

    def __len__(self) -> int:
        return len(self._paths)

    def __contains__(self, path: object) -> bool:
        return path in self._paths

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PathSet):
            return NotImplemented
        return self._paths == other._paths


@dataclass(frozen=True)
class PartitionId:
    key: tuple[object, ...]


@dataclass(frozen=True)
class GroupId:
    partition: PartitionId
    key: tuple[object, ...]


@dataclass(frozen=True)
class SolutionSpace:
    """Extended path-algebra solution space."""

    paths: PathSet = field(default_factory=PathSet)
    partitions: tuple[PartitionId, ...] = ()
    groups: tuple[GroupId, ...] = ()
    path_to_group: Mapping[Path, GroupId] = field(default_factory=dict)
    group_to_partition: Mapping[GroupId, PartitionId] = field(default_factory=dict)
    path_ranks: Mapping[Path, int] = field(default_factory=dict)
    group_ranks: Mapping[GroupId, int] = field(default_factory=dict)
    partition_ranks: Mapping[PartitionId, int] = field(default_factory=dict)
    rows: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        paths = PathSet(self.paths)
        partitions = tuple(sorted(set(self.partitions), key=lambda partition: partition.key))
        groups = tuple(
            sorted(set(self.groups), key=lambda group: (group.partition.key, group.key))
        )

        object.__setattr__(self, "paths", paths)
        object.__setattr__(self, "partitions", partitions)
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "path_to_group", dict(self.path_to_group))
        object.__setattr__(self, "group_to_partition", dict(self.group_to_partition))
        object.__setattr__(self, "path_ranks", dict(self.path_ranks))
        object.__setattr__(self, "group_ranks", dict(self.group_ranks))
        object.__setattr__(self, "partition_ranks", dict(self.partition_ranks))

    def groups_for_partition(self, partition: PartitionId) -> tuple[GroupId, ...]:
        return tuple(group for group in self.groups if self.group_to_partition[group] == partition)

    def paths_for_group(self, group: GroupId) -> tuple[Path, ...]:
        return tuple(path for path in self.paths if self.path_to_group[path] == group)

    def rank(self, item: Path | GroupId | PartitionId) -> int:
        if isinstance(item, Path):
            return self.path_ranks[item]
        if isinstance(item, GroupId):
            return self.group_ranks[item]
        return self.partition_ranks[item]

    def min_len_group(self, group: GroupId) -> int:
        return min(len(path) for path in self.paths_for_group(group))

    def min_len_partition(self, partition: PartitionId) -> int:
        return min(
            self.min_len_group(group)
            for group in self.groups_for_partition(partition)
        )
