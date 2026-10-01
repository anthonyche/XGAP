"""Requirements restrict executable placements without changing query meaning."""

from copy import deepcopy
from dataclasses import replace
import json
import threading

import pytest

from xgap.backends.capabilities import SupportLevel
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.errors import CompilerError
from xgap.compilers.features import default_profile
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE, load_fixture
from xgap.experiments.toy_capabilities import load_capability_cases
from xgap.experiments.toy_semantic import load_semantic_cases, toy_backends
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans, run_semantic_plans
from xgap.semantic.program import SemanticGraphProgram, SemanticProgramError
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin


_, _, MAPPING = load_fixture()
CASES = load_capability_cases()


def enumerate_case(case, replicas=("neo4j", "fuseki")):
    return enumerate_semantic_plans(SemanticGraphProgram.from_dict(case["program"]),
        operator_sources={op: "toy" for op in case["source_bindings"]},
        sources={"toy": LogicalSource("toy", "frozen-v1", replicas)}, backends=toy_backends(MAPPING))


def canonical(items):
    return sorted(json.dumps(item, sort_keys=True) for item in items)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_exact_placement_admission_and_owned_witnesses(case):
    space = enumerate_case(case)
    assert canonical([c.plan.metadata["source_bindings"] for c in space.candidates]) == canonical(case["expected_placements"])
    assert len(space.rejected_placements) == 2 ** len(case["source_bindings"]) - len(space.candidates)
    assert all("unsatisfied capabilities" in r["reason"] for r in space.rejected_placements)
    for candidate in space.candidates:
        plan = candidate.plan
        nodes = {n.node_id: n for n in plan.nodes}
        admission = plan.metadata["capability_admission"]
        requested = {op["operator_id"]: op["required_capabilities"] for op in case["program"]["operators"]
                     if op["required_capabilities"]}
        assert set(admission["operators"]) == set(requested)
        for owner, record in admission["operators"].items():
            assert record["required"] == requested[owner]
            assert set(record["witnesses"]) == set(requested[owner])
            assert all(owner in nodes[node_id].semantic_operator_ids
                       for witnesses in record["witnesses"].values() for node_id in witnesses)
    # No artifact from rejected-only placements is registered for observation.
    admitted_backends = {backend for p in case["expected_placements"] for backend in p.values()}
    assert set(space.observation_catalogs) == admitted_backends
    direct = compile_semantic_program(SemanticGraphProgram.from_dict(case["program"]),
        source_bindings=case["expected_placements"][0], backends=toy_backends(MAPPING))
    actual_stages = {op: [n.kind.value for n in direct.nodes if op in n.semantic_operator_ids]
                     for op in case["expected_runtime_operators"]}
    assert actual_stages == case["expected_runtime_operators"]


@pytest.mark.parametrize("case", [CASES[i] for i in (1, 3, 4, 6)], ids=lambda c: c["id"])
def test_admitted_requirements_continue_through_observe_select_and_rdf_execution(case):
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")
    calls, lock = [], threading.Lock()
    class Client(FusekiClient):
        def _post_query(self, text):
            calls.append(text)
            with lock:
                return json.loads(graph.query(text).serialize(format="json"))
    space = enumerate_case(case, ("fuseki",))
    plugins = BackendPluginRegistry()
    plugins.register(CatalogBackendPlugin("fuseki", Client(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf")),
                                         space.observation_catalogs["fuseki"]))
    run = run_semantic_plans(space, BackendInvokeTool(plugins))
    assert run["success"], run
    rows = run["execution"]["value"]["final_rows"]
    assert (rows == case["expected_rows"] if case["ordered"] else canonical(rows) == canonical(case["expected_rows"]))
    assert run["total_remote_calls"] == len(calls) == 2 * case["expected_remote_calls"]
    assert run["selected_plan"]["metadata"]["capability_admission"]["operators"]


@pytest.mark.parametrize("requirements", [
    ["native.cypher"], ["property_graph.read"], ["coordinator.join"],
    ["coordinator.filter"], ["unknown.feature"], ["native.sparql", "native.cypher"],
])
def test_requirement_cannot_borrow_from_another_operator_or_backend(requirements):
    case = deepcopy(CASES[3])
    case["program"]["operators"][0]["required_capabilities"] = requirements
    with pytest.raises(SemanticProgramError, match="Operator 'people' has unsatisfied capabilities"):
        enumerate_case(case, ("fuseki",))


def test_known_native_requirement_does_not_override_compiler_capability_rejection():
    case = CASES[4]
    profile = default_profile("fuseki")
    feature = profile.features["path_algebra.Nodes"]
    profile = replace(profile, features={**profile.features,
        "path_algebra.Nodes": replace(feature, level=SupportLevel.UNSUPPORTED)})
    backends = toy_backends(MAPPING)
    backends["fuseki"] = replace(backends["fuseki"], profile=profile)
    with pytest.raises(CompilerError):
        compile_semantic_program(SemanticGraphProgram.from_dict(case["program"]),
            source_bindings={"people": "fuseki"}, backends=backends)


def test_read_model_requirement_checks_declared_model_as_well_as_language():
    backends = toy_backends(MAPPING)
    backends["fuseki"] = replace(backends["fuseki"],
        profile=replace(default_profile("fuseki"), data_model="other_model"))
    with pytest.raises(SemanticProgramError, match="rdf_graph.read"):
        compile_semantic_program(SemanticGraphProgram.from_dict(CASES[4]["program"]),
            source_bindings={"people": "fuseki"}, backends=backends)


@pytest.mark.parametrize("requirements", [[""], [" "], [1], [None], [[]], "native.cypher", ["x", "x"]])
def test_malformed_requirement_names_rejected(requirements):
    op = SemanticGraphProgram.from_dict(CASES[0]["program"]).operators[0]
    with pytest.raises(SemanticProgramError):
        replace(op, required_capabilities=requirements)


def test_no_requirements_keep_existing_metadata_and_frozen_fixture():
    original = load_semantic_cases()[0]
    assert all(not op.get("required_capabilities") for op in original["program"]["operators"])
    plan = compile_semantic_program(SemanticGraphProgram.from_dict(original["program"]),
        source_bindings=original["source_bindings"], backends=toy_backends(MAPPING))
    assert "capability_admission" not in plan.metadata
