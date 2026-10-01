"""Plan generation and selection use meaning and observations, not toy gold."""

from copy import deepcopy
from dataclasses import replace
import json
import threading

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE, load_fixture
from xgap.experiments.toy_semantic import load_semantic_cases, toy_backends
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.planning import FederatedPlanSelector, PlanObservationSnapshot, RemoteEstimate
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans, run_semantic_plans
from xgap.semantic.program import SemanticGraphProgram, SemanticProgramError
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin


_, _, MAPPING = load_fixture()
CASES = load_semantic_cases()


def setup(case=CASES[0], *, replicas=("rdf_a", "rdf_b"), version="toy-v1", **options):
    base = toy_backends(MAPPING)["fuseki"]
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    backends = {name: replace(base, backend_id=name, backend_mapping=replace(mapping,backend_id=name),
        profile=replace(default_profile("fuseki"), backend_id=name)) for name in replicas}
    return enumerate_semantic_plans(SemanticGraphProgram.from_dict(case["program"]),
        operator_sources={op:"toy" for op in case["source_bindings"]},
        sources={"toy":LogicalSource("toy",version,replicas)}, backends=backends, **options)


def registry(space, *, fail=False):
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    calls=[]
    parser_lock=threading.Lock()  # RDFLib's shared SPARQL parser is not reentrant.
    class Client(FusekiClient):
        def __init__(self,name):
            super().__init__(BackendDescriptor(name,"fuseki","sparql","rdf"))
            self.graph=rdf.Graph().parse(DEFAULT_FIXTURE/"load.ttl",format="turtle")
        def _post_query(self,text):
            calls.append((self.backend_id,text))
            if fail:
                raise OSError("controlled read failure")
            with parser_lock:
                return json.loads(self.graph.query(text).serialize(format="json"))
    plugins=BackendPluginRegistry()
    for name,catalog in space.observation_catalogs.items():
        plugins.register(CatalogBackendPlugin(name,Client(name),catalog))
    return BackendInvokeTool(plugins),calls


def controlled_snapshot(space, preferred):
    estimates=[]
    for request in space.observation_requests:
        artifact=space.observation_catalogs[request.backend_id].query_artifacts[request.payload["query_id"]]
        role="paths" if artifact.parameters.get("path_selection") else "people"
        latency=1.0 if request.backend_id==preferred[role] else 1000.0
        estimates.append(RemoteEstimate(request.observation_key,request.backend_id,latency,5,40,
                                       "controlled cost fixture", "v1"))
    return PlanObservationSnapshot("controlled","v1",tuple(estimates),1000,0.2,0.05)


def test_enumeration_compiles_four_distinct_equivalent_plans_and_four_unique_observations():
    space=setup()
    assert len(space.candidates)==4 and len(space.observation_requests)==4
    assert len({c.plan.plan_id for c in space.candidates})==4
    assert len({c.semantic_equivalence_key for c in space.candidates})==1
    assert all(sum(n.kind.value=="exchange" for n in c.plan.nodes)==2 for c in space.candidates)
    reordered=setup(replicas=("rdf_b","rdf_a"))
    assert [c.plan.to_dict() for c in space.candidates]==[c.plan.to_dict() for c in reordered.candidates]


@pytest.mark.parametrize("preferred",[
    {"paths":"rdf_a","people":"rdf_b"}, {"paths":"rdf_b","people":"rdf_a"}])
def test_cost_changes_switch_placement_and_selected_program_keeps_exact_answer(preferred):
    space=setup(); tool,calls=registry(space)
    result=run_semantic_plans(space,tool,snapshot=controlled_snapshot(space,preferred))
    assert result["success"],result
    assert result["selected_plan"]["metadata"]["source_bindings"]==preferred
    assert result["execution"]["value"]["final_rows"]==CASES[0]["expected_rows"]
    assert len(calls)==result["execution_calls"]==result["total_remote_calls"]==2
    assert result["observation_calls"]==0 and result["snapshot_reused"]
    estimates=result["selection"]["estimates"]
    assert all(e["predicted_transfer_bytes"]>0 for e in estimates)
    assert all(e["predicted_latency_ms"]>1 for e in estimates)


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_all_compositions_acquire_unique_observations_then_execute_the_selected_plan(case):
    space=setup(case); tool,calls=registry(space)
    result=run_semantic_plans(space,tool)
    assert result["success"],result
    actual=result["execution"]["value"]["final_rows"]
    canonical=lambda rows: sorted(json.dumps(r,sort_keys=True) for r in rows)
    assert (actual==case["expected_rows"] if case["ordered"] else canonical(actual)==canonical(case["expected_rows"]))
    assert result["observation_calls"]==2*case["expected_remote_calls"]
    assert result["execution_calls"]==case["expected_remote_calls"]
    assert result["total_remote_calls"]==len(calls)==3*case["expected_remote_calls"]
    assert result["planning_ms"]>=result["observation"]["elapsed_ms"]
    assert result["end_to_end_ms"]>=result["planning_ms"]


def test_missing_observation_or_failed_acquisition_dispatches_no_selected_plan():
    space=setup(); tool,calls=registry(space,fail=True)
    result=run_semantic_plans(space,tool)
    assert not result["success"] and len(calls)==result["total_remote_calls"]==1
    assert result["selection"] is result["execution"] is None
    snapshot=replace(controlled_snapshot(space,{"paths":"rdf_a","people":"rdf_b"}),estimates=())
    result=run_semantic_plans(space,tool,snapshot=snapshot)
    assert not result["success"] and result["total_remote_calls"]==0 and len(calls)==1


def test_snapshot_from_another_data_version_cannot_select_or_execute():
    old=setup(); new=setup(version="toy-v2"); tool,calls=registry(new)
    result=run_semantic_plans(new,tool,snapshot=controlled_snapshot(old,{"paths":"rdf_a","people":"rdf_b"}))
    assert not result["success"] and result["execution"] is None and calls==[]


def test_single_declared_source_does_not_invent_alternative_backends():
    space=setup(replicas=("rdf_a",))
    assert len(space.candidates)==1 and len(space.observation_requests)==2


@pytest.mark.parametrize("options",[{"max_candidates":3},{"max_observation_calls":3}])
def test_finite_budgets_do_not_silently_truncate_the_candidate_space(options):
    with pytest.raises(SemanticProgramError,match="budget"):
        setup(**options)


def test_global_empty_aggregate_cost_keeps_one_output_row():
    space=setup(CASES[4]); tool,_=registry(space)
    result=run_semantic_plans(space,tool)
    assert result["success"]
    assert all(e["node_row_counts"]["count/aggregate"]==1 for e in result["selection"]["estimates"])


def test_expected_answers_are_not_an_input_to_enumeration():
    changed=deepcopy(CASES[0]); changed["expected_rows"]=[{"wrong":True}]
    assert [c.plan.to_dict() for c in setup(changed).candidates]==[c.plan.to_dict() for c in setup().candidates]


def test_plugin_exception_keeps_attempt_count_and_skips_dependents():
    space=setup(CASES[3]); tool,calls=registry(space)
    attempts=[]
    def raised(_artifact):
        attempts.append("rdf_a")
        raise RuntimeError("plugin crashed before returning a report")
    tool.backends._plugins["rdf_a"].client.execute=raised
    result=run_semantic_plans(space,tool,snapshot=controlled_snapshot(space,{"paths":"rdf_a","people":"rdf_a"}))
    assert not result["success"] and result["total_remote_calls"]==1 and attempts==["rdf_a"]
    assert calls==[]
    nodes=result["execution"]["value"]["node_results"]
    assert sum(n["status"]=="error" for n in nodes)==1
    assert all(n["status"] in ("error","skipped") for n in nodes)
    assert any("plugin crashed" in (n["error"] or "") for n in nodes)


def test_unsupported_replica_is_recorded_without_discarding_supported_placements(monkeypatch):
    from xgap.compilers.errors import CompilerError
    import xgap.runtime.semantic_planning as module
    original=module.compile_semantic_program
    def compile_supported(program,**options):
        if "rdf_a" in options["source_bindings"].values():
            raise CompilerError("controlled unavailable backend capability")
        return original(program,**options)
    monkeypatch.setattr(module,"compile_semantic_program",compile_supported)
    space=setup()
    assert len(space.candidates)==1 and len(space.rejected_placements)==3
    assert len(space.observation_requests)==2
    assert all(request.backend_id=="rdf_b" for request in space.observation_requests)
