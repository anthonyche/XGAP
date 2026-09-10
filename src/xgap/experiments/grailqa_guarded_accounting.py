"""Reconstruct the complete ordered guarded-run ledger without external calls."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
from xgap.experiments.grailqa_guarded_reconstruction import reconstruct_guarded_query
from xgap.experiments.grailqa_guarded_token_evidence import reconstruct_query_token_evidence
from xgap.experiments.grailqa_inline_evidence import _require, _same
from xgap.experiments.hashing import content_hash


def reconstruct_guarded_ledger(
    *, states: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]], model: Any, catalog: Any, semantic: Any,
    counter: Any, retrieval_k: int, prompt_limit: int, context_limit: int,
) -> dict[str, Any]:
    """Admit each query in source order and rebuild all extraction copies/totals."""
    _same([s["question"] for s in states], list(questions), "whole frozen question population and order")
    position = 0
    diagnostics, query_reports, token_checks, all_feedback, all_probes = [], [], [], [], []
    for index, (state, question) in enumerate(zip(states, questions), 1):
        qid = question["question_id"]
        fields = "api_call_completed candidate_grounding_policy candidate_repair_policy candidates deterministic_latency_seconds failure llm_latency_seconds prompt_view question repair_calls request_records response_record retrieval retrieval_latency_seconds returned_candidate_count schema_version semantic_scores structured_response terminal".split()
        if state["api_call_completed"] is True:
            fields.append("provider_id")
        _same(sorted(state), sorted(fields), "complete typed query state fields")
        _same(state["candidate_repair_policy"], TYPED_GROUNDING_ONCE, "state repair policy")
        _require(position < len(events), "missing query start")
        _same(events[position], {"event": "query_started", "question_id": qid, "query_index": index}, "ordered query start")
        begin = position
        position += 1
        while position < len(events) and events[position].get("event") != "query_inference_completed":
            _same(events[position].get("question_id"), qid, "no overlapping or orphan query event")
            position += 1
        _require(position < len(events), "missing query completion")
        segment = list(events[begin:position + 1])
        query = reconstruct_guarded_query(
            state=state, question=question, events=segment, model=model, catalog=catalog,
            semantic=semantic, retrieval_k=retrieval_k, prompt_limit=prompt_limit,
        )
        tokens = reconstruct_query_token_evidence(
            question_id=qid, payloads=query.checked_payloads, events=segment, counter=counter,
            input_limit=model.config.token_limits["input"], output_limit=model.config.token_limits["output"],
            context_limit=context_limit, model=model.config.exact_model_snapshot,
        )
        _require(tokens["tokenizer_probe_latency_seconds"] <= state["llm_latency_seconds"] + 1e-6,
                 "probe time is included in recorded LLM time")
        checks = [e["check"] for e in segment if e["event"] == "token_check"]
        failed = [c for c in checks if c["passed"] is False]
        feedback = [e for e in segment if e["event"] == "candidate_contract_feedback"]
        invocation = state["response_record"]
        details = {}
        if invocation:
            denial = bool(failed)
            server_denial = denial and failed[-1]["reason"].startswith("server_tokenization_")
            details = {
                "guard_denial": denial, "local_guard_denial": denial and not server_denial,
                "server_tokenization_guard_denial": server_denial,
                "denied_call_kind": failed[-1]["call_kind"] if denial else None,
                "token_check_count": len(checks), "invocation_available": True,
                "generation_calls": invocation["generation_calls"], "repair_calls": invocation["repair_calls"],
                "provider_failure_category": invocation["failure_category"], "journal_failed_before_send": False,
                "before_send_scope": "inference_transport_only_not_tokenizer_probe", "journal_failure_phase": None,
                "candidate_repair_policy": TYPED_GROUNDING_ONCE, "candidate_feedback": feedback,
            }
        # Enforce one serial transcript, including probes before their checked
        # inference payload. A valid local count alone cannot admit a late probe.
        body = segment[1:-1]
        cursor = 0

        def take(kind):
            nonlocal cursor
            _require(cursor < len(body) and body[cursor].get("event") == kind, "serial query event: " + kind)
            value = body[cursor]
            cursor += 1
            return value

        for attempt, check in enumerate(checks, 1):
            kind = "generation" if attempt == 1 else "repair"
            receipt = next((r for r in tokens["tokenizer_probe_receipts"] if r["call_kind"] == kind), None)
            if receipt is not None:
                take("tokenizer_probe_attempt")
                _same(take(receipt["event"]), receipt, "serial tokenizer terminal")
            take("token_check")
            if check["passed"]:
                binding = {"question_id": qid, "attempt_index": attempt, "payload_sha256": check["payload_sha256"]}
                _same(take("transport_attempt"), {"event": "transport_attempt", **binding, "pre_send_intent_only": True}, "transport intent fields")
                _require(cursor < len(body), "missing transport terminal")
                terminal_kind = body[cursor]["event"]
                _require(terminal_kind in ("transport_response", "transport_error", "response_credential_echo_rejected"), "transport terminal type")
                terminal = take(terminal_kind)
                extra = {"raw_response": terminal["raw_response"]} if terminal_kind == "transport_response" else (
                    {"error_type": terminal["error_type"]} if terminal_kind == "transport_error" else {})
                _same(terminal, {"event": terminal_kind, **binding, **extra}, "transport terminal fields")
                if cursor < len(body) and body[cursor]["event"] == "candidate_contract_feedback":
                    take("candidate_contract_feedback")
        if invocation:
            _same(take("provider_invocation"), {"event": "provider_invocation", "question_id": qid,
                  "invocation": invocation, "request_records": state["request_records"]}, "final invocation fields")
            _same(take("guard_diagnostics"), {"event": "guard_diagnostics", "question_id": qid,
                  "diagnostics": details}, "independently rebuilt provider diagnostics")
        _same(cursor, len(body), "no unconsumed or unknown query events")
        probe_diagnostic = {key: tokens[key] for key in (
            "tokenizer_probe_attempted_calls", "tokenizer_probe_completed_results", "tokenizer_probe_error_count",
            "tokenizer_probe_latency_seconds", "tokenizer_probe_receipts", "preprocessing_equality_scope",
            "remote_serving_parity_verified",
        )}
        probe_diagnostic.update(journal_failed=False, journal_failure_phase=None)
        diagnostic = {
            "question_id": qid, "provider_invoked": bool(invocation),
            "actual_attempted_provider_calls": len(state["request_records"]), "token_check_count": len(checks),
            "guard_refusal": bool(failed),
            "local_token_refusal": any(not c["reason"].startswith("server_tokenization_") for c in failed),
            "server_tokenization_refusal": any(c["reason"].startswith("server_tokenization_") for c in failed),
            "server_tokenization": probe_diagnostic, "details": details,
        }
        _same(segment[-1], {"event": "query_inference_completed", "question_id": qid, "query_index": index,
              "state_sha256": content_hash(state), "diagnostic": diagnostic}, "reconstructed query completion")
        diagnostics.append(diagnostic)
        token_checks.extend({"question_id": qid, **check} for check in checks)
        all_feedback.extend(feedback)
        all_probes.extend(tokens["tokenizer_probe_receipts"])
        query_reports.append({"question_id": qid, "provider_evidence": query.provider_evidence,
                              "token_evidence": tokens, "candidate_count": len(query.candidates)})
        position += 1
    _same(list(events[position:]), [{"event": name, "question_count": len(states)}
          for name in ("inference_complete", "run_completed")], "complete inference/evaluation lifecycle with no trailing events")
    totals = {
        "actual_attempted_provider_calls": sum(d["actual_attempted_provider_calls"] for d in diagnostics),
        "local_token_refusal_query_count": sum(d["local_token_refusal"] for d in diagnostics),
        "guard_refusal_query_count": sum(d["guard_refusal"] for d in diagnostics),
        "server_tokenization_refusal_query_count": sum(d["server_tokenization_refusal"] for d in diagnostics),
        **{key: sum(d["server_tokenization"][key] for d in diagnostics) for key in (
            "tokenizer_probe_attempted_calls", "tokenizer_probe_completed_results",
            "tokenizer_probe_error_count", "tokenizer_probe_latency_seconds",
        )},
        "token_check_count": len(token_checks),
    }
    totals["total_external_attempted_calls"] = totals["actual_attempted_provider_calls"] + totals["tokenizer_probe_attempted_calls"]
    _require(totals["actual_attempted_provider_calls"] <= 2 * len(states)
             and totals["tokenizer_probe_attempted_calls"] <= 2 * len(states), "finite whole-run external budgets")
    return {"totals": totals, "queries": query_reports, "copies": {
        "retrieval": [s["retrieval"] for s in states],
        "llm_requests": [r for s in states for r in s["request_records"]],
        "llm_responses": [s["response_record"] for s in states if s["response_record"]],
        "candidate_feedback": all_feedback, "token_checks": token_checks,
        "guard_diagnostics": diagnostics, "server_tokenization_checks": all_probes,
    }}
