"""Feasible-first search for a strong policy in a finite-depth AND/OR tree.

Expansion is local/symbolic: this module cannot invoke any external tool. OR
chooses an action; AND retains ALL declared outcomes. Cost-ordered completion
finds an incumbent before spending a bounded allowance on root alternatives.
Scores are estimates, never admissible bounds or global optimality certificates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import time
from typing import Any, Hashable, Iterable, Protocol


@dataclass(frozen=True)
class ResourceUsage:
    model_calls: int = 0
    tokens: int = 0
    remote_calls: int = 0

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in asdict(self).values()):
            raise ValueError("Resource counters must be nonnegative integers")

    def __add__(self, other):
        return ResourceUsage(*(getattr(self, k) + getattr(other, k) for k in asdict(self)))

    def fits(self, limit):
        return all(getattr(self, k) <= getattr(limit, k) for k in asdict(self))


@dataclass(frozen=True)
class StrongSearchLimits:
    max_depth: int = 4
    max_states: int = 128
    max_actions: int = 128
    max_outcomes: int = 16
    max_terminals_per_state: int = 8
    planning_ms: float = 2000.0
    improvement_actions: int = 2
    resources: ResourceUsage = field(default_factory=lambda: ResourceUsage(1, 4096, 32))

    def __post_init__(self):
        for name, upper in (("max_depth", 32), ("max_states", 4096), ("max_actions", 4096),
                            ("max_outcomes", 256), ("max_terminals_per_state", 256),
                            ("improvement_actions", 4096)):
            value = getattr(self, name)
            lower = 1 if name in ("max_states", "max_outcomes", "max_terminals_per_state") else 0
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must lie in [{lower},{upper}]")
        _cost(self.planning_ms)
        if self.planning_ms <= 0:
            raise ValueError("planning_ms must be positive")


def _cost(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite nonnegative estimate")


@dataclass(frozen=True)
class TerminalAlternative:
    terminal_id: str
    estimated_cost: float | None
    payload: Any
    resources: ResourceUsage = field(default_factory=ResourceUsage)

    def __post_init__(self):
        if not self.terminal_id:
            raise ValueError("Terminal needs an identifier")
        if self.estimated_cost is not None:
            _cost(self.estimated_cost)


@dataclass(frozen=True)
class DeclaredOutcome:
    outcome_id: str
    state: Hashable


@dataclass(frozen=True)
class AcquisitionAlternative:
    action_id: str
    tool_name: str
    arguments: dict
    outcomes: tuple[DeclaredOutcome, ...]
    estimated_cost: float | None
    resources: ResourceUsage = field(default_factory=ResourceUsage)
    outcomes_exhaustive: bool = True

    def __post_init__(self):
        if self.estimated_cost is not None:
            _cost(self.estimated_cost)
        ids = [o.outcome_id for o in self.outcomes]
        if not self.action_id or not self.tool_name or not ids or any(not k for k in ids) or len(set(ids)) != len(ids):
            raise ValueError("Action needs nonempty, distinct declared outcomes")


class StrongPlanningDomain(Protocol):
    def terminals(self, state: Hashable) -> Iterable[TerminalAlternative]: ...
    def actions(self, state: Hashable) -> Iterable[AcquisitionAlternative]: ...


@dataclass(frozen=True)
class PolicyNode:
    state_id: int
    estimated_cost: float | None
    terminal: TerminalAlternative | None = None
    action: AcquisitionAlternative | None = None
    children: tuple[tuple[str, "PolicyNode"], ...] = ()

    def to_dict(self):
        return {"state_id": self.state_id, "estimated_cost": self.estimated_cost,
                "terminal_id": self.terminal.terminal_id if self.terminal else None,
                "action_id": self.action.action_id if self.action else None,
                "children": {label: child.to_dict() for label, child in self.children}}


@dataclass(frozen=True)
class PolicySearchResult:
    policy: PolicyNode | None
    status: str
    stop_reason: str
    expanded_states: int
    retained_states: int
    generated_actions: int
    elapsed_ms: float
    first_feasible_ms: float | None
    first_feasible_estimated_cost: float | None
    action_records: tuple[dict, ...]
    limit_events: tuple[str, ...]
    optimality_certified: bool = False
    root_lower_bound: float | None = None
    incumbent_cost_upper_bound: float | None = None

    def to_dict(self):
        return {"schema_version": "xgap-strong-policy-search-v1", "status": self.status,
                "stop_reason": self.stop_reason, "strong": self.policy is not None,
                "policy": self.policy.to_dict() if self.policy else None,
                "expanded_states": self.expanded_states, "retained_states": self.retained_states,
                "generated_actions": self.generated_actions, "elapsed_ms": self.elapsed_ms,
                "first_feasible_ms": self.first_feasible_ms,
                "first_feasible_estimated_cost": self.first_feasible_estimated_cost,
                "selected_estimated_cost": self.policy.estimated_cost if self.policy else None,
                "cost_objective": "estimated acquisition plus worst-outcome terminal cost",
                "optimality_certified": False, "root_lower_bound": None,
                "incumbent_cost_upper_bound": None, "action_records": list(self.action_records),
                "limit_events": list(self.limit_events), "external_calls_during_search": 0}


def search_strong_policy(root, domain: StrongPlanningDomain, *, limits=StrongSearchLimits(),
                         clock=time.perf_counter):
    """Return the best discovered COMPLETE strong policy, or no feasible plan.

    S states/A actions/depth H are global caps, not per recursive call. Each
    action reserves space for all outcomes atomically. Reaching a cap never
    replaces a completed incumbent with a partial AND branch. Child completion
    is feasible-first; root alternatives receive only the remaining improvement
    action allowance. No probability distribution or admissible heuristic needed.
    """
    started = clock()
    retained, expanded, generated = 1, 0, 0
    records, events = [], []
    first_ms = first_cost = first_action_count = None

    def elapsed():
        return (clock() - started) * 1000

    def stopped(*, action=False):
        if elapsed() >= limits.planning_ms:
            events.append("planning_deadline")
            return True
        if action and first_action_count is not None and generated - first_action_count >= limits.improvement_actions:
            events.append("improvement_budget")
            return True
        return False

    def found(policy):
        nonlocal first_ms, first_cost, first_action_count
        if first_ms is None:
            first_ms, first_cost, first_action_count = elapsed(), policy.estimated_cost, generated

    def solve(state, state_id, depth, usage, history):
        nonlocal retained, expanded, generated
        if stopped():
            return None
        expanded += 1
        best = None
        # The domain is responsible for polynomial local candidate generation.
        from itertools import islice
        def rank(node):
            return (node.estimated_cost is None, node.estimated_cost or 0)
        for terminal in islice(domain.terminals(state), limits.max_terminals_per_state):
            if (usage + terminal.resources).fits(limits.resources):
                candidate = PolicyNode(state_id, terminal.estimated_cost, terminal=terminal)
                if best is None or rank(candidate) < rank(best):
                    best = candidate
                    if not depth:
                        found(best)
            if elapsed() >= limits.planning_ms:
                events.append("planning_deadline")
                break
        if best is not None:
            if depth:
                return best
            found(best)
        if depth >= limits.max_depth:
            events.append("depth_budget")
            return best
        if stopped(action=True):
            return best
        actions = iter(domain.actions(state))
        while not stopped(action=True):
            if generated >= limits.max_actions:
                events.append("action_budget")
                break
            try:
                action = next(actions)
            except StopIteration:
                break
            generated += 1
            record = {"state_id": state_id, "action_id": action.action_id,
                      "acquisition_estimated_cost": action.estimated_cost,
                      "outcomes": [o.outcome_id for o in action.outcomes], "status": "declared"}
            records.append(record)
            if not action.outcomes_exhaustive or action.action_id in history:
                record["status"] = "incomplete_outcome_model_or_repeated_action"
                continue
            next_usage = usage + action.resources
            if not next_usage.fits(limits.resources):
                record["status"] = "resource_budget"
                events.append("resource_budget")
                continue
            count = len(action.outcomes)
            if count > limits.max_outcomes or retained + count > limits.max_states:
                record["status"] = "outcome_or_state_budget"
                events.append(record["status"])
                continue
            ids = tuple(range(retained + 1, retained + count + 1))
            retained += count
            record["child_states"] = dict(zip(record["outcomes"], ids))
            children = []
            for outcome, child_id in zip(action.outcomes, ids):
                child = solve(outcome.state, child_id, depth + 1, next_usage,
                              history | {action.action_id})
                if child is None:
                    break
                children.append((outcome.outcome_id, child))
            if len(children) != count:
                record["status"] = "no_complete_strong_continuation"
                continue
            costs = [c.estimated_cost for _, c in children]
            score = (None if action.estimated_cost is None or any(c is None for c in costs)
                     else action.estimated_cost + max(costs))
            candidate = PolicyNode(state_id, score,
                                   action=action, children=tuple(children))
            record.update(status="strong", estimated_cost=candidate.estimated_cost)
            if best is None or rank(candidate) < rank(best):
                best = candidate
            if depth:
                return best
            found(best)
        return best

    policy = solve(root, 1, 0, ResourceUsage(), frozenset())
    return PolicySearchResult(policy, "feasible" if policy else "no_feasible_plan",
        events[-1] if events else "declared_alternatives_finished", expanded, retained, generated,
        elapsed(), first_ms, first_cost, tuple(records), tuple(dict.fromkeys(events)))
