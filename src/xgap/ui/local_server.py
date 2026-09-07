"""Loopback-only HTTP boundary for the XGAP clarification UI.

The server exposes a fixed JSON API over one typed local controller.  It has
no generic command, environment, model, backend, or filesystem endpoint.
Mutating requests require an allowlisted browser origin and explicit
confirmation fields.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

from xgap.ui.local_control import (
    M15LocalClarificationController,
    M15LocalControlError,
)


LOCAL_UI_HTTP_SCHEMA_VERSION = "m15-e6c-local-ui-http-v1"
DEFAULT_LOCAL_UI_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)
_MAX_REQUEST_BYTES = 16 * 1024
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class M15LocalHttpConfig:
    """Finite network policy for one local UI process."""

    bind_address: str = "127.0.0.1"
    port: int = 8765
    allowed_origins: tuple[str, ...] = DEFAULT_LOCAL_UI_ORIGINS
    max_request_bytes: int = _MAX_REQUEST_BYTES

    def __post_init__(self) -> None:
        if self.bind_address != "127.0.0.1":
            raise ValueError("local UI server must bind to 127.0.0.1")
        if not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise ValueError("local UI server port is invalid")
        if not 1 <= self.max_request_bytes <= _MAX_REQUEST_BYTES:
            raise ValueError("local UI request limit is invalid")
        if not self.allowed_origins or len(set(self.allowed_origins)) != len(
            self.allowed_origins
        ):
            raise ValueError("local UI origins must be nonempty and unique")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port is None
            ):
                raise ValueError("local UI origin is not an exact loopback URL")


class M15LocalHttpServer(ThreadingHTTPServer):
    """HTTP server carrying only immutable policy and one controller."""

    daemon_threads = True

    def __init__(
        self,
        controller: M15LocalClarificationController,
        config: M15LocalHttpConfig,
    ) -> None:
        self.controller = controller
        self.config = config
        super().__init__(
            (config.bind_address, config.port),
            _M15LocalRequestHandler,
        )


class _M15LocalRequestHandler(BaseHTTPRequestHandler):
    server: M15LocalHttpServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _origin(self) -> str | None:
        raw = self.headers.get("Origin")
        return raw if raw in self.server.config.allowed_origins else None

    def _require_allowed_origin(self) -> str:
        origin = self._origin()
        if origin is None:
            raise PermissionError("request origin is not allowed")
        return origin

    def _json_response(
        self,
        status: int,
        payload: Mapping[str, Any],
        *,
        origin: str | None = None,
    ) -> None:
        encoded = (
            json.dumps(
                dict(payload),
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        if origin is not None:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(encoded)

    def _path(self) -> str | None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            return None
        return parsed.path

    def _read_json(self, expected_fields: set[str]) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding") is not None:
            raise ValueError("streamed request bodies are unsupported")
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise TypeError("request body must be application/json")
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "")
        except ValueError as exc:
            raise ValueError("request content length is invalid") from exc
        if length < 2 or length > self.server.config.max_request_bytes:
            raise OverflowError("request body size is outside the allowed range")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body is not valid JSON") from exc
        if not isinstance(parsed, Mapping) or set(parsed) != expected_fields:
            raise ValueError("request fields do not match the endpoint contract")
        return dict(parsed)

    def _action_error(self, exc: M15LocalControlError, origin: str) -> None:
        self._json_response(
            409,
            {
                "schema_version": LOCAL_UI_HTTP_SCHEMA_VERSION,
                "error": str(exc),
                "state": self.server.controller.snapshot(),
                "paper_result": False,
            },
            origin=origin,
        )

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        origin = self._origin()
        if self.headers.get("Origin") is not None and origin is None:
            self._json_response(
                403,
                {"error": "request origin is not allowed"},
            )
            return
        if path == "/health":
            self._json_response(
                200,
                {
                    "schema_version": LOCAL_UI_HTTP_SCHEMA_VERSION,
                    "status": "ready",
                    "bind_address": "127.0.0.1",
                    "paper_result": False,
                },
                origin=origin,
            )
            return
        if path == "/api/session":
            self._json_response(
                200,
                self.server.controller.snapshot(),
                origin=origin,
            )
            return
        self._json_response(404, {"error": "endpoint not found"}, origin=origin)

    def do_POST(self) -> None:  # noqa: N802
        try:
            origin = self._require_allowed_origin()
        except PermissionError as exc:
            self._json_response(403, {"error": str(exc)})
            return
        path = self._path()
        try:
            if path == "/api/clarification":
                body = self._read_json(
                    {
                        "session_sha256",
                        "question_sha256",
                        "candidate_id",
                        "confirmed",
                    }
                )
                if body["confirmed"] is not True:
                    raise M15LocalControlError(
                        "clarification choice requires explicit confirmation"
                    )
                state = self.server.controller.select_candidate(
                    expected_session_sha256=body["session_sha256"],
                    expected_question_sha256=body["question_sha256"],
                    candidate_id=body["candidate_id"],
                )
            elif path == "/api/submit":
                body = self._read_json(
                    {"submission_preview_sha256", "confirmed"}
                )
                state = self.server.controller.submit_selected_session(
                    expected_submission_preview_sha256=body[
                        "submission_preview_sha256"
                    ],
                    confirmed=body["confirmed"],
                )
            else:
                self._json_response(
                    404,
                    {"error": "endpoint not found"},
                    origin=origin,
                )
                return
        except M15LocalControlError as exc:
            self._action_error(exc, origin)
            return
        except TypeError as exc:
            self._json_response(415, {"error": str(exc)}, origin=origin)
            return
        except OverflowError as exc:
            self._json_response(413, {"error": str(exc)}, origin=origin)
            return
        except ValueError as exc:
            self._json_response(400, {"error": str(exc)}, origin=origin)
            return
        except Exception:
            _LOGGER.exception("local UI action failed unexpectedly")
            self._json_response(
                500,
                {"error": "local control action failed"},
                origin=origin,
            )
            return
        self._json_response(200, state, origin=origin)

    def do_OPTIONS(self) -> None:  # noqa: N802
        try:
            origin = self._require_allowed_origin()
        except PermissionError as exc:
            self._json_response(403, {"error": str(exc)})
            return
        if self._path() not in {"/api/clarification", "/api/submit"}:
            self._json_response(
                404,
                {"error": "endpoint not found"},
                origin=origin,
            )
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "300")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def _method_not_allowed(self) -> None:
        self._json_response(
            405,
            {"error": "method not allowed"},
            origin=self._origin(),
        )

    do_DELETE = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_PUT = _method_not_allowed


def build_m15_local_http_server(
    controller: M15LocalClarificationController,
    config: M15LocalHttpConfig | None = None,
) -> M15LocalHttpServer:
    """Bind one finite local controller to an explicit loopback endpoint."""

    if not isinstance(controller, M15LocalClarificationController):
        raise TypeError("local HTTP server requires an XGAP local controller")
    return M15LocalHttpServer(controller, config or M15LocalHttpConfig())
