"""Exercise real compiled SPARQL, paired scheduling and retained failure cases."""

import json

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.experiments.freebase_native_answers import FactAnswerQuery, ResourceStep, compile_fact_answer
from xgap.experiments.freebase_physical_comparison import comparison_plans, measure_plan, run_comparison
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import ExecutionReport
from xgap.pattern.ast import Direction


NS = "http://example.org/"


class Resources:
    backend_id = "neo4j"

    def __init__(self, resources=(NS + "paper",), fail=False):
        self.resources, self.fail = resources, fail
        self.calls = []

    def execute(self, artifact):
        self.calls.append(artifact)
        return ExecutionReport("neo4j", artifact.artifact_id, "cypher", not self.fail,
            rows=[{"entity_iri": x} for x in self.resources],
            error="controlled backend failure" if self.fail else None)


class RDF(FusekiClient):
    def __init__(self):
        super().__init__(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))
        self.graph = pytest.importorskip("rdflib").Graph().parse(data='''
            @prefix e: <http://example.org/> .
            e:paper e:type e:Class ; e:name "Alpha"@en, "Α"@el .
        ''', format="turtle")
        self.calls = []

    def _post_query(self, query):
        self.calls.append(query)
        return json.loads(self.graph.query(query).serialize(format="json"))


def program(anchor=NS + "Class", max_rows=10):
    return compile_fact_answer(FactAnswerQuery(anchor, (ResourceStep(NS + "type", Direction.IN),),
        NS + "name", "en"), max_rows=max_rows, max_binding_bytes=4096)


def test_actual_rdf_pairing_rotates_balances_and_separates_warmup(tmp_path):
    neo, rdf = Resources(), RDF()
    root = tmp_path / "run"
    result = run_comparison({"q1": program(), "q2": program()}, neo4j=neo, fuseki=rdf,
        output_root=root, measurement_rounds=4, warmup_rounds=1)
    assert result["success"] and result["not_run"] == 0
    assert result["planned_attempts"] == len(result["attempts"]) == 20
    assert len(neo.calls) == 10 and len(rdf.calls) == 20
    for query in result["summary"]["queries"]:
        assert query["all_measurement_pairs_equal"]
        assert query["complete_answer_equal_pairs"] == 4
        assert query["methods"]["neo4j_then_fuseki"]["backend_calls"] == [2]
        assert query["methods"]["single_fuseki"]["backend_calls"] == [1]
        assert query["methods"]["single_fuseki"]["successful"] == 4
    request = json.loads((root / "request.json").read_text())
    measured = [x for x in request["schedule"] if x["phase"] == "measurement"]
    assert measured[0]["query_id"] == "q1" and measured[4]["query_id"] == "q2"
    for query_id in ("q1", "q2"):
        query_rows = [x for x in measured if x["query_id"] == query_id]
        assert [x["strategy"] for x in query_rows[::2]].count("neo4j_then_fuseki") == 2
    assert request["automatic_retries"] == 0 and not request["paper_result"]
    assert not request["network_bytes_measured"]
    assert all(x["network_bytes"] is None for x in result["attempts"])
    assert json.loads((root / "result.json").read_text())["success"]


def test_both_strategies_can_return_complete_empty_answer(tmp_path):
    result = run_comparison({"empty": program(NS + "Absent")}, neo4j=Resources(()), fuseki=RDF(),
        output_root=tmp_path / "empty", measurement_rounds=2, warmup_rounds=0)
    assert result["success"]
    assert all(x["answers"] == () for x in result["attempts"])
    assert all(x["backend_calls"] == 1 for x in result["attempts"])


@pytest.mark.parametrize("failure", ["backend", "overflow", "mismatch"])
def test_retains_failure_and_unrun_denominator_without_retry(tmp_path, failure):
    neo = Resources(fail=failure == "backend")
    if failure == "overflow":
        neo.resources = (NS + "paper", NS + "other")
    if failure == "mismatch":
        neo.resources = ()
    root = tmp_path / failure
    result = run_comparison({"query": program(max_rows=1)}, neo4j=neo, fuseki=RDF(),
        output_root=root, measurement_rounds=2, warmup_rounds=0)
    assert not result["success"] and not result["attempts"][-1]["success"]
    assert len(neo.calls) == 1
    assert len(result["attempts"]) == (2 if failure == "mismatch" else 1)
    assert result["not_run"] + len(result["attempts"]) == 4
    assert "ratio_of_median_elapsed" not in result["summary"]["queries"][0]
    assert not json.loads((root / "result.json").read_text())["success"]
    if failure == "overflow":
        # Preserve the raw backend observation while rejecting truncated answers.
        assert len(result["attempts"][0]["backend_reports"][0]["rows"]) == 2


def test_started_attempt_is_durable_before_external_call(tmp_path):
    root = tmp_path / "intent"
    class Observe(Resources):
        def execute(self, artifact):
            record = json.loads((root / "result.json").read_text())
            assert (root / "request.json").exists()
            assert record["attempts"][-1]["status"] == "started"
            return super().execute(artifact)
    assert run_comparison({"q": program()}, neo4j=Observe(), fuseki=RDF(),
        output_root=root, measurement_rounds=2, warmup_rounds=0)["success"]


@pytest.mark.parametrize("options", [
    {"measurement_rounds": 3}, {"measurement_rounds": True},
    {"warmup_rounds": -1}, {"timeout_seconds": float("nan")},
    {"timeout_seconds": float("inf")}, {"timeout_seconds": True},
])
def test_invalid_schedule_cannot_dispatch(tmp_path, options):
    neo, rdf = Resources(), RDF()
    with pytest.raises(ValueError):
        run_comparison({"q": program()}, neo4j=neo, fuseki=rdf, output_root=tmp_path / "bad", **options)
    assert not neo.calls and not rdf.calls


def test_existing_output_is_not_reused(tmp_path):
    neo, rdf = Resources(), RDF()
    with pytest.raises(FileExistsError):
        run_comparison({"q": program()}, neo4j=neo, fuseki=rdf, output_root=tmp_path)
    assert not neo.calls and not rdf.calls


def test_deadline_preserves_not_run_instead_of_dispatch(tmp_path, monkeypatch):
    from xgap.experiments import freebase_physical_comparison as comparison
    clock = iter((0, 2))
    monkeypatch.setattr(comparison.time, "monotonic", lambda: next(clock))
    neo, rdf = Resources(), RDF()
    result = run_comparison({"q": program()}, neo4j=neo, fuseki=rdf, output_root=tmp_path / "deadline",
        measurement_rounds=2, warmup_rounds=0, timeout_seconds=1)
    assert not result["success"] and result["not_run"] == 4
    assert not result["attempts"] and not neo.calls and not rdf.calls


def test_transport_exception_retains_runtime_attempt_count():
    class Broken(Resources):
        def execute(self, artifact):
            raise RuntimeError("connection failed before an execution report")
    row = measure_plan(comparison_plans(program())["neo4j_then_fuseki"],
                       max_rows=10, neo4j=Broken(), fuseki=RDF())
    assert not row["success"]
    assert row["backend_calls"] == 1 and row["completed_backend_reports"] == 0
