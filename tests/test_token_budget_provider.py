from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from pathlib import Path
import runpy
from threading import Event
from typing import Any, Mapping

import pytest

from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import (
    LiveFailureCategory,
    LiveProviderError,
    OpenAICompatibleStructuredCandidateProvider,
    ProviderTransportError,
    redact_secrets,
)
from xgap.llm.token_budget_provider import (
    TokenBudgetAccountingError,
    TokenBudgetGuardDenied,
    TokenBudgetedCandidateProvider,
    TokenBudgetProviderStateError,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_m12b_provider.py"))


class StubGuard:
    def __init__(self, decisions: list[bool]) -> None:
        self.decisions = list(decisions)
        self.seen: list[dict[str, Any]] = []

    def check(self, payload: Mapping[str, Any], *, call_kind: str) -> dict[str, Any]:
        passed = self.decisions.pop(0)
        self.seen.append({"payload": copy.deepcopy(payload), "call_kind": call_kind})
        return {
            "schema_version": "offline-token-check-v1",
            "call_kind": call_kind,
            "payload_sha256": content_hash(payload),
            "passed": passed,
            "reason": None if passed else "input_budget_exceeded",
            "input_tokens": 50 if passed else 5000,
            "requested_output_tokens": payload["max_tokens"],
            "budgets": {"input": 4096, "output": 2048, "context": 8192},
            "tokenizer_identity": {"source": "offline-test-double"},
        }


class SequencedTransport:
    def __init__(self, responses: list[Mapping[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(copy.deepcopy(kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _valid() -> dict[str, Any]:
    return FIXTURES["_envelope"](
        json.dumps(FIXTURES["_structured"](FIXTURES["_candidate"]())),
        request_id="valid-response",
    )


def _invalid() -> dict[str, Any]:
    return FIXTURES["_envelope"]("not-json", request_id="invalid-response")


def _setup(monkeypatch, decisions, responses, **config_changes):
    monkeypatch.setenv("XGAP_TEST_API_KEY", "offline-test-secret")
    transport = SequencedTransport(responses)
    base = OpenAICompatibleStructuredCandidateProvider(
        replace(FIXTURES["_config"](), **config_changes),
        "Return controlled JSON only.", transport,
    )
    guard = StubGuard(decisions)
    provider = TokenBudgetedCandidateProvider(base, guard)
    return provider, base, guard, transport


def _capture_base_artifacts(monkeypatch, provider):
    artifacts = []
    original = provider._provider._artifact

    def capture(**kwargs):
        artifact = original(**kwargs)
        artifacts.append(artifact)
        return artifact

    monkeypatch.setattr(provider._provider, "_artifact", capture)
    return artifacts


def test_denied_generation_has_zero_external_calls_and_separate_check(monkeypatch) -> None:
    provider, base, guard, transport = _setup(monkeypatch, [False], [])
    artifacts = _capture_base_artifacts(monkeypatch, provider)

    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(FIXTURES["_request"]())

    artifact = caught.value.artifact
    assert type(caught.value.__cause__) is TokenBudgetGuardDenied
    assert caught.value.category is LiveFailureCategory.PROVIDER_ERROR
    assert provider.last_invocation is artifact
    assert provider._provider.last_invocation is artifact
    assert artifact.generation_calls == artifact.repair_calls == 0
    assert artifact.assembled_requests == artifact.request_records() == ()
    assert artifact.raw_responses == artifact.provider_request_ids == ()
    assert artifact.input_tokens is artifact.output_tokens is artifact.total_tokens is None
    assert artifact == replace(artifacts[0], generation_calls=0, assembled_requests=())
    assert transport.calls == []
    assert len(guard.seen) == len(provider.token_check_records) == 1
    assert provider.token_check_records[0]["call_kind"] == "generation"
    assert provider.token_check_records[0]["passed"] is False
    assert base.transport is transport and base.last_invocation is None


def test_denied_repair_keeps_only_attempted_generation_and_preserves_evidence(monkeypatch) -> None:
    invalid = _invalid()
    provider, _, guard, transport = _setup(monkeypatch, [True, False], [invalid])
    artifacts = _capture_base_artifacts(monkeypatch, provider)

    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(FIXTURES["_request"]())

    artifact = caught.value.artifact
    assert provider.last_invocation is caught.value.artifact
    assert artifact.generation_calls == 1
    assert artifact.repair_calls == 0
    assert len(transport.calls) == len(artifact.request_records()) == 1
    assert artifact.raw_responses == (invalid,)
    assert artifact.provider_request_ids == ("invalid-response",)
    assert (artifact.input_tokens, artifact.output_tokens, artifact.total_tokens) == (101, 57, 158)
    assert artifact.assembled_requests == (redact_secrets(transport.calls[0]["payload"]),)
    changed_fields = {
        field.name for field in fields(artifact)
        if getattr(artifact, field.name) != getattr(artifacts[0], field.name)
    }
    assert changed_fields == {"repair_calls", "assembled_requests"}
    assert [record["passed"] for record in provider.token_check_records] == [True, False]
    assert [record["call_kind"] for record in provider.token_check_records] == ["generation", "repair"]
    assert len(guard.seen[1]["payload"]["messages"]) == 4
    assert guard.seen[1]["payload"]["messages"][-2]["content"] == "not-json"
    assert guard.seen[0]["payload"] == transport.calls[0]["payload"]
    assert "tokenizer_identity" not in json.dumps(artifact.request_records())


def test_valid_repair_keeps_two_calls_and_both_payloads_unchanged(monkeypatch) -> None:
    invalid, valid = _invalid(), _valid()
    before = copy.deepcopy([invalid, valid])
    provider, base, guard, transport = _setup(monkeypatch, [True, True], [invalid, valid])
    request = FIXTURES["_request"]()
    expected_generation = base.build_request_payload(request)
    assert provider.provider_id == base.provider_id
    assert provider.build_request_payload(request) == expected_generation
    assert guard.seen == []
    artifacts = _capture_base_artifacts(monkeypatch, provider)

    result = provider.generate_candidates(request)

    assert result == json.loads(valid["choices"][0]["message"]["content"])
    assert [invalid, valid] == before
    artifact = provider.last_invocation
    assert artifact is artifacts[0]
    assert (artifact.generation_calls, artifact.repair_calls) == (1, 1)
    assert len(transport.calls) == len(artifact.request_records()) == 2
    assert transport.calls[0]["payload"] == expected_generation
    assert [item["payload"] for item in guard.seen] == [item["payload"] for item in transport.calls]
    assert artifact.raw_responses == tuple(before)
    assert artifact.provider_request_ids == ("invalid-response", "valid-response")
    assert (artifact.input_tokens, artifact.output_tokens, artifact.total_tokens) == (202, 114, 316)
    assert all(record["passed"] for record in provider.token_check_records)


def test_denial_reconciles_redacted_requests_while_checks_bind_original_payload(monkeypatch) -> None:
    provider, _, _, transport = _setup(
        monkeypatch, [True, False], [_invalid()],
        extra_parameters={"headers": {"Authorization": "offline-payload-secret"}},
    )
    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(FIXTURES["_request"]())

    actual_payload = transport.calls[0]["payload"]
    record = caught.value.artifact.request_records()[0]
    assert actual_payload["headers"] == {"Authorization": "offline-payload-secret"}
    assert record["payload"]["headers"] == "[REDACTED]"
    assert provider.token_check_records[0]["payload_sha256"] == content_hash(actual_payload)
    assert provider.token_check_records[0]["payload_sha256"] != record["payload_hash"]
    assert "offline-payload-secret" not in json.dumps(provider.token_check_records)
    assert "offline-payload-secret" not in json.dumps(caught.value.artifact.request_records())
    assert caught.value.artifact.generation_calls == 1
    assert caught.value.artifact.repair_calls == 0


@pytest.mark.parametrize("during_repair", [False, True])
@pytest.mark.parametrize("error_type", [ProviderTransportError, TokenBudgetGuardDenied])
def test_delegate_failure_is_counted_and_never_reconciled(monkeypatch, during_repair, error_type) -> None:
    # Even an identically typed/message-shaped error originating in the delegate
    # is an attempted transport failure, not this adapter's local refusal.
    failure = error_type(LiveFailureCategory.TIMEOUT, "Token budget check denied generation: fixture.")
    responses = [_invalid(), failure] if during_repair else [failure]
    provider, _, _, transport = _setup(monkeypatch, [True] * len(responses), responses)
    artifacts = _capture_base_artifacts(monkeypatch, provider)

    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(FIXTURES["_request"]())

    assert caught.value.__cause__ is failure
    assert provider.last_invocation is caught.value.artifact is artifacts[0]
    assert caught.value.category is LiveFailureCategory.TIMEOUT
    assert caught.value.artifact.generation_calls == 1
    assert caught.value.artifact.repair_calls == int(during_repair)
    assert len(transport.calls) == len(caught.value.artifact.request_records()) == len(responses)
    assert all(record["passed"] for record in provider.token_check_records)


def test_reuse_resets_checks_attempts_and_prior_invocation(monkeypatch) -> None:
    provider, _, _, transport = _setup(monkeypatch, [False, True, False], [_valid()])
    request = FIXTURES["_request"]()
    with pytest.raises(LiveProviderError):
        provider.generate_candidates(request)
    first_records = provider.token_check_records
    provider.generate_candidates(request)
    assert len(provider.token_check_records) == 1
    assert provider.token_check_records[0]["passed"] is True
    assert len(provider.last_invocation.request_records()) == 1
    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(request)
    assert caught.value.artifact.generation_calls == 0
    assert caught.value.artifact.request_records() == ()
    assert provider.token_check_records == first_records
    assert len(transport.calls) == 1
    returned_records = provider.token_check_records
    returned_records[0]["budgets"]["input"] = -1
    assert provider.token_check_records[0]["budgets"]["input"] == 4096


def test_missing_credentials_make_no_check_or_attempt_after_reuse(monkeypatch) -> None:
    provider, _, guard, transport = _setup(monkeypatch, [True], [_valid()])
    request = FIXTURES["_request"]()
    provider.generate_candidates(request)
    monkeypatch.delenv("XGAP_TEST_API_KEY")

    with pytest.raises(LiveProviderError, match="is unset") as caught:
        provider.generate_candidates(request)

    assert provider.last_invocation is caught.value.artifact
    assert caught.value.artifact.generation_calls == caught.value.artifact.repair_calls == 0
    assert caught.value.artifact.request_records() == provider.token_check_records == ()
    assert len(transport.calls) == len(guard.seen) == 1


@pytest.mark.parametrize("mismatch", ["prefix", "refused_tail", "extra_tail", "generation_count", "repair_count"])
def test_guard_denial_fails_explicitly_when_base_accounting_does_not_match(monkeypatch, mismatch) -> None:
    provider, _, _, transport = _setup(monkeypatch, [True, False], [_invalid()])
    original = provider._provider._artifact

    def corrupt(**kwargs):
        artifact = original(**kwargs)
        payloads = copy.deepcopy(list(artifact.assembled_requests))
        if mismatch == "prefix":
            payloads[0]["max_tokens"] += 1
        elif mismatch == "refused_tail":
            payloads[-1]["max_tokens"] += 1
        elif mismatch == "extra_tail":
            payloads.append(copy.deepcopy(payloads[-1]))
        elif mismatch == "generation_count":
            return replace(artifact, generation_calls=2)
        elif mismatch == "repair_count":
            return replace(artifact, repair_calls=0)
        return replace(artifact, assembled_requests=tuple(payloads))

    monkeypatch.setattr(provider._provider, "_artifact", corrupt)
    with pytest.raises(TokenBudgetAccountingError, match="exact attempted payload prefix"):
        provider.generate_candidates(FIXTURES["_request"]())
    assert provider.last_invocation is None
    assert len(transport.calls) == 1
    assert len(provider.token_check_records) == 2


def test_guard_cannot_mutate_the_transmitted_payload(monkeypatch) -> None:
    provider, base, guard, transport = _setup(monkeypatch, [True], [])
    request = FIXTURES["_request"]()
    expected = base.build_request_payload(request)
    original = guard.check

    def mutate(payload, *, call_kind):
        payload["messages"][0]["content"] = "Unexpected replacement"
        return original(payload, call_kind=call_kind)

    monkeypatch.setattr(guard, "check", mutate)
    with pytest.raises(TokenBudgetAccountingError, match="changed the payload"):
        provider.generate_candidates(request)
    assert transport.calls == []
    assert provider.last_invocation is None
    assert provider.build_request_payload(request) == expected


def test_reentrant_generation_is_rejected_without_resetting_outer_state(monkeypatch) -> None:
    provider, _, guard, transport = _setup(monkeypatch, [True], [_valid()])
    request = FIXTURES["_request"]()
    original = guard.check

    def reenter(payload, *, call_kind):
        with pytest.raises(TokenBudgetProviderStateError, match="reentrant"):
            provider.generate_candidates(request)
        return original(payload, call_kind=call_kind)

    monkeypatch.setattr(guard, "check", reenter)
    provider.generate_candidates(request)
    assert len(transport.calls) == len(provider.token_check_records) == 1
    assert provider.last_invocation.generation_calls == 1


def test_concurrent_generation_is_rejected_without_resetting_active_checks(monkeypatch) -> None:
    provider, _, _, transport = _setup(monkeypatch, [True], [_valid()])
    entered, release = Event(), Event()
    original = transport.post_json

    def block(**kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original(**kwargs)

    monkeypatch.setattr(transport, "post_json", block)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(provider.generate_candidates, FIXTURES["_request"]())
        try:
            assert entered.wait(timeout=5)
            checks = provider.token_check_records
            with pytest.raises(TokenBudgetProviderStateError, match="concurrent"):
                provider.generate_candidates(FIXTURES["_request"]())
            assert provider.token_check_records == checks
        finally:
            release.set()
        future.result(timeout=5)
    assert provider.last_invocation.generation_calls == 1
    assert len(transport.calls) == len(provider.last_invocation.request_records()) == 1
