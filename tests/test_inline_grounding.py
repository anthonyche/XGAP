"""Inline model choices reach the existing guarded semantic pipeline unchanged."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xgap.experiments.bundles import ModelBundle
from xgap.experiments.grailqa_candidate_feedback import TYPED_GROUNDING_ONCE
from xgap.experiments.grailqa_candidate_grounding import SEMANTIC_GROUNDING_POLICY
from xgap.experiments.grailqa_guarded_provider import (
    GuardedSemanticPilotProvider,
    QueryEventJournal,
)
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec
from xgap.experiments.grailqa_preflight_replay import (
    replay_grailqa_preflight,
    PreflightReplaySourceError,
)
from xgap.experiments.grailqa_semantic_pilot import _infer_one
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.live_run import build_openai_compatible_provider
from xgap.llm.inline_grounding import (
    materialize_inline_response,
    validate_response_contract,
)
from xgap.llm.openai_compatible import LiveFailureCategory, ProviderTransportError
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.llm.schemas import PlannerRequest
from xgap.llm.token_budget import ChatTokenBudgetGuard


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "models/qwen3_32b_vllm_cwru_grailqa_inline_v1"
SPEC = (
    ROOT
    / "experiments/specs/grailqa_semantic_preflight_inline_grounding_v1_cwru_qwen3_32b.json"
)
FIXTURES = runpy.run_path(str(ROOT / "tests/test_grailqa_candidate_grounding.py"))


def wire(raw):
    """Encode independently frozen test choices, never repair a model response."""
    result = deepcopy(raw)
    for candidate in result["candidates"]:
        candidate.update(confidence=1.0, rationale=None)

        def initialize(node):
            if isinstance(node, dict):
                if "label" in node and "properties" in node:
                    node["label_slot"] = None
                for child in node.values():
                    initialize(child)
            elif isinstance(node, list):
                for child in node:
                    initialize(child)

        initialize(candidate["pattern_query"])
        for item in candidate.pop("grounding")["slot_realizations"]:
            component = candidate["pattern_query"]
            for segment in item["component_ref"].split("."):
                component = component[segment]
            assert component["label"] == item["ontology_term_id"]
            component["label_slot"] = item["slot_id"]
    return result


def expand(raw):
    return materialize_inline_response(raw, entity_identity_property="type.object.id")


def response(raw):
    return {
        "id": "offline-inline",
        "choices": [{"message": {"content": json.dumps(raw)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
    }


def test_inline_choices_preserve_tree_and_anchors_and_remove_only_annotations():
    original = FIXTURES["case"].__wrapped__().raw
    original["candidates"][0].update(confidence=1.0, rationale=None)
    raw = wire(original)
    before = deepcopy(raw)
    assert expand(raw) == original
    assert raw == before
    # An anchor remains a semantic choice even when it differs from the candidate.
    raw["query_slots"][0]["query_anchor_id"] = "type.other"
    assert expand(raw)["query_slots"] == raw["query_slots"]


@pytest.mark.parametrize("kind", ["seq", "alt", "plus", "star", "optional", "bounded"])
@pytest.mark.parametrize("direction", ["OUT", "IN", "UNDIRECTED"])
def test_existing_topology_direction_and_constraints_survive_materialization(
    kind, direction
):
    raw = wire(FIXTURES["case"].__wrapped__().raw)
    pattern = raw["candidates"][0]["pattern_query"]
    edge = pattern["expr"]
    edge["edge"]["direction"] = direction
    child = deepcopy(edge)
    child["edge"]["label_slot"] = "relation-hop-2"
    if kind in ("seq", "alt"):
        pattern["expr"] = {"kind": kind, "left": edge, "right": child}
        expected = ["expr.left.edge", "expr.right.edge"]
    else:
        pattern["expr"] = {"kind": kind, "child": edge}
        if kind == "bounded":
            pattern["expr"].update(min_repeats=1, max_repeats=3)
        expected = ["expr.child.edge"]
    pattern["restrictor"] = "WALK"
    pattern["condition"] = {
        "kind": "not",
        "condition": {
            "kind": "property_equals",
            "ref": {"kind": "node", "position": "last"},
            "property": "type.object.id",
            "value": "m.visible",
        },
    }
    before = deepcopy(raw)
    output = expand(raw)
    c = output["candidates"][0]
    assert [
        r["component_ref"]
        for r in c["grounding"]["slot_realizations"]
        if r["slot_id"].startswith("relation-hop-")
    ] == expected
    assert c["grounding"]["entity_ids"] == ["m.visible"]
    assert c["pattern_query"]["condition"] == pattern["condition"]
    assert c["pattern_query"]["restrictor"] == "WALK"
    assert raw == before
    # The ordinary typed parser sees precisely the original syntax tree with
    # annotations erased; unavailable lowering does not change its direction.
    parsed = parse_normalized_planner_response(output, PlannerRequest("fixture"))
    serialized = path_pattern_query_to_dict(parsed.candidates[0].pattern_query)
    assert serialized["expr"]["kind"] == kind
    assert serialized["condition"] == pattern["condition"]


def test_property_and_condition_slots_use_exact_keys_without_guessing():
    raw = wire(FIXTURES["case"].__wrapped__().raw)
    pattern = raw["candidates"][0]["pattern_query"]
    pattern["source"]["properties"] = {"p.with.dots": 3, "type.object.id": "m.visible"}
    pattern["source"]["property_slots"] = {"p.with.dots": "p1"}
    pattern["condition"] = {
        "kind": "property_gt",
        "property": "p.score",
        "value": 2,
        "ref": {"kind": "node", "position": "last"},
    }
    pattern["condition_slot"] = "p2"
    slots = expand(raw)["candidates"][0]["grounding"]["slot_realizations"]
    assert {
        r["slot_id"]: r["component_ref"] for r in slots if r["slot_id"].startswith("p")
    } == {
        "p1": "source.properties.p.with.dots",
        "p2": "condition",
    }
    other = {**pattern["condition"], "property": "p.other"}
    pattern["condition"] = {"kind": "and", "conditions": [pattern["condition"], other]}
    assert (
        expand(raw)["candidates"][0]["grounding"]["slot_realizations"][-1][
            "ontology_term_id"
        ]
        is None
    )


@pytest.mark.parametrize(
    "defect", ["unknown-field", "legacy-grounding", "canonical-condition"]
)
def test_invalid_inline_structure_is_explicit_and_never_patched(defect):
    raw = wire(FIXTURES["case"].__wrapped__().raw)
    c = raw["candidates"][0]
    p = c["pattern_query"]
    if defect == "unknown-field":
        p["expr"]["edge"]["native_query"] = "not allowed"
    elif defect == "legacy-grounding":
        c["grounding"] = {"slot_realizations": [], "entity_ids": []}
    elif defect == "canonical-condition":
        p["condition"] = {"kind": "node_not_equals", "left": {}, "right": {}}
    before = deepcopy(raw)
    with pytest.raises(ValueError):
        expand(raw)
    assert raw == before


def provider_case(tmp_path, monkeypatch, wires, *, tokens=(100, 100)):
    fixture = FIXTURES["case"].__wrapped__()
    model = ModelBundle.load(BUNDLE)
    monkeypatch.setenv(model.config.api_key_env, "offline-inline-key")
    monkeypatch.delenv(model.config.model_env, raising=False)
    monkeypatch.delenv(model.config.base_url_env, raising=False)
    pending = list(wires)
    calls = []
    journal = QueryEventJournal(tmp_path / "events.jsonl")

    def send(**kwargs):
        events = [json.loads(line) for line in journal.path.read_text().splitlines()]
        assert events[-1]["event"] == "transport_attempt"
        assert events[-2]["event"] == "token_check"
        calls.append(deepcopy(kwargs["payload"]))
        result = pending.pop(0)
        if isinstance(result, Exception):
            raise result
        return response(result)

    base = build_openai_compatible_provider(
        model,
        SimpleNamespace(post_json=send),
        response_parser=parse_normalized_planner_response,
    )
    counter = SimpleNamespace(
        identity={"synthetic": True}, count_payload_tokens=Mock(side_effect=tokens)
    )
    guard = ChatTokenBudgetGuard(
        counter,
        input_limit=8192,
        output_limit=4096,
        context_limit=12288,
        expected_model=model.config.exact_model_snapshot,
    )
    provider = GuardedSemanticPilotProvider(
        model,
        guard,
        journal,
        "q1",
        base_provider=base,
        candidate_repair_policy=TYPED_GROUNDING_ONCE,
        grounding_policy=SEMANTIC_GROUNDING_POLICY,
    )
    return SimpleNamespace(
        fixture=fixture,
        model=model,
        base=base,
        provider=provider,
        calls=calls,
        journal=journal,
    )


def infer(case):
    retrieval = SimpleNamespace(
        types=("type.source",), relations=("r.connected",), to_dict=lambda: {}
    )
    with case.journal:
        return _infer_one(
            question={"question_id": "q1", "text": "fixture question"},
            catalog=SimpleNamespace(
                retrieve=lambda *a, **kw: retrieval,
                prompt_view=lambda *a, **kw: case.fixture.view,
            ),
            provider=case.provider,
            semantic=case.fixture.semantic,
            retrieval_k=20,
            candidate_cap=3,
            response_parser=parse_normalized_planner_response,
            grounding_policy=SEMANTIC_GROUNDING_POLICY,
        )


def test_real_guarded_inference_consumes_derived_candidates_and_preserves_model_evidence(
    tmp_path, monkeypatch
):
    raw = wire(FIXTURES["case"].__wrapped__().raw)
    case = provider_case(tmp_path, monkeypatch, [raw])
    state = infer(case)
    assert (
        state["candidates"][0]["grounded"]
        and state["candidates"][0]["validation"]["ok"]
    )
    assert len(case.calls) == 1 and state["repair_calls"] == 0
    artifact = state["response_record"]
    assert artifact["structured_response"] == raw  # wire evidence is never relabeled
    (receipt,) = artifact["response_materializations"]
    assert receipt["materialized_response"] == expand(raw)
    assert receipt["source_response_sha256"] == content_hash(raw)
    assert receipt["materialized_response_sha256"] == content_hash(
        state["structured_response"]
    )
    (feedback,) = case.provider.guard_diagnostics["candidate_feedback"]
    assert feedback["source_response_representation"] == "materialized_inline"
    assert feedback["source_response_sha256"] == receipt["materialized_response_sha256"]
    # Existing per-question evaluator accepts the pipeline output while retaining
    # another failed question in its denominator; this is a synthetic metric.
    FIXTURES["_assert_metrics"](
        case.fixture,
        tmp_path,
        state,
        case.fixture.raw["candidates"][0]["pattern_query"],
        0.5,
        1,
        rejected=0,
        policy=SEMANTIC_GROUNDING_POLICY,
    )


@pytest.mark.parametrize(
    "bad_kind",
    ["missing-anchor", "missing-slot", "nonvisible-entity", "malformed-json-shape"],
)
def test_invalid_wire_uses_only_shared_repair_and_checks_the_original_repair_body(
    tmp_path, monkeypatch, bad_kind
):
    good = wire(FIXTURES["case"].__wrapped__().raw)
    bad = deepcopy(good)
    if bad_kind == "missing-anchor":
        bad["query_slots"] = []
    elif bad_kind == "missing-slot":
        bad["candidates"][0]["pattern_query"]["source"].pop("label_slot")
    elif bad_kind == "nonvisible-entity":
        bad["candidates"][0]["pattern_query"]["source"]["properties"][
            "type.object.id"
        ] = "m.invisible"
    else:
        bad = {"invalid": True}
    case = provider_case(tmp_path, monkeypatch, [bad, good])
    state = infer(case)
    assert (
        state["api_call_completed"]
        and state["repair_calls"] == 1
        and len(case.calls) == 2
    )
    assert case.calls[1]["messages"][-2]["content"] == json.dumps(bad)
    assert (
        "grounding"
        not in json.loads(case.calls[1]["messages"][-2]["content"]).get(
            "candidates", [{}]
        )[0]
    )
    assert len(state["response_record"]["raw_responses"]) == 2


def test_repair_refusal_keeps_first_materialization_and_does_not_send_again(
    tmp_path, monkeypatch
):
    bad = wire(FIXTURES["case"].__wrapped__().raw)
    bad["query_slots"] = []
    case = provider_case(tmp_path, monkeypatch, [bad], tokens=(100, 9000))
    state = infer(case)
    assert not state["api_call_completed"] and len(case.calls) == 1
    assert len(state["response_record"]["response_materializations"]) == 1
    assert case.provider.guard_diagnostics["local_guard_denial"]
    assert state["response_record"]["repair_calls"] == 0


def test_transport_timeout_never_triggers_inline_repair(tmp_path, monkeypatch):
    error = ProviderTransportError(LiveFailureCategory.TIMEOUT, "offline fixture")
    case = provider_case(tmp_path, monkeypatch, [error])
    state = infer(case)
    assert not state["api_call_completed"] and len(case.calls) == 1
    assert state["response_record"]["repair_calls"] == 0


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "missing-label",
        "nonexistent-property",
        "invalid-entity",
        "ambiguous-condition",
    ],
)
def test_invalid_semantic_annotations_do_not_discard_a_valid_sibling(
    tmp_path, monkeypatch, defect
):
    raw = wire(FIXTURES["case"].__wrapped__().raw)
    bad = deepcopy(raw["candidates"][0])
    bad["candidate_id"] = "bad-sibling"
    p = bad["pattern_query"]
    if defect == "duplicate":
        p["target"]["label_slot"] = p["source"]["label_slot"]
    elif defect == "missing-label":
        p["source"]["label"] = None
    elif defect == "nonexistent-property":
        p["source"]["property_slots"] = {"missing": "slot-class"}
    elif defect == "invalid-entity":
        p["source"]["properties"]["type.object.id"] = ["m.visible"]
    else:
        p["condition"] = {
            "kind": "and",
            "conditions": [
                {
                    "kind": "property_gt",
                    "ref": {"kind": "node", "position": "last"},
                    "property": key,
                    "value": 2,
                }
                for key in ("p.score", "p.other")
            ],
        }
        p["condition_slot"] = "slot-class"
    raw["candidates"].append(bad)
    before = deepcopy(raw)
    case = provider_case(tmp_path, monkeypatch, [raw])
    state = infer(case)
    assert len(case.calls) == 1 and state["repair_calls"] == 0
    assert state["candidates"][0]["grounded"]
    assert not state["candidates"][1]["grounded"]
    assert state["response_record"]["structured_response"] == before == raw


def test_bundle_selects_wire_contract_and_preserves_scientific_inputs():
    model = ModelBundle.load(BUNDLE)
    spec = GrailQAPreflightSpec.load(SPEC)
    assert spec.data["model_bundle_hash"] == model.bundle_hash
    old_path = (
        ROOT
        / "experiments/specs/grailqa_semantic_preflight_contract_feedback_v1_cwru_qwen3_32b.json"
    )
    old = GrailQAPreflightSpec.load(old_path).data
    allowed = {
        "experiment_id",
        "run_id_prefix",
        "model_bundle_root",
        "model_bundle_hash",
        "freeze_hash",
    }
    assert {
        key for key in set(old) | set(spec.data) if old.get(key) != spec.data.get(key)
    } == allowed
    base = build_openai_compatible_provider(
        model, response_parser=parse_normalized_planner_response
    )
    assert base.config.response_contract == model.config.metadata["response_contract"]
    legacy = ModelBundle.load(ROOT / old["model_bundle_root"])
    assert legacy.bundle_hash == old["model_bundle_hash"]
    assert (
        "response_contract"
        not in build_openai_compatible_provider(legacy).config.safe_dict()
    )
    with pytest.raises(ValueError, match="wire schema"):
        replace(base.config, response_contract=None)
    with pytest.raises(ValueError, match="Unknown"):
        validate_response_contract(
            {"kind": "guessed", "entity_identity_property": "id"}
        )


def test_actual_payload_changes_only_prompt_and_wire_schema():
    fixture = FIXTURES["case"].__wrapped__()
    request = PlannerRequest(
        "fixture",
        max_candidates=3,
        metadata={
            "task_id": "q1",
            "prompt_schema_view": fixture.view.to_dict(),
        },
    )
    old = ModelBundle.load(ROOT / "models/qwen3_32b_vllm_cwru_grailqa_contract_v1")
    new = ModelBundle.load(BUNDLE)
    payloads = [
        build_openai_compatible_provider(m).build_request_payload(request)
        for m in (old, new)
    ]
    assert {k for k in payloads[0] if payloads[0][k] != payloads[1][k]} == {
        "messages",
        "response_format",
    }
    bodies = [json.loads(p["messages"][1]["content"]) for p in payloads]
    assert {k for k in bodies[0] if bodies[0][k] != bodies[1][k]} == {
        "structured_output_schema"
    }
    schema_validator = pytest.importorskip("jsonschema")
    schema_validator.Draft202012Validator.check_schema(new.structured_schema)
    schema_validator.validate(
        {**wire(fixture.raw), "model": "offline-fixture"}, new.structured_schema
    )


@pytest.mark.parametrize("corruption", [None, "derived", "raw", "payload", "missing"])
def test_read_only_replay_recomputes_materialization_from_wire_evidence(
    tmp_path, monkeypatch, corruption
):
    raw = wire(FIXTURES["case"].__wrapped__().raw)
    case = provider_case(tmp_path, monkeypatch, [raw])
    state = infer(case)
    evidence = deepcopy(state["response_record"])
    if corruption == "derived":
        receipt = evidence["response_materializations"][-1]
        receipt["materialized_response"]["candidates"][0]["pattern_query"]["expr"][
            "edge"
        ]["direction"] = "IN"
        receipt["materialized_response_sha256"] = content_hash(
            receipt["materialized_response"]
        )
    elif corruption == "raw":
        evidence["structured_response"]["query_slots"][0][
            "query_anchor_id"
        ] = "type.other"
    elif corruption == "payload":
        evidence["response_materializations"][-1]["request_payload_sha256"] = "x" * 64
    elif corruption == "missing":
        evidence.pop("response_materializations")
    (tmp_path / "llm_requests.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in state["request_records"])
    )
    (tmp_path / "llm_responses.jsonl").write_text(json.dumps(evidence) + "\n")
    if corruption:
        with pytest.raises(PreflightReplaySourceError):
            replay_grailqa_preflight(run_root=tmp_path)
    else:
        replay = replay_grailqa_preflight(run_root=tmp_path)
        assert replay["queries"][0]["materialization_recomputed"]
        assert replay["queries"][0]["stage"] == "grounding_passed"
        assert replay["paper_result"] is False


def test_validator_mutation_is_internal_failure_without_model_repair(
    tmp_path, monkeypatch
):
    raw = wire(FIXTURES["case"].__wrapped__().raw)
    case = provider_case(tmp_path, monkeypatch, [raw])
    request = PlannerRequest(
        "fixture",
        max_candidates=3,
        metadata={
            "task_id": "q1",
            "prompt_schema_view": case.fixture.view.to_dict(),
        },
    )

    def mutate(body, _request):
        body["model"] = "changed-after-materialization"

    base = replace(
        case.base,
        transport=SimpleNamespace(post_json=Mock(return_value=response(raw))),
        response_validator=mutate,
    )
    with pytest.raises(RuntimeError, match="mutated"):
        base.generate_candidates(request)
    assert base.transport.post_json.call_count == 1
