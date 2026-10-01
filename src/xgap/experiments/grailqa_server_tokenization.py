"""Bounded comparison against a running vLLM 0.11.1 tokenization endpoint.

For the supported text-only payload, the server's ordered token IDs must equal
the pinned local tokenizer's IDs before inference can proceed. This observes
one payload's preprocessing, not model weights, a global template identity, or
an atomic guarantee against a service restart before subsequent inference.
No old experiment entrypoint is activated by importing this module.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from threading import Lock
import time
from typing import Any, Literal, Mapping, Protocol
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from xgap.experiments.grailqa_guarded_provider import (
    CredentialPersistenceError, QueryEventJournal, _contains_known_credential,
    _credential_value_for_payload_check,
)
from xgap.experiments.hashing import content_hash
from xgap.llm.token_budget import _text_chat_inputs
from xgap.llm.token_budget_provider import (
    TokenBudgetAccountingError, TokenBudgetGuard, TokenBudgetProviderStateError,
)


EQUALITY_SCOPE = "exact_payload_preprocessing_at_probe_time_only"
_MAX_RESPONSE_BYTES = 1024 * 1024


class ServerTokenizationEndpointError(RuntimeError):
    """A bounded endpoint failure; arbitrary endpoint text is never exposed."""

    def __init__(self, reason: str = "transport_unavailable") -> None:
        if reason not in {"transport_unavailable", "http_error", "redirect_refused", "invalid_response"}:
            reason = "transport_unavailable"
        self.reason = reason
        super().__init__("Server tokenization endpoint unavailable.")


class TokenizationTransport(Protocol):
    def post_json(
        self, *, url: str, api_key: str, payload: Mapping[str, Any], timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


def _tokenize_url(base_url: str) -> str:
    try:
        parts = urlsplit(base_url)
        port = parts.port
    except (TypeError, ValueError):
        raise ValueError("An exact loopback v1 base URL is required.") from None
    if (
        parts.scheme != "http" or parts.hostname != "127.0.0.1"
        or type(port) is not int or not 1 <= port <= 65535
        or parts.netloc != f"127.0.0.1:{port}"
        or parts.path not in {"/v1", "/v1/"} or parts.query or parts.fragment
    ):
        raise ValueError("An exact loopback v1 base URL is required.")
    return f"http://127.0.0.1:{port}/tokenize"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ServerTokenizationEndpointError("redirect_refused")


class LoopbackTokenizationTransport:
    """One HTTP attempt with no environment proxy, redirect, or retry."""

    def post_json(
        self, *, url: str, api_key: str, payload: Mapping[str, Any], timeout_seconds: float,
    ) -> Mapping[str, Any]:
        if not url.endswith("/tokenize") or _tokenize_url(url[:-9] + "/v1") != url:
            raise ValueError("The tokenization URL must name the exact loopback endpoint.")
        marker = _credential_value_for_payload_check(api_key, url)
        if _contains_known_credential(payload, marker):
            raise CredentialPersistenceError("Outgoing request contains the current credential.")
        data = json.dumps(dict(payload), allow_nan=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                if response.geturl() != url:
                    raise ServerTokenizationEndpointError("redirect_refused")
                if response.status != 200:
                    raise ServerTokenizationEndpointError("http_error")
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except ServerTokenizationEndpointError:
            raise
        except urllib.error.HTTPError:
            raise ServerTokenizationEndpointError("http_error") from None
        except (OSError, urllib.error.URLError):
            raise ServerTokenizationEndpointError("transport_unavailable") from None
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ServerTokenizationEndpointError("invalid_response")
        try:
            result = json.loads(body)
        except (UnicodeError, ValueError):
            raise ServerTokenizationEndpointError("invalid_response") from None
        if not isinstance(result, dict):
            raise ServerTokenizationEndpointError("invalid_response")
        return result


def _projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    messages, kwargs = _text_chat_inputs(payload)
    if kwargs != {"enable_thinking": False}:
        raise ValueError("The frozen non-thinking text profile is required.")
    # response_format constrains decoding, not this text preprocessing path.
    # Bind the FULL inference payload separately; never append schema text here.
    return {
        "model": payload["model"], "messages": messages,
        "chat_template_kwargs": kwargs,
        "add_generation_prompt": True, "continue_final_message": False,
        "add_special_tokens": False, "return_token_strs": False,
    }


def _valid_ids(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(type(token) is int and token >= 0 for token in value)


class ServerTokenizationGuard:
    """One generation probe and at most one actual repair probe per question.

    Ordinary endpoint errors/mismatches deny inference without a retry. Journal
    failures and broken call accounting propagate fatally. The returned check
    retains the local guard's schema; separate probe receipts account for these
    additional service calls, which are not model-generation or backend calls.
    """

    def __init__(
        self, local_guard: TokenBudgetGuard, counter: Any, journal: QueryEventJournal,
        question_id: str, *, base_url: str, api_key: str, timeout_seconds: float,
        context_limit: int, maximum_calls: int = 2,
        transport: TokenizationTransport | None = None,
    ) -> None:
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("A nonempty question ID is required.")
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("A nonempty runtime credential is required.")
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
            or type(context_limit) is not int or context_limit <= 0
            or type(maximum_calls) is not int or maximum_calls not in {1, 2}
        ):
            raise ValueError("Finite tokenization limits are required.")
        self._url = _tokenize_url(base_url)
        marker = _credential_value_for_payload_check(api_key, self._url)
        if _contains_known_credential(question_id, marker):
            raise CredentialPersistenceError("Question identity contains the current credential.")
        self._local_guard, self._counter, self._journal = local_guard, counter, journal
        self._question_id, self._api_key = question_id, api_key
        # The literal public CWRU placeholder is not a secret on this exact
        # loopback endpoint. Every genuine credential still uses exact scanning.
        self._credential_marker = marker
        self._timeout, self._context_limit, self._maximum = timeout_seconds, context_limit, maximum_calls
        self._transport = transport if transport is not None else LoopbackTokenizationTransport()
        self._attempted = self._completed = self._errors = self._checks = 0
        self._latency = 0.0
        self._receipts: list[dict[str, Any]] = []
        self._terminal = False
        self._journal_failed = False
        self._journal_failure_phase: str | None = None
        self._lock = Lock()

    @property
    def journal_failed(self) -> bool:
        return self._journal_failed

    @property
    def journal_failure_phase(self) -> str | None:
        return self._journal_failure_phase

    def _append(self, event: Mapping[str, Any]) -> None:
        try:
            self._journal.append(event)
        except BaseException:
            self._journal_failed = True
            self._journal_failure_phase = str(event["event"])
            raise

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "tokenizer_probe_attempted_calls": self._attempted,
            "tokenizer_probe_completed_results": self._completed,
            "tokenizer_probe_error_count": self._errors,
            "tokenizer_probe_latency_seconds": self._latency,
            "tokenizer_probe_receipts": deepcopy(self._receipts),
            "preprocessing_equality_scope": EQUALITY_SCOPE,
            "remote_serving_parity_verified": False,
            "journal_failed": self._journal_failed,
            "journal_failure_phase": self._journal_failure_phase,
        }

    def check(
        self, payload: Mapping[str, Any], *, call_kind: Literal["generation", "repair"],
    ) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise TokenBudgetProviderStateError("Tokenization guard does not support overlapping calls.")
        try:
            if self._terminal or call_kind != ("generation" if self._checks == 0 else "repair") or self._checks >= 2:
                raise TokenBudgetProviderStateError("Unexpected tokenization guard call order.")
            self._checks += 1
            if _contains_known_credential(payload, self._credential_marker):
                raise CredentialPersistenceError("Outgoing request contains the current credential.")
            full_hash = content_hash(payload)
            local = self._local_guard.check(payload, call_kind=call_kind)
            try:
                record = json.loads(json.dumps(local, allow_nan=False))
            except (ValueError, TypeError):
                raise TokenBudgetAccountingError("Local token check is not JSON safe.") from None
            if (
                not isinstance(record, dict) or record.get("payload_sha256") != full_hash
                or record.get("call_kind") != call_kind or type(record.get("passed")) is not bool
                or content_hash(payload) != full_hash
            ):
                raise TokenBudgetAccountingError("Local token check does not bind the unchanged request.")
            if _contains_known_credential(record, self._credential_marker):
                raise CredentialPersistenceError("Token check contains the current credential.")
            if record["passed"] is False:
                self._terminal = True
                return record
            if self._attempted >= self._maximum:
                return self._deny(record, "server_tokenization_call_budget_exhausted")
            try:
                projected = _projection(payload)
                identity = deepcopy(self._counter.identity)
                if identity != record.get("tokenizer_identity"):
                    return self._deny(record, "server_tokenization_local_identity_mismatch")
                local_sequence = self._counter.payload_token_ids(payload)
                local_ids = list(local_sequence) if isinstance(local_sequence, (list, tuple)) else local_sequence
                if content_hash(payload) != full_hash:
                    raise TokenBudgetAccountingError("Local token counter changed the bound payload.")
                if (
                    not _valid_ids(local_ids) or type(record.get("input_tokens")) is not int
                    or len(local_ids) != record["input_tokens"]
                    or self._counter.identity != identity
                    or record.get("budgets", {}).get("context") != self._context_limit
                ):
                    return self._deny(record, "server_tokenization_local_identity_mismatch")
            except (ValueError, TypeError, KeyError, OSError):
                return self._deny(record, "server_tokenization_local_unavailable")
            binding = {
                "question_id": self._question_id, "call_kind": call_kind,
                "probe_index": self._attempted + 1, "payload_sha256": full_hash,
                "tokenize_payload_sha256": content_hash(projected),
                "local_token_ids_sha256": content_hash(local_ids),
                "local_count": len(local_ids), "preprocessing_equality_scope": EQUALITY_SCOPE,
            }
            self._append({"event": "tokenizer_probe_attempt", **binding, "pre_send_intent_only": True})
            self._attempted += 1
            started = time.perf_counter()
            try:
                response = self._transport.post_json(
                    url=self._url, api_key=self._api_key, payload=projected,
                    timeout_seconds=self._timeout,
                )
            except ServerTokenizationEndpointError as error:
                elapsed = time.perf_counter() - started
                self._latency += elapsed
                receipt = {"event": "tokenizer_probe_error", **binding,
                           "reason": "server_tokenization_" + error.reason, "elapsed_seconds": elapsed}
                self._append(receipt)
                self._errors += 1
                self._receipts.append(receipt)
                return self._deny(record, receipt["reason"])
            except BaseException:
                self._latency += time.perf_counter() - started
                raise
            elapsed = time.perf_counter() - started
            self._latency += elapsed
            reason = "server_tokenization_match"
            ids, count, maximum = None, None, None
            if _contains_known_credential(response, self._credential_marker):
                reason = "server_tokenization_credential_echo_rejected"
            elif not isinstance(response, Mapping) or set(response) - {"tokens", "count", "max_model_len", "token_strs"}:
                reason = "server_tokenization_invalid_response"
            else:
                ids, count, maximum = response.get("tokens"), response.get("count"), response.get("max_model_len")
                if (
                    not _valid_ids(ids) or type(count) is not int or count != len(ids)
                    or type(maximum) is not int or maximum <= 0
                    or response.get("token_strs") is not None
                ):
                    reason = "server_tokenization_invalid_response"
                elif maximum != self._context_limit:
                    reason = "server_tokenization_context_mismatch"
                elif ids != local_ids:
                    reason = "server_tokenization_ids_mismatch"
            try:
                # identity is a cached receipt: the public token-ID operation
                # rechecks actual files/template/libraries after the HTTP wait.
                after_sequence = self._counter.payload_token_ids(payload)
                after_ids = list(after_sequence) if isinstance(after_sequence, (list, tuple)) else after_sequence
                if not _valid_ids(after_ids) or after_ids != local_ids or self._counter.identity != identity:
                    reason = "server_tokenization_local_identity_mismatch"
            except (ValueError, TypeError, KeyError, OSError):
                reason = "server_tokenization_local_unavailable"
            if content_hash(payload) != full_hash or content_hash(projected) != binding["tokenize_payload_sha256"]:
                raise TokenBudgetAccountingError("Tokenization transport changed the bound payload.")
            receipt = {
                "event": "tokenizer_probe_result", **binding, "reason": reason,
                "elapsed_seconds": elapsed, "matched": reason == "server_tokenization_match",
                "server_token_ids_sha256": content_hash(ids) if _valid_ids(ids) else None,
                "server_count": count if type(count) is int else None,
                "server_max_model_len": maximum if type(maximum) is int else None,
            }
            self._append(receipt)
            self._completed += 1
            self._receipts.append(receipt)
            return record if receipt["matched"] else self._deny(record, reason)
        except BaseException:
            self._terminal = True
            raise
        finally:
            self._lock.release()

    def _deny(self, record: dict[str, Any], reason: str) -> dict[str, Any]:
        self._terminal = True
        return {**record, "passed": False, "reason": reason}
