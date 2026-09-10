"""Constraint-preserving candidate execution; fixtures are not model predictions."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import runpy

import pytest

from xgap.algebra.conditions import And, LabelEquals, NodeNotEquals, NodeRef, PropertyEquals, PropertyGreaterThan
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.rdf_terms import RdfTerm
from xgap.backends.sparql_bindings import IRI_ROWS_MARKER, bind_sparql_iris
from xgap.experiments.freebase_candidate_compiler import (
    CandidateExecutionUnavailable, ExecutionRequirements, FreebaseExecutionMapping, NS,
    compile_candidate_execution,
)
from xgap.experiments.freebase_candidate_execution import _CheckedClient, execute_candidate, prepare_candidate_batch
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from xgap.llm.schemas import PlannerRequest
from xgap.pattern.ast import Direction, EdgePattern, NodePattern, PathMode, PathPatternQuery, Rel, Selector, SelectorKind, Seq
from xgap.runtime import FederatedScheduler, RuntimeNode, RuntimeNodeKind


MAPPING = FreebaseExecutionMapping("test-only", "a"*64, {"p.score": "numeric", "p.tag": "string"})


def query(condition=None, *, direction=Direction.OUT, anchor="m.p1", target=None):
    return PathPatternQuery(None, NodePattern(properties={} if anchor is None else {"type.object.id": anchor}),
        Rel(EdgePattern(label="r.author", direction=direction)), target or NodePattern(),
        Selector(SelectorKind.ALL), PathMode.WALK, condition=condition)


def compile_(pattern, *, require=True, answer="last", max_rows=20, max_bytes=8192, mapping=MAPPING):
    return compile_candidate_execution(pattern, mapping, ExecutionRequirements(require, answer),
                                       max_rows=max_rows, max_binding_bytes=max_bytes)


class RdfEngine(FusekiClient):
    def __init__(self, graph):
        super().__init__(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))
        self.graph, self.calls = graph, []

    def _post_query(self, text):
        self.calls.append(text)
        return json.loads(self.graph.query(text).serialize(format="json"))


class Paths:
    backend_id = "neo4j"

    def __init__(self, paths, *, answer=-1, fail=False):
        self.paths, self.answer, self.fail, self.calls = paths, answer, fail, []

    def execute(self, artifact):
        self.calls.append(artifact)
        rows = [{**{f"n{i}": NS+v for i, v in enumerate(path)},
                 "answer": RdfTerm("uri", NS+path[self.answer]).to_binding()} for path in self.paths]
        return ExecutionReport("neo4j", artifact.artifact_id, "cypher", not self.fail,
                               rows=rows, error="unavailable" if self.fail else None)


@pytest.fixture
def graph():
    rdflib = pytest.importorskip("rdflib")
    return rdflib.Graph().parse(data=f'''@prefix f: <{NS}> .
      f:m.p1 f:r.author f:m.a1 ; f:p.score 2025 ; f:p.tag "yes" ; f:type.object.type f:t.paper .
      f:m.p2 f:r.author f:m.a2 ; f:p.score 2020 ; f:p.tag "no" .
      f:m.a1 f:r.affiliation f:m.u ; f:p.score 1 ; f:type.object.type f:t.person .
      f:m.a2 f:r.affiliation f:m.u ; f:p.score 3 .
      f:m.decoy f:r.author "not a resource" .
    ''', format="turtle")


@pytest.mark.parametrize("direction,anchor,path,answer", [
    (Direction.OUT, "m.p1", ("m.p1", "m.a1"), "last"),
    (Direction.IN, "m.a1", ("m.a1", "m.p1"), "last"),
    (Direction.OUT, "m.p1", ("m.p1", "m.a1"), 1),
])
def test_anchored_resource_projection_matches_independent_rdf(graph, direction, anchor, path, answer):
    program = compile_(query(direction=direction, anchor=anchor), answer=answer)
    neo = Paths([path], answer=0 if answer == 1 else -1)
    rdf = RdfEngine(graph)
    result = execute_candidate(program, neo4j=neo, fuseki=rdf)
    assert result["success"] and result["answer_count"] == 1
    assert len(neo.calls) == len(rdf.calls) == 1  # Resource-only execution plus separate baseline.
    assert result["federated"]["total_remote_calls"] == 1


def test_intermediate_numeric_constraint_with_two_hops_and_types(graph):
    # University <- person <- paper, with person type and paper year preserved.
    expression = Seq(Rel(EdgePattern(label="r.affiliation", direction=Direction.IN)),
                     Rel(EdgePattern(label="r.author", direction=Direction.IN)))
    pattern = replace(query(anchor="m.u"), expr=expression, target=NodePattern(label="t.paper"),
        condition=And(LabelEquals(NodeRef(2), "t.person"), PropertyGreaterThan(NodeRef(3), "p.score", 2023),
                      NodeNotEquals(NodeRef(1), NodeRef(3))))
    program = compile_(pattern)
    rdf = RdfEngine(graph)
    result = execute_candidate(program, neo4j=Paths([("m.u", "m.a1", "m.p1")]), fuseki=rdf)
    assert result["success"] and result["answers"] == [RdfTerm("uri", NS+"m.p1").to_binding()]
    assert result["federated"]["total_remote_calls"] == 3 and len(rdf.calls) == 3
    assert "VALUES (?n0 ?n1 ?n2)" in rdf.calls[0]


def test_correlated_rows_do_not_create_cross_path_answers(graph):
    pattern = query(And(PropertyEquals(NodeRef(1), "p.tag", "yes"),
                        PropertyGreaterThan(NodeRef(2), "p.score", 2)), anchor=None)
    result = execute_candidate(compile_(pattern, require=False),
        neo4j=Paths([("m.p1", "m.a1"), ("m.p2", "m.a2")]), fuseki=RdfEngine(graph))
    assert result["success"] and result["answer_count"] == 0


@pytest.mark.parametrize("literal", ['2024', '"wrong"', '"NaN"^^xsd:double', '"INF"^^xsd:double',
                                    '"broken"^^xsd:integer', '<http://example.org/iri>'])
def test_scalar_contract_rejects_multivalue_wrong_type_nonfinite_and_invalid_lexical(graph, literal):
    rdflib = pytest.importorskip("rdflib")
    subject, predicate = rdflib.URIRef(NS+"m.p1"), rdflib.URIRef(NS+"p.score")
    if literal != '2024':
        graph.remove((subject, predicate, None))
    graph.parse(data=f'@prefix xsd: <http://www.w3.org/2001/XMLSchema#> . <{subject}> <{predicate}> {literal} .', format="turtle")
    rdf = RdfEngine(graph)
    result = execute_candidate(compile_(query(PropertyGreaterThan(NodeRef(1), "p.score", 2023))),
                               neo4j=Paths([("m.p1", "m.a1")]), fuseki=rdf)
    assert not result["success"] and not result["federated"]["success"]
    assert "baseline" not in result and len(rdf.calls) == 1
    assert result["federated_executions"][-1]["success"]  # Preserve the actual native report.


def test_missing_scalar_means_no_match_and_does_not_invent_value(graph):
    rdflib = pytest.importorskip("rdflib")
    graph.remove((rdflib.URIRef(NS+"m.p1"), rdflib.URIRef(NS+"p.score"), None))
    result = execute_candidate(compile_(query(PropertyGreaterThan(NodeRef(1), "p.score", 2023))),
                               neo4j=Paths([("m.p1", "m.a1")]), fuseki=RdfEngine(graph))
    assert result["success"] and result["answer_count"] == 0


def test_empty_resource_paths_short_circuit_bound_calls(graph):
    result = execute_candidate(compile_(query(PropertyGreaterThan(NodeRef(2), "p.score", 2), anchor="m.absent")),
                               neo4j=Paths([]), fuseki=RdfEngine(graph))
    assert result["success"] and result["answer_count"] == 0


@pytest.mark.parametrize("value,datatype,kind", [(True, "boolean", "boolean"), (2025.0, "double", "numeric")])
def test_scalar_boolean_and_numeric_equality(graph, value, datatype, kind):
    rdflib = pytest.importorskip("rdflib")
    graph.add((rdflib.URIRef(NS+"m.p1"), rdflib.URIRef(NS+"p.extra"),
               rdflib.Literal(value, datatype=rdflib.URIRef("http://www.w3.org/2001/XMLSchema#"+datatype))))
    mapping = FreebaseExecutionMapping("typed-test", "a"*64, {"p.extra": kind})
    result = execute_candidate(compile_(query(PropertyEquals(NodeRef(1), "p.extra", value)), mapping=mapping),
                               neo4j=Paths([("m.p1", "m.a1")]), fuseki=RdfEngine(graph))
    assert result["success"] and result["answer_count"] == 1


@pytest.mark.parametrize("mode", ["backend", "overflow", "binding-bytes"])
def test_failures_do_not_become_empty_answers(graph, mode):
    program = compile_(query(PropertyGreaterThan(NodeRef(1), "p.score", 2023)),
                       max_rows=1 if mode == "overflow" else 20, max_bytes=1 if mode == "binding-bytes" else 8192)
    paths = [("m.p1", "m.a1"), ("m.p2", "m.a2")] if mode == "overflow" else [("m.p1", "m.a1")]
    result = execute_candidate(program, neo4j=Paths(paths, fail=mode == "backend"), fuseki=RdfEngine(graph))
    assert not result["success"] and "baseline" not in result


@pytest.mark.parametrize("mode,code", [("unanchored", "required_entity_anchor_missing"),
    ("implicit-simple", "implicit_restrictor"), ("trail", "implicit_restrictor"),
    ("required-binding", "required_entity_binding_missing"), ("scalar-mapping", "scalar_encoding_undeclared"),
    ("answer-position", "answer_position")])
def test_refuses_semantic_approximation(mode, code):
    pattern, requirements = query(), ExecutionRequirements(True)
    if mode == "unanchored": pattern = query(anchor=None)
    if mode == "implicit-simple": pattern = replace(pattern, restrictor=PathMode.SIMPLE)
    if mode == "trail": pattern = replace(pattern, restrictor=PathMode.TRAIL)
    if mode == "required-binding": requirements = ExecutionRequirements(True, required_bindings=((1,"m.other"),))
    if mode == "scalar-mapping": pattern = query(PropertyEquals(NodeRef(1), "p.unknown", "x"))
    if mode == "answer-position": requirements = ExecutionRequirements(True, 3)
    with pytest.raises(CandidateExecutionUnavailable) as caught:
        compile_candidate_execution(pattern, MAPPING, requirements, max_rows=20, max_binding_bytes=8192)
    assert caught.value.code == code


def row_parameters(rows):
    return {"sparql_iri_rows": {"parameter": "rows", "columns": ["a", "b"], "max_bindings": 8, "max_bytes": 8192}, "rows": rows}


def test_correlated_binding_preserves_pairs_deduplication_and_empty():
    rows = [{"a": NS+"a", "b": NS+"b"}, {"a": NS+"c", "b": NS+"d"}]
    bound = bind_sparql_iris(IRI_ROWS_MARKER, row_parameters(rows+rows))
    assert bound == f"VALUES (?a ?b) {{ (<{NS}a> <{NS}b>) (<{NS}c> <{NS}d>) }}"
    assert bind_sparql_iris(IRI_ROWS_MARKER, row_parameters([])) == "VALUES (?a ?b) {  }"


@pytest.mark.parametrize("mode", ["non-iri", "missing", "extra", "duplicate-column", "unhashable-column", "rows-overflow", "bytes", "profile-conflict"])
def test_malformed_correlated_bindings_fail(mode):
    params = row_parameters([{"a": NS+"a", "b": NS+"b"}])
    if mode == "non-iri": params["rows"][0]["b"] = "x> } UNION {}"
    if mode == "missing": del params["rows"][0]["b"]
    if mode == "extra": params["rows"][0]["c"] = NS+"c"
    if mode == "duplicate-column": params["sparql_iri_rows"]["columns"] = ["a", "a"]
    if mode == "unhashable-column": params["sparql_iri_rows"]["columns"] = [{}]
    if mode == "rows-overflow": params["rows"] *= 9
    if mode == "bytes": params["sparql_iri_rows"]["max_bytes"] = 1
    if mode == "profile-conflict": params["sparql_iri_binding"] = {}
    with pytest.raises(ValueError): bind_sparql_iris(IRI_ROWS_MARKER, params)


@pytest.mark.parametrize("mode", ["ok", "missing", "nan", "conflict", "duplicate", "overflow", "overwrite"])
def test_scheduler_binds_whole_rows_and_rejects_invalid_inputs(mode):
    params = {"bind_fields": ["a", "b"], "parameter": "rows", "max_bindings": 3}
    artifact = QueryArtifact("binding", "sparql", IRI_ROWS_MARKER).to_dict()
    rows = ({"a": "one", "b": "two", "unused": 0}, {"a": "three", "b": "four"})
    if mode == "missing": rows[0].pop("b")
    if mode == "nan": rows[0]["b"] = float("nan")
    if mode == "conflict": params["bind_field"] = "a"
    if mode == "duplicate": params["bind_fields"] = ["a", "a"]
    if mode == "overflow": params["max_bindings"] = 1
    if mode == "overwrite": artifact["parameters"] = {"rows": []}
    node = RuntimeNode("bind", RuntimeNodeKind.REMOTE_BIND_QUERY, ("input",), parameters=params)
    if mode == "ok":
        bound, count = FederatedScheduler._bind_artifact(node, artifact, rows+rows)
        assert count == 2 and bound["parameters"]["rows"] == [{"a":"one","b":"two"}, {"a":"three","b":"four"}]
    else:
        with pytest.raises(ValueError): FederatedScheduler._bind_artifact(node, artifact, rows)


def grounded_fixture():
    from xgap.experiments.runtime_alignment import RetrievedOntologyTerm
    helpers = runpy.run_path(str(Path(__file__).with_name("test_m13e3b4_relation_endpoint_grounding.py")))
    view = helpers["_prompt_view"]()
    view = replace(view, entities=({"entity_id": "m.p1"},), terms=(*view.terms,
        RetrievedOntologyTerm("type.target", "class", "type.target", (), 1.0, ("fixture",))))
    raw = helpers["_grounded_raw"](target_type="type.target")
    candidate = raw["candidates"][0]
    candidate["grounding"]["entity_ids"] = ["m.p1"]
    request = PlannerRequest("Explicit fixture question", metadata={"task_id": view.task_id, "prompt_schema_view": view.to_dict()})
    return raw, request, view


def test_actual_ast_anchor_required_even_with_declaration_and_good_sibling_retained():
    raw, request, view = grounded_fixture()
    good = deepcopy(raw["candidates"][0])
    good["candidate_id"] = "anchored"
    good["pattern_query"]["source"]["properties"] = {"type.object.id": "m.p1"}
    raw["candidates"].append(good)
    before = deepcopy(raw)
    batch = prepare_candidate_batch(raw, request, view, MAPPING, ExecutionRequirements(True), max_rows=20, max_binding_bytes=8192)
    assert raw == before and list(batch.programs) == ["anchored"]
    assert batch.evidence["candidates"][0]["code"] == "required_entity_anchor_missing"
    assert batch.evidence["candidates"][1]["stage"] == "prepared"
    assert batch.evidence["candidates"][0]["semantic_validation"]["ok"]


def test_entire_malformed_envelope_remains_visible():
    raw, request, view = grounded_fixture()
    raw["candidates"][0]["pattern_query"]["source"] = None
    batch = prepare_candidate_batch(raw, request, view, MAPPING, ExecutionRequirements(True), max_rows=20, max_binding_bytes=8192)
    assert not batch.programs and len(batch.evidence["candidates"]) == 1
    assert batch.evidence["failure"]["stage"] == "normalized_parser_rejected"


@pytest.mark.parametrize("mode", ["lost-row", "missing-flag", "wrong-flag"])
def test_guard_cannot_silently_drop_rows(mode):
    program = compile_(query(PropertyGreaterThan(NodeRef(1), "p.score", 2023)))
    artifact = QueryArtifact.from_dict(next(n for n in program.plan.nodes if n.node_id == "scalar-contract").parameters["artifact"])
    artifact = replace(artifact, parameters={**artifact.parameters, "path_rows": [{"n0": NS+"m.p1", "n1": NS+"m.a1"}]})
    row = {"n0": RdfTerm("uri",NS+"m.p1").to_binding(), "n1": RdfTerm("uri",NS+"m.a1").to_binding(),
           "invalid": RdfTerm("literal","false",datatype="http://www.w3.org/2001/XMLSchema#boolean").to_binding()}
    if mode == "missing-flag": del row["invalid"]
    if mode == "wrong-flag": row["invalid"] = RdfTerm("literal","false").to_binding()
    class BrokenGuard:
        backend_id = "fuseki"
        def execute(self, artifact):
            return ExecutionReport("fuseki", artifact.artifact_id,"sparql",True,rows=[] if mode == "lost-row" else [row])
    assert not _CheckedClient(BrokenGuard(),20).execute(artifact).success
