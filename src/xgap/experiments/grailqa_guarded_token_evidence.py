"""Recount checked payloads and reconstruct their retained server-probe ledger.

The whole-run reader must establish the pinned local counter's file identity.
No endpoint is called. Server errors are retained observations; the omitted
raw error/invalid-response bodies cannot be independently reconstructed.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence

from xgap.experiments.grailqa_inline_evidence import _require, _same
from xgap.experiments.grailqa_server_tokenization import EQUALITY_SCOPE, _projection
from xgap.experiments.hashing import content_hash
from xgap.llm.token_budget import _text_chat_inputs


_ERROR_REASONS = {"server_tokenization_" + name for name in (
    "transport_unavailable", "http_error", "redirect_refused", "invalid_response",
)}
_OBSERVATION_REASONS = {"server_tokenization_" + name for name in (
    "credential_echo_rejected", "invalid_response", "local_identity_mismatch", "local_unavailable",
)}


def reconstruct_query_token_evidence(
    *, question_id: str, payloads: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]], counter: Any,
    input_limit: int, output_limit: int, context_limit: int, model: str,
) -> dict[str, Any]:
    """Check exact local counts and one retained probe for each locally valid send.

    Error receipts preserve a failed attempt and its recorded reason without
    elevating that reason to independently reconstructed remote causality.
    The complete reader must also bind extraction copies, transport and totals.
    """
    _require(all(type(n) is int and n > 0 for n in (input_limit, output_limit, context_limit))
             and input_limit + output_limit <= context_limit, "frozen positive token budgets")
    events = [deepcopy(e) for e in events if e.get("question_id") == question_id]
    checks = [(i, e) for i, e in enumerate(events) if e.get("event") == "token_check"]
    probes = [(i, e) for i, e in enumerate(events) if str(e.get("event", "")).startswith("tokenizer_probe_")]
    _same(len(payloads), len(checks), "token payload population")
    _require(len(payloads) <= 2, "bounded token-check population")
    identity = deepcopy(counter.identity)
    used_positions: set[int] = set()
    receipts, counts, observations = [], [], []
    previous_check_position = -1
    for index, (payload, (check_position, event)) in enumerate(zip(payloads, checks), 1):
        kind = "generation" if index == 1 else "repair"
        _same(event["check_index"], index, "token-check index")
        _same(event["call_kind"], kind, "token-check event kind")
        frozen_payload = deepcopy(payload)
        _same(payload.get("model"), model, "token-count model")
        _same(payload.get("max_tokens"), output_limit, "token output reservation")
        _text_chat_inputs(payload)
        ids = counter.payload_token_ids(payload)
        _same(payload, frozen_payload, "token counter preserves payload")
        _same(counter.identity, identity, "stable tokenizer identity")
        _require(isinstance(ids, (list, tuple)) and bool(ids)
                 and all(type(n) is int and n >= 0 for n in ids), "exact token ID sequence")
        ids = list(ids)
        count = len(ids)
        reason = "input_budget_exceeded" if count > input_limit else (
            "context_budget_exceeded" if count + output_limit > context_limit else "within_budget")
        expected = {
            "schema_version": "xgap-chat-token-budget-check-v1", "call_kind": kind,
            "payload_sha256": content_hash(payload), "passed": reason == "within_budget", "reason": reason,
            "input_tokens": count, "requested_output_tokens": output_limit,
            "budgets": {"input": input_limit, "output": output_limit, "context": context_limit},
            "tokenizer_identity": identity,
        }
        counts.append(count)
        local_probes = [(i, e) for i, e in probes if previous_check_position < i < check_position]
        if reason != "within_budget":
            _same(local_probes, [], "locally refused request has no server probe")
        else:
            _require(len(local_probes) == 2, "one intent and terminal receipt per locally valid request")
            (attempt_position, attempt), (terminal_position, terminal) = local_probes
            used_positions.update((attempt_position, terminal_position))
            binding = {
                "question_id": question_id, "call_kind": kind, "probe_index": len(receipts) + 1,
                "payload_sha256": content_hash(payload),
                "tokenize_payload_sha256": content_hash(_projection(payload)),
                "local_token_ids_sha256": content_hash(ids), "local_count": count,
                "preprocessing_equality_scope": EQUALITY_SCOPE,
            }
            _same(attempt, {"event": "tokenizer_probe_attempt", **binding, "pre_send_intent_only": True},
                  "probe intent reconstruction")
            for key, value in binding.items():
                _same(terminal.get(key), value, "probe result binding: " + key)
            elapsed = terminal.get("elapsed_seconds")
            _require(type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
                     "finite recorded probe time")
            source_reason = terminal.get("reason")
            if terminal.get("event") == "tokenizer_probe_error":
                _require(source_reason in _ERROR_REASONS, "known endpoint-error observation")
                _same(sorted(terminal), sorted(set(binding) | {"event", "reason", "elapsed_seconds"}), "probe error fields")
                observations.append({"probe_index": binding["probe_index"], "reason": source_reason})
                expected.update(passed=False, reason=source_reason)
            else:
                _same(terminal.get("event"), "tokenizer_probe_result", "probe terminal kind")
                _same(sorted(terminal), sorted(set(binding) | {"event", "reason", "elapsed_seconds", "matched",
                                                   "server_token_ids_sha256", "server_count", "server_max_model_len"}),
                      "probe result fields")
                server_hash = terminal.get("server_token_ids_sha256")
                server_count = terminal.get("server_count")
                server_context = terminal.get("server_max_model_len")
                if source_reason in _OBSERVATION_REASONS:
                    _same(terminal.get("matched"), False, "unreconstructed server/local error refuses inference")
                    observations.append({"probe_index": binding["probe_index"], "reason": source_reason})
                    expected.update(passed=False, reason=source_reason)
                else:
                    _require(type(server_count) is int and server_count > 0
                             and type(server_context) is int and server_context > 0
                             and isinstance(server_hash, str) and len(server_hash) == 64
                             and all(ch in "0123456789abcdef" for ch in server_hash), "bounded server token receipt")
                    actual_reason = "server_tokenization_context_mismatch" if server_context != context_limit else (
                        "server_tokenization_ids_mismatch" if server_hash != binding["local_token_ids_sha256"]
                        else "server_tokenization_match")
                    if server_hash == binding["local_token_ids_sha256"]:
                        _same(server_count, count, "equal token sequence has equal count")
                    _same(source_reason, actual_reason, "server comparison outcome")
                    _same(terminal.get("matched"), actual_reason == "server_tokenization_match", "server equality flag")
                    if actual_reason != "server_tokenization_match":
                        expected.update(passed=False, reason=actual_reason)
            receipts.append(terminal)
        _same(event["check"], expected, "recounted token receipt")
        if expected["passed"] is False:
            _require(index == len(checks), "no token check after refusal")
        previous_check_position = check_position
    _same(sorted(used_positions), [i for i, _ in probes], "no orphan or late tokenizer probes")
    return {
        "question_id": question_id, "checked_payload_count": len(payloads),
        "input_counts_recomputed": counts,
        "tokenizer_probe_attempted_calls": len(receipts),
        "tokenizer_probe_completed_results": sum(r["event"] == "tokenizer_probe_result" for r in receipts),
        "tokenizer_probe_error_count": sum(r["event"] == "tokenizer_probe_error" for r in receipts),
        "tokenizer_probe_latency_seconds": sum((r["elapsed_seconds"] for r in receipts), 0.0),
        "tokenizer_probe_receipts": receipts,
        "recorded_reasons_not_independently_reconstructed": observations,
        "preprocessing_equality_scope": EQUALITY_SCOPE,
        "remote_serving_parity_verified": False, "external_calls": 0,
    }
