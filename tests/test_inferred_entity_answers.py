"""Controlled model wire -> real grounding/selection/P1 -> tiny RDF answers.

The local token counter and HTTP response are explicitly synthetic. Compiled
SPARQL runs through FusekiClient/RDFLib; expected answers are handwritten.
No reference, evaluation answer, native service, or model inference is used.
"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.rdf_encoding import RdfResourceTripleEncoding
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.freebase_question import QuestionBudget
from xgap.experiments.grailqa_guarded_provider import QueryEventJournal
from xgap.experiments.inferred_entity_answers import (
    MODEL_ID, SCHEMA_VERSION, build_entity_answer_provider,
    parse_entity_answer_response, run_entity_answer_question,
)
from xgap.experiments.runtime_alignment import RetrievedOntologyTerm
from xgap.experiments.semantic import DirectionalOntologyDeviation, OntologyGraph, SemanticDeviationConfig
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError
from xgap.llm.token_budget import ChatTokenBudgetGuard
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource


ROOT = Path(__file__).resolve().parents[1]
CASE = runpy.run_path(str(ROOT / "examples/grounded_candidate_execution_demo.py"))["controlled_recording_case"]
NS = "http://rdf.freebase.com/ns/"
RECORDING = "music.release_track.recording"
RELEASE = "music.release_track.release"
BROAD = "fixture.related_release"


def _inputs(*, ambiguous=False):
    raw, request, view = CASE("m.recording", filter_value=None)
    raw.update(schema_version=SCHEMA_VERSION, model="Qwen/Qwen3-32B")
    raw["candidates"][0].update(confidence=0.8, rationale="Controlled response fixture.",
                                predicted_projection={"kind": "path_node", "position": "last"})
    pattern = raw["candidates"][0]["pattern_query"]
    # This separate closed wire schema explicitly requires nullable var fields.
    for component in (pattern["source"], pattern["target"],
                      pattern["expr"]["left"]["edge"], pattern["expr"]["right"]["edge"]):
        component["var"] = None
    ontology = OntologyGraph("independent-answer-fixture", "v1", ("fixture.type",),
        (RECORDING, RELEASE, BROAD), (), {RELEASE: (BROAD,)}, max_relaxation_hops=2)
    view = replace(view, ontology_hash=ontology.ontology_hash,
        terms=(*view.terms, RetrievedOntologyTerm(BROAD, "relation", BROAD, (), 1.0, ("controlled-fixture",))),
        source_schema_items=(*view.source_schema_items, BROAD),
        entities=(*view.entities, {"entity_id": "m.other"}) if ambiguous else view.entities)
    retrieval_data = {"question_id": view.task_id, "types": ["fixture.type"], "relations": [RECORDING, RELEASE, BROAD]}
    retrieval = SimpleNamespace(types=("fixture.type",), relations=(RECORDING, RELEASE, BROAD),
                                to_dict=lambda: deepcopy(retrieval_data))
    catalog = SimpleNamespace(ontology=ontology, retrieve=Mock(return_value=retrieval),
                              prompt_view=Mock(return_value=view))
    return SimpleNamespace(raw=raw, request=replace(request, metadata={
        **request.metadata, "prompt_schema_view": view.to_dict()}), view=view, catalog=catalog,
        semantic=DirectionalOntologyDeviation(ontology, SemanticDeviationConfig(max_relaxation_hops=2)),
        question={"question_id": view.task_id, "text": request.question})


def _runtime(*, extra_release=False, fail_on=None):
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    triples = [("m.track", RECORDING, "m.recording"), ("m.track", RELEASE, "m.release"),
               ("m.track", BROAD, "m.broad_release")]
    if extra_release:
        triples.append(("m.track", RELEASE, "m.release2"))
    text = "\n".join(f"<{NS}{s}> <{NS}{p}> <{NS}{o}> ." for s, p, o in triples) + "\n"
    snapshot = hashlib.sha256(text.encode()).hexdigest()
    encoding = RdfResourceTripleEncoding("independent-inferred-answer", snapshot, NS)
    calls = []

    class LocalClient(FusekiClient):
        def __init__(self):
            super().__init__(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))
            self.graph = rdf.Graph().parse(data=text, format="nt")

        def _post_query(self, query):
            calls.append(query)
            if len(calls) == fail_on:
                raise OSError("controlled inferred-answer backend failure")
            return json.loads(self.graph.query(query).serialize(format="json"))

    return SimpleNamespace(calls=calls, arguments={
        "source_id": "tiny", "sources": {"tiny": LogicalSource("tiny", snapshot, ("fuseki",))},
        "backends": {"fuseki": SemanticBackend("fuseki", NS, identity_property="type.object.id",
                                                rdf_resource_encoding=encoding)},
        "backend_clients": {"fuseki": LocalClient()},
    })


def _provider(tmp_path, monkeypatch, raw, *, tokens=100, transport_error=None):
    model = ModelBundle.load(ROOT / "models" / MODEL_ID)
    monkeypatch.setenv(model.config.api_key_env, "synthetic-inferred-answer-test-key")
    monkeypatch.delenv(model.config.model_env, raising=False)
    monkeypatch.delenv(model.config.base_url_env, raising=False)
    journal = QueryEventJournal(tmp_path / "entity-answer-events.jsonl")
    calls = []

    def send(**kwargs):
        events = [json.loads(line) for line in journal.path.read_text().splitlines()]
        assert events[-1]["event"] == "transport_attempt"
        assert events[-2]["event"] == "token_check" and events[-2]["check"]["passed"] is True
        calls.append(deepcopy(kwargs["payload"]))
        if transport_error is not None:
            raise transport_error
        return {"id": "controlled-entity-answer-response", "choices": [{"message": {"content": json.dumps(raw)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180}}

    counter = SimpleNamespace(identity={"synthetic": True, "remote_serving_parity_verified": False},
                              count_payload_tokens=lambda payload: tokens)
    guard = ChatTokenBudgetGuard(counter, input_limit=8192, output_limit=4096,
                                context_limit=12288, expected_model=model.config.exact_model_snapshot)
    provider = build_entity_answer_provider(model, guard, journal, "controlled-recording",
                                            transport=SimpleNamespace(post_json=send))
    return SimpleNamespace(provider=provider, calls=calls, journal=journal)


def _run(case, provider, runtime, **kwargs):
    with provider.journal:
        return run_entity_answer_question(question=case.question, catalog=case.catalog,
            provider=provider.provider, semantic=case.semantic, require_entity_anchor=True,
            **runtime.arguments, **kwargs)


def _failed(record):
    assert record["success"] is False, record
    assert "answers" not in record and "answer_count" not in record
    assert record["automatic_retries"] == 0
    assert record["question_correctness_verified"] is record["paper_result"] is False


@pytest.mark.parametrize("position,expected", [("first", "m.recording"), ("last", "m.release")])
def test_same_path_different_predicted_positions_change_meaning_and_answers(tmp_path, monkeypatch, position, expected):
    import xgap.experiments.inferred_entity_answers as module

    case = _inputs()
    first = case.raw["candidates"][0]
    first.update(candidate_id="first", confidence=0.9 if position == "first" else 0.1,
                 predicted_projection={"kind": "path_node", "position": "first"})
    last = deepcopy(first)
    last.update(candidate_id="last", confidence=0.9 if position == "last" else 0.1,
                predicted_projection={"kind": "path_node", "position": "last"})
    case.raw["candidates"].append(last)
    parsed_requests = []
    real_parse = module.parse_entity_answer_response

    def observe_parser(raw, request):
        parsed_requests.append(request)
        return real_parse(raw, request)

    monkeypatch.setattr(module, "parse_entity_answer_response", observe_parser)
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    record = _run(case, provider, runtime)
    assert record["success"] and record["status"] == "answered", record
    assert record["answers"] == [{"type": "uri", "value": NS + expected}]
    assert record["selection"]["candidate_id"] == position
    assert len({row["meaning_sha256"] for row in record["ranking"]}) == 2
    assert all(row["semantic_deviation"] == 0 for row in record["ranking"])
    assert record["projection_covered_by_epsilon"] is False
    assert record["model_calls"] == len(provider.calls) == 1
    assert (record["input_tokens"], record["output_tokens"]) == (100, 80)
    assert record["backend_remote_calls"] == len(runtime.calls) == 2
    contract = record["request"]["metadata"]["grounding_contracts"][-1]
    assert contract == {"kind": "entity_answer_goal_v1", "require_entity_anchor": True,
                        "required_entity_ids": ["m.recording"]}
    assert len(parsed_requests) == 2
    assert all(request.to_dict() == record["request"] for request in parsed_requests)
    assert "entity_answer_goal_v1" in json.dumps(provider.calls[0])
    execution = record["execution"]
    assert execution["answer_contract"]["position"] == position
    planning = execution["agent_run"]["state"]["output"]["planning_run"]
    assert planning["selection"]["algorithm"] in {"independent_source_minimum", "coordinate_two_passes"}
    assert planning["observation_calls"] == planning["execution_calls"] == 1
    assert record["end_to_end_ms"] >= execution["end_to_end_ms"] >= 0
    assert record["question_correctness_verified"] is record["paper_result"] is False


@pytest.mark.parametrize("policy,selected,answer", [
    ("semantic_bound", "exact-low-confidence", "m.release"),
    ("model_top1", "generalized-high-confidence", "m.broad_release"),
])
def test_semantic_and_model_selection_have_a_falsifiable_difference(tmp_path, monkeypatch, policy, selected, answer):
    case = _inputs()
    exact = case.raw["candidates"][0]
    exact.update(candidate_id="exact-low-confidence", confidence=0.2)
    generalized = deepcopy(exact)
    generalized.update(candidate_id="generalized-high-confidence", confidence=0.99)
    generalized["pattern_query"]["expr"]["right"]["edge"]["label"] = BROAD
    generalized["grounding"]["slot_realizations"][1]["ontology_term_id"] = BROAD
    case.raw["candidates"].insert(0, generalized)
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    record = _run(case, provider, runtime, selection_policy=policy, epsilon=1.0)
    assert record["success"], record
    assert record["selection"]["candidate_id"] == selected
    scores = {row["candidate_id"]: row["semantic_deviation"] for row in record["ranking"]}
    assert scores["exact-low-confidence"] == 0
    assert scores["generalized-high-confidence"] == pytest.approx(1 / 6)
    assert record["answers"] == [{"type": "uri", "value": NS + answer}]
    assert record["model_calls"] == len(provider.calls) == 1
    assert record["backend_remote_calls"] == len(runtime.calls) == 2


def test_parser_retains_prediction_metadata_without_rewriting_the_raw_response():
    case = _inputs()
    before = deepcopy(case.raw)
    parsed = parse_entity_answer_response(case.raw, case.request)
    assert parsed.candidates[0].metadata["predicted_projection"] == {"kind": "path_node", "position": "last"}
    assert parsed.candidates[0].candidate_id == "explicit-recording"
    assert parsed.candidates[0].confidence == 0.8
    assert case.raw == before


def test_missing_projection_has_no_default_or_repair(tmp_path, monkeypatch):
    case = _inputs()
    del case.raw["candidates"][0]["predicted_projection"]
    with pytest.raises(ValueError, match="projection"):
        parse_entity_answer_response(case.raw, case.request)
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    record = _run(case, provider, runtime)
    _failed(record)
    assert record["status"] == "inference_failed"
    assert record["model_calls"] == len(provider.calls) == 1
    assert record["backend_remote_calls"] == 0 and runtime.calls == []


@pytest.mark.parametrize("bad", ["out-of-path-position", "unsupported-restrictor"])
def test_selected_unavailable_meaning_does_not_fall_back_to_a_sibling(tmp_path, monkeypatch, bad):
    case = _inputs()
    selected = case.raw["candidates"][0]
    sibling = deepcopy(selected)
    sibling.update(candidate_id="executable-sibling", confidence=0.1)
    selected.update(candidate_id="selected-unavailable", confidence=0.99)
    if bad == "out-of-path-position":
        selected["predicted_projection"]["position"] = 4
    else:
        selected["pattern_query"]["restrictor"] = "TRAIL"
    case.raw["candidates"].append(sibling)
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    record = _run(case, provider, runtime)
    _failed(record)
    assert record["selection"]["candidate_id"] == "selected-unavailable"
    assert len(record["ranking"]) == 2
    assert record["model_calls"] == len(provider.calls) == 1
    assert record["backend_remote_calls"] == 0 and runtime.calls == []
    assert record["status"] == ("admission_failed" if bad == "out-of-path-position" else "selected_meaning_unavailable")


@pytest.mark.parametrize("failure", ["token-denial", "transport-error"])
def test_generation_failure_has_exact_attempts_and_no_retry(tmp_path, monkeypatch, failure):
    case = _inputs()
    error = ProviderTransportError(LiveFailureCategory.PROVIDER_ERROR, "controlled unavailable")
    provider = _provider(tmp_path, monkeypatch, case.raw, tokens=8193 if failure == "token-denial" else 100,
                         transport_error=error if failure == "transport-error" else None)
    runtime = _runtime()
    record = _run(case, provider, runtime)
    _failed(record)
    assert record["status"] == "inference_failed"
    assert record["model_calls"] == len(provider.calls) == (0 if failure == "token-denial" else 1)
    assert record["backend_remote_calls"] == 0 and runtime.calls == []
    events = [json.loads(line) for line in provider.journal.path.read_text().splitlines()]
    assert sum(event["event"] == "token_check" for event in events) == 1
    assert sum(event["event"] == "transport_attempt" for event in events) == len(provider.calls)


@pytest.mark.parametrize("case_name", ["unconfirmed", "invisible", "confirmed", "different-visible", "negative-only"])
def test_entity_confirmation_requires_visibility_and_positive_selected_binding(tmp_path, monkeypatch, case_name):
    case = _inputs(ambiguous=True)
    confirmed = () if case_name == "unconfirmed" else ("m.invisible",) if case_name == "invisible" else ("m.recording",)
    candidate = case.raw["candidates"][0]
    if case_name == "different-visible":
        candidate["pattern_query"]["source"]["properties"]["type.object.id"] = "m.other"
        candidate["grounding"]["entity_ids"] = ["m.other"]
    elif case_name == "negative-only":
        candidate["pattern_query"]["source"]["properties"] = {}
        candidate["pattern_query"]["condition"] = {"kind": "property_not_equals",
            "ref": {"kind": "node", "position": 1}, "property": "type.object.id", "value": "m.recording"}
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    record = _run(case, provider, runtime, confirmed_entity_ids=confirmed)
    if case_name == "confirmed":
        assert record["success"], record
        assert record["answers"] == [{"type": "uri", "value": NS + "m.release"}]
        assert record["backend_remote_calls"] == len(runtime.calls) == 2
        assert record["request"]["metadata"]["grounding_contracts"][-1]["required_entity_ids"] == ["m.recording"]
    else:
        _failed(record)
        expected = {"unconfirmed": "clarification_required", "invisible": "grounding_unavailable"}.get(
            case_name, "selected_meaning_unavailable")
        assert record["status"] == expected, record
        assert record["backend_remote_calls"] == 0 and runtime.calls == []
    expected_models = 0 if case_name in {"unconfirmed", "invisible"} else 1
    assert record["model_calls"] == len(provider.calls) == expected_models


@pytest.mark.parametrize("budget_kind", ["backend-calls", "answer-rows"])
def test_finite_question_budgets_retain_the_stage_that_exhausted_them(tmp_path, monkeypatch, budget_kind):
    case = _inputs()
    provider = _provider(tmp_path, monkeypatch, case.raw)
    runtime = _runtime(extra_release=budget_kind == "answer-rows")
    budget = QuestionBudget(max_backend_calls=1) if budget_kind == "backend-calls" else QuestionBudget(max_rows=1)
    record = _run(case, provider, runtime, budget=budget)
    _failed(record)
    if budget_kind == "backend-calls":
        assert record["status"] == "budget_exhausted"
        assert record["model_calls"] == len(provider.calls) == 0
        assert record["backend_remote_calls"] == 0 and runtime.calls == []
    else:
        assert record["status"] == "answer_invalid", record
        assert record["model_calls"] == len(provider.calls) == 1
        assert record["backend_remote_calls"] == len(runtime.calls) == 2
        assert record["execution"]["agent_run"]["success"] is True


def test_selected_backend_failure_is_not_an_empty_answer(tmp_path, monkeypatch):
    case = _inputs()
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime(fail_on=2)
    record = _run(case, provider, runtime)
    _failed(record)
    assert record["status"] == "execution_failed", record
    assert record["model_calls"] == len(provider.calls) == 1
    assert record["backend_remote_calls"] == len(runtime.calls) == 2
    assert record["execution"]["agent_run"]["success"] is False
    assert "controlled inferred-answer backend failure" in json.dumps(record["execution"])


@pytest.mark.parametrize("extra", ["condition-negated", "source-extra-field"])
def test_nested_unknown_fields_cannot_be_silently_discarded(tmp_path, monkeypatch, extra):
    case = _inputs()
    pattern = case.raw["candidates"][0]["pattern_query"]
    pattern["condition"] = {"kind": "length_equals", "value": 2}
    assert len(parse_entity_answer_response(case.raw, case.request).candidates) == 1
    if extra == "condition-negated":
        pattern["condition"]["negated"] = True
    else:
        pattern["source"]["unexpected_constraint"] = True
    before = deepcopy(case.raw)
    with pytest.raises(ValueError, match="wire schema rejected"):
        parse_entity_answer_response(case.raw, case.request)
    assert case.raw == before
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    record = _run(case, provider, runtime)
    _failed(record)
    assert record["status"] == "inference_failed"
    assert record["model_calls"] == len(provider.calls) == 1
    assert record["backend_remote_calls"] == 0 and runtime.calls == []


@pytest.mark.parametrize("reported_field,reported_value", [
    ("generation_calls", 2), ("repair_calls", 1), ("api_call_completed", False),
])
def test_contradictory_provider_call_record_is_retained_and_blocks_execution(
        tmp_path, monkeypatch, reported_field, reported_value):
    case = _inputs()
    provider, runtime = _provider(tmp_path, monkeypatch, case.raw), _runtime()
    actual_generate = provider.provider.generate
    reported = []

    def inconsistent_ledger(request, view):
        # Execute one real guarded controlled transport call, then inject only
        # the provider ledger contradiction at the orchestration boundary.
        generation = actual_generate(request, view)
        assert generation.api_call_completed and generation.repair_calls == 0
        invocation = deepcopy(generation.response_record)
        if reported_field != "api_call_completed":
            invocation[reported_field] = reported_value
        reported.append(invocation)
        return replace(generation, response_record=invocation,
                       api_call_completed=False if reported_field == "api_call_completed" else True)

    monkeypatch.setattr(provider.provider, "generate", inconsistent_ledger)
    record = _run(case, provider, runtime)
    _failed(record)
    assert record["status"] == "provider_contract_failed", record
    assert len(provider.calls) == len(reported) == 1
    assert record["backend_remote_calls"] == 0 and runtime.calls == []
    assert record["execution"] is None
    assert record["generation_record"] == record["inference"]["response_record"] == reported[0]
    assert record["inference"]["repair_calls"] == 0
    if reported_field == "api_call_completed":
        assert record["inference"]["api_call_completed"] is False
        assert record["inference"]["structured_response"] and record["inference"]["candidates"]
        assert record["model_calls"] == 1
    else:
        assert record["generation_record"][reported_field] == reported_value
        assert record["model_calls"] == 2  # Preserve the conflicting report without repairing it.
    assert (record["input_tokens"], record["output_tokens"]) == (100, 80)
