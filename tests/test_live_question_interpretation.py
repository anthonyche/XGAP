"""Controlled HTTP replies test the real adapter, never claim model quality."""

from copy import deepcopy
from dataclasses import replace
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

import pytest

from test_question_interpretation import CASES, question_run
from xgap.experiments.toy_binding import interpretation_inputs
from xgap.experiments.toy_live_interpretation import (MODEL, qwen_toy_config,
    toy_model_requests, run_toy_model_requests)
from xgap.llm.interpretation import OpenAICompatibleInterpretationProvider
from xgap.llm.openai_compatible import ProviderTransportError, LiveFailureCategory
from xgap.llm.token_budget import ChatTokenBudgetGuard
from xgap.semantic.interpretation import interpret_question
from xgap.semantic.interpretation_replay import RecordingInterpretationProvider, ReplayInterpretationProvider


class Counter:
    identity = {"kind": "controlled-tokenizer-test-double"}
    def count_payload_tokens(self, payload):
        return 100


class Transport:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []
    def post_json(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.raw, Exception):
            raise self.raw
        return deepcopy(self.raw)


def response(case=CASES[0]):
    request, template = interpretation_inputs(case)
    return {"id": "controlled-response", "model": MODEL,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(template.interpret(request).payload)}}]}


def provider(raw, *, config=None, counter=None):
    default, prompt = qwen_toy_config()
    guard = ChatTokenBudgetGuard(counter or Counter(), input_limit=8192,
        output_limit=4096, context_limit=12288, expected_model=MODEL)
    return OpenAICompatibleInterpretationProvider(config or default, prompt, guard, Transport(raw))


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("XGAP_LLM_API_KEY", "controlled-private-test-key")


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["id"])
def test_adapter_runs_question_through_real_planner_and_tiny_rdf(case):
    model = provider(response(case))
    result, calls = question_run(case, provider=model)
    assert result["success"], result
    assert result["state"]["output"]["planning_run"]["execution"]["value"]["final_rows"] == case["expected_rows"]
    assert result["interpretation_external_calls"] == len(model.transport.calls) == 1
    assert result["input_tokens"] == 100 and result["output_tokens"] == 50
    assert result["interpretation_token_usage_complete"] is True
    assert len(calls) == result["backend_remote_calls"]
    payload = model.transport.calls[0]["payload"]
    assert payload["max_tokens"] == 4096 and payload["chat_template_kwargs"] == {"enable_thinking": False}
    request = json.loads(payload["messages"][1]["content"])
    assert set(request) == {"schema_version", "question", "context", "required_constraints", "max_response_bytes"}
    assert set(request["context"]) == {"query_profile", "runtime"}
    assert "controlled-private-test-key" not in json.dumps(result)


@pytest.mark.parametrize("failure", ["missing_key", "over_budget", "tokenizer_error"])
def test_preflight_failures_dispatch_nothing(monkeypatch, failure):
    class BadCounter(Counter):
        def count_payload_tokens(self, payload):
            if failure == "tokenizer_error":
                raise ValueError("counter unavailable")
            return 9000
    model = provider(response(), counter=BadCounter() if failure != "missing_key" else None)
    if failure == "missing_key":
        monkeypatch.delenv("XGAP_LLM_API_KEY")
    result, calls = question_run(CASES[0], provider=model)
    assert not result["success"]
    assert result["interpretation_external_calls"] == 0
    assert model.transport.calls == calls == []


@pytest.mark.parametrize("failure", ["timeout", "exception", "json", "truncated", "model", "choices",
                                     "nonfinite", "semantic", "hard_constraint", "entity_authority", "oversize"])
def test_observed_failures_keep_cost_and_never_retry(failure):
    raw = response()
    if failure == "timeout": raw = ProviderTransportError(LiveFailureCategory.TIMEOUT, "controlled-private-test-key timeout")
    elif failure == "exception": raw = RuntimeError("controlled-private-test-key internal detail")
    elif failure == "json": raw["choices"][0]["message"]["content"] = "{broken"
    elif failure == "truncated": raw["choices"][0]["finish_reason"] = "length"
    elif failure == "model": raw["model"] = "different-model"
    elif failure == "choices": raw["choices"].append(deepcopy(raw["choices"][0]))
    elif failure == "nonfinite": raw["choices"][0]["message"]["content"] = '{"value": NaN}'
    elif failure == "oversize": raw["choices"][0]["message"]["content"] = "x" * 1_048_577
    else:
        content = json.loads(raw["choices"][0]["message"]["content"])
        if failure == "semantic": content["program"]["operators"][0]["kind"] = "invented"
        if failure == "hard_constraint": content["program"]["operators"][0]["constraints"] = []
        if failure == "entity_authority":
            content["program"]["holes"][0].update(candidates=["a"], is_resolved=True)
        raw["choices"][0]["message"]["content"] = json.dumps(content)
    model = provider(raw)
    result, calls = question_run(CASES[0], provider=model)
    assert not result["success"] and calls == []
    assert result["interpretation_external_calls"] == len(model.transport.calls) == 1
    available = failure not in {"timeout", "exception"}
    assert result["interpretation_token_usage_complete"] is available
    assert result["input_tokens"] == (100 if available else 0)
    assert result["output_tokens"] == (50 if available else 0)
    assert "controlled-private-test-key" not in json.dumps(result)
    if failure not in {"timeout", "exception", "oversize"}:
        assert "raw_provider_response" in result["interpretation"]["provenance"]


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": 50, "total_tokens": 51},
                                  {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 149}])
def test_missing_or_inconsistent_usage_is_unavailable_not_free(usage):
    raw = response()
    raw["usage"] = usage
    result, _ = question_run(CASES[0], provider=provider(raw))
    assert result["success"] and result["interpretation_external_calls"] == 1
    assert result["interpretation_token_usage_complete"] is False
    assert result["interpretation"]["usage_unavailable"] is True


@pytest.mark.parametrize("failure", [False, True])
def test_saved_wire_response_or_failure_replays_with_historical_cost(tmp_path, failure):
    raw = response()
    if failure: raw["choices"][0]["message"]["content"] = "broken"
    model = provider(raw)
    journal = RecordingInterpretationProvider(model)
    request, _ = interpretation_inputs(CASES[0])
    original = interpret_question(request, journal)
    path = tmp_path / "saved.json"
    journal.save(path)
    replay = ReplayInterpretationProvider.from_path(path)
    repeated = interpret_question(request, replay)
    replay.assert_consumed()
    assert repeated["status"] == original["status"]
    assert repeated["external_calls"] == repeated["input_tokens"] == repeated["output_tokens"] == 0
    assert repeated["provenance"]["recorded_usage"]["input_tokens"] == 100
    assert repeated["provenance"]["recorded_provenance"]["raw_provider_response"] == raw
    assert len(model.transport.calls) == 1


def test_tiny_request_batch_stops_on_transport_failure_and_keeps_five_denominator(tmp_path):
    model = provider(ProviderTransportError(LiveFailureCategory.TIMEOUT, "controlled timeout"))
    report = run_toy_model_requests(model, tmp_path / "run")
    assert report["external_calls"] == len(model.transport.calls) == 1
    assert len(report["queries"]) == 5 and not report["success"]
    assert all(q["status"] == "not_attempted_after_provider_failure" for q in report["queries"][1:])
    assert (tmp_path / "run/B01.json").is_file()
    assert all(set(r.context) == {"query_profile", "runtime"} for _, r in toy_model_requests())


def test_loopback_http_uses_actual_transport_and_secret_free_journal(tmp_path):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = json.dumps(response()).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config, prompt = qwen_toy_config()
        config = replace(config, base_url=f"http://127.0.0.1:{server.server_port}/v1")
        model = OpenAICompatibleInterpretationProvider(config, prompt, provider(response()).token_guard)
        result, _ = question_run(CASES[0], provider=model)
        assert result["success"] and len(received) == 1
        assert received[0][0] == "/v1/chat/completions"
        assert model.last_invocation["request_payload"] == received[0][1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
