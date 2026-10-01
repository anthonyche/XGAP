"""Bounded natural-language question orchestration over existing components.

The catalog and model are injected, as are already loaded backend clients.
This development path does not open references, mutate facts, rank meanings
by physical cost, or change a frozen GrailQA protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Any, Callable, Mapping, Protocol

from xgap.experiments.freebase_candidate_compiler import ExecutionRequirements, FreebaseExecutionMapping
from xgap.experiments.freebase_candidate_execution import execute_candidate, prepare_candidate_batch
from xgap.experiments.grailqa_semantic_pilot import (
    SemanticPilotProvider, build_inference_request, strict_inference_leakage_audit,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.runtime_alignment import PromptSchemaView
from xgap.llm.schemas import PlannerRequest


class QuestionCatalog(Protocol):
    def retrieve(self, question_id: str, question: str, *, top_k: int) -> Any: ...
    def prompt_view(self, result: Any, *, candidates_per_slot: int, max_entities: int) -> PromptSchemaView: ...


@dataclass(frozen=True)
class QuestionBudget:
    candidate_cap: int = 3
    retrieval_k: int = 20
    prompt_limit: int = 4
    max_rows: int = 10000
    max_binding_bytes: int = 4 * 1024 * 1024
    max_backend_calls: int = 4
    deadline_seconds: float = 900.0

    def __post_init__(self) -> None:
        import math
        integers = (self.candidate_cap, self.retrieval_k, self.prompt_limit, self.max_rows,
                    self.max_binding_bytes, self.max_backend_calls)
        if any(type(v) is not int or v <= 0 for v in integers) or self.candidate_cap > 3:
            raise ValueError("Question budgets must be finite positive integers, with at most three candidates")
        if (type(self.deadline_seconds) not in (int, float)
                or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0):
            raise ValueError("A finite positive question deadline is required")


def run_grounded_question(*, request: PlannerRequest, view: PromptSchemaView,
                         mapping: FreebaseExecutionMapping, requirements: ExecutionRequirements,
                         provider: SemanticPilotProvider, neo4j: Any, fuseki: Any,
                         budget: QuestionBudget = QuestionBudget(), verify_baseline: bool = False,
                         clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """Generate, validate, choose a unique supported meaning, and execute once.

    Multiple entity choices require explicit caller-owned positional bindings
    before model invocation. Multiple distinct candidate programs remain an
    ambiguity; unsupported but well-formed siblings cannot be silently dropped
    in favour of a conveniently executable interpretation.

    The deadline is checked between stages. Clients/provider own their finite
    per-call timeouts; this API does not promise in-flight cancellation.
    """
    started = clock()
    stage = "input"
    report: dict[str, Any] = {
        "schema_version": "freebase-question-v1", "question": request.question,
        "question_id": view.task_id, "status": "incomplete", "success": False,
        "mapping": mapping.to_dict(), "execution_requirements": requirements.to_dict(),
        "answer_scope": "declared_snapshot", "global_completeness_verified": False,
        "question_correctness_verified": False, "paper_result": False,
        "stages": [], "model_calls": 0, "backend_calls": 0,
    }

    def stop(status: str, reason: str) -> dict[str, Any]:
        report.update(status=status, reason=reason, end_to_end_wall_seconds=clock()-started)
        return report

    def expired() -> bool:
        return clock()-started >= budget.deadline_seconds

    def measured(name: str, action: Callable[[], Any]) -> Any:
        nonlocal stage
        stage = name
        before = clock()
        try:
            return action()
        finally:
            report["stages"].append({"stage": name, "wall_seconds": clock()-before})

    try:
        strict_inference_leakage_audit(request.to_dict())
        if (request.metadata.get("prompt_schema_view") != view.to_dict()
                or request.metadata.get("task_id") != view.task_id
                or type(request.max_candidates) is not int
                or not 1 <= request.max_candidates <= budget.candidate_cap
                or type(verify_baseline) is not bool):
            raise ValueError("Question input identity or candidate budget mismatch")
        visible = set(view.visible_entity_ids)
        required_ids = {identity for _, identity in requirements.required_bindings}
        if required_ids - visible:
            return stop("grounding_unavailable", "A required identity is absent from the prompt context")
        if requirements.require_entity_anchor and not required_ids and len(visible) != 1:
            report["identity_candidates"] = [dict(entity) for entity in view.entities]
            return stop("clarification_required" if visible else "grounding_unavailable",
                        "An anchored question requires an unambiguous catalog identity or explicit confirmed bindings")
        # Tell the model the caller's goal, and preserve exactly this augmented
        # request throughout generation and candidate preparation.
        contract = {"kind": "execution_goal_v1", **requirements.to_dict()}
        request = replace(request, metadata={**request.metadata, "grounding_contracts": [
            *request.metadata.get("grounding_contracts", ()), contract]})
        report.update(request=request.to_dict(), prompt_view=view.to_dict(), request_sha256=content_hash(request.to_dict()))
        if expired():
            return stop("budget_exhausted", "Deadline reached before model invocation")
        report["model_calls"] = None  # Unknown if an injected provider raises without a ledger.
        generation = measured("generation", lambda: provider.generate(request, view))
        report["generation"] = {
            "structured_response": generation.structured_response,
            "request_records": list(generation.request_records), "response_record": dict(generation.response_record),
            "api_call_completed": generation.api_call_completed, "repair_calls": generation.repair_calls,
            "latency_seconds": generation.latency_seconds, "error": generation.error,
        }
        invocation = generation.response_record
        counts = (invocation.get("generation_calls"), invocation.get("repair_calls"))
        if all(type(n) is int and n >= 0 for n in counts):
            report["model_calls"] = sum(counts)
        if not generation.api_call_completed or generation.structured_response is None:
            return stop("generation_failed", "Provider did not return an accepted structured response")
        if expired():
            return stop("budget_exhausted", "Deadline reached after model invocation")
        prepared = measured("preparation", lambda: prepare_candidate_batch(
            generation.structured_response, request, view, mapping, requirements,
            max_rows=budget.max_rows, max_binding_bytes=budget.max_binding_bytes))
        report["preparation"] = prepared.evidence
        if not prepared.programs:
            return stop("no_executable_candidate", "All candidate outcomes are retained in preparation")
        if any(row["stage"] == "execution_unavailable" for row in prepared.evidence["candidates"]):
            return stop("interpretation_unresolved", "A valid sibling has an unresolved execution requirement")
        meanings = {program.input_pattern_sha256 for program in prepared.programs.values()}
        if len(meanings) != 1:
            return stop("clarification_required", "Distinct query meanings remain; no cost-based semantic choice was made")
        candidate_id, program = next(iter(prepared.programs.items()))
        report["selection"] = {"policy": "unique_structural_program_v1", "candidate_id": candidate_id,
                               "equivalent_candidate_ids": list(prepared.programs),
                               "input_pattern_sha256": program.input_pattern_sha256}
        calls = sum(node.kind.value in {"remote_query", "remote_bind_query"} for node in program.plan.nodes)
        if calls + int(verify_baseline) > budget.max_backend_calls or expired():
            return stop("budget_exhausted", "Execution exceeds the remaining deadline or backend-call budget")
        execution = measured("execution", lambda: execute_candidate(
            program, neo4j=neo4j, fuseki=fuseki, verify_baseline=verify_baseline))
        report["execution"] = execution
        report["backend_calls"] = execution["federated"]["total_remote_calls"] + execution["baseline_remote_calls"]
        if execution["execution_success"]:
            report.update(answers=execution["answers"], answer_count=execution["answer_count"])
        if expired():
            return stop("budget_exhausted", "Deadline exceeded during execution; completed evidence is retained")
        if not execution["success"]:
            return stop("verification_failed" if execution["execution_success"] else "execution_failed",
                        "See separately retained execution and verification outcomes")
        report["success"] = True
        return stop("answered", "Answer is for the selected interpretation on the declared snapshot")
    except Exception as error:
        # Provider transport details are in its credential-safe journal. Avoid
        # persisting arbitrary exception strings from injected components.
        report["error"] = {"stage": stage, "type": type(error).__name__}
        return stop("failed", "A stage raised an exception; no retry was attempted")


def answer_question(*, question_record: Mapping[str, Any], catalog: QuestionCatalog,
                    provider_factory: Callable[[str], SemanticPilotProvider],
                    mapping: FreebaseExecutionMapping, requirements: ExecutionRequirements,
                    neo4j: Any, fuseki: Any, budget: QuestionBudget = QuestionBudget(),
                    verify_baseline: bool = False) -> dict[str, Any]:
    """Build inference-only catalog context, then use the same execution entry."""
    started = time.perf_counter()
    strict_inference_leakage_audit(question_record)
    qid, text = question_record["question_id"], question_record["text"]
    if not isinstance(qid, str) or not qid or not isinstance(text, str) or not text.strip():
        raise ValueError("Question ID and natural-language text must be nonempty strings")
    try:
        retrieval = catalog.retrieve(qid, text, top_k=budget.retrieval_k)
        view = catalog.prompt_view(retrieval, candidates_per_slot=budget.prompt_limit, max_entities=budget.prompt_limit)
        request = build_inference_request(question_record, retrieval, view, budget.candidate_cap)
    except Exception as error:
        return {"status": "retrieval_failed", "success": False, "question_id": qid,
                "error_type": type(error).__name__, "model_calls": 0, "backend_calls": 0,
                "end_to_end_wall_seconds": time.perf_counter()-started, "paper_result": False}
    elapsed = time.perf_counter()-started
    if elapsed >= budget.deadline_seconds:
        return {"status": "budget_exhausted", "success": False, "question_id": qid,
                "reason": "Catalog retrieval exhausted the deadline", "model_calls": 0, "backend_calls": 0,
                "retrieval_wall_seconds": elapsed, "paper_result": False}
    try:
        provider = provider_factory(qid)
    except Exception as error:
        return {"status": "provider_unavailable", "success": False, "question_id": qid,
                "error_type": type(error).__name__, "model_calls": 0, "backend_calls": 0,
                "end_to_end_wall_seconds": time.perf_counter()-started, "paper_result": False}
    remaining = budget.deadline_seconds - (time.perf_counter()-started)
    if remaining <= 0:
        return {"status": "budget_exhausted", "success": False, "question_id": qid,
                "reason": "Provider construction exhausted the deadline", "model_calls": 0, "backend_calls": 0,
                "end_to_end_wall_seconds": time.perf_counter()-started, "paper_result": False}
    result = run_grounded_question(request=request, view=view, mapping=mapping, requirements=requirements,
        provider=provider, neo4j=neo4j, fuseki=fuseki,
        budget=replace(budget, deadline_seconds=remaining), verify_baseline=verify_baseline)
    result.update(retrieval=retrieval.to_dict(), retrieval_wall_seconds=elapsed)
    result["end_to_end_wall_seconds"] = time.perf_counter()-started
    return result
