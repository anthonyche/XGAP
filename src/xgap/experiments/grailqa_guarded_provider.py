"""Per-question semantic-provider bridge with durable pre-send token receipts.

This opt-in adapter preserves the existing provider's attempt/usage/latency
ledger. Local token checks and durable journal writes are separate from model
attempts. Neither this adapter nor its journal authorizes an experiment.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Literal, Mapping

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_semantic_pilot import GenerationResult
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.experiments.runtime_alignment import PromptSchemaView
from xgap.llm.openai_compatible import (
    LiveFailureCategory, LiveInvocationArtifact, LiveProviderError,
    OpenAICompatibleStructuredCandidateProvider, OpenAICompatibleTransport,
    ProviderTransportError, redact_secrets,
)
from xgap.llm.schemas import PlannerRequest
from xgap.llm.token_budget_provider import (
    TokenBudgetAccountingError, TokenBudgetGuard, TokenBudgetGuardDenied,
    TokenBudgetedCandidateProvider, TokenBudgetProviderStateError,
)


class QueryEventJournal:
    """Exclusively create a JSONL journal and durably append generic mappings.

    No existing journal is reopened. Each append is serialized before writing,
    then flushed and fsynced. After an I/O failure, this handle refuses further
    appends instead of retrying a possibly partially persisted event.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).absolute()
        if self.path.exists() or self.path.is_symlink():
            raise FileExistsError("Query journal already exists or is a symlink.")
        self._handle = self.path.open("x", encoding="utf-8")
        self._lock = Lock()
        self._failed = False

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def closed(self) -> bool:
        return self._handle.closed

    def append(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping):
            raise TypeError("Query journal entries must be JSON mappings.")
        text = json.dumps(dict(event), sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
        with self._lock:
            if self._failed or self.closed:
                raise RuntimeError("Query journal is closed or has a previous I/O failure.")
            try:
                self._handle.write(text)
                self._handle.flush()
                os.fsync(self._handle.fileno())
            except OSError:
                self._failed = True
                raise

    def close(self) -> None:
        with self._lock:
            self._handle.close()

    def __enter__(self) -> "QueryEventJournal":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


class CredentialPersistenceError(RuntimeError):
    """The current supplied credential must not enter persisted request text."""


def _contains_known_credential(value: object, credential: str) -> bool:
    """Detect only this known credential, not arbitrary secrets or PII."""
    if isinstance(value, str):
        return bool(credential) and credential in value
    if isinstance(value, Mapping):
        return any(
            _contains_known_credential(str(key), credential)
            or _contains_known_credential(item, credential)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_known_credential(item, credential) for item in value)
    return False


_CHECK_FIELDS = frozenset({
    "schema_version", "call_kind", "payload_sha256", "passed", "reason", "input_tokens",
    "requested_output_tokens", "budgets", "tokenizer_identity",
})
_FORBIDDEN_CHECK_KEYS = frozenset({
    "api_key", "authorization", "authorization_header", "access_token", "secret", "password",
    "headers", "messages", "prompt", "prompt_text", "system_prompt", "payload", "content",
})


def _check_has_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in _FORBIDDEN_CHECK_KEYS or _check_has_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_check_has_forbidden_key(item) for item in value)
    return False


class _JournaledGuard:
    def __init__(self, guard: TokenBudgetGuard, journal: QueryEventJournal, question_id: str):
        self.guard, self.journal, self.question_id = guard, journal, question_id
        self.records: list[dict[str, Any]] = []
        self.journal_failed = False

    def check(
        self, payload: Mapping[str, Any], *, call_kind: Literal["generation", "repair"],
    ) -> dict[str, Any]:
        payload_sha256 = content_hash(payload)
        record = self.guard.check(payload, call_kind=call_kind)
        record = json.loads(json.dumps(record, allow_nan=False))
        if (
            not isinstance(record, dict) or set(record) - _CHECK_FIELDS
            or _check_has_forbidden_key(record)
            or record.get("payload_sha256") != payload_sha256
            or content_hash(payload) != payload_sha256
            or record.get("call_kind") != call_kind
            or type(record.get("passed")) is not bool
            or (record.get("reason") is not None and (
                not isinstance(record["reason"], str)
                or re.fullmatch(r"[a-z][a-z0-9_]*", record["reason"]) is None
            ))
        ):
            raise TokenBudgetAccountingError("Token-check receipt is unsafe or does not bind its call.")
        event = {
            "event": "token_check", "question_id": self.question_id,
            "check_index": len(self.records) + 1, "call_kind": call_kind,
            "check": record,
        }
        try:
            # The enclosing checked transport cannot delegate until this
            # append, flush, and fsync have completed successfully.
            self.journal.append(event)
        except Exception:
            self.journal_failed = True
            raise
        self.records.append(deepcopy(record))
        return record


class _JournaledTransport:
    """Retain completed responses even if the next repair check cannot finish."""

    def __init__(
        self, delegate: OpenAICompatibleTransport, journal: QueryEventJournal, question_id: str,
    ) -> None:
        self.delegate, self.journal, self.question_id = delegate, journal, question_id
        self.attempt_index = 0
        self.failure_phase: str | None = None

    def _append(self, phase: str, event: Mapping[str, Any]) -> None:
        try:
            self.journal.append(event)
        except Exception:
            self.failure_phase = phase
            raise

    def post_json(
        self, *, url: str, api_key: str, payload: Mapping[str, Any], timeout_seconds: float,
    ) -> Mapping[str, Any]:
        if _contains_known_credential(payload, api_key):
            # Not a ProviderTransportError: no send occurred, and the legacy
            # provider must not persist its assembled but unsafe request.
            raise CredentialPersistenceError("Outgoing request contains the current credential.")
        index = self.attempt_index + 1
        binding = {"question_id": self.question_id, "attempt_index": index,
                   "payload_sha256": content_hash(payload)}
        self._append("transport_attempt", {
            "event": "transport_attempt", **binding, "pre_send_intent_only": True,
        })
        self.attempt_index = index
        try:
            response = self.delegate.post_json(
                url=url, api_key=api_key, payload=payload, timeout_seconds=timeout_seconds,
            )
        except Exception as error:
            self._append("transport_error", {
                "event": "transport_error", **binding, "error_type": type(error).__name__,
            })
            raise
        if _contains_known_credential(response, api_key):
            self._append("response_credential_echo_rejected", {
                "event": "response_credential_echo_rejected", **binding,
            })
            # The send happened. Preserve its exact attempt count while keeping
            # the unsafe raw body out of both the journal and the base parser.
            raise ProviderTransportError(
                LiveFailureCategory.PROVIDER_ERROR,
                "Provider response contains the current credential; response rejected.",
            )
        self._append("transport_response", {
            "event": "transport_response", **binding, "raw_response": redact_secrets(response),
        })
        return response


class GuardedSemanticPilotProvider:
    """Single-use bridge for one frozen question; share only its run journal."""

    def __init__(
        self, model_bundle: ModelBundle, guard: TokenBudgetGuard,
        journal: QueryEventJournal, question_id: str, *,
        base_provider: OpenAICompatibleStructuredCandidateProvider | None = None,
    ) -> None:
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("A nonempty question ID is required.")
        base = base_provider if base_provider is not None else build_openai_compatible_provider(
            model_bundle, response_parser=parse_normalized_planner_response,
        )
        # The bounded provider intentionally does not expose its private config.
        # Capture the effective environment-resolved identity before wrapping.
        self._effective_config = deepcopy(base.config.safe_dict())
        self._model_name = base.config.model
        self._provider_id = base.provider_id
        self._journal, self._question_id = journal, question_id
        self._guard = _JournaledGuard(guard, journal, question_id)
        self._transport = _JournaledTransport(base.transport, journal, question_id)
        self._provider = TokenBudgetedCandidateProvider(
            replace(base, transport=self._transport), self._guard,
        )
        self._diagnostics: dict[str, Any] = {}
        self._lock = Lock()
        self._used = False

    @property
    def effective_config(self) -> dict[str, Any]:
        return deepcopy(self._effective_config)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def token_check_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(self._guard.records))

    @property
    def last_invocation(self) -> LiveInvocationArtifact | None:
        return self._provider.last_invocation

    @property
    def guard_diagnostics(self) -> dict[str, Any]:
        return deepcopy(self._diagnostics)

    def generate(self, request: PlannerRequest, prompt_view: PromptSchemaView) -> GenerationResult:
        del prompt_view  # The frozen request already contains the exact view.
        with self._lock:
            if self._used:
                raise TokenBudgetProviderStateError("Use a new provider instance for each question.")
            if str(request.metadata.get("task_id", "")) != self._question_id:
                raise ValueError("Request task ID does not match the journaled question.")
            self._used = True
        provider_error: LiveProviderError | None = None
        try:
            response = self._provider.generate_candidates(request)
            invocation = self.last_invocation
            if invocation is None:
                raise TokenBudgetAccountingError("Provider returned without an invocation artifact.")
            return GenerationResult(
                structured_response=dict(response), request_records=invocation.request_records(),
                response_record=invocation.to_dict(), latency_seconds=invocation.latency_seconds,
                repair_calls=invocation.repair_calls, api_call_completed=True,
            )
        except LiveProviderError as error:
            provider_error = error
            invocation = error.artifact
            return GenerationResult(
                structured_response=None, request_records=invocation.request_records(),
                response_record=invocation.to_dict(), latency_seconds=invocation.latency_seconds,
                repair_calls=invocation.repair_calls, api_call_completed=False, error=str(error),
            )
        finally:
            invocation = self.last_invocation
            records = self.token_check_records
            local_denial = (
                provider_error is not None
                and type(provider_error.__cause__) is TokenBudgetGuardDenied
                and bool(records) and records[-1]["passed"] is False
                and invocation is not None
                and invocation.generation_calls + invocation.repair_calls == len(records) - 1
            )
            self._diagnostics = {
                "local_guard_denial": local_denial,
                "denied_call_kind": records[-1]["call_kind"] if local_denial else None,
                "token_check_count": len(records),
                "invocation_available": invocation is not None,
                "generation_calls": invocation.generation_calls if invocation else None,
                "repair_calls": invocation.repair_calls if invocation else None,
                "provider_failure_category": (
                    invocation.failure_category.value
                    if invocation and invocation.failure_category is not None else None
                ),
                "journal_failed_before_send": (
                    self._guard.journal_failed or self._transport.failure_phase == "transport_attempt"
                ),
                "journal_failure_phase": (
                    "token_check" if self._guard.journal_failed else self._transport.failure_phase
                ),
            }
            # A failed pre-send journal write must propagate. Do not attempt a
            # second write to the failed journal or manufacture zero-call success.
            if not self._guard.journal_failed and self._transport.failure_phase is None:
                if invocation is not None:
                    self._journal.append({
                        "event": "provider_invocation", "question_id": self._question_id,
                        "invocation": invocation.to_dict(),
                        "request_records": list(invocation.request_records()),
                    })
                self._journal.append({
                    "event": "guard_diagnostics", "question_id": self._question_id,
                    "diagnostics": self.guard_diagnostics,
                })
