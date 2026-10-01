"""Bounded predicted identity binding; no service, model or benchmark run."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from xgap.agent.one_shot_grounding import OneShotGroundingError, ground_interpretation
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.toy_binding import BUNDLE_FIXTURE, load_binding_cases
from xgap.semantic.binding import SemanticBindingValue, bind_semantic_query
from xgap.semantic.program import SemanticGraphProgram, SemanticHole, SemanticHoleKind, SemanticProgramError
from xgap.tools.artifact_resolution import ArtifactOntologyProvider, ONTOLOGY_SCHEMA_VERSION
from xgap.tools.resolution import ResolutionCandidateRequest, ResolutionProviderFailure


def inputs(index=0):
    case = load_binding_cases()[index]
    reference = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
    bundle = FrozenResolutionBundle.load(BUNDLE_FIXTURE / reference["root"],
                                         expected_bundle_hash=reference["bundle_hash"])
    return case, SemanticGraphProgram.from_dict(case["program"]), bundle


def test_original_tiny_meaning_binds_without_rewriting_hard_constraints_or_truth():
    case, program, bundle = inputs()
    before = program.to_dict()
    bound, trace = ground_interpretation(program, case["operator_sources"], bundle, case["nl"])
    assert {name: item["value"] for name, item in bound.bindings.items()} == case["expected_bindings"]
    assert bound.program.holes == () and program.to_dict() == before
    assert trace["lookup_count"] == trace["catalog_lookup_count"] == len(program.holes)
    assert trace["ontology_lookup_count"] == trace["external_calls"] == trace["model_calls"] == 0
    assert trace["success"] and not trace["approximate"]
    assert bound.bindings["person"]["authoritative"] is True


def test_ambiguous_entity_is_a_prediction_and_cannot_enter_legacy_binding_as_authority():
    case, program, bundle = inputs(4)
    bound, trace = ground_interpretation(program, case["operator_sources"], bundle, case["nl"])
    selected = next(item for item in trace["candidate_sets"] if item["hole_id"] == "person")
    assert selected["candidate_ids"] == ["entity:alice", "entity:bob"]
    assert selected["selected_candidate_id"] == "entity:alice"
    assert selected["authoritative"] is False and trace["approximate"]
    assert bound.bindings["person"]["authoritative"] is False
    assert bound.bindings["person"]["selection_policy"] == "predicted_catalog_choice"
    with pytest.raises(SemanticProgramError, match="authoritative"):
        bind_semantic_query(program, trace["resolution"], binding_values=bundle.bindings,
                            operator_sources=case["operator_sources"])
    malformed = deepcopy(trace["resolution"])
    next(item for item in malformed["candidate_sets"] if item["hole_id"] == "person").pop("selection_policy")
    with pytest.raises(SemanticProgramError, match="authoritative"):
        bind_semantic_query(program, malformed, binding_values=bundle.bindings,
                            operator_sources=case["operator_sources"], allow_predicted_entities=True)


def test_bounded_catalog_stops_at_cap_plus_one_and_reports_unknown_full_match_count():
    case, program, bundle = inputs(4)
    _, trace = ground_interpretation(program, case["operator_sources"], bundle, case["nl"],
                                     max_candidates_per_hole=1, use_ontology=False)
    lookup = next(item for item in trace["lookups"] if item["request"]["hole_id"] == "person")
    response = lookup["response"]
    assert response["candidate_ids"] == ["entity:alice"] and response["authoritative"] is False
    metadata = response["metadata"]
    assert metadata["truncated"] and not metadata["scan_complete"]
    assert metadata["entries_visited"] == metadata["matched_candidate_count_lower_bound"] == 2
    assert metadata["matched_candidate_count"] is None
    with pytest.raises(ResolutionProviderFailure, match="refusing silent truncation"):
        bundle.catalog.resolve(ResolutionCandidateRequest.from_arguments(lookup["request"]), None)
    request = replace(ResolutionCandidateRequest.from_arguments(lookup["request"]), max_candidates=2)
    complete = bundle.catalog.resolve_bounded(request, None)
    assert complete.metadata["matched_candidate_count"] == 2
    assert complete.metadata["scan_complete"] and not complete.metadata["truncated"]


@pytest.mark.parametrize("required", [True, False])
def test_missing_referenced_hole_cannot_be_silently_dropped_even_if_optional(required):
    case, program, bundle = inputs()
    program = replace(program, holes=tuple(replace(hole, mention="missing", required=required)
                      if hole.hole_id == "person" else hole for hole in program.holes))
    with pytest.raises(OneShotGroundingError) as failure:
        ground_interpretation(program, case["operator_sources"], bundle, case["nl"])
    trace = failure.value.trace
    assert trace["lookup_count"] >= 1 and not trace["success"]
    assert trace["external_calls"] == 0 and trace["automatic_retries"] == 0
    assert any(item["selected_candidate_id"] is None for item in trace["candidate_sets"])


def test_unused_optional_hole_and_zero_hole_program_do_not_require_artificial_bindings():
    case, program, bundle = inputs()
    program = replace(program, holes=(*program.holes,
        SemanticHole("optional-unused", SemanticHoleKind.TYPE, "missing optional", required=False)))
    bound, trace = ground_interpretation(program, case["operator_sources"], bundle, case["nl"])
    assert not bound.program.holes and trace["candidate_sets"][-1]["status"] == "unresolved"
    again, empty = ground_interpretation(bound.program, bound.operator_sources, bundle, case["nl"])
    assert empty["success"] and empty["lookup_count"] == 0
    assert again.operator_sources == bound.operator_sources


def test_precision_ontology_lookup_only_fills_missing_predicate_and_performance_stops(tmp_path):
    case, program, bundle = inputs()
    artifact = {"schema_version": ONTOLOGY_SCHEMA_VERSION, "ontology_id": "tiny-ontology",
        "ontology_version": "v1", "concepts": [{"candidate_id": "predicate:connected",
            "kind": "predicate", "labels": ["connected"], "provenance": {"scope": "test"}}],
        "relations": [], "metadata": {"scope": "toy-development"}}
    path = tmp_path / "ontology.json"
    path.write_text(json.dumps(artifact))
    bundle = replace(bundle, ontology=ArtifactOntologyProvider(path), bindings={**bundle.bindings,
        "predicate:connected": SemanticBindingValue(SemanticHoleKind.PREDICATE, "KNOWS")})
    program = replace(program, holes=tuple(replace(hole, mention="connected")
                      if hole.hole_id == "predicate" else hole for hole in program.holes))
    bound, precision = ground_interpretation(program, case["operator_sources"], bundle, case["nl"], use_ontology=True)
    assert bound.bindings["predicate"]["value"] == "KNOWS"
    assert precision["ontology_lookup_count"] == 1
    assert [item["request"]["hole_kind"] for item in precision["lookups"] if item["kind"] == "ontology"] == ["predicate"]
    with pytest.raises(OneShotGroundingError) as failure:
        ground_interpretation(program, case["operator_sources"], bundle, case["nl"], use_ontology=False)
    assert failure.value.trace["ontology_lookup_count"] == 0


def test_predicted_entity_still_requires_typed_binding_and_enforcing_identity():
    case, program, bundle = inputs(4)
    raw = program.to_dict()
    raw["operators"][0]["constraints"][0]["predicate"]["property"] = "display_name"
    with pytest.raises(OneShotGroundingError, match="enforce node identity"):
        ground_interpretation(SemanticGraphProgram.from_dict(raw), case["operator_sources"], bundle, case["nl"])
    broken = replace(bundle, bindings={**bundle.bindings,
        "entity:alice": SemanticBindingValue(SemanticHoleKind.TYPE, "Person")})
    with pytest.raises(OneShotGroundingError, match="compatible typed binding"):
        ground_interpretation(program, case["operator_sources"], broken, case["nl"])


def test_hole_budget_fails_before_lookup_and_local_provider_failure_is_recorded_once(monkeypatch):
    case, program, bundle = inputs()
    calls = []

    def broken(request, context):
        calls.append(request.hole_id)
        raise OSError("local frozen catalog unavailable")

    monkeypatch.setattr(bundle.catalog, "resolve_bounded", broken)
    with pytest.raises(OneShotGroundingError) as failure:
        ground_interpretation(program, case["operator_sources"], bundle, case["nl"], max_holes=1)
    assert calls == [] and failure.value.trace["lookup_count"] == 0
    with pytest.raises(OneShotGroundingError) as failure:
        ground_interpretation(program, case["operator_sources"], bundle, case["nl"])
    assert len(calls) == failure.value.trace["lookup_count"] == 1
    assert failure.value.trace["lookups"][0]["status"] == "failed"
    assert failure.value.trace["lookups"][0]["elapsed_ms"] >= 0
    assert failure.value.trace["automatic_retries"] == 0
