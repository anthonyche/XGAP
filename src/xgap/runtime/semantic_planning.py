"""Bounded source-placement enumeration and costed semantic execution.

A logical source declares complete equivalent replicas of one snapshot. This is
a deployment assertion, not something inferred from endpoint availability.
Compilation is pure; observations and execution use existing registered tools.
"""

from dataclasses import dataclass, replace
import hashlib
from itertools import product
import json
import math
import time
from typing import Mapping
from uuid import uuid4

from xgap.compilers.errors import CompilerError
from xgap.infrastructure.runtime import QueryArtifact
from xgap.runtime.contracts import RuntimeNode, RuntimeNodeKind as R
from xgap.runtime.observations import PlanObservationCollector, PlanObservationRequest
from xgap.runtime.planning import FederatedPlanCandidate, FederatedPlanSelector, PlanObservationSnapshot
from xgap.runtime.scheduler import FederatedScheduler
from xgap.runtime.semantic_compiler import SemanticBackend, compile_semantic_program
from xgap.runtime.semantic_memory import SemanticPlanMemory
from xgap.runtime.tool import FederatedExecutionTool
from xgap.semantic.program import SemanticGraphProgram, SemanticOperatorKind as S, SemanticProgramError
from xgap.tools.backends import BackendInvokeTool, BackendObservationCatalog, BackendOperation
from xgap.tools.contracts import ToolContext, ToolStatus


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class LogicalSource:
    source_id: str
    snapshot_version: str
    replica_backend_ids: tuple[str, ...]

    def __post_init__(self):
        if not self.source_id or not self.snapshot_version or not self.replica_backend_ids:
            raise ValueError("Logical source needs an identity, snapshot version and replicas")
        if len(set(self.replica_backend_ids)) != len(self.replica_backend_ids):
            raise ValueError("Replica backend IDs must be unique")


@dataclass(frozen=True)
class SemanticPlanSpace:
    candidates: tuple[FederatedPlanCandidate, ...]
    observation_requests: tuple[PlanObservationRequest, ...]
    observation_catalogs: Mapping[str, BackendObservationCatalog]
    rejected_placements: tuple[dict, ...]
    enumeration_ms: float


def _instrument_semantic_plan(plan, identities, equivalence_key):
    artifacts, requests = {}, {}
    candidate_id = plan.plan_id + "/" + _hash({"meaning": equivalence_key, "placement": plan.metadata["source_bindings"]})[:20]
    exchanges = {node.node_id: node.node_id + "/exchange" for node in plan.nodes if node.kind is R.REMOTE_QUERY}
    nodes = []
    for node in plan.nodes:
        if node.kind is R.REMOTE_QUERY:
            backend = node.parameters["backend_id"]
            artifact = QueryArtifact.from_dict(node.parameters["artifact"])
            owner = node.semantic_operator_ids[0]
            key = _hash({"backend": backend, "source": identities[owner], "artifact": artifact.to_dict()})
            artifacts.setdefault(backend, {})[key] = artifact
            requests[key] = PlanObservationRequest("observe-" + key, key, backend,
                BackendOperation.PROFILE, {"query_id": key})
            nodes.append(replace(node, parameters={**node.parameters, "observation_key": key}))
            nodes.append(RuntimeNode(exchanges[node.node_id], R.EXCHANGE, (node.node_id,),
                                     semantic_operator_ids=node.semantic_operator_ids))
        else:
            nodes.append(replace(node, inputs=tuple(exchanges.get(i, i) for i in node.inputs)))
    metadata = {**plan.metadata, "logical_sources": identities,
                "cost_model": "m15-linear-row-proxy; uncalibrated unless independently supplied"}
    plan = replace(plan, plan_id=candidate_id, nodes=tuple(nodes),
                   roots=tuple(exchanges.get(i, i) for i in plan.roots), metadata=metadata)
    return FederatedPlanCandidate(plan, equivalence_key), artifacts, requests


def enumerate_semantic_plans(program: SemanticGraphProgram, *,
        operator_sources: Mapping[str, str], sources: Mapping[str, LogicalSource],
        backends: Mapping[str, SemanticBackend], max_candidates: int = 64,
        max_observation_calls: int = 128, max_remote_calls: int = 16,
        max_parallelism: int = 4) -> SemanticPlanSpace:
    """Enumerate declared equivalent placements, never arbitrary online engines."""
    started = time.perf_counter()
    for value in (max_candidates, max_observation_calls):
        if type(value) is not int or value <= 0:
            raise ValueError("Enumeration and observation bounds must be positive integers")
    source_ops = sorted(op.operator_id for op in program.operators if op.kind in (S.MATCH, S.TRAVERSE))
    if set(operator_sources) != set(source_ops):
        raise SemanticProgramError("Logical source bindings must cover every Match/Traverse exactly")
    choices, identities = [], {}
    for op in source_ops:
        source_id = operator_sources[op]
        source = sources.get(source_id)
        if source is None or source.source_id != source_id:
            raise SemanticProgramError(f"Unknown logical source for {op}")
        replicas = sorted(source.replica_backend_ids)
        if any(replica not in backends for replica in replicas):
            raise SemanticProgramError("Every declared replica needs backend configuration")
        if len({backends[replica].resource_namespace for replica in replicas}) != 1:
            raise SemanticProgramError("Equivalent replicas must share an explicit identity namespace")
        choices.append(replicas)
        identities[op] = {"source_id": source_id, "snapshot_version": source.snapshot_version}
    count = math.prod(len(options) for options in choices)
    if count > max_candidates:
        raise SemanticProgramError(f"{count} placements exceed the finite candidate budget {max_candidates}")
    equivalence_key = _hash({"program": program.to_dict(), "logical_sources": identities})
    candidates, rejected, artifacts, requests = [], [], {}, {}
    for assignment in product(*choices):
        placement = dict(zip(source_ops, assignment))
        try:
            plan = compile_semantic_program(program, source_bindings=placement, backends=backends,
                max_remote_calls=max_remote_calls, max_parallelism=max_parallelism)
        except (ValueError, CompilerError) as error:
            rejected.append({"source_bindings": placement, "reason": str(error)})
            continue
        candidate, local_artifacts, local_requests = _instrument_semantic_plan(plan, identities, equivalence_key)
        candidates.append(candidate)
        for backend, queries in local_artifacts.items():
            artifacts.setdefault(backend, {}).update(queries)
        requests.update(local_requests)
    if not candidates:
        raise SemanticProgramError(f"No executable placement: {rejected}")
    if len(requests) > max_observation_calls:
        raise SemanticProgramError("Unique native observations exceed the finite observation budget")
    catalogs = {backend: BackendObservationCatalog("semantic-native-observations", equivalence_key,
                                                  query_artifacts=queries)
                for backend, queries in artifacts.items()}
    return SemanticPlanSpace(tuple(candidates), tuple(requests[k] for k in sorted(requests)),
                             catalogs, tuple(rejected), (time.perf_counter() - started) * 1000)


def select_static_semantic_plan(candidates, backend_order):
    """Select a declared equivalent placement without observations or answers."""
    if (not isinstance(backend_order, tuple) or not backend_order
            or any(not isinstance(b, str) or not b.strip() for b in backend_order)
            or len(set(backend_order)) != len(backend_order)):
        raise ValueError("Static backend priority must be a nonempty tuple of unique backend IDs")
    if not candidates or len({c.semantic_equivalence_key for c in candidates}) != 1:
        raise ValueError("Static selection requires one nonempty semantic equivalence class")
    if len({c.plan.plan_id for c in candidates}) != len(candidates):
        raise ValueError("Static candidate plan IDs must be unique")
    placements = [c.plan.metadata.get("source_bindings") for c in candidates]
    if any(not isinstance(p, Mapping) or not p for p in placements):
        raise ValueError("Static selection requires explicit compiled source placements")
    operators = tuple(sorted(placements[0]))
    if any(set(p) != set(operators) for p in placements):
        raise ValueError("Static candidates must bind the same source operators")
    priority = {backend: i for i, backend in enumerate(backend_order)}
    if any(not isinstance(backend, str) or backend not in priority
           for placement in placements for backend in placement.values()):
        raise ValueError("Static priority must cover every admitted backend")
    selected = min(candidates, key=lambda c: (
        tuple(priority[c.plan.metadata["source_bindings"][op]] for op in operators), c.plan.plan_id))
    return {"semantic_equivalence_key": selected.semantic_equivalence_key,
            "selected_plan_id": selected.plan.plan_id,
            "selection_rule": "fixed backend priority in sorted source-operator order, then plan ID",
            "backend_order": list(backend_order), "source_operator_order": list(operators),
            "snapshot_id": None, "snapshot_version": None, "estimates": None}


def run_semantic_plans(space: SemanticPlanSpace, backend_tool: BackendInvokeTool, *,
        snapshot: PlanObservationSnapshot | None = None,
        static_backend_order: tuple[str, ...] | None = None,
        plan_memory: SemanticPlanMemory | None = None,
        bandwidth_bytes_per_ms: float = 1000.0, exchange_fixed_ms: float = 0.0,
        coordinator_row_ms: float = 0.01, goal_id: str = "semantic-planning") -> dict:
    """Acquire unique observations if needed, select, then dispatch only the winner.

    An explicit static order bypasses observation acquisition and cost selection.
    Observation queries execute data access and are charged separately from the
    selected plan. A supplied snapshot avoids fresh acquisition, not its recorded
    historical cost. Failed observation/execution never falls back or retries.
    """
    started = time.perf_counter()
    record = {"success": False, "error": None, "enumeration_ms": space.enumeration_ms,
              "candidate_count": len(space.candidates), "rejected_placements": list(space.rejected_placements),
              "observation": None, "selection": None, "execution": None,
              "observation_calls": 0, "execution_calls": 0, "selection_ms": 0.0,
              "snapshot_reused": snapshot is not None and static_backend_order is None, "automatic_retries": 0}
    record["selection_policy"] = "static_backend_order" if static_backend_order is not None else "costed"
    record.update(memory={"state": "disabled", "reads": 0, "writes": 0}, memory_ms=0.0)
    polynomial = hasattr(space, "local_option_count")
    if polynomial:
        record.update(local_option_count=space.local_option_count,
            possible_placement_count=space.possible_placement_count,
            candidate_budget_unit="local_options", search_space_materialized=False)
    try:
        if plan_memory is not None and (snapshot is not None or static_backend_order is not None):
            raise ValueError("Planning memory, an explicit snapshot and static selection are mutually exclusive")
        if static_backend_order is not None and snapshot is not None:
            raise ValueError("Static selection and a cost snapshot are mutually exclusive")
        if plan_memory is not None:
            memory_at = time.perf_counter()
            try:
                snapshot, record["memory"] = plan_memory.lookup(space,
                    bandwidth_bytes_per_ms=bandwidth_bytes_per_ms, exchange_fixed_ms=exchange_fixed_ms,
                    coordinator_row_ms=coordinator_row_ms)
                record["snapshot_reused"] = snapshot is not None
            finally:
                record["memory_ms"] += (time.perf_counter() - memory_at) * 1000
        if snapshot is None and static_backend_order is None:
            collected = PlanObservationCollector(backend_tool).collect(space.observation_requests,
                snapshot_id=record["memory"]["key"] if plan_memory is not None else "semantic-plan-observations",
                version=uuid4().hex if plan_memory is not None else space.candidates[0].semantic_equivalence_key,
                bandwidth_bytes_per_ms=bandwidth_bytes_per_ms, exchange_fixed_ms=exchange_fixed_ms,
                coordinator_row_ms=coordinator_row_ms, goal_id=goal_id)
            record["observation"] = collected.to_dict()
            record["observation_calls"] = collected.attempted_calls
            if not collected.success:
                raise ValueError(collected.error)
            snapshot = collected.snapshot
            if plan_memory is not None:
                memory_at = time.perf_counter()
                try:
                    plan_memory.remember(record["memory"]["key"], collected, goal_id=goal_id)
                    record["memory"].update(state=record["memory"]["state"] + "_stored", writes=1)
                finally:
                    record["memory_ms"] += (time.perf_counter() - memory_at) * 1000
        selected_at = time.perf_counter()
        if polynomial:
            selected, selection = (space.static_select(static_backend_order) if static_backend_order is not None
                                   else space.select(snapshot))
            plan = selected.plan
            record["candidate_count"] = selection.get("evaluated_plan_count", 1)
        else:
            selection = (select_static_semantic_plan(space.candidates, static_backend_order)
                         if static_backend_order is not None else
                         FederatedPlanSelector().select(space.candidates, snapshot).to_dict())
            plan = next(c.plan for c in space.candidates if c.plan.plan_id == selection["selected_plan_id"])
        record["selection_ms"] = (time.perf_counter() - selected_at) * 1000
        record["selection"] = selection
        record["selected_plan"] = plan.to_dict()
        result = FederatedExecutionTool(FederatedScheduler(backend_tool)).invoke(
            {"plan": plan.to_dict()}, ToolContext(goal_id, 1, "execute-selected-semantic-plan"))
        record["execution"] = result.to_dict()
        record["execution_calls"] = int(result.metrics.get("remote_calls", 0))
        record["success"] = result.status is ToolStatus.SUCCESS
        record["error"] = result.error
    except (OSError, ValueError) as error:
        record["error"] = str(error)
    record["total_remote_calls"] = record["observation_calls"] + record["execution_calls"]
    record["planning_ms"] = space.enumeration_ms + record["selection_ms"] + record["memory_ms"] + (
        record["observation"]["elapsed_ms"] if record["observation"] else 0)
    record["end_to_end_ms"] = space.enumeration_ms + (time.perf_counter() - started) * 1000
    return record
