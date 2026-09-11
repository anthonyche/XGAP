"""Existing resolution policy → typed binding → costed native execution."""

from dataclasses import dataclass, replace
import time
from typing import Any, Mapping

from xgap.agent.contracts import AgentDecision, DecisionKind, GoalStatus, PlannedToolCall
from xgap.agent.environment import AgentEnvironment
from xgap.agent.loop import GoalLoop
from xgap.agent.resolution import SelectiveResolutionConfig, SelectiveSemanticResolutionPolicy, build_selective_resolution_goal
from xgap.runtime.planning import PlanObservationSnapshot
from xgap.runtime.semantic_compiler import SemanticBackend
from xgap.runtime.semantic_memory import SemanticPlanMemory
from xgap.runtime.semantic_planning import LogicalSource, run_semantic_plans
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.semantic.binding import SemanticBindingValue, bind_semantic_query
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin, ToolRegistry
from xgap.tools.contracts import ToolEffect, ToolResult, ToolSpec, ToolStatus


BIND_PLAN_EXECUTE = "runtime.bind_plan_execute"


@dataclass
class BoundSemanticExecutionTool:
    program: SemanticGraphProgram
    operator_sources: Mapping[str, Any]
    binding_values: Mapping[str, SemanticBindingValue]
    sources: Mapping[str, LogicalSource]
    backends: Mapping[str, SemanticBackend]
    backend_clients: Mapping[str, Any]
    max_candidates: int = 64  # Mainline v2: local-option budget, not Cartesian placements.
    max_observation_calls: int = 128
    max_remote_calls: int = 16
    snapshot: PlanObservationSnapshot | None = None
    static_backend_order: tuple[str, ...] | None = None
    plan_memory: SemanticPlanMemory | None = None

    @property
    def spec(self):
        return ToolSpec(BIND_PLAN_EXECUTE,
            "Bind resolved identifiers, enforce typed constraints, plan and execute the selected query",
            {"type": "object", "required": ["resolution"], "properties": {"resolution": {"type": "object"}},
             "additionalProperties": False}, "bound_semantic_execution", ToolEffect.EXTERNAL, remote=True)

    def invoke(self, arguments, context):
        started = time.perf_counter()
        if set(arguments) != {"resolution"}:
            return ToolResult.error_result(BIND_PLAN_EXECUTE, "Expected one resolution result")
        # Binding/admission run before any backend tool is called.
        bound = bind_semantic_query(self.program, arguments["resolution"],
            binding_values=self.binding_values, operator_sources=self.operator_sources)
        space = prepare_semantic_placements(bound.program, operator_sources=bound.operator_sources,
            sources=self.sources, backends=self.backends, max_local_options=self.max_candidates,
            max_observation_calls=self.max_observation_calls, max_remote_calls=self.max_remote_calls)
        plugins = BackendPluginRegistry()
        for name, catalog in space.observation_catalogs.items():
            if name not in self.backend_clients:
                return ToolResult.unavailable(BIND_PLAN_EXECUTE, f"No client for admitted backend {name}")
            plugins.register(CatalogBackendPlugin(name, self.backend_clients[name], catalog))
        run = run_semantic_plans(space, BackendInvokeTool(plugins), snapshot=self.snapshot,
            static_backend_order=self.static_backend_order, plan_memory=self.plan_memory, goal_id=context.goal_id)
        value = {"bound_program": bound.program.to_dict(), "bindings": dict(bound.bindings),
                 "operator_sources": dict(bound.operator_sources), "planning_run": run}
        metrics = {"elapsed_ms": (time.perf_counter() - started) * 1000,
                   "remote_calls": run["total_remote_calls"], "observation_calls": run["observation_calls"],
                   "execution_calls": run["execution_calls"]}
        return ToolResult(BIND_PLAN_EXECUTE, ToolStatus.SUCCESS if run["success"] else ToolStatus.ERROR,
                          value=value, error=run["error"] if not run["success"] else None, metrics=metrics)


@dataclass(frozen=True)
class SemanticExecutionPolicy:
    resolver: SelectiveSemanticResolutionPolicy

    def decide(self, state, environment):
        executions = [o for o in state.observations if o.kind == "tool_result" and o.source == BIND_PLAN_EXECUTE]
        if executions:
            last = executions[-1].payload
            if last["status"] == ToolStatus.SUCCESS.value:
                return AgentDecision.succeed("Bound semantic program executed with its constraints", last["value"])
            if last["status"] == ToolStatus.UNAVAILABLE.value:
                return AgentDecision.block(last["error"])
            return AgentDecision.fail(last["error"])
        decision = self.resolver.decide(state, environment)
        if decision.kind is not DecisionKind.SUCCEED:
            return decision
        for item in decision.output["candidate_sets"]:
            if len(item["candidate_ids"]) != 1 or (item["hole_kind"] == "entity" and not item["authoritative"]):
                return AgentDecision.block("Semantic ambiguity requires a binding before physical cost selection")
        return AgentDecision.call(PlannedToolCall("bind-plan-execute", BIND_PLAN_EXECUTE,
            {"resolution": decision.output}), "Apply resolved identities and constraints before native planning")


def run_agentic_semantic_query(tool: BoundSemanticExecutionTool, question: str, *,
        resolution_tools: ToolRegistry, config: SelectiveResolutionConfig = SelectiveResolutionConfig()):
    """Run one finite query goal; NL interpretation and benchmark scoring are separate."""
    started = time.perf_counter()
    registry = ToolRegistry()
    for spec in resolution_tools.specs():
        registry.register(resolution_tools.get(spec.name))
    registry.register(tool)
    resolver = SelectiveSemanticResolutionPolicy(tool.program, question, config)
    goal = build_selective_resolution_goal(tool.program, config)
    goal = replace(goal, goal_id="semantic-query:" + tool.program.program_id,
        objective="Resolve declared semantic slots and execute their constrained meaning",
        allowed_tools=(*goal.allowed_tools, BIND_PLAN_EXECUTE),
        max_steps=goal.max_steps + 2, max_tool_calls=goal.max_tool_calls + 1,
        success_criteria=(*goal.success_criteria, "all required bindings affect executable meaning", "selected plan returns a terminal result"))
    state = GoalLoop().run(goal, SemanticExecutionPolicy(resolver), AgentEnvironment("semantic-query", registry))
    metrics = [o.payload.get("metrics", {}) for o in state.observations if o.kind == "tool_result"]
    return {"success": state.status is GoalStatus.SUCCEEDED, "state": state.to_dict(),
        "end_to_end_ms": (time.perf_counter() - started) * 1000,
        "backend_remote_calls": sum(m.get("remote_calls", 0) for m in metrics),
        "resolution_external_calls": sum(m.get("external_calls", 0) for m in metrics),
        "input_tokens": sum(m.get("input_tokens", 0) for m in metrics),
        "output_tokens": sum(m.get("output_tokens", 0) for m in metrics)}


def run_frozen_semantic_query(*, program: SemanticGraphProgram, question: str,
        operator_sources, catalog_root, catalog_hash, sources, backends, backend_clients,
        clarification_tool=None, max_candidates=64, max_observation_calls=128,
        max_remote_calls=16, snapshot=None, config=SelectiveResolutionConfig(), static_backend_order=None,
        plan_memory=None):
    """Use one pinned prepared bundle for resolution and executable bindings.

    The model-free deterministic API above is unchanged. This entry does not
    build catalogs, inspect raw datasets or retry missing preparation.
    """
    from xgap.catalog.bundle import FrozenResolutionBundle
    from xgap.tools.artifact_resolution import artifact_catalog_tool, artifact_ontology_tool
    from xgap.tools.resolution import USER_CLARIFY_TOOL

    if clarification_tool is not None and clarification_tool.spec.name != USER_CLARIFY_TOOL:
        raise ValueError("Only an explicit user-clarification tool may supplement the frozen bundle")
    started = time.perf_counter()
    try:
        bundle = FrozenResolutionBundle.load(catalog_root, expected_bundle_hash=catalog_hash)
    except (OSError, ValueError) as error:
        return {"success": False, "status": "catalog_unavailable", "error": str(error),
                "expected_bundle_hash": catalog_hash, "backend_remote_calls": 0,
                "resolution_external_calls": 0, "input_tokens": 0, "output_tokens": 0,
                "end_to_end_ms": (time.perf_counter() - started) * 1000}
    registry = ToolRegistry()
    registry.register(artifact_catalog_tool(bundle.catalog))
    if bundle.ontology:
        registry.register(artifact_ontology_tool(bundle.ontology))
    if clarification_tool is not None:
        registry.register(clarification_tool)
    program = replace(program, metadata={**program.metadata, "resolution_bundle": bundle.identity})
    tool = BoundSemanticExecutionTool(program, operator_sources, bundle.bindings,
        sources, backends, backend_clients, max_candidates, max_observation_calls,
        max_remote_calls, snapshot, static_backend_order, plan_memory)
    result = run_agentic_semantic_query(tool, question, resolution_tools=registry, config=config)
    return {**result, "status": result["state"]["status"], "resolution_bundle": bundle.identity,
            "end_to_end_ms": (time.perf_counter() - started) * 1000}
