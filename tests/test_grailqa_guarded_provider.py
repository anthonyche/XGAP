"""Durable guard/provider integration with synthetic envelopes and no network."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

import xgap.experiments.grailqa_guarded_provider as bridge
import xgap.llm.openai_compatible as compatible
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.llm.token_budget_provider import (
    TokenBudgetAccountingError, TokenBudgetGuardDenied, TokenBudgetProviderStateError,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_m12b_provider.py"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _valid() -> dict[str, Any]:
    return FIXTURES["_envelope"](
        json.dumps(FIXTURES["_structured"](FIXTURES["_candidate"]())), request_id="valid-id",
    )


def _invalid() -> dict[str, Any]:
    return FIXTURES["_envelope"]("not-json", request_id="invalid-id")


class Guard:
    def __init__(self, decisions: list[bool]):
        self.decisions = list(decisions)

    def check(self, payload: Mapping[str, Any], *, call_kind: str) -> dict[str, Any]:
        passed = self.decisions.pop(0)
        return {
            "schema_version": "fixture-token-check-v1", "call_kind": call_kind,
            "payload_sha256": content_hash(payload), "passed": passed,
            "reason": "within_budget" if passed else "input_budget_exceeded",
            "input_tokens": 100 if passed else 10000,
            "requested_output_tokens": payload["max_tokens"],
            "budgets": {"input": 8192, "output": 2048, "context": 12288},
            "tokenizer_identity": {"tokenizer_class": "SyntheticOfflineTokenizer"},
        }


class Transport:
    def __init__(self, responses: list[Mapping[str, Any] | Exception], journal_path: Path):
        self.responses = list(responses)
        self.journal_path = journal_path
        self.calls: list[dict[str, Any]] = []

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        # A fresh reader must see the preceding successful receipt before send.
        events = _rows(self.journal_path)
        intent = events[-1]
        assert intent["event"] == "transport_attempt"
        assert intent["pre_send_intent_only"] is True
        assert intent["attempt_index"] == len(self.calls) + 1
        last = events[-2]
        assert last["event"] == "token_check"
        assert last["check"]["passed"] is True
        assert last["check_index"] == len(self.calls) + 1
        assert last["check"]["payload_sha256"] == content_hash(kwargs["payload"])
        self.calls.append(deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _setup(tmp_path, monkeypatch, decisions, responses):
    monkeypatch.setenv("XGAP_TEST_API_KEY", "offline-test-private-credential")
    journal = bridge.QueryEventJournal(tmp_path / "events.jsonl")
    transport = Transport(responses, journal.path)
    base = compatible.OpenAICompatibleStructuredCandidateProvider(
        FIXTURES["_config"](), "Synthetic prompt retained only with invocation.", transport,
        response_parser=parse_normalized_planner_response,
    )
    guard = Guard(decisions)
    provider = bridge.GuardedSemanticPilotProvider(
        SimpleNamespace(), guard, journal, "task-1", base_provider=base,
    )
    return SimpleNamespace(journal=journal, transport=transport, base=base,
                           guard=guard, provider=provider, request=FIXTURES["_request"]())


def _invocation_event(case) -> dict[str, Any]:
    events = _rows(case.journal.path)
    assert events[-1]["event"] == "guard_diagnostics"
    invocation = next(event for event in events if event["event"] == "provider_invocation")
    assert invocation["question_id"] == "task-1"
    assert invocation["invocation"] == case.provider.last_invocation.to_dict()
    assert invocation["request_records"] == list(case.provider.last_invocation.request_records())
    assert events[-1]["diagnostics"] == case.provider.guard_diagnostics
    return invocation


def test_generation_denial_persists_check_and_zero_attempt_invocation(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [False], [])
    result = case.provider.generate(case.request, None)
    assert result.api_call_completed is False
    assert result.request_records == ()
    assert result.response_record["generation_calls"] == result.repair_calls == 0
    assert case.transport.calls == []
    assert case.provider.guard_diagnostics["local_guard_denial"] is True
    assert case.provider.guard_diagnostics["denied_call_kind"] == "generation"
    events = _rows(case.journal.path)
    assert [event["event"] for event in events] == ["token_check", "provider_invocation", "guard_diagnostics"]
    assert events[0]["check_index"] == 1
    assert events[0]["question_id"] == "task-1"
    assert "Synthetic prompt" not in json.dumps(events[0])
    _invocation_event(case)
    case.journal.close()


def test_repair_denial_keeps_first_attempt_response_and_usage(tmp_path, monkeypatch):
    invalid = _invalid()
    before = deepcopy(invalid)
    case = _setup(tmp_path, monkeypatch, [True, False], [invalid])
    result = case.provider.generate(case.request, None)
    assert result.api_call_completed is False
    assert len(case.transport.calls) == len(result.request_records) == 1
    assert result.response_record["generation_calls"] == 1
    assert result.repair_calls == 0
    assert result.response_record["raw_responses"] == [before]
    assert result.response_record["usage"] == {"input_tokens": 101, "output_tokens": 57, "total_tokens": 158}
    assert result.response_record["provider_request_ids"] == ["invalid-id"]
    assert case.provider.guard_diagnostics["local_guard_denial"] is True
    assert case.provider.guard_diagnostics["denied_call_kind"] == "repair"
    checks = [event for event in _rows(case.journal.path) if event["event"] == "token_check"]
    assert [event["check_index"] for event in checks] == [1, 2]
    assert [event["call_kind"] for event in checks] == ["generation", "repair"]
    assert [event["check"]["passed"] for event in checks] == [True, False]
    assert invalid == before
    _invocation_event(case)
    case.journal.close()


def test_normal_repair_keeps_two_attempts_and_does_not_double_count_latency(tmp_path, monkeypatch):
    invalid, valid = _invalid(), _valid()
    case = _setup(tmp_path, monkeypatch, [True, True], [invalid, valid])
    clock = iter([20.0, 20.375])
    monkeypatch.setattr(compatible.time, "perf_counter", lambda: next(clock))
    result = case.provider.generate(case.request, None)
    assert result.api_call_completed is True
    assert len(case.transport.calls) == len(result.request_records) == 2
    assert (result.response_record["generation_calls"], result.repair_calls) == (1, 1)
    assert result.latency_seconds == result.response_record["latency_seconds"] == 0.375
    assert result.latency_seconds == case.provider.last_invocation.latency_seconds
    assert result.response_record["raw_responses"] == [invalid, valid]
    assert result.response_record["usage"] == {"input_tokens": 202, "output_tokens": 114, "total_tokens": 316}
    assert result.structured_response == json.loads(valid["choices"][0]["message"]["content"])
    assert case.provider.guard_diagnostics["local_guard_denial"] is False
    assert case.base.last_invocation is None  # The wrapper preserves its caller's provider.
    _invocation_event(case)
    case.journal.close()


@pytest.mark.parametrize("error_type", [compatible.ProviderTransportError, TokenBudgetGuardDenied])
def test_send_error_remains_one_attempt_not_local_guard_denial(tmp_path, monkeypatch, error_type):
    error = error_type(compatible.LiveFailureCategory.TIMEOUT, "Synthetic remote failure.")
    case = _setup(tmp_path, monkeypatch, [True], [error])
    result = case.provider.generate(case.request, None)
    assert result.api_call_completed is False
    assert len(case.transport.calls) == len(result.request_records) == 1
    assert result.response_record["generation_calls"] == 1
    assert result.repair_calls == 0
    assert case.provider.guard_diagnostics["local_guard_denial"] is False
    assert case.provider.guard_diagnostics["provider_failure_category"] == "timeout"
    _invocation_event(case)
    case.journal.close()


def test_journal_append_failure_before_send_propagates_without_forged_result(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    calls = []
    def fail_append(event):
        calls.append(event)
        raise OSError("Synthetic disk failure.")
    monkeypatch.setattr(case.journal, "append", fail_append)
    with pytest.raises(OSError, match="Synthetic disk failure"):
        case.provider.generate(case.request, None)
    assert len(calls) == 1
    assert case.transport.calls == []
    assert case.provider.last_invocation is None
    assert case.provider.token_check_records == ()
    assert case.provider.guard_diagnostics["generation_calls"] is None
    assert case.provider.guard_diagnostics["journal_failed_before_send"] is True
    assert case.journal.path.read_text() == ""
    case.journal.close()


def test_fsync_failure_before_send_is_fatal_even_when_buffer_was_flushed(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    def fail_fsync(fd):
        raise OSError("Synthetic fsync failure.")
    monkeypatch.setattr(bridge.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="fsync"):
        case.provider.generate(case.request, None)
    assert case.transport.calls == []
    assert case.journal.failed is True
    assert case.provider.last_invocation is None
    with pytest.raises(RuntimeError, match="previous I/O failure"):
        case.journal.append({"state": "not-retried"})
    case.journal.close()


def test_invocation_journal_failure_after_send_is_not_success(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    append = case.journal.append
    def fail_invocation(event):
        if event.get("event") == "provider_invocation":
            raise OSError("Invocation persistence failed.")
        append(event)
    monkeypatch.setattr(case.journal, "append", fail_invocation)
    with pytest.raises(OSError, match="Invocation persistence"):
        case.provider.generate(case.request, None)
    assert len(case.transport.calls) == 1
    assert case.provider.last_invocation.generation_calls == 1
    case.journal.close()


def test_first_response_survives_fatal_repair_check_journal_failure(tmp_path, monkeypatch):
    invalid = _invalid()
    case = _setup(tmp_path, monkeypatch, [True, True], [invalid, _valid()])
    append = case.journal.append
    append_attempts = []
    def fail_repair_check(event):
        append_attempts.append(event["event"])
        if event.get("event") == "token_check" and event["check_index"] == 2:
            raise OSError("Repair receipt cannot be persisted.")
        append(event)
    monkeypatch.setattr(case.journal, "append", fail_repair_check)
    with pytest.raises(OSError, match="Repair receipt"):
        case.provider.generate(case.request, None)
    assert len(case.transport.calls) == 1
    assert case.provider.last_invocation is None
    assert case.provider.guard_diagnostics["generation_calls"] is None
    assert case.provider.guard_diagnostics["repair_calls"] is None
    assert case.provider.guard_diagnostics["journal_failure_phase"] == "token_check"
    events = _rows(case.journal.path)
    assert [event["event"] for event in events] == ["token_check", "transport_attempt", "transport_response"]
    assert events[-1]["raw_response"] == invalid
    assert events[-1]["question_id"] == "task-1"
    assert events[-1]["attempt_index"] == 1
    assert append_attempts == ["token_check", "transport_attempt", "transport_response", "token_check"]
    case.journal.close()


def test_attempt_intent_persistence_failure_prevents_actual_transport(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    append = case.journal.append
    def fail_attempt(event):
        if event.get("event") == "transport_attempt":
            raise OSError("Intent cannot be persisted.")
        append(event)
    monkeypatch.setattr(case.journal, "append", fail_attempt)
    with pytest.raises(OSError, match="Intent cannot"):
        case.provider.generate(case.request, None)
    assert case.transport.calls == []
    assert case.provider.last_invocation is None
    assert case.provider.guard_diagnostics["generation_calls"] is None
    assert case.provider.guard_diagnostics["journal_failed_before_send"] is True
    assert case.provider.guard_diagnostics["journal_failure_phase"] == "transport_attempt"
    assert [event["event"] for event in _rows(case.journal.path)] == ["token_check"]
    case.journal.close()


def test_transport_error_event_contains_type_not_credentials_or_message(tmp_path, monkeypatch):
    error = compatible.ProviderTransportError(
        compatible.LiveFailureCategory.TIMEOUT, "private-error-content offline-test-private-credential",
    )
    case = _setup(tmp_path, monkeypatch, [True], [error])
    case.provider.generate(case.request, None)
    event = next(row for row in _rows(case.journal.path) if row["event"] == "transport_error")
    assert event["error_type"] == "ProviderTransportError"
    assert "private-error-content" not in json.dumps(event)
    assert "offline-test-private-credential" not in json.dumps(event)
    assert "api_key" not in event and "url" not in event
    case.journal.close()


@pytest.mark.parametrize("location", ["question", "nested_key"])
def test_outgoing_known_credential_is_rejected_before_send_or_payload_persistence(tmp_path, monkeypatch, location):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    credential = "offline-test-private-credential"
    if location == "question":
        case.request = replace(case.request, question=f"Synthetic request containing {credential}.")
    else:
        base = replace(case.base, config=replace(
            case.base.config, extra_parameters={"nested": [{credential: "value"}]},
        ))
        case.provider = bridge.GuardedSemanticPilotProvider(
            SimpleNamespace(), case.guard, case.journal, "task-1", base_provider=base,
        )
    with pytest.raises(bridge.CredentialPersistenceError, match="current credential"):
        case.provider.generate(case.request, None)
    assert case.transport.calls == []
    assert case.provider.last_invocation is None
    assert case.provider.guard_diagnostics["generation_calls"] is None
    events = _rows(case.journal.path)
    assert not any(event["event"] in {"transport_attempt", "provider_invocation"} for event in events)
    assert credential not in case.journal.path.read_text()
    case.journal.close()


@pytest.mark.parametrize("location", ["content", "nested_key"])
def test_response_known_credential_echo_is_one_send_no_repair_and_never_persisted(tmp_path, monkeypatch, location):
    credential = "offline-test-private-credential"
    response = _valid()
    if location == "content":
        response["choices"][0]["message"]["content"] = f"Unsafe echo: {credential}"
    else:
        response["nested"] = [{credential: "value"}]
    original = deepcopy(response)
    case = _setup(tmp_path, monkeypatch, [True], [response])
    result = case.provider.generate(case.request, None)
    assert result.api_call_completed is False
    assert len(case.transport.calls) == len(result.request_records) == 1
    assert result.response_record["generation_calls"] == 1
    assert result.repair_calls == 0
    assert result.response_record["raw_responses"] == []
    assert response == original  # Rejection, not a rewritten model response.
    events = _rows(case.journal.path)
    rejection = next(event for event in events if event["event"] == "response_credential_echo_rejected")
    assert set(rejection) == {"event", "question_id", "attempt_index", "payload_sha256"}
    assert rejection["attempt_index"] == 1
    assert not any(event["event"] == "transport_response" for event in events)
    assert credential not in case.journal.path.read_text()
    assert credential not in json.dumps(result.response_record)
    assert case.provider.guard_diagnostics["local_guard_denial"] is False
    assert case.provider.guard_diagnostics["provider_failure_category"] == "provider_error"
    case.journal.close()


def test_post_generation_grounding_error_cannot_erase_provider_journal(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    with pytest.raises(ValueError, match="downstream grounding"):
        result = case.provider.generate(case.request, None)
        assert result.api_call_completed is True
        raise ValueError("Synthetic downstream grounding error.")
    _invocation_event(case)
    assert len(case.transport.calls) == 1
    case.journal.close()


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/tokenize",
    "http://127.0.0.1:8000/v1/chat/completions",
])
def test_public_loopback_placeholder_is_not_a_secret(url):
    assert bridge._credential_value_for_payload_check("local", url) == ""
    assert bridge._credential_value_for_payload_check("real-secret", url) == "real-secret"
    assert bridge._credential_value_for_payload_check("x", url) == "x"


@pytest.mark.parametrize("url", [
    "http://example.test:8000/tokenize", "http://localhost:8000/tokenize",
    "https://127.0.0.1:8000/tokenize", "http://127.0.0.1/tokenize",
    "http://127.0.0.1:8000/other", "http://127.0.0.1:8000/tokenize?key=value",
    "http://127.0.0.1:8000/tokenize#fragment", "http://user@127.0.0.1:8000/tokenize",
    "http://127.0.0.1:invalid/tokenize", "http://127.0.0.1:0/tokenize",
])
def test_placeholder_exception_never_widens_to_other_endpoints(url):
    assert bridge._credential_value_for_payload_check("local", url) == "local"


def test_public_loopback_placeholder_allows_ordinary_local_catalog_text(tmp_path, monkeypatch):
    response = _valid()
    response["id"] = "local-response"
    case = _setup(tmp_path, monkeypatch, [True], [response])
    monkeypatch.setenv("XGAP_TEST_API_KEY", "local")
    base = compatible.OpenAICompatibleStructuredCandidateProvider(
        replace(case.base.config, base_url="http://127.0.0.1:8000/v1"),
        "Use the local catalog.", case.transport,
        response_parser=parse_normalized_planner_response,
    )
    case.provider = bridge.GuardedSemanticPilotProvider(
        SimpleNamespace(), case.guard, case.journal, "task-1", base_provider=base,
    )
    result = case.provider.generate(case.request, None)
    assert result.api_call_completed is True
    assert len(case.transport.calls) == 1
    assert case.transport.calls[0]["api_key"] == "local"
    assert "Use the local catalog." in case.journal.path.read_text()
    assert "local-response" in case.journal.path.read_text()
    _invocation_event(case)
    case.journal.close()


def test_captures_effective_config_and_default_normalized_parser_before_wrapping(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    built = []
    def build(model, *, response_parser):
        built.append((model, response_parser))
        return replace(case.base, response_parser=response_parser)
    monkeypatch.setattr(bridge, "build_openai_compatible_provider", build)
    model = object()
    provider = bridge.GuardedSemanticPilotProvider(model, Guard([True]), case.journal, "task-1")
    assert built == [(model, parse_normalized_planner_response)]
    assert provider.provider_id == case.base.provider_id
    assert provider.model_name == case.base.config.model
    assert provider.effective_config == case.base.config.safe_dict()
    captured = provider.effective_config
    captured["model"] = "changed-copy"
    assert provider.model_name == provider.effective_config["model"] == "fixed-test-model"
    provider.generate(case.request, None)
    assert len(case.transport.calls) == 1
    case.journal.close()


def test_request_binding_and_single_use_reject_before_send(tmp_path, monkeypatch):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    wrong = replace(case.request, metadata={**case.request.metadata, "task_id": "other-query"})
    with pytest.raises(ValueError, match="task ID"):
        case.provider.generate(wrong, None)
    assert case.transport.calls == []
    assert case.journal.path.read_text() == ""
    case.provider.generate(case.request, None)
    before = case.journal.path.read_bytes()
    with pytest.raises(TokenBudgetProviderStateError, match="new provider instance"):
        case.provider.generate(case.request, None)
    assert case.journal.path.read_bytes() == before
    assert len(case.transport.calls) == 1
    case.journal.close()


@pytest.mark.parametrize("unsafe", [{"headers": {"Authorization": "secret"}}, {"prompt_text": "not-a-receipt"}])
def test_unsafe_guard_receipts_are_never_journaled_or_sent(tmp_path, monkeypatch, unsafe):
    case = _setup(tmp_path, monkeypatch, [True], [_valid()])
    check = case.guard.check
    monkeypatch.setattr(case.guard, "check", lambda payload, **kwargs: {**check(payload, **kwargs), **unsafe})
    with pytest.raises(TokenBudgetAccountingError, match="unsafe"):
        case.provider.generate(case.request, None)
    assert case.transport.calls == []
    assert case.provider.token_check_records == ()
    text = case.journal.path.read_text()
    assert "Authorization" not in text
    assert "not-a-receipt" not in text
    assert "offline-test-private-credential" not in text
    case.journal.close()


def test_journal_generic_mapping_is_append_only_flushed_and_fsynced(tmp_path, monkeypatch):
    path = tmp_path / "states.jsonl"
    sizes = []
    real_fsync = os.fsync
    def tracked_fsync(fd):
        sizes.append(os.fstat(fd).st_size)
        real_fsync(fd)
    monkeypatch.setattr(bridge.os, "fsync", tracked_fsync)
    with bridge.QueryEventJournal(path) as journal:
        journal.append({"state": "started", "question_id": "synthetic"})
        first = path.read_bytes()
        journal.append({"state": "finished"})
        assert path.read_bytes().startswith(first)
    assert journal.closed is True
    assert len(sizes) == 2 and 0 < sizes[0] < sizes[1]
    assert _rows(path) == [{"question_id": "synthetic", "state": "started"}, {"state": "finished"}]
    with pytest.raises(RuntimeError, match="closed"):
        journal.append({"state": "later"})


@pytest.mark.parametrize("kind", ["file", "symlink", "broken_symlink"])
def test_journal_exclusive_creation_rejects_existing_or_symlink(tmp_path, kind):
    path = tmp_path / "events.jsonl"
    if kind == "file":
        path.write_text("keep-this", encoding="utf-8")
    else:
        target = tmp_path / "target"
        if kind == "symlink":
            target.write_text("keep-this", encoding="utf-8")
        path.symlink_to(target)
    with pytest.raises(FileExistsError):
        bridge.QueryEventJournal(path)
    if kind == "file":
        assert path.read_text() == "keep-this"
    else:
        assert path.is_symlink()


@pytest.mark.parametrize("bad", [{"bad": {1, 2}}, {"bad": float("nan")}, ["not-a-mapping"]])
def test_non_json_safe_journal_input_does_not_partially_append(tmp_path, bad):
    with bridge.QueryEventJournal(tmp_path / "events.jsonl") as journal:
        with pytest.raises((TypeError, ValueError)):
            journal.append(bad)
        assert journal.path.read_text() == ""
        assert journal.failed is False
