"""Independent meaning gold, real execution seam, and saved failure replay."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from test_semantic_binding_execution import setup
from xgap.agent.question import run_question
from xgap.experiments.toy_binding import BUNDLE_FIXTURE, INTAKE_FIXTURE, interpretation_inputs, load_binding_cases
from xgap.semantic.interpretation import (InterpretationRequest, InterpretationResponse,
    InterpretationFailure, interpret_question)
from xgap.semantic.interpretation_replay import RecordingInterpretationProvider, ReplayInterpretationProvider
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools.artifact_resolution import ExplicitUserSelectionProvider, explicit_user_clarification_tool


CASES = load_binding_cases()


def question_run(case, *, provider=None, root=None, request=None, **execution_options):
    default_request, default_provider = interpretation_inputs(case)
    tool, calls = setup(case, bindings_override={})
    pin = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
    user = (explicit_user_clarification_tool(ExplicitUserSelectionProvider(
        case["explicit_user_selection"], source_id="controlled-toy-selection"))
        if case.get("explicit_user_selection") else None)
    result = run_question(request or default_request, provider or default_provider,
        catalog_root=root or BUNDLE_FIXTURE / pin["root"], catalog_hash=pin["bundle_hash"],
        sources=tool.sources, backends=tool.backends, backend_clients=tool.backend_clients,
        clarification_tool=user, max_candidates=4, max_observation_calls=4, **execution_options)
    return result, calls


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["id"])
def test_nl_interpretation_matches_independent_original_meaning(case):
    request, provider = interpretation_inputs(case)
    result = interpret_question(request, provider)
    assert result["success"], result
    actual = result["program"]
    gold = SemanticGraphProgram.from_dict(case["program"]).to_dict()
    # Only program identity and intake provenance differ; operator meaning is exact.
    actual["program_id"] = gold["program_id"]
    actual["metadata"] = gold["metadata"]
    assert actual == gold
    assert result["operator_sources"] == case["operator_sources"]


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["id"])
def test_nl_through_frozen_resolution_and_planning_matches_independent_answer(case):
    result, calls = question_run(case)
    assert result["success"], result
    assert result["interpretation"]["status"] == "interpreted"
    output = result["state"]["output"]
    assert output["planning_run"]["execution"]["value"]["final_rows"] == case["expected_rows"]
    assert {h:v["value"] for h,v in output["bindings"].items()} == case["expected_bindings"]
    assert len(calls) == result["backend_remote_calls"]


class ControlledProvider:
    provider_id = "controlled-provider-v1"

    def __init__(self, payload=None, *, failure=False):
        self.payload = payload
        self.failure = failure
        self.calls = 0

    def interpret(self, request):
        self.calls += 1
        if self.failure:
            raise InterpretationFailure("controlled_timeout", "Saved development timeout", usage={"external_calls":1})
        return InterpretationResponse(deepcopy(self.payload), external_calls=1, input_tokens=7,
                                      output_tokens=3, provenance={"kind":"controlled_provider"})


@pytest.mark.parametrize("change", ["malformed", "drop", "predicate", "policy", "native", "hole", "oversize", "entity_candidate"])
def test_invalid_interpretation_stops_before_backend_dispatch(change):
    request, provider = interpretation_inputs(CASES[0])
    payload = deepcopy(provider.interpret(request).payload)
    if change == "malformed": payload["program"]["operators"][0]["kind"] = "missing_operator"
    if change == "drop": payload["program"]["operators"][0]["constraints"] = []
    if change == "predicate": payload["program"]["operators"][0]["constraints"][0]["predicate"]["value"] = "b"
    if change == "policy": payload["program"]["operators"][0]["constraints"][0]["policy"] = "relaxable"
    if change == "native": payload["program"]["metadata"]["cypher"] = "MATCH (n) RETURN n"
    if change == "hole": payload["program"]["holes"][0]["authoritative"] = True
    if change == "entity_candidate":
        payload["program"]["holes"][0].update(candidates=["entity:bob"], is_resolved=True)
    if change == "oversize": request = replace(request, max_response_bytes=100)
    controlled = ControlledProvider(payload)
    result, calls = question_run(CASES[0], provider=controlled, request=request)
    assert result["status"] == "interpretation_invalid" and not result["success"]
    assert not calls and controlled.calls == 1
    assert (result["interpretation_external_calls"], result["input_tokens"], result["output_tokens"]) == (1,7,3)


def test_missing_catalog_precedes_provider_and_backend_calls(tmp_path):
    provider = ControlledProvider(failure=True)
    result, calls = question_run(CASES[0], provider=provider, root=tmp_path)
    assert result["status"] == "catalog_unavailable" and provider.calls == 0 and not calls


def test_provider_failure_is_observed_once_and_never_executes():
    provider = ControlledProvider(failure=True)
    result, calls = question_run(CASES[0], provider=provider)
    assert result["status"] == "provider_failure" and provider.calls == 1 and not calls
    assert result["interpretation_external_calls"] == 1


@pytest.mark.parametrize("outcome", ["valid", "malformed", "failure"])
def test_saved_response_and_failure_replay_without_original_provider(tmp_path, outcome):
    request, template = interpretation_inputs(CASES[0])
    payload = deepcopy(template.interpret(request).payload)
    if outcome == "malformed": payload["program"]["operators"][0]["kind"] = "unsupported_operator"
    original = ControlledProvider(payload, failure=outcome == "failure")
    recorder = RecordingInterpretationProvider(original)
    before = interpret_question(request, recorder)
    path = tmp_path / "recording.json"; recorder.save(path)
    data = path.read_bytes()
    with pytest.raises(FileExistsError): recorder.save(path)
    replay = ReplayInterpretationProvider.from_path(path)
    after = interpret_question(request, replay)
    replay.assert_consumed()
    assert after["status"] == before["status"]
    assert original.calls == 1 and path.read_bytes() == data
    assert (after["external_calls"],after["input_tokens"],after["output_tokens"]) == (0,0,0)
    assert after["provenance"]["recorded_usage"]["external_calls"] == 1
    if outcome != "failure": assert after["raw_response"] == before["raw_response"]
    if outcome == "valid": assert after["program"] == before["program"]
    assert interpret_question(request, replay)["failure_category"] == "replay_exhausted"


@pytest.mark.parametrize("field", ["question", "context", "required_constraints", "max_response_bytes"])
def test_replay_rejects_changed_request_and_versions(tmp_path, field):
    request, provider = interpretation_inputs(CASES[0])
    recorder = RecordingInterpretationProvider(provider); interpret_question(request, recorder)
    path = tmp_path / "recording.json"; recorder.save(path)
    replay = ReplayInterpretationProvider.from_path(path)
    changed = replace(request, **{field:{"question":"another question", "context":{"version":"changed"},
        "required_constraints":(), "max_response_bytes":1024}[field]})
    assert interpret_question(changed, replay)["failure_category"] == "replay_mismatch"
    with pytest.raises(ValueError, match="Unused"): replay.assert_consumed()


def test_template_missing_required_phrase_is_not_silently_executed():
    request, provider = interpretation_inputs(CASES[0])
    result, calls = question_run(CASES[0], request=replace(request, question="查找 Alice knows 的 people"))
    assert not result["success"] and not calls


@pytest.mark.parametrize("name,status", [("malformed", "interpretation_invalid"), ("timeout", "provider_failure")])
def test_durable_minimal_failure_inputs(name, status):
    replay = ReplayInterpretationProvider.from_path(INTAKE_FIXTURE / "replay" / (name + ".json"))
    raw = replay.records[0]["request"]
    request = InterpretationRequest(raw["question"], raw["context"])
    result = interpret_question(request, replay)
    assert result["status"] == status and result["external_calls"] == 0
    replay.assert_consumed()


def test_replay_request_identity_distinguishes_boolean_from_numeric_context(tmp_path):
    request, provider = interpretation_inputs(CASES[0])
    request = replace(request, context={"version":1})
    recorder = RecordingInterpretationProvider(provider); interpret_question(request, recorder)
    path = tmp_path / "recording.json"; recorder.save(path)
    result = interpret_question(replace(request, context={"version":True}), ReplayInterpretationProvider.from_path(path))
    assert result["failure_category"] == "replay_mismatch"


def test_provider_cannot_mutate_the_caller_hard_constraint_before_validation():
    request, template = interpretation_inputs(CASES[0])
    before = request.to_dict()
    class MutatingProvider:
        provider_id = "controlled-mutating-provider"
        def interpret(self, received):
            payload = deepcopy(template.interpret(received).payload)
            received.required_constraints[1]["constraint"]["predicate"]["op"] = "le"
            payload["program"]["operators"][3]["constraints"][0]["predicate"]["op"] = "le"
            return InterpretationResponse(payload)
    result = interpret_question(request, MutatingProvider())
    assert result["status"] == "interpretation_invalid"
    assert request.to_dict() == before
