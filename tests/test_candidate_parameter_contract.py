"""New typed-v2 structure risks only; no inference, catalog build or execution."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from xgap.experiments.hashing import content_hash
from xgap.experiments.one_shot_toy import (
    PROFILE, load_one_shot_toy_provider, one_shot_toy_inputs,
)
from xgap.experiments.toy_binding import interpretation_inputs, load_binding_cases
from xgap.llm.candidate_interpretation import candidate_interpretation_schema
from xgap.semantic.interpretation import InterpretationRequest
from xgap.semantic.interpretation_candidates import (
    SCHEMA, interpret_candidate_question, parse_interpretation_candidates,
)
from xgap.semantic.interpretation_replay import ReplayInterpretationProvider
from xgap.semantic.parameter_contract import (
    PARAMETER_CONTRACT, _issues, validate_program_parameters,
)
from xgap.semantic.program import SemanticProgramError


OBSERVED = Path(__file__).parent / "fixtures/candidate_parameter_contract/observed_failure.json"


def test_saved_real_failure_replay_rejects_both_bad_levels_and_preserves_history():
    before = OBSERVED.read_bytes()
    observation = json.loads(before)
    recording = observation["recording"]
    record = recording["records"][0]
    assert content_hash(record["response"]["payload"]) == observation["payload_sha256"]
    raw = record["request"]
    request = InterpretationRequest(raw["question"], raw["context"],
        tuple(raw["required_constraints"]), raw["max_response_bytes"])
    replay = ReplayInterpretationProvider(recording)
    result = interpret_candidate_question(request, replay, candidate_cap=3)
    replay.assert_consumed()
    assert result["status"] == "no_admissible_interpretation" and result["external_calls"] == 0
    assert result["parameter_contract_version"] == PARAMETER_CONTRACT
    candidate = result["candidates"][0]
    assert candidate["raw_candidate"] == record["response"]["payload"]["candidates"][0]
    assert ".parameters: unknown fields ['constraints', 'required_capabilities']" in candidate["error"]
    assert ".path_pattern: missing fields ['selector', 'target']" in candidate["error"]
    assert ".path_pattern.expr: unknown fields ['condition', 'max_depth', 'restrictor', 'selector', 'target']" in candidate["error"]
    assert result["provenance"]["recorded_usage"]["external_calls"] == 1
    assert observation["historical_outcome"] == {
        "status": "no_executable_interpretation", "admitted_count": 1,
        "candidate_status": "admitted", "grounding_status": "grounding_failed"}
    assert OBSERVED.read_bytes() == before


def test_misnested_path_fields_are_rejected_even_without_duplicate_operator_fields():
    # Independent malformed input, not an edited/repaired copy of the observed response.
    program = {"operators": [{"operator_id": "wrong-level", "kind": "traverse",
        "parameters": {"path_pattern": {"source": {}, "expr": {"kind": "rel", "edge": {},
            "target": {}, "selector": {"kind": "ALL"}, "restrictor": "WALK",
            "condition": None, "max_depth": None}}}, "constraints": []}]}
    before = deepcopy(program)
    with pytest.raises(SemanticProgramError) as failure:
        validate_program_parameters(program)
    assert ".path_pattern.expr: unknown fields" in str(failure.value)
    assert ".parameters: unknown fields" not in str(failure.value)
    assert program == before


def test_old_correct_tiny_candidate_is_unchanged_under_typed_v2_admission():
    request, template = interpretation_inputs(load_binding_cases()[0])
    old = template.interpret(request).payload
    raw = {"schema_version": SCHEMA, "candidates": [{"candidate_id": "existing-tiny",
        "quality_proxy": None, "program": old["program"], "operator_sources": old["operator_sources"]}]}
    before = deepcopy(raw)
    result = parse_interpretation_candidates(raw, request, candidate_cap=1)
    assert result[0]["status"] == "admitted"
    assert result[0]["program"] == old["program"] and raw == before
    assert result[0]["quality_proxy"] is None and not result[0]["quality_proxy_calibrated"]


def test_nine_existing_operator_parameter_shapes_and_internal_schema_fail_closed():
    # Structure examples only: this deliberately is not an executable connected DAG.
    examples = {
        "match": {"node": {"label": {"$hole": "type"}, "properties": {"active": True}},
            "entity_field": "person", "properties": {"age": "age"}},
        "traverse": {"path_pattern": {"path_var": None, "source": {}, "target": {},
            "expr": {"kind": "seq", "left": {"kind": "rel", "edge": {"direction": "OUT"}},
                "right": {"kind": "bounded", "child": {"kind": "rel", "edge": {}},
                    "min_repeats": 0, "max_repeats": 2}}, "selector": {"kind": "ALL", "k": None},
            "restrictor": "TRAIL", "max_depth": 3, "condition": None}},
        "project": {"projections": {"person": {"kind": "field", "field": "person"},
            "node": {"kind": "path_node", "position": "last"}, "edge": {"kind": "path_edge", "position": 1},
            "length": {"kind": "path_length"}}},
        "filter": {"condition": {"op": "and", "args": [
            {"op": "ge", "field": "age", "value": {"$hole": "age"}},
            {"op": "is_not_null", "field": "person"}]}},
        "join": {"left_on": "person", "right_on": "person", "right_prefix": "right_"},
        "union": {},
        "aggregate": {"group_by": [], "aggregations": {"n": {"op": "count"},
            "sum_age": {"op": "sum", "field": "age", "distinct": False}}},
        "order_limit": {"order_by": [{"field": "age", "direction": "desc", "nulls": "last"}], "limit": 10},
        "align": {"field": "person", "output_field": "canonical", "mapping": {"a": "b"}, "on_missing": "drop"},
    }
    validate_program_parameters({"operators": [{"operator_id": kind, "kind": kind,
        "parameters": parameters, "constraints": []} for kind, parameters in examples.items()]})
    schema = candidate_interpretation_schema(3)
    alternatives = schema["properties"]["candidates"]["items"]["properties"]["program"]["properties"]["operators"]["items"]["anyOf"]
    assert {item["properties"]["kind"]["const"] for item in alternatives} == set(examples)
    assert all(item["properties"]["parameters"]["additionalProperties"] is False for item in alternatives)
    with pytest.raises(RuntimeError, match="Unsupported keyword"):
        _issues({"type": "object", "unimplemented_keyword": True}, {}, "internal-contract")


def test_new_typed_b01_precision_complete_wire_stays_inside_existing_byte_guard():
    provider = load_one_shot_toy_provider(mode="precision", disable_thinking=True)
    request, _ = one_shot_toy_inputs(query_id="B01", mode="precision")

    class NoCalls:
        def post_json(self, **kwargs):
            pytest.fail("Wire budget admission must not call any service")

    provider.transport = NoCalls()
    payload = provider.build_request_payload(request)
    check = provider.token_guard.check(payload, call_kind="generation")
    schema = payload["response_format"]["json_schema"]["schema"]
    assert PROFILE == "xgap-one-shot-toy-development-v2"
    assert schema["title"] == PARAMETER_CONTRACT
    assert content_hash(schema) == content_hash(provider.config.structured_schema)
    assert content_hash(schema) != "31415283e165b204a1b3cec38f069e9ea4773585a3ebb6a30f553bd282d1099f"
    assert check["passed"] and check["request_bytes"] <= 65536
    assert check["requested_output_tokens"] == 6144 and provider.config.candidate_cap == 3
    assert not check["exact_input_tokens_verified"] and not check["context_fit_verified"]
    print(json.dumps({"request_bytes": check["request_bytes"], "request_limit_bytes": 65536,
        "schema_sha256": content_hash(schema), "prompt_sha256": provider.config.prompt_hash,
        "external_calls": 0}, sort_keys=True))
