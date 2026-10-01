"""Match row constraints run on normalized RDF bindings, without path conversion."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from test_question_interpretation import CASES, ControlledProvider, question_run
from test_semantic_planning import MAPPING
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.node_match import compile_node_match
from xgap.experiments.toy_semantic import toy_backends
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.pattern.ast import NodePattern
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_compiler import compile_semantic_program, compile_semantic_source
from xgap.semantic.interpretation import InterpretationRequest, SCHEMA
from xgap.semantic.program import SemanticGraphProgram, hard_constraints_sha256
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


BACKENDS = toy_backends(MAPPING)
NS = BACKENDS["fuseki"].resource_namespace


def _program(*predicates):
    return SemanticGraphProgram.from_dict({"program_id": "independent-match-row-constraints",
        "operators": [{"operator_id": "people", "kind": "match", "input_ids": [], "input_kinds": [],
            "output_kind": "binding_set", "parameters": {"node": {"label": "Person", "properties": {}},
                "entity_field": "person", "properties": {"age": "age"}},
            "constraints": [{"constraint_id": f"requirement-{i}", "expression": f"Explicit requirement {i}",
                             "policy": "hard", "predicate": predicate} for i, predicate in enumerate(predicates)]}],
        "roots": ["people"]})


@pytest.fixture
def rdf_client():
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    graph = rdf.Graph()
    person = rdf.URIRef(mapping.resolve("Person", "node_labels").iri)
    age = rdf.URIRef(mapping.resolve("age", "properties").iri)
    name = rdf.URIRef(mapping.resolve("name", "properties").iri)
    # Independent values deliberately distinguish bool/number/null and >2**53.
    for identifier, value, label in (
        ("boolean", True, "keep"), ("one", 1, "keep"),
        ("large", 9007199254740993, "keep"), ("missing", None, "keep"),
        ("adult", 30, "keep"), ("other", 40, "other"),
    ):
        subject = rdf.URIRef(NS + identifier)
        graph.add((subject, rdf.RDF.type, person))
        graph.add((subject, name, rdf.Literal(label)))
        if value is not None:
            graph.add((subject, age, rdf.Literal(value)))
    calls = []

    class LocalRDF(FusekiClient):
        def _post_query(self, text):
            calls.append(text)
            return json.loads(graph.query(text).serialize(format="json"))

    return LocalRDF(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf")), calls


def _execute(program, client):
    plan = compile_semantic_program(program, source_bindings={"people": "fuseki"}, backends=BACKENDS)
    registry = BackendPluginRegistry()
    registry.register(NativeBackendPlugin("fuseki", client))
    return plan, FederatedScheduler(BackendInvokeTool(registry)).execute(plan)


def test_mixed_path_and_named_row_constraints_are_conjoined_after_normalization(rdf_client):
    client, calls = rdf_client
    path = {"kind": "property_equals", "ref": {"kind": "node", "position": "first"},
            "property": "name", "value": "keep"}
    program = _program(path, {"op": "ge", "field": "age", "value": 30},
                       {"op": "lt", "field": "age", "value": 100})
    before, constraint_hash = deepcopy(program.to_dict()), hard_constraints_sha256(program)
    fragment = compile_semantic_source(program.operators[0], BACKENDS["fuseki"])
    path_only = compile_semantic_source(_program(path).operators[0], BACKENDS["fuseki"])
    assert fragment.nodes[0].parameters["artifact"] == path_only.nodes[0].parameters["artifact"]
    assert [node.kind.value for node in fragment.nodes] == [
        "remote_query", "normalize_node_bindings", "coordinator_filter",
    ]
    assert fragment.nodes[-1].inputs == (fragment.nodes[-2].node_id,)
    assert fragment.output == fragment.nodes[-1].node_id
    assert all(node.semantic_operator_ids == ("people",) for node in fragment.nodes)
    _, result = _execute(program, client)
    assert result.success, result.to_dict()
    assert list(result.final_rows) == [{"person": NS + "adult", "age": 30}]
    assert result.total_remote_calls == len(calls) == 1
    assert program.to_dict() == before and hard_constraints_sha256(program) == constraint_hash


@pytest.mark.parametrize("predicate,identifier,value", [
    ({"op": "eq", "field": "age", "value": 1}, "one", 1),
    ({"op": "eq", "field": "age", "value": True}, "boolean", True),
    ({"op": "is_null", "field": "age"}, "missing", None),
    ({"op": "gt", "field": "age", "value": 9007199254740992}, "large", 9007199254740993),
])
def test_match_row_semantics_preserve_boolean_null_and_large_integer_values(rdf_client, predicate, identifier, value):
    client, calls = rdf_client
    plan, result = _execute(_program(predicate), client)
    assert result.success, result.to_dict()
    assert list(result.final_rows) == [{"person": NS + identifier, "age": value}]
    assert type(result.final_rows[0]["age"]) is type(value)
    normalized = next(row for row in result.node_results if row.kind.value == "normalize_node_bindings")
    assert normalized.row_count == 6  # The backend did not reinterpret the row predicate.
    assert sum(node.kind.value == "coordinator_filter" for node in plan.nodes) == 1
    assert len(calls) == result.total_remote_calls == 1


def test_missing_match_output_field_fails_compilation_before_backend_dispatch(rdf_client):
    client, calls = rdf_client
    with pytest.raises(ValueError, match="missing"):
        _execute(_program({"op": "ge", "field": "missing", "value": 30}), client)
    assert calls == []


def test_predicate_with_both_path_and_row_discriminators_is_rejected(rdf_client):
    client, calls = rdf_client
    mixed = {"kind": "property_equals", "ref": {"kind": "node", "position": "first"},
             "property": "age", "value": 30, "op": "eq", "field": "age"}
    with pytest.raises(ValueError):
        _execute(_program(mixed), client)
    assert calls == []


def test_old_match_without_row_constraints_keeps_its_native_and_binding_fragment():
    backend = BACKENDS["fuseki"]
    fragment = compile_semantic_source(_program().operators[0], backend)
    prior_artifact = compile_node_match(NodePattern(label="Person", properties={}), {"age": "age"},
        backend_id="fuseki", backend_mapping=backend.backend_mapping,
        rdf_node_classes=backend.rdf_node_classes, profile=backend.profile, artifact_id="people-match")
    assert [node.node_id for node in fragment.nodes] == ["people/native", "people/bindings"]
    assert [node.kind.value for node in fragment.nodes] == ["remote_query", "normalize_node_bindings"]
    assert fragment.nodes[0].parameters == {"backend_id": "fuseki", "artifact": prior_artifact.to_dict()}
    assert fragment.nodes[1].inputs == ("people/native",) and fragment.output == "people/bindings"
    assert fragment.schema.fields == frozenset({"person", "age"})
    assert fragment.remote_calls == 1


def test_row_constraint_on_traverse_remains_unsupported():
    raw = _program({"op": "ge", "field": "age", "value": 30}).to_dict()
    raw["operators"][0].update(kind="traverse", output_kind="path_set", parameters={"path_pattern": {
        "source": {"label": None, "properties": {}}, "target": {"label": None, "properties": {}},
        "expr": {"kind": "rel", "edge": {"label": "knows", "direction": "OUT", "properties": {}}},
        "selector": {"kind": "ALL", "k": None}, "restrictor": "WALK", "condition": None}})
    with pytest.raises(ValueError):
        compile_semantic_source(SemanticGraphProgram.from_dict(raw).operators[0], BACKENDS["fuseki"])


def test_authored_match_row_response_enters_ordinary_question_p1_without_rewriting_meaning():
    case = next(case for case in CASES if case["id"] == "B04")
    program = _program({"kind": "property_equals", "ref": {"kind": "node", "position": "first"},
                        "property": "id", "value": "a"}, {"op": "ge", "field": "age", "value": 30})
    payload = {"schema_version": SCHEMA, "program": program.to_dict(), "operator_sources": {"people": "toy"}}
    before = deepcopy(payload)
    provider = ControlledProvider(payload)
    request = InterpretationRequest(case["nl"], context={"requested_output": {
        "kind": "binding_set", "fields": ["person", "age"]}})
    result, calls = question_run(case, request=request, provider=provider)
    assert result["success"], result
    assert result["interpretation_external_calls"] == provider.calls == 1
    planning = result["state"]["output"]["planning_run"]
    assert planning["selection"]["algorithm"] in {"independent_source_minimum", "coordinate_two_passes"}
    assert planning["execution"]["value"]["final_rows"] == case["expected_rows"]
    filters = [node for node in planning["selected_plan"]["nodes"] if node["kind"] == "coordinator_filter"]
    assert len(filters) == 1 and filters[0]["semantic_operator_ids"] == ["people"]
    assert result["backend_remote_calls"] == len(calls) == 3
    assert planning["observation_calls"] == 2 and planning["execution_calls"] == 1
    assert result["interpretation"]["program"] == before["program"] and payload == before
