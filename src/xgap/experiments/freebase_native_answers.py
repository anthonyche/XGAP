"""Typed resource paths followed by literal lookup across real backend plugins.

The dataset layout is explicit: URI-object RDF facts are mirrored as Neo4j
resource edges; the unchanged complete RDF snapshot is available in Fuseki.
This adapter is independent of model output, catalog retrieval and gold data.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping

from xgap.backends.rdf_terms import RDF_TERMS_V1, RdfTerm, validate_iri
from xgap.backends.sparql_bindings import IRI_VALUES_MARKER
from xgap.compilers.directed import compile_directed_rows
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from xgap.pattern.ast import Direction, EdgePattern, NodePattern, PathMode, PathPatternQuery, Rel, Selector, SelectorKind, Seq
from xgap.runtime import FederatedExecutionPlan, FederatedScheduler, RuntimeNode, RuntimeNodeKind
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


RESOURCE_LABEL = "XgapRdfResource"
EDGE_LABEL = "XGAP_RDF_RESOURCE_EDGE"


@dataclass(frozen=True)
class ResourceStep:
    predicate: str
    direction: Direction = Direction.OUT

    def __post_init__(self) -> None:
        validate_iri(self.predicate)
        if self.direction not in (Direction.OUT, Direction.IN):
            raise ValueError("An explicit OUT or IN resource step is required")


@dataclass(frozen=True)
class FactAnswerQuery:
    anchor: str
    steps: tuple[ResourceStep, ...]
    literal_predicate: str
    language: str | None = None

    def __post_init__(self) -> None:
        validate_iri(self.anchor)
        validate_iri(self.literal_predicate)
        if not isinstance(self.steps, tuple) or not 1 <= len(self.steps) <= 64 or any(
            not isinstance(s, ResourceStep) for s in self.steps
        ):
            raise ValueError("A resource path requires 1 to 64 typed steps")
        if self.language is not None:
            term = RdfTerm("literal", "", language=self.language)
            object.__setattr__(self, "language", term.language)

    def to_dict(self) -> dict[str, Any]:
        return {"anchor": self.anchor, "steps": [{"predicate": s.predicate, "direction": s.direction.name}
                for s in self.steps], "literal_predicate": self.literal_predicate, "language": self.language}


@dataclass(frozen=True)
class FactAnswerProgram:
    query: FactAnswerQuery
    plan: FederatedExecutionPlan
    baseline: QueryArtifact
    max_rows: int


def compile_fact_answer(query: FactAnswerQuery, *, max_rows: int, max_binding_bytes: int) -> FactAnswerProgram:
    for value in (max_rows, max_binding_bytes):
        if type(value) is not int or value <= 0:
            raise ValueError("Fact answer budgets must be positive integers")
    edges = [Rel(EdgePattern(label=EDGE_LABEL, properties={"predicate": s.predicate}, direction=s.direction))
             for s in query.steps]
    expression = edges[0]
    for edge in edges[1:]:
        expression = Seq(expression, edge)
    path = PathPatternQuery(None, NodePattern(label=RESOURCE_LABEL, properties={"iri": query.anchor}),
        expression, NodePattern(label=RESOURCE_LABEL), Selector(SelectorKind.ALL), PathMode.WALK)
    compiled = compile_directed_rows(path, backend_id="neo4j")
    identity = hashlib.sha256(json.dumps(query.to_dict(), sort_keys=True).encode()).hexdigest()[:16]
    # LIMIT + 1 is an overflow sentinel. The execution adapter rejects it rather
    # than presenting a truncated answer as complete.
    neo = QueryArtifact(f"rdf-path-{identity}", "cypher",
        "CALL {\n" + compiled.text + "\n}\nRETURN DISTINCT target.iri AS entity_iri\n"
        + f"LIMIT {max_rows + 1}", kind="compiled")
    literal = f"?entity <{query.literal_predicate}> ?answer . FILTER(isLiteral(?answer))"
    if query.language is not None:
        literal += f" FILTER(LANG(?answer) = {json.dumps(query.language)})"
    rdf_parameters = {"rdf_result_encoding": RDF_TERMS_V1, "expected_result_columns": ["entity", "answer"]}
    lookup = QueryArtifact(f"rdf-literals-{identity}", "sparql",
        f"SELECT DISTINCT ?entity ?answer WHERE {{ {IRI_VALUES_MARKER}\n{literal} }} LIMIT {max_rows + 1}",
        kind="compiled", parameters={**rdf_parameters, "sparql_iri_binding": {
            "parameter": "entity_iris", "variable": "entity", "max_bindings": max_rows,
            "max_bytes": max_binding_bytes}})
    patterns = [f"BIND(<{query.anchor}> AS ?n0)"]
    for i, step in enumerate(query.steps):
        start, end = (i, i+1) if step.direction is Direction.OUT else (i+1, i)
        patterns.append(f"?n{start} <{step.predicate}> ?n{end} . FILTER(isIRI(?n{end}) && isIRI(?n{start}))")
    patterns.extend((f"BIND(?n{len(query.steps)} AS ?entity)", literal))
    baseline = QueryArtifact(f"rdf-baseline-{identity}", "sparql",
        "SELECT DISTINCT ?entity ?answer WHERE {\n" + "\n".join(patterns) + f"\n}} LIMIT {max_rows + 1}",
        kind="compiled", parameters=rdf_parameters)
    plan = FederatedExecutionPlan(f"rdf-bind-{identity}", (
        RuntimeNode("resources", RuntimeNodeKind.REMOTE_QUERY,
            parameters={"backend_id": "neo4j", "artifact": neo.to_dict()}),
        RuntimeNode("literals", RuntimeNodeKind.REMOTE_BIND_QUERY, ("resources",),
            parameters={"backend_id": "fuseki", "artifact": lookup.to_dict(), "bind_field": "entity_iri",
                        "parameter": "entity_iris", "max_bindings": max_rows}),
        RuntimeNode("answer", RuntimeNodeKind.PROJECT, ("literals",), parameters={"fields": ["entity", "answer"]}),
    ), ("answer",), max_remote_calls=2, max_parallelism=1,
        metadata={"dataset_encoding": "rdf-resource-edge-mirror-v1", "max_result_rows": max_rows})
    return FactAnswerProgram(query, plan, baseline, max_rows)


class _BoundedClient:
    def __init__(self, client: Any, max_rows: int):
        self.client = client
        self.backend_id = client.backend_id
        self.max_rows = max_rows
        self.reports: list[ExecutionReport] = []

    def healthcheck(self):
        return self.client.healthcheck()

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        report = self.client.execute(artifact)
        self.reports.append(report)
        if report.success and len(report.rows) > self.max_rows:
            return replace(report, success=False, rows=[], error="Complete answer exceeds explicit result-row budget")
        return report


def answer_pairs(rows: Any) -> tuple[tuple[str, str], ...]:
    return tuple(sorted({(RdfTerm.from_binding(r["entity"]).identity,
                          RdfTerm.from_binding(r["answer"]).identity) for r in rows}))


def execute_fact_answer(program: FactAnswerProgram, *, neo4j: Any, fuseki: Any) -> dict[str, Any]:
    clients = [_BoundedClient(c, program.max_rows) for c in (neo4j, fuseki)]
    registry = BackendPluginRegistry()
    for client in clients:
        registry.register(NativeBackendPlugin(client.backend_id, client))
    result = FederatedScheduler(BackendInvokeTool(registry)).execute(program.plan)
    # Preserve failures; a missing/broken backend is never an empty answer.
    evidence: dict[str, Any] = {"query": program.query.to_dict(), "federated": result.to_dict(),
        "federated_executions": [r.to_dict() for c in clients for r in c.reports],
        "success": False, "paper_result": False}
    if not result.success:
        return evidence
    baseline = clients[1].execute(program.baseline)
    evidence["baseline"] = baseline.to_dict()
    if baseline.success:
        evidence["answers_equal"] = answer_pairs(result.root_rows["answer"]) == answer_pairs(baseline.rows)
        evidence["success"] = evidence["answers_equal"]
    return evidence
