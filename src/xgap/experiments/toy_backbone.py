"""Tiny, inspectable backbone checks independent of LLMs and benchmark catalogs."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from xgap.algebra import PropertyGraph, evaluate
from xgap.algebra.conditions import NodeRef, PropertyGreaterThanOrEqual
from xgap.algebra.ops import NodesOp, SelectionOp
from xgap.algebra.pretty import format_plan
from xgap.compilers import compile_cypher, compile_sparql
from xgap.compilers.directed import compile_directed_rows
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern.ast import Rel
from xgap.pattern.lowering import lower_path_pattern
from xgap.runtime import (
    ExistingM9FragmentCompiler, FederatedExecutionPlan, FederatedScheduler,
    RuntimeNode, RuntimeNodeKind, SemanticFragment,
)
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


DEFAULT_FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_toy_v1"


def load_fixture(root: str | Path = DEFAULT_FIXTURE) -> tuple[dict, list[dict], dict]:
    root = Path(root)
    graph = json.loads((root / "graph.json").read_text())
    cases = json.loads((root / "queries.json").read_text())
    mapping = json.loads((root / "mapping.json").read_text())
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Toy query IDs must be unique")
    for case in cases:
        for key in ("nl", "gold_path_pattern_query", "expected_logical_plan", "reference_target_queries"):
            if not case.get(key):
                raise ValueError(f"{case['id']} lacks {key}")
        if case["expected_paths"] != sorted(set(case["expected_paths"])):
            raise ValueError("Expected complete paths must be explicitly sorted and unique")
        for relative in case["reference_target_queries"].values():
            target = (root / relative).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                raise ValueError("Reference target must be an existing fixture file")
    return graph, cases, mapping


def property_graph(data: dict) -> PropertyGraph:
    graph = PropertyGraph()
    for node in data["nodes"]:
        graph.add_node(node["id"], node["label"], node["properties"])
    for edge in data["edges"]:
        graph.add_edge(edge["id"], edge["source"], edge["target"], edge["label"], {"id": edge["id"]})
    return graph


def check_reference(case: dict, graph: PropertyGraph) -> dict[str, Any]:
    """Compare real parsing/lowering/evaluation with independent frozen expectations."""
    row: dict[str, Any] = {"query_id": case["id"], "reference_passed": False, "logical_plan_passed": False}
    try:
        pattern = parse_path_pattern_query(case["gold_path_pattern_query"])
        plan = lower_path_pattern(pattern)
        row["logical_plan"] = format_plan(plan)
        row["logical_plan_passed"] = row["logical_plan"] == case["expected_logical_plan"]
        row["actual_paths"] = ["/".join(path.sequence) for path in evaluate(plan, graph)]
        row["reference_passed"] = row["actual_paths"] == case["expected_paths"]
    except (ValueError, TypeError, NotImplementedError) as error:
        row["gap"] = f"{type(error).__name__}: {error}"
    return row


def compile_diagnostics(case: dict, mapping: dict) -> dict[str, Any]:
    """Availability is not equivalent to compiler result correctness."""
    pattern = parse_path_pattern_query(case["gold_path_pattern_query"])
    result = {}
    for name, compile_query in (
        ("m9_cypher", lambda: compile_cypher(pattern)),
        ("m9_sparql", lambda: compile_sparql(pattern, backend_mapping=mapping)),
        ("directed_cypher", lambda: compile_directed_rows(pattern, backend_id="neo4j")),
        ("directed_sparql", lambda: compile_directed_rows(pattern, backend_id="fuseki", backend_mapping=mapping)),
    ):
        try:
            artifact = compile_query()
            result[name] = {"available": True, "artifact": artifact.to_dict(), "result_correctness_verified": False}
        except (ValueError, TypeError, NotImplementedError) as error:
            result[name] = {"available": False, "error": f"{type(error).__name__}: {error}"}
    return result


def check_sparql_targets(root: str | Path = DEFAULT_FIXTURE) -> list[dict]:
    """Execute independent reference targets, never the compiler's expected output."""
    import rdflib

    root = Path(root)
    _, cases, _ = load_fixture(root)
    graph = rdflib.Graph().parse(root / "load.ttl", format="turtle")
    rows = []
    for case in cases:
        text = (root / case["reference_target_queries"]["fuseki"]).read_text()
        row: dict[str, Any] = {"query_id": case["id"], "success": False}
        try:
            row["actual_paths"] = sorted({str(result.path) for result in graph.query(text)})
            row["success"] = row["actual_paths"] == case["expected_paths"]
        except Exception as error:
            row["error"] = f"{type(error).__name__}: {error}"
        rows.append(row)
    return rows


def compile_vertical_slice(case: dict, mapping: dict) -> FederatedExecutionPlan:
    """Explicit toy placement: one native path fragment and one age fragment.

    This is the first fixed-meaning slice, not a general partitioning optimizer.
    Both fragments go through the existing production compiler adapters.
    """
    pattern = parse_path_pattern_query(case["gold_path_pattern_query"])
    condition = pattern.condition
    if not isinstance(pattern.expr, Rel) or not isinstance(condition, PropertyGreaterThanOrEqual):
        raise ValueError("Toy vertical slice requires one edge and a numeric lower-bound condition")
    if condition.ref != NodeRef.last():
        raise ValueError("The property fragment must filter the reached node")
    compiler = ExistingM9FragmentCompiler(backend_mappings={"fuseki": mapping})
    paths = compiler.compile(SemanticFragment("paths", "neo4j", replace(pattern, condition=None), ("traverse",)))
    eligible = compiler.compile(SemanticFragment("eligible", "fuseki", SelectionOp(
        PropertyGreaterThanOrEqual(NodeRef.first(), condition.property_name, condition.value), NodesOp()), ("filter",)))
    # This fixture's adapters expose stable IDs, not engine-owned entity objects.
    path_artifact = replace(paths.artifact, text="CALL {\n" + paths.artifact.text + "\n}\n"
        'RETURN DISTINCT source.id + "/" + edges[0].id + "/" + target.id AS path, target.id AS target')
    id_iri = mapping["term_mappings"]["fuseki"]["id"]["representation"]
    eligible_artifact = replace(eligible.artifact, text="SELECT DISTINCT ?eligible WHERE { {\n"
        + eligible.artifact.text + f"\n}} ?source <{id_iri}> ?eligible . }}")
    return FederatedExecutionPlan("toy-" + case["id"], (
        RuntimeNode("paths", RuntimeNodeKind.REMOTE_QUERY,
                    parameters={"backend_id": "neo4j", "artifact": path_artifact.to_dict()}),
        RuntimeNode("eligible", RuntimeNodeKind.REMOTE_QUERY,
                    parameters={"backend_id": "fuseki", "artifact": eligible_artifact.to_dict()}),
        RuntimeNode("join", RuntimeNodeKind.COORDINATOR_JOIN, ("paths", "eligible"),
                    parameters={"left_on": "target", "right_on": "eligible"}),
        RuntimeNode("answer", RuntimeNodeKind.PROJECT, ("join",), parameters={"fields": ["path"]}),
    ), ("answer",), max_remote_calls=2, max_parallelism=1)


def execute_vertical_slice(case: dict, mapping: dict, *, neo4j: Any, fuseki: Any) -> dict:
    plan = compile_vertical_slice(case, mapping)
    registry = BackendPluginRegistry()
    for client in (neo4j, fuseki):
        registry.register(NativeBackendPlugin(client.backend_id, client))
    result = FederatedScheduler(BackendInvokeTool(registry)).execute(plan)
    actual = sorted({row["path"] for row in result.final_rows}) if result.success else None
    return {"success": result.success and actual == case["expected_paths"],
        "actual_paths": actual, "expected_paths": case["expected_paths"],
        "plan": plan.to_dict(), "runtime": result.to_dict(), "live_llm": False, "paper_result": False}


def run_offline(root: str | Path = DEFAULT_FIXTURE) -> dict:
    data, cases, mapping = load_fixture(root)
    graph = property_graph(data)
    reference = [check_reference(case, graph) for case in cases]
    targets = check_sparql_targets(root)
    return {"fixture": str(root), "node_count": len(data["nodes"]), "edge_count": len(data["edges"]),
        "query_count": len(cases), "reference": reference, "sparql_reference_targets": targets,
        "compiler_diagnostics": {case["id"]: compile_diagnostics(case, mapping) for case in cases},
        "reference_passed": sum(row["reference_passed"] for row in reference),
        "logical_plan_passed": sum(row["logical_plan_passed"] for row in reference),
        "sparql_targets_passed": sum(row["success"] for row in targets),
        "full_backbone_complete": False, "live_backends": False, "live_llm": False, "paper_result": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    target = Path(args.output)
    if target.exists():
        parser.error("Output already exists; preserve previous evidence")
    result = run_offline(args.fixture)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("query_count", "reference_passed", "logical_plan_passed", "sparql_targets_passed", "full_backbone_complete")}))
    # A coverage report may contain genuine gaps; its creation is not T1 acceptance.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
