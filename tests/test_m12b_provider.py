from __future__ import annotations

import io
import json
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.hashing import content_hash
from xgap.llm.openai_compatible import (
    LiveFailureCategory,
    LiveProviderError,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleStructuredCandidateProvider,
    ProviderTransportError,
    UrllibOpenAICompatibleTransport,
    redact_secrets,
)
from xgap.llm.schemas import PlannerRequest


ROOT = Path(__file__).resolve().parents[1]


def _candidate(candidate_id: str = "candidate-1") -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "confidence": 0.9,
        "rationale": "Grounded development candidate.",
        "pattern_query": {
            "path_var": "p",
            "source": {"var": "person", "label": "Person", "properties": {}},
            "expr": {
                "kind": "rel",
                "edge": {
                    "var": "transfer",
                    "label": "TRANSFER",
                    "direction": "OUT",
                    "properties": {},
                },
            },
            "target": {"var": "account", "label": "Account", "properties": {}},
            "selector": {"kind": "ALL", "k": None},
            "restrictor": "TRAIL",
            "condition": None,
            "max_depth": None,
        },
        "grounding": {
            "slot_realizations": [
                {
                    "slot_id": "slot-1-transfer",
                    "ontology_term_id": "Transfer",
                    "component_ref": "expr.edge",
                }
            ],
            "entity_ids": [],
        },
    }


def _structured(*candidates: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": "fake-openai-compatible",
        "model": "fixed-test-model",
        "query_slots": [
            {"slot_id": "slot-1-transfer", "query_anchor_id": "Transfer"}
        ],
        "candidates": [dict(item) for item in candidates],
    }


def _envelope(content: object, *, request_id: str = "request-1") -> dict[str, Any]:
    return {
        "id": request_id,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 101, "completion_tokens": 57, "total_tokens": 158},
    }


def _request(max_candidates: int = 2) -> PlannerRequest:
    return PlannerRequest(
        "Find accounts reached by transfer.",
        max_candidates=max_candidates,
        metadata={
            "task_id": "task-1",
            "prompt_schema_view": {
                "ontology": {"id": "test", "version": "v1", "hash": "hash"},
                "terms": [{"term_id": "Transfer", "kind": "relation"}],
                "entities": [],
                "query_slots": [
                    {
                        "slot_id": "slot-1-transfer",
                        "candidate_anchor_ids": ["Transfer"],
                    }
                ],
            },
        },
    )


def _config(*, max_repair_calls: int = 1) -> OpenAICompatibleProviderConfig:
    return OpenAICompatibleProviderConfig(
        provider_id="test-openai-compatible",
        base_url="https://provider.invalid/v1",
        api_key_env="XGAP_TEST_API_KEY",
        model="fixed-test-model",
        temperature=0.0,
        top_p=1.0,
        max_tokens=2048,
        candidate_cap=2,
        timeout_seconds=5.0,
        structured_output_mode="json_schema",
        structured_schema={"type": "object"},
        prompt_hash="prompt-hash",
        seed=7,
        seed_supported=True,
        max_repair_calls=max_repair_calls,
    )


@dataclass
class FakeTransport:
    responses: list[Mapping[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        return self.responses.pop(0)


def test_live_model_bundles_load_with_fixed_snapshots_and_portable_vllm() -> None:
    dashscope = ModelBundle.load(ROOT / "models/qwen3_max_dashscope_live")
    vllm = ModelBundle.load(ROOT / "models/qwen3_vllm_template")

    assert dashscope.config.exact_model_snapshot == "qwen3-max-2026-01-23"
    assert dashscope.config.provider == "dashscope_openai_compatible"
    assert dashscope.config.base_url_env == "DASHSCOPE_BASE_URL"
    assert dashscope.structured_schema is not None
    assert vllm.config.provider == "vllm_openai_compatible"
    assert vllm.config.base_url == "http://127.0.0.1:8000/v1"
    assert vllm.config.base_url_env == "XGAP_VLLM_BASE_URL"
    assert not Path(vllm.config.base_url).is_absolute()


def test_structured_request_is_bounded_and_contains_no_credentials(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_TEST_API_KEY", "secret-value")
    transport = FakeTransport([_envelope(json.dumps(_structured(_candidate())))])
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(), "Return controlled JSON only.", transport
    )

    response = provider.generate_candidates(_request())

    assert len(response["candidates"]) == 1
    assert len(transport.calls) == 1
    payload = transport.calls[0]["payload"]
    assert payload["model"] == "fixed-test-model"
    assert payload["response_format"]["type"] == "json_schema"
    assert "prompt_schema_view" in payload["messages"][1]["content"]
    assert "secret-value" not in json.dumps(payload)
    artifact = provider.last_invocation
    assert artifact is not None
    assert artifact.generation_calls == 1
    assert artifact.repair_calls == 0
    assert artifact.input_tokens == 101
    assert artifact.output_tokens == 57
    assert artifact.total_tokens == 158
    assert artifact.provider_request_ids == ("request-1",)
    request_records = artifact.request_records()
    assert len(request_records) == 1
    assert request_records[0]["call_kind"] == "generation"
    assert request_records[0]["payload"] == payload
    assert request_records[0]["payload_hash"] == content_hash(payload)
    assert "secret-value" not in json.dumps(request_records)


def test_empty_prompt_schema_view_fails_before_network() -> None:
    transport = FakeTransport([])
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(), "Return controlled JSON only.", transport
    )
    request = PlannerRequest(
        "Find accounts reached by transfer.",
        max_candidates=2,
        metadata={"task_id": "task-1", "prompt_schema_view": {}},
    )

    with pytest.raises(ValueError, match="ontology context"):
        provider.generate_candidates(request)

    assert transport.calls == []


def test_missing_api_key_fails_without_network(monkeypatch) -> None:
    monkeypatch.delenv("XGAP_TEST_API_KEY", raising=False)
    transport = FakeTransport([])
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(), "Return controlled JSON only.", transport
    )

    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(_request())

    assert caught.value.category is LiveFailureCategory.PROVIDER_ERROR
    assert caught.value.artifact.generation_calls == 0
    assert transport.calls == []


def test_protocol_allows_exactly_one_repair_call(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_TEST_API_KEY", "secret-value")
    transport = FakeTransport(
        [
            _envelope("not-json", request_id="request-invalid"),
            _envelope(json.dumps(_structured(_candidate())), request_id="request-repaired"),
        ]
    )
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(), "Return controlled JSON only.", transport
    )

    provider.generate_candidates(_request())

    assert len(transport.calls) == 2
    assert transport.calls[1]["payload"]["messages"][-1]["role"] == "user"
    artifact = provider.last_invocation
    assert artifact is not None
    assert artifact.generation_calls == 1
    assert artifact.repair_calls == 1
    assert [item["call_kind"] for item in artifact.request_records()] == [
        "generation",
        "repair",
    ]


def test_second_invalid_response_fails_as_repair_failed(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_TEST_API_KEY", "secret-value")
    transport = FakeTransport([_envelope("not-json"), _envelope("still-not-json")])
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(), "Return controlled JSON only.", transport
    )

    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(_request())

    assert caught.value.category is LiveFailureCategory.REPAIR_FAILED
    assert caught.value.artifact.generation_calls == 1
    assert caught.value.artifact.repair_calls == 1
    assert len(transport.calls) == 2


def test_duplicate_live_candidate_ids_are_structured_output_errors(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_TEST_API_KEY", "secret-value")
    transport = FakeTransport(
        [_envelope(json.dumps(_structured(_candidate(), _candidate())))]
    )
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(max_repair_calls=0), "Return controlled JSON only.", transport
    )

    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(_request())

    assert caught.value.category is LiveFailureCategory.STRUCTURED_OUTPUT_ERROR


def test_candidate_cap_is_enforced_before_provider_call(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_TEST_API_KEY", "secret-value")
    transport = FakeTransport([])
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(), "Return controlled JSON only.", transport
    )

    with pytest.raises(ValueError, match="candidate cap"):
        provider.generate_candidates(_request(max_candidates=3))

    assert transport.calls == []


def test_transport_error_and_nested_credentials_are_redacted(monkeypatch) -> None:
    class FailingTransport:
        def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
            raise ProviderTransportError(
                LiveFailureCategory.TIMEOUT,
                f"timeout for {kwargs['api_key']}",
            )

    monkeypatch.setenv("XGAP_TEST_API_KEY", "secret-value")
    provider = OpenAICompatibleStructuredCandidateProvider(
        _config(), "Return controlled JSON only.", FailingTransport()
    )
    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(_request())

    serialized = json.dumps(caught.value.artifact.to_dict())
    assert caught.value.category is LiveFailureCategory.TIMEOUT
    assert "secret-value" not in serialized
    assert redact_secrets({"headers": {"Authorization": "secret-value"}}) == {
        "headers": "[REDACTED]"
    }


def test_http_401_explains_dashscope_endpoint_key_compatibility(monkeypatch) -> None:
    def reject(*args: Any, **kwargs: Any):
        del args, kwargs
        raise urllib.error.HTTPError(
            "https://provider.invalid/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":{"code":"invalid_api_key"}}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", reject)
    transport = UrllibOpenAICompatibleTransport()

    with pytest.raises(ProviderTransportError) as caught:
        transport.post_json(
            url="https://dashscope.invalid/v1/chat/completions",
            api_key="secret-value",
            payload={"model": "fixed-test-model", "messages": []},
            timeout_seconds=1.0,
        )

    assert caught.value.category is LiveFailureCategory.PROVIDER_ERROR
    assert "same DashScope region, workspace, and billing plan" in str(caught.value)
    assert "secret-value" not in str(caught.value)


def test_failure_taxonomy_is_stable_and_complete() -> None:
    required = {
        "provider_error",
        "timeout",
        "structured_output_error",
        "repair_failed",
        "invalid_candidate",
        "hallucinated_ontology_id",
        "unresolved_query_anchor",
        "incomplete_slot_coverage",
        "missing_backend_mapping",
        "semantic_inadmissible",
        "representation_unsupported",
        "compiler_unsupported",
    }
    assert {item.value for item in LiveFailureCategory} == required
