"""Synthetic correctness counterexamples; no model or benchmark quality claim."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from xgap.experiments.grailqa_candidate_grounding import (
    LEGACY_GROUNDING_POLICY, STRICT_GROUNDING_POLICY, SEMANTIC_GROUNDING_POLICY, ground_canonical_candidates,
)
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec, _evaluate_preflight
from xgap.experiments.grailqa_semantic_pilot import GenerationResult, _infer_one
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.runtime_alignment import (
    PromptQuerySlot, RetrievedOntologyTerm, RuntimeAlignmentError, parse_grounded_planner_response,
)
from xgap.experiments.semantic import DirectionalOntologyDeviation, OntologyGraph, SemanticDeviationConfig
from xgap.llm.schemas import PlannerRequest


FIXTURES = runpy.run_path(str(Path(__file__).with_name("test_m13e3b4_relation_endpoint_grounding.py")))


@pytest.fixture
def case():
    ontology = OntologyGraph(
        ontology_id="fixture", version="v1", classes=("type.source", "type.target", "type.other"),
        relations=("r.connected",), properties=("p.score", "p.other"),
        parents={"type.source": ("type.other",)}, max_relaxation_hops=2,
        domain_range={"r.connected": {"domain": "type.source", "range": "type.target"}},
    )
    view = FIXTURES["_prompt_view"]()
    view = replace(
        view, ontology_hash=ontology.ontology_hash,
        terms=(*view.terms, *(
            RetrievedOntologyTerm(term, kind, term, (), 1.0, ("fixture",))
            for term, kind in (("type.other", "class"), ("p.score", "property"), ("p.other", "property"))
        )),
        entities=({"entity_id": "m.visible"}, {"entity_id": "m.other"}),
    )
    return SimpleNamespace(
        view=view, raw=FIXTURES["_grounded_raw"](target_type="type.target"),
        semantic=DirectionalOntologyDeviation(ontology, SemanticDeviationConfig(max_relaxation_hops=2)),
    )


def _batch(case):
    parsed = parse_normalized_planner_response(case.raw, PlannerRequest("fixture question"))
    return ground_canonical_candidates(case.raw, parsed, case.view)


def _infer(case, policy=STRICT_GROUNDING_POLICY):
    retrieval = SimpleNamespace(types=("type.source",), relations=("r.connected",), to_dict=lambda: {})
    provider = SimpleNamespace(provider_id="fixture", generate=Mock(return_value=GenerationResult(
        structured_response=case.raw, request_records=({"request_id": "once"},),
        response_record={"external_calls": 1}, latency_seconds=0.1, repair_calls=0,
        api_call_completed=True,
    )))
    state = _infer_one(
        question={"question_id": "q1", "text": "fixture question"},
        catalog=SimpleNamespace(retrieve=Mock(return_value=retrieval), prompt_view=Mock(return_value=case.view)),
        provider=provider, semantic=case.semantic, retrieval_k=20, candidate_cap=3,
        response_parser=parse_normalized_planner_response, grounding_policy=policy,
    )
    provider.generate.assert_called_once()
    assert state["request_records"] == [{"request_id": "once"}]
    assert state["response_record"] == {"external_calls": 1}
    assert state["repair_calls"] == 0
    return state


@pytest.mark.parametrize("actual", [None, "type.other"])
def test_rejects_falsely_declared_class_but_preserves_legacy_replay(case, actual):
    case.raw["candidates"][0]["pattern_query"]["source"]["label"] = actual
    before = copy.deepcopy(case.raw)
    legacy = _infer(case, LEGACY_GROUNDING_POLICY)
    assert legacy["candidates"][0]["semantic_admissible"] is True  # Reproduced defect.
    assert legacy["candidates"][0]["semantic_deviation"] == 0.0
    strict = _infer(case)
    row, = strict["candidates"]
    assert row["grounding_failure"]["code"] == "component_term_mismatch"
    assert not row["grounded"] and not row["semantic_admissible"]
    assert strict["semantic_scores"] == []
    assert case.raw == before


def test_real_ontology_relaxation_is_not_forced_back_to_query_anchor(case):
    raw_candidate = case.raw["candidates"][0]
    raw_candidate["pattern_query"]["source"]["label"] = "type.other"
    raw_candidate["grounding"]["slot_realizations"][0]["ontology_term_id"] = "type.other"
    state = _infer(case)
    row, = state["candidates"]
    assert row["grounded"] and row["semantic_admissible"]
    assert row["semantic_deviation"] > 0.0
    assert case.raw["query_slots"][0]["query_anchor_id"] == "type.source"


@pytest.mark.parametrize("bad_first", [True, False])
def test_one_bad_grounding_does_not_drop_good_sibling_or_reorder(case, bad_first):
    good = case.raw["candidates"][0]
    bad = copy.deepcopy(good)
    bad["candidate_id"] = "bad"
    bad["grounding"]["slot_realizations"][0]["component_ref"] = "s.label"
    case.raw["candidates"] = [bad, good] if bad_first else [good, bad]
    legacy = _infer(case, LEGACY_GROUNDING_POLICY)
    assert legacy["candidates"] == []
    state = _infer(case)
    assert state["failure"] is None
    assert [row["candidate_id"] for row in state["candidates"]] == [row["candidate_id"] for row in case.raw["candidates"]]
    assert [row["candidate_index"] for row in state["candidates"]] == [1, 2]
    assert [row["candidate_id"] for row in state["semantic_scores"]] == ["candidate-1"]
    rejected, = [row for row in state["candidates"] if not row["grounded"]]
    assert rejected["grounding_failure"]["code"] == "slot_grounding"


@pytest.mark.parametrize("problem", ["missing-anchor", "duplicate-anchor", "duplicate-id", "wrong-anchor", "missing-optional-anchor"])
def test_shared_contract_error_still_fails_the_whole_query(case, problem):
    if problem == "missing-anchor":
        case.raw["query_slots"].pop()
    elif problem == "duplicate-anchor":
        case.raw["query_slots"].append(copy.deepcopy(case.raw["query_slots"][0]))
    elif problem == "duplicate-id":
        case.raw["candidates"].append(copy.deepcopy(case.raw["candidates"][0]))
    elif problem == "wrong-anchor":
        case.raw["query_slots"][0]["query_anchor_id"] = "type.invented"
    else:
        case.view = replace(case.view, query_slots=(*case.view.query_slots, PromptQuerySlot(
            "relation-hop-2", "optional", "relation", ("r.connected",), ("fixture",), False,
        )))
    state = _infer(case)
    assert state["candidates"] == state["semantic_scores"] == []
    assert state["failure"] is not None
    assert state["candidate_grounding_policy"] == STRICT_GROUNDING_POLICY


@pytest.mark.parametrize("problem", ["reordered", "extra", "cap"])
def test_batch_rejects_ambiguous_raw_parsed_identity(case, problem):
    second = copy.deepcopy(case.raw["candidates"][0])
    second["candidate_id"] = "second"
    case.raw["candidates"].append(second)
    parsed = parse_normalized_planner_response(case.raw, PlannerRequest("fixture question"))
    if problem == "reordered":
        case.raw["candidates"].reverse()
    elif problem == "extra":
        case.raw["candidates"].append(second)
    else:
        parsed = replace(parsed, request=PlannerRequest("fixture question", max_candidates=1))
    with pytest.raises(RuntimeAlignmentError, match="unique ordered"):
        ground_canonical_candidates(case.raw, parsed, case.view)


@pytest.mark.parametrize("wrapper", ["direct", "and", "or", "not", "nested"])
@pytest.mark.parametrize("value,declared", [("m.invisible", []), ("m.visible", []), (123, []), (["m.visible"], [])])
def test_entity_conditions_cannot_bypass_visibility_or_declaration(case, wrapper, value, declared):
    condition = {"kind": "property_equals", "ref": {"kind": "node", "position": 1},
                 "property": "type.object.id", "value": value}
    if wrapper in ("and", "or"):
        condition = {"kind": wrapper, "conditions": [condition, {"kind": "length_equals", "value": 1}]}
    elif wrapper == "not":
        condition = {"kind": "not", "condition": condition}
    elif wrapper == "nested":
        condition = {"kind": "and", "conditions": [
            {"kind": "length_equals", "value": 1},
            {"kind": "not", "condition": {"kind": "or", "conditions": [condition, copy.deepcopy(condition)]}},
        ]}
    candidate = case.raw["candidates"][0]
    candidate["pattern_query"]["condition"] = condition
    candidate["grounding"]["entity_ids"] = declared
    result = _batch(case)
    assert result.grounded.grounded_candidates == ()
    assert result.failures["candidate-1"].category == "entity_grounding_failure"


@pytest.mark.parametrize("location", ["source", "target", "condition", "edge"])
def test_actual_visible_declared_identity_is_preserved(case, location):
    candidate = case.raw["candidates"][0]
    pattern = candidate["pattern_query"]
    if location == "condition":
        pattern["condition"] = {"kind": "property_equals", "ref": {"kind": "node", "position": "last"},
                                "property": "type.object.id", "value": "m.visible"}
    else:
        item = pattern["expr"]["edge"] if location == "edge" else pattern[location]
        item["properties"]["type.object.id"] = "m.visible"
    candidate["grounding"]["entity_ids"] = ["m.visible"]
    before = copy.deepcopy(case.raw)
    result = _batch(case)
    assert not result.failures
    assert result.grounded.candidate("candidate-1").entity_ids == ("m.visible",)
    assert case.raw == before


@pytest.mark.parametrize("wrong", [False, True])
def test_property_slot_binds_actual_key_not_merely_same_kind(case, wrong):
    candidate = case.raw["candidates"][0]
    candidate["pattern_query"]["source"]["properties"]["p.score"] = 4
    case.view = replace(case.view, query_slots=(*case.view.query_slots, PromptQuerySlot(
        "score", "score", "property", ("p.score",), ("fixture",),
    )))
    case.raw["query_slots"].append({"slot_id": "score", "query_anchor_id": "p.score"})
    candidate["grounding"]["slot_realizations"].append({
        "slot_id": "score", "ontology_term_id": "p.other" if wrong else "p.score",
        "component_ref": "source.properties.p.score",
    })
    assert bool(_batch(case).failures) is wrong


def test_exact_role_derived_type_remains_valid(case):
    batch = _batch(case)
    assert not batch.failures
    evidence, = batch.grounded.candidate("candidate-1").endpoint_type_evidence
    assert (evidence.role.value, evidence.type_id) == ("target", "type.target")
    case.raw["candidates"][0]["pattern_query"]["target"]["label"] = "type.unseen"
    assert _batch(case).failures["candidate-1"].code == "slot_grounding"


def test_unknown_policy_fails_before_any_retrieval_or_provider():
    catalog, provider = Mock(), Mock()
    with pytest.raises(ValueError, match="grounding policy"):
        _infer_one(question={}, catalog=catalog, provider=provider, semantic=Mock(),
                   retrieval_k=20, candidate_cap=3, grounding_policy="typo")
    assert catalog.mock_calls == provider.mock_calls == []


def test_capability_limits_are_not_disguised_as_grounding_success(case):
    # This repair does not pretend that the M5 lowerer supports IN. It is an
    # independent capability gap, retained for the next admission milestone.
    candidate = case.raw["candidates"][0]
    candidate["pattern_query"]["expr"]["edge"]["direction"] = "IN"
    candidate["pattern_query"]["target"]["label"] = "type.source"
    state = _infer(case)
    assert state["candidates"][0]["validation"]["stage"] == "lowering"
    assert state["semantic_scores"] == []


def test_rejected_exact_reference_cannot_inflate_recall_or_structured_rate(case, tmp_path):
    bad = case.raw["candidates"][0]
    bad["grounding"]["slot_realizations"][0]["component_ref"] = "s.label"
    state = _infer(case)
    _assert_metrics(case, tmp_path, state, bad["pattern_query"], 0.0, 0)


def test_good_sibling_counts_once_and_all_question_denominators_remain(case, tmp_path):
    good = case.raw["candidates"][0]
    bad = copy.deepcopy(good)
    bad["candidate_id"] = "bad"
    bad["grounding"]["slot_realizations"][0]["component_ref"] = "s.label"
    case.raw["candidates"].append(bad)
    state = _infer(case)
    _assert_metrics(case, tmp_path, state, good["pattern_query"], 0.5, 1)


def _assert_metrics(case, tmp_path, state, reference, expected, accepted, *, rejected=1, unassessed=0,
                    policy=STRICT_GROUNDING_POLICY):
    # q2 contributes a failure, never silently disappears from the denominator.
    other = {**copy.deepcopy(state), "question": {"question_id": "q2"}, "candidates": [],
             "semantic_scores": [], "failure": {"category": "malformed_output"}, "api_call_completed": False,
             "returned_candidate_count": 0, "structured_response": None}
    refs = [{"question_id": qid, "pattern_query": reference} for qid in ("q1", "q2")]
    (tmp_path / "reference_interpretations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in refs))
    reachability = tmp_path / "reachability.jsonl"
    reachability.write_text("".join(json.dumps({
        "question_id": qid, "deployed_prompt": {"joint": {"reachable": True}},
    }) + "\n" for qid in ("q1", "q2")))
    spec = GrailQAPreflightSpec(tmp_path / "spec.json", {
        "pilot_root": ".", "candidate_grounding_policy": policy, "epsilon_values": [0, 1],
    })
    result = _evaluate_preflight([state, other], spec, tmp_path, {
        "reachability_rows_path": str(reachability),
    }, grounding_policy=policy)
    metrics = result["metrics"]
    assert metrics["query_count"] == 2
    assert metrics["candidate_recall"] == metrics["structured_valid_rate"] == expected
    assert metrics["validated_grounded_candidate_count"] == len(result["candidates"]) == accepted
    assert metrics["rejected_candidate_count"] == len(result["rejected_candidates"]) == rejected
    assert metrics["jointly_reachable_subset"]["candidate_recall"] == expected
    assert metrics["jointly_reachable_subset"]["question_count"] == 2
    assert metrics["generated_candidate_count"] == accepted + rejected + unassessed
    assert metrics["unassessed_candidate_count"] == unassessed
    return result


def test_semantic_policy_keeps_in_candidate_without_claiming_execution(case, tmp_path):
    raw = case.raw["candidates"][0]
    raw["pattern_query"]["expr"]["edge"]["direction"] = "IN"
    raw["pattern_query"]["target"]["label"] = "type.source"
    before = copy.deepcopy(case.raw)
    state = _infer(case, SEMANTIC_GROUNDING_POLICY)
    row, = state["candidates"]
    assert row["validation"]["ok"] and row["grounded"] and row["semantic_admissible"]
    assert row["validation"]["formatted_plan"] is None
    assert row["logical_lowering"]["status"] == "unavailable"
    assert not row["logical_lowering"]["available"]
    assert not row["logical_lowering"]["backend_execution_verified"]
    result = _assert_metrics(case, tmp_path, state, raw["pattern_query"], 0.5, 1,
                             rejected=0, policy=SEMANTIC_GROUNDING_POLICY)
    assert result["metrics"]["logical_lowering_status_counts"] == {
        "available": 0, "unavailable": 1, "error": 0, "not_assessed": 0,
    }
    assert result["metrics"]["logical_lowering_available_query_rate"] == 0
    assert len(result["candidate_capabilities"]) == 1
    assert case.raw == before


def test_semantic_policy_checks_conditions_before_scoring_and_isolates_siblings(case, tmp_path):
    good = case.raw["candidates"][0]
    bad = copy.deepcopy(good)
    bad["candidate_id"] = "out-of-range"
    bad["pattern_query"]["condition"] = {
        "kind": "property_equals", "ref": {"kind": "node", "position": 3}, "property": "p.score", "value": 4,
    }
    case.raw["candidates"].append(bad)
    state = _infer(case, SEMANTIC_GROUNDING_POLICY)
    assert [row["candidate_id"] for row in state["semantic_scores"]] == [good["candidate_id"]]
    assert state["candidates"][1]["logical_lowering"]["status"] == "not_assessed"
    result = _assert_metrics(case, tmp_path, state, good["pattern_query"], 0.5, 1,
                            policy=SEMANTIC_GROUNDING_POLICY)
    assert len(result["candidate_capabilities"]) == 2
    assert result["metrics"]["logical_lowering_status_counts"]["available"] == 1
    assert result["metrics"]["logical_lowering_available_query_rate"] == 0.5


def test_semantic_policy_never_undoes_canonical_grounding_rejection(case):
    case.raw["candidates"][0]["pattern_query"]["source"]["label"] = "type.other"
    state = _infer(case, SEMANTIC_GROUNDING_POLICY)
    assert state["candidates"][0]["validation"]["ok"]
    assert not state["candidates"][0]["grounded"]
    assert state["semantic_scores"] == []


@pytest.mark.parametrize("spec_policy,state_policy", [
    (STRICT_GROUNDING_POLICY, SEMANTIC_GROUNDING_POLICY),
    (SEMANTIC_GROUNDING_POLICY, STRICT_GROUNDING_POLICY),
])
def test_semantic_and_canonical_v1_policies_cannot_be_mixed(tmp_path, spec_policy, state_policy):
    spec = GrailQAPreflightSpec(tmp_path / "missing", {"candidate_grounding_policy": spec_policy})
    with pytest.raises(ValueError, match="matching spec and state"):
        _evaluate_preflight([{"candidate_grounding_policy": state_policy}], spec, tmp_path, {},
                            grounding_policy=SEMANTIC_GROUNDING_POLICY)


def test_shared_anchor_failure_is_unassessed_not_a_false_type_or_recall_result(case, tmp_path):
    case.raw["query_slots"].pop()
    state = _infer(case)
    assert state["returned_candidate_count"] == 1
    result = _assert_metrics(
        case, tmp_path, state, case.raw["candidates"][0]["pattern_query"], 0.0, 0,
        rejected=0, unassessed=1,
    )
    assert result["metrics"]["failure_taxonomy"]["grounding_failure"] == 1
    assert result["metrics"]["failure_taxonomy"]["type_check_failure"] == 0


@pytest.mark.parametrize("strict_spec,strict_states,strict_evaluation", [
    (False, True, False), (True, True, False), (False, True, True), (True, False, True),
])
def test_all_policy_mismatches_fail_before_any_reference_read(
    tmp_path, strict_spec, strict_states, strict_evaluation,
):
    def policy(strict):
        return STRICT_GROUNDING_POLICY if strict else LEGACY_GROUNDING_POLICY
    spec = GrailQAPreflightSpec(tmp_path / "missing", {
        "candidate_grounding_policy": policy(strict_spec),
    })
    with pytest.raises(ValueError, match="matching spec and state"):
        _evaluate_preflight(
            [{"candidate_grounding_policy": policy(strict_states)}], spec, tmp_path, {},
            grounding_policy=policy(strict_evaluation),
        )


def test_policy_mismatch_refuses_evaluation_before_opening_references(tmp_path):
    spec = GrailQAPreflightSpec(tmp_path / "missing", {"candidate_grounding_policy": STRICT_GROUNDING_POLICY})
    with pytest.raises(ValueError, match="matching spec and state"):
        _evaluate_preflight([{}], spec, tmp_path, {}, grounding_policy=STRICT_GROUNDING_POLICY)


@pytest.mark.parametrize("entities", [None, 123, "m.visible", ["m.visible", "m.visible"], [123], [["m.visible"]]])
def test_malformed_entity_declaration_is_local_not_a_run_crash(case, entities):
    bad = copy.deepcopy(case.raw["candidates"][0])
    bad["candidate_id"] = "bad"
    bad["grounding"]["entity_ids"] = entities
    case.raw["candidates"].append(bad)
    batch = _batch(case)
    assert [item.candidate.candidate_id for item in batch.grounded.grounded_candidates] == ["candidate-1"]
    assert batch.failures["bad"].code == "invalid_entity_declaration"


@pytest.mark.parametrize("extra", ["unknown-property", "unknown-class", "unknown-relation"])
def test_unclaimed_condition_terms_are_still_checked_against_visible_context(case, extra):
    if extra == "unknown-property":
        condition = {"kind": "property_equals", "ref": {"kind": "node", "position": 1},
                     "property": "p.invented", "value": 1}
    else:
        ref = {"kind": "node", "position": 1} if extra == "unknown-class" else {"kind": "edge", "index": 1}
        condition = {"kind": "label_equals", "ref": ref, "value": "invented"}
    case.raw["candidates"][0]["pattern_query"]["condition"] = condition
    assert _batch(case).failures["candidate-1"].code == "nonvisible_ast_term"


@pytest.mark.parametrize("value", [None, {}, [], 1, False, ""])
def test_malformed_condition_label_is_candidate_local_not_a_crash(case, value):
    bad = copy.deepcopy(case.raw["candidates"][0])
    bad["candidate_id"] = "bad"
    bad["pattern_query"]["condition"] = {
        "kind": "label_equals", "ref": {"kind": "node", "position": 1}, "value": value,
    }
    case.raw["candidates"].append(bad)
    batch = _batch(case)
    assert [item.candidate.candidate_id for item in batch.grounded.grounded_candidates] == ["candidate-1"]
    assert batch.failures["bad"].code == "invalid_ast_term"
    state = _infer(case)
    assert state["failure"] is None
    assert [item["candidate_id"] for item in state["semantic_scores"]] == ["candidate-1"]


@pytest.mark.parametrize("keys,accepted", [(["p.score"], True), (["p.score", "p.score"], True), (["p.score", "p.other"], False)])
def test_condition_property_declaration_must_have_one_unambiguous_actual_key(case, keys, accepted):
    candidate = case.raw["candidates"][0]
    leaves = [{"kind": "property_equals", "ref": {"kind": "node", "position": 1},
               "property": key, "value": 4} for key in keys]
    candidate["pattern_query"]["condition"] = leaves[0] if len(leaves) == 1 else {"kind": "and", "conditions": leaves}
    case.view = replace(case.view, query_slots=(*case.view.query_slots, PromptQuerySlot(
        "score", "score", "property", ("p.score",), ("fixture",),
    )))
    case.raw["query_slots"].append({"slot_id": "score", "query_anchor_id": "p.score"})
    candidate["grounding"]["slot_realizations"].append({
        "slot_id": "score", "ontology_term_id": "p.score", "component_ref": "condition",
    })
    assert (not _batch(case).failures) is accepted


def test_legacy_entrypoint_cannot_silently_run_the_new_spec(tmp_path):
    from xgap.experiments.grailqa_preflight import run_preflight

    repo = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="guarded development runner"):
        run_preflight(
            repo_root=repo, output_root=tmp_path / "uncreated",
            spec_path=repo / "experiments/specs/grailqa_semantic_preflight_canonical_grounding_v1_cwru_qwen3_32b.json",
        )
    assert not (tmp_path / "uncreated").exists()
