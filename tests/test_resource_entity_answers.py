"""Explicit entity answers over an independent RDF graph and the ordinary P1 path.

RDFLib executes the compiled SPARQL through a FusekiClient transport override.
These prepared-meaning checks measure neither interpretation nor paper accuracy.
"""

from dataclasses import replace
import hashlib
import json

import pytest

from xgap.agent.semantic_execution import BoundSemanticExecutionTool
from xgap.algebra.ops import RecursiveMode
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfResourceTripleEncoding
from xgap.experiments.resource_entity_answers import run_resource_entity_answers
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.parser import path_pattern_query_to_dict
from xgap.pattern.ast import (
    Direction, EdgePattern, NodePattern, PathPatternQuery, Rel, Selector,
    SelectorKind, Seq,
)
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_planning import LogicalSource
from xgap.semantic.program import SemanticGraphProgram


NS = "http://rdf.freebase.com/ns/"
# The duplicate stored triple and distinct a/d paths must not multiply answers.
TRIPLES = "\n".join(f"<{NS}{s}> <{NS}{p}> <{NS}{o}> ." for s, p, o in (
    ("a", "p", "b"), ("a", "p", "b"), ("d", "p", "b"),
    ("b", "q", "c"), ("c", "r", "e"),
)) + "\n"
SNAPSHOT = hashlib.sha256(TRIPLES.encode()).hexdigest()
ENCODING = RdfResourceTripleEncoding("independent-entity-answer-tiny", SNAPSHOT, NS)


def _program(*, hops=2, position="last", direction=Direction.OUT, source=None):
    edges = [Rel(EdgePattern(label=label, direction=direction)) for label in ("p", "q", "r")[:hops]]
    expression = edges[0]
    for edge in edges[1:]:
        expression = Seq(expression, edge)
    query = PathPatternQuery(
        None, NodePattern(properties={} if source is None else {"type.object.id": source}),
        expression, NodePattern(), Selector(SelectorKind.ALL), RecursiveMode.WALK,
    )
    return SemanticGraphProgram.from_dict({
        "program_id": "independent-resource-entity-answer",
        "operators": [
            {"operator_id": "traverse", "kind": "traverse", "input_ids": [], "input_kinds": [],
             "output_kind": "path_set", "parameters": {"path_pattern": path_pattern_query_to_dict(query)}},
            {"operator_id": "answer", "kind": "project", "input_ids": ["traverse"],
             "input_kinds": ["path_set"], "output_kind": "binding_set",
             "parameters": {"projections": {"answer": {"kind": "path_node", "position": position}}}},
        ],
        "roots": ["answer"],
    })


def _tool(program, *, replicas=("fuseki",), fail_on=None):
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    calls = []

    class LocalClient(FusekiClient):
        def __init__(self, name):
            super().__init__(BackendDescriptor(name, "fuseki", "sparql", "rdf"))
            self.graph = rdf.Graph().parse(data=TRIPLES, format="nt")

        def _post_query(self, text):
            calls.append({"backend": self.backend_id, "query": text})
            if len(calls) == fail_on:
                raise OSError("controlled resource read failure")
            return json.loads(self.graph.query(text).serialize(format="json"))

    backends = {name: SemanticBackend(
        name, NS, identity_property="type.object.id", rdf_resource_encoding=ENCODING,
        profile=replace(default_profile("fuseki"), backend_id=name),
    ) for name in replicas}
    return BoundSemanticExecutionTool(
        program=program, operator_sources={"traverse": "tiny"}, binding_values={},
        sources={"tiny": LogicalSource("tiny", SNAPSHOT, replicas)}, backends=backends,
        backend_clients={name: LocalClient(name) for name in replicas},
        max_candidates=len(replicas), max_observation_calls=len(replicas), max_remote_calls=1,
    ), calls


def _planning(record):
    return record["agent_run"]["state"]["output"]["planning_run"]


def _assert_no_answers(record, status):
    assert record["success"] is False and record["status"] == status, record
    assert "answers" not in record and "answer_count" not in record
    assert record["model_calls"] == 0 and record["automatic_retries"] == 0
    assert record["question_correctness_verified"] is False
    assert record["paper_result"] is False
    assert record["end_to_end_ms"] >= 0


@pytest.mark.parametrize("hops,position,direction,source,expected", [
    pytest.param(1, "first", Direction.OUT, None, ("a", "d"), id="explicit-first"),
    pytest.param(2, "last", Direction.OUT, None, ("c",), id="last-deduplicates-distinct-paths"),
    pytest.param(3, 3, Direction.OUT, None, ("c",), id="explicit-intermediate-node"),
    pytest.param(1, "last", Direction.IN, "b", ("a", "d"), id="incoming-traversal-order"),
])
def test_explicit_entity_meaning_runs_real_planning_and_rdf(hops, position, direction, source, expected):
    program = _program(hops=hops, position=position, direction=direction, source=source)
    tool, calls = _tool(program)
    record = run_resource_entity_answers(tool, "Return the explicitly projected path entities.", max_answer_rows=8)

    assert record["success"] is True and record["status"] == "answered", record
    assert sorted(record["answers"], key=lambda term: term["value"]) == [
        {"type": "uri", "value": NS + entity} for entity in expected
    ]
    assert record["answer_count"] == len(expected)
    assert record["model_calls"] == 0
    assert record["question_correctness_verified"] is record["paper_result"] is False
    assert record["backend_remote_calls"] == len(calls) == 2
    assert record["end_to_end_ms"] >= record["agent_run"]["end_to_end_ms"] >= 0
    assert record["agent_run"]["resolution_external_calls"] == 0
    contract = record["answer_contract"]
    canonical = json.dumps(program.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert contract["program_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert (contract["source_id"], contract["snapshot_version"], contract["position"]) == ("tiny", SNAPSHOT, position)
    assert contract["edge_count"] == hops and contract["resource_namespace"] == NS
    planning = _planning(record)
    assert planning["selection"]["algorithm"] in {"independent_source_minimum", "coordinate_two_passes"}
    assert planning["observation_calls"] == planning["execution_calls"] == 1
    assert planning["total_remote_calls"] == record["backend_remote_calls"]
    # Both a and d give a path even where the explicit entity projection yields one answer.
    remote = [node for node in planning["execution"]["value"]["node_results"] if node["remote_calls"]]
    assert len(remote) == 1 and len(remote[0]["rows"]) == 2


def test_successful_empty_result_is_an_answered_empty_set():
    tool, calls = _tool(_program(source="absent"))
    record = run_resource_entity_answers(tool, "Return the explicitly projected entities.", max_answer_rows=1)
    assert record["success"] is True and record["status"] == "answered", record
    assert record["answers"] == [] and record["answer_count"] == 0
    assert record["backend_remote_calls"] == len(calls) == 2
    assert _planning(record)["execution"]["value"]["success"] is True


@pytest.mark.parametrize("case", [
    "no-project", "missing-position", "non-entity", "out-of-range-empty", "nested-reference-leakage",
])
def test_answer_meaning_is_admitted_before_any_backend_call(case):
    data = _program(source="absent" if case == "out-of-range-empty" else None).to_dict()
    if case == "nested-reference-leakage":
        data["metadata"] = {"context": {"reference_interpretation": {"evaluation_only": True}}}
    elif case == "no-project":
        data["operators"] = data["operators"][:1]
        data["roots"] = ["traverse"]
    else:
        expression = data["operators"][1]["parameters"]["projections"]["answer"]
        if case == "missing-position":
            del expression["position"]
        elif case == "non-entity":
            expression.update(kind="path_edge", position=1)
        else:
            expression["position"] = 4  # A two-hop path has only three node positions.
    tool, calls = _tool(SemanticGraphProgram.from_dict(data))
    record = run_resource_entity_answers(tool, "Return the explicitly projected entities.", max_answer_rows=8)
    _assert_no_answers(record, "admission_failed")
    assert record["agent_run"] is None
    assert record["backend_remote_calls"] == 0 and calls == []
    if case == "nested-reference-leakage":
        assert "metadata.context.reference_interpretation" in record["error"]


@pytest.mark.parametrize("case", ["snapshot-conflict", "namespace-conflict", "missing-resource-encoding"])
def test_every_replica_must_share_the_declared_resource_snapshot(case):
    tool, calls = _tool(_program(), replicas=("fuseki", "other_rdf"))
    other = tool.backends["other_rdf"]
    if case == "snapshot-conflict":
        other = replace(other, rdf_resource_encoding=replace(ENCODING, snapshot_id="another-snapshot"))
    elif case == "namespace-conflict":
        namespace = "https://other.invalid/resource/"
        other = replace(other, resource_namespace=namespace,
                        rdf_resource_encoding=replace(ENCODING, resource_namespace=namespace))
    else:
        other = replace(other, rdf_resource_encoding=None)
    tool.backends = {**tool.backends, "other_rdf": other}
    record = run_resource_entity_answers(tool, "Return the explicitly projected entities.", max_answer_rows=8)
    _assert_no_answers(record, "admission_failed")
    assert record["agent_run"] is None
    assert record["backend_remote_calls"] == 0 and calls == []


@pytest.mark.parametrize("fail_on", [1, 2], ids=["initial-observation", "selected-execution"])
def test_backend_failure_retains_attempts_and_never_becomes_an_empty_answer(fail_on):
    tool, calls = _tool(_program(), fail_on=fail_on)
    record = run_resource_entity_answers(tool, "Return the explicitly projected entities.", max_answer_rows=8)
    _assert_no_answers(record, "execution_failed")
    assert record["agent_run"]["success"] is False
    assert record["backend_remote_calls"] == len(calls) == fail_on
    executions = [observation["payload"] for observation in record["agent_run"]["state"]["observations"]
                  if observation["source"] == "runtime.bind_plan_execute"]
    assert len(executions) == 1
    planning = executions[0]["value"]["planning_run"]
    assert planning["observation_calls"] == 1
    assert planning["execution_calls"] == fail_on - 1
    assert "controlled resource read failure" in json.dumps(record["agent_run"])


def test_answer_row_budget_is_checked_before_adapter_deduplication(monkeypatch):
    import xgap.experiments.resource_entity_answers as module

    actual_run = module.run_agentic_semantic_query
    completed_runs = []

    def duplicate_final_row(*args, **kwargs):
        # Keep the real bind/plan/compile/backend run; perturb only this adapter's
        # input rows to distinguish a pre-dedup budget from a post-dedup budget.
        run = actual_run(*args, **kwargs)
        assert run["success"], run
        rows = run["state"]["output"]["planning_run"]["execution"]["value"]["final_rows"]
        assert rows == [{"answer": NS + "c"}]
        rows.append(dict(rows[0]))
        completed_runs.append(run)
        return run

    monkeypatch.setattr(module, "run_agentic_semantic_query", duplicate_final_row)
    tool, calls = _tool(_program())
    record = run_resource_entity_answers(tool, "Return the explicitly projected entities.", max_answer_rows=1)
    _assert_no_answers(record, "answer_invalid")
    assert len(completed_runs) == 1 and record["agent_run"] is completed_runs[0]
    assert record["agent_run"]["success"] is True
    assert record["backend_remote_calls"] == len(calls) == 2
    assert "row budget" in record["error"]
