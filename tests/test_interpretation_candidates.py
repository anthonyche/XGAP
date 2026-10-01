"""Candidate-local admission and one-response accounting, without execution."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from xgap.experiments.toy_binding import interpretation_inputs, load_binding_cases
from xgap.semantic.interpretation import InterpretationFailure, InterpretationResponse
from xgap.semantic.interpretation_candidates import (
    SCHEMA, interpret_candidate_question, parse_interpretation_candidates,
)


def candidate_inputs():
    request, template = interpretation_inputs(load_binding_cases()[0])
    program = template.interpret(request).payload
    candidate = {"candidate_id": "meaning-a", "quality_proxy": 0.8,
                 "program": deepcopy(program["program"]),
                 "operator_sources": deepcopy(program["operator_sources"])}
    return request, candidate


def pool(*candidates):
    return {"schema_version": SCHEMA, "candidates": list(candidates)}


class Provider:
    provider_id = "controlled-candidate-provider"

    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def interpret(self, request):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return InterpretationResponse(deepcopy(self.payload), external_calls=1,
                                      input_tokens=11, output_tokens=7)


def test_candidate_failures_are_local_and_do_not_repair_or_claim_entity_authority():
    request, good = candidate_inputs()
    invalid = []
    for identifier in ("operator", "entity-authority", "hard-constraint", "quality"):
        item = deepcopy(good)
        item["candidate_id"] = identifier
        if identifier == "operator":
            item["program"]["operators"][0]["kind"] = "invented"
        elif identifier == "entity-authority":
            item["program"]["holes"][0].update(candidates=["entity:alice"], is_resolved=True)
        elif identifier == "hard-constraint":
            item["program"]["operators"][0]["constraints"] = []
        else:
            item["quality_proxy"] = 1.01
        invalid.append(item)
    raw = pool(*invalid, good)
    original = deepcopy(raw)
    result = parse_interpretation_candidates(raw, request, candidate_cap=5)
    assert [item["status"] for item in result] == ["invalid"] * 4 + ["admitted"]
    assert all(item["error"] and item["raw_candidate"] == invalid[i]
               for i, item in enumerate(result[:4]))
    assert result[-1]["program"]["holes"][0]["candidates"] == []
    assert raw == original


def test_duplicate_ids_are_all_rejected_but_unknown_quality_is_still_admissible():
    request, good = candidate_inputs()
    unknown = {**deepcopy(good), "candidate_id": "unknown-quality", "quality_proxy": None}
    result = parse_interpretation_candidates(pool(good, deepcopy(good), unknown), request, candidate_cap=3)
    assert [item["status"] for item in result] == ["invalid", "invalid", "admitted"]
    assert result[-1]["quality_proxy"] is None and result[-1]["quality_proxy_calibrated"] is False
    assert all("Duplicate" in item["error"] for item in result[:2])


def test_nonfinite_injected_candidate_retains_valid_sibling_and_serializable_evidence():
    request, good = candidate_inputs()
    bad = {**deepcopy(good), "candidate_id": "bad", "quality_proxy": float("nan")}
    report = interpret_candidate_question(request, Provider(pool(bad, good)), candidate_cap=2)
    assert report["success"] and report["admitted_count"] == 1
    assert report["candidates"][0]["status"] == "invalid"
    assert "NaN" in report["candidates"][0]["raw_candidate_text"]
    json.dumps(report, allow_nan=False)


def test_pool_budget_is_not_silent_truncation_and_invalid_envelope_retains_raw():
    request, good = candidate_inputs()
    another = {**deepcopy(good), "candidate_id": "b"}
    model = Provider(pool(good, another))
    report = interpret_candidate_question(request, model, candidate_cap=1)
    assert not report["success"] and report["status"] == "interpretation_invalid"
    assert report["candidates"] == [] and report["raw_response"] == model.payload
    assert report["external_calls"] == model.calls == 1
    for bad_cap in (0, 9, True):
        with pytest.raises(ValueError):
            interpret_candidate_question(request, model, candidate_cap=bad_cap)
    assert model.calls == 1
    small = replace(request, max_response_bytes=100)
    with pytest.raises(ValueError, match="byte bound"):
        parse_interpretation_candidates(pool(good), small, candidate_cap=1)


def test_pool_charges_one_response_once_and_cannot_mutate_caller_admission_requirements():
    request, good = candidate_inputs()
    original = request.to_dict()

    class MutatingProvider(Provider):
        def interpret(self, request):
            request.required_constraints[0]["constraint"]["expression"] = "changed by provider"
            return super().interpret(request)

    model = MutatingProvider(pool(good, {**deepcopy(good), "candidate_id": "b"}))
    report = interpret_candidate_question(request, model, candidate_cap=2)
    assert report["success"] and report["admitted_count"] == 2
    assert (report["external_calls"], report["input_tokens"], report["output_tokens"]) == (1, 11, 7)
    assert model.calls == 1 and request.to_dict() == original
    assert report["token_usage_complete"] is True


def test_all_invalid_and_provider_failure_are_distinct_terminal_results():
    request, good = candidate_inputs()
    good["program"]["operators"][0]["kind"] = "invalid"
    invalid = interpret_candidate_question(request, Provider(pool(good)), candidate_cap=1)
    assert invalid["status"] == "no_admissible_interpretation" and not invalid["success"]
    assert invalid["candidates"][0]["raw_candidate"] == good
    model = Provider(InterpretationFailure("timeout", "controlled timeout",
        usage={"external_calls": 1}, provenance={"usage_reported": False}))
    failure = interpret_candidate_question(request, model, candidate_cap=1)
    assert failure["status"] == "provider_failure" and not failure["token_usage_complete"]
    assert failure["external_calls"] == model.calls == 1 and failure["automatic_retries"] == 0
