"""Independent orientation witnesses and algebra laws on the frozen tiny graph."""

import json

import pytest

from xgap.algebra import (EdgesOp, NodesOp, ReverseOp, JoinOp, UnionOp, Path, PathSet,
    GroupByOp, evaluate)
from xgap.algebra.conditions import EdgeRef, NodeRef, PropertyEquals
from xgap.algebra.ops import GroupKey, SelectionOp, RecursiveOp, RecursiveMode
from xgap.algebra.validation import ValidationError, validate_plan
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers import compile_cypher, compile_sparql, UnsupportedCompilationError
from xgap.experiments.toy_backbone import (DEFAULT_FIXTURE, check_reference, execute_bounded_toy_case,
    load_fixture, property_graph)
from xgap.experiments.toy_orientation import FIXTURE, load_orientation_cases, logical_expectations
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.pattern.ast import Direction, EdgePattern, Rel


DATA, ORIGINAL, MAPPING = load_fixture()
CASES = load_orientation_cases()


class RDF(FusekiClient):
    def __init__(self):
        super().__init__(BackendDescriptor("fuseki","fuseki","sparql","rdf"))
        rdf=pytest.importorskip("rdflib",minversion="7.1.4")
        self.graph=rdf.Graph().parse(DEFAULT_FIXTURE/"load.ttl",format="turtle")
    def _post_query(self,text):
        return json.loads(self.graph.query(text).serialize(format="json"))


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_direction_chain_logical_reference_and_independent_rdf_agree(case):
    row=check_reference(case,property_graph(DATA))
    assert row["logical_plan_passed"] and row["reference_passed"],row
    rdf=RDF()
    actual=sorted({str(row[0]) for row in rdf.graph.query((FIXTURE/case["reference_target_queries"]["fuseki"]).read_text())})
    assert actual==case["expected_paths"]
    result=execute_bounded_toy_case(case,MAPPING,client=rdf)
    assert result["success"],result


def test_t15_has_new_explicit_logical_expectation_and_unchanged_original_gold():
    case=ORIGINAL[14];graph=property_graph(DATA)
    old=check_reference(case,graph)
    assert old["reference_passed"] and not old["logical_plan_passed"]
    assert case["expected_logical_plan"].startswith("semantic.Traverse")
    current=check_reference(case,graph,expected_logical_plan=logical_expectations()["T15"])
    assert current["reference_passed"] and current["logical_plan_passed"]
    assert current["actual_paths"]==["b/e1/a","b/e7/a"]


def test_reverse_preserves_stored_edge_identity_and_properties():
    graph=property_graph(DATA)
    chosen=SelectionOp(PropertyEquals(EdgeRef(1),"id","e1"),EdgesOp())
    backward=ReverseOp(chosen)
    assert evaluate(chosen,graph)==PathSet([Path(("a","e1","b"))])
    assert evaluate(backward,graph)==PathSet([Path(("b","e1","a"))])
    assert (graph.edge_source("e1"),graph.edge_target("e1"))==("a","b")
    assert evaluate(SelectionOp(PropertyEquals(NodeRef.first(),"age",22),backward),graph)==evaluate(backward,graph)


def test_reverse_is_involutive_distributes_over_union_and_reverses_join_order():
    graph=property_graph(DATA)
    a=SelectionOp(PropertyEquals(EdgeRef(1),"id","e1"),EdgesOp())
    b=SelectionOp(PropertyEquals(EdgeRef(1),"id","e2"),EdgesOp())
    assert evaluate(ReverseOp(NodesOp()),graph)==evaluate(NodesOp(),graph)
    assert evaluate(ReverseOp(ReverseOp(EdgesOp())),graph)==evaluate(EdgesOp(),graph)
    assert evaluate(ReverseOp(UnionOp(a,b)),graph)==evaluate(UnionOp(ReverseOp(a),ReverseOp(b)),graph)
    reversed_join=evaluate(ReverseOp(JoinOp(a,b)),graph)
    assert reversed_join==PathSet([Path(("c","e2","b","e1","a"))])
    assert reversed_join==evaluate(JoinOp(ReverseOp(b),ReverseOp(a)),graph)


def test_reverse_requires_pathset_and_m9_never_treats_it_as_forward():
    with pytest.raises(ValidationError,match="PATH_SET"):
        validate_plan(ReverseOp(GroupByOp(EdgesOp(),GroupKey.NONE)))
    with pytest.raises(TypeError,match="PathSet"):
        evaluate(ReverseOp(GroupByOp(EdgesOp(),GroupKey.NONE)),property_graph(DATA))
    for compile_native in (compile_cypher,lambda p:compile_sparql(p,backend_mapping=MAPPING)):
        with pytest.raises(UnsupportedCompilationError,match="Reverse"):
            compile_native(ReverseOp(EdgesOp()))


@pytest.mark.parametrize("mode",list(RecursiveMode))
def test_orientation_reversal_preserves_each_recursive_mode(mode):
    graph=property_graph(DATA)
    forward=RecursiveOp(EdgesOp(),mode,max_depth=3)
    backward=RecursiveOp(ReverseOp(EdgesOp()),mode,max_depth=3)
    assert evaluate(ReverseOp(forward),graph)==evaluate(backward,graph)


def test_undirected_expansion_obeys_existing_branch_budget():
    from xgap.compilers.bounded_paths import _alternatives
    expr=Rel(EdgePattern(direction=Direction.UNDIRECTED))
    with pytest.raises(ValueError,match="budget"):
        _alternatives(expr,1)
    branches=_alternatives(expr,2)
    assert {b[0].direction for b in branches}=={Direction.OUT,Direction.IN}
