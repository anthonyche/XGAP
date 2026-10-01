"""Grounded, model-owned answer projection through the ordinary P1 executor.

This opt-in experiment path never opens evaluation files or changes the frozen
semantic-only runner. Ontology deviation does not certify answer-position quality.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping

from xgap.agent.semantic_execution import BoundSemanticExecutionTool
from xgap.experiments.freebase_candidate_compiler import ExecutionRequirements, check_execution_anchors
from xgap.experiments.freebase_question import QuestionBudget
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_guarded_provider import GuardedSemanticPilotProvider
from xgap.experiments.grailqa_semantic_pilot import _infer_one, strict_inference_leakage_audit
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.experiments.resource_entity_answers import run_resource_entity_answers
from xgap.llm.parser import parse_path_pattern_query
from xgap.semantic.program import SemanticGraphProgram


SCHEMA_VERSION = "xgap-grounded-entity-answer-v1"
MODEL_ID = "qwen3_32b_vllm_cwru_entity_answers_v1"


@lru_cache(maxsize=1)
def _schema_validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise ValueError("Entity-answer experiments require the entity-answers optional dependency") from error
    schema = json.loads((Path(__file__).resolve().parents[3] / "models" / MODEL_ID /
                         "structured_schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def parse_entity_answer_response(raw, request):
    """Validate the new explicit answer fields, preserving the existing path parser."""
    strict_inference_leakage_audit(raw)
    error = next(_schema_validator().iter_errors(raw), None)
    if error is not None:
        location = ".".join(str(part) for part in error.absolute_path)
        raise ValueError(f"Entity-answer wire schema rejected {location}: {error.message}")
    if (not isinstance(raw, Mapping) or set(raw) != {
            "schema_version", "provider_id", "model", "query_slots", "candidates"}
            or raw["schema_version"] != SCHEMA_VERSION):
        raise ValueError("An explicit versioned entity-answer envelope is required")
    candidates = raw["candidates"]
    if (not isinstance(candidates, list) or not 1 <= len(candidates) <= min(3, request.max_candidates)):
        raise ValueError("Entity-answer candidates exceed the declared bounded pool")
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != {
                "candidate_id", "confidence", "rationale", "pattern_query", "grounding", "predicted_projection"}:
            raise ValueError("Every candidate must explicitly supply its predicted projection")
        projection = candidate["predicted_projection"]
        if (not isinstance(projection, Mapping) or set(projection) != {"kind", "position"}
                or projection["kind"] != "path_node"):
            raise ValueError("Predicted entity answers require a path_node projection")
        position = projection["position"]
        if not (type(position) is int and 1 <= position <= 4) and position not in ("first", "last"):
            raise ValueError("Predicted position must explicitly be first, last, or one to four")
        confidence = candidate["confidence"]
        if confidence is not None and (type(confidence) not in (int, float)
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("Candidate confidence must be finite in [0,1] or null")
    parsed = parse_normalized_planner_response(raw, request)
    if len({c.candidate_id for c in parsed.candidates}) != len(candidates):
        raise ValueError("Candidate IDs must be unique")
    # The raw response is retained separately; metadata also prevents projection
    # loss in callers that serialize only the existing PlannerCandidate record.
    return replace(parsed, candidates=tuple(replace(candidate, metadata={
        **candidate.metadata, "predicted_projection": dict(raw_candidate["predicted_projection"])
    }) for candidate, raw_candidate in zip(parsed.candidates, candidates)))


def build_entity_answer_provider(model, guard, journal, question_id, *, transport=None):
    """Use the existing token guard, journal and one-call production transport."""
    schema = _schema_validator().schema
    if (model.config.model_id != MODEL_ID or model.config.version != SCHEMA_VERSION
            or model.config.max_repair_calls != 0 or model.config.timeout_seconds > 120
            or model.config.metadata.get("response_contract") is not None
            or content_hash(model.structured_schema) != content_hash(schema)):
        raise ValueError("Entity-answer generation requires its separate zero-repair model bundle")
    base = build_openai_compatible_provider(model, transport, response_parser=parse_entity_answer_response)
    return GuardedSemanticPilotProvider(model, guard, journal, question_id, base_provider=base,
        grounding_policy=SEMANTIC_GROUNDING_POLICY)


class _BeforeGeneration(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class _OneGeneration:
    def __init__(self, provider, *, started, budget, require_anchor, confirmed_ids):
        self.provider = provider
        self.provider_id = provider.provider_id
        self.started, self.budget = started, budget
        self.require_anchor, self.required_ids = require_anchor, confirmed_ids
        self.entered = False
        self.request = self.view = self.result = None
        self.original_request = None

    def generate(self, request, view):
        self.original_request = request
        self.request, self.view = request, view
        visible = set(view.visible_entity_ids)
        if set(self.required_ids) - visible:
            raise _BeforeGeneration("grounding_unavailable", "Confirmed entity IDs must be prompt-visible")
        if self.require_anchor and not self.required_ids:
            if len(visible) != 1:
                raise _BeforeGeneration("clarification_required" if visible else "grounding_unavailable",
                    "An anchored question requires one catalog identity or explicitly confirmed IDs")
            self.required_ids = tuple(visible)
        self.request = replace(request, metadata={**request.metadata, "grounding_contracts": [
            *request.metadata.get("grounding_contracts", ()),
            {"kind": "entity_answer_goal_v1", "require_entity_anchor": self.require_anchor,
             "required_entity_ids": list(self.required_ids)}]})
        strict_inference_leakage_audit(self.request.to_dict())
        if self.entered or time.perf_counter() - self.started >= self.budget.deadline_seconds:
            raise _BeforeGeneration("budget_exhausted", "Generation is outside the one-call/deadline budget")
        self.entered = True
        self.result = self.provider.generate(self.request, view)
        return self.result

    def parse(self, raw, request):
        if request != self.original_request or self.request is None:
            raise ValueError("Inference parser request differs from the generated question")
        return parse_entity_answer_response(raw, self.request)


def _select(state, *, epsilon, policy):
    raw = {c["candidate_id"]: c for c in state["structured_response"]["candidates"]}
    eligible = []
    for row in state["candidates"]:
        if not row["validation"]["ok"] or not row["grounded"]:
            continue
        if policy == "semantic_bound" and (not row["semantic_admissible"]
                or row["semantic_deviation"] is None or row["semantic_deviation"] > epsilon):
            continue
        projection = raw[row["candidate_id"]]["predicted_projection"]
        meaning_hash = content_hash({"pattern_query": row["pattern_query"], "predicted_projection": projection})
        eligible.append({**row, "predicted_projection": dict(projection), "meaning_sha256": meaning_hash})
    eligible.sort(key=lambda row: (
        *((float(row["semantic_deviation"]),) if policy == "semantic_bound" else ()),
        -float(row["confidence"] or 0), row["meaning_sha256"], row["candidate_id"]))
    return eligible


def _program(selected):
    return SemanticGraphProgram.from_dict({"program_id": "entity-answer-" + selected["meaning_sha256"],
        "operators": [
            {"operator_id": "traverse", "kind": "traverse", "input_ids": [], "input_kinds": [],
             "output_kind": "path_set", "parameters": {"path_pattern": selected["pattern_query"]}},
            {"operator_id": "answer", "kind": "project", "input_ids": ["traverse"],
             "input_kinds": ["path_set"], "output_kind": "binding_set", "parameters": {
                 "projections": {"answer": selected["predicted_projection"]}}}], "roots": ["answer"],
        "metadata": {"inferred_meaning_sha256": selected["meaning_sha256"],
                     "candidate_id": selected["candidate_id"], "answer_origin": "model_prediction"}})


def run_entity_answer_question(*, question, catalog, provider, semantic, source_id,
        sources, backends, backend_clients, require_entity_anchor: bool,
        confirmed_entity_ids=(), epsilon=0.0, selection_policy="semantic_bound",
        budget: QuestionBudget = QuestionBudget(), static_backend_order=None):
    """Infer one bounded pool, select meaning without gold, and execute once."""
    started = time.perf_counter()
    record: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "success": False,
        "status": "input_failed", "inference": None, "execution": None,
        "model_calls": 0, "input_tokens": 0, "output_tokens": 0,
        "backend_remote_calls": 0, "automatic_retries": 0, "paper_result": False,
        "question_correctness_verified": False, "projection_covered_by_epsilon": False,
        "selection_policy": selection_policy, "epsilon": epsilon}
    limited = None
    try:
        strict_inference_leakage_audit(question)
        _schema_validator()  # Resolve the optional validator before any model work.
        if (type(require_entity_anchor) is not bool or selection_policy not in {"semantic_bound", "model_top1"}
                or type(epsilon) not in (int, float) or not math.isfinite(epsilon) or not 0 <= epsilon <= 1):
            raise ValueError("Invalid explicit entity requirement, policy or epsilon")
        ids = tuple(confirmed_entity_ids)
        if (any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids)
                or isinstance(confirmed_entity_ids, str)):
            raise ValueError("Confirmed entity IDs must be a unique explicit sequence")
        if (not isinstance(question.get("question_id"), str) or not question["question_id"]
                or not isinstance(question.get("text"), str) or not question["text"].strip()):
            raise ValueError("Question ID and text must be explicit nonempty strings")
        source = sources[source_id]
        # This profile has one fixed-path source query per replica and one
        # selected execution. Reserve all cold observations before generation.
        maximum_calls = 1 + (len(source.replica_backend_ids) if static_backend_order is None else 0)
        if maximum_calls > budget.max_backend_calls:
            record["status"] = "budget_exhausted"
            record["error"] = "Declared observation and execution calls exceed the backend budget"
            return record
        limited = _OneGeneration(provider, started=started, budget=budget,
            require_anchor=require_entity_anchor, confirmed_ids=ids)
        record["status"] = "inference_failed"
        state = _infer_one(question=question, catalog=catalog, provider=limited, semantic=semantic,
            retrieval_k=budget.retrieval_k, candidate_cap=budget.candidate_cap,
            prompt_candidates_per_slot=budget.prompt_limit,
            response_parser=limited.parse, grounding_policy=SEMANTIC_GROUNDING_POLICY)
        record["inference"] = state
        record["status"] = "inference_failed"
        invocation = limited.result.response_record if limited.result is not None else {}
        generation_count, repair_count = (invocation.get(k) for k in ("generation_calls", "repair_calls"))
        invalid_counts = any(n is not None and (type(n) is not int or n < 0)
                             for n in (generation_count, repair_count))
        if (state.get("repair_calls", 0) != 0 or invalid_counts
                or (generation_count is not None and generation_count > 1)
                or (repair_count is not None and repair_count != 0)
                or (state.get("api_call_completed") and generation_count == 0)
                or ((state.get("structured_response") or state.get("candidates"))
                    and state.get("api_call_completed") is not True)):
            record["status"] = "provider_contract_failed"
            record["error"] = "The provider's reported calls violate the one-generation/zero-repair contract"
            return record
        if time.perf_counter() - started >= budget.deadline_seconds:
            record["status"] = "budget_exhausted"
            return record
        if not state.get("structured_response") or not state.get("candidates"):
            return record
        ranking = _select(state, epsilon=epsilon, policy=selection_policy)
        record["ranking"] = [{key: row[key] for key in (
            "candidate_id", "meaning_sha256", "predicted_projection", "semantic_deviation", "confidence")}
            for row in ranking]
        if not ranking:
            record["status"] = "no_admissible_meaning"
            return record
        selected = ranking[0]
        record["selection"] = record["ranking"][0]
        record["status"] = "selected_meaning_unavailable"
        anchors = check_execution_anchors(parse_path_pattern_query(selected["pattern_query"]),
            ExecutionRequirements(require_entity_anchor))
        if set(limited.required_ids) - {identity for _, identity in anchors}:
            record["error"] = "Selected meaning does not enforce every required entity identity"
            return record
        tool = BoundSemanticExecutionTool(_program(selected), {"traverse": source_id}, {}, sources,
            backends, backend_clients, max_candidates=len(source.replica_backend_ids),
            max_observation_calls=len(source.replica_backend_ids), max_remote_calls=1,
            static_backend_order=static_backend_order)
        execution = run_resource_entity_answers(tool, question["text"], max_answer_rows=budget.max_rows)
        record["execution"] = execution
        record["backend_remote_calls"] = execution["backend_remote_calls"]
        if time.perf_counter() - started >= budget.deadline_seconds:
            record["status"] = "budget_exhausted"
            return record
        record.update(success=execution["success"], status=execution["status"])
        if execution["success"]:
            record.update(answers=execution["answers"], answer_count=execution["answer_count"])
        return record
    except _BeforeGeneration as error:
        record.update(status=error.status, error=str(error))
        return record
    except Exception as error:
        # Retain safe provider journals, not arbitrary transport exception text.
        record["error_type"] = type(error).__name__
        return record
    finally:
        if limited is not None:
            record["required_entity_ids"] = list(limited.required_ids)
            if limited.request is not None:
                record["request"] = limited.request.to_dict()
                record["prompt_view"] = limited.view.to_dict()
            if limited.entered:
                record.update(model_calls=None, input_tokens=None, output_tokens=None)
                if limited.result is not None:
                    invocation = limited.result.response_record
                    record["generation_record"] = dict(invocation)
                    counts = [invocation.get(k) for k in ("generation_calls", "repair_calls")]
                    if all(type(n) is int and n >= 0 for n in counts):
                        record["model_calls"] = sum(counts)
                    usage = invocation.get("usage", {})
                    for key in ("input_tokens", "output_tokens"):
                        if type(usage.get(key)) is int and usage[key] >= 0:
                            record[key] = usage[key]
        record["end_to_end_ms"] = (time.perf_counter() - started) * 1000
