"""Semantic-DAG development checks on the frozen tiny graph."""

import json
from pathlib import Path

from xgap.experiments.toy_backbone import toy_rdf_edge_encoding
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_semantic_v1"


def load_semantic_cases():
    return json.loads((FIXTURE / "cases.json").read_text())


def toy_backends(mapping):
    ns = mapping["backends"]["fuseki"]["namespace"]
    return {backend: SemanticBackend(backend, ns, backend_mapping=mapping,
        rdf_edge_encoding=toy_rdf_edge_encoding(mapping), rdf_node_classes=(ns + "Person",))
        for backend in ("neo4j", "fuseki")}


def wrap_path_case(case, backend_id):
    return {"id": case["id"], "nl": case["nl"], "program": {
        "program_id": "semantic-" + case["id"], "operators": [{"operator_id": "traverse",
        "kind": "traverse", "input_ids": [], "input_kinds": [], "output_kind": "path_set",
        "parameters": {"path_pattern": case["gold_path_pattern_query"]}}], "roots": ["traverse"]},
        "source_bindings": {"traverse": backend_id},
        "expected_rows": [{"path": path.split("/")} for path in case["expected_paths"]],
        "expected_remote_calls": 1}


def execute_semantic_case(case, mapping, *, clients, source_bindings=None):
    program = SemanticGraphProgram.from_dict(case["program"])
    plan = compile_semantic_program(program, source_bindings=(case["source_bindings"]
        if source_bindings is None else source_bindings), backends=toy_backends(mapping))
    plugins = BackendPluginRegistry()
    for client in clients.values():
        plugins.register(NativeBackendPlugin(client.backend_id, client))
    result = FederatedScheduler(BackendInvokeTool(plugins)).execute(plan)
    actual = list(result.final_rows) if result.success else None
    expected = case["expected_rows"]
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    matched = (actual == expected if case.get("ordered") else
               actual is not None and canonical(actual) == canonical(expected))
    return {"query_id": case["id"], "success": result.success and matched
            and result.total_remote_calls == case["expected_remote_calls"],
        "actual_rows": actual, "expected_rows": expected, "ordered": case.get("ordered", False),
        "plan": plan.to_dict(), "runtime": result.to_dict(), "paper_result": False, "live_llm": False}
