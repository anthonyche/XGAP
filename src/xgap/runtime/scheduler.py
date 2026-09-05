"""Bounded coordinator scheduler for federated execution plans."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Mapping

from xgap.runtime.contracts import (
    FederatedExecutionPlan,
    FederatedRunResult,
    JsonRow,
    RuntimeNode,
    RuntimeNodeKind,
    RuntimeNodeResult,
    RuntimeNodeStatus,
)
from xgap.tools.backends import BACKEND_INVOKE_TOOL, BackendInvokeTool
from xgap.tools.contracts import ToolContext, ToolStatus


def _encoded_size(rows: Iterable[Mapping[str, Any]]) -> int:
    return len(
        json.dumps(list(rows), sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    )


def _deduplicate(rows: Iterable[Mapping[str, Any]]) -> tuple[JsonRow, ...]:
    unique: dict[str, JsonRow] = {}
    for row in rows:
        normalized = dict(row)
        key = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
        unique[key] = normalized
    return tuple(unique[key] for key in sorted(unique))


class FederatedScheduler:
    """Execute independent remote nodes in parallel and local nodes deterministically."""

    def __init__(self, backend_tool: BackendInvokeTool):
        self._backend_tool = backend_tool

    def execute(
        self,
        plan: FederatedExecutionPlan,
        *,
        goal_id: str = "federated-query",
    ) -> FederatedRunResult:
        started = time.perf_counter()
        nodes = {node.node_id: node for node in plan.nodes}
        results: dict[str, RuntimeNodeResult] = {}
        pending = set(nodes)

        while pending:
            while True:
                skipped = [
                    node_id
                    for node_id in sorted(pending)
                    if any(
                        input_id in results
                        and results[input_id].status is not RuntimeNodeStatus.SUCCESS
                        for input_id in nodes[node_id].inputs
                    )
                ]
                if not skipped:
                    break
                for node_id in skipped:
                    node = nodes[node_id]
                    results[node_id] = RuntimeNodeResult(
                        node_id=node_id,
                        kind=node.kind,
                        status=RuntimeNodeStatus.SKIPPED,
                        error="dependency did not complete successfully",
                    )
                    pending.remove(node_id)

            if not pending:
                break

            ready = [
                nodes[node_id]
                for node_id in sorted(pending)
                if all(
                    input_id in results
                    and results[input_id].status is RuntimeNodeStatus.SUCCESS
                    for input_id in nodes[node_id].inputs
                )
            ]
            if not ready:
                if pending:
                    raise RuntimeError("validated runtime DAG made no scheduling progress")
                break

            remote_kinds = {
                RuntimeNodeKind.REMOTE_QUERY,
                RuntimeNodeKind.REMOTE_BIND_QUERY,
            }
            remote = [node for node in ready if node.kind in remote_kinds]
            local = [node for node in ready if node.kind not in remote_kinds]
            if remote:
                workers = min(plan.max_parallelism, len(remote))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_by_id = {
                        node.node_id: executor.submit(
                            self._execute_remote,
                            node,
                            goal_id,
                            results,
                        )
                        for node in remote
                    }
                    for node_id in sorted(future_by_id):
                        results[node_id] = future_by_id[node_id].result()
                        pending.remove(node_id)
            for node in local:
                results[node.node_id] = self._execute_local(node, results)
                pending.remove(node.node_id)

        root_rows = {
            root: results[root].rows
            for root in plan.roots
            if results[root].status is RuntimeNodeStatus.SUCCESS
        }
        success = len(root_rows) == len(plan.roots)
        ordered_results = tuple(results[node.node_id] for node in plan.nodes)
        return FederatedRunResult(
            plan_id=plan.plan_id,
            success=success,
            root_rows=root_rows,
            node_results=ordered_results,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def _execute_remote(
        self,
        node: RuntimeNode,
        goal_id: str,
        results: Mapping[str, RuntimeNodeResult],
    ) -> RuntimeNodeResult:
        started = time.perf_counter()
        backend_id = node.parameters.get("backend_id")
        artifact = node.parameters.get("artifact")
        if not isinstance(backend_id, str) or not isinstance(artifact, Mapping):
            return self._error(
                node,
                "remote query requires backend_id and artifact mapping",
                started,
            )
        input_bytes = 0
        binding_count: int | None = None
        prepared_artifact = dict(artifact)
        if node.kind is RuntimeNodeKind.REMOTE_BIND_QUERY:
            input_rows = results[node.inputs[0]].rows
            input_bytes = _encoded_size(input_rows)
            try:
                prepared_artifact, binding_count = self._bind_artifact(
                    node,
                    prepared_artifact,
                    input_rows,
                )
            except (KeyError, TypeError, ValueError) as exc:
                return self._error(node, str(exc), started, input_bytes=input_bytes)
            if binding_count == 0:
                return RuntimeNodeResult(
                    node_id=node.node_id,
                    kind=node.kind,
                    status=RuntimeNodeStatus.SUCCESS,
                    rows=(),
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    input_bytes=input_bytes,
                    output_bytes=_encoded_size(()),
                    remote_calls=0,
                    metadata={
                        "backend_id": backend_id,
                        "binding_count": 0,
                        "empty_binding_short_circuit": True,
                    },
                )
        result = self._backend_tool.invoke(
            {
                "backend_id": backend_id,
                "operation": "execute",
                "payload": {"artifact": prepared_artifact},
            },
            ToolContext(
                goal_id=goal_id,
                step=0,
                call_id=f"remote:{node.node_id}",
                metadata={"runtime_node_id": node.node_id},
            ),
        )
        if result.status is not ToolStatus.SUCCESS:
            return self._error(
                node,
                result.error or "remote query failed",
                started,
                input_bytes=input_bytes,
                remote_calls=1,
            )
        value = result.value
        execution = value.get("execution") if isinstance(value, Mapping) else None
        raw_rows = execution.get("rows") if isinstance(execution, Mapping) else None
        if not isinstance(raw_rows, list) or any(not isinstance(row, Mapping) for row in raw_rows):
            return self._error(
                node,
                "backend execution returned invalid rows",
                started,
                input_bytes=input_bytes,
                remote_calls=1,
            )
        rows = tuple(dict(row) for row in raw_rows)
        metadata: dict[str, Any] = {
            "backend_id": backend_id,
            "tool_metrics": dict(result.metrics),
        }
        if binding_count is not None:
            metadata["binding_count"] = binding_count
        return RuntimeNodeResult(
            node_id=node.node_id,
            kind=node.kind,
            status=RuntimeNodeStatus.SUCCESS,
            rows=rows,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            input_bytes=input_bytes,
            output_bytes=_encoded_size(rows),
            remote_calls=1,
            metadata=metadata,
        )

    @staticmethod
    def _bind_artifact(
        node: RuntimeNode,
        artifact: dict[str, Any],
        rows: tuple[JsonRow, ...],
    ) -> tuple[dict[str, Any], int]:
        bind_field = node.parameters.get("bind_field")
        parameter = node.parameters.get("parameter")
        max_bindings = node.parameters.get("max_bindings")
        if not isinstance(bind_field, str) or not bind_field:
            raise ValueError("remote_bind_query requires a nonempty bind_field")
        if not isinstance(parameter, str) or not parameter:
            raise ValueError("remote_bind_query requires a nonempty parameter")
        if (
            not isinstance(max_bindings, int)
            or isinstance(max_bindings, bool)
            or max_bindings <= 0
        ):
            raise ValueError("remote_bind_query requires a positive max_bindings")
        raw_parameters = artifact.get("parameters", {})
        if not isinstance(raw_parameters, Mapping):
            raise ValueError("remote_bind_query artifact parameters must be a mapping")
        if parameter in raw_parameters:
            raise ValueError(
                f"remote_bind_query refuses to overwrite parameter '{parameter}'"
            )
        values: dict[str, Any] = {}
        for row in rows:
            if bind_field not in row:
                raise ValueError(f"bind field '{bind_field}' is missing")
            value = row[bind_field]
            if value is None or not isinstance(value, (str, int, float, bool)):
                raise ValueError("bind values must be non-null JSON scalars")
            key = json.dumps(value, sort_keys=True, separators=(",", ":"))
            values[key] = value
        ordered = [values[key] for key in sorted(values)]
        if len(ordered) > max_bindings:
            raise ValueError(
                f"remote_bind_query has {len(ordered)} bindings but limit is {max_bindings}"
            )
        prepared = dict(artifact)
        prepared["parameters"] = {**dict(raw_parameters), parameter: ordered}
        return prepared, len(ordered)

    def _execute_local(
        self,
        node: RuntimeNode,
        results: Mapping[str, RuntimeNodeResult],
    ) -> RuntimeNodeResult:
        started = time.perf_counter()
        inputs = [results[input_id].rows for input_id in node.inputs]
        input_bytes = sum(_encoded_size(rows) for rows in inputs)
        try:
            if node.kind is RuntimeNodeKind.ALIGN:
                rows = self._align(node, inputs[0])
                bytes_moved = 0
            elif node.kind is RuntimeNodeKind.EXCHANGE:
                rows = tuple(dict(row) for row in inputs[0])
                bytes_moved = _encoded_size(rows)
            elif node.kind is RuntimeNodeKind.COORDINATOR_JOIN:
                rows = self._join(node, inputs[0], inputs[1])
                bytes_moved = 0
            elif node.kind is RuntimeNodeKind.COORDINATOR_SEMI_JOIN:
                rows = self._semi_join(node, inputs[0], inputs[1])
                bytes_moved = 0
            elif node.kind is RuntimeNodeKind.MERGE:
                rows = _deduplicate(row for group in inputs for row in group)
                bytes_moved = 0
            elif node.kind is RuntimeNodeKind.PROJECT:
                rows = self._project(node, inputs[0])
                bytes_moved = 0
            else:
                raise ValueError(f"unsupported local runtime node '{node.kind.value}'")
        except (KeyError, TypeError, ValueError) as exc:
            return self._error(node, str(exc), started, input_bytes=input_bytes)
        return RuntimeNodeResult(
            node_id=node.node_id,
            kind=node.kind,
            status=RuntimeNodeStatus.SUCCESS,
            rows=rows,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            input_bytes=input_bytes,
            output_bytes=_encoded_size(rows),
            bytes_moved=bytes_moved,
        )

    @staticmethod
    def _align(node: RuntimeNode, rows: tuple[JsonRow, ...]) -> tuple[JsonRow, ...]:
        field = node.parameters.get("field")
        output_field = node.parameters.get("output_field", field)
        mapping = node.parameters.get("mapping", {})
        on_missing = node.parameters.get("on_missing", "error")
        if not isinstance(field, str) or not field:
            raise ValueError("align requires a nonempty field")
        if not isinstance(output_field, str) or not output_field:
            raise ValueError("align output_field must be nonempty")
        if not isinstance(mapping, Mapping):
            raise ValueError("align mapping must be a mapping")
        if on_missing not in {"error", "drop", "keep"}:
            raise ValueError("align on_missing must be error, drop, or keep")
        output: list[JsonRow] = []
        for row in rows:
            if field not in row:
                raise ValueError(f"align field '{field}' is missing")
            source_value = row[field]
            mapped = mapping.get(str(source_value)) if mapping else source_value
            if mapped is None:
                if on_missing == "drop":
                    continue
                if on_missing == "keep":
                    mapped = source_value
                else:
                    raise ValueError(f"no alignment for '{source_value}'")
            aligned = dict(row)
            aligned[output_field] = mapped
            output.append(aligned)
        return tuple(output)

    @staticmethod
    def _join(
        node: RuntimeNode,
        left_rows: tuple[JsonRow, ...],
        right_rows: tuple[JsonRow, ...],
    ) -> tuple[JsonRow, ...]:
        left_on = node.parameters.get("left_on")
        right_on = node.parameters.get("right_on")
        right_prefix = node.parameters.get("right_prefix", "right.")
        if not isinstance(left_on, str) or not isinstance(right_on, str):
            raise ValueError("coordinator_join requires string left_on and right_on")
        if not isinstance(right_prefix, str):
            raise ValueError("coordinator_join right_prefix must be a string")
        index: dict[str, list[JsonRow]] = {}
        for row in right_rows:
            if right_on not in row:
                raise ValueError(f"right join field '{right_on}' is missing")
            key = json.dumps(row[right_on], sort_keys=True, default=str)
            index.setdefault(key, []).append(row)

        joined: list[JsonRow] = []
        for left in left_rows:
            if left_on not in left:
                raise ValueError(f"left join field '{left_on}' is missing")
            key = json.dumps(left[left_on], sort_keys=True, default=str)
            for right in index.get(key, []):
                merged = dict(left)
                for name, value in right.items():
                    if name not in merged or merged[name] == value:
                        merged[name] = value
                    else:
                        merged[f"{right_prefix}{name}"] = value
                joined.append(merged)
        return _deduplicate(joined)

    @staticmethod
    def _semi_join(
        node: RuntimeNode,
        left_rows: tuple[JsonRow, ...],
        right_rows: tuple[JsonRow, ...],
    ) -> tuple[JsonRow, ...]:
        left_on = node.parameters.get("left_on")
        right_on = node.parameters.get("right_on")
        if not isinstance(left_on, str) or not isinstance(right_on, str):
            raise ValueError(
                "coordinator_semi_join requires string left_on and right_on"
            )
        right_keys: set[str] = set()
        for row in right_rows:
            if right_on not in row:
                raise ValueError(f"right semi-join field '{right_on}' is missing")
            right_keys.add(json.dumps(row[right_on], sort_keys=True, default=str))
        selected: list[JsonRow] = []
        for row in left_rows:
            if left_on not in row:
                raise ValueError(f"left semi-join field '{left_on}' is missing")
            key = json.dumps(row[left_on], sort_keys=True, default=str)
            if key in right_keys:
                selected.append(dict(row))
        return _deduplicate(selected)

    @staticmethod
    def _project(node: RuntimeNode, rows: tuple[JsonRow, ...]) -> tuple[JsonRow, ...]:
        fields = node.parameters.get("fields")
        if (
            not isinstance(fields, (list, tuple))
            or not fields
            or any(not isinstance(field, str) or not field for field in fields)
        ):
            raise ValueError("project requires a nonempty list of field names")
        if len(set(fields)) != len(fields):
            raise ValueError("project field names must be unique")
        projected: list[JsonRow] = []
        for row in rows:
            missing = [field for field in fields if field not in row]
            if missing:
                raise ValueError(f"project fields are missing: {', '.join(missing)}")
            projected.append({field: row[field] for field in fields})
        return _deduplicate(projected)

    @staticmethod
    def _error(
        node: RuntimeNode,
        error: str,
        started: float,
        *,
        input_bytes: int = 0,
        remote_calls: int = 0,
    ) -> RuntimeNodeResult:
        return RuntimeNodeResult(
            node_id=node.node_id,
            kind=node.kind,
            status=RuntimeNodeStatus.ERROR,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            input_bytes=input_bytes,
            remote_calls=remote_calls,
            error=error,
        )
