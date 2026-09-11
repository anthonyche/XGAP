"""Small structural replays of LINK's undeclared and misplaced source slots."""

from copy import deepcopy

import pytest

from test_question_interpretation import CASES, ControlledProvider, question_run
from xgap.experiments.toy_binding import interpretation_inputs
from xgap.semantic.interpretation import InterpretationRequest, SCHEMA, parse_interpretation


def payload():
    return {
        "schema_version": SCHEMA,
        "program": {
            "program_id": "source-admission",
            "operators": [
                {"operator_id": "people", "kind": "match", "input_ids": [],
                 "input_kinds": [], "output_kind": "binding_set",
                 "parameters": {"node": {"label": {"$hole": "person_type"}}}},
                {"operator_id": "eligible", "kind": "filter", "input_ids": ["people"],
                 "input_kinds": ["binding_set"], "output_kind": "binding_set",
                 "parameters": {}, "constraints": [{
                     "constraint_id": "age", "expression": "at least 30", "policy": "hard",
                     "predicate": {"op": "ge", "field": "age", "value": {"$hole": "age"}},
                 }]},
            ],
            "roots": ["eligible"],
            "holes": [
                {"hole_id": "source", "kind": "source", "mention": "toy graph"},
                {"hole_id": "person_type", "kind": "type", "mention": "people"},
                {"hole_id": "age", "kind": "constraint", "mention": "30"},
            ],
        },
        "operator_sources": {"people": {"$hole": "source"}},
    }


def request(context=None):
    return InterpretationRequest("Find people at least 30 in toy graph", context=context or {})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("undeclared_source", "Undeclared executable semantic hole 'source'"),
        ("source_toy_and_coordinator", "cover exactly Match/Traverse"),
        ("missing_source", "cover exactly Match/Traverse"),
        ("wrong_hole_kind", "Source holes bind logical sources only"),
        ("empty_source", "nonempty logical source"),
        ("unknown_literal", "Unknown runtime logical source"),
        ("malformed_source_ref", "contain only a nonempty"),
        ("nonstring_source_ref", "contain only a nonempty"),
        ("nested_undeclared", "Undeclared executable semantic hole 'missing'"),
        ("malformed_parameter_ref", "contain only a nonempty"),
        ("source_in_parameters", "Source holes bind logical sources only"),
        ("source_in_constraint", "Source holes bind logical sources only"),
        ("undeclared_constraint", "Undeclared executable semantic hole 'missing'"),
    ],
)
def test_invalid_executable_slots_or_assignments_reject_without_repair(change, message):
    value = payload()
    source = value["operator_sources"]
    operators = value["program"]["operators"]
    if change == "undeclared_source":
        value["program"]["holes"].pop(0)
    elif change == "source_toy_and_coordinator":
        source.update(people={"$hole": "source_toy"}, eligible={"$hole": "source_toy"})
    elif change == "missing_source":
        source.clear()
    elif change == "wrong_hole_kind":
        source["people"] = {"$hole": "person_type"}
    elif change == "empty_source":
        source["people"] = "  "
    elif change == "unknown_literal":
        source["people"] = "invented_graph"
    elif change == "malformed_source_ref":
        source["people"] = {"$hole": "source", "fallback": "toy"}
    elif change == "nonstring_source_ref":
        source["people"] = {"$hole": ["source"]}
    elif change == "nested_undeclared":
        operators[0]["parameters"]["node"]["properties"] = {"nested": [{"$hole": "missing"}]}
    elif change == "malformed_parameter_ref":
        operators[0]["parameters"]["node"]["label"] = {"$hole": "person_type", "value": "Person"}
    elif change == "source_in_parameters":
        operators[0]["parameters"]["node"]["label"] = {"$hole": "source"}
    elif change in {"source_in_constraint", "undeclared_constraint"}:
        operators[1]["constraints"][0]["predicate"]["value"] = {
            "$hole": "source" if change == "source_in_constraint" else "missing"
        }
    before = deepcopy(value)
    with pytest.raises(ValueError, match=message):
        parse_interpretation(value, request({"runtime": {"sources": {"toy": {}}}}))
    assert value == before


@pytest.mark.parametrize(
    ("source_value", "context"),
    [
        ({"$hole": "source"}, {"runtime": {"sources": {"toy": {}}}}),
        ("toy", {"runtime": {"sources": {"toy": {}}}}),
        ("provider_neutral_source", {}),
    ],
)
def test_declared_source_or_allowed_literal_is_admitted_unchanged(source_value, context):
    value = payload()
    value["operator_sources"]["people"] = source_value
    before = deepcopy(value)
    program, sources = parse_interpretation(value, request(context))
    assert program.program_id == "source-admission"
    assert sources == value["operator_sources"]
    assert value == before


def test_unknown_source_hole_stops_ordinary_question_and_preserves_raw_usage():
    original_request, template = interpretation_inputs(CASES[0])
    value = deepcopy(template.interpret(original_request).payload)
    value["program"]["holes"] = [
        hole for hole in value["program"]["holes"] if hole["kind"] != "source"
    ]
    model = ControlledProvider(value)
    result, calls = question_run(CASES[0], provider=model)
    assert result["status"] == "interpretation_invalid" and not result["success"]
    assert calls == [] and model.calls == 1
    assert result["backend_remote_calls"] == result["resolution_external_calls"] == 0
    assert (result["interpretation_external_calls"], result["input_tokens"], result["output_tokens"]) == (1, 7, 3)
    assert result["interpretation"]["raw_response"] == value
    assert "Undeclared executable semantic hole" in result["error"]
