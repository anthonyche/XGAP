"""Rebuild guarded query semantics from explicit inference inputs and wire evidence.

No inference producer, reference answer, transport, or model is invoked. The
catalog must be supplied by the whole-run reader after its source admission.
Shared pure parsers, grounding contracts and ontology mathematics remain the
semantic definition; producer candidate rows and scores are not trusted.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_candidate_feedback import GroundedCandidateFeedback
from xgap.experiments.grailqa_candidate_grounding import (
    SEMANTIC_GROUNDING_POLICY, ground_canonical_candidates,
)
from xgap.experiments.grailqa_inline_evidence import (
    _offline_provider, _require, _same, audit_inline_query_evidence,
)
from xgap.experiments.grailqa_semantic_pilot import (
    _entity_grounding_error, _relation_grounding_error, build_inference_request,
    strict_inference_leakage_audit,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.runtime_alignment import PromptSchemaView
from xgap.experiments.semantic import DirectionalOntologyDeviation, SlotAlignmentEvidence
from xgap.llm.candidate_assessment import assess_candidate
from xgap.llm.inline_grounding import materialize_inline_response
from xgap.llm.openai_compatible import (
    _structured_content, _validate_candidate_array_bounds, _validate_grounded_shape,
)
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.llm.schemas import PlannerRequest


@dataclass(frozen=True)
class ReconstructedGuardedQuery:
    question_id: str
    request: PlannerRequest | None
    prompt_view: PromptSchemaView | None
    checked_payloads: tuple[Mapping[str, Any], ...]
    candidates: tuple[Mapping[str, Any], ...]
    semantic_scores: tuple[Mapping[str, Any], ...]
    provider_evidence: Mapping[str, Any] | None


def _failure(qid: str, category: str, message: str) -> dict[str, Any]:
    return {"schema_version": "m13d-first-failure-v1", "question_id": qid,
            "category": category, "message": message}


def _candidate_records(
    raw: Mapping[str, Any], request: PlannerRequest, view: PromptSchemaView,
    semantic: DirectionalOntologyDeviation,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    parsed = parse_normalized_planner_response(raw, request)
    batch = ground_canonical_candidates(raw, parsed, view)
    anchors = {item.slot_id: item.query_anchor_id for item in batch.grounded.query_anchors}
    candidates, scores = [], []
    first_failure = None
    qid = str(request.metadata["task_id"])
    for position, candidate in enumerate(parsed.candidates, 1):
        assessed = assess_candidate(candidate)
        row = {
            "question_id": qid, "candidate_id": candidate.candidate_id,
            "candidate_index": position,
            "pattern_query": path_pattern_query_to_dict(candidate.pattern_query),
            "confidence": candidate.confidence,
            "validation": assessed.semantic_validation.to_dict(),
            "logical_lowering": assessed.logical_lowering.to_dict(),
            "grounded": False, "semantic_admissible": False,
        }
        issue = batch.failures.get(candidate.candidate_id)
        if issue is not None:
            row.update(grounding_failure=issue.to_dict(), grounding_error=issue.message)
        failure = None
        if not assessed.semantic_validation.ok:
            failure = ("type_check_failure", assessed.semantic_validation.message)
        elif issue is not None:
            failure = (issue.category, issue.message)
        else:
            binding = batch.grounded.candidate(candidate.candidate_id)
            entity_error = _entity_grounding_error(candidate.pattern_query, binding.entity_ids, view)
            relation_error = _relation_grounding_error(candidate.pattern_query, binding)
            if entity_error or relation_error:
                row["grounding_error"] = entity_error or relation_error
                failure = ("entity_grounding_failure" if entity_error else "relation_grounding_failure",
                           entity_error or relation_error)
            else:
                evidence = tuple(SlotAlignmentEvidence(
                    slot_id=slot.slot_id, query_term=anchors[slot.slot_id],
                    aligned_term=slot.ontology_term_id,
                    metadata={"component_ref": slot.component_ref},
                ) for slot in binding.slot_realizations)
                score = semantic.evaluate(evidence)
                row.update(grounded=True, semantic_admissible=score.admissible,
                           semantic_deviation=score.finite_value)
                scores.append({"question_id": qid, "candidate_id": candidate.candidate_id,
                               "measurement": score.to_dict()})
        if first_failure is None and failure is not None:
            first_failure = failure
        candidates.append(row)
    final_failure = None
    if not any(row["semantic_admissible"] for row in candidates):
        kind, message = first_failure or ("semantic_bound_rejection", "No candidate had finite c_sem.")
        final_failure = _failure(qid, kind, message)
    return candidates, scores, final_failure


def _checked_payloads(
    *, state: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
    request: PlannerRequest, view: PromptSchemaView, model: ModelBundle,
) -> tuple[Mapping[str, Any], ...]:
    provider = _offline_provider(model)
    initial = provider.build_request_payload(request)
    sent = [deepcopy(row["payload"]) for row in state["request_records"]]
    checks = [e["check"] for e in events if e.get("event") == "token_check"]
    if sent:
        _same(sent[0], initial, "generation request from independent catalog context")
    if len(checks) == len(sent) + 1:
        if not sent:
            sent.append(initial)
        else:
            # A retained token refusal contains only a payload digest. Recover
            # the actual repair from the original wire response and validators.
            raw = state["response_record"]["raw_responses"][-1]
            feedback = GroundedCandidateFeedback(lambda _: None, materialized_inline=True)
            feedback.bind(request, view)
            validation_error = None
            try:
                wire = _structured_content(raw)
                _validate_candidate_array_bounds(wire, model.structured_schema)
                derived = materialize_inline_response(
                    wire, entity_identity_property=model.config.metadata["response_contract"]["entity_identity_property"],
                )
                parse_normalized_planner_response(derived, request)
                _validate_grounded_shape(derived)
                feedback(derived, request)
            except (ValueError, KeyError, TypeError) as error:
                validation_error = str(error)
            _require(validation_error is not None, "refused repair must follow invalid wire evidence")
            sent.append(provider._repair_payload(initial, raw, validation_error))
    _same(len(sent), len(checks), "all checked payloads reconstructed")
    for payload, check in zip(sent, checks):
        _same(content_hash(payload), check["payload_sha256"], "reconstructed token-check payload")
    return tuple(sent)


def reconstruct_guarded_query(
    *, state: Mapping[str, Any], question: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
    model: ModelBundle, catalog: Any, semantic: DirectionalOntologyDeviation,
    retrieval_k: int, prompt_limit: int,
) -> ReconstructedGuardedQuery:
    """Verify one query against freshly retrieved, reference-free context.

    The enclosing reader supplies the frozen question, catalog and model. A
    passing query does not admit their provenance or the complete experiment.
    Original timing is checked for consistency, never regenerated or imputed.
    """
    state = deepcopy(state)
    _same(state["question"], question, "frozen inference question")
    strict_inference_leakage_audit(question)
    qid = str(question["question_id"])
    query_events = [e for e in events if e.get("question_id") == qid]
    _same(state["schema_version"], "grailqa-semantic-capability-query-state-v1", "typed query state schema")
    _same(state["candidate_grounding_policy"], SEMANTIC_GROUNDING_POLICY, "typed grounding policy")
    retrieval = catalog.retrieve(qid, str(question["text"]), top_k=retrieval_k)
    saved_retrieval = {key: value for key, value in state["retrieval"].items() if key != "latency_seconds"}
    _same(saved_retrieval, retrieval.to_dict(), "catalog retrieval reconstruction")
    _same(state["retrieval_latency_seconds"], state["retrieval"]["latency_seconds"], "retrieval time copy")
    for key in ("retrieval_latency_seconds", "llm_latency_seconds", "deterministic_latency_seconds"):
        value = state[key]
        _require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "finite recorded query latency")

    expected = {"candidates": [], "semantic_scores": [], "structured_response": None,
                "prompt_view": None, "returned_candidate_count": 0}
    request, view, provider_evidence, payloads = None, None, None, ()
    if not retrieval.types or not retrieval.relations:
        _same(state["request_records"], [], "retrieval failure has no request")
        _same(state["response_record"], {}, "retrieval failure has no invocation")
        _require(not any(e.get("event") not in ("query_started", "query_inference_completed")
                         for e in query_events), "retrieval failure has no external events")
        expected.update(api_call_completed=False, repair_calls=0, terminal=True,
                        llm_latency_seconds=0.0, deterministic_latency_seconds=0.0,
                        failure=_failure(qid, "retrieval_miss", "No bounded type or relation context was available."))
    else:
        view = catalog.prompt_view(retrieval, candidates_per_slot=prompt_limit, max_entities=prompt_limit)
        request = build_inference_request(question, retrieval, view, model.config.candidate_count)
        provider_evidence = audit_inline_query_evidence(state=state, events=query_events, model=model)
        payloads = _checked_payloads(state=state, events=query_events, request=request, view=view, model=model)
        invocation = state["response_record"]
        expected.update(llm_latency_seconds=invocation["latency_seconds"], repair_calls=invocation["repair_calls"])
        if provider_evidence["provider_succeeded"]:
            wire = _structured_content(invocation["raw_responses"][-1])
            derived = materialize_inline_response(
                wire, entity_identity_property=model.config.metadata["response_contract"]["entity_identity_property"],
            )
            candidates, scores, failure = _candidate_records(derived, request, view, semantic)
            expected.update(candidates=candidates, semantic_scores=scores, failure=failure,
                            structured_response=derived, prompt_view=view.to_dict(),
                            returned_candidate_count=len(derived["candidates"]), api_call_completed=True,
                            terminal=True, provider_id=invocation["provider"])
        else:
            expected.update(api_call_completed=False, terminal=False, deterministic_latency_seconds=0.0,
                            failure=_failure(qid, "malformed_output", invocation["error_message"] or "Provider request failed."))
    for key, value in expected.items():
        _same(state.get(key), value, "reconstructed query field: " + key)
    return ReconstructedGuardedQuery(
        qid, request, view, payloads, tuple(expected["candidates"]),
        tuple(expected["semantic_scores"]), provider_evidence,
    )
