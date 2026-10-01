"""INT-1 compiler/ordinary P1 boundary on a tiny independent RDF graph."""

from dataclasses import replace
import json

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.resource_triples import compile_resource_triple_paths
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.compilers.rdf_encoding import RdfResourceTripleEncoding
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.pattern.ast import Direction, EdgePattern, NodePattern, PathPatternQuery, Rel, Selector, SelectorKind
from xgap.algebra.ops import RecursiveMode as PathMode
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.runtime.planning import PlanObservationSnapshot, RemoteEstimate
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.runtime.semantic_planning import LogicalSource, run_semantic_plans
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin


NS = "http://rdf.freebase.com/ns/"
ENCODING = RdfResourceTripleEncoding("tiny-resource-set", "independent-tiny-fixture-v1", NS)


def query():
    return PathPatternQuery(None, NodePattern(label="T", properties={"type.object.id": "a"}),
        Rel(EdgePattern(label="p", direction=Direction.OUT)), NodePattern(),
        Selector(SelectorKind.ALL), PathMode.WALK)


def program(projection="path_node"):
    return SemanticGraphProgram.from_dict({"program_id": "int1-resource", "operators": [
        {"operator_id": "traverse", "kind": "traverse", "input_ids": [], "input_kinds": [],
         "output_kind": "path_set", "parameters": {"path_pattern": path_pattern_query_to_dict(query())}},
        {"operator_id": "answer", "kind": "project", "input_ids": ["traverse"], "input_kinds": ["path_set"],
         "output_kind": "binding_set", "parameters": {"projections": {"answer": {"kind": projection, "position": 1}}}},
    ], "roots": ["answer"]})


def backends():
    return {name: SemanticBackend(name, NS, identity_property="type.object.id", rdf_resource_encoding=ENCODING)
            for name in ("neo4j", "fuseki")}


def test_source_compiles_and_ordinary_ptime_execution_preserves_first_answer():
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph().parse(data=f'<{NS}a> <{NS}type.object.type> <{NS}T> .\n'
        f'<{NS}a> <{NS}p> <{NS}b> .\n<{NS}a> <{NS}p> "literal outside resource graph" .', format="nt")
    space = prepare_semantic_placements(program(), operator_sources={"traverse": "tiny"},
        sources={"tiny": LogicalSource("tiny", ENCODING.snapshot_id, ("neo4j", "fuseki"))}, backends=backends())
    calls = []
    class Client(FusekiClient):
        def _post_query(self, text):
            calls.append(text)
            return json.loads(graph.query(text).serialize(format="json"))
    plugins = BackendPluginRegistry()
    plugins.register(CatalogBackendPlugin("fuseki", Client(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf")),
                                          space.observation_catalogs["fuseki"]))
    estimates = tuple(RemoteEstimate(r.observation_key, r.backend_id, 1 if r.backend_id == "fuseki" else 100,
        1, 80, "controlled test cost", "v1") for r in space.observation_requests)
    result = run_semantic_plans(space, BackendInvokeTool(plugins), snapshot=PlanObservationSnapshot("tiny", "v1", estimates, 1000, .2, .05))
    assert result["success"], result
    assert result["selected_plan"]["metadata"]["source_bindings"] == {"traverse": "fuseki"}
    assert result["execution"]["value"]["final_rows"] == [{"answer": NS + "a"}]
    assert len(calls) == 1


def test_representation_conflict_and_edge_projection_rejected_before_execution():
    with pytest.raises(ValueError, match="combined"):
        replace(backends()["fuseki"], backend_mapping={})
    with pytest.raises(ValueError, match="differ"):
        replace(backends()["fuseki"], identity_property="id")
    with pytest.raises(ValueError, match="edge identity"):
        compile_semantic_program(program("path_edge"), source_bindings={"traverse": "fuseki"}, backends=backends())


@pytest.mark.parametrize("bad", [
    replace(query(), source=NodePattern(properties={"height": 2})),
    replace(query(), restrictor=PathMode.SIMPLE),
    replace(query(), expr=Rel(EdgePattern(properties={"height": 2}))),
])
def test_unsupported_conditions_never_disappear(bad):
    for backend in ("neo4j", "fuseki"):
        with pytest.raises(UnsupportedCompilationError):
            compile_resource_triple_paths(bad, backend_id=backend, encoding=ENCODING)
