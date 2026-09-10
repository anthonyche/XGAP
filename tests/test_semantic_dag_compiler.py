"""Real RDF execution of generated DAGs plus frozen cross-engine native gates."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE, load_fixture
from xgap.experiments.toy_semantic import execute_semantic_case, load_semantic_cases, toy_backends, wrap_path_case
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.row_operations import filter_rows
from xgap.runtime.semantic_compiler import compile_semantic_program
from xgap.semantic.program import SemanticConstraint, SemanticGraphProgram, SemanticHole, SemanticHoleKind, SemanticProgramError


_, PATH_CASES, MAPPING = load_fixture()
CASES = load_semantic_cases()


@pytest.fixture
def client():
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")

    class IndependentRDF(FusekiClient):
        def _post_query(self, text):
            return json.loads(graph.query(text).serialize(format="json"))

    return IndependentRDF(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))


@pytest.mark.parametrize("case", PATH_CASES, ids=lambda c: c["id"])
def test_eighteen_paths_enter_through_the_typed_semantic_program(case, client):
    result = execute_semantic_case(wrap_path_case(case, "fuseki"), MAPPING, clients={"fuseki": client})
    assert result["success"], result
    assert result["plan"]["metadata"]["operator_outputs"] == {"traverse": "traverse/paths"}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_composed_semantic_operators_against_independent_rdf_engine(case, client):
    result = execute_semantic_case(case, MAPPING, clients={"fuseki": client},
        source_bindings={op: "fuseki" for op in case["source_bindings"]})
    assert result["success"], result
    assert FederatedExecutionPlan.from_dict(result["plan"]).to_dict() == result["plan"]
    stages = {op: [n["kind"] for n in result["plan"]["nodes"] if op in n["semantic_operator_ids"]]
              for op in case["expected_runtime_operators"]}
    assert stages == case["expected_runtime_operators"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_independent_reference_sparql_matches_hand_authored_results(case):
    from xgap.experiments.toy_semantic import FIXTURE
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")
    rows = []
    for result in graph.query((FIXTURE / case["reference_target_queries"]["fuseki"]).read_text()):
        row = {str(k): str(v) if isinstance(v, rdf.URIRef) else v.toPython() for k, v in result.asdict().items()}
        if "path" in row:
            row["path"] = row["path"].split("/")
        rows.append(row)
    canonical = lambda rows: sorted(json.dumps(r, sort_keys=True) for r in rows)
    assert (rows == case["expected_rows"] if case["ordered"] else canonical(rows) == canonical(case["expected_rows"]))


def compile_case(case):
    return compile_semantic_program(SemanticGraphProgram.from_dict(case["program"]),
        source_bindings=case["source_bindings"], backends=toy_backends(MAPPING))


def test_program_roundtrip_topological_reordering_and_shared_fanout():
    case = deepcopy(CASES[3])
    program = SemanticGraphProgram.from_dict(case["program"])
    assert SemanticGraphProgram.from_dict(program.to_dict()) == program
    original = compile_case(case)
    case["program"]["operators"].reverse()
    reordered = compile_case(case)
    assert original.nodes == reordered.nodes
    assert sum(node.kind.value == "remote_query" for node in original.nodes) == 1


@pytest.mark.parametrize("mutation", [
    lambda c: c["source_bindings"].update(unknown="neo4j"),
    lambda c: c["program"]["operators"][-1]["parameters"].update(ignored_constraint=True),
    lambda c: c["program"]["operators"][-1]["parameters"]["projections"].update(bad={"kind":"field","field":"missing"}),
    lambda c: c["program"]["operators"][-1].update(output_kind="path_set"),
])
def test_invalid_semantic_program_does_not_make_a_runnable_plan(mutation):
    case = deepcopy(CASES[0]); mutation(case)
    with pytest.raises((SemanticProgramError, ValueError)):
        compile_case(case)


def test_holes_and_opaque_hard_constraints_are_not_ignored():
    case = CASES[0]; program = SemanticGraphProgram.from_dict(case["program"])
    options = dict(source_bindings=case["source_bindings"], backends=toy_backends(MAPPING))
    with pytest.raises(SemanticProgramError, match="holes"):
        compile_semantic_program(replace(program, holes=(SemanticHole("who", SemanticHoleKind.ENTITY, "someone"),)), **options)
    constrained = replace(program.operators[0], constraints=(SemanticConstraint("hard", "age >= 60"),))
    with pytest.raises(SemanticProgramError, match="constraints"):
        compile_semantic_program(replace(program, operators=(constrained, *program.operators[1:])), **options)


def test_same_local_identifier_in_different_namespaces_is_not_the_same_entity():
    from xgap.runtime.row_operations import project_rows
    projections = {"entity": {"kind": "path_node", "position": "last"}}
    assert project_rows([{"path":["a"]}], projections, namespace="urn:left:") != project_rows(
        [{"path":["a"]}], projections, namespace="urn:right:")


def test_row_filter_retains_type_and_decimal_precision():
    rows = [{"x": True}, {"x": 1}, {"x": "1"}, {"x": None}]
    assert filter_rows(rows, {"op":"eq","field":"x","value":1}) == ({"x":1},)
    decimal = {"type":"literal","value":"1.00000000000000000000000000001",
               "datatype":"http://www.w3.org/2001/XMLSchema#decimal"}
    assert filter_rows([{"x":decimal}], {"op":"gt","field":"x","value":1}) == ({"x":decimal},)


def test_failed_match_is_not_retried_and_descendants_are_skipped(client):
    calls = []
    def fail(text):
        calls.append(text)
        raise OSError("controlled backend failure")
    client._post_query = fail
    case = CASES[3]
    result = execute_semantic_case(case, MAPPING, clients={"fuseki": client}, source_bindings={"people":"fuseki"})
    assert not result["success"] and result["actual_rows"] is None and len(calls) == 1
    assert all(row["status"] == "skipped" for row in result["runtime"]["node_results"][1:])
