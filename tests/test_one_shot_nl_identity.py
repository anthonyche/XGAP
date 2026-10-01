"""Replay the new failure and validate generic identity syntax, with no services."""

import json
from pathlib import Path

from xgap.agent.one_shot_grounding import ground_interpretation
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.experiments.one_shot_split import split_inputs, load_split_provider
from xgap.experiments.one_shot_toy import load_one_shot_toy_provider
from xgap.semantic.interpretation import InterpretationRequest, InterpretationResponse
from xgap.semantic.interpretation_candidates import interpret_candidate_question, SCHEMA
from xgap.semantic.interpretation_replay import ReplayInterpretationProvider
from xgap.semantic.program import SemanticGraphProgram


def test_actual_invalid_node_descriptor_replays_unchanged_without_a_model_call():
    saved = json.loads((Path(__file__).parent / "fixtures/one_shot_split_invalid_source.json").read_text())["recording"]
    raw = saved["records"][0]["request"]
    request = InterpretationRequest(raw["question"], raw["context"], tuple(raw["required_constraints"]), raw["max_response_bytes"])
    provider = ReplayInterpretationProvider(saved)
    result = interpret_candidate_question(request, provider, candidate_cap=1)
    provider.assert_consumed()
    assert result["status"] == "no_admissible_interpretation"
    assert result["external_calls"] == 0
    assert "unknown fields ['condition']" in result["candidates"][0]["error"]
    assert result["candidates"][0]["raw_candidate"] == saved["records"][0]["response"]["payload"]["candidates"][0]


def test_generic_nl_identity_syntax_binds_without_prepared_request_constraints():
    request, _, inputs, _ = split_inputs()
    # Independently authored minimal syntax example, not a repaired model record.
    program = {"program_id":"identity-syntax", "operators":[{
        "operator_id":"edge_lookup", "kind":"traverse", "input_ids":[], "input_kinds":[], "output_kind":"path_set",
        "parameters":{"path_pattern":{"path_var":None, "source":{"properties":{"id":{"$hole":"who"}}},
            "expr":{"kind":"rel","edge":{"label":{"$hole":"relation"},"direction":"OUT","properties":{}}},
            "target":{},"selector":{"kind":"ALL","k":None},"restrictor":"WALK","condition":None,"max_depth":None}},
        "constraints":[],"required_capabilities":[]}], "roots":["edge_lookup"], "metadata":{},
        "holes":[{"hole_id":key,"kind":kind,"mention":mention,"required":True,"candidates":[],"is_resolved":False}
            for key,kind,mention in (("who","entity","Nora"),("relation","predicate","knows"))]}
    class Example:
        provider_id = "authored-syntax-example"
        def interpret(self, request):
            return InterpretationResponse({"schema_version":SCHEMA,"candidates":[{
                "candidate_id":"syntax","quality_proxy":None,"program":program,"operator_sources":{"edge_lookup":"relations"}}]})
    admitted = interpret_candidate_question(request, Example(), candidate_cap=1)
    assert admitted["success"] and request.required_constraints == ()
    bundle = FrozenResolutionBundle.load(inputs["catalog_root"], expected_bundle_hash=inputs["catalog_hash"])
    bound, trace = ground_interpretation(SemanticGraphProgram.from_dict(program), {"edge_lookup":"relations"},
        bundle, request.question, use_ontology=False)
    assert bound.program.operators[0].parameters["path_pattern"]["source"]["properties"]["id"] == "a"
    assert trace["candidate_sets"][0]["authoritative"] is False
    provider = load_split_provider()
    original = load_one_shot_toy_provider(mode="performance", wire_profile="envelope-schema-v1")
    assert provider.config.prompt_hash != original.config.prompt_hash
    assert provider.config.structured_schema == original.config.structured_schema
    payload = provider.build_request_payload(request)
    assert provider.token_guard.check(payload, call_kind="generation")["passed"]
    assert "source.properties" not in json.dumps(request.to_dict())
    assert "nl-only-identity-v1" in provider.provider_id
