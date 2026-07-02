"""Neo4j native Cypher client using the HTTP transaction endpoint."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


class Neo4jClient:
    """Executes native Cypher artifacts against Neo4j.

    This client intentionally uses only the Python standard library. It
    does not depend on the Neo4j Python driver and does not compile XGAP
    logical plans.
    """

    def __init__(self, descriptor: BackendDescriptor):
        self.descriptor = descriptor
        runtime = descriptor.runtime
        self.backend_id = descriptor.id
        self.http_url = os.environ.get(
            str(runtime.get("http_url_env", "NEO4J_HTTP_URL")),
            str(runtime.get("default_http_url", "http://127.0.0.1:7474")),
        ).rstrip("/")
        self.database = os.environ.get(
            str(runtime.get("database_env", "NEO4J_DATABASE")),
            str(runtime.get("default_database", "neo4j")),
        )
        self.user = os.environ.get(
            str(runtime.get("user_env", "NEO4J_USER")),
            str(runtime.get("default_user", "neo4j")),
        )
        self.password = os.environ.get(
            str(runtime.get("password_env", "NEO4J_PASSWORD")),
            str(runtime.get("default_password", "xgap-lab-password")),
        )
        self.timeout_seconds = float(runtime.get("timeout_seconds", 30))

    def healthcheck(self) -> BackendStatus:
        artifact = QueryArtifact(
            artifact_id="neo4j-healthcheck",
            language="cypher",
            text="RETURN 1 AS ok",
        )
        report = self.execute(artifact)
        return BackendStatus(
            backend_id=self.backend_id,
            ok=report.success,
            message="Neo4j HTTP transaction endpoint is ready"
            if report.success
            else report.error or "Neo4j healthcheck failed",
            checked_at=report.ended_at,
            details={"http_url": self.http_url, "database": self.database},
        )

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        if artifact.kind != "native" or artifact.language.lower() != "cypher":
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="Neo4jClient executes native Cypher artifacts only",
            )

        started_at = _now()
        started = time.perf_counter()
        try:
            response = self._post_statement(artifact.text, artifact.parameters)
            rows = self._rows_from_response(response)
            success = True
            error = None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            rows = []
            success = False
            error = str(exc)
        ended_at = _now()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=success,
            rows=rows,
            elapsed_ms=elapsed_ms,
            error=error,
            started_at=started_at,
            ended_at=ended_at,
            metadata={"transport": "neo4j-http", "database": self.database},
        )

    def _post_statement(self, statement: str, parameters: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.http_url}/db/{self.database}/tx/commit"
        payload = json.dumps(
            {"statements": [{"statement": statement, "parameters": parameters}]}
        ).encode("utf-8")
        auth = base64.b64encode(f"{self.user}:{self.password}".encode("utf-8")).decode(
            "ascii"
        )
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read().decode("utf-8")
        parsed = json.loads(body)
        errors = parsed.get("errors", [])
        if errors:
            message = "; ".join(str(error.get("message", error)) for error in errors)
            raise ValueError(message)
        return parsed

    def _rows_from_response(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        output_rows: list[dict[str, Any]] = []
        for result in response.get("results", []):
            columns = [str(column) for column in result.get("columns", [])]
            for item in result.get("data", []):
                row_values = item.get("row", [])
                output_rows.append(
                    {
                        column: _jsonable(row_values[index])
                        for index, column in enumerate(columns)
                        if index < len(row_values)
                    }
                )
        return output_rows
