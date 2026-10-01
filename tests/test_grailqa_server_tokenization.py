from copy import deepcopy
import io
import json
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from xgap.experiments import grailqa_server_tokenization as module
from xgap.experiments.grailqa_guarded_provider import CredentialPersistenceError, QueryEventJournal
from xgap.experiments.hashing import content_hash
from xgap.llm.token_budget import ChatTokenBudgetGuard, TokenizerUnavailable
from xgap.llm.token_budget_provider import TokenBudgetAccountingError, TokenBudgetProviderStateError


PAYLOAD = {
    "model": "Qwen/Qwen3-32B",
    "messages": [{"role": "system", "content": "Frozen text."}, {"role": "user", "content": "Question."}],
    "chat_template_kwargs": {"enable_thinking": False},
    "response_format": {"type": "json_schema", "json_schema": {"name": "test", "schema": {"type": "object"}}},
    "temperature": 0.0, "top_p": 1.0, "max_tokens": 4096,
}
SECRET = 'test-secret-quote-"-value'


class Counter:
    def __init__(self):
        self.identity = {"identity_sha256": "synthetic-identity", "remote_serving_parity_verified": False}
        self.ids = (8, 9, 10)

    def count_payload_tokens(self, payload):
        return len(self.ids)

    def payload_token_ids(self, payload):
        return self.ids


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(**kwargs)
        return response


def _response(**overrides):
    return {"tokens": [8, 9, 10], "count": 3, "max_model_len": 12288, **overrides}


@pytest.fixture
def case(tmp_path):
    counter = Counter()
    local = ChatTokenBudgetGuard(counter, input_limit=8192, output_limit=4096, context_limit=12288, expected_model=PAYLOAD["model"])
    journal = QueryEventJournal(tmp_path / "events.jsonl")
    transport = Transport([_response(), _response()])
    options = dict(base_url="http://127.0.0.1:8000/v1", api_key=SECRET, timeout_seconds=5.0, context_limit=12288)
    guard = module.ServerTokenizationGuard(local, counter, journal, "q1", transport=transport, **options)
    result = SimpleNamespace(counter=counter, local=local, journal=journal, transport=transport, guard=guard, options=options, payload=deepcopy(PAYLOAD))
    yield result
    journal.close()


def _events(case):
    return [json.loads(line) for line in case.journal.path.read_text().splitlines()]


def test_match_preserves_local_check_and_exact_projection(case):
    before = deepcopy(case.payload)
    local = case.local.check(case.payload, call_kind="generation")
    result = case.guard.check(case.payload, call_kind="generation")
    assert result == local
    assert case.payload == before
    request = case.transport.calls[0]
    assert request["url"] == "http://127.0.0.1:8000/tokenize"
    assert request["timeout_seconds"] == 5.0
    assert request["payload"] == {
        "model": PAYLOAD["model"], "messages": PAYLOAD["messages"],
        "chat_template_kwargs": {"enable_thinking": False},
        "add_generation_prompt": True, "continue_final_message": False,
        "add_special_tokens": False, "return_token_strs": False,
    }
    events = _events(case)
    assert [row["event"] for row in events] == ["tokenizer_probe_attempt", "tokenizer_probe_result"]
    assert events[1]["matched"] is True
    assert events[1]["payload_sha256"] == content_hash(PAYLOAD)
    assert events[1]["local_token_ids_sha256"] == events[1]["server_token_ids_sha256"] == content_hash([8, 9, 10])
    assert case.guard.diagnostics["tokenizer_probe_attempted_calls"] == 1
    assert case.guard.diagnostics["tokenizer_probe_completed_results"] == 1
    assert case.guard.diagnostics["remote_serving_parity_verified"] is False
    assert case.guard.diagnostics["preprocessing_equality_scope"] == module.EQUALITY_SCOPE
    for forbidden in (SECRET, "Frozen text.", "Question.", '"tokens":', '"messages":'):
        assert forbidden not in case.journal.path.read_text()
    copy = case.guard.diagnostics
    copy["tokenizer_probe_receipts"].clear()
    assert len(case.guard.diagnostics["tokenizer_probe_receipts"]) == 1


@pytest.mark.parametrize("response,reason", [
    (_response(tokens=[8, 11, 10]), "ids_mismatch"),
    (_response(tokens=[8, 9], count=2), "ids_mismatch"),
    (_response(count=4), "invalid_response"),
    (_response(count=True), "invalid_response"),
    (_response(count="3"), "invalid_response"),
    (_response(tokens=[8, True, 10]), "invalid_response"),
    (_response(tokens=[8, -1, 10]), "invalid_response"),
    (_response(tokens=[8, 9.0, 10]), "invalid_response"),
    (_response(tokens=[]), "invalid_response"),
    (_response(tokens=(8, 9, 10)), "invalid_response"),
    (_response(max_model_len=True), "invalid_response"),
    (_response(max_model_len=0), "invalid_response"),
    (_response(max_model_len=16384), "context_mismatch"),
    (_response(token_strs=["do not persist"]), "invalid_response"),
    (_response(extra="do not persist"), "invalid_response"),
    ({}, "invalid_response"),
    ([], "invalid_response"),
])
def test_invalid_server_responses_deny_without_retry(case, response, reason):
    case.transport.responses = [response]
    result = case.guard.check(case.payload, call_kind="generation")
    assert result["passed"] is False
    assert result["reason"] == "server_tokenization_" + reason
    assert len(case.transport.calls) == 1
    assert case.guard.diagnostics["tokenizer_probe_completed_results"] == 1
    assert _events(case)[1]["matched"] is False
    assert "do not persist" not in case.journal.path.read_text()
    with pytest.raises(TokenBudgetProviderStateError):
        case.guard.check(case.payload, call_kind="generation")


@pytest.mark.parametrize("reason", ["transport_unavailable", "http_error", "redirect_refused", "invalid_response"])
def test_endpoint_error_is_charged_separately_without_retry(case, reason):
    case.transport.responses = [module.ServerTokenizationEndpointError(reason)]
    result = case.guard.check(case.payload, call_kind="generation")
    assert result["reason"] == "server_tokenization_" + reason
    assert result["passed"] is False
    diagnostic = case.guard.diagnostics
    assert diagnostic["tokenizer_probe_attempted_calls"] == 1
    assert diagnostic["tokenizer_probe_completed_results"] == 0
    assert diagnostic["tokenizer_probe_error_count"] == 1
    assert diagnostic["tokenizer_probe_latency_seconds"] >= 0
    assert [row["event"] for row in _events(case)] == ["tokenizer_probe_attempt", "tokenizer_probe_error"]


def test_local_over_budget_does_not_contact_server(case):
    case.counter.ids = (8,) * 8193
    local = case.local.check(case.payload, call_kind="generation")
    result = case.guard.check(case.payload, call_kind="generation")
    assert result == local
    assert result["reason"] == "input_budget_exceeded"
    assert case.transport.calls == [] and _events(case) == []
    assert case.guard.diagnostics["tokenizer_probe_attempted_calls"] == 0


def test_actual_repair_payload_gets_second_probe_and_no_third_probe(case):
    assert case.guard.check(case.payload, call_kind="generation")["passed"]
    repaired = deepcopy(case.payload)
    repaired["messages"].extend([{"role": "assistant", "content": "invalid response"}, {"role": "user", "content": "Repair syntax only."}])
    assert case.guard.check(repaired, call_kind="repair")["passed"]
    assert case.transport.calls[1]["payload"]["messages"] == repaired["messages"]
    assert case.guard.diagnostics["tokenizer_probe_attempted_calls"] == 2
    assert _events(case)[3]["call_kind"] == "repair"
    with pytest.raises(TokenBudgetProviderStateError):
        case.guard.check(repaired, call_kind="repair")
    assert len(case.transport.calls) == 2


def test_local_repair_refusal_keeps_first_probe_only(case):
    case.guard.check(case.payload, call_kind="generation")
    case.counter.ids = (8,) * 8193
    assert case.guard.check(case.payload, call_kind="repair")["reason"] == "input_budget_exceeded"
    assert len(case.transport.calls) == 1


def test_explicit_one_call_bound_denies_second_probe(case):
    guard = module.ServerTokenizationGuard(case.local, case.counter, case.journal, "q1", maximum_calls=1, transport=case.transport, **case.options)
    guard.check(case.payload, call_kind="generation")
    assert guard.check(case.payload, call_kind="repair")["reason"] == "server_tokenization_call_budget_exhausted"
    assert len(case.transport.calls) == 1


@pytest.mark.parametrize("phase", ["tokenizer_probe_attempt", "tokenizer_probe_result", "tokenizer_probe_error"])
def test_journal_failure_is_fatal_not_endpoint_unavailable(case, monkeypatch, phase):
    if phase == "tokenizer_probe_error":
        case.transport.responses = [module.ServerTokenizationEndpointError()]
    append = case.journal.append
    def failing(event):
        if event["event"] == phase:
            raise OSError("Synthetic evidence persistence failure.")
        append(event)
    monkeypatch.setattr(case.journal, "append", failing)
    with pytest.raises(OSError):
        case.guard.check(case.payload, call_kind="generation")
    assert case.guard.journal_failed is True
    assert case.guard.journal_failure_phase == phase
    assert case.guard.diagnostics["tokenizer_probe_completed_results"] == 0
    assert case.guard.diagnostics["tokenizer_probe_error_count"] == 0
    expected = int(phase != "tokenizer_probe_attempt")
    assert case.guard.diagnostics["tokenizer_probe_attempted_calls"] == len(case.transport.calls) == expected
    with pytest.raises(TokenBudgetProviderStateError):
        case.guard.check(case.payload, call_kind="repair")


@pytest.mark.parametrize("change", ["ids", "identity", "raise", "payload"])
def test_local_remeasurement_defect_fails_closed_before_probe(case, monkeypatch, change):
    def changed(payload):
        if change == "identity":
            case.counter.identity = {"different": True}
        elif change == "raise":
            raise TokenizerUnavailable("Unstable tokenizer.")
        elif change == "payload":
            payload["temperature"] = 0.5
        return (8, 9) if change == "ids" else (8, 9, 10)
    monkeypatch.setattr(case.counter, "payload_token_ids", changed)
    if change == "payload":
        with pytest.raises(TokenBudgetAccountingError):
            case.guard.check(case.payload, call_kind="generation")
    else:
        result = case.guard.check(case.payload, call_kind="generation")
        assert result["passed"] is False
    assert case.transport.calls == [] and _events(case) == []


def test_identity_drift_during_probe_denies_inference(case):
    def change(**kwargs):
        case.counter.identity = {"different": True}
        return _response()
    case.transport.responses = [change]
    result = case.guard.check(case.payload, call_kind="generation")
    assert result["reason"] == "server_tokenization_local_identity_mismatch"
    assert _events(case)[1]["matched"] is False


@pytest.mark.parametrize("change", ["ids", "unavailable"])
def test_cached_identity_cannot_hide_tokenizer_change_during_probe(case, monkeypatch, change):
    identity = deepcopy(case.counter.identity)
    def mutate(**kwargs):
        if change == "ids":
            case.counter.ids = (8, 11, 10)
        else:
            def unavailable(payload):
                raise TokenizerUnavailable("Tokenizer files changed while awaiting server.")
            monkeypatch.setattr(case.counter, "payload_token_ids", unavailable)
        return _response()
    case.transport.responses = [mutate]
    result = case.guard.check(case.payload, call_kind="generation")
    assert case.counter.identity == identity
    assert result["passed"] is False
    assert len(case.transport.calls) == 1
    assert _events(case)[1]["matched"] is False


def test_public_local_placeholder_is_not_a_secret_on_exact_loopback(case):
    case.counter.identity = {"schema_version": "xgap-local-chat-tokenizer-identity-v1"}
    local = ChatTokenBudgetGuard(case.counter, input_limit=8192, output_limit=4096, context_limit=12288, expected_model=PAYLOAD["model"])
    case.payload["messages"][1]["content"] = "Use the local catalog."
    guard = module.ServerTokenizationGuard(local, case.counter, case.journal, "local-q1", transport=case.transport, **{**case.options, "api_key": "local"})
    assert guard.check(case.payload, call_kind="generation")["passed"] is True
    assert case.transport.calls[0]["api_key"] == "local"


@pytest.mark.parametrize("location", ["content", "nested_key"])
def test_known_credentials_refused_before_probe_and_not_persisted(case, location):
    if location == "content":
        case.payload["messages"][1]["content"] = SECRET
    else:
        case.payload["response_format"][SECRET] = "value"
    with pytest.raises(CredentialPersistenceError):
        case.guard.check(case.payload, call_kind="generation")
    assert case.transport.calls == [] and _events(case) == []


def test_response_credential_echo_rejected_without_raw_body(case):
    case.transport.responses = [_response(extra={SECRET: "unsafe"})]
    result = case.guard.check(case.payload, call_kind="generation")
    assert result["reason"] == "server_tokenization_credential_echo_rejected"
    assert SECRET not in case.journal.path.read_text()
    assert _events(case)[1]["server_token_ids_sha256"] is None


@pytest.mark.parametrize("kind", ["repair", "invalid"])
def test_wrong_initial_call_kind_sends_nothing(case, kind):
    with pytest.raises(TokenBudgetProviderStateError):
        case.guard.check(case.payload, call_kind=kind)
    assert case.transport.calls == []


def test_reentrant_call_is_fatal_and_not_retried(case):
    def reenter(**kwargs):
        return case.guard.check(case.payload, call_kind="repair")
    case.transport.responses = [reenter]
    with pytest.raises(TokenBudgetProviderStateError):
        case.guard.check(case.payload, call_kind="generation")
    assert len(case.transport.calls) == 1
    assert case.guard.diagnostics["tokenizer_probe_completed_results"] == 0


@pytest.mark.parametrize("kwargs", [
    {"base_url": "https://127.0.0.1:8000/v1"},
    {"base_url": "http://localhost:8000/v1"},
    {"base_url": "http://127.0.0.1:8000/v1?x=1"},
    {"base_url": "http://127.0.0.1:8000/v1#x"},
    {"base_url": "http://user@127.0.0.1:8000/v1"},
    {"base_url": "http://127.0.0.1:8000/other"},
    {"base_url": "http://10.0.0.1:8000/v1"},
    {"base_url": "http://127.0.0.1/v1"},
    {"base_url": "http://127.0.0.1:99999/v1"},
    {"timeout_seconds": 0}, {"timeout_seconds": float("inf")}, {"timeout_seconds": True},
    {"context_limit": True}, {"context_limit": 0}, {"maximum_calls": 3}, {"maximum_calls": True},
])
def test_invalid_configuration_never_constructs_a_remote_attempt(case, kwargs):
    with pytest.raises(ValueError):
        module.ServerTokenizationGuard(case.local, case.counter, case.journal, "q1", **{**case.options, **kwargs})


class HTTPResponse(io.BytesIO):
    status = 200
    def geturl(self):
        return "http://127.0.0.1:8000/tokenize"


def test_http_transport_disables_environment_proxies_and_redirects(monkeypatch):
    captured = {}
    def build(*handlers):
        captured["handlers"] = handlers
        def open_request(request, timeout):
            captured.update(request=request, timeout=timeout)
            return HTTPResponse(json.dumps(_response()).encode())
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(module.urllib.request, "build_opener", build)
    result = module.LoopbackTokenizationTransport().post_json(url="http://127.0.0.1:8000/tokenize", api_key=SECRET, payload=module._projection(PAYLOAD), timeout_seconds=5)
    assert result == _response()
    assert captured["handlers"][0].proxies == {}
    assert isinstance(captured["handlers"][1], module._NoRedirect)
    assert captured["request"].get_method() == "POST"
    assert captured["timeout"] == 5
    with pytest.raises(module.ServerTokenizationEndpointError) as error:
        captured["handlers"][1].redirect_request(None, None, 302, "unsafe", {}, "http://remote/secret")
    assert error.value.reason == "redirect_refused"
    assert "unsafe" not in str(error.value) and "remote" not in str(error.value)


@pytest.mark.parametrize("behavior", ["http_error", "url_error", "malformed", "array", "oversized", "different_url"])
def test_http_transport_errors_are_safe_and_single_attempt(monkeypatch, behavior):
    calls = []
    def open_request(request, timeout):
        calls.append(request)
        if behavior == "http_error":
            raise urllib.error.HTTPError(request.full_url, 400, SECRET, {}, io.BytesIO(SECRET.encode()))
        if behavior == "url_error":
            raise urllib.error.URLError(SECRET)
        body = b"[]" if behavior == "array" else b"invalid"
        if behavior == "oversized":
            body = b"x" * (module._MAX_RESPONSE_BYTES + 1)
        response = HTTPResponse(body)
        if behavior == "different_url":
            response.geturl = lambda: "http://remote/"
        return response
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=open_request))
    with pytest.raises(module.ServerTokenizationEndpointError) as error:
        module.LoopbackTokenizationTransport().post_json(url="http://127.0.0.1:8000/tokenize", api_key=SECRET, payload=module._projection(PAYLOAD), timeout_seconds=5)
    assert len(calls) == 1
    assert SECRET not in str(error.value)
