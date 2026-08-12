from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from xgap.experiments.bundles import DatasetBundle
from xgap.experiments.contracts import ExperimentSpec
from xgap.experiments.runtime_alignment import (
    FileBackedRuntimeAlignmentProvider,
    OntologyArtifactLoader,
    OntologyContextRetriever,
    PromptSchemaViewBuilder,
    RetrievalLimits,
    RuntimeAlignmentError,
    assert_no_gold_leakage,
    parse_grounded_planner_response,
)
from xgap.experiments.semantic import DirectionalOntologySemanticDeviationScorer
from xgap.llm.openai_compatible import LiveFailureCategory
from xgap.llm.parser import parse_planner_response
from xgap.llm.schemas import PlannerRequest
from xgap.planning import MappingSufficiencyStatus, QueryPlanningContext


ROOT = Path(__file__).resolve().parents[1]


def _bundle() -> DatasetBundle:
    return DatasetBundle.load(ROOT / "datasets/financial_risk_dev")


def _view(question_id: str = "fr-q001", *, limits: RetrievalLimits | None = None):
    dataset = _bundle()
    loader = OntologyArtifactLoader.from_dataset(dataset)
    retriever = OntologyContextRetriever(loader, limits or RetrievalLimits())
    view = PromptSchemaViewBuilder(loader, retriever).build(
        task_id="runtime-task",
        question=dataset.question(question_id).text,
        backend_ids=("reference_evaluator",),
    )
    return dataset, loader, view


def _candidate() -> dict[str, Any]:
    return {
        "candidate_id": "runtime-candidate",
        "confidence": 0.8,
        "rationale": "Runtime-grounded interpretation.",
        "pattern_query": {
            "path_var": "p",
            "source": {"var": "person", "label": "Person", "properties": {"name": "Alice"}},
            "expr": {
                "kind": "seq",
                "left": {
                    "kind": "rel",
                    "edge": {"var": "owns", "label": "OWNS", "direction": "OUT", "properties": {}},
                },
                "right": {
                    "kind": "rel",
                    "edge": {"var": "transfer", "label": "TRANSFER", "direction": "OUT", "properties": {}},
                },
            },
            "target": {"var": "account", "label": "Account", "properties": {}},
            "selector": {"kind": "ALL", "k": None},
            "restrictor": "TRAIL",
            "condition": None,
            "max_depth": None,
        },
    }


def _grounded_raw(view, *, realization_overrides: dict[str, str] | None = None):
    overrides = realization_overrides or {}
    candidate = _candidate()
    candidate["grounding"] = {
        "slot_realizations": [
            {
                "slot_id": slot.slot_id,
                "ontology_term_id": overrides.get(slot.slot_id, slot.candidate_anchor_ids[0]),
                "component_ref": f"pattern.{slot.slot_id}",
            }
            for slot in view.query_slots
        ],
        "entity_ids": list(view.visible_entity_ids),
    }
    return {
        "provider_id": "runtime-test-provider",
        "model": "runtime-test-model",
        "query_slots": [
            {"slot_id": slot.slot_id, "query_anchor_id": slot.candidate_anchor_ids[0]}
            for slot in view.query_slots
        ],
        "candidates": [candidate],
    }


def _parse(view, raw):
    request = PlannerRequest("runtime question", max_candidates=3)
    response = parse_planner_response(raw, request)
    return response, parse_grounded_planner_response(raw, response, view)


def test_prompt_schema_view_is_bounded_deterministic_and_gold_free() -> None:
    dataset, loader, first = _view(limits=RetrievalLimits(4, 3, 2, 5))
    _, _, second = _view(limits=RetrievalLimits(4, 3, 2, 5))

    assert first.to_dict() == second.to_dict()
    assert len(first.query_slots) <= 4
    assert all(len(slot.candidate_anchor_ids) <= 3 for slot in first.query_slots)
    assert len(first.entities) <= 2
    assert len(first.source_schema_items) <= 5
    assert set(first.visible_term_ids) < set(dataset.ontology.all_terms)
    assert "Person" in first.visible_term_ids
    assert "Ownership" in first.visible_term_ids
    assert "Transfer" in first.visible_term_ids
    assert "Account" in first.visible_term_ids
    assert loader.runtime_manifest["gold_artifacts_exposed"] is False
    assert not hasattr(loader, "gold_alignments")
    assert_no_gold_leakage(first.to_dict())


def test_query_anchor_and_candidate_realization_remain_separate_and_reuse_c_sem() -> None:
    dataset, loader, view = _view()
    account_slot = next(slot for slot in view.query_slots if slot.candidate_anchor_ids[0] == "Account")
    raw = _grounded_raw(view, realization_overrides={account_slot.slot_id: "FinancialEntity"})
    response, grounded = _parse(view, raw)
    provider = FileBackedRuntimeAlignmentProvider(
        loader, view, grounded, ("reference_evaluator",)
    )
    candidate = response.candidates[0]
    query_context = QueryPlanningContext("q", "task", "question")
    alignment = provider.resolve(query_context, candidate)
    result = DirectionalOntologySemanticDeviationScorer(
        dataset.ontology,
        ExperimentSpec.load(
            ROOT / "experiments/configs/financial_risk_qwen_live_dev.json"
        ).semantic_deviation,
    ).score(query_context, candidate, alignment)

    account_evidence = next(
        item for item in alignment.semantic_inputs["slot_alignments"]
        if item["slot_id"] == account_slot.slot_id
    )
    assert account_evidence["query_term"] == "Account"
    assert account_evidence["aligned_term"] == "FinancialEntity"
    assert result.value is not None and result.value > 0
    assert result.components["measurement"]["slots"][-1]["relation"] == "generalization"


def test_hallucinated_id_and_incomplete_slot_coverage_fail_explicitly() -> None:
    _, _, view = _view()
    hallucinated = _grounded_raw(view)
    hallucinated["query_slots"][0]["query_anchor_id"] = "HallucinatedTerm"
    response = parse_planner_response(hallucinated, PlannerRequest("question"))
    with pytest.raises(RuntimeAlignmentError) as caught:
        parse_grounded_planner_response(hallucinated, response, view)
    assert caught.value.category is LiveFailureCategory.HALLUCINATED_ONTOLOGY_ID

    incomplete = _grounded_raw(view)
    incomplete["candidates"][0]["grounding"]["slot_realizations"].pop()
    response = parse_planner_response(incomplete, PlannerRequest("question"))
    with pytest.raises(RuntimeAlignmentError) as caught:
        parse_grounded_planner_response(incomplete, response, view)
    assert caught.value.category is LiveFailureCategory.INCOMPLETE_SLOT_COVERAGE


def test_missing_backend_mapping_is_reported_by_file_backed_provider() -> None:
    _, loader, view = _view()
    person_slot = next(slot for slot in view.query_slots if slot.candidate_anchor_ids[0] == "Person")
    raw = _grounded_raw(view, realization_overrides={person_slot.slot_id: "FinancialEntity"})
    response, grounded = _parse(view, raw)
    provider = FileBackedRuntimeAlignmentProvider(loader, view, grounded, ("neo4j",))

    alignment = provider.resolve(
        QueryPlanningContext("q", "task", "question"), response.candidates[0]
    )

    assert alignment.mapping_sufficiency.status is MappingSufficiencyStatus.MISSING
    assert alignment.mapping_sufficiency.required_terms
    assert "FinancialEntity" in alignment.mapping_sufficiency.reason


def test_runtime_loader_and_provider_reject_invalid_artifact_references() -> None:
    _, loader, view = _view()
    bad_mapping = dict(loader.backend_mapping)
    term_mappings = {
        key: dict(value)
        for key, value in bad_mapping["term_mappings"].items()
    }
    term_mappings["reference_evaluator"]["UnknownTerm"] = {
        "kind": "class",
        "representation": "label:Unknown",
    }
    bad_mapping["term_mappings"] = term_mappings
    with pytest.raises(ValueError, match="unknown ontology IDs"):
        replace(loader, backend_mapping=bad_mapping)

    raw = _grounded_raw(view)
    _, grounded = _parse(view, raw)
    with pytest.raises(ValueError, match="unknown backend mappings"):
        FileBackedRuntimeAlignmentProvider(
            loader, view, grounded, ("unknown-backend",)
        )


def test_runtime_sibling_alignment_is_admissible_under_frozen_m12_metric() -> None:
    dataset, loader, view = _view("fr-q018")
    slot = view.query_slots[0]
    assert slot.candidate_anchor_ids[0] == "HighRiskCompany"
    assert "LowRiskCompany" in slot.candidate_anchor_ids
    raw = _grounded_raw(view, realization_overrides={slot.slot_id: "LowRiskCompany"})
    response, grounded = _parse(view, raw)
    provider = FileBackedRuntimeAlignmentProvider(
        loader, view, grounded, ("reference_evaluator",)
    )
    context = QueryPlanningContext("q", "task", "question")
    alignment = provider.resolve(context, response.candidates[0])
    scorer = DirectionalOntologySemanticDeviationScorer(
        dataset.ontology,
        ExperimentSpec.load(
            ROOT / "experiments/configs/financial_risk_qwen_live_dev.json"
        ).semantic_deviation,
    )

    result = scorer.score(context, response.candidates[0], alignment)

    assert result.value == 0.5
    assert result.components["measurement"]["slots"][0]["relation"] == "sibling"


def test_anti_leakage_guard_rejects_evaluation_only_fields_recursively() -> None:
    for key in ("gold_answers", "gold_logical_form", "gold_alignments", "evaluation_labels"):
        with pytest.raises(ValueError, match="Evaluation-only field"):
            assert_no_gold_leakage({"nested": [{key: "forbidden"}]})
