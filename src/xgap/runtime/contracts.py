"""Typed coordinator-level federated execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


JsonMap = dict[str, Any]
JsonRow = dict[str, Any]


class RuntimePlanError(ValueError):
    """Raised when a federated execution plan is invalid."""


class RuntimeNodeKind(str, Enum):
    REMOTE_QUERY = "remote_query"
    REMOTE_BIND_QUERY = "remote_bind_query"
    ALIGN = "align"
    EXCHANGE = "exchange"
    COORDINATOR_JOIN = "coordinator_join"
    COORDINATOR_SEMI_JOIN = "coordinator_semi_join"
    COORDINATOR_GROUP_AGGREGATE = "coordinator_group_aggregate"
    COORDINATOR_SORT_LIMIT = "coordinator_sort_limit"
    COORDINATOR_PATH_SELECT = "coordinator_path_select"
    MERGE = "merge"
    PROJECT = "project"


class RuntimeNodeStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


_ARITY: dict[RuntimeNodeKind, tuple[int, int | None]] = {
    RuntimeNodeKind.REMOTE_QUERY: (0, 0),
    RuntimeNodeKind.REMOTE_BIND_QUERY: (1, 1),
    RuntimeNodeKind.ALIGN: (1, 1),
    RuntimeNodeKind.EXCHANGE: (1, 1),
    RuntimeNodeKind.COORDINATOR_JOIN: (2, 2),
    RuntimeNodeKind.COORDINATOR_SEMI_JOIN: (2, 2),
    RuntimeNodeKind.COORDINATOR_GROUP_AGGREGATE: (1, 1),
    RuntimeNodeKind.COORDINATOR_SORT_LIMIT: (1, 1),
    RuntimeNodeKind.COORDINATOR_PATH_SELECT: (1, 1),
    RuntimeNodeKind.MERGE: (1, None),
    RuntimeNodeKind.PROJECT: (1, 1),
}


@dataclass(frozen=True)
class RuntimeNode:
    node_id: str
    kind: RuntimeNodeKind
    inputs: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    semantic_operator_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise RuntimePlanError("runtime node_id must be nonempty")
        minimum, maximum = _ARITY[self.kind]
        input_count = len(self.inputs)
        if input_count < minimum or (maximum is not None and input_count > maximum):
            expected = f">={minimum}" if maximum is None else (
                str(minimum) if minimum == maximum else f"{minimum}..{maximum}"
            )
            raise RuntimePlanError(
                f"runtime node '{self.node_id}' kind '{self.kind.value}' expects "
                f"{expected} inputs, got {input_count}"
            )
        if len(set(self.inputs)) != len(self.inputs):
            raise RuntimePlanError(f"runtime node '{self.node_id}' has duplicate inputs")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeNode":
        raw_inputs = data.get("inputs", [])
        raw_semantic_ids = data.get("semantic_operator_ids", [])
        parameters = data.get("parameters", {})
        if not isinstance(raw_inputs, list) or not isinstance(raw_semantic_ids, list):
            raise RuntimePlanError("runtime node inputs and semantic_operator_ids must be lists")
        if not isinstance(parameters, Mapping):
            raise RuntimePlanError("runtime node parameters must be a mapping")
        try:
            kind = RuntimeNodeKind(str(data["kind"]))
            node_id = str(data["node_id"])
        except (KeyError, ValueError) as exc:
            raise RuntimePlanError(f"invalid runtime node: {exc}") from exc
        return cls(
            node_id=node_id,
            kind=kind,
            inputs=tuple(str(item) for item in raw_inputs),
            parameters=dict(parameters),
            semantic_operator_ids=tuple(str(item) for item in raw_semantic_ids),
        )

    def to_dict(self) -> JsonMap:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "inputs": list(self.inputs),
            "parameters": dict(self.parameters),
            "semantic_operator_ids": list(self.semantic_operator_ids),
        }


@dataclass(frozen=True)
class FederatedExecutionPlan:
    plan_id: str
    nodes: tuple[RuntimeNode, ...]
    roots: tuple[str, ...]
    max_remote_calls: int = 16
    max_parallelism: int = 4
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise RuntimePlanError("federated plan_id must be nonempty")
        if not self.nodes or not self.roots:
            raise RuntimePlanError("a federated plan requires nodes and roots")
        if self.max_remote_calls < 0 or self.max_parallelism <= 0:
            raise RuntimePlanError("runtime budgets must be nonnegative and parallelism positive")
        nodes = {node.node_id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise RuntimePlanError("runtime node ids must be unique")
        if len(set(self.roots)) != len(self.roots):
            raise RuntimePlanError("runtime roots must be unique")
        for root in self.roots:
            if root not in nodes:
                raise RuntimePlanError(f"unknown runtime root '{root}'")
        for node in self.nodes:
            for input_id in node.inputs:
                if input_id not in nodes:
                    raise RuntimePlanError(
                        f"runtime node '{node.node_id}' references unknown input '{input_id}'"
                    )

        remote_calls = sum(
            node.kind
            in {RuntimeNodeKind.REMOTE_QUERY, RuntimeNodeKind.REMOTE_BIND_QUERY}
            for node in self.nodes
        )
        if remote_calls > self.max_remote_calls:
            raise RuntimePlanError(
                f"plan requires {remote_calls} remote calls but budget is {self.max_remote_calls}"
            )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise RuntimePlanError("federated execution plan must be acyclic")
            if node_id in visited:
                return
            visiting.add(node_id)
            for input_id in nodes[node_id].inputs:
                visit(input_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in nodes:
            visit(node_id)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FederatedExecutionPlan":
        raw_nodes = data.get("nodes")
        raw_roots = data.get("roots")
        metadata = data.get("metadata", {})
        if not isinstance(raw_nodes, list) or not isinstance(raw_roots, list):
            raise RuntimePlanError("federated plan nodes and roots must be lists")
        if not isinstance(metadata, Mapping):
            raise RuntimePlanError("federated plan metadata must be a mapping")
        try:
            plan_id = str(data["plan_id"])
            max_remote_calls = int(data.get("max_remote_calls", 16))
            max_parallelism = int(data.get("max_parallelism", 4))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimePlanError(f"invalid federated plan: {exc}") from exc
        return cls(
            plan_id=plan_id,
            nodes=tuple(RuntimeNode.from_dict(node) for node in raw_nodes),
            roots=tuple(str(root) for root in raw_roots),
            max_remote_calls=max_remote_calls,
            max_parallelism=max_parallelism,
            metadata=dict(metadata),
        )

    def to_dict(self) -> JsonMap:
        return {
            "plan_id": self.plan_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "roots": list(self.roots),
            "max_remote_calls": self.max_remote_calls,
            "max_parallelism": self.max_parallelism,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RuntimeNodeResult:
    node_id: str
    kind: RuntimeNodeKind
    status: RuntimeNodeStatus
    rows: tuple[JsonRow, ...] = ()
    elapsed_ms: float = 0.0
    input_bytes: int = 0
    output_bytes: int = 0
    bytes_moved: int = 0
    remote_calls: int = 0
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> JsonMap:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "rows": [dict(row) for row in self.rows],
            "row_count": self.row_count,
            "elapsed_ms": self.elapsed_ms,
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "bytes_moved": self.bytes_moved,
            "remote_calls": self.remote_calls,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FederatedRunResult:
    plan_id: str
    success: bool
    root_rows: Mapping[str, tuple[JsonRow, ...]]
    node_results: tuple[RuntimeNodeResult, ...]
    elapsed_ms: float

    @property
    def total_remote_calls(self) -> int:
        return sum(result.remote_calls for result in self.node_results)

    @property
    def total_bytes_moved(self) -> int:
        return sum(result.bytes_moved for result in self.node_results)

    @property
    def final_rows(self) -> tuple[JsonRow, ...]:
        rows: list[JsonRow] = []
        for root_id in sorted(self.root_rows):
            rows.extend(dict(row) for row in self.root_rows[root_id])
        return tuple(rows)

    def to_dict(self) -> JsonMap:
        return {
            "plan_id": self.plan_id,
            "success": self.success,
            "root_rows": {
                root_id: [dict(row) for row in rows]
                for root_id, rows in sorted(self.root_rows.items())
            },
            "final_rows": [dict(row) for row in self.final_rows],
            "node_results": [result.to_dict() for result in self.node_results],
            "elapsed_ms": self.elapsed_ms,
            "total_remote_calls": self.total_remote_calls,
            "total_bytes_moved": self.total_bytes_moved,
        }
