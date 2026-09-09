"""Opt-in feedback uses only the supplied prompt and the existing repair budget."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import xgap.experiments.grailqa_candidate_feedback as feedback
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_guarded_provider import GuardedSemanticPilotProvider, QueryEventJournal
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError
from xgap.llm.schemas import PlannerRequest
from xgap.llm.token_budget import ChatTokenBudgetGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e3b4_relation_endpoint_grounding.py"))
WIRE = runpy.run_path(str(ROOT / "tests/test_m13e2_cwru_vllm.py"))


def raw(*, bad=False):
    value = FIXTURES["_grounded_raw"](target_type="type.target")
    value["candidates"][0].update(confidence=1.0, rationale=None)
    if bad:
        value["candidates"][0]["grounding"]["slot_realizations"][0]["component_ref"] = "s.label"
    return value


def envelope(value):
    result = WIRE["_provider_response"]()
    result["choices"][0]["message"]["content"] = json.dumps(value)
    return result


def setup_case(tmp_path, monkeypatch, responses, tokens=(1000, 1000), validator=None):
    model = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_grailqa_contract_v1")
    monkeypatch.setenv(str(model.config.api_key_env), "offline-feedback-fixture")
    monkeypatch.delenv(str(model.config.model_env), raising=False)
    monkeypatch.delenv(str(model.config.base_url_env), raising=False)
    view = FIXTURES["_prompt_view"]()
    request = PlannerRequest("Find connected targets", max_candidates=3, metadata={
        "task_id": "q1", "prompt_schema_view": view.to_dict(), "inference_only": True,
    })
    journal = QueryEventJournal(tmp_path / "events.jsonl")
    remaining = list(responses)
    calls = []

    def send(**kwargs):
        events = [json.loads(line) for line in journal.path.read_text().splitlines()]
        assert events[-1]["event"] == "transport_attempt"
        assert events[-2]["event"] == "token_check"
        if calls and any(e["event"] == "candidate_contract_feedback" for e in events):
            assert next(e for e in events if e["event"] == "candidate_contract_feedback")["no_valid_candidate"]
        calls.append(deepcopy(kwargs["payload"]))
        response = remaining.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    base = build_openai_compatible_provider(
        model, SimpleNamespace(post_json=send), response_parser=parse_normalized_planner_response,
    )
    base = replace(base, response_validator=validator)
    counter = SimpleNamespace(identity={"fixture": True}, count_payload_tokens=Mock(side_effect=tokens))
    guard = ChatTokenBudgetGuard(
        counter, input_limit=8192, output_limit=4096, context_limit=12288, expected_model=base.config.model,
    )
    provider = GuardedSemanticPilotProvider(
        model, guard, journal, "q1", base_provider=base,
        candidate_repair_policy=feedback.TYPED_GROUNDING_ONCE, grounding_policy=SEMANTIC_GROUNDING_POLICY,
    )
    return SimpleNamespace(provider=provider, request=request, view=view, journal=journal,
                           counter=counter, calls=calls, base=base, guard=guard, model=model)


@pytest.mark.parametrize("first", ["grounding", "shared-anchor", "semantic-type", "malformed"])
def test_all_invalid_uses_one_combined_repair_and_preserves_both_raw_responses(tmp_path, monkeypatch, first):
    invalid = raw(bad=first == "grounding")
    if first == "shared-anchor":
        invalid["query_slots"][0]["query_anchor_id"] = "nonvisible.type"
    elif first == "semantic-type":
        invalid["candidates"][0]["pattern_query"]["selector"]["k"] = 1  # ALL cannot take k.
    elif first == "malformed":
        invalid = {"bad": "not a candidate envelope"}
    envelopes = [envelope(invalid), envelope(raw())]
    before = deepcopy(envelopes)
    case = setup_case(tmp_path, monkeypatch, envelopes)
    with case.journal:
        result = case.provider.generate(case.request, case.view)
    assert result.api_call_completed and result.repair_calls == 1
    assert len(case.calls) == len(result.request_records) == len(case.provider.token_check_records) == 2
    assert envelopes == before
    # All original context and raw model content are retained in the repair payload.
    original = case.calls[0]["messages"]
    repaired = case.calls[1]["messages"]
    assert repaired[:len(original)] == original
    assert repaired[-2]["content"] == envelopes[0]["choices"][0]["message"]["content"]
    if first != "malformed":
        assert "No typed, prompt-grounded candidate" in repaired[-1]["content"]
    records = case.provider.guard_diagnostics["candidate_feedback"]
    assert records[-1]["valid_candidate_count"] == 1
    assert len(records) == (1 if first == "malformed" else 2)
    if first == "semantic-type":
        assert records[0]["candidate_issues"][0]["code"] == "semantic_type_check"
    events = [json.loads(line) for line in case.journal.path.read_text().splitlines()]
    wire_responses = [e["raw_response"] for e in events if e["event"] == "transport_response"]
    assert wire_responses == envelopes
    assert all(e["gold_used"] is False and e["lowering_consulted"] is False for e in records)
    assert records[-1]["request_sha256"] == content_hash(case.request.to_dict())


@pytest.mark.parametrize("kind", ["plain", "bad-sibling", "inward"])
def test_at_least_one_valid_candidate_never_triggers_quality_retry(tmp_path, monkeypatch, kind):
    value = raw()
    if kind == "bad-sibling":
        sibling = raw(bad=True)["candidates"][0]
        sibling["candidate_id"] = "bad-sibling"
        value["candidates"].append(sibling)
    elif kind == "inward":
        pattern = value["candidates"][0]["pattern_query"]
        pattern["expr"]["edge"]["direction"] = "IN"
        pattern["source"]["label"], pattern["target"]["label"] = "type.target", "type.source"
        value["candidates"][0]["grounding"]["slot_realizations"][0]["component_ref"] = "target"
    case = setup_case(tmp_path, monkeypatch, [envelope(value)])
    with case.journal:
        result = case.provider.generate(case.request, case.view)
    assert result.api_call_completed and result.repair_calls == 0 and len(case.calls) == 1
    assert result.structured_response == value
    record, = case.provider.guard_diagnostics["candidate_feedback"]
    assert record["valid_candidate_count"] == 1 and not record["no_valid_candidate"]


@pytest.mark.parametrize("first", ["invalid", "malformed"])
def test_repeated_invalid_cannot_add_a_third_attempt(tmp_path, monkeypatch, first):
    case = setup_case(tmp_path, monkeypatch, [envelope(raw(bad=True) if first == "invalid" else {}), envelope(raw(bad=True))])
    with case.journal:
        result = case.provider.generate(case.request, case.view)
    assert not result.api_call_completed and result.repair_calls == 1 and len(case.calls) == 2
    assert case.provider.guard_diagnostics["candidate_feedback"][-1]["no_valid_candidate"]


def test_transport_timeout_is_never_repaired(tmp_path, monkeypatch):
    error = ProviderTransportError(LiveFailureCategory.TIMEOUT, "fixture timeout")
    case = setup_case(tmp_path, monkeypatch, [error])
    with case.journal:
        result = case.provider.generate(case.request, case.view)
    assert not result.api_call_completed and result.repair_calls == 0 and len(case.calls) == 1
    assert case.provider.guard_diagnostics["candidate_feedback"] == []


def test_feedback_repair_still_faces_full_payload_token_guard(tmp_path, monkeypatch):
    case = setup_case(tmp_path, monkeypatch, [envelope(raw(bad=True))], tokens=(1000, 8193))
    with case.journal:
        result = case.provider.generate(case.request, case.view)
    assert not result.api_call_completed and result.repair_calls == 0 and len(case.calls) == 1
    assert len(case.provider.token_check_records) == 2
    assert case.provider.guard_diagnostics["denied_call_kind"] == "repair"
    assert "Diagnostics:" in case.counter.count_payload_tokens.call_args.args[0]["messages"][-1]["content"]


@pytest.mark.parametrize("error", [OSError("disk full"), ValueError("serialization")])
def test_failed_feedback_journal_is_fatal_before_repair(tmp_path, monkeypatch, error):
    case = setup_case(tmp_path, monkeypatch, [envelope(raw(bad=True))])
    real_append = case.journal.append

    def append(event):
        if event["event"] == "candidate_contract_feedback":
            raise error
        real_append(event)

    # Bind the failing writer before constructing the callback.
    case.provider._feedback._record = append
    with case.journal, pytest.raises(feedback.CandidateFeedbackProtocolError, match="journal failed"):
        case.provider.generate(case.request, case.view)
    assert len(case.calls) == 1
    assert case.provider.guard_diagnostics["journal_failure_phase"] == "candidate_contract_feedback"
    events = [json.loads(line) for line in case.journal.path.read_text().splitlines()]
    assert events[-1]["event"] == "transport_response"


def test_wrong_prompt_binding_fails_before_first_call(tmp_path, monkeypatch):
    case = setup_case(tmp_path, monkeypatch, [])
    with case.journal, pytest.raises(feedback.CandidateFeedbackProtocolError, match="binding"):
        case.provider.generate(case.request, replace(case.view, task_id="different"))
    assert case.calls == []
    case.counter.count_payload_tokens.assert_not_called()


def test_unexpected_assessment_bug_is_not_repairable(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "type_check_semantic_path_pattern", Mock(side_effect=TypeError("implementation bug")))
    case = setup_case(tmp_path, monkeypatch, [envelope(raw())])
    with case.journal, pytest.raises(feedback.CandidateFeedbackProtocolError, match="internally"):
        case.provider.generate(case.request, case.view)
    assert len(case.calls) == 1


def test_existing_validator_is_preserved_and_shares_repair_budget(tmp_path, monkeypatch):
    validator = Mock(side_effect=[ValueError("existing extra shape requirement"), None])
    case = setup_case(tmp_path, monkeypatch, [envelope(raw()), envelope(raw())], validator=validator)
    with case.journal:
        result = case.provider.generate(case.request, case.view)
    assert result.api_call_completed and result.repair_calls == 1
    assert validator.call_count == 2
    assert len(case.provider.guard_diagnostics["candidate_feedback"]) == 1


def test_real_inference_receives_only_final_repaired_candidates_with_full_cost(tmp_path, monkeypatch):
    from xgap.experiments.grailqa_semantic_pilot import _infer_one
    from xgap.experiments.semantic import DirectionalOntologyDeviation, OntologyGraph, SemanticDeviationConfig

    ontology = OntologyGraph(
        ontology_id="fixture", version="v1", classes=("type.source", "type.target"),
        relations=("r.connected",), properties=(), parents={}, max_relaxation_hops=2,
        domain_range={"r.connected": {"domain": "type.source", "range": "type.target"}},
    )
    case = setup_case(tmp_path, monkeypatch, [envelope(raw(bad=True)), envelope(raw())])
    view = replace(case.view, ontology_hash=ontology.ontology_hash)
    retrieval = SimpleNamespace(types=("type.source",), relations=("r.connected",),
                                to_dict=lambda: {"question_id": "q1"})
    catalog = SimpleNamespace(ontology=ontology, retrieve=Mock(return_value=retrieval),
                              prompt_view=Mock(return_value=view))
    with case.journal:
        state = _infer_one(
            question={"question_id": "q1", "text": "Find connected targets"}, catalog=catalog,
            provider=case.provider,
            semantic=DirectionalOntologyDeviation(ontology, SemanticDeviationConfig(max_relaxation_hops=2)),
            retrieval_k=20, candidate_cap=3, prompt_candidates_per_slot=4,
            response_parser=parse_normalized_planner_response, grounding_policy=SEMANTIC_GROUNDING_POLICY,
        )
    assert state["failure"] is None
    assert state["repair_calls"] == 1 and len(state["request_records"]) == 2
    assert state["api_call_completed"] and len(state["candidates"]) == 1
    candidate, = state["candidates"]
    assert candidate["validation"]["ok"] and candidate["grounded"]
    assert candidate["logical_lowering"]["available"]
    assert not candidate["logical_lowering"]["backend_execution_verified"]
    assert len(state["semantic_scores"]) == 1


@pytest.mark.parametrize("change", ["parser", "repair-budget"])
def test_opt_in_requires_matching_parser_and_existing_one_repair(tmp_path, monkeypatch, change):
    case = setup_case(tmp_path, monkeypatch, [])
    base = (replace(case.base, response_parser=lambda raw, req: None) if change == "parser" else
            replace(case.base, config=replace(case.base.config, max_repair_calls=0)))
    with case.journal, pytest.raises(ValueError, match="normalized parser and one shared repair"):
        GuardedSemanticPilotProvider(case.model, case.guard, case.journal, "q1", base_provider=base,
            candidate_repair_policy=feedback.TYPED_GROUNDING_ONCE, grounding_policy=SEMANTIC_GROUNDING_POLICY)
    assert case.calls == []


@pytest.mark.parametrize("policy", [None, True, {}, "typo"])
def test_unknown_policy_never_defaults_to_schema_only(policy):
    with pytest.raises(ValueError, match="repair policy"):
        feedback.validate_repair_policy(policy, SEMANTIC_GROUNDING_POLICY)


def test_feedback_cannot_be_enabled_with_legacy_grounding():
    with pytest.raises(ValueError, match="semantic grounding"):
        feedback.validate_repair_policy(feedback.TYPED_GROUNDING_ONCE, "legacy_grounding_v1")


def test_feedback_detail_is_bounded_without_silently_shortening_raw_response():
    issue = feedback._issue("fixture", "a" * 1000)
    assert len(issue["detail"]) == 256 and issue["detail_truncated"] is True


def test_callback_rejects_request_mutation_and_non_json_identity():
    view = FIXTURES["_prompt_view"]()
    request = PlannerRequest("question", metadata={"task_id": "q1", "prompt_schema_view": view.to_dict()})
    records = []
    callback = feedback.GroundedCandidateFeedback(records.append)
    callback.bind(request, view)
    with pytest.raises(feedback.CandidateFeedbackProtocolError, match="changed"):
        callback(raw(), replace(request, question="a different question"))
    unsafe = raw()
    unsafe["extra"] = float("nan")
    with pytest.raises(feedback.CandidateFeedbackProtocolError, match="JSON-safe"):
        callback(unsafe, request)
    assert records == []


@pytest.mark.parametrize("spec_policy,state_policy", [
    (feedback.TYPED_GROUNDING_ONCE, feedback.SCHEMA_ONLY),
    (feedback.SCHEMA_ONLY, feedback.TYPED_GROUNDING_ONCE),
])
def test_mixed_repair_evaluation_fails_before_opening_references(tmp_path, spec_policy, state_policy):
    from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec, _evaluate_preflight

    spec = GrailQAPreflightSpec(tmp_path / "missing", {
        "candidate_grounding_policy": SEMANTIC_GROUNDING_POLICY, "candidate_repair_policy": spec_policy,
    })
    with pytest.raises(ValueError, match="matching spec and state"):
        _evaluate_preflight([{
            "candidate_grounding_policy": SEMANTIC_GROUNDING_POLICY, "candidate_repair_policy": state_policy,
        }], spec, tmp_path, {}, grounding_policy=SEMANTIC_GROUNDING_POLICY)
