from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from xgap.experiments import m15_finbench_federation as federation
from xgap.experiments.m15_finbench_workload import _templates
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport
from xgap.runtime import FederatedScheduler, RuntimeNodeKind
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


@pytest.fixture
def public_workload(tmp_path: Path, monkeypatch) -> tuple[Path, dict[str, object]]:
    templates = tmp_path / "templates"
    templates.mkdir()
    for name, text in _templates().items():
        (templates / name).write_text(text, encoding="utf-8")
    instances = [
        {
            "query_id": "q-f1",
            "family_id": "f1_direct_transfer_control",
            "split_role": "training",
            "parameters": {
                "person_id": "P1",
                "start_time": "2020-01-01 00:00:00.000",
                "end_time": "2020-12-31 23:59:59.999",
            },
        },
        {
            "query_id": "q-f2",
            "family_id": "f2_temporal_path_control",
            "split_role": "heldout_instance",
            "parameters": {
                "start_account_id": "A1",
                "start_time": "2020-01-01 00:00:00.000",
                "end_time": "2020-12-31 23:59:59.999",
                "max_hops": 3,
            },
        },
        {
            "query_id": "q-f3",
            "family_id": "f3_aggregate_risk_ranking",
            "split_role": "heldout_family",
            "parameters": {
                "start_time": "2020-01-01 00:00:00.000",
                "end_time": "2021-01-01 00:00:00.000",
                "risk_level": "High risk",
                "top_k": 2,
            },
        },
    ]
    loaded: dict[str, object] = {
        "root": tmp_path,
        "manifest": {
            "population_id": "finbench-test",
            "workload_sha256": "a" * 64,
        },
        "public_instances": {"instances": instances},
        "family_contracts": {},
    }
    monkeypatch.setattr(
        federation,
        "load_finbench_primary_public_workload",
        lambda _root: loaded,
    )
    return tmp_path, loaded


def test_compiler_builds_two_physical_routes_for_each_family(
    public_workload,
) -> None:
    root, _ = public_workload

    expected = {
        "q-f1": ("graph_first_hash", "control_first_bind"),
        "q-f2": ("path_first_hash", "control_first_bound_path"),
        "q-f3": ("aggregate_first_hash", "control_first_bound_aggregate"),
    }
    for query_id, strategies in expected.items():
        candidates = federation.build_finbench_plan_candidates(root, query_id=query_id)
        assert tuple(item.plan.metadata["physical_strategy"] for item in candidates) == strategies
        assert len({item.semantic_equivalence_key for item in candidates}) == 1
        assert all(item.plan.max_remote_calls == 2 for item in candidates)
        assert all(item.plan.metadata["paper_result"] is False for item in candidates)
        assert all(item.plan.metadata["current_query_profile_calls"] == 0 for item in candidates)
        assert any(
            node.kind is RuntimeNodeKind.REMOTE_BIND_QUERY
            for node in candidates[1].plan.nodes
        )

    aggregate = federation.build_finbench_plan_candidates(root, query_id="q-f3")[0].plan
    assert any(
        node.kind is RuntimeNodeKind.COORDINATOR_GROUP_AGGREGATE
        for node in aggregate.nodes
    )
    assert any(
        node.kind is RuntimeNodeKind.COORDINATOR_SORT_LIMIT
        for node in aggregate.nodes
    )


def test_artifact_binding_uses_parameters_and_escaped_rdf_literal(
    public_workload,
) -> None:
    root, loaded = public_workload

    f1 = federation.build_finbench_query_artifacts(root, query_id="q-f1")
    assert f1["neo4j_full"].parameters["person_id"] == "P1"
    assert "$person_id" in f1["neo4j_full"].text
    assert "P1" not in f1["neo4j_full"].text
    f3 = federation.build_finbench_query_artifacts(root, query_id="q-f3")
    assert 'VALUES ?risk_level { "High risk" }' in f3["fuseki_control"].text
    assert "{{" not in f3["fuseki_control"].text

    loaded["public_instances"]["instances"][2]["parameters"]["risk_level"] = 'x" } UNION { ?s ?p ?o'
    escaped = federation.build_finbench_query_artifacts(root, query_id="q-f3")
    assert '\\" } UNION' in escaped["fuseki_control"].text


@dataclass
class FamilyRowsClient:
    backend_id: str
    rows: dict[str, list[dict[str, object]]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")

    def execute(self, artifact) -> ExecutionReport:
        role = next(
            role
            for role in ("neo4j-full", "neo4j-bound", "fuseki-control")
            if artifact.artifact_id.endswith(role)
        )
        return ExecutionReport(
            backend_id=self.backend_id,
            artifact_id=artifact.artifact_id,
            language=artifact.language,
            success=True,
            rows=[dict(row) for row in self.rows[role]],
            elapsed_ms=1.0,
        )


def _scheduler(rows: dict[str, list[dict[str, object]]]) -> FederatedScheduler:
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            NativeBackendPlugin(backend_id, FamilyRowsClient(backend_id, rows))
        )
    return FederatedScheduler(BackendInvokeTool(plugins))


@pytest.mark.parametrize(
    ("query_id", "rows", "expected"),
    [
        (
            "q-f1",
            {
                "neo4j-full": [
                    {"company_id": "C1", "account_id": "A1", "total_amount": 7.0},
                    {"company_id": "C2", "account_id": "A2", "total_amount": 9.0},
                ],
                "neo4j-bound": [
                    {"company_id": "C1", "account_id": "A1", "total_amount": 7.0}
                ],
                "fuseki-control": [{"account_id": "A1"}],
            },
            [{"company_id": "C1", "account_id": "A1", "total_amount": "7.000"}],
        ),
        (
            "q-f2",
            {
                "neo4j-full": [
                    {"other_id": "A2", "account_distance": 2, "medium_id": "M1"},
                    {"other_id": "A3", "account_distance": 1, "medium_id": "M2"},
                ],
                "neo4j-bound": [
                    {"other_id": "A2", "account_distance": 2, "medium_id": "M1"}
                ],
                "fuseki-control": [{"medium_id": "M1", "medium_type": "PHONE"}],
            },
            [
                {
                    "other_id": "A2",
                    "account_distance": 2,
                    "medium_id": "M1",
                    "medium_type": "PHONE",
                }
            ],
        ),
        (
            "q-f3",
            {
                "neo4j-full": [
                    {
                        "company_id": "C1",
                        "account_id": "A1",
                        "medium_ids": ["M1", "M9"],
                        "account_amount": 3.1,
                    },
                    {
                        "company_id": "C1",
                        "account_id": "A2",
                        "medium_ids": ["M2"],
                        "account_amount": 4.2,
                    },
                    {
                        "company_id": "C2",
                        "account_id": "A3",
                        "medium_ids": ["M3"],
                        "account_amount": 9.0,
                    },
                    {
                        "company_id": "C3",
                        "account_id": "A4",
                        "medium_ids": ["M1"],
                        "account_amount": 8.0,
                    },
                ],
                "neo4j-bound": [
                    {"company_id": "C3", "total_amount": 8.0},
                    {"company_id": "C1", "total_amount": 7.3},
                ],
                "fuseki-control": [{"medium_id": "M1"}, {"medium_id": "M2"}],
            },
            [
                {"company_id": "C3", "total_amount": "8.000"},
                {"company_id": "C1", "total_amount": "7.300"},
            ],
        ),
    ],
)
def test_two_strategies_produce_same_exact_family_answer(
    public_workload, query_id, rows, expected
) -> None:
    root, loaded = public_workload
    family_id = next(
        item["family_id"]
        for item in loaded["public_instances"]["instances"]
        if item["query_id"] == query_id
    )
    scheduler = _scheduler(rows)

    results = [
        scheduler.execute(candidate.plan, goal_id=f"test:{candidate.plan.plan_id}")
        for candidate in federation.build_finbench_plan_candidates(root, query_id=query_id)
    ]

    assert all(result.success for result in results)
    assert all(result.total_remote_calls == 2 for result in results)
    assert [
        federation.canonicalize_finbench_rows(family_id, result.final_rows)
        for result in results
    ] == [expected, expected]


def test_canonicalizer_rejects_schema_and_nonfinite_amount() -> None:
    with pytest.raises(ValueError, match="schema"):
        federation.canonicalize_finbench_rows(
            "f1_direct_transfer_control", [{"company_id": "C1"}]
        )
    with pytest.raises(ValueError, match="finite"):
        federation.canonicalize_finbench_rows(
            "f3_aggregate_risk_ranking",
            [{"company_id": "C1", "total_amount": float("nan")}],
        )
