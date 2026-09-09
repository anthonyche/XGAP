"""Opt-in typed/grounded candidate feedback within one existing repair budget.

No ranking, gold, ontology-distance threshold, lowering or backend invocation is
consulted here. An unsupported but valid interpretation is not a repair reason.
Original model responses remain unchanged, including rejected sibling rows.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Callable, Mapping

from xgap.experiments.grailqa_candidate_grounding import (
    SEMANTIC_GROUNDING_POLICY, ground_canonical_candidates,
)
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.runtime_alignment import PromptSchemaView, RuntimeAlignmentError
from xgap.llm.schemas import PlannerRequest
from xgap.pattern.semantic_validation import type_check_semantic_path_pattern
from xgap.pattern.typecheck import PatternTypeError


SCHEMA_ONLY = "schema_only_v1"
TYPED_GROUNDING_ONCE = "typed_grounding_one_repair_v1"
MAX_DETAIL_CHARACTERS = 256
MAX_CANDIDATES = 3


def validate_repair_policy(value: object, grounding_policy: str) -> str:
    if not isinstance(value, str) or value not in (SCHEMA_ONLY, TYPED_GROUNDING_ONCE):
        raise ValueError("Unknown GrailQA candidate repair policy.")
    if value == TYPED_GROUNDING_ONCE and grounding_policy != SEMANTIC_GROUNDING_POLICY:
        raise ValueError("Typed grounding repair requires the semantic grounding v2 policy.")
    return value


class CandidateContractFeedback(ValueError):
    """An expected contract violation eligible for the provider's one repair."""


class CandidateFeedbackProtocolError(RuntimeError):
    """Internal, binding and persistence errors are not model repair requests."""


def _issue(code: str, error: object) -> dict[str, Any]:
    detail = str(error)
    return {"code": code, "detail": detail[:MAX_DETAIL_CHARACTERS],
            "detail_truncated": len(detail) > MAX_DETAIL_CHARACTERS}


class GroundedCandidateFeedback:
    """Single-request callback; journal every assessed response before repair."""

    def __init__(self, record: Callable[[Mapping[str, Any]], None]) -> None:
        self._record = record
        self._view: PromptSchemaView | None = None
        self._request_hash: str | None = None
        self.records: list[dict[str, Any]] = []
        self.journal_failed = False

    def bind(self, request: PlannerRequest, view: PromptSchemaView) -> None:
        if (self._view is not None or not isinstance(view, PromptSchemaView)
                or view.task_id != request.metadata.get("task_id")
                or view.to_dict() != request.metadata.get("prompt_schema_view")
                or type(request.max_candidates) is not int
                or not 1 <= request.max_candidates <= MAX_CANDIDATES):
            raise CandidateFeedbackProtocolError("Candidate feedback request/view binding is invalid.")
        self._view = deepcopy(view)
        self._request_hash = content_hash(request.to_dict())

    def __call__(self, raw: Mapping[str, Any], request: PlannerRequest) -> None:
        try:
            request_hash = content_hash(request.to_dict())
            response_hash = content_hash(raw)
        except (TypeError, ValueError) as error:
            raise CandidateFeedbackProtocolError("Candidate feedback identity is not JSON-safe.") from error
        if (self._view is None or self._request_hash != request_hash
                or self._view.to_dict() != request.metadata.get("prompt_schema_view")
                or len(self.records) >= 2):
            raise CandidateFeedbackProtocolError("Candidate feedback request changed or call bound exceeded.")
        # Parsing already passed in the provider. Unexpected implementation
        # defects must escape its ValueError/TypeError-based repair boundary.
        try:
            report = self._assess(raw, request)
        except Exception as error:
            raise CandidateFeedbackProtocolError("Candidate feedback assessment failed internally.") from error
        event = {
            "event": "candidate_contract_feedback", "schema_version": "grailqa-candidate-feedback-v1",
            "question_id": self._view.task_id, "policy": TYPED_GROUNDING_ONCE,
            "assessment_index": len(self.records) + 1,
            "source_response_sha256": response_hash, "request_sha256": self._request_hash,
            "prompt_view_sha256": self._view.view_hash, **report,
            "no_valid_candidate": report["valid_candidate_count"] == 0,
            "feedback_detail_character_limit": MAX_DETAIL_CHARACTERS,
            "gold_used": False, "lowering_consulted": False,
        }
        try:
            self._record(deepcopy(event))
        except Exception as error:
            self.journal_failed = True
            raise CandidateFeedbackProtocolError("Candidate feedback journal failed; no repair may be sent.") from error
        self.records.append(event)
        if event["no_valid_candidate"]:
            # This bounds diagnostic details only, never the preserved raw
            # response or assembled request. The normal token guard still runs.
            feedback = {key: event[key] for key in ("shared_issue", "candidate_issues")}
            raise CandidateContractFeedback(
                "No typed, prompt-grounded candidate. Repair the contract using only the supplied "
                "prompt IDs and actual AST component paths; do not invent identities or alter "
                "question constraints. Diagnostics: " + json.dumps(feedback, ensure_ascii=True, sort_keys=True)
            )

    def _assess(self, raw: Mapping[str, Any], request: PlannerRequest) -> dict[str, Any]:
        parsed = parse_normalized_planner_response(raw, request)
        try:
            batch = ground_canonical_candidates(raw, parsed, self._view)
        except RuntimeAlignmentError as error:
            return {"valid_candidate_count": 0, "shared_issue": _issue("shared_grounding", error),
                    "candidate_issues": []}
        issues = []
        valid = 0
        for index, candidate in enumerate(parsed.candidates, start=1):
            failure = batch.failures.get(candidate.candidate_id)
            if failure is not None:
                issues.append({"candidate_index": index, **_issue(failure.code, failure.message)})
                continue
            try:
                type_check_semantic_path_pattern(candidate.pattern_query)
            except PatternTypeError as error:
                issues.append({"candidate_index": index, **_issue("semantic_type_check", error)})
            else:
                valid += 1
        return {"valid_candidate_count": valid, "shared_issue": None, "candidate_issues": issues}
