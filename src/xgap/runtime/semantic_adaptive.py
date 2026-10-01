"""One executed source prefix, polynomial residual placement, exact result reuse."""

from dataclasses import asdict, dataclass, replace
import time
from uuid import uuid4

from xgap.runtime.adaptive import AdaptiveFederatedExecutor, ReplanPolicy
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.planning import FederatedPlanSelector, RemoteEstimate, _NodeEstimate
from xgap.runtime.scheduler import FederatedScheduler
from xgap.tools.contracts import ToolResult, ToolStatus
from xgap.runtime.tool import FEDERATED_EXECUTION_TOOL


@dataclass(frozen=True)
class SemanticPrefixPolicy:
    source_operator: str | None = None
    replan_policy: ReplanPolicy = ReplanPolicy()

    def __post_init__(self):
        if self.source_operator is not None and (not isinstance(self.source_operator, str) or not self.source_operator.strip()):
            raise ValueError("Prefix source must be a nonempty semantic source ID")
        if not isinstance(self.replan_policy, ReplanPolicy):
            raise ValueError("Prefix adaptation requires a finite ReplanPolicy")

    def to_dict(self):
        return {"source_operator": self.source_operator, "replan_policy": asdict(self.replan_policy),
            "scope": "one_input_free_source_prefix", "max_prefixes": 1,
            "default_rule": "minimum historical local readiness, then source ID"}

    def eligible(self, space):
        sources = {op.operator_id for op in space.program.operators if op.operator_id in space.options and not op.input_ids}
        if not sources or (self.source_operator is not None and self.source_operator not in sources):
            raise ValueError("Prefix policy needs an admitted input-free semantic source")
        return (self.source_operator,) if self.source_operator is not None else tuple(sorted(sources))

    def choose(self, space, candidate, snapshot):
        placements = candidate.plan.metadata["source_bindings"]
        choices = []
        for source in self.eligible(space):
            backend = placements[source]
            nodes = space.local_nodes[source, backend]
            prefix = replace(candidate.plan, plan_id=candidate.plan.plan_id + "/prefix:" + source,
                nodes=nodes, roots=(space.fragments[source, backend].output,), metadata={"source_operator": source})
            cost = FederatedPlanSelector().estimate(prefix, snapshot).predicted_latency_ms
            choices.append((cost, source, prefix))
        _, source, prefix = min(choices, key=lambda item: item[:2])
        return source, prefix


class ResidualPlanSelector(FederatedPlanSelector):
    """Original cost recurrence with validated, zero-ready completed constants."""

    def __init__(self, prefix_plan, prefix_results):
        self.prefix_plan = prefix_plan
        self.completed = FederatedScheduler._validate_initial_results(
            {n.node_id: n for n in prefix_plan.nodes}, prefix_results)
        if set(self.completed) != {n.node_id for n in prefix_plan.nodes}:
            raise ValueError("Residual planning needs every completed prefix result")
        for result in self.completed.values():
            if type(result.output_bytes) is not int or result.output_bytes < 0:
                raise ValueError("Completed output bytes must be a nonnegative integer")
        self.states = {key: _NodeEstimate(0.0, result.row_count,
            max(1.0, result.output_bytes / max(result.row_count, 1))) for key, result in self.completed.items()}

    def estimate(self, plan, snapshot):
        AdaptiveFederatedExecutor._reusable_prefix(self.prefix_plan, plan, self.completed)
        return super().estimate(plan, snapshot)

    def estimate_local(self, plan, snapshot):
        # Local views either contain the whole fixed source or another source.
        # Full candidates and lower-bound views always use estimate() above.
        if set(self.completed) & {n.node_id for n in plan.nodes}:
            AdaptiveFederatedExecutor._reusable_prefix(self.prefix_plan, plan, self.completed)
        return super().estimate(plan, snapshot)

    def _estimate_node(self, node, estimates, snapshot):
        if node.node_id in self.states:
            return self.states[node.node_id], 0.0, 0, None
        return super()._estimate_node(node, estimates, snapshot)


def residual_space(space, initial, source, prefix_plan, prefix_results):
    SemanticPrefixPolicy(source_operator=source).eligible(space)
    backend = initial.plan.metadata["source_bindings"][source]
    if backend not in space.options[source]:
        raise ValueError("Completed source backend is outside the admitted placement domain")
    if (prefix_plan.nodes != space.local_nodes[source, backend]
            or prefix_plan.roots != (space.fragments[source, backend].output,)):
        raise ValueError("Residual domain requires the entire selected source fragment")
    selector = ResidualPlanSelector(prefix_plan, prefix_results)
    AdaptiveFederatedExecutor._reusable_prefix(prefix_plan, initial.plan, selector.completed)
    remaining = replace(space, options={**space.options, source: (backend,)}, baseline=initial)
    return remaining, selector


def execute_semantic_prefix(space, backend_tool, policy, snapshot, initial, selection, record, goal_id):
    """Execute once, retain failure evidence, and never reacquire/retry a prefix."""
    detail = record["prefix"]
    started = time.perf_counter()
    planning_ms = 0.0
    planned_at = None
    try:
        planned_at = time.perf_counter()
        source, prefix = policy.choose(space, initial, snapshot)
        backend = initial.plan.metadata["source_bindings"][source]
        # Exact node identity/closure is checked before the first prefix call.
        initial_nodes = {n.node_id: n for n in initial.plan.nodes}
        if any(initial_nodes.get(n.node_id) != n for n in prefix.nodes):
            raise ValueError("Prefix nodes differ from the initially selected plan")
        detail.update(source_operator=source, fixed_source_bindings={source: backend},
            history_snapshot=snapshot.to_dict(), initial_selection=selection, probe_plan=prefix.to_dict())
        planning_ms += (time.perf_counter() - planned_at) * 1000
        planned_at = None
        scheduler = FederatedScheduler(backend_tool)
        probe = scheduler.execute(prefix, goal_id=goal_id + ":prefix")
        detail["probe_run"] = probe.to_dict()
        detail["prefix_remote_calls"] = record["execution_calls"] = probe.total_remote_calls
        if not probe.success:
            raise ValueError("Semantic execution prefix failed; no continuation or retry")
        planned_at = time.perf_counter()
        results = {r.node_id: r for r in probe.node_results}
        version = snapshot.version + "/prefix:" + uuid4().hex
        updates, reasons = {}, []
        for node in sorted(prefix.nodes, key=lambda n: n.node_id):
            if node.kind not in (R.REMOTE_QUERY, R.REMOTE_BIND_QUERY):
                continue
            key = node.parameters["observation_key"]
            observed = RemoteEstimate.from_runtime_result(key, results[node.node_id],
                source="executed semantic prefix", version=version)
            expected = snapshot.by_key[key]
            if observed.backend_id != expected.backend_id:
                raise ValueError("Executed prefix observation changed backend identity")
            for name, before, after, threshold in (
                ("rows", expected.row_count, observed.row_count, policy.replan_policy.cardinality_factor_threshold),
                ("latency", expected.elapsed_ms, observed.elapsed_ms, policy.replan_policy.latency_factor_threshold)):
                factor = AdaptiveFederatedExecutor._factor(before, after)
                if factor >= threshold:
                    reasons.append(f"{node.node_id}:{name}_factor={factor:g}")
            updates[key] = observed
        updated = snapshot.with_estimates(tuple(updates.values()), version=version)
        remaining, selector = residual_space(space, initial, source, prefix, results)
        detail.update(updated_snapshot=updated.to_dict(), replan_reasons=reasons,
            observation_update_rule="last lexical node ID for repeated observation key",
            residual_domain={"local_options": remaining.local_option_count,
                "possible_placement_count": remaining.possible_placement_count,
                "max_remote_calls_including_prefix": remaining.max_remote_calls},
            residual_initial_estimate=selector.estimate(initial.plan, updated).to_dict())
        chosen = initial
        if reasons and policy.replan_policy.max_replans == 1:
            detail["selection_runs"] += 1
            chosen, after = remaining.select(updated, _selector=selector)
            after["certificate"] = {**after["certificate"], "objective": "estimated_remaining_critical_path_ms",
                "fixed_source_bindings": {source: backend}, "completed_node_ids": sorted(results)}
            detail["selection_after_prefix"] = after
            selection = after
            detail["replan_count"] = int(chosen.plan.plan_id != initial.plan.plan_id)
        reusable = AdaptiveFederatedExecutor._reusable_prefix(prefix, chosen.plan, results)
        detail.update(reused_node_ids=sorted(reusable),
            residual_executed_estimate=selector.estimate(chosen.plan, updated).to_dict())
        record["selected_plan"] = chosen.plan.to_dict()
        record["selection"] = selection
        record["candidate_count"] = selection["evaluated_plan_count"]
        planning_ms += (time.perf_counter() - planned_at) * 1000
        planned_at = None
        final = scheduler.execute(chosen.plan, goal_id=goal_id + ":continuation", initial_results=reusable)
        detail["continuation_run"] = final.to_dict()
        # Final node_results already include reused prefix results.
        record["execution_calls"] = final.total_remote_calls
        detail["continuation_new_remote_calls"] = final.total_remote_calls - probe.total_remote_calls
        detail["state"] = "completed" if final.success else "continuation_failed"
        combined = replace(final, elapsed_ms=probe.elapsed_ms + final.elapsed_ms)
        return ToolResult(FEDERATED_EXECUTION_TOOL, ToolStatus.SUCCESS if final.success else ToolStatus.ERROR,
            value=combined.to_dict(), error=None if final.success else "Semantic continuation failed",
            metrics={"elapsed_ms": combined.elapsed_ms, "remote_calls": final.total_remote_calls,
                     "bytes_moved": final.total_bytes_moved, "row_count": len(final.final_rows)})
    except (OSError, ValueError):
        detail["state"] = "failed"
        raise
    finally:
        if planned_at is not None:
            planning_ms += (time.perf_counter() - planned_at) * 1000
        detail["elapsed_ms"] = (time.perf_counter() - started) * 1000
        detail["planning_ms"] = planning_ms
