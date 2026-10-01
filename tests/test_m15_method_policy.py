from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from xgap.agent import JsonlMemoryStore
from xgap.experiments.m15_method_policy import (
    M15_METHOD_POLICIES,
    M15Method,
    M15MethodError,
    build_m15_plan_memory_context,
    run_m15_method_task,
)
from xgap.experiments.m15_scaled_federation import (
    build_m15_scaled_observation_catalogs,
    build_m15_scaled_observation_requests,
    build_m15_scaled_plan_candidates,
    build_m15_scaled_plan_memory_context,
    build_m15_scaled_probe_plan,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    M15WorkloadSpec,
    generate_m15_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import (
    PlanObservationSnapshot,
    PlanSnapshotMemory,
    ProbeObservation,
    RemoteEstimate,
)
from xgap.tools import (
    BackendInvokeTool,
    BackendPluginRegistry,
    CatalogBackendPlugin,
)


@dataclass
class MethodClient:
    backend_id: str
    rows: list[dict[str, object]]
    elapsed_by_artifact: dict[str, float] = field(default_factory=dict)
    artifact_calls: list[str] = field(default_factory=list)

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "method fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        self.artifact_calls.append(artifact.artifact_id)
        rows = [dict(row) for row in self.rows]
        company_ids = artifact.parameters.get("company_ids")
        if self.backend_id == "neo4j" and isinstance(company_ids, list):
            allowed = set(company_ids)
            rows = [
                row
                for row in rows
                if str(row["company_id"]).rsplit(":", 1)[-1] in allowed
            ]
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=rows,
            elapsed_ms=self.elapsed_by_artifact.get(artifact.artifact_id, 2.0),
            metadata={"transport": "method-policy-fixture"},
        )

    def profile(self, artifact: QueryArtifact) -> ExecutionReport:
        return self.execute(artifact)


def _bundle(tmp_path: Path) -> M15WorkloadBundle:
    return generate_m15_workload_bundle(
        M15WorkloadSpec(
            workload_id="method-test",
            seed="method-test-v1",
            company_count=20,
            transfer_count=100,
            high_risk_company_count=4,
            hot_company_count=3,
            hot_transfer_count=80,
            high_risk_placement="cold_first",
            max_bindings=20,
        ),
        tmp_path / "bundle",
    )


def _tool(
    bundle: M15WorkloadBundle,
    *,
    elapsed_by_artifact: dict[str, float] | None = None,
) -> tuple[BackendInvokeTool, dict[str, MethodClient]]:
    catalogs = build_m15_scaled_observation_catalogs(bundle)
    clients = {
        backend_id: MethodClient(
            backend_id,
            bundle.expected_source_rows[backend_id],
            dict(elapsed_by_artifact or {}),
        )
        for backend_id in ("neo4j", "fuseki")
    }
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            CatalogBackendPlugin(
                backend_id,
                clients[backend_id],
                catalogs[backend_id],
            )
        )
    return BackendInvokeTool(plugins), clients


def _inputs(bundle: M15WorkloadBundle):
    bandwidth = 1000.0
    exchange = 0.5
    coordinator = 0.001
    candidates = build_m15_scaled_plan_candidates(bundle)
    requests = build_m15_scaled_observation_requests(bundle)
    context = build_m15_scaled_plan_memory_context(
        bundle,
        bandwidth_bytes_per_ms=bandwidth,
        exchange_fixed_ms=exchange,
        coordinator_row_ms=coordinator,
    )
    return {
        "context": context,
        "candidates": candidates,
        "requests": requests,
        "probe_plan": build_m15_scaled_probe_plan(bundle),
        "probe_observation": ProbeObservation("high-risk", requests[2].observation_key),
        "expected_rows": tuple(bundle.expected_rows),
        "bandwidth_bytes_per_ms": bandwidth,
        "exchange_fixed_ms": exchange,
        "coordinator_row_ms": coordinator,
    }


def test_method_policies_remove_distinct_mechanisms() -> None:
    assert set(M15_METHOD_POLICIES) == set(M15Method)
    assert M15_METHOD_POLICIES[M15Method.STATIC_PARALLEL_HASH].fixed_strategy == (
        "parallel_hash_join"
    )
    assert M15_METHOD_POLICIES[M15Method.STATIC_RISK_FIRST_BIND].fixed_strategy == (
        "risk_first_bind_join"
    )
    assert M15_METHOD_POLICIES[M15Method.NO_MEMORY].collect_every_task is True
    assert M15_METHOD_POLICIES[M15Method.NO_PROFILE_PROBE].probe_on_memory_hit is False
    assert M15_METHOD_POLICIES[M15Method.NO_REPLAN].max_replans == 0
    assert M15_METHOD_POLICIES[M15Method.FULL_AGENT].max_replans == 1
    assert len(
        {
            tuple(sorted(policy.to_dict().items(), key=lambda item: item[0]))
            for policy in M15_METHOD_POLICIES.values()
        }
    ) == len(M15Method)


def test_memory_context_is_deterministic_and_binds_cost_and_workload(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    first = build_m15_scaled_plan_memory_context(
        bundle,
        bandwidth_bytes_per_ms=1000.0,
        exchange_fixed_ms=0.5,
        coordinator_row_ms=0.001,
    )
    same = build_m15_scaled_plan_memory_context(
        bundle,
        bandwidth_bytes_per_ms=1000.0,
        exchange_fixed_ms=0.5,
        coordinator_row_ms=0.001,
    )
    changed = build_m15_scaled_plan_memory_context(
        bundle,
        bandwidth_bytes_per_ms=2000.0,
        exchange_fixed_ms=0.5,
        coordinator_row_ms=0.001,
    )

    assert first == same
    assert first.snapshot_id == same.snapshot_id
    assert first.snapshot_id != changed.snapshot_id
    assert first.factors["external_binding"]["workload_manifest"]["spec_sha256"] == (
        bundle.manifest["spec_sha256"]
    )


def test_full_agent_cold_then_warm_reuses_cross_process_memory(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    inputs = _inputs(bundle)
    memory_path = tmp_path / "memory.jsonl"
    cold_tool, _ = _tool(bundle)

    cold = run_m15_method_task(
        method=M15Method.FULL_AGENT,
        task_id="cold-task",
        backend_tool=cold_tool,
        memory=PlanSnapshotMemory(JsonlMemoryStore(memory_path)),
        **inputs,
    )
    warm_tool, _ = _tool(bundle)
    warm = run_m15_method_task(
        method=M15Method.FULL_AGENT,
        task_id="warm-task",
        backend_tool=warm_tool,
        memory=PlanSnapshotMemory(JsonlMemoryStore(memory_path)),
        **inputs,
    )

    assert cold.success and warm.success
    assert cold.memory_state == "miss_profiled_and_persisted"
    assert cold.planning_profile_calls == 3
    assert cold.probe_remote_calls == 0
    assert cold.query_remote_calls == 2
    assert cold.total_backend_calls == 5
    assert warm.memory_state == "hit"
    assert warm.planning_profile_calls == 0
    assert warm.probe_remote_calls == 1
    assert warm.query_remote_calls == 2
    assert warm.total_backend_calls == 2
    assert warm.memory_reads == 1
    assert warm.memory_writes == 1
    assert len(memory_path.read_text(encoding="utf-8").splitlines()) == 2


def test_baselines_have_distinct_action_counts_and_exact_answers(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    inputs = _inputs(bundle)
    seed_path = tmp_path / "seed.jsonl"
    seed_tool, _ = _tool(bundle)
    seed = run_m15_method_task(
        method=M15Method.FULL_AGENT,
        task_id="seed",
        backend_tool=seed_tool,
        memory=PlanSnapshotMemory(JsonlMemoryStore(seed_path)),
        **inputs,
    )
    assert seed.success
    snapshot = seed.snapshot_before
    assert snapshot is not None

    results = {}
    for method in M15Method:
        tool, _ = _tool(bundle)
        memory = None
        if M15_METHOD_POLICIES[method].read_memory:
            path = tmp_path / f"{method.value}.jsonl"
            store = PlanSnapshotMemory(JsonlMemoryStore(path))
            store.put(snapshot, source="common-frozen-seed")
            memory = store
        results[method] = run_m15_method_task(
            method=method,
            task_id=f"task-{method.value}",
            backend_tool=tool,
            memory=memory,
            **inputs,
        )

    assert all(result.success and result.exact_answer for result in results.values())
    assert results[M15Method.NO_MEMORY].planning_profile_calls == 3
    assert results[M15Method.NO_MEMORY].total_backend_calls == 5
    assert results[M15Method.NO_PROFILE_PROBE].planning_profile_calls == 0
    assert results[M15Method.NO_PROFILE_PROBE].probe_remote_calls == 0
    assert results[M15Method.NO_REPLAN].probe_remote_calls == 1
    assert results[M15Method.NO_REPLAN].replan_count == 0
    assert results[M15Method.FULL_AGENT].probe_remote_calls == 1
    assert results[M15Method.STATIC_PARALLEL_HASH].memory_reads == 0
    assert results[M15Method.STATIC_RISK_FIRST_BIND].memory_reads == 0
    assert {
        results[M15Method.STATIC_PARALLEL_HASH].executed_plan_id,
        results[M15Method.STATIC_RISK_FIRST_BIND].executed_plan_id,
    } == {
        candidate.plan.plan_id for candidate in inputs["candidates"]
    }


def test_full_agent_replans_on_stale_memory_while_no_replan_keeps_initial(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    inputs = _inputs(bundle)
    keys = [request.observation_key for request in inputs["requests"]]
    snapshot = PlanObservationSnapshot(
        snapshot_id=inputs["context"].snapshot_id,
        version="stale-seed",
        estimates=(
            RemoteEstimate(keys[0], "neo4j", 100.0, 100, 100.0, "stale", "v1"),
            RemoteEstimate(keys[1], "neo4j", 10.0, 5, 100.0, "stale", "v1"),
            RemoteEstimate(keys[2], "fuseki", 1000.0, 4, 100.0, "stale", "v1"),
        ),
        bandwidth_bytes_per_ms=1_000_000_000.0,
        exchange_fixed_ms=0.0,
        coordinator_row_ms=0.0,
    )
    # The context itself freezes the cost model used by the task.  Rebuild it
    # with the same values as the deliberately stale snapshot.
    context = build_m15_plan_memory_context(
        context_id="m15-f1-method-test-stale",
        candidates=inputs["candidates"],
        requests=inputs["requests"],
        bandwidth_bytes_per_ms=1_000_000_000.0,
        exchange_fixed_ms=0.0,
        coordinator_row_ms=0.0,
        binding={"workload_manifest": dict(bundle.manifest)},
    )
    snapshot = PlanObservationSnapshot(
        snapshot_id=context.snapshot_id,
        version=snapshot.version,
        estimates=snapshot.estimates,
        bandwidth_bytes_per_ms=snapshot.bandwidth_bytes_per_ms,
        exchange_fixed_ms=snapshot.exchange_fixed_ms,
        coordinator_row_ms=snapshot.coordinator_row_ms,
    )
    task_inputs = {
        **inputs,
        "context": context,
        "bandwidth_bytes_per_ms": 1_000_000_000.0,
        "exchange_fixed_ms": 0.0,
        "coordinator_row_ms": 0.0,
    }

    outcomes = {}
    for method in (M15Method.NO_REPLAN, M15Method.FULL_AGENT):
        memory = PlanSnapshotMemory(
            JsonlMemoryStore(tmp_path / f"stale-{method.value}.jsonl")
        )
        memory.put(snapshot, source="controlled-stale-seed")
        tool, _ = _tool(bundle)
        outcomes[method] = run_m15_method_task(
            method=method,
            task_id=f"stale-{method.value}",
            backend_tool=tool,
            memory=memory,
            **task_inputs,
        )

    no_replan = outcomes[M15Method.NO_REPLAN]
    full = outcomes[M15Method.FULL_AGENT]
    assert no_replan.success and full.success
    assert no_replan.initial_plan_id.endswith("parallel-hash")
    assert no_replan.post_probe_plan_id.endswith("risk-first-bind")
    assert no_replan.executed_plan_id == no_replan.initial_plan_id
    assert no_replan.replan_count == 0
    assert full.initial_plan_id.endswith("parallel-hash")
    assert full.post_probe_plan_id.endswith("risk-first-bind")
    assert full.executed_plan_id == full.post_probe_plan_id
    assert full.replan_count == 1


def test_warm_only_method_rejects_missing_or_incompatible_memory_before_calls(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    inputs = _inputs(bundle)
    tool, clients = _tool(bundle)
    empty = PlanSnapshotMemory(JsonlMemoryStore(tmp_path / "empty.jsonl"))

    with pytest.raises(M15MethodError, match="compatible warm-memory"):
        run_m15_method_task(
            method=M15Method.NO_PROFILE_PROBE,
            task_id="missing-memory",
            backend_tool=tool,
            memory=empty,
            **inputs,
        )

    assert all(not client.artifact_calls for client in clients.values())
