"""Offline connection-boundary tests; no opener reaches a real endpoint."""

from copy import deepcopy
from dataclasses import replace
import http.client
import io
import json
from pathlib import Path
import runpy
import socket
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

import xgap.experiments.grailqa_loopback_inference as boundary
from xgap.experiments.grailqa_guarded_provider import CredentialPersistenceError
from xgap.llm.openai_compatible import (
    LiveFailureCategory, LiveProviderError,
    OpenAICompatibleStructuredCandidateProvider, ProviderTransportError,
)


URL = "http://127.0.0.1:8000/v1/chat/completions"
KEY = "synthetic-private-credential"
PAYLOAD = {"model": "Synthetic", "messages": [{"role": "user", "content": "local text"}], "max_tokens": 4096}
FIXTURES = runpy.run_path(str(Path(__file__).resolve().parent / "test_m12b_provider.py"))


class Response(io.BytesIO):
    def __init__(self, body=b'{"id":"synthetic"}', *, url=URL, status=200):
        super().__init__(body)
        self.url, self.status = url, status
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


def _install(monkeypatch, responses):
    state = SimpleNamespace(handlers=[], calls=[], responses=list(responses))
    def open_(request, *, timeout):
        state.calls.append((request, timeout))
        response = state.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(request)
        return response
    def build(*handlers):
        state.handlers.append(handlers)
        return SimpleNamespace(open=open_)
    monkeypatch.setattr(boundary.urllib.request, "build_opener", build)
    monkeypatch.setattr(boundary.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("Legacy urlopen must not run."))
    return state


def _post(**overrides):
    kwargs = {"url": URL, "api_key": KEY, "payload": deepcopy(PAYLOAD), "timeout_seconds": 60.0}
    kwargs.update(overrides)
    return boundary.LoopbackInferenceTransport().post_json(**kwargs)


def test_exact_payload_headers_no_proxy_and_bounded_single_read(monkeypatch):
    expected = {"id": "synthetic", "choices": [{"message": {"content": "unchanged"}}]}
    response = Response(json.dumps(expected).encode())
    state = _install(monkeypatch, [response])
    payload = deepcopy(PAYLOAD)
    assert _post(payload=payload) == expected
    assert payload == PAYLOAD
    assert len(state.calls) == 1
    request, timeout = state.calls[0]
    assert request.full_url == URL and request.method == "POST"
    assert request.get_header("Authorization") == "Bearer " + KEY
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == PAYLOAD and timeout == 60.0
    handlers = state.handlers[0]
    assert isinstance(handlers[0], urllib.request.ProxyHandler) and handlers[0].proxies == {}
    assert isinstance(handlers[1], boundary._NoRedirect)
    assert response.read_sizes == [8 * 1024 * 1024 + 1]


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8000/v1/chat/completions", "http://localhost:8000/v1/chat/completions",
    "http://127.0.0.2:8000/v1/chat/completions", "http://127.0.0.1/v1/chat/completions",
    URL + "/", URL + "?x=1", URL + "#fragment", " " + URL, URL + "\n",
    URL.replace(":8000", ":08000"), URL.replace(":8000", ":0"), URL.replace(":8000", ":65536"),
    URL.replace("127.0.0.1", "user@127.0.0.1"), URL.replace("chat/", "chat%2f"),
    URL.replace("http", "HTTP"), "http://[::1]:8000/v1/chat/completions", None, 42,
])
def test_invalid_endpoint_is_rejected_before_opener(monkeypatch, url):
    state = _install(monkeypatch, [])
    with pytest.raises(ValueError, match="numeric-loopback"):
        _post(url=url)
    assert not state.calls and not state.handlers


@pytest.mark.parametrize("timeout", [0, -1, True, None, "60", float("inf"), float("nan")])
def test_timeout_must_be_finite_positive_before_send(monkeypatch, timeout):
    state = _install(monkeypatch, [])
    with pytest.raises(ValueError, match="timeout"):
        _post(timeout_seconds=timeout)
    assert not state.calls and not state.handlers


@pytest.mark.parametrize("key", ["", None, "a\r\nb", "a\x00b", "密钥"])
def test_invalid_header_credential_rejected_before_send(monkeypatch, key):
    state = _install(monkeypatch, [])
    with pytest.raises(ValueError, match="credential"):
        _post(api_key=key)
    assert not state.calls and not state.handlers


@pytest.mark.parametrize("payload", [[], None, {"x": float("nan")}, {"x": object()}])
def test_invalid_payload_rejected_before_send(monkeypatch, payload):
    state = _install(monkeypatch, [])
    with pytest.raises(ValueError, match="payload"):
        _post(payload=payload)
    assert not state.calls and not state.handlers


@pytest.mark.parametrize("payload", [{"x": KEY}, {KEY: "value"}, {"nested": [{"x": "prefix" + KEY}]}])
def test_current_credential_not_sent_in_payload(monkeypatch, payload):
    state = _install(monkeypatch, [])
    with pytest.raises(CredentialPersistenceError) as caught:
        _post(payload=payload)
    assert KEY not in str(caught.value)
    assert not state.calls and not state.handlers


def test_public_local_placeholder_not_misclassified_as_secret(monkeypatch):
    state = _install(monkeypatch, [Response(b'{"value":"local synthetic response"}')])
    assert _post(api_key="local") == {"value": "local synthetic response"}
    assert state.calls[0][0].get_header("Authorization") == "Bearer local"


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_never_builds_or_forwards_authorization(monkeypatch, code):
    state = None
    def redirect(request):
        handler = state.handlers[0][1]
        return handler.redirect_request(request, None, code, KEY, {}, "https://elsewhere.invalid/?" + KEY)
    state = _install(monkeypatch, [redirect])
    with pytest.raises(ProviderTransportError, match="redirect refused") as caught:
        _post()
    assert caught.value.category == LiveFailureCategory.PROVIDER_ERROR
    assert KEY not in str(caught.value) and len(state.calls) == 1
    assert state.calls[0][0].full_url == URL


@pytest.mark.parametrize("error,category", [
    (TimeoutError(KEY), LiveFailureCategory.TIMEOUT),
    (socket.timeout(KEY), LiveFailureCategory.TIMEOUT),
    (urllib.error.URLError(TimeoutError(KEY)), LiveFailureCategory.TIMEOUT),
    (urllib.error.URLError(KEY), LiveFailureCategory.PROVIDER_ERROR),
    (ConnectionError(KEY), LiveFailureCategory.PROVIDER_ERROR),
    (http.client.IncompleteRead(KEY.encode()), LiveFailureCategory.PROVIDER_ERROR),
])
def test_attempt_errors_have_fixed_safe_category_no_retry(monkeypatch, error, category):
    state = _install(monkeypatch, [error])
    with pytest.raises(ProviderTransportError) as caught:
        _post()
    assert caught.value.category == category
    assert KEY not in str(caught.value) and len(state.calls) == 1


def test_http_error_body_never_read_or_persisted(monkeypatch):
    class Body:
        def read(self, *args):
            pytest.fail("Unsafe error body must not be read.")
        def close(self):
            pass
    state = _install(monkeypatch, [urllib.error.HTTPError(URL, 400, KEY, {}, Body())])
    with pytest.raises(ProviderTransportError, match="HTTP failure") as caught:
        _post()
    assert caught.value.category == LiveFailureCategory.PROVIDER_ERROR
    assert KEY not in str(caught.value) and len(state.calls) == 1


@pytest.mark.parametrize("body", [
    b"not-json", b"\xff", b"[]", b"null", b"42", b'"text"',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'{"x":-1e999}', b'{"x":1,"x":2}',
    b'{"nested":{"x":1,"x":2}}', ('{"x":"' + KEY + '"}').encode(),
])
def test_response_malformed_or_unsafe_is_one_provider_error(monkeypatch, body):
    state = _install(monkeypatch, [Response(body)])
    with pytest.raises(ProviderTransportError, match="response is invalid") as caught:
        _post()
    assert caught.value.category == LiveFailureCategory.PROVIDER_ERROR
    assert KEY not in str(caught.value) and len(state.calls) == 1


def test_oversize_response_is_bounded(monkeypatch):
    monkeypatch.setattr(boundary, "_MAX_RESPONSE_BYTES", 8)
    response = Response(b'{"value":123456789}')
    state = _install(monkeypatch, [response])
    with pytest.raises(ProviderTransportError, match="response is invalid"):
        _post()
    assert response.read_sizes == [9] and len(state.calls) == 1


@pytest.mark.parametrize("response", [Response(url="https://elsewhere.invalid"), Response(status=201), Response(status=500)])
def test_unexpected_response_url_or_status_refused_before_body(monkeypatch, response):
    state = _install(monkeypatch, [response])
    with pytest.raises(ProviderTransportError):
        _post()
    assert not response.read_sizes and len(state.calls) == 1


@pytest.mark.parametrize("response,category", [
    (Response(b"invalid-json"), LiveFailureCategory.PROVIDER_ERROR),
    (TimeoutError(KEY), LiveFailureCategory.TIMEOUT),
    (urllib.error.URLError(KEY), LiveFailureCategory.PROVIDER_ERROR),
    (Response(('{"message":"' + KEY + '"}').encode()), LiveFailureCategory.PROVIDER_ERROR),
])
def test_real_provider_charges_one_transport_failure_without_schema_repair(monkeypatch, response, category):
    monkeypatch.setenv("XGAP_TEST_API_KEY", KEY)
    state = _install(monkeypatch, [response])
    config = replace(FIXTURES["_config"](), base_url="http://127.0.0.1:8000/v1")
    provider = OpenAICompatibleStructuredCandidateProvider(config, "Synthetic instruction.", boundary.LoopbackInferenceTransport())
    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(FIXTURES["_request"]())
    assert caught.value.category == category
    artifact = provider.last_invocation
    assert (artifact.generation_calls, artifact.repair_calls) == (1, 0)
    assert len(artifact.request_records()) == len(state.calls) == 1
    assert artifact.raw_responses == ()
    assert KEY not in json.dumps(artifact.to_dict())


def test_valid_http_envelopes_keep_existing_bounded_schema_repair(monkeypatch):
    monkeypatch.setenv("XGAP_TEST_API_KEY", KEY)
    invalid = FIXTURES["_envelope"]("not-json", request_id="first")
    valid = FIXTURES["_envelope"](json.dumps(FIXTURES["_structured"](FIXTURES["_candidate"]())), request_id="second")
    state = _install(monkeypatch, [Response(json.dumps(invalid).encode()), Response(json.dumps(valid).encode())])
    config = replace(FIXTURES["_config"](), base_url="http://127.0.0.1:8000/v1")
    provider = OpenAICompatibleStructuredCandidateProvider(config, "Synthetic instruction.", boundary.LoopbackInferenceTransport())
    assert len(provider.generate_candidates(FIXTURES["_request"]())["candidates"]) == 1
    artifact = provider.last_invocation
    assert (artifact.generation_calls, artifact.repair_calls) == (1, 1)
    assert len(artifact.request_records()) == len(state.calls) == 2
    assert artifact.raw_responses == (invalid, valid)
