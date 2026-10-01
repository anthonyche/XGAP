"""Tiny independent gold chains for typed coordinator work and source placement."""

from dataclasses import replace
import json
import math
import threading

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.experiments.toy_backbone import check_reference, property_graph
from xgap.experiments.toy_semantic import execute_semantic_case, toy_backends
from xgap.experiments.toy_typed import (FIXTURE, load_typed_fixture, typed_sources,
    typed_reference, typed_reference_rows, typed_rows_match)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.semantic_planning import enumerate_semantic_plans, run_semantic_plans
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin


DATA, CASES, MAPPING = load_typed_fixture()
LOCK = threading.Lock()  # RDFLib parser only; production backend concurrency is unchanged.


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
def test_complete_gold_chain_and_generated_execution(case):
    for op, subquery in case["path_subqueries"].items():
        gold = {"id": case["id"] + "/" + op, **subquery,
                "gold_path_pattern_query": subquery["query"]}
        result = check_reference(gold, property_graph(DATA))
        assert result["logical_plan_passed"] and result["reference_passed"], result
    rdf = RDF()
    result = execute_semantic_case(case, MAPPING, clients={"fuseki": rdf},
        source_bindings={op: "fuseki" for op in case["source_bindings"]})
    assert result["success"], result
    assert typed_rows_match(case, result["actual_rows"])
    assert [n["kind"] for n in result["plan"]["nodes"]] == case["expected_runtime_kinds"]
    assert result["plan"]["metadata"]["binding_value_profile"] == "typed_binding_values_v1"
    assert rdf.calls == case["expected_remote_calls"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_independently_written_sparql_reference(case):
    rdf = RDF()
    result = rdf.execute(typed_reference(case, "fuseki"))
    assert result.success, result
    actual = typed_reference_rows(result, "fuseki", case["reference_columns"])
    assert typed_rows_match(case, actual), actual


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_normal_observation_selection_and_serving_with_declared_views(case):
    base = toy_backends(MAPPING)["fuseki"]
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    aliases = {"neo4j": "rdf_a", "fuseki": "rdf_b"}
    backends = {name: replace(base, backend_id=name,
        backend_mapping=replace(mapping, backend_id=name),
        profile=replace(default_profile("fuseki"), backend_id=name)) for name in aliases.values()}
    sources = {name: replace(source, replica_backend_ids=tuple(aliases[b] for b in source.replica_backend_ids))
               for name, source in typed_sources().items()}
    space = enumerate_semantic_plans(SemanticGraphProgram.from_dict(case["program"]),
        operator_sources=case["operator_sources"], sources=sources, backends=backends,
        max_candidates=4, max_observation_calls=8)
    assert not space.rejected_placements
    assert len(space.candidates) == math.prod(len(sources[s].replica_backend_ids)
                                            for s in case["operator_sources"].values())
    for candidate in space.candidates:
        for op, source in case["operator_sources"].items():
            assert candidate.plan.metadata["source_bindings"][op] in sources[source].replica_backend_ids
    plugins = BackendPluginRegistry(); clients = []
    for name, catalog in space.observation_catalogs.items():
        client = RDF(name); clients.append(client)
        plugins.register(CatalogBackendPlugin(name, client, catalog))
    result = run_semantic_plans(space, BackendInvokeTool(plugins))
    assert result["success"], result
    assert typed_rows_match(case, result["execution"]["value"]["final_rows"])
    assert result["observation_calls"] == len(space.observation_requests)
    assert result["execution_calls"] == case["expected_remote_calls"]
    assert sum(c.calls for c in clients) == result["observation_calls"] + result["execution_calls"]


def test_decimal_view_is_not_falsely_declared_a_neo4j_replica():
    sources = typed_sources()
    assert sources["credit"].replica_backend_ids == ("fuseki",)
    assert sources["credit"].snapshot_version != sources["core"].snapshot_version
    views = json.loads((FIXTURE / "sources.json").read_text())
    assert all("credit" not in n["properties"] for n in views["core"]["graph"]["nodes"])
    assert "credit" not in (FIXTURE / "load.cypher").read_text()


def test_planning_helper_requires_both_explicit_source_arguments():
    from xgap.experiments.toy_planning import execute_planned_semantic_case
    with pytest.raises(ValueError, match="supplied together"):
        execute_planned_semantic_case(CASES[0], MAPPING, clients={}, logical_sources=typed_sources())


@pytest.mark.parametrize("datatype,value", [("unsignedByte", "-1"), ("int", "2147483648"),
    ("positiveInteger", "0"), ("integer", "1.0"), ("decimal", "1e3"), ("double", "NaN")])
def test_native_normalization_validates_numeric_tags_before_conversion(datatype, value):
    from xgap.runtime.row_operations import _rdf_scalar
    with pytest.raises(ValueError):
        _rdf_scalar({"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#" + datatype,
                     "value": value})
