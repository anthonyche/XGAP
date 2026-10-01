"""Resolved IDs must change executable meaning before any backend dispatch."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import threading

import pytest

from xgap.agent.semantic_execution import BoundSemanticExecutionTool, run_agentic_semantic_query, BIND_PLAN_EXECUTE
from xgap.agent.semantic_execution import run_frozen_semantic_query
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE, load_fixture
from xgap.experiments.toy_binding import (binding_values, load_binding_cases, resolution_tools,
    reference_artifact, reference_rows, BUNDLE_FIXTURE)
from xgap.experiments.toy_semantic import toy_backends
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.binding import bind_semantic_query, SemanticBindingValue
from xgap.semantic.program import (SemanticGraphProgram, SemanticProgramError, SemanticHoleKind,
    hard_constraints_sha256)
from xgap.tools import ToolRegistry
from xgap.tools.resolution import ResolutionCandidateTool, ResolutionProviderFailure


CASES = load_binding_cases()
_, _, MAPPING = load_fixture()


def setup(case, *, fail=False, bindings_override=None):
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    calls = []
    lock = threading.Lock()  # Test adapter: the shared SPARQL parser is not reentrant.
    class Client(FusekiClient):
        def __init__(self, name):
            super().__init__(BackendDescriptor(name, "fuseki", "sparql", "rdf"))
            self.graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")
        def _post_query(self, text):
            calls.append((self.backend_id, text))
            if fail:
                raise OSError("controlled backend read failure")
            with lock:
                return json.loads(self.graph.query(text).serialize(format="json"))
    names = ("rdf_a", "rdf_b")
    base = toy_backends(MAPPING)["fuseki"]
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    backends = {name: replace(base, backend_id=name, backend_mapping=replace(mapping, backend_id=name),
        profile=replace(default_profile("fuseki"), backend_id=name)) for name in names}
    return BoundSemanticExecutionTool(SemanticGraphProgram.from_dict(case["program"]), case["operator_sources"],
        binding_values() if bindings_override is None else bindings_override,
        {"toy": LogicalSource("toy", "toy-v1", names)}, backends,
        {name: Client(name) for name in names}, max_candidates=4, max_observation_calls=4), calls


def run_case(case, *, clarification=True, fail=False):
    tool, calls = setup(case, fail=fail)
    result = run_agentic_semantic_query(tool, case["nl"],
        resolution_tools=resolution_tools(case, include_clarification=clarification))
    return result, calls


def run_frozen_case(case, *, root=None, pin=None, fail=False, clarification=True):
    from xgap.tools.artifact_resolution import ExplicitUserSelectionProvider, explicit_user_clarification_tool
    tool, calls = setup(case, fail=fail, bindings_override={})
    reference = json.loads((BUNDLE_FIXTURE / "reference.json").read_text())
    user = (explicit_user_clarification_tool(ExplicitUserSelectionProvider(case["explicit_user_selection"],
            source_id="controlled-toy-user-selection"))
            if clarification and case.get("explicit_user_selection") else None)
    result = run_frozen_semantic_query(program=tool.program, question=case["nl"],
        operator_sources=tool.operator_sources, catalog_root=root or BUNDLE_FIXTURE / reference["root"],
        catalog_hash=pin if pin is not None else reference["bundle_hash"], sources=tool.sources,
        backends=tool.backends, backend_clients=tool.backend_clients, clarification_tool=user,
        max_candidates=4, max_observation_calls=4)
    return result, calls


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["id"])
def test_frozen_catalog_entry_runs_the_same_independent_complete_query(case):
    result, calls = run_frozen_case(case)
    assert result["success"], result
    output = result["state"]["output"]
    assert output["planning_run"]["execution"]["value"]["final_rows"] == case["expected_rows"]
    assert {k:v["value"] for k,v in output["bindings"].items()} == case["expected_bindings"]
    assert output["bound_program"]["metadata"]["resolution_bundle"] == result["resolution_bundle"]
    assert len(calls) == result["backend_remote_calls"] == 3 * case["expected_remote_calls"]
    assert result["input_tokens"] == result["output_tokens"] == 0


@pytest.mark.parametrize("failure", ["missing", "wrong-version"])
def test_unprepared_catalog_stops_before_backend_dispatch(tmp_path, failure):
    result, calls = run_frozen_case(CASES[0], root=tmp_path if failure == "missing" else None,
                                  pin="0" * 64 if failure == "wrong-version" else None)
    assert not result["success"] and result["status"] == "catalog_unavailable"
    assert not calls and result["backend_remote_calls"] == result["resolution_external_calls"] == 0
    assert not list(tmp_path.iterdir())


def test_frozen_entry_preserves_ambiguity_and_one_failed_backend_observation():
    result, calls = run_frozen_case(CASES[4], clarification=False)
    assert not result["success"] and result["status"] == "blocked" and not calls
    result, calls = run_frozen_case(CASES[0], fail=True)
    assert not result["success"] and result["status"] == "failed"
    assert len(calls) == 1  # Observed backend failure is terminal; no automatic retry.


def test_full_query_survives_deleted_preparation_and_reads_only_pinned_catalog(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    from xgap.catalog.build import freeze_resolution_bundle
    from xgap.experiments.toy_binding import FIXTURE
    preparation = tmp_path / "preparation"; preparation.mkdir()
    for name in ("catalog.json", "bindings.json"):
        shutil.copyfile(FIXTURE / name, preparation / name)
    root = tmp_path / "frozen"
    manifest = freeze_resolution_bundle(catalog=preparation / "catalog.json", bindings=preparation / "bindings.json", output=root)
    shutil.rmtree(preparation)
    original_open = Path.open
    def only_frozen_catalog(path, *args, **kwargs):
        if path.name in ("catalog.json", "bindings.json"):
            assert path.parent == root, "Query attempted to open unfrozen preparation inputs"
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", only_frozen_catalog)
    result, calls = run_frozen_case(CASES[0], root=root, pin=manifest["bundle_hash"])
    assert result["success"], result
    assert result["state"]["output"]["planning_run"]["execution"]["value"]["final_rows"] == CASES[0]["expected_rows"]
    assert calls and not preparation.exists()


def resolution(program, case):
    values = binding_values()
    return {"program_id": program.program_id, "hard_constraints_sha256": hard_constraints_sha256(program),
        "hard_constraints_preserved": True, "candidate_sets": [{"hole_id": hole.hole_id,
            "candidate_ids": [next(k for k,v in values.items()
                if v.kind is hole.kind and v.value == case["expected_bindings"][hole.hole_id])],
            "authoritative": hole.kind is SemanticHoleKind.ENTITY, "sources": ["controlled-test"]}
            for hole in program.holes]}


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["id"])
def test_catalog_resolution_bind_plan_execute_matches_independent_gold(case):
    result, calls = run_case(case)
    assert result["success"], result
    output = result["state"]["output"]
    plan = output["planning_run"]
    assert plan["execution"]["value"]["final_rows"] == case["expected_rows"]
    assert {k:v["value"] for k,v in output["bindings"].items()} == case["expected_bindings"]
    assert [op["kind"] for op in output["bound_program"]["operators"]] == case["expected_logical_operators"]
    assert not output["bound_program"]["holes"]
    assert plan["execution_calls"] == case["expected_remote_calls"]
    assert len(calls) == result["backend_remote_calls"] == 3 * case["expected_remote_calls"]
    assert result["input_tokens"] == result["output_tokens"] == 0
    observations = [o for o in result["state"]["observations"] if o["kind"] == "tool_result"]
    assert observations[-1]["source"] == BIND_PLAN_EXECUTE
    assert sum(o["source"] == "user.clarify" for o in observations) == int("explicit_user_selection" in case)


@pytest.mark.parametrize("case", CASES, ids=lambda c:c["id"])
def test_independent_reference_uses_typed_rdf_results(case):
    tool,calls=setup(case)
    result=tool.backend_clients["rdf_a"].execute(reference_artifact(case,"fuseki"))
    assert result.success and reference_rows(result,"fuseki")==case["expected_rows"]
    assert len(calls)==1


def test_entity_ambiguity_blocks_before_planning_or_database_calls():
    result, calls = run_case(CASES[4], clarification=False)
    assert not result["success"] and result["state"]["status"] == "blocked"
    assert not calls and result["backend_remote_calls"] == 0


def test_physical_costs_do_not_choose_between_ambiguous_predicate_meanings():
    case=deepcopy(CASES[0])
    case["program"]["holes"][1]["candidates"]=["predicate:knows", "predicate:other"]
    result,calls=run_case(case)
    assert not result["success"] and result["state"]["status"]=="blocked"
    assert not calls


def test_failed_catalog_lookup_is_observed_once_without_backend_calls():
    attempts=[]
    class Provider:
        def resolve(self,request,context):
            attempts.append(request.hole_id)
            raise ResolutionProviderFailure("controlled unavailable catalog",source_id="replay-catalog",
                failure_category="artifact_unavailable")
    registry=ToolRegistry()
    registry.register(ResolutionCandidateTool("semantic.catalog.lookup", "local failure replay", Provider(), True))
    tool,calls=setup(CASES[0])
    result=run_agentic_semantic_query(tool,CASES[0]["nl"],resolution_tools=registry)
    assert not result["success"] and len(attempts)==1 and not calls
    observation=next(o for o in result["state"]["observations"] if o["kind"]=="tool_result")
    assert observation["payload"]["status"]=="error"


def test_binding_preserves_template_constraints_and_legacy_hash_contract():
    case = CASES[0]; program = SemanticGraphProgram.from_dict(case["program"])
    before = program.to_dict()
    bound = bind_semantic_query(program, resolution(program,case), binding_values=binding_values(), operator_sources=case["operator_sources"])
    assert program.to_dict() == before
    assert SemanticGraphProgram.from_dict(before).to_dict() == before
    for old, new in zip(program.operators, bound.program.operators):
        assert [(c.constraint_id,c.expression,c.policy) for c in old.constraints] == [(c.constraint_id,c.expression,c.policy) for c in new.constraints]
    assert bound.program.operators[0].constraints[0].predicate["value"] == "a"
    assert bound.program.metadata["semantic_binding"]["original_hard_constraints_sha256"] == hard_constraints_sha256(program)
    raw = deepcopy(case["program"])
    for op in raw["operators"]:
        for c in op.get("constraints",[]):
            c.pop("predicate")
    legacy = SemanticGraphProgram.from_dict(raw)
    payload = [{"operator_id":op.operator_id,"constraint":c.to_dict()} for op in legacy.operators for c in op.constraints]
    expected = hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
    assert hard_constraints_sha256(legacy) == expected != hard_constraints_sha256(program)


@pytest.mark.parametrize("fault", ["unused", "decorative", "wrong-kind", "unregistered", "non-authoritative", "wrong-hash", "negated", "disjunction"])
def test_bad_binding_cannot_be_applied(fault):
    case=deepcopy(CASES[0]); raw=case["program"]
    if fault == "unused":
        raw["operators"][0]["constraints"][0]["predicate"]["value"]="a"
    if fault == "decorative":
        raw["operators"][0]["constraints"][0]["predicate"]["value"]="a"
        raw["operators"][0]["parameters"]["path_pattern"]["path_var"]={"$hole":"person"}
    if fault in ("negated", "disjunction"):
        c=raw["operators"][0]["constraints"][0]; pred=c["predicate"]
        c["predicate"]={"kind":"not","condition":pred} if fault=="negated" else {"kind":"or","conditions":[pred,{"kind":"length_equals","value":1}]}
    program=SemanticGraphProgram.from_dict(raw); resolved=resolution(program,case); values=binding_values()
    if fault=="wrong-kind":values["entity:alice"]=SemanticBindingValue(SemanticHoleKind.TYPE,"a")
    if fault=="unregistered":values.pop("entity:alice")
    if fault=="non-authoritative":resolved["candidate_sets"][0]["authoritative"]=False
    if fault=="wrong-hash":resolved["hard_constraints_sha256"]="stale"
    with pytest.raises(SemanticProgramError):
        bind_semantic_query(program,resolved,binding_values=values,operator_sources=case["operator_sources"])


@pytest.mark.parametrize("fault", ["opaque", "decorative", "unsupported-owner"])
def test_unapplied_constraints_fail_before_backend_dispatch(fault):
    case=deepcopy(CASES[0])
    if fault=="opaque":case["program"]["operators"][0]["constraints"][0].pop("predicate")
    elif fault=="decorative":
        case["program"]["operators"][0]["constraints"][0]["predicate"]["value"]="a"
        case["program"]["operators"][0]["parameters"]["path_pattern"]["path_var"]={"$hole":"person"}
    else:
        case["program"]["operators"][-1]["constraints"]=[{"constraint_id":"unsupported","expression":"unsupported","policy":"hard","predicate":{"op":"ge","field":"age","value":30}}]
    result,calls=run_case(case)
    assert not result["success"] and not calls


@pytest.mark.parametrize("scope", ["traverse", "filter", "match"])
def test_structured_constraints_are_conjoined_with_existing_filters(scope):
    case=deepcopy(CASES[3] if scope=="match" else CASES[0])
    if scope=="traverse":
        case["program"]["operators"][0]["parameters"]["path_pattern"]["condition"]={"kind":"property_equals","ref":{"kind":"node","position":"first"},"property":"id","value":"b"}
    elif scope=="filter":case["program"]["operators"][3]["parameters"]["condition"]={"op":"lt","field":"age","value":30}
    else:case["program"]["operators"][0]["parameters"]["node"]["properties"]={"id":"b"}
    result,calls=run_case(case)
    assert result["success"],result
    assert result["state"]["output"]["planning_run"]["execution"]["value"]["final_rows"]==[]
    assert calls


def test_backend_failure_is_observed_once_without_serving_or_retry():
    result,calls=run_case(CASES[0],fail=True)
    assert not result["success"] and len(calls)==result["backend_remote_calls"]==1
    run=result["state"]["observations"][-1]["payload"]["value"]["planning_run"]
    assert run["execution_calls"]==run["automatic_retries"]==0
