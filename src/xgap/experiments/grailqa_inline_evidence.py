"""Read-only admission of inline provider evidence, not whole-run/paper results.

Recompute every transformation and repair from retained transport responses.
The journal is cross-checked, not treated as a signature or server attestation.
No catalog, reference answer, tokenizer, model, or backend is opened or invoked.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_candidate_feedback import (
    GroundedCandidateFeedback, TYPED_GROUNDING_ONCE,
)
from xgap.experiments.grailqa_preflight_replay import _reconstruct_request
from xgap.experiments.grailqa_semantic_pilot import build_inference_request
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.llm.inline_grounding import materialize_inline_response, validate_response_contract
from xgap.llm.openai_compatible import (
    OpenAICompatibleProviderConfig, OpenAICompatibleStructuredCandidateProvider,
    _structured_content, _validate_candidate_array_bounds, _validate_grounded_shape,
)


class InlineEvidenceError(ValueError):
    """The retained provider evidence is incomplete or inconsistent."""


def _same(actual: Any, expected: Any, label: str) -> None:
    # JSON identity deliberately distinguishes booleans from integer counters.
    if content_hash(actual) != content_hash(expected):
        raise InlineEvidenceError(label)


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise InlineEvidenceError(label)


def _offline_provider(model: ModelBundle) -> OpenAICompatibleStructuredCandidateProvider:
    """Build payloads from the bundle, never ambient credentials or overrides."""
    c = model.config
    config = OpenAICompatibleProviderConfig(
        provider_id=c.provider, base_url=str(c.base_url), api_key_env=str(c.api_key_env),
        model=c.exact_model_snapshot, temperature=c.temperature, top_p=c.top_p,
        max_tokens=int(c.token_limits["output"]), candidate_cap=c.candidate_count,
        timeout_seconds=c.timeout_seconds, structured_output_mode=c.structured_output_mode,
        structured_schema=model.structured_schema, prompt_hash=model.prompt.prompt_hash,
        seed=c.seed, seed_supported=c.seed_supported, max_repair_calls=c.max_repair_calls,
        extra_parameters=c.extra_parameters, response_contract=c.metadata.get("response_contract"),
    )

    def forbidden(**_: Any) -> Any:
        raise RuntimeError("Evidence audit cannot perform transport actions.")

    return OpenAICompatibleStructuredCandidateProvider(
        config=config, system_prompt=model.prompt.system_prompt,
        transport=SimpleNamespace(post_json=forbidden),
    )


def audit_inline_query_evidence(
    *, state: Mapping[str, Any], events: Sequence[Mapping[str, Any]], model: ModelBundle,
) -> dict[str, Any]:
    """Check one invoked query, including ordinary provider/guard failures.

    A retrieval-only miss has no inline provider evidence and is outside this
    function. Inputs are never modified. Successful audit is evidence admission,
    including failures, not a successful query or an accuracy measurement.
    """
    state, events = deepcopy(state), deepcopy(list(events))
    provider = _offline_provider(model)
    contract = validate_response_contract(provider.config.response_contract)
    _require(contract is not None, "an explicitly inline model bundle is required")
    response = state["response_record"]
    requests = state["request_records"]
    qid = state["question"]["question_id"]
    _same(response["task_id"], qid, "question identity")
    _same(response["generation_parameters"], provider.config.safe_dict(), "frozen provider configuration")
    _same(response["provider"], provider.provider_id, "provider identity")
    _same(response["model"], model.config.exact_model_snapshot, "model identity")
    _same(response["prompt_hash"], model.prompt.prompt_hash, "prompt identity")
    query_events = [e for e in events if e.get("question_id") == qid]
    invocations = [e for e in query_events if e.get("event") == "provider_invocation"]
    _require(len(invocations) == 1, "exactly one invocation journal record is required")
    _same(invocations[0]["invocation"], response, "journal invocation")
    _same(invocations[0]["request_records"], requests, "journal requests")
    n = len(requests)
    _require(n <= 2, "shared generation/repair call bound")
    _same(response["generation_calls"], int(n > 0), "generation count")
    _same(response["repair_calls"], max(0, n - 1), "repair count")
    _same(state["repair_calls"], response["repair_calls"], "consumed repair count")
    _same(response["assembled_request_hashes"], [r["payload_hash"] for r in requests], "assembled requests")
    diagnostics = [e for e in query_events if e.get("event") == "guard_diagnostics"]
    _require(len(diagnostics) == 1, "guard diagnostics required")
    _require(query_events.index(invocations[0]) < query_events.index(diagnostics[0]), "diagnostics after invocation")
    _same(diagnostics[0]["diagnostics"]["candidate_repair_policy"], TYPED_GROUNDING_ONCE, "repair policy")
    checks = [e for e in query_events if e.get("event") == "token_check"]
    denied = len(checks) == n + 1
    _require(len(checks) == n or denied, "token check count")
    for i, event in enumerate(checks, 1):
        kind = "generation" if i == 1 else "repair"
        _same(event["check_index"], i, "token check index")
        _same(event["call_kind"], kind, "token check kind")
        _same(event["check"]["call_kind"], kind, "token receipt kind")
        _same(event["check"]["passed"], i <= n, "token check outcome")
        if i <= n:
            _same(event["check"]["payload_sha256"], requests[i - 1]["payload_hash"], "checked payload")
    _require(not denied or n < 2, "no third checked attempt")
    _same(diagnostics[0]["diagnostics"]["guard_denial"], denied, "guard denial")
    _same(diagnostics[0]["diagnostics"]["token_check_count"], len(checks), "diagnostic check count")
    _same(diagnostics[0]["diagnostics"]["generation_calls"], int(n > 0), "diagnostic generation count")
    _same(diagnostics[0]["diagnostics"]["repair_calls"], max(0, n - 1), "diagnostic repair count")
    _same(diagnostics[0]["diagnostics"]["invocation_available"], True, "diagnostic invocation available")
    _same(diagnostics[0]["diagnostics"]["provider_failure_category"], response["failure_category"], "diagnostic provider outcome")
    attempts = [e for e in query_events if e.get("event") == "transport_attempt"]
    terminals = [e for e in query_events if e.get("event") in (
        "transport_response", "transport_error", "response_credential_echo_rejected",
    )]
    _same(len(attempts), n, "transport attempt count")
    _same(len(terminals), n, "transport terminal count")
    raw_responses = []
    for i, (row, attempt, terminal) in enumerate(zip(requests, attempts, terminals), 1):
        for event in (attempt, terminal):
            _same(event["attempt_index"], i, "transport index")
            _same(event["payload_sha256"], row["payload_hash"], "transport payload")
        _require(query_events.index(checks[i - 1]) < query_events.index(attempt)
                 < query_events.index(terminal) < query_events.index(invocations[0]), "transport event order")
        if i > 1:
            _require(query_events.index(terminals[i - 2]) < query_events.index(checks[i - 1]), "repair event order")
        if terminal["event"] == "transport_response":
            raw_responses.append(terminal["raw_response"])
        else:
            _require(i == n, "external failure cannot trigger another attempt")
    _same(response["raw_responses"], raw_responses, "raw transport responses")
    _same(response["provider_request_ids"], [str(r["id"]) for r in raw_responses if r.get("id") is not None], "provider request IDs")
    # Provider-reported usage is checked against its envelopes, not recounted.
    usage = {}
    for target, primary, fallback in (
        ("input_tokens", "prompt_tokens", "input_tokens"),
        ("output_tokens", "completion_tokens", "output_tokens"),
        ("total_tokens", "total_tokens", "total_tokens"),
    ):
        values = []
        for raw in raw_responses:
            value = raw.get("usage", {})
            value = value.get(primary, value.get(fallback)) if isinstance(value, Mapping) else None
            if type(value) is int:
                values.append(value)
        usage[target] = sum(values) if values else None
    _same(response["usage"], usage, "reported usage")
    expected_receipts, expected_feedback, feedback_calls = [], [], []
    effective = None
    last_error = None
    next_payload = None
    if n:
        partial, view = _reconstruct_request(requests, response)
        retrieval = {k: v for k, v in state["retrieval"].items() if k != "latency_seconds"}
        request = build_inference_request(
            state["question"], SimpleNamespace(to_dict=lambda: retrieval), view, partial.max_candidates,
        )
        next_payload = provider.build_request_payload(request)
        feedback = GroundedCandidateFeedback(expected_feedback.append, materialized_inline=True)
        feedback.bind(request, view)
        for i, row in enumerate(requests, 1):
            _same(row["payload"], next_payload, "generation/repair payload reconstruction")
            _same(row["payload_hash"], content_hash(row["payload"]), "payload digest")
            _same(row["provider"], provider.provider_id, "request provider")
            _same(row["model"], model.config.exact_model_snapshot, "request model")
            _same(row["timeout_seconds"], model.config.timeout_seconds, "request timeout")
            _same(row["url"], provider.config.chat_completions_url, "request endpoint")
            if i > len(raw_responses):
                effective = None
                break
            raw = raw_responses[i - 1]
            effective = None
            last_error = None
            try:
                wire = _structured_content(raw)
                _validate_candidate_array_bounds(wire, model.structured_schema)
                receipt = {
                    "schema_version": "xgap-response-materialization-v1", "call_index": i,
                    "contract": contract, "source_response_sha256": content_hash(wire),
                    "request_sha256": content_hash(request.to_dict()),
                    "request_payload_sha256": row["payload_hash"],
                }
                try:
                    derived = materialize_inline_response(wire, entity_identity_property=contract["entity_identity_property"])
                except ValueError:
                    expected_receipts.append({**receipt, "status": "invalid_inline_structure"})
                    raise
                expected_receipts.append({**receipt, "status": "materialized",
                    "materialized_response_sha256": content_hash(derived), "materialized_response": derived})
                parse_normalized_planner_response(derived, request)
                _validate_grounded_shape(derived)
                feedback_calls.append(i)
                feedback(derived, request)
                effective = derived
            except (ValueError, KeyError, TypeError) as error:
                last_error = str(error)
            if i < n:
                _require(last_error is not None, "valid candidate cannot trigger a quality retry")
            if last_error is not None:
                next_payload = provider._repair_payload(requests[0]["payload"], raw, last_error)
        if denied:
            _require(last_error is not None, "repair denial must follow an invalid response")
            _same(checks[-1]["check"]["payload_sha256"], content_hash(next_payload), "refused repair payload")
        if response["validation_status"] == "schema_valid":
            _require(effective is not None and not denied, "successful final validation")
            _same(response["structured_response"], _structured_content(raw_responses[-1]), "final wire response")
            _same(state.get("structured_response"), effective, "consumed materialized response")
            _same(state.get("prompt_view"), view.to_dict(), "consumed prompt view")
    else:
        _require(denied, "zero sends require a retained generation denial")
    _same(response.get("response_materializations", []), expected_receipts, "all materialization receipts")
    feedback_events = [e for e in query_events if e.get("event") == "candidate_contract_feedback"]
    _same(feedback_events, expected_feedback, "recomputed candidate feedback")
    _same(diagnostics[0]["diagnostics"].get("candidate_feedback"), expected_feedback, "diagnostic feedback")
    for event, call in zip(feedback_events, feedback_calls):
        _require(query_events.index(terminals[call - 1]) < query_events.index(event)
                 < query_events.index(invocations[0]), "feedback event order")
        if call < n:
            _require(query_events.index(event) < query_events.index(checks[call]), "feedback before repair")
    if denied:
        _require(query_events.index(checks[-1]) < query_events.index(invocations[0]), "denial before invocation")
        if n:
            _require(query_events.index(terminals[-1]) < query_events.index(checks[-1]), "denial after response")
            if feedback_events:
                _require(query_events.index(feedback_events[-1]) < query_events.index(checks[-1]), "feedback before denial")
        _require(isinstance(checks[-1]["check"].get("reason"), str)
                 and bool(checks[-1]["check"]["reason"]), "denial reason required")
    success = response["validation_status"] == "schema_valid"
    _same(state["api_call_completed"], success, "consumed provider outcome")
    if success:
        _same(response["parse_status"], "parsed", "successful parse status")
        _same(response["failure_category"], None, "successful failure category")
        _same(response["error_message"], None, "successful error message")
    else:
        _same(response["validation_status"], "failed", "failed validation status")
        _same(response["parse_status"], "failed", "failed parse status")
        _same(response["structured_response"], None, "failed wire outcome")
        _same(state.get("structured_response"), None, "failed consumed outcome")
        _require(denied or len(raw_responses) < n or last_error is not None, "failure requires retained cause")
        if not denied and len(raw_responses) == n:
            _same(response["error_message"], last_error, "deterministic failure message")
            _same(response["failure_category"], "repair_failed" if n == 2 else "structured_output_error", "deterministic failure category")
        else:
            _require(response["failure_category"] in {"provider_error", "timeout"}, "external/guard failure category")
    return {
        "question_id": qid, "evidence_admitted": True, "provider_succeeded": success,
        "attempted_calls": n, "materializations_recomputed": len(expected_receipts),
        "feedback_assessments_recomputed": len(expected_feedback),
        "generation_denied_without_payload_reconstruction": n == 0,
        "model_bundle_hash": model.bundle_hash,
    }


def audit_inline_run_evidence(*, run_root: Path, model: ModelBundle) -> dict[str, Any]:
    """Check the retained provider subset; never claim population admission."""
    names = ("query_states.jsonl", "query_events.jsonl", "llm_requests.jsonl",
             "llm_responses.jsonl", "candidate_feedback.jsonl")
    loaded, digests = {}, {}
    for name in names:
        path = run_root / name
        _require(path.is_file() and not path.is_symlink(), "regular evidence files required")
        data = path.read_bytes()
        digests[name] = hashlib.sha256(data).hexdigest()
        loaded[name] = [json.loads(line) for line in data.splitlines() if line.strip()]
    states = loaded["query_states.jsonl"]
    events = loaded["query_events.jsonl"]
    ids = [s["question"]["question_id"] for s in states]
    _require(bool(ids) and len(set(ids)) == len(ids), "nonempty unique query state IDs")
    _require(all(e.get("question_id") in set(ids) for e in events if "question_id" in e), "orphan journal query")
    _same(loaded["llm_requests.jsonl"], [r for s in states for r in s.get("request_records", [])], "request ledger extraction")
    _same(loaded["llm_responses.jsonl"], [s["response_record"] for s in states if s.get("response_record")], "response ledger extraction")
    _same(loaded["candidate_feedback.jsonl"], [e for e in events if e.get("event") == "candidate_contract_feedback"], "feedback ledger extraction")
    queries, uninvoked = [], []
    for state in states:
        qid = state["question"]["question_id"]
        seals = [e for e in events if e.get("event") == "query_inference_completed" and e.get("question_id") == qid]
        _require(len(seals) == 1, "exactly one query state seal required")
        _same(seals[0]["state_sha256"], content_hash(state), "sealed query state")
        _require(all(events.index(e) < events.index(seals[0]) for e in events
                     if e.get("question_id") == qid and e.get("event") in (
                         "provider_invocation", "guard_diagnostics", "token_check",
                         "transport_attempt", "transport_response", "transport_error",
                         "response_credential_echo_rejected", "candidate_contract_feedback",
                     )), "query sealed before provider evidence ended")
        if state.get("response_record"):
            queries.append(audit_inline_query_evidence(state=state, events=events, model=model))
        else:
            _require(not any(e.get("question_id") == qid and e.get("event") in (
                "transport_attempt", "provider_invocation", "candidate_contract_feedback", "token_check",
            ) for e in events), "uninvoked query has provider evidence")
            uninvoked.append(qid)
    _require(bool(queries), "no inline provider evidence to admit")
    for name in names:
        _same(hashlib.sha256((run_root / name).read_bytes()).hexdigest(), digests[name], "evidence unchanged during audit")
    return {
        "schema_version": "grailqa-inline-provider-evidence-v1", "evidence_admitted": True,
        "queries": queries, "uninvoked_queries_not_admitted": uninvoked, "input_sha256": digests,
        "claim_boundary": {"whole_run_admitted": False, "paper_result": False,
            "semantic_metrics_verified": False, "token_counts_recomputed": False,
            "server_identity_verified": False, "external_calls": 0},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--model-bundle", required=True)
    args = parser.parse_args(argv)
    try:
        result = audit_inline_run_evidence(run_root=Path(args.run_root), model=ModelBundle.load(args.model_bundle))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(json.dumps({"evidence_admitted": False, "error_type": type(error).__name__,
                          "paper_result": False}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
