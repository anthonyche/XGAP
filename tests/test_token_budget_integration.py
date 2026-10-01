"""Actual guard/adapter integration with prescribed, payload-bound token counts.

The counts are offline test fixtures, not measurements of the Qwen tokenizer.
No model weights, tokenizer package, service, or network connection is used.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.openai_compatible import LiveProviderError
from xgap.llm.token_budget import ChatTokenBudgetGuard
from xgap.llm.token_budget_provider import TokenBudgetedCandidateProvider


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e2_cwru_vllm.py"))


class PayloadFixtureCounter:
    def __init__(self, counts: Mapping[str, int]) -> None:
        self.counts = dict(counts)
        self.current_identity = {
            "schema_version": "offline-payload-counter-fixture-v1",
            "revision": "fixture-original",
            "remote_serving_parity_verified": False,
        }
        self.seen: list[Mapping[str, Any]] = []

    @property
    def identity(self) -> dict[str, Any]:
        return copy.deepcopy(self.current_identity)

    def count_payload_tokens(self, payload: Mapping[str, Any]) -> int:
        self.seen.append(copy.deepcopy(payload))
        return self.counts[content_hash(payload)]


class OfflineTransport:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.after_response = None

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(copy.deepcopy(kwargs))
        response = self.responses.pop(0)
        if self.after_response is not None:
            self.after_response()
        return response


def _setup(monkeypatch, *, generation_tokens=8192, repair_tokens=None):
    bundle = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_grailqa_contract_v1")
    monkeypatch.setenv(str(bundle.config.api_key_env), "offline-integration-fixture")
    monkeypatch.delenv(str(bundle.config.model_env), raising=False)
    monkeypatch.delenv(str(bundle.config.base_url_env), raising=False)
    good = FIXTURES["_provider_response"]()
    structured = json.loads(good["choices"][0]["message"]["content"])
    pattern = structured["candidates"][0]["pattern_query"]
    del pattern["selector"]
    del pattern["restrictor"]
    good["choices"][0]["message"]["content"] = json.dumps(structured)
    bad = copy.deepcopy(good)
    bad["id"] = "invalid-integration-response"
    bad["choices"][0]["message"]["content"] = "not-json"
    transport = OfflineTransport([good] if repair_tokens is None else [bad, good])
    base = build_openai_compatible_provider(
        bundle, transport, response_parser=parse_normalized_planner_response
    )
    request = FIXTURES["_planner_request"]()
    generation = base.build_request_payload(request)
    payloads = [generation]
    counts = {content_hash(generation): generation_tokens}
    if repair_tokens is not None:
        with pytest.raises(json.JSONDecodeError) as failure:
            json.loads(bad["choices"][0]["message"]["content"])
        repair = base._repair_payload(generation, bad, str(failure.value))
        payloads.append(repair)
        counts[content_hash(repair)] = repair_tokens
    counter = PayloadFixtureCounter(counts)
    guard = ChatTokenBudgetGuard(
        counter, input_limit=8192, output_limit=4096, context_limit=12288,
        expected_model=base.config.model,
    )
    return SimpleNamespace(
        provider=TokenBudgetedCandidateProvider(base, guard), counter=counter,
        transport=transport, request=request, payloads=payloads,
        structured=structured, bad=bad,
    )


@pytest.mark.parametrize("input_tokens", [8192, 8193], ids=["exact-fit", "over-budget"])
def test_actual_guard_and_normalized_provider_accept_fit_or_refuse_before_send(
    monkeypatch, input_tokens,
) -> None:
    case = _setup(monkeypatch, generation_tokens=input_tokens)
    before = copy.deepcopy(case.payloads)
    if input_tokens == 8192:
        assert case.provider.generate_candidates(case.request) == case.structured
        assert "selector" not in case.structured["candidates"][0]["pattern_query"]
        expected_calls = 1
    else:
        with pytest.raises(LiveProviderError) as caught:
            case.provider.generate_candidates(case.request)
        assert case.provider.last_invocation is caught.value.artifact
        expected_calls = 0

    artifact = case.provider.last_invocation
    check, = case.provider.token_check_records
    assert check["schema_version"] == "xgap-chat-token-budget-check-v1"
    assert check["passed"] is (input_tokens == 8192)
    assert check["reason"] == ("within_budget" if expected_calls else "input_budget_exceeded")
    assert check["input_tokens"] == input_tokens
    assert check["requested_output_tokens"] == 4096
    assert check["payload_sha256"] == content_hash(case.payloads[0])
    assert case.counter.seen == case.payloads == before
    assert artifact.generation_calls == expected_calls
    assert artifact.repair_calls == 0
    assert len(case.transport.calls) == len(artifact.request_records()) == expected_calls
    if expected_calls:
        assert case.transport.calls[0]["payload"] == case.payloads[0]


@pytest.mark.parametrize("repair_tokens", [8192, 8193], ids=["repair-fits", "repair-refused"])
def test_actual_repair_growth_is_checked_with_unchanged_output_reservation(
    monkeypatch, repair_tokens,
) -> None:
    case = _setup(monkeypatch, generation_tokens=8191, repair_tokens=repair_tokens)
    before = copy.deepcopy(case.payloads)
    if repair_tokens == 8192:
        assert case.provider.generate_candidates(case.request) == case.structured
        expected_calls = 2
    else:
        with pytest.raises(LiveProviderError) as caught:
            case.provider.generate_candidates(case.request)
        assert case.provider.last_invocation is caught.value.artifact
        expected_calls = 1

    checks = case.provider.token_check_records
    artifact = case.provider.last_invocation
    assert [check["call_kind"] for check in checks] == ["generation", "repair"]
    assert [check["input_tokens"] for check in checks] == [8191, repair_tokens]
    assert all(check["requested_output_tokens"] == 4096 for check in checks)
    assert all(check["budgets"] == {"input": 8192, "output": 4096, "context": 12288} for check in checks)
    assert checks[-1]["reason"] == ("within_budget" if expected_calls == 2 else "input_budget_exceeded")
    assert case.counter.seen == case.payloads == before
    assert [len(payload["messages"]) for payload in case.counter.seen] == [2, 4]
    assert case.payloads[1]["messages"][:2] == case.payloads[0]["messages"]
    assert case.payloads[1]["messages"][-2] == {"role": "assistant", "content": "not-json"}
    assert "Validation error:" in case.payloads[1]["messages"][-1]["content"]
    assert all(payload["max_tokens"] == 4096 for payload in case.payloads)
    assert [check["payload_sha256"] for check in checks] == [content_hash(payload) for payload in case.payloads]
    assert checks[0]["payload_sha256"] != checks[1]["payload_sha256"]
    assert artifact.generation_calls == 1
    assert artifact.repair_calls == expected_calls - 1
    assert len(case.transport.calls) == len(artifact.request_records()) == expected_calls
    assert [record["payload_hash"] for record in artifact.request_records()] == [
        check["payload_sha256"] for check in checks[:expected_calls]
    ]
    assert artifact.raw_responses[0] == case.bad
    assert "tokenizer_identity" not in json.dumps(artifact.request_records())


@pytest.mark.parametrize("before_repair", [False, True], ids=["before-generation", "before-repair"])
def test_tokenizer_identity_drift_refuses_the_next_send(monkeypatch, before_repair) -> None:
    case = _setup(monkeypatch, repair_tokens=8192 if before_repair else None)
    original_identity = case.counter.identity

    def drift():
        case.counter.current_identity["revision"] = "fixture-changed"

    if before_repair:
        case.transport.after_response = drift
    else:
        drift()
    with pytest.raises(LiveProviderError) as caught:
        case.provider.generate_candidates(case.request)

    checks = case.provider.token_check_records
    artifact = caught.value.artifact
    assert case.provider.last_invocation is artifact
    assert len(case.transport.calls) == len(artifact.request_records()) == int(before_repair)
    assert artifact.generation_calls == int(before_repair)
    assert artifact.repair_calls == 0
    assert len(case.counter.seen) == int(before_repair)
    assert len(checks) == 1 + int(before_repair)
    assert checks[-1]["passed"] is False
    assert checks[-1]["reason"] == "tokenization_unavailable"
    assert checks[-1]["input_tokens"] is None
    assert checks[-1]["requested_output_tokens"] == 4096
    assert checks[-1]["tokenizer_identity"] == original_identity
    assert checks[-1]["payload_sha256"] == content_hash(case.payloads[-1])
