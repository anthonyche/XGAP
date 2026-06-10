"""Directed labeled property graph for path-algebra evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from xgap.algebra.types import Path, PathSet


@dataclass(frozen=True)
class NodeRecord:
    label: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeRecord:
    source: str
    target: str
    label: str | None = None
    properties: Mapping[str, Any] = field(default_factory=dict)


class PropertyGraph:
    """A directed labeled multigraph with node and edge properties."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeRecord] = {}
        self._edges: dict[str, EdgeRecord] = {}
        self._outgoing: dict[str, list[str]] = {}
        self._incoming: dict[str, list[str]] = {}

    def add_node(
        self,
        node_id: str,
        label: str | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> None:
        if node_id in self._nodes:
            raise ValueError(f"Node {node_id!r} already exists.")
        self._nodes[node_id] = NodeRecord(label=label, properties=dict(properties or {}))
        self._outgoing[node_id] = []
        self._incoming[node_id] = []

    def add_edge(
        self,
        edge_id: str,
        source: str,
        target: str,
        label: str | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> None:
        if edge_id in self._edges:
            raise ValueError(f"Edge {edge_id!r} already exists.")
        if source not in self._nodes:
            raise KeyError(f"Source node {source!r} does not exist.")
        if target not in self._nodes:
            raise KeyError(f"Target node {target!r} does not exist.")
        self._edges[edge_id] = EdgeRecord(
            source=source,
            target=target,
            label=label,
            properties=dict(properties or {}),
        )
        self._outgoing[source].append(edge_id)
        self._incoming[target].append(edge_id)

    def node_label(self, node_id: str) -> str | None:
        return self._nodes[node_id].label

    def edge_label(self, edge_id: str) -> str | None:
        return self._edges[edge_id].label

    def node_property(self, node_id: str, property_name: str) -> Any:
        return self._nodes[node_id].properties[property_name]

    def edge_property(self, edge_id: str, property_name: str) -> Any:
        return self._edges[edge_id].properties[property_name]

    def edge_source(self, edge_id: str) -> str:
        return self._edges[edge_id].source

    def edge_target(self, edge_id: str) -> str:
        return self._edges[edge_id].target

    def outgoing_edges(self, node_id: str) -> tuple[str, ...]:
        return tuple(self._outgoing[node_id])

    def incoming_edges(self, node_id: str) -> tuple[str, ...]:
        return tuple(self._incoming[node_id])

    def nodes_as_paths(self) -> PathSet:
        return PathSet(Path.zero_length(node_id) for node_id in sorted(self._nodes))

    def edges_as_paths(self) -> PathSet:
        return PathSet(
            Path.one_length(edge.source, edge_id, edge.target)
            for edge_id, edge in sorted(self._edges.items())
        )
