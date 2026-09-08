from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
from typing import Any, Mapping

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.openai_compatible import LiveFailureCategory, LiveProviderError
from xgap.llm.parser import parse_planner_response


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e2_cwru_vllm.py"))


class RecordedTransport:
    def __init__(self, envelope: Mapping[str, Any]) -> None:
        self.envelope = dict(envelope)
        self.calls: list[dict[str, Any]] = []

    def post_json(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(copy.deepcopy(kwargs))
        return self.envelope


def _setup(monkeypatch, *, normalized: bool = True, defect: str | None = None):
    model = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_m13e2")
    monkeypatch.setenv(str(model.config.api_key_env), "parser-contract-fixture")
    envelope = FIXTURES["_provider_response"]()
    message = envelope["choices"][0]["message"]
    structured = json.loads(message["content"])
    pattern = structured["candidates"][0]["pattern_query"]
    del pattern["selector"]
    del pattern["restrictor"]
    if defect == "canonical_condition":
        pattern["condition"] = {
            "kind": "node_not_equals",
            "left": {"kind": "node", "position": 1},
            "right": {"kind": "node", "position": 2},
        }
    elif defect == "unknown_restrictor":
        pattern["restrictor"] = "NOT_A_RESTRICTOR"
    message["content"] = json.dumps(structured)
    transport = RecordedTransport(envelope)
    kwargs = {"response_parser": parse_normalized_planner_response} if normalized else {}
    provider = build_openai_compatible_provider(model, transport, **kwargs)
    return provider, transport, FIXTURES["_planner_request"](), structured


def test_normalized_parser_accepts_omitted_defaults_in_one_call_without_mutation(monkeypatch) -> None:
    provider, transport, request, structured = _setup(monkeypatch)
    before = copy.deepcopy(transport.envelope)

    result = provider.generate_candidates(request)

    assert provider.response_parser is parse_normalized_planner_response
    assert result == structured
    assert transport.envelope == before
    assert len(transport.calls) == 1
    artifact = provider.last_invocation
    assert artifact is not None
    assert artifact.generation_calls == 1
    assert artifact.repair_calls == 0
    assert artifact.validation_status == "schema_valid"
    assert artifact.raw_responses == (before,)
    assert artifact.structured_response == structured
    assert "selector" not in artifact.structured_response["candidates"][0]["pattern_query"]
    assert "restrictor" not in artifact.structured_response["candidates"][0]["pattern_query"]
    parsed = parse_normalized_planner_response(result, request)
    assert parsed.candidates[0].pattern_query.selector.kind.name == "ALL"
    assert parsed.candidates[0].pattern_query.restrictor.name == "SIMPLE"


def test_default_parser_retains_legacy_rejection_and_repair_bound(monkeypatch) -> None:
    provider, transport, request, _ = _setup(monkeypatch, normalized=False)

    with pytest.raises(LiveProviderError, match="selector must be a mapping") as caught:
        provider.generate_candidates(request)

    assert provider.response_parser is parse_planner_response
    assert len(transport.calls) == 2
    assert caught.value.category is LiveFailureCategory.REPAIR_FAILED
    assert caught.value.artifact.generation_calls == 1
    assert caught.value.artifact.repair_calls == provider.config.max_repair_calls == 1


@pytest.mark.parametrize("defect", ["canonical_condition", "unknown_restrictor"])
def test_normalized_parser_keeps_semantic_errors_inside_existing_repair_budget(monkeypatch, defect: str) -> None:
    provider, transport, request, _ = _setup(monkeypatch, defect=defect)
    before = copy.deepcopy(transport.envelope)

    with pytest.raises(LiveProviderError) as caught:
        provider.generate_candidates(request)

    assert len(transport.calls) == 2
    assert caught.value.category is LiveFailureCategory.REPAIR_FAILED
    assert caught.value.artifact.generation_calls == 1
    assert caught.value.artifact.repair_calls == 1
    assert caught.value.artifact.validation_status == "failed"
    assert caught.value.artifact.structured_response is None
    assert transport.envelope == before
    expected = "must not be generated" if defect == "canonical_condition" else "Unsupported restrictor"
    assert expected in caught.value.artifact.error_message


@pytest.mark.parametrize("reject", [False, True])
def test_existing_response_validator_hook_runs_after_injected_parser(monkeypatch, reject: bool) -> None:
    provider, transport, request, structured = _setup(monkeypatch)
    observed = []

    def validate(raw, actual_request):
        observed.append(copy.deepcopy(raw))
        assert actual_request is request
        assert raw == structured
        if reject:
            raise ValueError("Existing validator hook rejected response")

    provider.response_validator = validate
    if reject:
        with pytest.raises(LiveProviderError, match="Existing validator hook rejected response"):
            provider.generate_candidates(request)
        assert len(transport.calls) == len(observed) == 2
        assert provider.last_invocation.repair_calls == 1
    else:
        assert provider.generate_candidates(request) == structured
        assert len(transport.calls) == len(observed) == 1
        assert provider.last_invocation.repair_calls == 0
