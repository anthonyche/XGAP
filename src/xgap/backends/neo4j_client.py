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


_MAX_HTTP_ERROR_BODY_BYTES = 64 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _neo4j_http_error_message(error: urllib.error.HTTPError) -> str:
    """Return bounded structured Neo4j error evidence instead of a generic 500."""

    try:
        raw = error.read(_MAX_HTTP_ERROR_BODY_BYTES + 1)
    except (OSError, ValueError):
        raw = b""
    truncated = len(raw) > _MAX_HTTP_ERROR_BODY_BYTES
    raw = raw[:_MAX_HTTP_ERROR_BODY_BYTES]
    text = raw.decode("utf-8", errors="replace").strip()
    details: list[str] = []
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("errors"), list):
            for item in payload["errors"]:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code", "")).strip()
                message = str(item.get("message", "")).strip()
                detail = ": ".join(value for value in (code, message) if value)
                if detail:
                    details.append(detail)
        if not details:
            details.append(" ".join(text.split()))
    detail_text = "; ".join(details)
    if len(detail_text) > 8192:
        detail_text = detail_text[:8192] + "..."
        truncated = True
    suffix = " [response truncated]" if truncated else ""
    if detail_text:
        return f"Neo4j HTTP {error.code}: {detail_text}{suffix}"
    return f"Neo4j HTTP {error.code}: {error.reason}"


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
        details: dict[str, Any] = {
            "http_url": self.http_url,
            "database": self.database,
        }
        if report.success:
            version_report = self.execute(
                QueryArtifact(
                    artifact_id="neo4j-version",
                    language="cypher",
                    text=(
                        "CALL dbms.components() YIELD name, versions, edition "
                        "RETURN name, versions[0] AS version, edition"
                    ),
                )
            )
            if version_report.success and version_report.rows:
                details["software_version"] = version_report.rows[0].get("version")
                details["software_edition"] = version_report.rows[0].get("edition")
        return BackendStatus(
            backend_id=self.backend_id,
            ok=report.success,
            message="Neo4j HTTP transaction endpoint is ready"
            if report.success
            else report.error or "Neo4j healthcheck failed",
            checked_at=report.ended_at,
            details=details,
        )

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        if artifact.kind not in {"native", "compiled"} or artifact.language.lower() != "cypher":
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="Neo4jClient executes native or compiled Cypher artifacts only",
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

    def explain(self, artifact: QueryArtifact) -> ExecutionReport:
        """Obtain Neo4j's plan for a catalog-registered read-only query."""

        return self._observe_plan(artifact, prefix="EXPLAIN", plan_key="plan")

    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        """Execute and profile a catalog-registered read-only query."""

        return self._observe_plan(artifact, prefix="PROFILE", plan_key="profile")

    def _observe_plan(
        self,
        artifact: QueryArtifact,
        *,
        prefix: str,
        plan_key: str,
    ) -> ExecutionReport:
        if artifact.kind not in {"native", "compiled"} or artifact.language.lower() != "cypher":
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="Neo4j observation requires native or compiled Cypher",
            )
        query = artifact.text.lstrip()
        if query.upper().startswith(("EXPLAIN ", "PROFILE ")):
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="observation catalog queries must not include EXPLAIN or PROFILE",
            )

        started_at = _now()
        started = time.perf_counter()
        try:
            response = self._post_statement(
                f"{prefix} {artifact.text}",
                artifact.parameters,
                include_stats=True,
            )
            rows = self._rows_from_response(response)
            results = response.get("results", [])
            first = results[0] if results and isinstance(results[0], dict) else {}
            native_plan = first.get(plan_key)
            if not isinstance(native_plan, dict):
                alternate_key = "profile" if plan_key == "plan" else "plan"
                native_plan = first.get(alternate_key)
            if not isinstance(native_plan, dict):
                raise ValueError(f"Neo4j {prefix} returned no native plan")
            metadata = {
                "transport": "neo4j-http",
                "database": self.database,
                "observation": prefix.lower(),
                "native_plan": _jsonable(native_plan),
                "stats": _jsonable(first.get("stats", {})),
            }
            success = True
            error = None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            rows = []
            metadata = {
                "transport": "neo4j-http",
                "database": self.database,
                "observation": prefix.lower(),
            }
            success = False
            error = str(exc)
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=success,
            rows=rows,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=error,
            started_at=started_at,
            ended_at=_now(),
            metadata=metadata,
        )

    def _post_statement(
        self,
        statement: str,
        parameters: dict[str, Any],
        *,
        include_stats: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.http_url}/db/{self.database}/tx/commit"
        statement_payload: dict[str, Any] = {
            "statement": statement,
            "parameters": parameters,
        }
        if include_stats:
            statement_payload["includeStats"] = True
            statement_payload["resultDataContents"] = ["row"]
        payload = json.dumps(
            {"statements": [statement_payload]}
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
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ValueError(_neo4j_http_error_message(exc)) from exc
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
