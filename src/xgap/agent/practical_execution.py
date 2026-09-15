"""Follow one realized branch of a precomputed strong policy via GoalLoop."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import time

from xgap.agent.contracts import AgentDecision, GoalSpec, GoalStatus, PlannedToolCall
from xgap.agent.environment import AgentEnvironment
from xgap.agent.loop import GoalLoop
from xgap.agent.practical_planning import PracticalSemanticDomain, strong_search_view
from xgap.agent.practical_tools import lookup_practical_capabilities
from xgap.agent.strong_planning import ResourceUsage, StrongSearchLimits, search_strong_policy
from xgap.runtime.contracts import FederatedExecutionPlan
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.tool import FederatedExecutionTool
from xgap.runtime.planning_budget import CooperativePlanningBudget
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin, ToolRegistry
from xgap.tools.contracts import ToolEffect, ToolResult, ToolSpec, ToolStatus


FINAL_TOOL = "practical.execute_final"


@dataclass
class FrozenClarificationTool:
    """Development authority oracle; only invoke reads the separate binding file.

    The file contains semantic choices, never answer rows or compiled queries.
    Its complete binding map is private to the provider; one invocation exposes
    exactly the requested choice. No preflight loads its response into search.
    """
    response_path: Path
    name: str = "practical.clarify"
    expected_sha256: str | None = None

    @property
    def spec(self):
        return ToolSpec(self.name, "Reveal only the requested frozen semantic binding",
            {"type": "object"}, "scoped_binding", ToolEffect.READ_ONLY)

    def invoke(self, arguments, context):
        started = time.perf_counter()
        try:
            if self.expected_sha256 is None:
                data = json.loads(Path(self.response_path).read_text())
            else:
                # Do not read even the binding-only fixture during planning.
                with Path(self.response_path).open('rb') as stream:
                    content = stream.read(65537)
                if len(content) > 65536 or hashlib.sha256(content).hexdigest() != self.expected_sha256:
                    raise ValueError('Frozen clarification response size/hash mismatch')
                data = json.loads(content)
            if set(data) != {"schema_version", "program_sha256", "source_id", "version", "bindings"} or data["schema_version"] != "xgap-clarification-bindings-v1":
                raise ValueError("Clarification fixture may contain only the declared binding schema")
            if any(data[k] != arguments[k] for k in ("program_sha256", "source_id", "version")):
                raise ValueError("Clarification authority/version/query mismatch")
            slot = arguments["slot"]
            candidate = data["bindings"].get(slot)
            if candidate not in arguments["candidates"]:
                return ToolResult.unavailable(self.name, "Requested binding is outside the declared outcome set")
            return ToolResult.success(self.name, {k: arguments[k] for k in ("slot", "program_sha256", "source_id", "version")}
                | {"candidate_id": candidate}, metrics={"model_calls": 0, "tokens": 0, "remote_calls": 0,
                    "elapsed_ms": (time.perf_counter() - started) * 1000, "clarification_calls": 1})
        except (OSError, ValueError, KeyError, TypeError) as error:
            return ToolResult.error_result(self.name, str(error))


@dataclass
class _FinalTool:
    leaves: dict
    backend_clients: dict

    @property
    def spec(self):
        return ToolSpec(FINAL_TOOL, "Execute the one selected policy terminal", {"type": "object"},
                        "typed_federated_result", ToolEffect.EXTERNAL, remote=True)

    def invoke(self, arguments, context):
        terminal = self.leaves[arguments["terminal_id"]]
        payload = terminal.payload
        plan = FederatedExecutionPlan.from_dict(payload["physical_plan"])
        registry = BackendPluginRegistry()
        for backend_id in {n.parameters["backend_id"] for n in plan.nodes if "backend_id" in n.parameters}:
            registry.register(NativeBackendPlugin(backend_id, self.backend_clients[backend_id]))
        result = FederatedExecutionTool(FederatedScheduler(BackendInvokeTool(registry), retention="roots")).invoke(
            {"plan": plan.to_dict()}, context)
        return ToolResult(FINAL_TOOL, result.status, value={**payload, "result": result.to_dict()},
                          error=result.error, metrics={**result.metrics, "final_plan_executions": 1})


@dataclass
class _Follower:
    current: object
    action_specs: dict
    limits: StrongSearchLimits
    seen: int = 0
    usage: ResourceUsage = ResourceUsage()

    def decide(self, state, environment):
        observations = [o for o in state.observations if o.kind == "tool_result"]
        for observation in observations[self.seen:]:
            self.seen += 1
            result = observation.payload
            if observation.source == FINAL_TOOL:
                if result["status"] == ToolStatus.SUCCESS.value:
                    return AgentDecision.succeed("Selected strong-policy terminal executed", result["value"])
                return AgentDecision.fail(result["error"])
            action = self.current.action
            if action is None or observation.source != action.tool_name:
                return AgentDecision.fail("Observation does not match the selected policy action")
            spec = self.action_specs[action.action_id]
            metrics = result.get("metrics", {})
            try:
                actual = ResourceUsage(*(metrics.get(k, getattr(spec.resources, k)) for k in asdict(self.usage)))
            except ValueError:
                return AgentDecision.fail("Invalid actual acquisition resource counters")
            self.usage = self.usage + actual
            if not actual.fits(spec.resources) or not self.usage.fits(self.limits.resources):
                return AgentDecision.fail("Acquisition exceeded its declared resource reservation")
            if result["status"] != ToolStatus.SUCCESS.value:
                label = "unavailable" if result["status"] == ToolStatus.UNAVAILABLE.value else "error"
                if dict(spec.outcomes).get(label, "not-declared") is not None:
                    return AgentDecision.fail("Unmodeled failed acquisition; no automatic retry")
            else:
                value = result.get("value")
                if not isinstance(value, dict) or set(value) != {"slot", "candidate_id", "program_sha256", "source_id", "version"}:
                    return AgentDecision.fail("Binding response must expose only one scoped semantic choice")
                if any(value[k] != action.arguments[k] for k in ("slot", "program_sha256", "source_id", "version")):
                    return AgentDecision.fail("Observed binding provenance does not match the planned authority")
                labels = [label for label, candidate in spec.outcomes if candidate == value["candidate_id"] and candidate is not None]
                if len(labels) != 1:
                    return AgentDecision.fail("Observed binding is not a unique declared outcome")
                label = labels[0]
            children = dict(self.current.children)
            if label not in children:
                return AgentDecision.fail("Observed outcome has no strong continuation")
            self.current = children[label]
        if self.current.terminal is not None:
            return AgentDecision.call(PlannedToolCall("final", FINAL_TOOL,
                {"terminal_id": self.current.terminal.terminal_id}), "Execute the selected complete query once")
        action = self.current.action
        return AgentDecision.call(PlannedToolCall(f"state-{self.current.state_id}:{action.action_id}",
            action.tool_name, action.arguments), "Follow the strong policy's selected acquisition action")


def run_practical_semantic_query(program, *, initial_state, resolution_tools=None, backend_clients,
                                 limits=StrongSearchLimits(), execute=True, **domain_options):
    started = time.perf_counter()
    registry = resolution_tools or ToolRegistry()
    available = {s.name for s in registry.specs()}
    declared = tuple(domain_options.get("actions", ()))
    missing = [a.action_id for a in declared if a.tool_name not in available]
    domain_options["actions"] = tuple(a for a in declared if a.tool_name in available)
    # A known missing adapter is a planning capability restriction, not a
    # post-selection reason to discard a plan when another replica is usable.
    admitted_sources, capabilities = lookup_practical_capabilities(
        domain_options['sources'], domain_options['backends'], backend_clients)
    domain_options['sources'] = admitted_sources
    domain = PracticalSemanticDomain(program, **domain_options)
    domain.validate_state(initial_state)
    checkpoint=CooperativePlanningBudget(limits.planning_ms)
    domain.planning_checkpoint=checkpoint
    search_domain,pruning=strong_search_view(domain)
    search = search_strong_policy(initial_state, search_domain, limits=limits)
    report = {"schema_version": "xgap-practical-answer-v1", "success": False, "mode": domain.mode.mode,
        "search": search.to_dict(), "answer_rows": None, "final_plan_executions": 0,
        "backend_remote_calls": 0, "model_calls": 0, "tokens": 0, "clarification_calls": 0,
        "acquisition_remote_calls": 0, "acquisition_ms": 0, "capability_lookup": capabilities,
        "missing_acquisition_tools": missing, "planning_failures": domain.failures,
        "acquisition_actions": [asdict(a) for a in domain.action_specs],
        "acquisition_search_order": pruning['search_order'],
        "compiled_states": domain.compiled_states, "estimator_calls": domain.estimator_calls,
        "semantic_discrepancy_upper_bound": None, "discrepancy_status": "metric_deferred",
        "optimality_certified": False, "actual_acquisition_usage_complete": True, "status": search.status,
        "limits": asdict(limits), "strong_scope": "declared finite outcomes and admitted trusted skeleton"}
    report['cooperative_planning_budget']=checkpoint.to_dict()
    report['acquisition_pruning']=pruning
    if search.policy is None or not execute:
        report.update(status="planned" if search.policy else search.status,
                      end_to_end_ms=(time.perf_counter() - started) * 1000)
        return report
    leaves = {}
    def collect(node):
        if node.terminal:
            # Same native plan may carry distinct evidence; retain terminal identity.
            leaves[node.terminal.terminal_id] = node.terminal
        for _, child in node.children:
            collect(child)
    collect(search.policy)
    needed = {n["parameters"]["backend_id"] for t in leaves.values()
              for n in t.payload["physical_plan"]["nodes"] if "backend_id" in n["parameters"]}
    if not needed <= backend_clients.keys():
        report.update(status="backend_unavailable", end_to_end_ms=(time.perf_counter() - started) * 1000)
        return report
    execution_registry = ToolRegistry()
    for spec in registry.specs():
        execution_registry.register(registry.get(spec.name))
    execution_registry.register(_FinalTool(leaves, backend_clients))
    follower = _Follower(search.policy, {a.action_id: a for a in domain.action_specs}, limits)
    goal = GoalSpec("practical:" + program.program_id, "Follow one strong policy to a typed graph result",
        ("All declared acquisition outcomes have complete continuations", "Execute one selected final plan"),
        tuple(s.name for s in execution_registry.specs()), max_steps=limits.max_depth + 2,
        max_tool_calls=limits.max_depth + 1)
    state = GoalLoop().run(goal, follower, AgentEnvironment("practical-query", execution_registry))
    observations = [o for o in state.observations if o.kind == "tool_result"]
    for observation in observations:
        metrics = observation.payload.get("metrics", {})
        if observation.source == FINAL_TOOL:
            report["final_plan_executions"] += 1
            report["backend_remote_calls"] += metrics.get("remote_calls", 0)
        else:
            action_id = observation.payload['call_id'].split(':', 1)[1]
            spec = next(a for a in domain.action_specs if a.action_id == action_id)
            report['clarification_calls'] += int(spec.authority == 'clarification')
            report['acquisition_ms'] += metrics.get('elapsed_ms', 0)
            for key in ("model_calls", "tokens", "remote_calls"):
                reported = 'acquisition_remote_calls' if key == 'remote_calls' else key
                if key not in metrics and getattr(spec.resources, key):
                    report[reported] = None
                    report['actual_acquisition_usage_complete'] = False
                elif report[reported] is not None:
                    report[reported] += metrics.get(key, 0)
    report.update(success=state.status is GoalStatus.SUCCEEDED, status=state.status.value,
        execution_state=state.to_dict(), resource_reservation_used=asdict(follower.usage),
        end_to_end_ms=(time.perf_counter() - started) * 1000)
    if report["success"]:
        report.update(answer_rows=state.output["result"]["value"]["final_rows"],
                      execution=state.output, answer_quality_verified=False)
    return report
