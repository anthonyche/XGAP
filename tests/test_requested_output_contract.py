"""Request-owned output columns, with one controlled HTTP -> ordinary P1 slice."""

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_external_toy_interpretation import KEY_ENV, MODEL, SECRET, _envelope, _loopback
from test_question_interpretation import CASES, question_run
from xgap.experiments.external_toy_interpretation import load_external_toy_provider
from xgap.experiments.toy_binding import interpretation_inputs
from xgap.experiments.toy_live_interpretation import PROMPT_PATH, run_toy_model_requests, toy_model_requests
from xgap.experiments.toy_output_contract import (
    REQUEST_PROFILE, apply_toy_output_contract, requested_output_from_question,
)
from xgap.semantic.interpretation import InterpretationRequest, interpret_question
from xgap.semantic.interpretation_replay import RecordingInterpretationProvider, ReplayInterpretationProvider
from xgap.semantic.output_contract import RequestedOutput
from xgap.semantic.program import SemanticGraphProgram


@pytest.fixture(autouse=True)
def local_environment(monkeypatch):
    monkeypatch.setenv(KEY_ENV, SECRET)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def _provider(url="http://127.0.0.1:9/v1", *, profile=REQUEST_PROFILE):
    return load_external_toy_provider(base_url=url, model=MODEL, api_key_env=KEY_ENV,
                                     request_profile=profile)


def _binding_program(*, project=True, fields=("person", "age")):
    operators = [{"operator_id": "people", "kind": "match", "input_ids": [], "input_kinds": [],
                  "output_kind": "binding_set", "parameters": {"node": {"label": "Person", "properties": {}},
                  "entity_field": "person", "properties": {"age": "age", "edge": "edge"}}}]
    if project:
        operators.append({"operator_id": "answer", "kind": "project", "input_ids": ["people"],
                          "input_kinds": ["binding_set"], "output_kind": "binding_set",
                          "parameters": {"projections": {field: {"kind": "field", "field": field} for field in fields}}})
    else:
        operators[0]["parameters"]["properties"] = {field: field for field in fields if field != "person"}
    return SemanticGraphProgram.from_dict({"program_id": "independent-output-columns",
                                           "operators": operators, "roots": [operators[-1]["operator_id"]]})


@pytest.mark.parametrize("qid,fields", [
    ("B01", ["person", "edge"]), ("B03", ["person", "edge"]), ("B04", ["person", "age"]),
])
def test_question_clauses_determine_columns_without_consulting_answer_rows(qid, fields):
    case = next(case for case in CASES if case["id"] == qid)
    request, _ = interpretation_inputs(case)
    before = deepcopy(request.to_dict())
    contract = {"kind": "binding_set", "fields": fields}
    assert requested_output_from_question(case["nl"]) == contract
    updated = apply_toy_output_contract(request)
    assert updated.context["requested_output"] == contract
    assert updated.question == request.question and updated.required_constraints == request.required_constraints
    assert updated.max_response_bytes == request.max_response_bytes
    assert request.to_dict() == before and "requested_output" not in request.context


@pytest.mark.parametrize("question", [
    "在 toy graph 中查找 Alice knows 的 people。",
    "返回人员和边，并返回 Alice 的身份和年龄。",
])
def test_missing_or_ambiguous_return_clause_is_rejected(question):
    with pytest.raises(ValueError):
        requested_output_from_question(question)


@pytest.mark.parametrize("contract", [
    {"kind": "binding_set", "fields": []},
    {"kind": "binding_set", "fields": ["person", "person"]},
    {"kind": "binding_set", "fields": ["person"], "values": ["not-a-request-field"]},
])
def test_malformed_output_contract_is_rejected_before_provider_entry(contract):
    provider = Mock()
    with pytest.raises(ValueError):
        request = InterpretationRequest("Return an explicitly declared output.",
                                        context={"requested_output": contract})
        interpret_question(request, provider)
    provider.interpret.assert_not_called()


@pytest.mark.parametrize("project", [True, False], ids=["final-project", "final-match"])
def test_explicit_root_columns_match_as_a_set_and_contract_roundtrips(project):
    payload = {"kind": "binding_set", "fields": ["age", "person"]}
    contract = RequestedOutput.from_dict(payload)
    assert contract.to_dict() == payload
    contract.validate_program(_binding_program(project=project))


@pytest.mark.parametrize("mismatch", ["extra", "missing", "unsupported-root"])
def test_static_root_mismatch_cannot_depend_on_whether_execution_would_be_empty(mismatch):
    contract = RequestedOutput.from_dict({"kind": "binding_set", "fields": ["person", "age"]})
    if mismatch == "extra":
        program = _binding_program(fields=("person", "age", "edge"))
    elif mismatch == "missing":
        program = _binding_program(fields=("person",))
    else:
        raw = _binding_program(project=False).to_dict()
        raw["operators"].append({"operator_id": "filtered", "kind": "filter", "input_ids": ["people"],
            "input_kinds": ["binding_set"], "output_kind": "binding_set", "parameters": {
                "condition": {"op": "gt", "field": "age", "value": 1000000}}})
        raw["roots"] = ["filtered"]
        program = SemanticGraphProgram.from_dict(raw)
    with pytest.raises(ValueError):
        contract.validate_program(program)


def test_default_legacy_requests_and_prompt_body_remain_unchanged():
    default = toy_model_requests()
    legacy = toy_model_requests(request_profile="legacy-v2")
    explicit = toy_model_requests(request_profile=REQUEST_PROFILE)
    default_provider = load_external_toy_provider(base_url="http://127.0.0.1:9/v1", model=MODEL, api_key_env=KEY_ENV)
    old_provider, new_provider = _provider(profile="legacy-v2"), _provider()
    assert default_provider.system_prompt == old_provider.system_prompt == PROMPT_PATH.read_text(encoding="utf-8")
    assert new_provider.config.prompt_hash != old_provider.config.prompt_hash
    assert "requested_output" in new_provider.system_prompt
    for (qid, request), (old_qid, old), (new_qid, new) in zip(default, legacy, explicit):
        assert qid == old_qid == new_qid
        assert request.to_dict() == old.to_dict()
        assert set(old.context) == {"query_profile", "runtime"}
        assert json.dumps(default_provider.build_request_payload(request), ensure_ascii=True) == json.dumps(
            old_provider.build_request_payload(old), ensure_ascii=True)
        stripped = new.to_dict()
        del stripped["context"]["requested_output"]
        assert stripped == old.to_dict()


def test_controlled_http_with_contract_reaches_ordinary_p1_and_tiny_rdf():
    case = CASES[0]
    request, _ = interpretation_inputs(case)
    request = apply_toy_output_contract(request)
    envelope = _envelope(case)
    with _loopback(lambda path, body: (200, {}, json.dumps(envelope).encode())) as (url, received):
        result, calls = question_run(case, request=request, provider=_provider(url))
    assert result["success"], result
    assert result["interpretation_external_calls"] == len(received) == 1
    sent = json.loads(json.loads(received[0]["body"])["messages"][1]["content"])
    assert sent["context"]["requested_output"] == {"kind": "binding_set", "fields": ["person", "edge"]}
    planning = result["state"]["output"]["planning_run"]
    assert planning["selection"]["algorithm"] in {"independent_source_minimum", "coordinate_two_passes"}
    assert planning["execution"]["value"]["final_rows"] == case["expected_rows"]
    assert all(set(row) == {"person", "edge"} for row in planning["execution"]["value"]["final_rows"])
    assert result["backend_remote_calls"] == len(calls) > 0


def test_extra_age_output_after_one_controlled_model_call_stops_before_backend():
    case = CASES[0]
    request, _ = interpretation_inputs(case)
    request = apply_toy_output_contract(request)
    envelope = _envelope(case)
    payload = json.loads(envelope["choices"][0]["message"]["content"])
    root = next(op for op in payload["program"]["operators"] if op["operator_id"] == payload["program"]["roots"][0])
    root["parameters"]["projections"]["age"] = {"kind": "field", "field": "age"}
    envelope["choices"][0]["message"]["content"] = json.dumps(payload)
    provider = _provider()
    send = Mock(return_value=envelope)
    provider.transport = SimpleNamespace(post_json=send)
    result, calls = question_run(case, request=request, provider=provider)
    assert result["success"] is False and result["status"] == "interpretation_invalid", result
    assert result["interpretation_external_calls"] == send.call_count == 1
    assert result["backend_remote_calls"] == 0 and calls == []
    actual = result["interpretation"]["raw_response"]
    recorded_root = next(op for op in actual["program"]["operators"] if op["operator_id"] == root["operator_id"])
    assert "age" in recorded_root["parameters"]["projections"]  # Rejected, never trimmed into success.


def test_replay_is_bound_to_the_exact_requested_output_context(tmp_path):
    request, template = interpretation_inputs(CASES[0])
    request = apply_toy_output_contract(request)
    recorder = RecordingInterpretationProvider(template)
    recorded = interpret_question(request, recorder)
    assert recorded["success"], recorded
    path = tmp_path / "output-contract.json"
    recorder.save(path)
    before = path.read_bytes()
    replay = ReplayInterpretationProvider.from_path(path)
    changed = replace(request, context={**request.context, "requested_output": {
        "kind": "binding_set", "fields": ["person"]}})
    rejected = interpret_question(changed, replay)
    assert rejected["failure_category"] == "replay_mismatch" and rejected["external_calls"] == 0
    accepted = interpret_question(request, replay)
    replay.assert_consumed()
    assert accepted["success"] and accepted["program"] == recorded["program"]
    assert accepted["external_calls"] == 0 and path.read_bytes() == before


def test_toy_runner_persists_explicit_profile_before_dispatch_and_records_its_request(tmp_path):
    output = tmp_path / "explicit-profile"
    provider = _provider()
    sent = []

    def send(**kwargs):
        intent = json.loads((output / "result.json").read_text())
        assert intent["request_profile"] == REQUEST_PROFILE
        request = json.loads(kwargs["payload"]["messages"][1]["content"])
        assert request["context"]["requested_output"]["fields"] == ["person", "edge"]
        sent.append(request)
        return _envelope(CASES[0])

    provider.transport = SimpleNamespace(post_json=send)
    report = run_toy_model_requests(provider, output, max_requests=1, request_profile=REQUEST_PROFILE)
    assert report["requested_window_success"] and report["external_calls"] == len(sent) == 1
    assert report["request_profile"] == REQUEST_PROFILE and len(report["queries"]) == 5
    recording = json.loads((output / "B01.json").read_text())
    assert recording["records"][0]["request"] == sent[0]
