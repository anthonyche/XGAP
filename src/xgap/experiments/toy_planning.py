"""Native tiny plan-selection gate; correctness comparisons happen afterward."""

import hashlib
import json
from pathlib import Path

from xgap.experiments.toy_backbone import load_fixture
from xgap.experiments.toy_semantic import toy_backends
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans, run_semantic_plans
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin


def execute_planned_semantic_case(case, mapping, *, clients, max_observation_calls=4, fixture_root=None,
                                  logical_sources=None, operator_sources=None):
    if (logical_sources is None) != (operator_sources is None):
        raise ValueError("Explicit logical sources and operator sources must be supplied together")
    if logical_sources is None:
        graph = (json.loads((Path(fixture_root) / "graph.json").read_text())
                 if fixture_root is not None else load_fixture()[0])
        version = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()
        logical_sources = {"toy": LogicalSource("toy", version, ("neo4j", "fuseki"))}
        operator_sources = {op: "toy" for op in case["source_bindings"]}
    space = enumerate_semantic_plans(SemanticGraphProgram.from_dict(case["program"]),
        operator_sources=operator_sources, sources=logical_sources,
        backends=toy_backends(mapping), max_candidates=4, max_observation_calls=max_observation_calls)
    plugins = BackendPluginRegistry()
    for backend, catalog in space.observation_catalogs.items():
        plugins.register(CatalogBackendPlugin(backend, clients[backend], catalog))
    tool = BackendInvokeTool(plugins)
    run = run_semantic_plans(space, tool, goal_id="toy-planning-" + case["id"])
    record = {"query_id": case["id"], "success": False, "planning_run": run,
              "candidate_checks": [], "validation_only_extra_remote_calls": 0,
              "paper_result": False, "live_llm": False}
    if not run["success"]:
        return record
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    def matches(rows):
        return (list(rows) == case["expected_rows"] if case.get("ordered", False) else
                canonical(rows) == canonical(case["expected_rows"]))
    selected_rows = run["execution"]["value"]["final_rows"]
    if not matches(selected_rows):
        record["error"] = "Selected plan disagrees with independent gold"
        return record
    # Validation executions are not part of planning/serving performance.
    # Reuse the selected run; execute each other candidate only once.
    for candidate in space.candidates:
        plan = candidate.plan
        if plan.plan_id == run["selection"]["selected_plan_id"]:
            actual, success, calls = selected_rows, True, 0
        else:
            result = FederatedScheduler(tool).execute(plan)
            actual, success, calls = list(result.final_rows), result.success, result.total_remote_calls
        record["validation_only_extra_remote_calls"] += calls
        check = {"plan_id": plan.plan_id, "source_bindings": plan.metadata["source_bindings"],
                 "actual_rows": actual, "success": success and matches(actual),
                 "additional_remote_calls": calls}
        record["candidate_checks"].append(check)
        if not check["success"]:
            return record
    record["success"] = True
    return record
