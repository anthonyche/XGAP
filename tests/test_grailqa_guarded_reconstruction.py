"""Differential reconstruction over retained actual offline-provider histories."""

from copy import deepcopy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from xgap.experiments.grailqa_guarded_reconstruction import reconstruct_guarded_query
from xgap.experiments.grailqa_inline_evidence import InlineEvidenceError


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_grailqa_inline_evidence.py"))


def catalog_for(case):
    retrieval = SimpleNamespace(types=("type.source",), relations=("r.connected",), to_dict=lambda: {})
    return SimpleNamespace(retrieve=lambda *a, **kw: retrieval,
                           prompt_view=lambda *a, **kw: case.fixture.view)


def audit(case, state, events, *, catalog=None):
    return reconstruct_guarded_query(
        state=state, question={"question_id": "q1", "text": "fixture question"},
        events=events, model=case.model, catalog=catalog or catalog_for(case),
        semantic=case.fixture.semantic, retrieval_k=20, prompt_limit=4,
    )


@pytest.mark.parametrize("scenario", [
    "success", "repair", "repair-failed", "structure", "malformed", "bounds",
    "generation-denied", "repair-denied", "timeout", "repair-timeout",
])
def test_reconstruct_actual_pipeline_including_unsent_refusal(tmp_path, monkeypatch, scenario):
    case, state, events = FIXTURES["records"](tmp_path, monkeypatch, scenario)
    before = deepcopy((state, events, case.calls))
    # The independent reader cannot silently delegate to the inference producer.
    import xgap.experiments.grailqa_semantic_pilot as producer
    monkeypatch.setattr(producer, "_infer_one", lambda **kw: pytest.fail("producer called"))
    monkeypatch.setattr(producer, "_infer_one_impl", lambda **kw: pytest.fail("producer called"))
    result = audit(case, state, events)
    checks = [e["check"] for e in events if e["event"] == "token_check"]
    assert len(result.checked_payloads) == len(checks)
    assert list(result.candidates) == state["candidates"]
    assert list(result.semantic_scores) == state["semantic_scores"]
    assert before == (state, events, case.calls)
    if scenario == "generation-denied":
        assert len(result.checked_payloads) == 1 and not case.calls
        assert result.checked_payloads[0]["messages"]


@pytest.mark.parametrize("field", [
    "question", "retrieval", "prompt_view", "candidate_index", "confidence",
    "pattern_query", "validation", "grounded", "semantic_deviation",
    "semantic_scores", "logical_lowering", "returned_candidate_count",
    "terminal", "failure", "provider_id", "negative_time", "bool_time", "time_copy",
])
def test_reject_modified_inference_claims_even_with_unchanged_provider_history(tmp_path, monkeypatch, field):
    case, state, events = FIXTURES["records"](tmp_path, monkeypatch)
    row = state["candidates"][0]
    if field == "question":
        state["question"]["text"] = "different question"
    elif field == "retrieval":
        state["retrieval"]["invented"] = True
    elif field == "prompt_view":
        state["prompt_view"]["task_id"] = "other"
    elif field == "pattern_query":
        row[field]["expr"]["edge"]["direction"] = "IN"
    elif field == "validation":
        row[field]["ok"] = False
    elif field == "logical_lowering":
        row[field]["available"] = False
    elif field == "semantic_scores":
        state[field] = []
    elif field == "returned_candidate_count":
        state[field] = True  # JSON bool must not impersonate count 1.
    elif field == "failure":
        state[field] = {"category": "equivalence_failure"}
    elif field == "terminal":
        state[field] = False
    elif field == "provider_id":
        state[field] = "other"
    elif field in {"negative_time", "bool_time"}:
        state["deterministic_latency_seconds"] = -1 if field == "negative_time" else True
    elif field == "time_copy":
        state["llm_latency_seconds"] += 0.1
    else:
        row[field] = {"candidate_index": 2, "confidence": 0.01,
                      "grounded": False, "semantic_deviation": 123}[field]
    with pytest.raises((InlineEvidenceError, ValueError)):
        audit(case, state, events)


def test_context_changes_cannot_hide_behind_consistent_retained_request_hashes(tmp_path, monkeypatch):
    case, state, events = FIXTURES["records"](tmp_path, monkeypatch)
    from dataclasses import replace
    catalog = catalog_for(case)
    catalog.prompt_view = lambda *a, **kw: replace(case.fixture.view, task_id="other")
    with pytest.raises(InlineEvidenceError):
        audit(case, state, events, catalog=catalog)


def test_mixed_siblings_and_in_capability_reconstructed(tmp_path, monkeypatch):
    helpers = FIXTURES["HELPERS"]
    wire = helpers["wire"](helpers["FIXTURES"]["case"].__wrapped__().raw)
    invalid = deepcopy(wire["candidates"][0])
    invalid["candidate_id"] = "invalid"
    invalid["pattern_query"]["source"]["label"] = "type.unavailable"
    incoming = deepcopy(wire["candidates"][0])
    incoming["candidate_id"] = "incoming"
    incoming["pattern_query"]["expr"]["edge"]["direction"] = "IN"
    wire["candidates"].extend([invalid, incoming])
    case = helpers["provider_case"](tmp_path, monkeypatch, [wire])
    state = helpers["infer"](case)
    events = [json.loads(line) for line in case.journal.path.read_text().splitlines()]
    result = audit(case, state, events)
    assert len(result.candidates) == 3
    assert result.candidates[1]["grounded"] is False
    assert result.candidates[2]["logical_lowering"]["available"] is False
    assert len(case.calls) == 1


def test_uninvoked_retrieval_failure_cannot_hide_provider_events(tmp_path, monkeypatch):
    case, _, _ = FIXTURES["records"](tmp_path, monkeypatch)
    helpers = FIXTURES["HELPERS"]
    from xgap.experiments.grailqa_semantic_pilot import _infer_one
    from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
    catalog = SimpleNamespace(retrieve=lambda *a, **kw: SimpleNamespace(
        types=(), relations=(), to_dict=lambda: {}))
    state = _infer_one(
        question={"question_id":"q1", "text":"fixture question"}, catalog=catalog,
        provider=SimpleNamespace(generate=lambda *a: pytest.fail("retrieval miss called model")),
        semantic=case.fixture.semantic, retrieval_k=20, candidate_cap=3,
        grounding_policy=SEMANTIC_GROUNDING_POLICY,
    )
    result = audit(case, state, [], catalog=catalog)
    assert result.request is None and result.checked_payloads == ()
    with pytest.raises(InlineEvidenceError):
        audit(case, state, [{"question_id":"q1", "event":"tokenizer_probe_attempt"}], catalog=catalog)
