"""Exercise unchanged inference, normalization, grounding, and semantic scoring."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_candidate_grounding import LEGACY_GROUNDING_POLICY, STRICT_GROUNDING_POLICY, SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_guarded_provider import GuardedSemanticPilotProvider, QueryEventJournal
from xgap.experiments.grailqa_semantic_pilot import _infer_one
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.experiments.runtime_alignment import PromptQuerySlot, RetrievalLimits
from xgap.experiments.semantic import DirectionalOntologyDeviation, OntologyGraph, SemanticDeviationConfig
from xgap.llm.token_budget import ChatTokenBudgetGuard


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e3b4_relation_endpoint_grounding.py"))
CWRU_FIXTURES = runpy.run_path(str(ROOT / "tests/test_m13e2_cwru_vllm.py"))


@pytest.mark.parametrize("grounding_policy", [LEGACY_GROUNDING_POLICY, STRICT_GROUNDING_POLICY, SEMANTIC_GROUNDING_POLICY])
@pytest.mark.parametrize("scenario", ["grounded", "missing-optional-anchor", "token-refusal", "bad-sibling"])
def test_actual_inference_preserves_grounding_and_local_refusal_boundaries(
    monkeypatch, tmp_path, scenario, grounding_policy,
) -> None:
    ontology = OntologyGraph(
        ontology_id="fixture", version="v1", classes=("type.source", "type.target"),
        relations=("r.connected",), properties=(), parents={}, max_relaxation_hops=2,
        domain_range={"r.connected": {"domain": "type.source", "range": "type.target"}},
    )
    view = ENDPOINT_FIXTURES["_prompt_view"]()
    view = replace(
        view, ontology_hash=ontology.ontology_hash,
        query_slots=(*view.query_slots, PromptQuerySlot(
            "relation-hop-2", "optional hop", "relation", ("r.connected",),
            ("synthetic-fixture",), required_for_candidate=False,
        )),
        limits=RetrievalLimits(3, 1, 1, 2),
    )
    raw = ENDPOINT_FIXTURES["_grounded_raw"](target_type="type.target")
    raw["model"] = "Qwen/Qwen3-32B"
    candidate = raw["candidates"][0]
    candidate.update(confidence=1.0, rationale=None)
    del candidate["pattern_query"]["selector"]
    del candidate["pattern_query"]["restrictor"]
    if scenario != "missing-optional-anchor":
        raw["query_slots"].append({"slot_id": "relation-hop-2", "query_anchor_id": "r.connected"})
    if scenario == "bad-sibling":
        bad = copy.deepcopy(candidate)
        bad["candidate_id"] = "bad-sibling"
        bad["grounding"]["slot_realizations"][0]["component_ref"] = "s.label"
        raw["candidates"].append(bad)
    envelope = CWRU_FIXTURES["_provider_response"]()
    envelope["choices"][0]["message"]["content"] = json.dumps(raw)
    before = copy.deepcopy(envelope)
    transport = SimpleNamespace(post_json=Mock(return_value=envelope))
    retrieval_data = {"question_id": "q1", "types": ["type.source"], "relations": ["r.connected"]}
    retrieval = SimpleNamespace(
        types=("type.source",), relations=("r.connected",),
        to_dict=lambda: copy.deepcopy(retrieval_data),
    )
    catalog = SimpleNamespace(
        ontology=ontology, retrieve=Mock(return_value=retrieval), prompt_view=Mock(return_value=view),
    )
    semantic = DirectionalOntologyDeviation(ontology, SemanticDeviationConfig(max_relaxation_hops=2))
    model = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_grailqa_contract_v1")
    monkeypatch.setenv(str(model.config.api_key_env), "offline-inference-fixture")
    monkeypatch.delenv(str(model.config.model_env), raising=False)
    monkeypatch.delenv(str(model.config.base_url_env), raising=False)
    base = build_openai_compatible_provider(
        model, transport, response_parser=parse_normalized_planner_response,
    )
    counter = SimpleNamespace(
        identity={"schema_version": "synthetic-counter-v1", "remote_serving_parity_verified": False},
        count_payload_tokens=Mock(return_value=8193 if scenario == "token-refusal" else 1000),
    )
    guard = ChatTokenBudgetGuard(
        counter, input_limit=8192, output_limit=4096, context_limit=12288,
        expected_model=base.config.model,
    )
    journal_path = tmp_path / "query-events.jsonl"
    with QueryEventJournal(journal_path) as journal:
        provider = GuardedSemanticPilotProvider(model, guard, journal, "q1", base_provider=base)
        state = _infer_one(
            question={"question_id": "q1", "text": "Find the connected target."},
            catalog=catalog, provider=provider, semantic=semantic,
            retrieval_k=20, candidate_cap=3, prompt_candidates_per_slot=4,
            response_parser=parse_normalized_planner_response,
            grounding_policy=grounding_policy,
        )

    catalog.retrieve.assert_called_once_with("q1", "Find the connected target.", top_k=20)
    catalog.prompt_view.assert_called_once_with(retrieval, candidates_per_slot=4, max_entities=4)
    assert envelope == before
    assert state["repair_calls"] == 0
    check, = provider.token_check_records
    events = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert next(event for event in events if event["event"] == "token_check")["check"] == check
    assert check["requested_output_tokens"] == 4096
    checked_payload = counter.count_payload_tokens.call_args.args[0]
    assert check["payload_sha256"] == content_hash(checked_payload)
    assert provider.last_invocation is not None
    if scenario == "token-refusal":
        transport.post_json.assert_not_called()
        assert state["failure"]["schema_version"] == "m13d-first-failure-v1"
        assert state["failure"]["category"] == "malformed_output"
        assert state["api_call_completed"] is False
        assert state["request_records"] == []
        assert state["response_record"]["generation_calls"] == 0
        assert state["response_record"]["repair_calls"] == 0
        assert check["passed"] is False and check["reason"] == "input_budget_exceeded"
        assert provider.guard_diagnostics["local_guard_denial"] is True
        assert provider.guard_diagnostics["denied_call_kind"] == "generation"
        assert not any(event["event"] == "transport_attempt" for event in events)
    else:
        transport.post_json.assert_called_once()
        assert transport.post_json.call_args.kwargs["payload"] == checked_payload
        assert state["api_call_completed"] is True
        assert state["response_record"]["generation_calls"] == 1
        assert len(state["request_records"]) == 1
        assert check["passed"] is True
        assert provider.guard_diagnostics["local_guard_denial"] is False
        if scenario == "grounded":
            assert state["failure"] is None
            assert len(state["candidates"]) == len(state["semantic_scores"]) == 1
            assert state["candidates"][0]["grounded"] is True
            assert state["candidates"][0]["semantic_admissible"] is True
            assert state["candidates"][0]["semantic_deviation"] == 0.0
            assert state["candidates"][0]["pattern_query"]["selector"]["kind"] == "ALL"
            assert len(state["structured_response"]["query_slots"]) == 3
            assert len(state["structured_response"]["candidates"][0]["grounding"]["slot_realizations"]) == 2
        elif scenario == "bad-sibling":
            if grounding_policy != LEGACY_GROUNDING_POLICY:
                assert state["failure"] is None
                assert len(state["candidates"]) == 2
                assert len(state["semantic_scores"]) == 1
                assert state["candidates"][0]["grounded"] is True
                assert state["candidates"][1]["grounding_failure"]["code"] == "slot_grounding"
            else:
                assert state["candidates"] == []
                assert state["failure"]["category"] == "relation_grounding_failure"
        else:
            assert state["candidates"] == []
            assert state["failure"]["category"] == "relation_grounding_failure"
            assert "Every prompt query slot must have exactly one selected query anchor" in state["failure"]["message"]
