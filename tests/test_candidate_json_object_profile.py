"""Explicit compatibility wire risks only; all model transport is controlled."""

from copy import deepcopy
import json

import pytest

from test_interpretation_candidates import candidate_inputs, pool
from test_one_shot_toy import frozen_model
from xgap.experiments.hashing import content_hash
from xgap.experiments.one_shot_toy import (
    load_one_shot_toy_provider, one_shot_toy_inputs, one_shot_toy_preflight,
)
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError
from xgap.semantic.interpretation_candidates import interpret_candidate_question


class ControlledTransport:
    def __init__(self, response):
        self.response, self.calls = response, []

    def post_json(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return deepcopy(self.response)


def test_explicit_compatibility_wire_keeps_typed_hash_prompt_identity_and_full_byte_guard(tmp_path):
    default = load_one_shot_toy_provider(disable_thinking=True)
    compatible = load_one_shot_toy_provider(wire_profile="json-object-v1", disable_thinking=True)
    compatible.transport = ControlledTransport(AssertionError("Zero-call preflight reached transport"))
    assert default.config.structured_output_mode == "json_schema"
    assert compatible.config.structured_output_mode == "json_object"
    assert default.config.structured_schema == compatible.config.structured_schema
    assert default.config.prompt_hash == "560dc1ad5337dade405c730576ca3d6aec64707bd6fa65cbdd0201fd0ea8c0e0"
    assert compatible.config.prompt_hash != default.config.prompt_hash
    assert compatible.provider_id == default.provider_id + ":json-object-v1"
    request, _ = one_shot_toy_inputs()
    payload = compatible.build_request_payload(request)
    assert payload["response_format"] == {"type": "json_object"}
    assert "json_schema" not in payload["response_format"]
    schema_text = compatible.system_prompt.split("BEGIN LOCAL RESPONSE SPECIFICATION\n")[1].split(
        "\nEND LOCAL RESPONSE SPECIFICATION")[0]
    assert json.loads(schema_text) == compatible.config.structured_schema
    assert content_hash(compatible.system_prompt) == compatible.config.prompt_hash
    # Frozen unit fixture; no native label collection and no fit during preflight.
    estimator = frozen_model(tmp_path)
    result, _, _, _ = one_shot_toy_preflight(compatible, estimator_path=estimator)
    assert result["success"] and result["wire_profile"] == "json-object-v1"
    assert result["external_calls"] == result["backend_calls"] == 0 and not compatible.transport.calls
    check = result["request_budget"]
    assert check["request_bytes"] <= 65536 and check["requested_output_tokens"] == 6144
    assert not check["exact_input_tokens_verified"] and not check["context_fit_verified"]
    assert result["config"]["structured_schema_hash"] == content_hash(default.config.structured_schema)
    assert result["config"]["structured_output_mode"] == "json_object"
    with pytest.raises(ValueError, match="Unsupported candidate wire profile"):
        load_one_shot_toy_provider(wire_profile="automatic-fallback")
    print(json.dumps({"wire_profile": result["wire_profile"], "request_bytes": check["request_bytes"],
        "schema_sha256": content_hash(compatible.config.structured_schema),
        "prompt_sha256": compatible.config.prompt_hash, "external_calls": 0}, sort_keys=True))


def test_one_compatibility_response_still_rejects_bad_structure_and_entity_authority(monkeypatch):
    request, good = candidate_inputs()
    bad_structure = deepcopy(good)
    bad_structure["candidate_id"] = "bad-parameters"
    bad_structure["program"]["operators"][0]["parameters"]["constraints"] = []
    bad_identity = deepcopy(good)
    bad_identity["candidate_id"] = "invented-authority"
    bad_identity["program"]["holes"][0].update(candidates=["invented:alice"], is_resolved=True)
    raw = pool(bad_structure, bad_identity, good)
    provider = load_one_shot_toy_provider(wire_profile="json-object-v1")
    provider.transport = ControlledTransport({"model": provider.config.model,
        "usage": {"prompt_tokens": 100, "completion_tokens": 70, "total_tokens": 170},
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}]})
    monkeypatch.setenv(provider.config.api_key_env, "controlled-json-object-secret")
    result = interpret_candidate_question(request, provider, candidate_cap=3)
    assert result["status"] == "interpreted" and result["admitted_count"] == 1
    assert [item["status"] for item in result["candidates"]] == ["invalid", "invalid", "admitted"]
    assert ".parameters: unknown fields ['constraints']" in result["candidates"][0]["error"]
    assert result["candidates"][1]["raw_candidate"] == bad_identity
    assert result["raw_response"] == raw
    assert result["external_calls"] == len(provider.transport.calls) == 1
    assert (result["input_tokens"], result["output_tokens"]) == (100, 70)
    assert result["automatic_retries"] == 0
    assert provider.transport.calls[0]["payload"]["response_format"] == {"type": "json_object"}
    assert "controlled-json-object-secret" not in json.dumps(result)


def test_explicit_compatibility_http_failure_is_not_retried_or_priced_as_known_tokens(monkeypatch):
    request, _ = candidate_inputs()
    provider = load_one_shot_toy_provider(wire_profile="json-object-v1")
    provider.transport = ControlledTransport(ProviderTransportError(
        LiveFailureCategory.PROVIDER_ERROR, "Controlled HTTP 500; no server cause or usage available"))
    monkeypatch.setenv(provider.config.api_key_env, "controlled-json-object-secret")
    result = interpret_candidate_question(request, provider, candidate_cap=3)
    assert result["status"] == "provider_failure" and result["failure_category"] == "provider_error"
    assert result["external_calls"] == len(provider.transport.calls) == 1
    assert result["external_call_count_complete"] is True
    assert result["usage_unavailable"] and not result["token_usage_complete"]
    assert result["automatic_retries"] == 0 and "raw_response" not in result
    assert result["provenance"]["config"]["structured_output_mode"] == "json_object"
    assert result["provenance"]["request_payload"]["response_format"] == {"type": "json_object"}
    assert provider.config.max_repair_calls == 0
