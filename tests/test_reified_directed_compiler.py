"""Execute production SPARQL over the frozen toy graph; never use canned rows."""

from dataclasses import replace
import json

import pytest

from xgap.algebra.conditions import EdgeRef, PropertyEquals
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.rdf_terms import RDF_TERMS_V1
from xgap.compilers import UnsupportedCompilationError
from xgap.compilers.directed import compile_directed_rows
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.experiments.toy_backbone import (
    DEFAULT_FIXTURE, DIRECTED_TOY_QUERY_IDS, execute_directed_toy_case,
    load_fixture, toy_rdf_edge_encoding,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern.ast import Direction, EdgePattern, NodePattern, Rel, Seq


_, CASES, MAPPING = load_fixture()
BY_ID = {case["id"]: case for case in CASES}
ENCODING = toy_rdf_edge_encoding(MAPPING)
NS = MAPPING["backends"]["fuseki"]["namespace"]


@pytest.fixture
def rdf():
    return pytest.importorskip("rdflib", minversion="7.1.4")


@pytest.fixture
def graph(rdf):
    return rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")


def pattern(query_id="T02"):
    return parse_path_pattern_query(BY_ID[query_id]["gold_path_pattern_query"])


def compile_rdf(value, encoding=ENCODING, **kwargs):
    return compile_directed_rows(value, backend_id="fuseki", backend_mapping=MAPPING,
                                 rdf_edge_encoding=encoding, **kwargs)


def paths(graph, artifact):
    count = len(artifact.parameters["directions"])
    columns = ["n0"]
    for i in range(1, count + 1):
        columns.extend((f"e{i}", f"n{i}"))
    return sorted({"/".join(str(row[c]).removeprefix(NS) for c in columns)
                   for row in graph.query(artifact.text)})


@pytest.mark.parametrize("query_id", DIRECTED_TOY_QUERY_IDS)
def test_all_supported_toy_cases_through_compiler_client_and_scheduler(query_id, graph):
    class IndependentRDF(FusekiClient):
        def _post_query(self, query):
            return json.loads(graph.query(query).serialize(format="json"))

    client = IndependentRDF(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))
    result = execute_directed_toy_case(BY_ID[query_id], MAPPING, client=client)
    assert result["success"], result
    assert result["runtime"]["total_remote_calls"] == 1
    assert result["artifact"]["parameters"]["rdf_edge_identity"] == "resource_iri"
    assert result["artifact"]["parameters"]["rdf_result_encoding"] == RDF_TERMS_V1


def test_plain_rdf_is_unchanged_and_reification_preserves_parallel_edges(graph):
    old = compile_rdf(pattern("T03"), None)
    new = compile_rdf(pattern("T03"))
    assert len(list(graph.query(old.text))) == 2
    assert "rdf_result_encoding" not in old.parameters
    assert "rdf_edge_encoding_sha256" not in old.parameters
    assert paths(graph, new) == ["a/e1/b", "a/e4/c", "a/e7/b"]
    assert "predicate IRIs" in old.parameters["semantic_assumptions"][3]
    assert "edge-resource IRIs" in new.parameters["semantic_assumptions"][3]


def test_mixed_direction_allows_reusing_one_edge(graph):
    value = replace(pattern(), source=NodePattern(properties={"id": "b"}),
        expr=Seq(Rel(EdgePattern(label="KNOWS", direction=Direction.IN)),
                 Rel(EdgePattern(label="KNOWS"))))
    assert paths(graph, compile_rdf(value)) == [
        "b/e1/a/e1/b", "b/e1/a/e4/c", "b/e1/a/e7/b",
        "b/e7/a/e1/b", "b/e7/a/e4/c", "b/e7/a/e7/b",
    ]


def test_self_loop_can_repeat_in_fixed_walk(graph):
    value = replace(pattern("T05"), source=NodePattern(properties={"id": "d"}))
    assert paths(graph, compile_rdf(value)) == ["d/e6/d/e6/d"]


def test_edge_property_filter_uses_edge_resource_not_node_or_predicate(graph):
    value = replace(pattern("T05"), condition=PropertyEquals(EdgeRef(1), "id", "e7"))
    assert paths(graph, compile_rdf(value)) == ["a/e7/b/e2/c", "a/e7/b/e8/d"]
    # Node ID optimization and edge ID properties are separate contracts.
    nodes = RdfRowEncoding("toy-node-iri", ENCODING.class_predicate_iri, "id", NS)
    assert paths(graph, compile_rdf(value, rdf_encoding=nodes)) == [
        "a/e7/b/e2/c", "a/e7/b/e8/d"]
    with pytest.raises(UnsupportedCompilationError, match="reification"):
        compile_rdf(value, None)


def test_unlabeled_edges_exclude_rdf_metadata(graph):
    value = replace(pattern(), expr=Rel(EdgePattern()))
    assert paths(graph, compile_rdf(value)) == BY_ID["T02"]["expected_paths"]


def test_label_term_encoding_is_explicit_and_mapping_is_used(graph, rdf):
    iri_encoding = replace(ENCODING, label_encoding="mapped_iri")
    assert paths(graph, compile_rdf(pattern(), iri_encoding)) == []
    for edge in tuple(graph.subjects(rdf.RDF.type, rdf.URIRef(NS + "Edge"))):
        graph.set((edge, rdf.URIRef(NS + "label"), rdf.URIRef(NS + "KNOWS")))
    assert paths(graph, compile_rdf(pattern(), iri_encoding)) == BY_ID["T02"]["expected_paths"]
    assert paths(graph, compile_rdf(pattern())) == []
    mapped = compile_rdf(pattern(), iri_encoding).parameters["backend_mapping"]["relevant_mapped_iris"]
    assert any(term["iri"] == NS + "KNOWS" for term in mapped)
    assert iri_encoding.identity != ENCODING.identity


def test_edge_schema_change_alters_native_query_and_result(graph):
    reversed_encoding = replace(ENCODING, source_predicate_iri=ENCODING.target_predicate_iri,
                                target_predicate_iri=ENCODING.source_predicate_iri)
    assert paths(graph, compile_rdf(pattern("T03"), reversed_encoding)) == ["a/e3/c"]
    assert reversed_encoding.identity != ENCODING.identity


def test_encoding_validation_and_backend_boundary():
    with pytest.raises(ValueError, match="unsafe"):
        replace(ENCODING, source_predicate_iri="urn:x> ?s ?p ?o")
    with pytest.raises(ValueError, match="labels require"):
        replace(ENCODING, label_encoding="infer")
    with pytest.raises(UnsupportedCompilationError, match="RDF target"):
        compile_directed_rows(pattern(), backend_id="neo4j", rdf_edge_encoding=ENCODING)
    with pytest.raises(UnsupportedCompilationError, match="typed encoding"):
        compile_rdf(pattern(), {})
