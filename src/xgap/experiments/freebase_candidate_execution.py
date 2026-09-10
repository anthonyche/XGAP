"""Execute prompt-grounded intent through the existing backend/runtime boundary.

This is an opt-in engineering interface. It does not select a candidate, query
gold data, repair model choices, or change a frozen benchmark protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from xgap.backends.rdf_terms import RdfTerm, RDF_TERMS_V1
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.experiments.freebase_candidate_compiler import (
    CandidateExecutionUnavailable, CompiledCandidateExecution, ExecutionRequirements,
    FreebaseExecutionMapping, XSD, compile_candidate_execution,
)
from xgap.experiments.grailqa_candidate_grounding import ground_canonical_candidates
from xgap.experiments.hashing import content_hash
from xgap.experiments.interpretation_contract import parse_normalized_planner_response
from xgap.experiments.runtime_alignment import PromptSchemaView
from xgap.infrastructure.runtime import ExecutionReport, QueryArtifact
from xgap.llm.candidate_assessment import assess_candidate
from xgap.llm.schemas import PlannerRequest
from xgap.runtime import FederatedScheduler
from xgap.runtime.answers import AnswerProjection, exact_answer_match
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


@dataclass(frozen=True)
class PreparedCandidateBatch:
    evidence: Mapping[str, Any]
    programs: Mapping[str, CompiledCandidateExecution]


def prepare_candidate_batch(raw: Mapping[str, Any], request: PlannerRequest, view: PromptSchemaView,
                            mapping: FreebaseExecutionMapping, requirements: ExecutionRequirements,
                            *, max_rows: int, max_binding_bytes: int) -> PreparedCandidateBatch:
    """Preserve candidate order and failures while admitting executable programs."""
    if request.metadata.get("prompt_schema_view") != view.to_dict() or request.metadata.get("task_id") != view.task_id:
        raise ValueError("Execution request must carry this exact prompt view and task identity")
    candidates = raw.get("candidates")
    outcomes = [{"candidate_index": i, "candidate_id": c.get("candidate_id") if isinstance(c, Mapping) else None,
                 "raw_candidate_sha256": content_hash(c)}
                for i, c in enumerate(candidates if isinstance(candidates, list) else (), 1)]
    evidence = {"schema_version": "grounded-candidate-execution-v1", "task_id": view.task_id,
                "question": request.question, "prompt_view_sha256": view.view_hash,
                "raw_response_sha256": content_hash(raw), "mapping": mapping.to_dict(),
                "execution_requirements": requirements.to_dict(), "candidates": outcomes,
                "prepared_count": 0, "paper_result": False}
    stage = "normalized_parser_rejected"
    try:
        parsed = parse_normalized_planner_response(raw, request)
        stage = "grounding_envelope_rejected"
        batch = ground_canonical_candidates(raw, parsed, view)
    except Exception as error:  # Preserve the whole envelope failure, including every raw candidate.
        failure = {"stage": stage, "error_type": type(error).__name__, "message": str(error)}
        evidence["failure"] = failure
        for row in outcomes:
            row.update(failure)
        return PreparedCandidateBatch(evidence, {})
    grounded = {c.candidate.candidate_id: c for c in batch.grounded.grounded_candidates}
    programs = {}
    for row in outcomes:
        candidate_id = row["candidate_id"]
        if candidate_id in batch.failures:
            row.update(stage="grounding_rejected", failure=batch.failures[candidate_id].to_dict())
            continue
        candidate = grounded[candidate_id]
        row["grounded_candidate_sha256"] = content_hash(candidate.to_dict())
        assessment = assess_candidate(candidate.candidate)
        row["semantic_validation"] = assessment.semantic_validation.to_dict()
        if not assessment.semantic_validation.ok:
            row["stage"] = "semantic_type_rejected"
            continue
        try:
            program = compile_candidate_execution(candidate.candidate.pattern_query, mapping, requirements,
                max_rows=max_rows, max_binding_bytes=max_binding_bytes)
        except (CandidateExecutionUnavailable, UnsupportedCompilationError, ValueError) as error:
            row.update(stage="execution_unavailable", error_type=type(error).__name__,
                       code=getattr(error, "code", "unsupported_execution"), message=str(error))
            continue
        row.update(stage="prepared", input_pattern_sha256=program.input_pattern_sha256,
                   plan_sha256=content_hash(program.plan.to_dict()))
        programs[candidate_id] = program
    evidence["prepared_count"] = len(programs)
    return PreparedCandidateBatch(evidence, programs)


class _CheckedClient:
    """Finite result and scalar-contract guard, retaining original backend reports."""

    def __init__(self, client: Any, max_rows: int):
        self.client, self.backend_id, self.max_rows = client, client.backend_id, max_rows
        self.reports: list[ExecutionReport] = []

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        report = self.client.execute(artifact)
        self.reports.append(report)
        if not report.success:
            return report
        try:
            if report.backend_id != self.backend_id or report.artifact_id != artifact.artifact_id:
                raise ValueError("Backend result identity does not match the requested artifact")
            if len(report.rows) > self.max_rows:
                raise ValueError("Complete result exceeds the explicit row budget")
            columns = artifact.parameters.get("xgap_scalar_guard_columns")
            if columns is None:
                return report
            checked = []
            for row in report.rows:
                if set(row) != {*columns, "invalid"}:
                    raise ValueError("Scalar guard returned incomplete columns")
                flag = RdfTerm.from_binding(row["invalid"])
                if flag.datatype != XSD+"boolean" or flag.value not in {"false", "0"}:
                    raise ValueError("Reached data violates the declared functional scalar encoding")
                terms = {key: RdfTerm.from_binding(row[key]) for key in columns}
                if any(term.kind != "uri" for term in terms.values()):
                    raise ValueError("Scalar guard lost a resource identity")
                checked.append({key: term.value for key, term in terms.items()})
            expected = artifact.parameters["path_rows"]
            if ({content_hash(row) for row in checked} != {content_hash(row) for row in expected}
                    or len(checked) != len(expected)):
                raise ValueError("Scalar guard did not account for every correlated input row")
            metadata = {k: v for k, v in report.metadata.items() if k != "rdf_result_encoding"}
            return replace(report, rows=checked, metadata={**metadata, "scalar_contract_checked": True,
                           "result_encoding": "correlated_resource_iris_v1"})
        except (KeyError, TypeError, ValueError) as error:
            return replace(report, success=False, rows=[], error=str(error))


def execute_candidate(program: CompiledCandidateExecution, *, neo4j: Any, fuseki: Any) -> dict[str, Any]:
    if neo4j.backend_id != "neo4j" or fuseki.backend_id != "fuseki":
        raise ValueError("Dataset mapping requires the declared Neo4j and Fuseki plugins")
    clients = [_CheckedClient(c, program.max_rows) for c in (neo4j, fuseki)]
    registry = BackendPluginRegistry()
    for client in clients:
        registry.register(NativeBackendPlugin(client.backend_id, client))
    result = FederatedScheduler(BackendInvokeTool(registry)).execute(program.plan)
    evidence = {"input_pattern_sha256": program.input_pattern_sha256, "mapping": program.mapping.to_dict(),
                "plan": program.plan.to_dict(), "federated": result.to_dict(), "success": False,
                "federated_executions": [r.to_dict() for c in clients for r in c.reports], "paper_result": False}
    if not result.success:
        return evidence
    baseline = clients[1].execute(program.baseline)
    evidence["baseline_artifact"] = program.baseline.to_dict()
    evidence["baseline"] = baseline.to_dict()
    if not baseline.success:
        return evidence
    try:
        projection = AnswerProjection("answer")
        actual = projection.project_rows(result.root_rows["answer"])
        expected = projection.project_execution(baseline)
        evidence["answers_equal"] = exact_answer_match(actual, expected)
        evidence["answer_count"] = len(actual)
        evidence["answers"] = [term.to_binding() for term in actual]
        evidence["success"] = evidence["answers_equal"]
    except (KeyError, TypeError, ValueError) as error:
        evidence["error"] = str(error)
    return evidence
