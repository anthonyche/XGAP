"""External toy binding checks: controlled transports and owned loopback only."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
from types import SimpleNamespace

import pytest

from test_question_interpretation import CASES, question_run
from xgap.experiments import external_toy_interpretation as external
from xgap.experiments.toy_binding import interpretation_inputs
from xgap.experiments.toy_live_interpretation import run_toy_model_requests, toy_model_requests
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError
from xgap.semantic.interpretation import InterpretationRequest, interpret_question
from xgap.semantic.interpretation_replay import RecordingInterpretationProvider, ReplayInterpretationProvider


MODEL = "controlled-served-model/explicit"
KEY_ENV = "XGAP_TEST_EXTERNAL_KEY"
SECRET = "synthetic-external-fixture-key"


@pytest.fixture(autouse=True)
def local_environment(monkeypatch):
    monkeypatch.setenv(KEY_ENV, SECRET)
    # Keep owned-loopback tests independent of the host's external proxy setup.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def _provider(url="http://127.0.0.1:9/v1"):
    return external.load_external_toy_provider(base_url=url, model=MODEL, api_key_env=KEY_ENV)


def _envelope(case, *, usage="known"):
    request, template = interpretation_inputs(case)
    payload = template.interpret(request).payload
    envelope = {"model": MODEL, "choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(payload)}}]}
    if usage != "absent":
        envelope["usage"] = {"prompt_tokens": 11, "completion_tokens": 7,
                             "total_tokens": 18 if usage == "known" else 99}
    return envelope


def _controlled(provider, *, output=None, fail=False, mixed_usage=False):
    calls = []
    by_question = {interpretation_inputs(case)[0].question: case for case in CASES}

    def post_json(**kwargs):
        if output is not None:
            intent = json.loads((output / "result.json").read_text())
            assert intent["run_metadata"]["schema_version"] == external.PROFILE
            assert len(intent["queries"]) == 5
        calls.append(deepcopy(kwargs))
        if fail:
            raise ProviderTransportError(LiveFailureCategory.TIMEOUT, "controlled timeout " + SECRET)
        question = json.loads(kwargs["payload"]["messages"][1]["content"])["question"]
        usage = {2: "absent", 3: "inconsistent"}.get(len(calls), "known") if mixed_usage else "known"
        return _envelope(by_question[question], usage=usage)

    provider.transport = SimpleNamespace(post_json=post_json)
    return calls


@contextmanager
def _loopback(respond):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "body": body,
                             "authorization": self.headers.get("Authorization")})
            status, headers, reply = respond(self.path, body)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def do_GET(self):
            received.append({"path": self.path, "unexpected_redirect_get": True})
            self.send_error(500)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_explicit_configuration_never_inherits_old_qwen_settings(monkeypatch):
    monkeypatch.setenv("XGAP_LLM_MODEL", "Qwen/Qwen3-32B")
    monkeypatch.setenv("XGAP_LLM_BASE_URL", "https://unused.invalid/v1")
    provider = _provider("https://explicit.invalid/v1/")
    assert provider.config.model == MODEL
    assert provider.config.base_url == "https://explicit.invalid/v1"
    assert provider.config.chat_completions_url == "https://explicit.invalid/v1/chat/completions"
    assert provider.config.api_key_env == KEY_ENV
    assert provider.config.max_repair_calls == 0 and provider.config.max_tokens == 4096
    assert provider.config.extra_parameters == {}
    calls = _controlled(provider)
    report = external.external_toy_preflight(provider)
    assert report["success"] and report["external_calls"] == 0 and calls == []
    assert len(report["checks"]) == 5
    assert report["exact_input_tokens_verified"] is report["context_fit_verified"] is False
    assert report["live_endpoint_verified"] is report["checkpoint_identity_verified"] is False


@pytest.mark.parametrize("bad", ["credential-url", "query-url", "empty-model"])
def test_invalid_explicit_configuration_fails_without_an_endpoint_probe(bad):
    options = {"base_url": "https://explicit.invalid/v1", "model": MODEL, "api_key_env": KEY_ENV}
    if bad == "credential-url":
        options["base_url"] = "https://user:secret@explicit.invalid/v1"
    elif bad == "query-url":
        options["base_url"] += "?api_key=not-a-real-key"
    else:
        options["model"] = ""
    with pytest.raises(ValueError):
        external.load_external_toy_provider(**options)


def test_exact_request_byte_boundary_includes_unicode_and_the_full_schema():
    provider = _provider()
    payload = provider.build_request_payload(toy_model_requests()[0][1])
    payload["messages"][1]["content"] += " 中文 🧪"
    payload["response_format"]["json_schema"]["schema"] = deepcopy(provider.config.structured_schema)
    payload["response_format"]["json_schema"]["schema"]["description"] = "完整结构"
    actual = len(json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8"))
    assert actual > len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert actual > len(json.dumps({k: v for k, v in payload.items() if k != "response_format"}).encode())
    passed = external.ExternalChatRequestGuard(MODEL, request_byte_limit=actual).check(payload, call_kind="generation")
    denied = external.ExternalChatRequestGuard(MODEL, request_byte_limit=actual - 1).check(payload, call_kind="generation")
    assert passed["passed"] and passed["request_bytes"] == actual
    assert passed["input_tokens"] is None
    assert not denied["passed"] and denied["reason"] == "request_byte_budget_exceeded"


@pytest.mark.parametrize("violation", ["repair", "output"])
def test_repair_and_output_reservation_are_denied(violation):
    provider = _provider()
    payload = provider.build_request_payload(toy_model_requests()[0][1])
    if violation == "output":
        payload["max_tokens"] = 4097
    check = provider.token_guard.check(payload, call_kind="repair" if violation == "repair" else "generation")
    assert check["passed"] is False
    assert check["reason"] == ("repair_not_permitted" if violation == "repair" else "output_reservation_mismatch")


@pytest.mark.parametrize("limit", [1, 5])
def test_requested_prefix_keeps_five_rows_and_unknown_usage(tmp_path, limit):
    output = tmp_path / "run"
    provider = _provider()
    calls = _controlled(provider, output=output, mixed_usage=True)
    report = external.run_external_toy_requests(provider, output, max_requests=limit)
    assert len(report["queries"]) == 5
    assert [q["query_id"] for q in report["queries"]] == [case["id"] for case in CASES]
    assert report["external_calls"] == len(calls) == limit
    assert report["requested_window_success"] and report["requested_window_replay_size_admitted"]
    assert report["success"] is (limit == 5)
    assert all(q["status"] == "not_attempted_after_request_budget" and "observed_usage" not in q
               for q in report["queries"][limit:])
    usage = report["attempted_usage"]
    assert (usage["known_count"], usage["unknown_count"]) == ((1, 0) if limit == 1 else (3, 2))
    assert usage["input_tokens"] == (11 if limit == 1 else None)
    assert usage["output_tokens"] == (7 if limit == 1 else None)
    assert json.loads((output / "result.json").read_text()) == report
    assert SECRET not in (output / "result.json").read_text()


def test_continuation_window_attempts_b02_through_b05_without_repeating_b01(tmp_path):
    output = tmp_path / "continuation"
    provider = _provider()
    calls = _controlled(provider, output=output)
    report = external.run_external_toy_requests(provider, output, start_index=1, max_requests=4)
    assert len(calls) == report["external_calls"] == 4
    assert len(report["queries"]) == 5 and report["queries"][0]["status"] == "not_attempted_after_request_budget"
    assert report["requested_window_success"] and report["requested_window_replay_size_admitted"]
    assert report["success"] is False
    sent = [json.loads(call["payload"]["messages"][1]["content"])["question"] for call in calls]
    assert sent == [request.question for _, request in toy_model_requests()[1:]]
    assert not (output / "B01.json").exists()
    assert all((output / f"B0{i}.json").is_file() for i in range(2, 6))


@pytest.mark.parametrize("failure", ["transport", "local-byte-budget"])
def test_first_failure_stops_window_without_retry_and_preserves_usage(tmp_path, failure):
    output = tmp_path / "failed"
    provider = _provider()
    calls = _controlled(provider, output=output, fail=True)
    if failure == "local-byte-budget":
        provider.token_guard = external.ExternalChatRequestGuard(MODEL, request_byte_limit=1)
    report = external.run_external_toy_requests(provider, output, max_requests=5)
    assert report["external_calls"] == len(calls) == (1 if failure == "transport" else 0)
    assert not report["requested_window_success"] and not report["success"]
    assert report["automatic_retries"] == 0
    assert all(q["status"] == "not_attempted_after_provider_failure" for q in report["queries"][1:])
    assert report["queries"][0]["interpretation"]["failure_category"] == ("timeout" if failure == "transport" else "token_budget")
    if failure == "transport":
        assert report["attempted_usage"]["unknown_count"] == 1
        assert report["attempted_usage"]["input_tokens"] is None
    recording = (output / "B01.json").read_text()
    assert SECRET not in recording and SECRET not in (output / "result.json").read_text()
    assert "failure" in json.loads(recording)["records"][0]


def test_cli_defaults_to_zero_call_preflight_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY_ENV)
    def forbidden(*args, **kwargs):
        pytest.fail("preflight attempted an HTTP call")
    monkeypatch.setattr(external.BoundedExternalChatTransport, "post_json", forbidden)
    output = tmp_path / "preflight.json"
    assert external.main(["--base-url", "http://127.0.0.1:9/v1", "--model", MODEL,
                          "--api-key-env", KEY_ENV, "--output", str(output)]) == 0
    record = json.loads(output.read_text())
    assert record["external_calls"] == 0 and len(record["checks"]) == 5


def test_cli_execute_requires_the_named_key_before_creating_a_run(tmp_path, monkeypatch):
    monkeypatch.delenv(KEY_ENV)
    def forbidden(*args, **kwargs):
        pytest.fail("missing-key admission attempted HTTP")
    monkeypatch.setattr(external.BoundedExternalChatTransport, "post_json", forbidden)
    output = tmp_path / "not-created"
    with pytest.raises(SystemExit) as error:
        external.main(["--base-url", "http://127.0.0.1:9/v1", "--model", MODEL,
                       "--api-key-env", KEY_ENV, "--output", str(output), "--execute"])
    assert error.value.code == 2 and not output.exists()


def test_loopback_http_reaches_ordinary_p1_rdf_and_replays_without_another_model_call(tmp_path):
    envelope = _envelope(CASES[0])
    envelope["diagnostic"] = SECRET
    with _loopback(lambda path, body: (200, {}, json.dumps(envelope).encode())) as (url, received):
        provider = _provider(url)
        journal = RecordingInterpretationProvider(provider)
        result, backend_calls = question_run(CASES[0], provider=journal)
        assert result["success"], result
        planning = result["state"]["output"]["planning_run"]
        assert planning["execution"]["value"]["final_rows"] == CASES[0]["expected_rows"]
        assert planning["selection"]["algorithm"] in {"independent_source_minimum", "coordinate_two_passes"}
        assert result["backend_remote_calls"] == len(backend_calls) > 0
        assert result["interpretation_external_calls"] == len(received) == 1
        assert received[0]["path"] == "/v1/chat/completions"
        assert received[0]["authorization"] == "Bearer " + SECRET
        assert json.loads(received[0]["body"])["model"] == MODEL
        assert len(received[0]["body"]) == provider.last_invocation["token_budget"]["request_bytes"]
        path = tmp_path / "loopback-recording.json"
        journal.save(path)
        saved = path.read_bytes()
        assert SECRET.encode() not in saved
        raw_request = journal.records[0]["request"]
        request = InterpretationRequest(raw_request["question"], raw_request["context"],
                                        tuple(raw_request["required_constraints"]), raw_request["max_response_bytes"])
        replay = ReplayInterpretationProvider.from_path(path)
        repeated = interpret_question(request, replay)
        replay.assert_consumed()
        assert repeated["success"] and repeated["program"] == result["interpretation"]["program"]
        assert repeated["external_calls"] == 0 and len(received) == 1
        assert repeated["provenance"]["recorded_usage"]["external_calls"] == 1
        assert path.read_bytes() == saved


def test_external_transport_rejects_redirect_without_following_it():
    with _loopback(lambda path, body: (302, {"Location": "/should-not-follow"}, b"redirect")) as (url, received):
        with pytest.raises(ProviderTransportError, match="HTTP 302"):
            external.BoundedExternalChatTransport().post_json(url=url + "/chat/completions",
                api_key=SECRET, payload={"model": MODEL}, timeout_seconds=2)
        assert len(received) == 1 and received[0]["path"] == "/v1/chat/completions"


@pytest.mark.parametrize("failure", ["response-cap", "http-error"])
def test_external_transport_response_failures_are_bounded_and_redacted(failure):
    status, reply = (200, b"x" * (external.RESPONSE_BYTES + 1)) if failure == "response-cap" else (
        503, (SECRET + " " + "x" * 5000).encode())
    with _loopback(lambda path, body: (status, {}, reply)) as (url, received):
        with pytest.raises(ProviderTransportError) as error:
            external.BoundedExternalChatTransport().post_json(url=url + "/chat/completions",
                api_key=SECRET, payload={"model": MODEL}, timeout_seconds=2)
        assert len(received) == 1
        assert SECRET not in str(error.value) and len(str(error.value)) < 1200
        assert ("1 MiB" if failure == "response-cap" else "HTTP 503") in str(error.value)


def test_recording_write_failure_retains_started_entry_and_received_attempt(tmp_path, monkeypatch):
    output = tmp_path / "recording-failure"
    provider = _provider()
    calls = _controlled(provider, output=output)
    actual_send = provider.transport.post_json
    exported = []

    def assert_started(**kwargs):
        before_send = json.loads((output / "result.json").read_text())["queries"][0]
        assert before_send["status"] == "started"
        assert before_send["observed_usage"] == {"external_calls": None, "token_usage_known": False,
                                                  "input_tokens": None, "output_tokens": None}
        return actual_send(**kwargs)

    def fail_export(journal, path):
        received = json.loads((output / "result.json").read_text())["queries"][0]
        assert received["status"] == "interpreted" and received["interpretation"]["success"]
        assert received["observed_usage"] == {"external_calls": 1, "token_usage_known": True,
                                               "input_tokens": 11, "output_tokens": 7}
        exported.append(path)
        raise OSError("controlled replay-export failure " + SECRET)

    provider.transport = SimpleNamespace(post_json=assert_started)
    monkeypatch.setattr(RecordingInterpretationProvider, "save", fail_export)
    report = external.run_external_toy_requests(provider, output, max_requests=5)
    assert report["external_calls"] == len(calls) == len(exported) == 1
    assert report["queries"][0]["status"] == "recording_failed"
    assert report["queries"][0]["interpretation"]["status"] == "interpreted"
    assert report["queries"][0]["recording"]["error_type"] == "OSError"
    assert all(q["status"] == "not_attempted_after_recording_failure" for q in report["queries"][1:])
    assert not report["success"] and not report["requested_window_success"]
    assert not report["requested_window_replay_size_admitted"]
    assert report["attempted_usage"]["input_tokens"] == 11
    assert report["attempted_usage"]["output_tokens"] == 7
    assert report["automatic_retries"] == 0
    persisted = (output / "result.json").read_text()
    assert json.loads(persisted) == report and SECRET not in persisted
