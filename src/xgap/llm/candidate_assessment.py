"""Separate semantic contract validity from the available logical lowerer.

Logical-plan availability is not backend executability. Native compilation,
plugin capability admission and execution are deliberately not performed here.
The legacy validate_candidate API remains unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from xgap.llm.schemas import CandidateValidationReport, PlannerCandidate
from xgap.llm.validation import validate_candidate
from xgap.pattern.ast import Alt, Bounded, Direction, OptionalExpr, Plus, Rel, Seq, Star
from xgap.pattern.semantic_validation import PROFILE, type_check_semantic_path_pattern


@dataclass(frozen=True)
class LoweringIssue:
    code: str
    component_ref: str

    def to_dict(self):
        return {"code": self.code, "component_ref": self.component_ref}


@dataclass(frozen=True)
class LogicalLoweringAssessment:
    status: str
    issues: tuple[LoweringIssue, ...] = ()
    report: CandidateValidationReport | None = None

    def to_dict(self):
        return {
            "schema_version": "logical_lowering_assessment_v1",
            "profile": "m5_path_algebra_lowerer",
            "status": self.status,
            "available": self.status == "available",
            "issues": [item.to_dict() for item in self.issues],
            "report": self.report.to_dict() if self.report is not None else None,
            "backend_execution_verified": False,
        }


@dataclass(frozen=True)
class CandidateAssessment:
    semantic_validation: CandidateValidationReport
    logical_lowering: LogicalLoweringAssessment


def assess_candidate(candidate: PlannerCandidate) -> CandidateAssessment:
    """No execution, AST rewrite, direction erasure, fallback or model call."""
    try:
        type_check_semantic_path_pattern(candidate.pattern_query)
    except Exception as error:  # report boundary preserves unexpected failures
        return CandidateAssessment(
            CandidateValidationReport(candidate.candidate_id, False, "semantic_type_check", str(error),
                                      metadata={"profile": PROFILE}),
            LogicalLoweringAssessment("not_assessed"),
        )
    validation = CandidateValidationReport(
        candidate.candidate_id, True, "semantic_validated",
        "Typed path-intent checks passed; this is not logical/backend execution admission.",
        metadata={"profile": PROFILE},
    )
    issues = tuple(_missing_capabilities(candidate.pattern_query.expr, "expr"))
    if issues:
        return CandidateAssessment(validation, LogicalLoweringAssessment("unavailable", issues))
    try:
        report = validate_candidate(candidate)
    except Exception as error:  # preserve unexpected implementation errors as evidence
        report = CandidateValidationReport(candidate.candidate_id, False, "capability_error", str(error))
    # An unexpected lowerer failure is not fabricated as a declared unsupported
    # feature and cannot turn semantic validity into execution availability.
    return CandidateAssessment(validation, LogicalLoweringAssessment(
        "available" if report.ok else "error", report=report,
    ))


def _missing_capabilities(expr, path):
    if isinstance(expr, Rel):
        if expr.edge.direction is not Direction.OUT:
            yield LoweringIssue(f"direction_{expr.edge.direction.name.lower()}_unsupported", f"{path}.edge")
    elif isinstance(expr, (Seq, Alt)):
        yield from _missing_capabilities(expr.left, f"{path}.left")
        yield from _missing_capabilities(expr.right, f"{path}.right")
    elif isinstance(expr, (Plus, Star, OptionalExpr, Bounded)):
        if isinstance(expr, OptionalExpr):
            yield LoweringIssue("optional_regex_unsupported", path)
        elif isinstance(expr, Bounded):
            yield LoweringIssue("bounded_regex_unsupported", path)
        yield from _missing_capabilities(expr.child, f"{path}.child")
