"""Strict, opt-in HTTP transport for the guarded GrailQA development runner.

This transport is deliberately separate from the frozen provider defaults. It
performs one bounded attempt to the exact numeric-loopback chat endpoint, with
neither environment proxies nor redirect following. Endpoint failures retain
the legacy provider's transport-error categories, not schema-repair semantics.
"""

from __future__ import annotations

import http.client
import json
import math
import socket
from typing import Any, Mapping
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from xgap.experiments.grailqa_guarded_provider import (
    CredentialPersistenceError, _contains_known_credential,
    _credential_value_for_payload_check,
)
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def _validate_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        port = parts.port
        valid = (
            isinstance(url, str) and parts.scheme == "http"
            and type(port) is int and 1 <= port <= 65535
            and url == f"http://127.0.0.1:{port}/v1/chat/completions"
        )
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("An exact numeric-loopback chat endpoint is required.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never construct a second Request carrying the Authorization header.
        raise ProviderTransportError(
            LiveFailureCategory.PROVIDER_ERROR, "Loopback inference redirect refused."
        )


def _reject_nonfinite(value: str) -> None:
    raise ValueError("Nonfinite JSON is not accepted.")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite JSON is not accepted.")
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not accepted.")
        result[key] = value
    return result


class LoopbackInferenceTransport:
    """OpenAI-compatible transport with one local HTTP attempt and no retry.

    Configuration and request rejection occurs before a send and propagates as a
    fatal local error. Once an attempt starts, safe ProviderTransportError values
    preserve the provider's one-call accounting and suppress schema repair.
    """

    def post_json(
        self, *, url: str, api_key: str, payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        _validate_url(url)
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        ):
            raise ValueError("A finite positive inference timeout is required.")
        if (
            not isinstance(api_key, str) or not api_key or not api_key.isascii()
            or any(ord(character) < 32 or ord(character) == 127 for character in api_key)
        ):
            raise ValueError("A valid runtime credential is required.")
        if not isinstance(payload, Mapping):
            raise ValueError("The inference payload must be an object.")
        marker = _credential_value_for_payload_check(api_key, url)
        if _contains_known_credential(payload, marker):
            raise CredentialPersistenceError("Outgoing request contains the current credential.")
        try:
            body = json.dumps(dict(payload), ensure_ascii=True, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise ValueError("The inference payload must be finite JSON.") from None
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "xgap-grailqa-guarded/1",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                if response.geturl() != url:
                    raise ProviderTransportError(
                        LiveFailureCategory.PROVIDER_ERROR, "Loopback inference redirect refused."
                    )
                if response.status != 200:
                    raise ProviderTransportError(
                        LiveFailureCategory.PROVIDER_ERROR, "Loopback inference HTTP failure."
                    )
                response_body = response.read(_MAX_RESPONSE_BYTES + 1)
        except ProviderTransportError:
            raise
        except urllib.error.HTTPError:
            # Error bodies and arbitrary endpoint text are never persisted.
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR, "Loopback inference HTTP failure."
            ) from None
        except (TimeoutError, socket.timeout):
            raise ProviderTransportError(
                LiveFailureCategory.TIMEOUT, "Provider request timed out."
            ) from None
        except urllib.error.URLError as error:
            timeout = isinstance(error.reason, (TimeoutError, socket.timeout))
            raise ProviderTransportError(
                LiveFailureCategory.TIMEOUT if timeout else LiveFailureCategory.PROVIDER_ERROR,
                "Provider request timed out." if timeout else "Loopback inference transport failed.",
            ) from None
        except (OSError, http.client.HTTPException):
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR, "Loopback inference transport failed."
            ) from None
        if not isinstance(response_body, bytes) or len(response_body) > _MAX_RESPONSE_BYTES:
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR, "Loopback inference response is invalid."
            )
        try:
            result = json.loads(
                response_body.decode("utf-8"), parse_constant=_reject_nonfinite,
                parse_float=_finite_float, object_pairs_hook=_unique_object,
            )
        except (UnicodeError, ValueError, RecursionError):
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR, "Loopback inference response is invalid."
            ) from None
        if not isinstance(result, dict) or _contains_known_credential(result, marker):
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR, "Loopback inference response is invalid."
            )
        return result
