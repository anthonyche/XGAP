from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.agent import (
    GoalLoop,
    GoalStatus,
    MemoryScope,
    SelectiveResolutionConfig,
    SelectiveSemanticResolutionPolicy,
    build_selective_resolution_goal,
    selective_resolution_environment,
)
from xgap.llm import (
    LiveFailureCategory,
    M15_RESOLUTION_BASE_SCHEMA,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleResolutionCandidateProvider,
    build_openai_compatible_resolution_provider,
)
from xgap.llm.openai_compatible import ProviderTransportError
from xgap.semantic import (
    SemanticGraphProgram,
    SemanticHole,
    SemanticHoleKind,
    SemanticOperator,
    SemanticOperatorKind,
    SemanticValueKind,
)
from xgap.tools import (
    ResolutionCandidateRequest,
    ResolutionCandidateTool,
    ResolutionProviderFailure,
    SEMANTIC_LLM_PROPOSE_TOOL,
    ToolContext,
    ToolEffect,
    ToolRegistry,
    ToolStatus,
)


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _Transport:
    responses: list[Mapping[str, Any]] = field(default_factory=list)
    failure: ProviderTransportError | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(dict(kwargs))
        if self.failure is not None:
            raise self.failure
        return self.responses.pop(0)


def _config(
    *,
    max_repair_calls: int = 0,
    schema: Mapping[str, Any] = M15_RESOLUTION_BASE_SCHEMA,
) -> OpenAICompatibleProviderConfig:
    return OpenAICompatibleProviderConfig(
        provider_id="test-openai-compatible",
        base_url="https://provider.invalid/v1",
        api_key_env="XGAP_M15_TEST_API_KEY",
        model="fixed-test-model",
        temperature=0.0,
        top_p=1.0,
        max_tokens=256,
        candidate_cap=8,
        timeout_seconds=5.0,
        structured_output_mode="json_schema",
        structured_schema=dict(schema),
        prompt_hash="a" * 64,
        seed=0,
        seed_supported=True,
        max_repair_calls=max_repair_calls,
    )


def _request(
    *,
    kind: SemanticHoleKind = SemanticHoleKind.PREDICATE,
) -> ResolutionCandidateRequest:
    return ResolutionCandidateRequest(
        program_id="financial-risk",
        hole_id="transfer-predicate",
        hole_kind=kind,
        mention="funded",
        candidate_ids=("predicate:paid", "predicate:invested"),
        question="Which companies did Alice fund?",
        hard_constraints_sha256="b" * 64,
        max_candidates=8,
    )


def _envelope(content: object) -> dict[str, Any]:
    return {
        "id": "request-1",
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 44,
            "completion_tokens": 7,
            "total_tokens": 51,
        },
    }


def _provider(transport: _Transport) -> OpenAICompatibleResolutionCandidateProvider:
    return OpenAICompatibleResolutionCandidateProvider(
        _config(),
        "Select only supplied semantic candidate IDs.",
        transport,
    )


def test_frozen_cwru_model_bundle_builds_no_repair_resolution_provider() -> None:
    bundle = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_m15e2")

    provider = build_openai_compatible_resolution_provider(bundle, _Transport())

    assert bundle.bundle_hash == (
        "5730c5084e5388f9c680fb3492a8332598b6a27d3e963229cb5513cdc7acb3f5"
    )
    assert provider.config.model == "Qwen/Qwen3-32B"
    assert provider.config.max_repair_calls == 0
    assert provider.config.timeout_seconds == 60.0
    assert provider.config.candidate_cap == 8


def test_success_uses_one_request_and_dynamic_candidate_enum(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_M15_TEST_API_KEY", "secret-value")
    structured = {
        "hole_id": "transfer-predicate",
        "candidate_ids": ["predicate:invested"],
    }
    transport = _Transport([_envelope(json.dumps(structured))])
    provider = _provider(transport)

    response = provider.resolve(
        _request(),
        ToolContext("goal", 1, "call"),
    )

    assert response.candidate_ids == ("predicate:invested",)
    assert response.authoritative is False
    assert response.external_calls == 1
    assert response.input_tokens == 44
    assert response.output_tokens == 7
    assert len(transport.calls) == 1
    payload = transport.calls[0]["payload"]
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["hole_id"]["const"] == "transfer-predicate"
    assert schema["properties"]["candidate_ids"]["items"]["enum"] == [
        "predicate:paid",
        "predicate:invested",
    ]
    assert schema["properties"]["candidate_ids"]["maxItems"] == 2
    # vLLM 0.11.1 rejects uniqueItems in its guided-decoding grammar.  XGAP
    # retains the uniqueness contract in the deterministic response validator.
    assert "uniqueItems" not in schema["properties"]["candidate_ids"]
    assert "secret-value" not in json.dumps(payload)
    assert provider.last_invocation is not None
    assert provider.last_invocation.external_calls == 1
    assert provider.last_invocation.status == "success"
    assert response.metadata["provider_repair_calls"] == 0


def test_duplicate_candidate_ids_are_rejected_after_provider_response(
    monkeypatch,
) -> None:
    monkeypatch.setenv("XGAP_M15_TEST_API_KEY", "secret-value")
    structured = {
        "hole_id": "transfer-predicate",
        "candidate_ids": ["predicate:paid", "predicate:paid"],
    }
    transport = _Transport([_envelope(json.dumps(structured))])
    provider = _provider(transport)

    with pytest.raises(ResolutionProviderFailure, match="must be unique") as caught:
        provider.resolve(
            _request(),
            ToolContext("goal", 1, "call"),
        )

    assert caught.value.external_calls == 1
    assert caught.value.failure_category == "structured_output_error"
    assert len(transport.calls) == 1
    schema = transport.calls[0]["payload"]["response_format"]["json_schema"][
        "schema"
    ]
    assert "uniqueItems" not in schema["properties"]["candidate_ids"]


def test_entity_request_fails_before_network(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_M15_TEST_API_KEY", "secret-value")
    transport = _Transport([])
    provider = _provider(transport)

    with pytest.raises(ResolutionProviderFailure, match="user clarification") as caught:
        provider.resolve(
            _request(kind=SemanticHoleKind.ENTITY),
            ToolContext("goal", 1, "call"),
        )

    assert caught.value.external_calls == 0
    assert transport.calls == []
    assert provider.last_invocation is not None
    assert provider.last_invocation.failure_category == "preflight_error"


def test_missing_api_key_fails_with_zero_external_calls(monkeypatch) -> None:
    monkeypatch.delenv("XGAP_M15_TEST_API_KEY", raising=False)
    transport = _Transport([])
    provider = _provider(transport)

    with pytest.raises(ResolutionProviderFailure, match="is unset") as caught:
        provider.resolve(_request(), ToolContext("goal", 1, "call"))

    assert caught.value.external_calls == 0
    assert transport.calls == []
    assert provider.last_invocation is not None
    assert provider.last_invocation.request_payload_sha256 is not None


def test_provider_rejects_repair_enabled_config() -> None:
    with pytest.raises(ValueError, match="forbids provider repair calls"):
        OpenAICompatibleResolutionCandidateProvider(
            _config(max_repair_calls=1),
            "Select only supplied semantic candidate IDs.",
            _Transport([]),
        )


def test_provider_rejects_a_different_static_schema() -> None:
    with pytest.raises(ValueError, match="unsupported base schema"):
        OpenAICompatibleResolutionCandidateProvider(
            _config(schema={"type": "object"}),
            "Select only supplied semantic candidate IDs.",
            _Transport([]),
        )


def test_bundle_factory_rejects_prompt_schema_binding_drift() -> None:
    bundle = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_m15e2")
    bad_prompt = replace(
        bundle.prompt,
        structured_output_schema={
            "ref": "structured_schema.json",
            "hash": "0" * 64,
        },
    )
    drifted = ModelBundle(
        root=bundle.root,
        config=bundle.config,
        prompt=bad_prompt,
        structured_schema=bundle.structured_schema,
    )

    with pytest.raises(ValueError, match="schema bindings disagree"):
        build_openai_compatible_resolution_provider(drifted, _Transport())


def test_malformed_response_fails_after_one_call_without_repair(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_M15_TEST_API_KEY", "secret-value")
    transport = _Transport([_envelope("not-json")])
    provider = _provider(transport)

    with pytest.raises(ResolutionProviderFailure, match="not JSON") as caught:
        provider.resolve(_request(), ToolContext("goal", 1, "call"))

    assert caught.value.external_calls == 1
    assert len(transport.calls) == 1
    assert provider.last_invocation is not None
    assert provider.last_invocation.failure_category == (
        LiveFailureCategory.STRUCTURED_OUTPUT_ERROR.value
    )


def test_unbounded_response_is_a_costed_tool_error_not_a_retry(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_M15_TEST_API_KEY", "secret-value")
    structured = {
        "hole_id": "transfer-predicate",
        "candidate_ids": ["predicate:hallucinated"],
    }
    transport = _Transport([_envelope(structured)])
    provider = _provider(transport)
    tool = ResolutionCandidateTool(
        name=SEMANTIC_LLM_PROPOSE_TOOL,
        description="bounded M15 LLM candidate proposal",
        provider=provider,
        may_introduce_candidates=False,
        effect=ToolEffect.EXTERNAL,
        remote=True,
        maximum_external_calls=1,
    )

    result = tool.invoke(
        _request().to_dict(),
        ToolContext("goal", 1, "call"),
    )

    assert result.status is ToolStatus.ERROR
    assert "unbounded candidate ID" in result.error
    assert result.metrics["external_calls"] == 1.0
    assert result.metrics["input_tokens"] == 44.0
    assert result.metadata["provider_repair_calls"] == 0
    assert len(transport.calls) == 1


def test_transport_timeout_is_preserved_as_one_failed_external_call(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_M15_TEST_API_KEY", "secret-value")
    transport = _Transport(
        failure=ProviderTransportError(
            LiveFailureCategory.TIMEOUT,
            "provider timed out",
        )
    )
    provider = _provider(transport)

    with pytest.raises(ResolutionProviderFailure, match="timed out") as caught:
        provider.resolve(_request(), ToolContext("goal", 1, "call"))

    assert caught.value.failure_category == LiveFailureCategory.TIMEOUT.value
    assert caught.value.external_calls == 1
    assert len(transport.calls) == 1
    assert provider.last_invocation is not None
    assert provider.last_invocation.external_calls == 1


def test_provider_runs_through_goal_loop_trace_and_execution_memory(monkeypatch) -> None:
    monkeypatch.setenv("XGAP_M15_TEST_API_KEY", "secret-value")
    transport = _Transport(
        [
            _envelope(
                {
                    "hole_id": "transfer-predicate",
                    "candidate_ids": ["predicate:invested"],
                }
            )
        ]
    )
    provider = _provider(transport)
    tool = ResolutionCandidateTool(
        name=SEMANTIC_LLM_PROPOSE_TOOL,
        description="bounded M15 LLM candidate proposal",
        provider=provider,
        may_introduce_candidates=False,
        effect=ToolEffect.EXTERNAL,
        remote=True,
        maximum_external_calls=1,
    )
    operator = SemanticOperator(
        operator_id="match",
        kind=SemanticOperatorKind.MATCH,
        input_ids=(),
        input_kinds=(),
        output_kind=SemanticValueKind.BINDING_SET,
    )
    program = SemanticGraphProgram(
        "financial-risk",
        (operator,),
        ("match",),
        holes=(
            SemanticHole(
                "transfer-predicate",
                SemanticHoleKind.PREDICATE,
                "funded",
                candidates=("predicate:paid", "predicate:invested"),
            ),
        ),
    )
    registry = ToolRegistry()
    registry.register(tool)
    config = SelectiveResolutionConfig(use_ontology=False, use_llm=True)
    environment = selective_resolution_environment(registry)

    state = GoalLoop().run(
        build_selective_resolution_goal(program, config),
        SelectiveSemanticResolutionPolicy(
            program,
            "Which companies did Alice fund?",
            config,
        ),
        environment,
    )

    assert state.status is GoalStatus.SUCCEEDED
    assert state.tool_calls == 1
    assert state.output["llm_calls"] == 1
    assert state.output["candidate_sets"][0]["candidate_ids"] == [
        "predicate:invested"
    ]
    memory = environment.memory.records(MemoryScope.EXECUTION)
    assert len(memory) == 1
    assert memory[0].value["metrics"]["external_calls"] == 1.0
    assert memory[0].value["value"]["metadata"]["provider_repair_calls"] == 0
