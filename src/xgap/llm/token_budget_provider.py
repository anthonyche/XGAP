"""Opt-in token checks at the existing candidate provider's transport boundary."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from threading import Lock
from typing import Any, Literal, Mapping, Protocol

from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import (
    LiveFailureCategory,
    LiveInvocationArtifact,
    LiveProviderError,
    OpenAICompatibleStructuredCandidateProvider,
    OpenAICompatibleTransport,
    ProviderTransportError,
    redact_secrets,
)
from xgap.llm.schemas import PlannerRequest


class TokenBudgetGuard(Protocol):
    def check(
        self, payload: Mapping[str, Any], *, call_kind: Literal["generation", "repair"]
    ) -> dict[str, Any]: ...


class TokenBudgetGuardDenied(ProviderTransportError):
    """A local refusal, handled by the provider without schema repair."""


class TokenBudgetAccountingError(RuntimeError):
    """The guard or invocation evidence cannot establish exact call accounting."""


class TokenBudgetProviderStateError(RuntimeError):
    """An adapter invocation overlaps another invocation or bypasses its owner."""


class _CheckedTransport:
    def __init__(self, delegate: OpenAICompatibleTransport, guard: TokenBudgetGuard):
        self._delegate = delegate
        self._guard = guard
        self.checks: list[dict[str, Any]] = []
        self.attempted_payloads: list[Mapping[str, Any]] = []
        self.refused_payload: Mapping[str, Any] | None = None
        self.denial: TokenBudgetGuardDenied | None = None
        self.active = False

    def begin(self) -> None:
        self.checks.clear()
        self.attempted_payloads.clear()
        self.refused_payload = None
        self.denial = None
        self.active = True

    def post_json(
        self,
        *,
        url: str,
        api_key: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        if not self.active or self.denial is not None or len(self.checks) >= 2:
            raise TokenBudgetProviderStateError("Unexpected token-budget transport invocation.")
        call_kind: Literal["generation", "repair"] = (
            "generation" if not self.checks else "repair"
        )
        checked_payload = copy.deepcopy(dict(payload))
        payload_sha256 = content_hash(checked_payload)
        record = self._guard.check(checked_payload, call_kind=call_kind)
        if checked_payload != payload or content_hash(checked_payload) != payload_sha256:
            raise TokenBudgetAccountingError("Token guard changed the payload it checked.")
        try:
            record = json.loads(json.dumps(record, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise TokenBudgetAccountingError("Token guard record is not JSON-safe.") from error
        if (
            not isinstance(record, dict)
            or record.get("payload_sha256") != payload_sha256
            or record.get("call_kind") != call_kind
            or type(record.get("passed")) is not bool
        ):
            raise TokenBudgetAccountingError("Token guard record does not bind this payload and call.")
        self.checks.append(record)
        safe_payload = redact_secrets(payload)
        if not record["passed"]:
            self.refused_payload = safe_payload
            self.denial = TokenBudgetGuardDenied(
                LiveFailureCategory.PROVIDER_ERROR,
                f"Token budget check denied {call_kind}: {record.get('reason')}.",
            )
            raise self.denial
        # Count the attempt before delegation, including delegates that fail.
        self.attempted_payloads.append(safe_payload)
        return self._delegate.post_json(
            url=url, api_key=api_key, payload=payload, timeout_seconds=timeout_seconds
        )

    def reconcile_denial(self, artifact: LiveInvocationArtifact) -> LiveInvocationArtifact:
        attempted = tuple(self.attempted_payloads)
        attempted_count = len(attempted)
        if (
            self.denial is None
            or self.refused_payload is None
            or attempted_count not in {0, 1}
            or len(self.checks) != attempted_count + 1
            or any(record["passed"] is not True for record in self.checks[:-1])
            or self.checks[-1]["passed"] is not False
            or artifact.assembled_requests != (*attempted, self.refused_payload)
            or artifact.generation_calls != 1
            or artifact.repair_calls != attempted_count
            or artifact.failure_category != self.denial.category
        ):
            raise TokenBudgetAccountingError(
                "Guard denial does not match the exact attempted payload prefix "
                "and one refused trailing payload."
            )
        return replace(
            artifact,
            generation_calls=int(attempted_count > 0),
            repair_calls=0,
            assembled_requests=attempted,
        )


class TokenBudgetedCandidateProvider:
    """Privately wrap a provider without changing its request or response contract.

    The caller's provider is copied so its transport and invocation state remain
    untouched. Token checks are separate from transmitted request evidence.
    Instances support sequential reuse, but reject concurrent or reentrant calls.
    """

    def __init__(
        self,
        provider: OpenAICompatibleStructuredCandidateProvider,
        guard: TokenBudgetGuard,
    ) -> None:
        self._transport = _CheckedTransport(provider.transport, guard)
        self._provider = replace(provider, transport=self._transport)
        self._last_invocation: LiveInvocationArtifact | None = None
        self._invocation_lock = Lock()

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    @property
    def last_invocation(self) -> LiveInvocationArtifact | None:
        return self._last_invocation

    @property
    def token_check_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._transport.checks))

    def build_request_payload(self, request: PlannerRequest) -> dict[str, Any]:
        return self._provider.build_request_payload(request)

    def generate_candidates(self, request: PlannerRequest) -> Mapping[str, Any]:
        if not self._invocation_lock.acquire(blocking=False):
            raise TokenBudgetProviderStateError(
                "Token-budget provider does not support concurrent or reentrant generation."
            )
        try:
            self._last_invocation = None
            self._provider.last_invocation = None
            self._transport.begin()
            try:
                result = self._provider.generate_candidates(request)
            except LiveProviderError as error:
                cause = error.__cause__
                if type(cause) is TokenBudgetGuardDenied and cause is self._transport.denial:
                    artifact = self._transport.reconcile_denial(error.artifact)
                    self._provider.last_invocation = artifact
                    error.artifact = artifact
                self._last_invocation = error.artifact
                raise
            self._last_invocation = self._provider.last_invocation
            return result
        finally:
            self._transport.active = False
            self._invocation_lock.release()
