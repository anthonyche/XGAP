"""Total Boolean truth, independent gold chains and normal semantic placement."""

from dataclasses import replace
import json
import threading

import pytest

from xgap.algebra.conditions import (And, Or, Not, EdgeRef, NodeRef, PropertyEquals,
    PropertyNotEquals, PropertyGreaterThan, LabelEquals, LengthEquals)
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.bounded_paths import _shortest_condition
from xgap.compilers.directed import compile_directed_rows
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.compilers.features import default_profile
from xgap.compilers.node_match import compile_node_match
from xgap.experiments.toy_backbone import check_reference, load_fixture, property_graph
from xgap.experiments.toy_boolean import FIXTURE, execute_boolean_case, load_boolean_matches
from xgap.experiments.toy_semantic import execute_semantic_case, toy_backends, wrap_path_case
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern.ast import NodePattern
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans, run_semantic_plans
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin


DATA, CASES, MAPPING = load_fixture(FIXTURE)
LOCK = threading.Lock()  # Only RDFLib's shared local parser; live backends stay concurrent.


class RDF(FusekiClient):
    def __init__(self, name="fuseki"):
        super().__init__(BackendDescriptor(name, name, "sparql", "rdf"))
        rdf = pytest.importorskip("rdflib", minversion="7.1.4")
        self.graph = rdf.Graph().parse(FIXTURE / "load.ttl", format="turtle")
        self.calls = 0

    def _post_query(self, text):
        with LOCK:
            self.calls += 1
            return json.loads(self.graph.query(text).serialize(format="json"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_independent_complete_chain_and_semantic_execution(case):
    reference = check_reference(case, property_graph(DATA))
    assert reference["logical_plan_passed"] and reference["reference_passed"], reference
    rdf = RDF()
    independent = sorted({str(row[0]) for row in rdf.graph.query(
        (FIXTURE / case["reference_target_queries"]["fuseki"]).read_text())})
    assert independent == case["expected_paths"]
    actual = execute_boolean_case(case, MAPPING, client=rdf)
    assert actual["success"], actual
    assert rdf.calls == case["expected_remote_calls"]


@pytest.mark.parametrize("case", load_boolean_matches(), ids=lambda c:c["id"])
def test_match_uses_same_total_conditions_and_typed_scalar_outputs(case):
    result = execute_semantic_case(case, MAPPING, clients={"fuseki": RDF()})
    assert result["success"], result


@pytest.mark.parametrize("case", [wrap_path_case(CASES[3], "fuseki"),
    {**wrap_path_case(CASES[13], "fuseki"), "expected_remote_calls": 2},
    load_boolean_matches()[0]], ids=lambda c:c["id"])
def test_boolean_conditions_flow_through_observation_selection_and_serving(case):
    base = toy_backends(MAPPING)["fuseki"]
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    names = ("rdf_a", "rdf_b")
    backends = {name:replace(base, backend_id=name, backend_mapping=replace(mapping,backend_id=name),
        profile=replace(default_profile("fuseki"),backend_id=name)) for name in names}
    program = SemanticGraphProgram.from_dict(case["program"])
    space = enumerate_semantic_plans(program, operator_sources={program.roots[0]:"toy"},
        sources={"toy":LogicalSource("toy","boolean-v1",names)}, backends=backends)
    plugins = BackendPluginRegistry(); clients=[]
    for name,catalog in space.observation_catalogs.items():
        client=RDF(name); clients.append(client)
        plugins.register(CatalogBackendPlugin(name,client,catalog))
    result=run_semantic_plans(space, BackendInvokeTool(plugins))
    assert result["success"], result
    assert result["observation_calls"] == 2 * case["expected_remote_calls"]
    assert result["execution_calls"] == case["expected_remote_calls"]
    canonical=lambda rows:sorted(json.dumps(r,sort_keys=True) for r in rows)
    assert canonical(result["execution"]["value"]["final_rows"]) == canonical(case["expected_rows"])
    assert sum(c.calls for c in clients) == result["observation_calls"] + result["execution_calls"]


def test_shortest_placement_inspects_nested_leaves():
    endpoint=Or(PropertyEquals(NodeRef.first(),"id","a"),Not(LabelEquals(NodeRef.last(),"Ghost")))
    assert _shortest_condition(endpoint) == (endpoint, [])
    assert _shortest_condition(And(endpoint,LengthEquals(2))) == (endpoint,[2])
    for condition in (Not(LengthEquals(2)),Or(endpoint,LengthEquals(2)),
                      Or(endpoint,Not(PropertyEquals(EdgeRef(1),"weight",1)))):
        with pytest.raises(ValueError,match="SHORTEST"):
            _shortest_condition(condition)


@pytest.mark.parametrize("bad", [PropertyEquals(NodeRef.first(),"score",None),
    PropertyEquals(NodeRef.first(),"unsafe\\name",1),
    PropertyEquals(NodeRef.first(),"score",2**64)])
def test_literal_checks_cannot_be_bypassed_inside_or_not(bad):
    query=parse_path_pattern_query(CASES[8]["gold_path_pattern_query"])
    query=replace(query,condition=Or(PropertyEquals(NodeRef.first(),"id","a"),Not(bad)))
    with pytest.raises(UnsupportedCompilationError):
        compile_directed_rows(query,backend_id="neo4j")


def test_edge_conditions_remain_unavailable_without_rdf_edge_identity():
    query=parse_path_pattern_query(CASES[8]["gold_path_pattern_query"])
    with pytest.raises(UnsupportedCompilationError,match="edge reification"):
        compile_directed_rows(query,backend_id="fuseki",backend_mapping=MAPPING)


def test_zero_match_does_not_allow_out_of_range_references_hidden_in_boolean():
    with pytest.raises(ValueError):
        compile_node_match(NodePattern(),{},backend_id="neo4j",
            condition=Not(PropertyEquals(EdgeRef(1),"weight",1)))


@pytest.mark.parametrize("case", load_boolean_matches(), ids=lambda c:c["id"])
def test_independent_match_reference_preserves_scalar_types(case):
    from xgap.experiments.toy_boolean import boolean_match_reference, boolean_match_reference_rows
    rdf=RDF(); result=rdf.execute(boolean_match_reference(case,"fuseki"))
    rows=boolean_match_reference_rows(result,"fuseki")
    canonical=lambda rows:sorted(json.dumps(r,sort_keys=True) for r in rows)
    assert result.success and canonical(rows) == canonical(case["expected_rows"])


@pytest.mark.parametrize("feature", ["condition.boolean_or", "condition.boolean_not", "graph_model.scalar_property_predicates"])
def test_explicit_backend_exclusions_apply_beneath_boolean_nodes(feature):
    from xgap.backends.capabilities import FeatureSupport
    query=parse_path_pattern_query(CASES[8]["gold_path_pattern_query"])
    profile=default_profile("neo4j")
    excluded=FeatureSupport.from_dict(feature,{"level":"unsupported","reason":"explicit test exclusion"})
    profile=replace(profile,features={**profile.features,feature:excluded})
    with pytest.raises(UnsupportedCompilationError,match="required primitive"):
        compile_directed_rows(query,backend_id="neo4j",profile=profile)


def test_variable_position_rejection_is_preserved_before_boolean_or_scoped_compilation():
    from xgap.runtime.bounded_paths import compile_bounded_path_plan
    for case in json.loads((FIXTURE / "rejected.json").read_text()):
        with pytest.raises(ValueError,match="fixed-length"):
            compile_bounded_path_plan(parse_path_pattern_query(case["query"]),
                **toy_backends(MAPPING)["fuseki"].path_options())


@pytest.mark.parametrize("feature", ["path_algebra.Nodes", "path_algebra.Selection"])
def test_match_migration_preserves_explicit_primitive_rejections(feature):
    from xgap.backends.capabilities import SupportLevel
    profile=default_profile("neo4j")
    profile=replace(profile,features={**profile.features,
        feature:replace(profile.features[feature],level=SupportLevel.UNSUPPORTED)})
    with pytest.raises(UnsupportedCompilationError,match="required Match primitive"):
        compile_node_match(NodePattern(),{},backend_id="neo4j",profile=profile,
            condition=Not(PropertyEquals(NodeRef.first(),"score",1)))
