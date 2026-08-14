"""Typed runtime records for backend smoke experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from xgap.infrastructure.descriptors import DescriptorError, JsonMap, load_yaml_mapping


JsonRows = list[dict[str, Any]]


def _dict(value: Mapping[str, Any] | None) -> JsonMap:
    return dict(value or {})


def _list(value: object, field_name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DescriptorError(f"DatasetSpec field '{field_name}' must be a list")
    return list(value)


@dataclass(frozen=True)
class BackendStatus:
    backend_id: str
    ok: bool
    message: str
    checked_at: str | None = None
    details: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackendStatus":
        return cls(
            backend_id=str(data["backend_id"]),
            ok=bool(data["ok"]),
            message=str(data.get("message", "")),
            checked_at=data.get("checked_at"),
            details=_dict(data.get("details") if isinstance(data.get("details"), dict) else {}),
        )

    def to_dict(self) -> JsonMap:
        return {
            "backend_id": self.backend_id,
            "ok": self.ok,
            "message": self.message,
            "checked_at": self.checked_at,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    name: str
    description: str
    backends: JsonMap
    expected_fields: list[str] = field(default_factory=list)
    expected_non_empty: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DatasetSpec":
        backends = data.get("backends")
        if not isinstance(backends, dict):
            raise DescriptorError("DatasetSpec field 'backends' must be a mapping")
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            description=str(data.get("description", "")),
            backends=dict(backends),
            expected_fields=[str(item) for item in _list(data.get("expected_fields"), "expected_fields")],
            expected_non_empty=bool(data.get("expected_non_empty", True)),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DatasetSpec":
        return cls.from_dict(load_yaml_mapping(path))

    def backend_config(self, backend_id: str) -> JsonMap:
        config = self.backends.get(backend_id)
        if not isinstance(config, dict):
            raise KeyError(f"Dataset '{self.id}' has no backend config for '{backend_id}'")
        return dict(config)

    def to_dict(self) -> JsonMap:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "backends": dict(self.backends),
            "expected_fields": list(self.expected_fields),
            "expected_non_empty": self.expected_non_empty,
        }


@dataclass(frozen=True)
class QueryArtifact:
    artifact_id: str
    language: str
    text: str
    kind: str = "native"
    source_path: str | None = None
    parameters: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QueryArtifact":
        return cls(
            artifact_id=str(data["artifact_id"]),
            language=str(data["language"]),
            text=str(data["text"]),
            kind=str(data.get("kind", "native")),
            source_path=data.get("source_path"),
            parameters=_dict(data.get("parameters") if isinstance(data.get("parameters"), dict) else {}),
        )

    def to_dict(self) -> JsonMap:
        return {
            "artifact_id": self.artifact_id,
            "language": self.language,
            "text": self.text,
            "kind": self.kind,
            "source_path": self.source_path,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class ExecutionReport:
    backend_id: str
    artifact_id: str
    language: str
    success: bool
    rows: JsonRows = field(default_factory=list)
    elapsed_ms: float | None = None
    error: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    metadata: JsonMap = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def result_status(self) -> str:
        if not self.success:
            return "execution_error"
        if self.row_count:
            return "execution_success_nonempty"
        return "execution_success_empty"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionReport":
        rows = data.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError("ExecutionReport rows must be a list")
        report = cls(
            backend_id=str(data["backend_id"]),
            artifact_id=str(data["artifact_id"]),
            language=str(data["language"]),
            success=bool(data["success"]),
            rows=[dict(row) for row in rows if isinstance(row, dict)],
            elapsed_ms=data.get("elapsed_ms"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            metadata=_dict(data.get("metadata") if isinstance(data.get("metadata"), dict) else {}),
        )
        if data.get("row_count") not in {None, report.row_count}:
            raise ValueError("ExecutionReport row_count does not match its rows")
        if data.get("result_status") not in {None, report.result_status}:
            raise ValueError("ExecutionReport result_status does not match its outcome")
        return report

    def to_dict(self) -> JsonMap:
        return {
            "backend_id": self.backend_id,
            "artifact_id": self.artifact_id,
            "language": self.language,
            "success": self.success,
            "rows": [dict(row) for row in self.rows],
            "row_count": self.row_count,
            "result_status": self.result_status,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    backend_id: str
    dataset_id: str
    query_artifact: QueryArtifact
    execution: ExecutionReport
    normalized_result_path: str
    log_path: str
    metadata: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunRecord":
        return cls(
            run_id=str(data["run_id"]),
            backend_id=str(data["backend_id"]),
            dataset_id=str(data["dataset_id"]),
            query_artifact=QueryArtifact.from_dict(data["query_artifact"]),
            execution=ExecutionReport.from_dict(data["execution"]),
            normalized_result_path=str(data["normalized_result_path"]),
            log_path=str(data["log_path"]),
            metadata=_dict(data.get("metadata") if isinstance(data.get("metadata"), dict) else {}),
        )

    def to_dict(self) -> JsonMap:
        return {
            "run_id": self.run_id,
            "backend_id": self.backend_id,
            "dataset_id": self.dataset_id,
            "query_artifact": self.query_artifact.to_dict(),
            "execution": self.execution.to_dict(),
            "normalized_result_path": self.normalized_result_path,
            "log_path": self.log_path,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)
