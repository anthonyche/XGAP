"""Recount actual offline ServerTokenizationGuard receipts without transport."""

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

from xgap.experiments.grailqa_guarded_token_evidence import reconstruct_query_token_evidence
from xgap.experiments.grailqa_inline_evidence import InlineEvidenceError
from xgap.experiments.grailqa_server_tokenization import ServerTokenizationEndpointError


HELPERS = runpy.run_path(str(Path(__file__).with_name("test_grailqa_server_tokenization.py")))


@pytest.fixture
def case(tmp_path):
    generator = HELPERS["case"].__wrapped__(tmp_path)
    yield next(generator)
    with pytest.raises(StopIteration):
        next(generator)


def check(case, payload, index):
    kind = "generation" if index == 1 else "repair"
    result = case.guard.check(payload, call_kind=kind)
    case.journal.append({"event":"token_check", "question_id":"q1", "check_index":index,
                         "call_kind":kind, "check":result})
    return result


def events(case):
    return [json.loads(line) for line in case.journal.path.read_text().splitlines()]


def audit(case, payloads, records=None):
    return reconstruct_query_token_evidence(
        question_id="q1", payloads=payloads, events=events(case) if records is None else records,
        counter=case.counter, input_limit=8192, output_limit=4096, context_limit=12288,
        model=case.payload["model"],
    )


@pytest.mark.parametrize("mode", ["match", "local-refusal", "ids-mismatch", "context-mismatch", "error", "invalid"])
def test_recounts_actual_guard_results_and_keeps_failure_scope(case, mode):
    if mode == "local-refusal":
        case.counter.ids = (8,) * 8193
    elif mode == "ids-mismatch":
        case.transport.responses = [HELPERS["_response"](tokens=[8, 11, 10])]
    elif mode == "context-mismatch":
        case.transport.responses = [HELPERS["_response"](max_model_len=16384)]
    elif mode == "error":
        case.transport.responses = [ServerTokenizationEndpointError("http_error")]
    elif mode == "invalid":
        case.transport.responses = [HELPERS["_response"](count=True)]
    original = check(case, case.payload, 1)
    before = deepcopy((case.payload, events(case), case.transport.calls))
    result = audit(case, [case.payload])
    assert result["input_counts_recomputed"] == [original["input_tokens"]]
    assert result["tokenizer_probe_attempted_calls"] == (0 if mode == "local-refusal" else 1)
    assert bool(result["recorded_reasons_not_independently_reconstructed"]) == (mode in {"error", "invalid"})
    assert result["external_calls"] == 0
    assert before == (case.payload, events(case), case.transport.calls)


def test_generation_and_repair_are_separately_recounted(case):
    check(case, case.payload, 1)
    repair = deepcopy(case.payload)
    repair["messages"].append({"role":"user", "content":"repair request"})
    check(case, repair, 2)
    result = audit(case, [case.payload, repair])
    assert result["checked_payload_count"] == result["tokenizer_probe_attempted_calls"] == 2
    assert result["tokenizer_probe_receipts"] == case.guard.diagnostics["tokenizer_probe_receipts"]
    assert result["tokenizer_probe_latency_seconds"] == case.guard.diagnostics["tokenizer_probe_latency_seconds"]


@pytest.mark.parametrize("defect", [
    "local-count", "server-count", "local-ids", "server-ids", "matched-bool", "context",
    "payload", "projection", "probe-index", "check-index", "missing-probe", "extra-probe",
    "late-probe", "wrong-order", "negative-time", "bool-time", "counter-drift", "identity",
    "budget", "unjustified-refusal", "third-check",
])
def test_rejects_corrupted_numeric_or_probe_history(case, defect):
    check(case, case.payload, 1)
    records = events(case)
    intent, result, receipt = records
    if defect == "local-count":
        receipt["check"]["input_tokens"] = 4
    elif defect == "server-count":
        result["server_count"] = 4
    elif defect == "local-ids":
        intent["local_token_ids_sha256"] = result["local_token_ids_sha256"] = "0" * 64
    elif defect == "server-ids":
        result["server_token_ids_sha256"] = "0" * 64
    elif defect == "matched-bool":
        result["matched"] = 1
    elif defect == "context":
        result["server_max_model_len"] = 16384
    elif defect in {"payload", "projection"}:
        key = "payload_sha256" if defect == "payload" else "tokenize_payload_sha256"
        intent[key] = result[key] = "0" * 64
    elif defect == "probe-index":
        intent["probe_index"] = result["probe_index"] = True
    elif defect == "check-index":
        receipt["check_index"] = True
    elif defect == "missing-probe":
        records.remove(intent)
    elif defect == "extra-probe":
        records.insert(0, deepcopy(intent))
    elif defect == "late-probe":
        records.remove(result)
        records.append(result)
    elif defect == "wrong-order":
        records[0], records[1] = records[1], records[0]
    elif defect in {"negative-time", "bool-time"}:
        result["elapsed_seconds"] = -1 if defect == "negative-time" else True
    elif defect == "counter-drift":
        case.counter.ids = (8, 11, 10)
    elif defect == "identity":
        receipt["check"]["tokenizer_identity"] = {"other":True}
    elif defect == "budget":
        receipt["check"]["budgets"]["input"] = 10000
    elif defect == "unjustified-refusal":
        receipt["check"].update(passed=False, reason="input_budget_exceeded")
    elif defect == "third-check":
        records.extend([deepcopy(receipt), deepcopy(receipt)])
    with pytest.raises((InlineEvidenceError, ValueError, KeyError)):
        audit(case, [case.payload], records)


def test_no_payload_does_not_admit_orphan_probe(case):
    assert audit(case, [], []) ["checked_payload_count"] == 0
    check(case, case.payload, 1)
    with pytest.raises(InlineEvidenceError):
        audit(case, [], events(case)[:2])
