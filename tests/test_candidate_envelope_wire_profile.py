"""Envelope-only server grammar with unchanged typed local admission."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from test_interpretation_candidates import candidate_inputs, pool
from test_one_shot_toy import frozen_model
from xgap.experiments.hashing import content_hash
from xgap.experiments.one_shot_toy import load_one_shot_toy_provider, one_shot_toy_preflight
from xgap.llm.candidate_interpretation import candidate_wire_profile
from xgap.semantic.interpretation_candidates import interpret_candidate_question
from xgap.semantic.parameter_contract import PARAMETER_CONTRACT


TYPED_HASH = "b8647be9dffe1aa6bbf06318a209b19c0e0b6aa539d5e9e1cc00bec87fd0d2ee"
ENVELOPE_HASH = "31415283e165b204a1b3cec38f069e9ea4773585a3ebb6a30f553bd282d1099f"


def test_explicit_envelope_schema_restores_original_wire_without_changing_prior_profiles():
    provider = load_one_shot_toy_provider(wire_profile="envelope-schema-v1")
    config = provider.config
    assert candidate_wire_profile(config.structured_output_mode, config.schema_profile) == "envelope-schema-v1"
    assert content_hash(config.structured_schema) == ENVELOPE_HASH
    assert config.structured_schema["properties"]["candidates"]["maxItems"] == config.candidate_cap == 3
    operators = config.structured_schema["properties"]["candidates"]["items"]["properties"]["program"]["properties"]["operators"]
    assert operators["items"]["properties"]["parameters"] == {"type": "object"}
    assert "$defs" not in config.structured_schema
    assert "BEGIN LOCAL RESPONSE SPECIFICATION" not in provider.system_prompt
    assert "are siblings of parameters" in provider.system_prompt
    assert config.prompt_hash == "560dc1ad5337dade405c730576ca3d6aec64707bd6fa65cbdd0201fd0ea8c0e0"
    default = load_one_shot_toy_provider()
    previous_json_object = load_one_shot_toy_provider(wire_profile="json-object-v1")
    assert content_hash(default.config.structured_schema) == TYPED_HASH
    assert default.config.prompt_hash == config.prompt_hash
    assert previous_json_object.config.prompt_hash == "33045f3fa519c04397fe879c92dd0775c6e52fd756c79871823ac9dd6e6f973d"
    assert provider.provider_id == default.provider_id + ":envelope-schema-v1"
    with pytest.raises(ValueError, match="schema profile differs"):
        replace(config, schema_profile="typed-v1")
    with pytest.raises(ValueError, match="mode/schema profile combination"):
        candidate_wire_profile("json_object", "envelope-v1")


def test_envelope_preflight_records_distinct_wire_local_hashes_and_original_bounds(tmp_path):
    provider = load_one_shot_toy_provider(wire_profile="envelope-schema-v1", disable_thinking=True)

    class NoTransport:
        def post_json(self, **kwargs):
            pytest.fail("Preflight cannot issue any model request")

    provider.transport = NoTransport()
    report, request, _, _ = one_shot_toy_preflight(provider, estimator_path=frozen_model(tmp_path))
    assert report["success"] and report["external_calls"] == report["backend_calls"] == 0
    config = report["config"]
    assert report["wire_profile"] == config["wire_profile"] == "envelope-schema-v1"
    assert config["structured_output_mode"] == "json_schema" and config["schema_profile"] == "envelope-v1"
    assert config["wire_schema_hash"] == config["structured_schema_hash"] == ENVELOPE_HASH
    assert config["local_admission_schema_hash"] == TYPED_HASH
    assert config["parameter_contract_version"] == PARAMETER_CONTRACT
    payload = provider.build_request_payload(request)
    assert payload["response_format"]["json_schema"]["schema"] == provider.config.structured_schema
    assert report["request_budget"]["request_bytes"] <= 65536
    assert report["request_budget"]["requested_output_tokens"] == 6144
    print(json.dumps({"wire_profile": report["wire_profile"],
        "request_bytes": report["request_budget"]["request_bytes"],
        "wire_schema_hash": config["wire_schema_hash"],
        "local_admission_schema_hash": config["local_admission_schema_hash"],
        "prompt_hash": config["prompt_hash"], "external_calls": 0}, sort_keys=True))


def test_original_bad_response_is_still_rejected_locally_under_envelope_wire(monkeypatch):
    request, good = candidate_inputs()
    observed = json.loads((Path(__file__).parent / "fixtures/candidate_parameter_contract/observed_failure.json").read_text())
    original_bad = observed["recording"]["records"][0]["response"]["payload"]["candidates"][0]
    raw = pool(original_bad, good)
    before = deepcopy(raw)
    provider = load_one_shot_toy_provider(wire_profile="envelope-schema-v1")
    calls = []

    class ControlledTransport:
        def post_json(self, **kwargs):
            calls.append(kwargs)
            return {"model": provider.config.model,
                "usage": {"prompt_tokens": 100, "completion_tokens": 70, "total_tokens": 170},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}]}

    provider.transport = ControlledTransport()
    monkeypatch.setenv(provider.config.api_key_env, "controlled-envelope-wire-secret")
    result = interpret_candidate_question(request, provider, candidate_cap=3)
    assert result["status"] == "interpreted" and result["admitted_count"] == 1
    assert [item["status"] for item in result["candidates"]] == ["invalid", "admitted"]
    rejected = result["candidates"][0]
    assert ".parameters: unknown fields ['constraints', 'required_capabilities']" in rejected["error"]
    assert ".path_pattern.expr: unknown fields" in rejected["error"]
    assert rejected["raw_candidate"] == original_bad and raw == before
    assert result["external_calls"] == len(calls) == 1 and result["automatic_retries"] == 0
    assert (result["input_tokens"], result["output_tokens"]) == (100, 70)
    assert result["provenance"]["config"]["wire_schema_hash"] == ENVELOPE_HASH
    assert result["provenance"]["config"]["local_admission_schema_hash"] == TYPED_HASH
