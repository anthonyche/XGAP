"""Typed semantic contracts and logical capabilities are different gates."""

from dataclasses import replace
import copy
from unittest.mock import Mock

import pytest

from xgap.algebra.conditions import (
    And, EdgeRef, LabelEquals, LengthEquals, NodeNotEquals, NodeRef, Not, Or,
    PropertyEquals, PropertyNotEquals, PropertyLessThan, PropertyLessThanOrEqual,
    PropertyGreaterThan, PropertyGreaterThanOrEqual,
)
from xgap.llm.candidate_assessment import assess_candidate
from xgap.llm.schemas import CandidateValidationReport, PlannerCandidate
from xgap.llm.validation import validate_candidate
from xgap.pattern.ast import (
    Alt, Bounded, Direction, EdgePattern, NodePattern, OptionalExpr, PathMode,
    PathPatternQuery, Plus, Rel, Selector, SelectorKind, Seq, Star, Var,
)
from xgap.pattern.semantic_validation import type_check_semantic_path_pattern


def candidate(expr=None, condition=None, **kwargs):
    query = PathPatternQuery(
        None, NodePattern(label="Person"), expr or Rel(EdgePattern(label="Knows")),
        NodePattern(label="Person"), Selector(SelectorKind.ALL), PathMode.TRAIL,
        condition=condition,
    )
    return PlannerCandidate("fixture question", replace(query, **kwargs))


@pytest.mark.parametrize("direction", list(Direction))
def test_direction_is_not_erased_or_mistaken_for_semantic_error(direction):
    c = candidate(Rel(EdgePattern(label="Knows", direction=direction)))
    before = copy.deepcopy(c)
    report = assess_candidate(c)
    assert report.semantic_validation.ok
    logical = report.logical_lowering.to_dict()
    assert logical["available"] and logical["status"] == "available"
    assert logical["profile"] == "m5_path_algebra_orientation_v1"
    assert logical["backend_execution_verified"] is False
    assert c == before
    assert logical["issues"] == []
    assert validate_candidate(c).stage == "validated"
    if direction is not Direction.OUT:
        assert "Reverse" in logical["report"]["formatted_plan"]


@pytest.mark.parametrize("wrapper,code", [
    (OptionalExpr, "optional_regex_unsupported"),
    (lambda child: Bounded(child, 1, 3), "bounded_regex_unsupported"),
])
def test_all_missing_features_are_recorded_in_ast_order(wrapper, code):
    expr = wrapper(Rel(EdgePattern(label="R", direction=Direction.IN)))
    report = assess_candidate(candidate(Seq(Rel(EdgePattern()), expr)))
    assert report.semantic_validation.ok
    assert [item.to_dict() for item in report.logical_lowering.issues] == [
        {"code": code, "component_ref": "expr.right"},
    ]


@pytest.mark.parametrize("condition_class", [LabelEquals, PropertyEquals, PropertyNotEquals,
    PropertyLessThan, PropertyLessThanOrEqual, PropertyGreaterThan, PropertyGreaterThanOrEqual])
@pytest.mark.parametrize("ref", [NodeRef(3), EdgeRef(2), NodeRef(0), EdgeRef(-1), NodeRef(True), EdgeRef(1.5)])
def test_every_condition_reference_is_checked_recursively(condition_class, ref):
    condition = condition_class(ref, "Person") if condition_class is LabelEquals else condition_class(ref, "age", 2)
    c = candidate(condition=And(LengthEquals(1), Not(Or(condition, LengthEquals(0)))))
    assessment = assess_candidate(c)
    assert assessment.semantic_validation.ok is False
    assert assessment.logical_lowering.status == "not_assessed"


@pytest.mark.parametrize("ref", [NodeRef.first(), NodeRef.last(), NodeRef(1), NodeRef(2), EdgeRef(1)])
def test_valid_scalar_refs_remain_valid(ref):
    assessment = assess_candidate(candidate(condition=PropertyGreaterThanOrEqual(ref, "amount", 2)))
    assert assessment.semantic_validation.ok
    assert assessment.logical_lowering.status == "available"


@pytest.mark.parametrize("expr", [Plus(Rel(EdgePattern())), Star(Rel(EdgePattern())),
    Alt(Rel(EdgePattern()), Seq(Rel(EdgePattern()), Rel(EdgePattern())))])
@pytest.mark.parametrize("ref,valid", [(NodeRef.first(), True), (NodeRef.last(), True), (NodeRef(1), False), (EdgeRef(1), False)])
def test_numeric_variable_length_refs_require_explicit_bounds(expr, ref, valid):
    assessment = assess_candidate(candidate(expr, PropertyEquals(ref, "age", 1)))
    assert assessment.semantic_validation.ok is valid


@pytest.mark.parametrize("value", [True, 1.5, 0, -1])
def test_selector_and_depth_are_strict_integers(value):
    assert not assess_candidate(candidate(selector=Selector(SelectorKind.ANY_K, value))).semantic_validation.ok
    assert not assess_candidate(candidate(max_depth=value)).semantic_validation.ok


@pytest.mark.parametrize("value", [True, "3", None, float("inf"), float("nan"), [], {}])
def test_numeric_condition_constant_is_not_coerced(value):
    report = assess_candidate(candidate(condition=PropertyLessThan(NodeRef.first(), "age", value)))
    assert report.semantic_validation.ok is False


@pytest.mark.parametrize("condition", [
    NodeNotEquals(NodeRef(1), EdgeRef(1)), LabelEquals(NodeRef("middle"), "Person"),
    PropertyEquals(NodeRef.first(), "", 3), LengthEquals(True), LengthEquals(1.5),
    LabelEquals(NodeRef.first(), []), Not(None), And(None), Or(None), object(),
])
def test_malformed_conditions_fail_closed(condition):
    assert not assess_candidate(candidate(condition=condition)).semantic_validation.ok


@pytest.mark.parametrize("expr", [Bounded(Rel(EdgePattern()), True, 2),
    Bounded(Rel(EdgePattern()), 0, 1.5), Bounded(Rel(EdgePattern()), 2, 1)])
def test_malformed_bounds_cannot_be_disguised_as_unavailable(expr):
    report = assess_candidate(candidate(expr))
    assert not report.semantic_validation.ok
    assert report.logical_lowering.status == "not_assessed"


def test_semantic_validation_never_calls_lowerer(monkeypatch):
    lower = Mock(side_effect=AssertionError("must not lower"))
    monkeypatch.setattr("xgap.llm.candidate_assessment.validate_candidate", lower)
    c = candidate(OptionalExpr(Rel(EdgePattern(direction=Direction.IN))))
    type_check_semantic_path_pattern(c.pattern_query)
    report = assess_candidate(c)
    assert report.semantic_validation.ok
    lower.assert_not_called()


def test_unexpected_lowerer_failure_is_an_error_not_declared_unavailability(monkeypatch):
    monkeypatch.setattr("xgap.llm.candidate_assessment.validate_candidate", Mock(return_value=
        CandidateValidationReport("candidate-1", False, "lowering", "unexpected failure")))
    report = assess_candidate(candidate())
    assert report.semantic_validation.ok
    assert report.logical_lowering.status == "error"
    assert report.logical_lowering.issues == ()
    assert not report.logical_lowering.to_dict()["available"]


def test_unexpected_lowerer_exception_cannot_claim_execution(monkeypatch):
    monkeypatch.setattr("xgap.llm.candidate_assessment.validate_candidate", Mock(side_effect=RuntimeError("broken formatter")))
    report = assess_candidate(candidate())
    assert report.semantic_validation.ok
    assert report.logical_lowering.status == "error"
    assert report.logical_lowering.report.stage == "capability_error"
    assert not report.logical_lowering.to_dict()["available"]


def test_variable_conflicts_and_unsafe_walk_remain_semantic_errors():
    assert not assess_candidate(candidate(source=NodePattern(Var("x")),
        expr=Rel(EdgePattern(Var("x"))))).semantic_validation.ok
    assert not assess_candidate(candidate(Plus(Rel(EdgePattern())), restrictor=PathMode.WALK)).semantic_validation.ok
