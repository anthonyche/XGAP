"""Offline strict-mode runner integration; synthetic outcomes are not evidence of quality."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import runpy
from unittest.mock import Mock

import pytest

import xgap.experiments.grailqa_guarded_preflight as runner
from xgap.experiments.grailqa_server_tokenization import (
    EQUALITY_SCOPE,
    ServerTokenizationEndpointError,
    ServerTokenizationGuard,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.live_run import build_openai_compatible_provider


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_grailqa_guarded_preflight.py"))
CWRU = FIXTURES["CWRU_FIXTURES"]
_rows = FIXTURES["_rows"]


def _document(case, filename):
    return json.loads((case.output / filename).read_text(encoding="utf-8"))


@pytest.fixture
def strict_case(monkeypatch, tmp_path):
    # Real temporary model/spec/contract, local guard, server guard, provider,
    # normalized parser and journals. Only catalog/evaluation/infer-loop setup
    # and the two external transports are synthetic.
    case = FIXTURES["case"].__wrapped__(monkeypatch, tmp_path)
    case.kwargs.update(allow_unverified_serving_tokenizer=False, verify_server_tokenization=True)
    case.input_tokens = 100
    case.probe_behavior = "match"
    case.force_repair = False
    case.probe_calls = []
    case.checked_payloads = []
    case.guards = []
    case.results = []

    def count(payload):
        case.checked_payloads.append(copy.deepcopy(payload))
        return case.input_tokens

    case.counter.count_payload_tokens.side_effect = count
    case.counter.payload_token_ids = Mock(side_effect=lambda payload: tuple(range(case.input_tokens)))

    class ProbeTransport:
        def post_json(self, **kwargs):
            events = _rows(case.output / "query_events.jsonl")
            intent = events[-1]
            assert intent["event"] == "tokenizer_probe_attempt"
            assert intent["pre_send_intent_only"] is True
            assert intent["payload_sha256"] == content_hash(case.checked_payloads[-1])
            assert intent["tokenize_payload_sha256"] == content_hash(kwargs["payload"])
            assert kwargs["payload"]["messages"] == case.checked_payloads[-1]["messages"]
            assert kwargs["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
            assert kwargs["payload"]["add_generation_prompt"] is True
            assert kwargs["payload"]["continue_final_message"] is False
            assert kwargs["payload"]["add_special_tokens"] is False
            assert kwargs["url"] == "http://127.0.0.1:8000/tokenize"
            assert kwargs["timeout_seconds"] == runner.TOKENIZER_PROBE_TIMEOUT_SECONDS
            case.probe_calls.append(copy.deepcopy(kwargs))
            if case.probe_behavior == "error":
                raise ServerTokenizationEndpointError("transport_unavailable")
            ids = list(range(case.input_tokens))
            if case.probe_behavior == "mismatch" or (
                case.probe_behavior == "repair-mismatch" and len(case.probe_calls) == 2
            ):
                ids[-1] += 1  # Equal count is insufficient: ordered IDs must match.
            return {"count": len(ids), "max_model_len": 12288, "tokens": ids}

    def make_guard(*args, **kwargs):
        guard = ServerTokenizationGuard(*args, **kwargs, transport=ProbeTransport())
        case.guards.append(guard)
        return guard

    case.guard_factory = Mock(side_effect=make_guard)
    monkeypatch.setattr(runner, "ServerTokenizationGuard", case.guard_factory)

    class ModelTransport:
        def post_json(self, **kwargs):
            # Read from disk during the send, proving the matched probe result
            # and exact token check are durable prerequisites, not end summaries.
            events = _rows(case.output / "query_events.jsonl")
            receipt, check, intent = events[-3:]
            assert [row["event"] for row in (receipt, check, intent)] == [
                "tokenizer_probe_result", "token_check", "transport_attempt",
            ]
            digest = content_hash(kwargs["payload"])
            assert receipt["matched"] is True
            assert receipt["payload_sha256"] == check["check"]["payload_sha256"] == intent["payload_sha256"] == digest
            assert check["check"]["passed"] is True
            assert kwargs["payload"] == case.checked_payloads[-1]
            case.transport_calls.append(copy.deepcopy(kwargs))
            response = CWRU["_provider_response"]()
            if case.force_repair and len(case.transport_calls) == 1:
                response["choices"][0]["message"]["content"] = "not-json"
            return response

    def build_provider(model, *, transport_override, **kwargs):
        # The new runner must select the bounded inference transport, not the
        # legacy urllib default. Replace it only after checking the wiring.
        assert isinstance(transport_override, runner.LoopbackInferenceTransport)
        return build_openai_compatible_provider(model, ModelTransport(), **kwargs)

    case.base_factory.side_effect = build_provider

    def infer(**kwargs):
        question, provider = kwargs["question"], kwargs["provider"]
        index = len(case.inference_order)
        qid = question["question_id"]
        assert qid == case.spec["question_ids"][index]
        assert len(_rows(case.output / "query_states.jsonl")) == index
        assert provider.token_check_records == () and provider.last_invocation is None
        case.inference_order.append(qid)
        case.providers.append(provider)
        result = None
        if index == 0:
            request = CWRU["_planner_request"]()
            request = replace(request, metadata={**request.metadata, "task_id": qid})
            result = provider.generate(request, None)
            case.results.append(result)
        return {
            "question": question, "retrieval": {"question_id": qid, "synthetic": True},
            "request_records": list(result.request_records) if result else [],
            "response_record": result.response_record if result else None,
            "api_call_completed": bool(result and result.api_call_completed),
            "candidates": [], "semantic_scores": [],
            "failure": {"question_id": qid, "category": "synthetic_no_valid_candidate"},
        }

    case.infer.side_effect = infer
    return case


def test_same_length_token_mismatch_denies_inference_and_charges_one_probe(strict_case):
    case = strict_case
    case.probe_behavior = "mismatch"
    assert runner.run_guarded_preflight(**case.kwargs)["status"] == "completed"

    status = _document(case, "run_status.json")
    assert len(case.probe_calls) == status["tokenizer_probe_attempted_calls"] == 1
    assert status["tokenizer_probe_completed_results"] == 1
    assert status["tokenizer_probe_error_count"] == 0
    assert status["actual_attempted_provider_calls"] == len(case.transport_calls) == 0
    assert status["total_external_attempted_calls"] == 1
    assert status["guard_refusal_query_count"] == status["server_tokenization_refusal_query_count"] == 1
    assert status["local_token_refusal_query_count"] == 0
    check, = _rows(case.output / "token_checks.jsonl")
    receipt, = _rows(case.output / "server_tokenization_checks.jsonl")
    assert check["reason"] == receipt["reason"] == "server_tokenization_ids_mismatch"
    assert check["passed"] is receipt["matched"] is False
    assert receipt["local_count"] == receipt["server_count"] == 100
    assert receipt["local_token_ids_sha256"] != receipt["server_token_ids_sha256"]
    assert _rows(case.output / "llm_requests.jsonl") == []
    invocation = case.providers[0].last_invocation
    assert invocation.generation_calls == invocation.repair_calls == 0
    assert case.providers[0].guard_diagnostics["server_tokenization_guard_denial"] is True
    assert case.providers[0].guard_diagnostics["local_guard_denial"] is False
    assert case.results[0].api_call_completed is False


def test_probe_transport_failure_is_separate_from_model_failure_and_not_retried(strict_case):
    case = strict_case
    case.probe_behavior = "error"
    runner.run_guarded_preflight(**case.kwargs)

    status = _document(case, "run_status.json")
    assert status["tokenizer_probe_attempted_calls"] == status["tokenizer_probe_error_count"] == 1
    assert status["tokenizer_probe_completed_results"] == 0
    assert status["actual_attempted_provider_calls"] == 0
    assert status["total_external_attempted_calls"] == len(case.probe_calls) == 1
    assert status["tokenizer_probe_latency_seconds"] >= 0
    assert case.transport_calls == []
    receipt, = _rows(case.output / "server_tokenization_checks.jsonl")
    assert receipt["event"] == "tokenizer_probe_error"
    assert receipt["reason"] == "server_tokenization_transport_unavailable"
    assert status["server_tokenization_refusal_query_count"] == 1


def test_local_budget_refusal_never_probes_or_sends(strict_case):
    case = strict_case
    case.input_tokens = 8193
    runner.run_guarded_preflight(**case.kwargs)

    status = _document(case, "run_status.json")
    assert status["actual_attempted_provider_calls"] == status["tokenizer_probe_attempted_calls"] == 0
    assert status["total_external_attempted_calls"] == status["tokenizer_probe_error_count"] == 0
    assert status["local_token_refusal_query_count"] == status["guard_refusal_query_count"] == 1
    assert status["server_tokenization_refusal_query_count"] == 0
    assert case.probe_calls == case.transport_calls == []
    case.counter.payload_token_ids.assert_not_called()
    assert _rows(case.output / "server_tokenization_checks.jsonl") == []
    assert case.providers[0].guard_diagnostics["local_guard_denial"] is True
    assert case.providers[0].guard_diagnostics["server_tokenization_guard_denial"] is False


def test_strict_generation_and_repair_require_individually_bound_durable_probes(strict_case):
    case = strict_case
    case.force_repair = True
    runner.run_guarded_preflight(**case.kwargs)

    status = _document(case, "run_status.json")
    manifest = _document(case, "run_manifest.json")
    assert status["actual_attempted_provider_calls"] == status["tokenizer_probe_attempted_calls"] == 2
    assert status["tokenizer_probe_completed_results"] == 2
    assert status["total_external_attempted_calls"] == 4
    assert status["guard_refusal_query_count"] == status["tokenizer_probe_error_count"] == 0
    assert manifest["schema_version"] == "grailqa-guarded-development-preflight-v2"
    assert manifest["serving_tokenizer_mode"] == status["serving_tokenizer_mode"] == "per_request_server_tokenization"
    assert manifest["maximum_tokenizer_probe_calls"] == manifest["maximum_provider_calls"] == 30
    assert manifest["maximum_total_external_calls"] == 60
    assert manifest["claim_boundary"]["remote_serving_parity_verified"] is False
    assert manifest["claim_boundary"]["completion_requires_successful_cli_and_status_without_failure_marker"] is True
    assert manifest["cost_boundary"]["total_external_attempted_calls_scope"] == "per_query_inference_plus_tokenizer_probes_only"
    assert manifest["cost_boundary"]["service_startup_health_checks_included"] is False
    assert not (case.output / "run_failure.json").exists()
    assert manifest["paper_result"] is status["paper_result"] is False
    checks = _rows(case.output / "token_checks.jsonl")
    receipts = _rows(case.output / "server_tokenization_checks.jsonl")
    assert [row["call_kind"] for row in checks] == [row["call_kind"] for row in receipts] == ["generation", "repair"]
    assert checks[0]["payload_sha256"] != checks[1]["payload_sha256"]
    assert len(case.transport_calls) == len(case.probe_calls) == len(case.checked_payloads) == 2
    for index, (check, receipt, sent) in enumerate(zip(checks, receipts, case.transport_calls), start=1):
        assert check["payload_sha256"] == receipt["payload_sha256"] == content_hash(sent["payload"])
        assert receipt["tokenize_payload_sha256"] == content_hash(case.probe_calls[index - 1]["payload"])
        assert receipt["probe_index"] == index
        assert receipt["preprocessing_equality_scope"] == EQUALITY_SCOPE
        assert sent["payload"]["max_tokens"] == check["requested_output_tokens"] == 4096
    assert len(case.transport_calls[1]["payload"]["messages"]) > len(case.transport_calls[0]["payload"]["messages"])
    invocation = case.providers[0].last_invocation
    assert invocation.generation_calls == invocation.repair_calls == 1
    assert len(_rows(case.output / "llm_requests.jsonl")) == 2
    assert case.results[0].api_call_completed is True
    case.evaluate.assert_called_once()

    diagnostics = _rows(case.output / "guard_diagnostics.jsonl")
    assert len(diagnostics) == len({id(guard) for guard in case.guards}) == 15
    assert [row["question_id"] for row in diagnostics] == case.spec["question_ids"]
    for row in diagnostics[1:]:
        assert row["provider_invoked"] is False
        assert row["actual_attempted_provider_calls"] == row["token_check_count"] == 0
        assert row["server_tokenization"]["tokenizer_probe_attempted_calls"] == 0
        assert row["server_tokenization"]["tokenizer_probe_receipts"] == []
        assert row["server_tokenization"]["remote_serving_parity_verified"] is False
    assert {row["question_id"] for row in receipts} == {case.spec["question_ids"][0]}


def test_repair_probe_refusal_retains_one_actual_generation_and_two_probe_attempts(strict_case):
    case = strict_case
    case.force_repair = True
    case.probe_behavior = "repair-mismatch"
    runner.run_guarded_preflight(**case.kwargs)

    status = _document(case, "run_status.json")
    assert status["actual_attempted_provider_calls"] == len(case.transport_calls) == 1
    assert status["tokenizer_probe_attempted_calls"] == len(case.probe_calls) == 2
    assert status["total_external_attempted_calls"] == 3
    assert status["server_tokenization_refusal_query_count"] == 1
    invocation = case.providers[0].last_invocation
    assert (invocation.generation_calls, invocation.repair_calls) == (1, 0)
    assert case.providers[0].guard_diagnostics["denied_call_kind"] == "repair"
    assert len(_rows(case.output / "llm_requests.jsonl")) == 1
    assert [row["passed"] for row in _rows(case.output / "token_checks.jsonl")] == [True, False]


def test_fatal_repair_probe_receipt_write_preserves_evidence_and_unknown_totals(strict_case, monkeypatch):
    case = strict_case
    case.force_repair = True
    original_journal = runner.QueryEventJournal

    class FailingReceiptJournal(original_journal):
        def append(self, event):
            if event.get("event") == "tokenizer_probe_result" and event["probe_index"] == 2:
                raise OSError("synthetic-probe-receipt-write-failure")
            super().append(event)

    monkeypatch.setattr(runner, "QueryEventJournal", FailingReceiptJournal)
    with pytest.raises(OSError, match="synthetic-probe-receipt"):
        runner.run_guarded_preflight(**case.kwargs)

    status = _document(case, "run_status.json")
    assert status["status"] == "incomplete"
    assert status["call_accounting_complete"] is False
    for key in ("actual_attempted_provider_calls", "tokenizer_probe_attempted_calls", "total_external_attempted_calls"):
        assert status[key] is None
    assert len(case.probe_calls) == 2 and len(case.transport_calls) == 1
    assert status["completed_inference_query_count"] == 0
    assert status["error_type"] == "OSError"
    assert "synthetic-probe-receipt" not in json.dumps(status)
    assert _rows(case.output / "query_states.jsonl") == []
    events = _rows(case.output / "query_events.jsonl")
    assert events[-1]["event"] == "tokenizer_probe_attempt"
    assert events[-1]["probe_index"] == 2
    assert len([row for row in events if row["event"] == "transport_response"]) == 1
    assert len([row for row in events if row["event"] == "tokenizer_probe_result"]) == 1
    assert not any(row["event"] in {"inference_complete", "run_completed"} for row in events)
    case.evaluate.assert_not_called()
    assert not (case.output / "metrics.json").exists()


def test_final_status_fsync_failure_cannot_be_mistaken_for_published_success(strict_case, monkeypatch):
    case = strict_case
    original_fsync = os.fsync
    status_path = case.output / "run_status.json"
    failed_status_fsyncs = []

    def fail_only_final_status(fd):
        if status_path.exists():
            opened, status = os.fstat(fd), status_path.stat()
            if (opened.st_dev, opened.st_ino) == (status.st_dev, status.st_ino):
                failed_status_fsyncs.append(fd)
                raise OSError("synthetic-sensitive-terminal-status-fsync")
        return original_fsync(fd)

    monkeypatch.setattr(runner.os, "fsync", fail_only_final_status)
    with pytest.raises(OSError, match="synthetic-sensitive-terminal-status-fsync"):
        runner.run_guarded_preflight(**case.kwargs)

    assert len(failed_status_fsyncs) == 1
    # flush preceded the failure, so a reader could see complete success bytes.
    # Preserve those bytes as evidence; the separate marker overrides success.
    assert _document(case, "run_status.json")["status"] == "completed"
    failure = _document(case, "run_failure.json")
    assert failure["status"] == "incomplete" and failure["error_type"] == "OSError"
    assert failure["call_accounting_complete"] is False
    for key in ("actual_attempted_provider_calls", "tokenizer_probe_attempted_calls", "total_external_attempted_calls"):
        assert failure[key] is None
    assert "synthetic-sensitive" not in json.dumps(failure)
    assert failure["reason"] == "incomplete_see_error_type_and_partial_records"
    assert failure["automatic_resume"] is failure["paper_result"] is False
    assert _rows(case.output / "query_events.jsonl")[-1]["event"] == "run_completed"
    assert len(case.probe_calls) == len(case.transport_calls) == 1
    case.evaluate.assert_called_once()


def test_persistent_disk_failure_propagates_even_when_failure_marker_is_unavailable(strict_case, monkeypatch):
    case = strict_case
    original_write = runner._write_json
    attempts = []

    def fail_terminal_publication(path, value):
        attempts.append(path.name)
        if path.name in {"run_status.json", "run_failure.json"}:
            raise OSError("synthetic-sensitive-disk-unavailable")
        return original_write(path, value)

    monkeypatch.setattr(runner, "_write_json", fail_terminal_publication)
    with pytest.raises(OSError, match="synthetic-sensitive-disk-unavailable"):
        runner.run_guarded_preflight(**case.kwargs)

    assert attempts[-3:] == ["run_status.json", "run_status.json", "run_failure.json"]
    assert not (case.output / "run_status.json").exists()
    assert not (case.output / "run_failure.json").exists()
    assert _rows(case.output / "query_events.jsonl")[-1]["event"] == "run_completed"
    assert len(case.probe_calls) == len(case.transport_calls) == 1
    case.evaluate.assert_called_once()


@pytest.mark.parametrize("allow,verify", [(False, False), (True, True), (1, False), (False, 1), (None, True)])
def test_mode_selection_fails_before_any_provider_tokenizer_or_probe(strict_case, allow, verify):
    case = strict_case
    kwargs = {**case.kwargs, "allow_unverified_serving_tokenizer": allow, "verify_server_tokenization": verify}
    with pytest.raises(ValueError):
        runner.run_guarded_preflight(**kwargs)
    case.base_factory.assert_not_called()
    case.tokenizer.assert_not_called()
    case.guard_factory.assert_not_called()
    assert case.probe_calls == case.transport_calls == []
    assert not case.output.exists()


@pytest.mark.parametrize("both", [False, True])
def test_cli_strict_mode_is_executable_and_mutually_exclusive(strict_case, capsys, both):
    case = strict_case
    argv = [
        part for key, value in case.kwargs.items()
        if key not in {"allow_unverified_serving_tokenizer", "verify_server_tokenization"}
        for part in ("--" + ("spec" if key == "spec_path" else key.replace("_", "-")), str(value))
    ]
    argv.append("--verify-server-tokenization")
    if both:
        argv.append("--allow-unverified-serving-tokenizer")
        with pytest.raises(SystemExit) as error:
            runner.main(argv)
        assert error.value.code == 2
        case.base_factory.assert_not_called()
        case.tokenizer.assert_not_called()
        case.guard_factory.assert_not_called()
        assert not case.output.exists()
    else:
        assert runner.main(argv) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "completed"
        assert len(case.probe_calls) == len(case.transport_calls) == 1
        assert _document(case, "run_status.json")["serving_tokenizer_mode"] == "per_request_server_tokenization"
