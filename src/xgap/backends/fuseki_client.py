"""Apache Jena Fuseki native SPARQL client."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact


_MAX_HTTP_ERROR_BODY_BYTES = 64 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fuseki_http_error_message(error: urllib.error.HTTPError) -> str:
    """Preserve bounded Fuseki error text so server timeouts stay observable."""

    try:
        raw = error.read(_MAX_HTTP_ERROR_BODY_BYTES + 1)
    except (OSError, ValueError):
        raw = b""
    truncated = len(raw) > _MAX_HTTP_ERROR_BODY_BYTES
    text = " ".join(
        raw[:_MAX_HTTP_ERROR_BODY_BYTES]
        .decode("utf-8", errors="replace")
        .split()
    )
    if len(text) > 8192:
        text = text[:8192] + "..."
        truncated = True
    suffix = " [response truncated]" if truncated else ""
    if text:
        return f"Fuseki HTTP {error.code}: {text}{suffix}"
    return f"Fuseki HTTP {error.code}: {error.reason}"


class FusekiClient:
    """Executes native SPARQL artifacts against a Fuseki dataset."""

    def __init__(self, descriptor: BackendDescriptor):
        self.descriptor = descriptor
        runtime = descriptor.runtime
        self.backend_id = descriptor.id
        self.base_url = os.environ.get(
            str(runtime.get("base_url_env", "FUSEKI_URL")),
            str(runtime.get("default_base_url", "http://127.0.0.1:3030")),
        ).rstrip("/")
        self.dataset = os.environ.get(
            str(runtime.get("dataset_env", "FUSEKI_DATASET_NAME")),
            str(runtime.get("default_dataset", "xgap")),
        )
        self.timeout_seconds = float(runtime.get("timeout_seconds", 30))

    def healthcheck(self) -> BackendStatus:
        checked_at = _now()
        url = f"{self.base_url}/$/ping"
        server_header = None
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                ok = 200 <= response.status < 300
                server_header = response.headers.get("Server")
            message = "Fuseki ping endpoint is ready" if ok else f"Fuseki ping returned {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            ok = False
            message = str(exc)
        return BackendStatus(
            backend_id=self.backend_id,
            ok=ok,
            message=message,
            checked_at=checked_at,
            details={
                "base_url": self.base_url,
                "dataset": self.dataset,
                "server_header": server_header,
            },
        )

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        if artifact.kind not in {"native", "compiled"} or artifact.language.lower() != "sparql":
            return ExecutionReport(
                backend_id=self.backend_id,
                artifact_id=artifact.artifact_id,
                language=artifact.language,
                success=False,
                error="FusekiClient executes native or compiled SPARQL artifacts only",
            )

        started_at = _now()
        started = time.perf_counter()
        try:
            response = self._post_query(artifact.text)
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
            metadata={"transport": "sparql-http", "dataset": self.dataset},
        )

    def _post_query(self, query: str) -> dict[str, Any]:
        url = f"{self.base_url}/{self.dataset}/sparql"
        payload = urllib.parse.urlencode({"query": query}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ValueError(_fuseki_http_error_message(exc)) from exc
        return json.loads(body)

    def _rows_from_response(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        variables = [str(item) for item in response.get("head", {}).get("vars", [])]
        rows: list[dict[str, Any]] = []
        for binding_row in response.get("results", {}).get("bindings", []):
            row: dict[str, Any] = {}
            for variable in variables:
                binding = binding_row.get(variable)
                if isinstance(binding, dict):
                    row[variable] = binding.get("value")
            rows.append(row)
        return rows
