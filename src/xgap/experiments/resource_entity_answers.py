"""Prepared explicit entity meaning through the ordinary agent/P1 execution path.

This adapter has no answer-position default or benchmark reference input. The
existing semantic Project owns meaning; only its resulting IRI representation
is converted to typed answers here. Model interpretation and scoring are separate.
"""

from __future__ import annotations

import time
from typing import Any

from xgap.agent.semantic_execution import BoundSemanticExecutionTool, run_agentic_semantic_query
from xgap.backends.rdf_terms import RdfTerm
from xgap.compilers.directed import _shape
from xgap.compilers.errors import CompilerError
from xgap.compilers.features import default_profile
from xgap.compilers.rdf_encoding import RdfResourceTripleEncoding
from xgap.experiments.grailqa_semantic_pilot import strict_inference_leakage_audit
from xgap.experiments.hashing import content_hash
from xgap.llm.parser import parse_path_pattern_query
from xgap.runtime.answers import AnswerProjection
from xgap.semantic.program import SemanticOperatorKind as S, SemanticValueKind as V
from xgap.tools import ToolRegistry


def _answer_contract(tool: BoundSemanticExecutionTool) -> tuple[dict[str, Any], RdfResourceTripleEncoding]:
    program = tool.program
    strict_inference_leakage_audit(program.to_dict())
    if program.holes or tool.binding_values:
        raise ValueError("Entity-answer execution requires an already bound meaning")
    if len(program.operators) != 2 or len(program.roots) != 1:
        raise ValueError("Entity answers require one Traverse followed by one root Project")
    by_id = {op.operator_id: op for op in program.operators}
    project = by_id[program.roots[0]]
    if (project.kind is not S.PROJECT or len(project.input_ids) != 1
            or project.input_kinds != (V.PATH_SET,) or project.output_kind is not V.BINDING_SET):
        raise ValueError("The answer root must project a path node into a binding set")
    traverse = by_id[project.input_ids[0]]
    if traverse.kind is not S.TRAVERSE or traverse.input_ids or traverse.output_kind is not V.PATH_SET:
        raise ValueError("The answer root must consume one complete source Traverse")
    projections = project.parameters.get("projections", {})
    if set(projections) != {"answer"}:
        raise ValueError("The semantic Project must explicitly define only the answer field")
    expression = projections["answer"]
    if (not isinstance(expression, dict) or set(expression) != {"kind", "position"}
            or expression["kind"] != "path_node"):
        raise ValueError("Entity answers require an explicit path_node position")
    position = expression["position"]
    if not (type(position) is int and position > 0) and position not in ("first", "last"):
        raise ValueError("An answer position is a positive node index, first, or last")
    query = parse_path_pattern_query(traverse.parameters["path_pattern"])
    edge_count = _shape(query, default_profile("fuseki")).edge_count
    if not 1 <= edge_count <= 3 or (type(position) is int and position > edge_count + 1):
        raise ValueError("Answer position must belong to the fixed one-to-three-hop path")
    if set(tool.operator_sources) != {traverse.operator_id}:
        raise ValueError("Source assignments must cover exactly the source Traverse")
    source_id = tool.operator_sources[traverse.operator_id]
    source = tool.sources[source_id]
    encodings = [tool.backends[name].rdf_resource_encoding for name in source.replica_backend_ids]
    if (not encodings or any(not isinstance(e, RdfResourceTripleEncoding) for e in encodings)
            or any(e.snapshot_id != source.snapshot_version for e in encodings)
            or any(e != encodings[0] for e in encodings)):
        raise ValueError("Every replica must declare the same resource encoding and logical snapshot")
    encoding = encodings[0]
    return {"program_sha256": content_hash(program.to_dict()), "root": project.operator_id,
            "traverse": traverse.operator_id, "column": "answer", "position": position,
            "edge_count": edge_count, "source_id": source_id,
            "snapshot_version": source.snapshot_version, "encoding_sha256": encoding.identity,
            "replicas": list(source.replica_backend_ids), "resource_namespace": encoding.resource_namespace,
            "origin": "explicit_semantic_project", "deployment_assertion_verified": False}, encoding


def _typed_answers(rows: Any, encoding: RdfResourceTripleEncoding, max_rows: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > max_rows:
        raise ValueError("Complete entity answer exceeds its row budget or is missing")
    typed = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"answer"}:
            raise ValueError("Entity results must contain exactly the declared answer column")
        iri = row["answer"]
        if not isinstance(iri, str) or not iri.startswith(encoding.resource_namespace):
            raise ValueError("Entity answer is outside the declared resource namespace")
        suffix = iri[len(encoding.resource_namespace):]
        if encoding.rdf.resource_iri(suffix) != iri:
            raise ValueError("Entity answer does not preserve canonical resource identity")
        typed.append({"answer": RdfTerm("uri", iri).to_binding()})
    return [term.to_binding() for term in AnswerProjection("answer").project_rows(typed)]


def run_resource_entity_answers(tool: BoundSemanticExecutionTool, question: str, *,
                                max_answer_rows: int) -> dict[str, Any]:
    """Execute a bound meaning once and retain all agent failures and actual costs."""
    started = time.perf_counter()
    record: dict[str, Any] = {"schema_version": "resource-entity-answers-v1", "success": False,
        "status": "admission_failed", "agent_run": None, "model_calls": 0,
        "backend_remote_calls": 0, "answer_scope": "declared_snapshot",
        "question_correctness_verified": False, "paper_result": False, "automatic_retries": 0}
    stage = "admission"
    try:
        if type(max_answer_rows) is not int or max_answer_rows <= 0:
            raise ValueError("A finite positive answer-row budget is required")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("An explicit nonempty question is required")
        contract, encoding = _answer_contract(tool)
        record["answer_contract"] = contract
        record["max_answer_rows"] = max_answer_rows
        stage = "execution"
        run = run_agentic_semantic_query(tool, question, resolution_tools=ToolRegistry())
        record["agent_run"] = run
        record["backend_remote_calls"] = run["backend_remote_calls"]
        if not run["success"]:
            record["status"] = "execution_failed"
            return record
        stage = "answer"
        planning = run["state"]["output"]["planning_run"]
        if (not planning["success"] or planning["execution"]["status"] != "success"
                or not planning["execution"]["value"]["success"]):
            raise ValueError("Successful entity answers require a successful execution")
        normalized_at = time.perf_counter()
        try:
            answers = _typed_answers(planning["execution"]["value"]["final_rows"], encoding, max_answer_rows)
        finally:
            record["answer_normalization_ms"] = (time.perf_counter() - normalized_at) * 1000
        record.update(success=True, status="answered", answers=answers, answer_count=len(answers))
        return record
    except (KeyError, TypeError, ValueError, CompilerError) as error:
        record.update(status={"admission": "admission_failed", "execution": "execution_failed",
                              "answer": "answer_invalid"}[stage], error_type=type(error).__name__, error=str(error))
        return record
    finally:
        record["end_to_end_ms"] = (time.perf_counter() - started) * 1000
