"""The v2 pool uses one existing transport action and retains v1 isolation."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from test_interpretation_candidates import candidate_inputs, pool
from xgap.experiments.hashing import content_hash
from xgap.llm.candidate_interpretation import (
    OpenAICompatibleCandidateInterpretationProvider, candidate_interpretation_schema,
)
from xgap.llm.interpretation import OpenAICompatibleInterpretationProvider
from xgap.llm.openai_compatible import (
    LiveFailureCategory, OpenAICompatibleProviderConfig, ProviderTransportError,
)
from xgap.llm.token_budget import ChatTokenBudgetGuard
from xgap.semantic.interpretation_candidates import SCHEMA, interpret_candidate_question


MODEL = "controlled-candidate-model"
PROMPT = "Return bounded semantic candidates; quality_proxy is uncalibrated or null."


class Counter:
    identity = {"tokenizer": "controlled-tokenizer", "revision": "test-only-v1"}

    def count_payload_tokens(self, payload):
        return 100


class Transport:
    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def post_json(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.raw, Exception):
            raise self.raw
        return deepcopy(self.raw)


def model(raw, *, cap=3, counter=None):
    config = OpenAICompatibleProviderConfig(provider_id="controlled-pool", base_url="http://localhost:1/v1",
        api_key_env="XGAP_CANDIDATE_TEST_KEY", model=MODEL, temperature=0, top_p=1,
        max_tokens=1000, candidate_cap=cap, timeout_seconds=2, structured_output_mode="json_schema",
        structured_schema=candidate_interpretation_schema(cap), prompt_hash=content_hash(PROMPT),
        max_repair_calls=0)
    guard = ChatTokenBudgetGuard(counter or Counter(), input_limit=1000, output_limit=1000,
                                context_limit=2000, expected_model=MODEL)
    return OpenAICompatibleCandidateInterpretationProvider(config, PROMPT, guard, Transport(raw))


def wire(candidates):
    return {"model": MODEL, "usage": {"prompt_tokens": 100, "completion_tokens": 70, "total_tokens": 170},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(candidates)}}]}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("XGAP_CANDIDATE_TEST_KEY", "private-controlled-candidate-key")


def test_one_http_pool_preserves_mode_context_admits_siblings_and_charges_once():
    request, good = candidate_inputs()
    request = replace(request, context={**request.context, "one_shot_profile": {
        "mode": "precision", "candidate_cap": 3}})
    bad = deepcopy(good)
    bad["candidate_id"] = "invalid"
    bad["program"]["operators"][0]["kind"] = "invented"
    provider = model(wire(pool(good, bad, {**deepcopy(good), "candidate_id": "unknown", "quality_proxy": None})))
    report = interpret_candidate_question(request, provider, candidate_cap=3)
    assert report["success"] and report["admitted_count"] == 2
    assert [item["status"] for item in report["candidates"]] == ["admitted", "invalid", "admitted"]
    assert (report["external_calls"], report["input_tokens"], report["output_tokens"]) == (1, 100, 70)
    assert len(provider.transport.calls) == 1
    payload = provider.transport.calls[0]["payload"]
    sent = json.loads(payload["messages"][1]["content"])
    assert sent["schema_version"] == SCHEMA and sent["candidate_cap"] == 3
    assert sent["context"]["one_shot_profile"] == request.context["one_shot_profile"]
    assert payload["response_format"]["json_schema"]["schema"] == candidate_interpretation_schema(3)
    assert "private-controlled-candidate-key" not in json.dumps(report)


def test_preflight_budget_rejects_before_transport_without_changing_v1_contract():
    request, good = candidate_inputs()

    class OverBudget(Counter):
        def count_payload_tokens(self, payload):
            return 1001

    provider = model(wire(pool(good)), counter=OverBudget())
    report = interpret_candidate_question(request, provider, candidate_cap=3)
    assert report["status"] == "provider_failure" and report["failure_category"] == "token_budget"
    assert report["external_calls"] == 0 and not provider.transport.calls
    with pytest.raises(ValueError, match="one candidate"):
        OpenAICompatibleInterpretationProvider(provider.config, PROMPT, provider.token_guard)
    assert candidate_interpretation_schema(1)["properties"]["candidates"]["maxItems"] == 1


def test_http_timeout_retains_one_attempt_unknown_tokens_redaction_and_no_retry():
    request, _ = candidate_inputs()
    provider = model(ProviderTransportError(LiveFailureCategory.TIMEOUT, "private-controlled-candidate-key timeout"))
    report = interpret_candidate_question(request, provider, candidate_cap=3)
    assert report["status"] == "provider_failure" and report["failure_category"] == "timeout"
    assert report["external_calls"] == len(provider.transport.calls) == 1
    assert not report["token_usage_complete"] and report["automatic_retries"] == 0
    assert "private-controlled-candidate-key" not in json.dumps(report)


def test_response_over_cap_remains_an_observed_rejection_and_missing_usage_is_unknown():
    request, good = candidate_inputs()
    raw = wire(pool(good, {**deepcopy(good), "candidate_id": "b"}))
    raw.pop("usage")
    provider = model(raw, cap=1)
    report = interpret_candidate_question(request, provider, candidate_cap=1)
    assert report["status"] == "interpretation_invalid" and report["admitted_count"] == 0
    assert report["raw_response"]["candidates"] == json.loads(raw["choices"][0]["message"]["content"])["candidates"]
    assert report["external_calls"] == len(provider.transport.calls) == 1
    assert not report["token_usage_complete"]
