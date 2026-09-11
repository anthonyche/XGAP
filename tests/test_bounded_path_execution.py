"""The complete toy query set through production native compilation/runtime."""

from dataclasses import replace
import json

import pytest

from xgap.algebra import evaluate
from xgap.algebra.conditions import LengthEquals
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.bounded_paths import compile_bounded_paths
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.experiments.toy_backbone import (DEFAULT_FIXTURE, execute_bounded_toy_case,
    load_fixture, property_graph, toy_rdf_edge_encoding)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern.ast import Alt, EdgePattern, PathMode, Plus, Rel, Selector, SelectorKind, Seq, Star
from xgap.pattern.lowering import lower_path_pattern
from xgap.runtime.path_selection import select_native_paths


DATA, CASES, MAPPING = load_fixture()
NS = MAPPING["backends"]["fuseki"]["namespace"]
OPTIONS = dict(backend_mapping=MAPPING, rdf_edge_encoding=toy_rdf_edge_encoding(MAPPING),
               rdf_node_classes=(NS + "Person",), resource_namespace=NS)


@pytest.fixture
def client():
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")

    class IndependentRDF(FusekiClient):
        def _post_query(self, query):
            return json.loads(graph.query(query).serialize(format="json"))

    return IndependentRDF(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_every_frozen_query_compiles_and_executes_to_its_complete_gold(case, client):
    result = execute_bounded_toy_case(case, MAPPING, client=client)
    assert result["success"], result
    assert result["runtime"]["total_remote_calls"] == 1
    assert result["plan"]["nodes"][-1]["kind"] == "coordinator_path_select"


def execute_pattern(pattern, client):
    artifact = compile_bounded_paths(pattern, backend_id="fuseki", **OPTIONS)
    report = client.execute(artifact)
    assert report.success, report.error
    rows = select_native_paths(report.rows, artifact.parameters["path_selection"])
    return sorted("/".join(row["path"]) for row in rows)


@pytest.mark.parametrize("kind,k", [(SelectorKind.ANY_SHORTEST, None),
    (SelectorKind.SHORTEST_K, 2), (SelectorKind.SHORTEST_K_GROUP, 2)])
def test_remaining_selectors_match_separate_reference_semantics(kind, k, client):
    pattern = replace(parse_path_pattern_query(CASES[6]["gold_path_pattern_query"]),
                      selector=Selector(kind, k))
    expected = sorted("/".join(p.sequence) for p in evaluate(lower_path_pattern(pattern), property_graph(DATA)))
    assert execute_pattern(pattern, client) == expected


def test_shortest_length_filter_stays_above_shortest_not_below(client):
    pattern = replace(parse_path_pattern_query(CASES[10]["gold_path_pattern_query"]),
                      condition=LengthEquals(3))
    assert execute_pattern(pattern, client) == []


def test_star_shortest_retains_zero_paths_and_positive_shortest_cycles(client):
    pattern = parse_path_pattern_query(CASES[10]["gold_path_pattern_query"])
    pattern = replace(pattern, expr=Star(pattern.expr.child))
    expected = sorted(["a", *CASES[10]["expected_paths"]])
    assert execute_pattern(pattern, client) == expected


def test_recursion_depth_counts_child_paths_not_edges(client):
    pattern = parse_path_pattern_query(CASES[6]["gold_path_pattern_query"])
    edge = Rel(EdgePattern(label="KNOWS"))
    pattern = replace(pattern, expr=Plus(Seq(edge, edge)), max_depth=2)
    expected = sorted("/".join(p.sequence) for p in evaluate(lower_path_pattern(pattern), property_graph(DATA)))
    assert execute_pattern(pattern, client) == expected


def test_union_deduplicates_identical_branches_without_collapsing_parallel_edges(client):
    pattern = parse_path_pattern_query(CASES[2]["gold_path_pattern_query"])
    pattern = replace(pattern, expr=Alt(pattern.expr, pattern.expr))
    assert execute_pattern(pattern, client) == CASES[2]["expected_paths"]


def test_bounds_and_nested_scope_fail_before_execution():
    pattern = parse_path_pattern_query(CASES[6]["gold_path_pattern_query"])
    with pytest.raises(UnsupportedCompilationError, match="budget"):
        compile_bounded_paths(pattern, backend_id="fuseki", max_branches=2, **OPTIONS)
    with pytest.raises(UnsupportedCompilationError, match="explicit finite"):
        compile_bounded_paths(replace(pattern, restrictor=PathMode.TRAIL, max_depth=None), backend_id="fuseki", **OPTIONS)
    with pytest.raises(UnsupportedCompilationError, match="nested scoped"):
        compile_bounded_paths(replace(pattern, expr=Plus(pattern.expr), restrictor=PathMode.TRAIL), backend_id="fuseki", **OPTIONS)


def test_missing_native_identity_is_error_not_an_empty_answer():
    parameters = {"language": "cypher", "identity_property": "id", "resource_namespace": NS,
                  "max_edges": 1, "selector": "ALL"}
    with pytest.raises(KeyError):
        select_native_paths([{"length": 1, "n0": {"id": "a"}, "e1": {}, "n1": {"id": "b"}}], parameters)
