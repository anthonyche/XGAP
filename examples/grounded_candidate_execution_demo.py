"""Compile a controlled grounded response; no model/backend calls or gold data.

The callable fixture also supports separately recorded native development runs.
Its entity and scalar constant are explicit caller inputs, never repaired IDs.
"""

import json

from xgap.experiments.freebase_candidate_compiler import ExecutionRequirements, FreebaseExecutionMapping
from xgap.experiments.freebase_candidate_execution import prepare_candidate_batch
from xgap.experiments.runtime_alignment import PromptSchemaView, PromptQuerySlot, RetrievedOntologyTerm, RetrievalLimits
from xgap.llm.schemas import PlannerRequest


def controlled_recording_case(entity_id="m.fixture_recording", *, filter_value="1"):
    relations = ("music.release_track.recording", "music.release_track.release")
    prop = "music.release_track.track_number"
    terms = tuple(RetrievedOntologyTerm(term, "relation", term, (), 1.0, ("controlled-fixture",)) for term in relations)
    slots = tuple(PromptQuerySlot(f"r{i}", "controlled fixture", "relation", (term,), ("controlled-fixture",))
                  for i, term in enumerate(relations, 1))
    if filter_value is not None:
        terms += (RetrievedOntologyTerm(prop, "property", prop, (), 1.0, ("controlled-fixture",)),)
        slots += (PromptQuerySlot("p1", "controlled fixture", "property", (prop,), ("controlled-fixture",)),)
    view = PromptSchemaView("controlled-recording", "freebase-fixture", "v1", "controlled-fixture",
        "v1", "controlled-fixture", terms, ({"entity_id": entity_id},), slots, {},
        tuple(t.term_id for t in terms), RetrievalLimits(20, 4, 4, 4))
    request = PlannerRequest("Controlled fixture: releases linked to this recording through the selected track number",
        metadata={"task_id": view.task_id, "prompt_schema_view": view.to_dict(), "controlled_fixture": True})
    raw = {"provider_id": "controlled-fixture-no-model", "query_slots": [
        {"slot_id": slot.slot_id, "query_anchor_id": slot.candidate_anchor_ids[0]} for slot in slots], "candidates": [{
        "candidate_id": "explicit-recording", "pattern_query": {
            "source": {"label": None, "properties": {"type.object.id": entity_id}},
            "expr": {"kind": "seq", "left": {"kind": "rel", "edge": {"label": relations[0], "direction": "IN", "properties": {}}},
                     "right": {"kind": "rel", "edge": {"label": relations[1], "direction": "OUT", "properties": {}}}},
            "target": {"label": None, "properties": {}}, "selector": {"kind": "ALL", "k": None},
            "restrictor": "SIMPLE", "max_depth": 2,
            "condition": None if filter_value is None else {"kind": "property_equals", "ref": {"kind": "node", "position": 2},
                                                            "property": prop, "value": filter_value}},
        "grounding": {"entity_ids": [entity_id], "slot_realizations": [
            {"slot_id": "r1", "ontology_term_id": relations[0], "component_ref": "expr.left.edge"},
            {"slot_id": "r2", "ontology_term_id": relations[1], "component_ref": "expr.right.edge"},
            *([] if filter_value is None else [{"slot_id": "p1", "ontology_term_id": prop, "component_ref": "condition"}])]}}]}
    return raw, request, view


def main():
    raw, request, view = controlled_recording_case()
    mapping = FreebaseExecutionMapping("controlled-fixture", "a"*64, {"music.release_track.track_number": "string"})
    prepared = prepare_candidate_batch(raw, request, view, mapping, ExecutionRequirements(True), max_rows=100, max_binding_bytes=8192)
    assert prepared.evidence["prepared_count"] == 1, prepared.evidence
    print(json.dumps({"controlled_fixture": True, "executed": False, "preparation": prepared.evidence,
                      "plans": [program.plan.to_dict() for program in prepared.programs.values()]}, indent=2))


if __name__ == "__main__":
    main()
