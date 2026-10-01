"""Identity/answer contracts checked against an independent SPARQL engine."""

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs

import pytest

from xgap.algebra.conditions import NodeRef, PropertyEquals, PropertyNotEquals
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.rdf_terms import (
    RdfTerm,
    RDF_TERMS_V1,
    XSD_STRING,
    parse_select_results,
)
from xgap.compilers.directed import compile_directed_rows
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.compilers.rdf_encoding import RdfRowEncoding
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from xgap.pattern.ast import (
    Direction,
    EdgePattern,
    NodePattern,
    PathMode,
    PathPatternQuery,
    Rel,
    Selector,
    SelectorKind,
)
from xgap.runtime.answers import AnswerProjection, exact_answer_match
from xgap.runtime.directed_fragments import DirectedRowFragmentCompiler
from xgap.runtime.fragments import SemanticFragment
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.contracts import RuntimeNode, RuntimeNodeKind


ROOT = Path(__file__).resolve().parents[1]
NS = "http://rdf.freebase.com/ns/"
ENCODING = RdfRowEncoding("freebase-test-v1", NS + "type.object.type", "mid", NS)
MAPPING = {
    "mapping_id": "freebase-test",
    "version": "1",
    "backends": {
        "fuseki": {
            "namespace": NS,
            "compiler_tokens": {
                "node_labels": {"Person": "people.person"},
                "edge_labels": {"parent": "people.person.parents"},
                "properties": {"mid": "type.object.mid"},
            },
        }
    },
    "term_mappings": {
        "fuseki": {
            "people.person": {"kind": "class", "representation": NS + "people.person"},
            "people.person.parents": {
                "kind": "relation",
                "representation": NS + "people.person.parents",
            },
            "type.object.mid": {
                "kind": "property",
                "representation": NS + "type.object.mid",
            },
        }
    },
}


def client():
    return FusekiClient(
        BackendDescriptor.from_yaml(ROOT / "descriptors/backends/fuseki.yaml")
    )


def pattern(direction=Direction.IN):
    return PathPatternQuery(
        None,
        NodePattern(label="Person", properties={"mid": "m.parent"}),
        Rel(EdgePattern(label="parent", direction=direction)),
        NodePattern(),
        Selector(SelectorKind.ALL),
        PathMode.WALK,
    )


def payload(rows, columns=("answer",)):
    return {"head": {"vars": list(columns)}, "results": {"bindings": rows}}


def test_term_identity_does_not_collapse_uri_literal_datatype_or_language():
    terms = [
        RdfTerm("uri", NS + "m.a"),
        RdfTerm("literal", NS + "m.a"),
        RdfTerm("literal", "1"),
        RdfTerm("literal", "1", datatype="urn:integer"),
        RdfTerm("literal", "word", language="EN"),
        RdfTerm("literal", "word", language="fr"),
    ]
    assert len({term.identity for term in terms}) == 6
    assert RdfTerm("literal", "word", language="en") == terms[4]
    assert RdfTerm("literal", "1", datatype=XSD_STRING) == terms[2]
    assert not exact_answer_match(
        [RdfTerm("literal", "01", datatype="urn:integer")], [terms[3]]
    )


def test_coordinator_joins_typed_values_without_lexical_false_match():
    uri = RdfTerm("uri", NS + "m.a").to_binding()
    literal = RdfTerm("literal", NS + "m.a").to_binding()
    node = RuntimeNode(
        "join",
        RuntimeNodeKind.COORDINATOR_JOIN,
        ("left", "right"),
        {"left_on": "key", "right_on": "key"},
    )
    rows = FederatedScheduler._join(
        node,
        ({"key": uri},),
        ({"key": literal, "value": "wrong"}, {"key": uri, "value": "correct"}),
    )
    assert len(rows) == 1 and rows[0]["value"] == "correct"


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"head": {}, "boolean": False},
        payload([], ("answer", "answer")),
        {"head": {"vars": ["answer"]}, "results": {}},
        payload([{"other": {"type": "uri", "value": "urn:x"}}]),
        payload([{"answer": {"type": "uri", "value": "relative"}}]),
        payload([{"answer": {"type": "literal", "value": 1}}]),
        payload([{"answer": {"type": "literal", "value": "x", "datatype": ""}}]),
        payload([{"answer": {"type": "bnode", "value": "same-label"}}]),
    ],
)
def test_malformed_or_unscoped_select_is_not_empty_success(bad):
    with pytest.raises(ValueError):
        parse_select_results(bad, expected_columns=("answer",))


def test_legitimate_empty_and_unbound_are_distinct_from_missing_envelope():
    assert parse_select_results(payload([])) == []
    assert parse_select_results(payload([{}])) == [{}]
    with pytest.raises(ValueError, match="missing"):
        AnswerProjection("answer").project_rows([{}])


def test_failure_and_untyped_legacy_result_never_become_successful_answers():
    report = ExecutionReport("fuseki", "q", "sparql", success=False, rows=[])
    with pytest.raises(ValueError, match="Failed"):
        AnswerProjection("answer").project_execution(report)
    with pytest.raises(ValueError, match="typed"):
        AnswerProjection("answer").project_execution(replace(report, success=True))
    assert (
        AnswerProjection("answer").project_execution(
            replace(
                report, success=True, metadata={"rdf_result_encoding": RDF_TERMS_V1}
            )
        )
        == ()
    )


def test_property_graph_identity_requires_explicit_mapping_and_exact_column():
    projection = AnswerProjection("target", "property_graph_nodes_v1", ENCODING)
    actual = projection.project_rows(
        [{"source": {"mid": "m.other"}, "target": {"mid": "m.child", "name": "Child"}}]
        * 2
    )
    assert actual == (RdfTerm("uri", NS + "m.child"),)
    with pytest.raises(ValueError):
        AnswerProjection("target", "property_graph_nodes_v1")
    with pytest.raises(ValueError):
        projection.project_rows([{"target": {"name": "Child"}}])


def test_client_failure_is_costed_once_and_default_result_mode_is_unchanged(
    monkeypatch,
):
    backend = client()
    calls = []
    monkeypatch.setattr(
        backend,
        "_post_query",
        lambda text: calls.append(text)
        or payload([{"answer": {"type": "bnode", "value": "b1"}}]),
    )
    artifact = QueryArtifact(
        "q",
        "sparql",
        "SELECT ?answer WHERE {}",
        parameters={"rdf_result_encoding": RDF_TERMS_V1},
    )
    report = backend.execute(artifact)
    assert not report.success and "Blank-node" in report.error and len(calls) == 1
    legacy = backend.execute(replace(artifact, parameters={}))
    assert legacy.success and legacy.rows == [{"answer": "b1"}]
    assert len(calls) == 2


@pytest.mark.parametrize("bad", ["m.x> ?s ?p ?o", "m.x%3E", "urn:x", "", 1])
def test_resource_identity_rejects_native_text_and_noncanonical_ids(bad):
    value = replace(pattern(), source=NodePattern(properties={"mid": bad}))
    with pytest.raises((UnsupportedCompilationError, ValueError)):
        compile_directed_rows(
            value, backend_id="fuseki", backend_mapping=MAPPING, rdf_encoding=ENCODING
        )


def test_encoding_is_explicit_and_runtime_propagates_the_response_contract():
    value = pattern()
    legacy = compile_directed_rows(value, backend_id="fuseki", backend_mapping=MAPPING)
    compiler = DirectedRowFragmentCompiler(
        backend_mappings={"fuseki": MAPPING}, rdf_encodings={"fuseki": ENCODING}
    )
    compiled = compiler.compile(
        SemanticFragment("fragment", "fuseki", value, ("traverse",))
    )
    artifact = compiled.artifact
    assert "rdf_result_encoding" not in legacy.parameters
    assert artifact.parameters["rdf_result_encoding"] == RDF_TERMS_V1
    assert artifact.parameters["expected_result_columns"] == list(
        compiled.output_schema
    )
    assert artifact.parameters["rdf_row_encoding_sha256"] == ENCODING.identity
    assert compiled.to_runtime_node().parameters["artifact"] == artifact.to_dict()
    with pytest.raises(UnsupportedCompilationError):
        compile_directed_rows(value, backend_id="neo4j", rdf_encoding=ENCODING)


def test_identity_inequality_excludes_literals_and_unmapped_resources():
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph()
    for target in [
        rdf.URIRef(NS + "m.child"),
        rdf.URIRef("urn:foreign"),
        rdf.Literal("m.child"),
        rdf.URIRef(NS + "bad/id"),
    ]:
        graph.add(
            (
                rdf.URIRef(NS + "m.parent"),
                rdf.URIRef(NS + "people.person.parents"),
                target,
            )
        )
    query = replace(
        pattern(Direction.OUT),
        source=NodePattern(properties={"mid": "m.parent"}),
        condition=PropertyNotEquals(NodeRef("last"), "mid", "m.other"),
    )
    artifact = compile_directed_rows(
        query, backend_id="fuseki", backend_mapping=MAPPING, rdf_encoding=ENCODING
    )
    assert {str(row.target) for row in graph.query(artifact.text)} == {NS + "m.child"}


def test_ntriples_serialization_roundtrips_control_and_supplementary_unicode():
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    term = RdfTerm("literal", '\b\f\n\t"\\𝄞中文', language="EN")
    graph = rdf.Graph().parse(data=f"<urn:s> <urn:p> {term.ntriples()} .", format="nt")
    value = next(graph.objects())
    assert str(value) == term.value and value.language == "en"


def test_compilation_http_execution_and_answer_projection_on_independent_engine():
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph()
    U = lambda name: rdf.URIRef(NS + name)
    graph.add((U("m.child"), U("people.person.parents"), U("m.parent")))
    graph.add((U("m.parent"), U("type.object.type"), U("people.person")))
    # A misleading literal-valued relation must not equal the IRI-bound anchor.
    graph.add((U("m.decoy"), U("people.person.parents"), rdf.Literal(NS + "m.parent")))
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            query = parse_qs(
                self.rfile.read(int(self.headers["Content-Length"])).decode()
            )["query"][0]
            requests.append(query)
            body = graph.query(query).serialize(format="json")
            self.send_response(200)
            self.send_header("Content-Type", "application/sparql-results+json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = client()
        backend.base_url = f"http://127.0.0.1:{server.server_port}"
        artifact = compile_directed_rows(
            pattern(),
            backend_id="fuseki",
            backend_mapping=MAPPING,
            rdf_encoding=ENCODING,
        )
        result = backend.execute(artifact)
        assert result.success, result.error
        answer = AnswerProjection("target").project_execution(result)
        assert exact_answer_match(answer, [RdfTerm("uri", NS + "m.child")])
        assert not exact_answer_match(answer, [RdfTerm("uri", NS + "m.parent")])
        # Same data, impossible identity constraint: a real successful empty answer.
        impossible = replace(
            pattern(), condition=PropertyNotEquals(NodeRef("first"), "mid", "m.parent")
        )
        empty = backend.execute(
            compile_directed_rows(
                impossible,
                backend_id="fuseki",
                backend_mapping=MAPPING,
                rdf_encoding=ENCODING,
            )
        )
        assert empty.success, empty.error
        assert AnswerProjection("target").project_execution(empty) == ()
        assert len(requests) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(
    os.environ.get("XGAP_RUN_RDF_ANSWERS") != "1",
    reason="requires explicitly enabled live Fuseki",
)
def test_live_fuseki_preserves_term_distinctions_without_loading_data():
    artifact = QueryArtifact(
        "rdf-answer-live",
        "sparql",
        'SELECT ?answer WHERE { VALUES ?answer { <urn:same> "urn:same" "word"@en "1"^^<http://www.w3.org/2001/XMLSchema#integer> } }',
        parameters={
            "rdf_result_encoding": RDF_TERMS_V1,
            "expected_result_columns": ["answer"],
        },
    )
    result = client().execute(artifact)
    assert result.success, result.error
    assert len(AnswerProjection("answer").project_execution(result)) == 4
