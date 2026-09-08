from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import xgap.experiments.grailqa_preflight as preflight
import xgap.experiments.grailqa_semantic_paper_run as paper_run
import xgap.experiments.grailqa_semantic_pilot as pilot
from xgap.experiments.bundles import ModelBundle
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.parser import parse_planner_response


ROOT = Path(__file__).resolve().parents[1]
CWRU_FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e2_cwru_vllm.py"))


class ProviderConstructionCaptured(Exception):
    """Stop an actual entrypoint immediately before it could make a live call."""


@pytest.mark.parametrize("normalized", [False, True], ids=["legacy-default", "normalized"])
def test_live_wrapper_forwards_parser_to_real_provider_with_offline_transport(
    monkeypatch: pytest.MonkeyPatch, normalized: bool,
) -> None:
    model = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_m13e2")
    monkeypatch.setenv(str(model.config.api_key_env), "offline-parser-wiring-fixture")
    envelope = CWRU_FIXTURES["_provider_response"]()
    structured = json.loads(envelope["choices"][0]["message"]["content"])
    pattern = structured["candidates"][0]["pattern_query"]
    del pattern["selector"]
    del pattern["restrictor"]
    envelope["choices"][0]["message"]["content"] = json.dumps(structured)
    before = copy.deepcopy(envelope)
    transport = CWRU_FIXTURES["FakeTransport"](envelope)
    constructed = []

    def build_with_offline_transport(actual_model, *, response_parser=parse_planner_response):
        assert actual_model is model
        provider = build_openai_compatible_provider(
            actual_model, transport, response_parser=response_parser
        )
        constructed.append(provider)
        return provider

    monkeypatch.setattr(pilot, "build_openai_compatible_provider", build_with_offline_transport)
    kwargs = {"response_parser": parse_normalized_planner_response} if normalized else {}
    wrapper = pilot.LiveSemanticPilotProvider(model, **kwargs)
    request = CWRU_FIXTURES["_planner_request"]()

    # The live wrapper forwards the request's bounded prompt view from metadata;
    # its separate prompt_view argument is used only by the fake pilot provider.
    result = wrapper.generate(request, None)  # type: ignore[arg-type]

    expected_parser = parse_normalized_planner_response if normalized else parse_planner_response
    assert wrapper.response_parser is expected_parser
    assert len(constructed) == 1
    assert constructed[0].response_parser is expected_parser
    assert envelope == before
    assert result.response_record["generation_calls"] == 1
    if normalized:
        assert result.api_call_completed is True
        assert result.structured_response == structured
        assert result.error is None
        assert result.repair_calls == 0
        assert len(transport.calls) == len(result.request_records) == 1
        assert result.response_record["validation_status"] == "schema_valid"
    else:
        assert result.api_call_completed is False
        assert result.structured_response is None
        assert "selector must be a mapping" in result.error
        assert result.repair_calls == model.config.max_repair_calls == 1
        assert len(transport.calls) == len(result.request_records) == 2
        assert result.response_record["validation_status"] == "failed"


def test_preflight_entrypoint_selects_normalized_provider_parser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    model = object()
    spec = SimpleNamespace(data={"model_bundle_root": "offline-model"})
    readiness = {"ready": True, "catalog_root": str(tmp_path / "catalog")}
    check_readiness = Mock(return_value=readiness)
    construct_provider = Mock(side_effect=ProviderConstructionCaptured)
    monkeypatch.setattr(preflight, "GrailQAPreflightSpec", SimpleNamespace(load=Mock(return_value=spec)))
    monkeypatch.setattr(preflight, "preflight_readiness", check_readiness)
    monkeypatch.setattr(preflight, "GrailQAInferenceCatalogV2", SimpleNamespace(load=Mock(return_value=object())))
    monkeypatch.setattr(preflight, "ModelBundle", SimpleNamespace(load=Mock(return_value=model)))
    monkeypatch.setattr(preflight, "LiveSemanticPilotProvider", construct_provider)
    read_questions = Mock(side_effect=AssertionError("Inference must not start in this wiring test"))
    monkeypatch.setattr(preflight, "_read_jsonl", read_questions)

    with pytest.raises(ProviderConstructionCaptured):
        preflight.run_preflight(
            spec_path=tmp_path / "preflight.json",
            repo_root=tmp_path,
            output_root=tmp_path / "preflight-output",
        )

    check_readiness.assert_called_once_with(spec, tmp_path.resolve(), require_credentials=True)
    construct_provider.assert_called_once_with(
        model, response_parser=parse_normalized_planner_response
    )
    read_questions.assert_not_called()


def test_paper_run_entrypoint_selects_normalized_provider_parser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    model = object()
    request = {"run_id": "offline-parser-wiring"}
    admission, authority = {}, {}
    controls = {"request.json": request, "admission.json": admission, "authority.json": authority}
    validate_inputs = Mock(return_value=(request, admission, authority, ("q0",), object(), model))
    construct_provider = Mock(side_effect=ProviderConstructionCaptured)
    monkeypatch.setattr(paper_run, "_regular_directory", lambda path, **kwargs: Path(path))
    monkeypatch.setattr(paper_run, "_regular_file", lambda path, **kwargs: Path(path))
    monkeypatch.setattr(paper_run, "_load_json", lambda path, **kwargs: controls[Path(path).name])
    monkeypatch.setattr(paper_run, "_validate_run_inputs_without_opening_gold", validate_inputs)
    read_questions = Mock(return_value=[{"question_id": "q0", "question": "Offline fixture"}])
    monkeypatch.setattr(paper_run, "_load_jsonl", read_questions)
    monkeypatch.setattr(paper_run, "LiveSemanticPilotProvider", construct_provider)
    execute_run = Mock(side_effect=AssertionError("Inference must not start in this wiring test"))
    monkeypatch.setattr(paper_run, "execute_grailqa_semantic_paper_run", execute_run)

    with pytest.raises(ProviderConstructionCaptured):
        paper_run.run_grailqa_semantic_paper(
            request_path=tmp_path / "request.json",
            admission_path=tmp_path / "admission.json",
            authority_path=tmp_path / "authority.json",
            protocol_path=tmp_path / "protocol.json",
            author_selection_path=tmp_path / "selection.json",
            repo_root=tmp_path,
            catalog_root=tmp_path / "catalog",
            reachability_summary_path=tmp_path / "reachability-summary.json",
            reachability_rows_path=tmp_path / "reachability-rows.jsonl",
            output_root=tmp_path / request["run_id"],
        )

    validate_inputs.assert_called_once()
    construct_provider.assert_called_once_with(
        model, response_parser=parse_normalized_planner_response
    )
    read_questions.assert_called_once_with(
        tmp_path / "datasets/grailqa_pilot_v1/inference_questions.jsonl",
        name="inference questions",
    )
    execute_run.assert_not_called()
