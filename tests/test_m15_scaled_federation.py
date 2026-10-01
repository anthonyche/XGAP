from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xgap.experiments.m15_scaled_federation import (
    build_m15_scaled_observation_catalogs,
    build_m15_scaled_observation_requests,
    build_m15_scaled_plan_candidates,
    build_m15_scaled_probe_plan,
    build_m15_scaled_semantic_program,
)
from xgap.experiments.m15_workload import (
    M15WorkloadBundle,
    M15WorkloadSpec,
    generate_m15_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import FederatedScheduler, RuntimeNodeKind
from xgap.semantic import ConstraintPolicy
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
SELECTIVE_CONFIG = REPO_ROOT / "experiments/configs/m15_f0_selective.json"
BROAD_CONFIG = REPO_ROOT / "experiments/configs/m15_f0_broad_hot.json"


@dataclass
class BundleClient:
    backend_id: str
    rows: list[dict[str, object]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "verified bundle fixture")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
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
            elapsed_ms=2.0,
            metadata={"transport": "verified-bundle-fixture"},
        )


def _run_candidates(bundle: M15WorkloadBundle):
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            NativeBackendPlugin(
                backend_id,
                BundleClient(
                    backend_id,
                    bundle.expected_source_rows[backend_id],
                ),
            )
        )
    scheduler = FederatedScheduler(BackendInvokeTool(plugins))
    candidates = build_m15_scaled_plan_candidates(bundle)
    return candidates, {
        candidate.plan.metadata["physical_strategy"]: scheduler.execute(candidate.plan)
        for candidate in candidates
    }


def test_scaled_plans_are_exact_and_selective_bind_reduces_exchange(
    tmp_path: Path,
) -> None:
    bundle = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(SELECTIVE_CONFIG),
        tmp_path / "selective",
    )
    candidates, results = _run_candidates(bundle)

    assert len({item.semantic_equivalence_key for item in candidates}) == 1
    assert all(result.success for result in results.values())
    expected = tuple(bundle.expected_rows)
    assert results["parallel_hash_join"].final_rows == expected
    assert results["risk_first_bind_join"].final_rows == expected
    assert (
        results["risk_first_bind_join"].total_bytes_moved
        < results["parallel_hash_join"].total_bytes_moved / 5
    )
    bind = next(
        node
        for node in candidates[1].plan.nodes
        if node.kind is RuntimeNodeKind.REMOTE_BIND_QUERY
    )
    assert bind.parameters["max_bindings"] == bundle.spec.max_bindings


def test_broad_hot_workload_preserves_answer_but_makes_bind_nearly_full(
    tmp_path: Path,
) -> None:
    bundle = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(BROAD_CONFIG),
        tmp_path / "broad",
    )
    _, results = _run_candidates(bundle)

    expected = tuple(bundle.expected_rows)
    assert results["parallel_hash_join"].final_rows == expected
    assert results["risk_first_bind_join"].final_rows == expected
    assert (
        results["risk_first_bind_join"].total_bytes_moved
        > results["parallel_hash_join"].total_bytes_moved * 0.8
    )


def test_scaled_program_catalog_requests_and_probe_share_one_bundle_contract(
    tmp_path: Path,
) -> None:
    bundle = generate_m15_workload_bundle(
        M15WorkloadSpec.from_json(SELECTIVE_CONFIG),
        tmp_path / "selective",
    )
    program = build_m15_scaled_semantic_program(bundle)
    catalogs = build_m15_scaled_observation_catalogs(bundle)
    requests = build_m15_scaled_observation_requests(bundle)
    candidates = build_m15_scaled_plan_candidates(bundle)
    probe = build_m15_scaled_probe_plan(bundle)

    constraints = {
        constraint.constraint_id: constraint
        for operator in program.operators
        for constraint in operator.constraints
    }
    assert constraints["person-identity"].policy is ConstraintPolicy.HARD
    assert constraints["frozen-window"].policy is ConstraintPolicy.HARD
    assert program.metadata["paper_result"] is False
    assert program.metadata["workload_spec_sha256"] == bundle.manifest["spec_sha256"]
    bound_profile = catalogs["neo4j"].query_artifacts["recent-transfers-bound"]
    assert len(bound_profile.parameters["company_ids"]) == 20
    assert catalogs["neo4j"].version == str(bundle.manifest["spec_sha256"])[:16]
    assert [request.observation_key for request in requests] == [
        candidates[0].plan.nodes[0].parameters["observation_key"],
        candidates[1].plan.nodes[3].parameters["observation_key"],
        candidates[0].plan.nodes[1].parameters["observation_key"],
    ]
    candidate_nodes = [
        {node.node_id: node for node in candidate.plan.nodes} for candidate in candidates
    ]
    for probe_node in probe.nodes:
        assert all(nodes[probe_node.node_id] == probe_node for nodes in candidate_nodes)
    assert probe.max_remote_calls == 1
