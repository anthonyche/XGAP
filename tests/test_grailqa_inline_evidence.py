"""Independent corruption tests over real offline guarded-provider records."""

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

from xgap.experiments.grailqa_inline_evidence import (
    InlineEvidenceError, audit_inline_query_evidence, audit_inline_run_evidence, main,
)
from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError


ROOT = Path(__file__).resolve().parents[1]
HELPERS = runpy.run_path(str(ROOT / "tests/test_inline_grounding.py"))


def records(tmp_path, monkeypatch, scenario="success"):
    good = HELPERS["wire"](HELPERS["FIXTURES"]["case"].__wrapped__().raw)
    bad = deepcopy(good)
    bad["candidates"][0]["pattern_query"]["source"].pop("label_slot")
    tokens = (100, 100)
    wires = [good]
    if scenario == "repair":
        wires = [bad, good]
    elif scenario == "repair-failed":
        wires = [bad, bad]
    elif scenario == "structure":
        broken = deepcopy(good)
        broken["candidates"][0]["pattern_query"]["expr"]["kind"] = "unknown"
        wires = [broken, good]
    elif scenario == "malformed":
        wires = [{"invalid": True}, good]
    elif scenario == "bounds":
        wires = [{**good, "candidates": good["candidates"] * 4}, good]
    elif scenario == "generation-denied":
        tokens = (9000,)
        wires = []
    elif scenario == "repair-denied":
        tokens = (100, 9000)
        wires = [bad]
    elif scenario in {"timeout", "repair-timeout"}:
        error = ProviderTransportError(LiveFailureCategory.TIMEOUT, "offline fixture timeout")
        wires = [error] if scenario == "timeout" else [bad, error]
    case = HELPERS["provider_case"](tmp_path, monkeypatch, wires, tokens=tokens)
    state = HELPERS["infer"](case)
    events = [json.loads(line) for line in case.journal.path.read_text().splitlines()]
    return case, state, events


@pytest.mark.parametrize("scenario", [
    "success", "repair", "repair-failed", "structure", "malformed", "bounds",
    "generation-denied", "repair-denied", "timeout", "repair-timeout",
])
def test_real_pipeline_evidence_and_failures_are_admitted_without_sends(tmp_path, monkeypatch, scenario):
    case, state, events = records(tmp_path, monkeypatch, scenario)
    before = deepcopy((state, events, case.calls))
    # Ambient provider overrides must not change the audit's model or endpoint.
    monkeypatch.setenv("XGAP_LLM_BASE_URL", "http://unavailable.invalid")
    monkeypatch.setenv("XGAP_LLM_MODEL", "unrelated")
    result = audit_inline_query_evidence(state=state, events=events, model=case.model)
    assert result["evidence_admitted"]
    assert result["provider_succeeded"] == state["api_call_completed"]
    assert result["attempted_calls"] == len(case.calls)
    assert before == (state, events, case.calls)


def resync_invocation(state, events):
    for event in events:
        if event["event"] == "provider_invocation":
            event["invocation"] = deepcopy(state["response_record"])
            event["request_records"] = deepcopy(state["request_records"])


@pytest.mark.parametrize("defect", [
    "old-request-hash", "old-derived-rehash", "old-status", "old-contract",
    "receipt-schema", "duplicate-receipt", "missing-first", "swapped-receipts",
    "raw-first", "usage", "request-id", "final-wire", "consumed-tree",
    "feedback-valid-count", "feedback-request", "feedback-order", "valid-retry",
    "check-payload", "check-order", "transport-raw", "transport-index",
    "missing-response-event", "duplicate-invocation", "call-bool", "repair-body",
])
def test_corrupt_history_and_self_consistent_hashes_are_rejected(tmp_path, monkeypatch, defect):
    case, state, events = records(tmp_path, monkeypatch, "repair")
    response = state["response_record"]
    first = response["response_materializations"][0]
    feedback = [e for e in events if e["event"] == "candidate_contract_feedback"]
    if defect == "old-request-hash":
        first["request_sha256"] = "0" * 64
    elif defect == "old-derived-rehash":
        first["materialized_response"]["candidates"][0]["pattern_query"]["expr"]["edge"]["direction"] = "IN"
        first["materialized_response_sha256"] = content_hash(first["materialized_response"])
    elif defect == "old-status":
        first["status"] = "invalid_inline_structure"
    elif defect == "old-contract":
        first["contract"]["entity_identity_property"] = "changed"
    elif defect == "receipt-schema":
        first["schema_version"] = "unknown"
    elif defect == "duplicate-receipt":
        response["response_materializations"].append(deepcopy(first))
    elif defect == "missing-first":
        response["response_materializations"].pop(0)
    elif defect == "swapped-receipts":
        response["response_materializations"].reverse()
    elif defect == "raw-first":
        response["raw_responses"][0]["choices"][0]["message"]["content"] = "{}"
    elif defect == "usage":
        response["usage"]["total_tokens"] += 1
    elif defect == "request-id":
        response["provider_request_ids"].reverse()
        response["provider_request_ids"][0] = "other"
    elif defect == "final-wire":
        response["structured_response"]["question"] = "different"
    elif defect == "consumed-tree":
        state["structured_response"]["candidates"][0]["pattern_query"]["expr"]["edge"]["direction"] = "IN"
    elif defect in {"feedback-valid-count", "feedback-request"}:
        key = "valid_candidate_count" if defect == "feedback-valid-count" else "request_sha256"
        feedback[0][key] = 55 if defect == "feedback-valid-count" else "0" * 64
        diagnostic = next(e["diagnostics"] for e in events if e["event"] == "guard_diagnostics")
        diagnostic["candidate_feedback"] = deepcopy(feedback)
    elif defect == "feedback-order":
        events.remove(feedback[0])
        events.insert(0, feedback[0])
    elif defect == "valid-retry":
        # Both the response journal and invocation now claim a valid first call.
        response["raw_responses"][0] = deepcopy(response["raw_responses"][1])
        next(e for e in events if e["event"] == "transport_response")["raw_response"] = deepcopy(response["raw_responses"][0])
    elif defect.startswith("check-"):
        event = next(e for e in events if e["event"] == "token_check")
        if defect == "check-payload":
            event["check"]["payload_sha256"] = "0" * 64
        else:
            events.remove(event)
            events.append(event)
    elif defect == "transport-raw":
        next(e for e in events if e["event"] == "transport_response")["raw_response"] = {}
    elif defect == "transport-index":
        next(e for e in events if e["event"] == "transport_attempt")["attempt_index"] = 2
    elif defect == "missing-response-event":
        events.remove(next(e for e in events if e["event"] == "transport_response"))
    elif defect == "duplicate-invocation":
        events.append(deepcopy(next(e for e in events if e["event"] == "provider_invocation")))
    elif defect == "call-bool":
        response["generation_calls"] = True
    elif defect == "repair-body":
        row = state["request_records"][1]
        row["payload"]["messages"][-1]["content"] = "Try improving answer accuracy"
        row["payload_hash"] = content_hash(row["payload"])
        response["assembled_request_hashes"][1] = row["payload_hash"]
        for event in events:
            if event.get("attempt_index") == 2:
                event["payload_sha256"] = row["payload_hash"]
            if event.get("check_index") == 2:
                event["check"]["payload_sha256"] = row["payload_hash"]
    resync_invocation(state, events)
    with pytest.raises((InlineEvidenceError, ValueError)):
        audit_inline_query_evidence(state=state, events=events, model=case.model)


def write_run(root, state, events):
    events = [*events, {"event": "query_inference_completed", "question_id": "q1",
                       "state_sha256": content_hash(state)}]
    rows = {"query_states.jsonl": [state], "query_events.jsonl": events,
            "llm_requests.jsonl": state["request_records"],
            "llm_responses.jsonl": [state["response_record"]],
            "candidate_feedback.jsonl": [e for e in events if e["event"] == "candidate_contract_feedback"]}
    for name, values in rows.items():
        (root / name).write_text("".join(json.dumps(v) + "\n" for v in values))


@pytest.mark.parametrize("defect", [None, "seal", "feedback", "duplicate-state", "orphan", "symlink"])
def test_read_only_run_ledger_gate_and_cli(tmp_path, monkeypatch, capsys, defect):
    case, state, events = records(tmp_path, monkeypatch)
    write_run(tmp_path, state, events)
    if defect == "seal":
        (tmp_path / "query_states.jsonl").write_text(json.dumps({**state, "terminal": False}) + "\n")
    elif defect == "feedback":
        (tmp_path / "candidate_feedback.jsonl").write_text("")
    elif defect == "duplicate-state":
        (tmp_path / "query_states.jsonl").write_text((json.dumps(state) + "\n") * 2)
    elif defect == "orphan":
        with (tmp_path / "query_events.jsonl").open("a") as f:
            f.write(json.dumps({"event": "transport_attempt", "question_id": "q2"}) + "\n")
    elif defect == "symlink":
        path = tmp_path / "candidate_feedback.jsonl"
        target = tmp_path / "original.jsonl"
        path.rename(target)
        path.symlink_to(target)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    args = ["--run-root", str(tmp_path), "--model-bundle", str(HELPERS["BUNDLE"])]
    assert main(args) == (2 if defect else 0)
    result = json.loads(capsys.readouterr().out)
    assert result["evidence_admitted"] is (defect is None)
    if not defect:
        assert result["claim_boundary"]["whole_run_admitted"] is False
        assert result["claim_boundary"]["external_calls"] == 0
        assert audit_inline_run_evidence(run_root=tmp_path, model=case.model) == result
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
