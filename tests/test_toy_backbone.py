"""Frozen expectations exercise existing components; gaps remain visible."""

from copy import deepcopy
import json

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.experiments.toy_backbone import (
    DEFAULT_FIXTURE, check_reference, check_sparql_targets, compile_diagnostics,
    compile_vertical_slice, execute_vertical_slice, load_fixture, property_graph,
)
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import ExecutionReport


DATA, CASES, MAPPING = load_fixture()


def test_tiny_population_preserves_parallel_edges_cycles_and_isolated_node():
    assert len(DATA["nodes"]) == 5 and len(DATA["edges"]) == 8 and len(CASES) == 18
    assert {x["id"] for x in CASES} == {f"T{i:02}" for i in range(1, 19)}
    pairs = [(x["source"], x["target"]) for x in DATA["edges"]]
    assert pairs.count(("a", "b")) == 2 and ("d", "d") in pairs
    assert all("z" not in pair for pair in pairs)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_gold_to_logical_plan_and_complete_reference_paths(case):
    row = check_reference(case, property_graph(DATA))
    if case["id"] == "T15":
        # T0 documents the gap, not a claim that IN is implemented by this lowerer.
        assert not row["reference_passed"] and "only OUT" in row["gap"]
        assert case["expected_paths"] == ["b/e1/a", "b/e7/a"]
        assert compile_diagnostics(case, MAPPING)["directed_cypher"]["available"]
    else:
        assert row["logical_plan_passed"], row
        assert row["reference_passed"], row


def test_all_independent_sparql_targets_match_authored_answers():
    pytest.importorskip("rdflib", minversion="7.1.4")
    rows = check_sparql_targets()
    assert len(rows) == 18
    assert all(row["success"] for row in rows), [row for row in rows if not row["success"]]


def test_expected_answer_changes_are_not_self_fulfilling():
    case = deepcopy(CASES[3])
    case["expected_paths"] = ["a/e1/b"]  # Bob is 22, so the >=30 filter excludes him.
    assert not check_reference(case, property_graph(DATA))["reference_passed"]
    case = deepcopy(CASES[3])
    case["expected_logical_plan"] = "Edges"
    assert not check_reference(case, property_graph(DATA))["logical_plan_passed"]


def test_recursive_modes_and_selector_ties_have_distinguishing_witnesses():
    paths = {case["id"]: set(case["expected_paths"]) for case in CASES}
    assert "a/e4/c/e3/a/e4/c" in paths["T07"] - paths["T08"]
    assert "a/e1/b/e2/c/e3/a" in paths["T10"] - paths["T09"]
    assert paths["T11"] == paths["T12"]
    assert {"a/e1/b", "a/e7/b"} <= paths["T11"]
    assert paths["T13"] < paths["T14"]


class IndependentRDF(FusekiClient):
    def __init__(self):
        super().__init__(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))
        rdf = pytest.importorskip("rdflib", minversion="7.1.4")
        self.graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")

    def _post_query(self, query):
        return json.loads(self.graph.query(query).serialize(format="json"))


class RecordedPathClient:
    """A declared local response fixture, not a Cypher engine."""
    backend_id = "neo4j"

    def __init__(self, fail=False):
        self.fail = fail

    def execute(self, artifact):
        return ExecutionReport("neo4j", artifact.artifact_id, "cypher", not self.fail,
            rows=[{"path": "a/e1/b", "target": "b"}, {"path": "a/e7/b", "target": "b"},
                  {"path": "a/e4/c", "target": "c"}], error="controlled failure" if self.fail else None)


def test_vertical_slice_uses_actual_rdf_filter_and_existing_scheduler():
    result = execute_vertical_slice(CASES[-1], MAPPING, neo4j=RecordedPathClient(), fuseki=IndependentRDF())
    assert result["success"] and result["actual_paths"] == ["a/e4/c"]
    assert result["runtime"]["total_remote_calls"] == 2
    assert not result["live_llm"] and not result["paper_result"]
    # Change the input threshold, not the implementation; the native SPARQL changes.
    case = deepcopy(CASES[-1])
    case["gold_path_pattern_query"]["condition"]["value"] = 50
    case["expected_paths"] = []
    assert execute_vertical_slice(case, MAPPING, neo4j=RecordedPathClient(), fuseki=IndependentRDF())["success"]


def test_failed_source_is_not_an_empty_correct_answer():
    result = execute_vertical_slice(CASES[-1], MAPPING, neo4j=RecordedPathClient(True), fuseki=IndependentRDF())
    assert not result["success"] and result["actual_paths"] is None


def test_deterministic_slice_needs_no_provider_or_catalog(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("unexpected network"))
    plan = compile_vertical_slice(CASES[-1], MAPPING)
    assert plan.max_remote_calls == 2
    assert {node.kind.value for node in plan.nodes} == {"remote_query", "coordinator_join", "project"}


def test_invalid_split_rejects_before_backend_dispatch():
    with pytest.raises(ValueError, match="one edge"):
        compile_vertical_slice(CASES[4], MAPPING)
