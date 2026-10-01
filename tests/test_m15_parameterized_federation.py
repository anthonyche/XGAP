from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import xgap.experiments.m15_parameterized_federation as parameterized_federation

from xgap.experiments.m15_parameterized_federation import (
    build_m15_parameterized_plan_candidates,
    load_m15_parameterized_instance,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.infrastructure.runtime import BackendStatus, ExecutionReport, QueryArtifact
from xgap.runtime import FederatedScheduler, RuntimeNodeKind
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SPEC = (
    REPO_ROOT / "experiments/configs/m15_f2c_parameterized_workload_dev.json"
)
QUERY_TEMPLATE = (
    REPO_ROOT
    / "experiments/configs/m15_f2c_parameterized_financial_risk_v2.json"
)
BACKEND_TEMPLATES = REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"


@dataclass
class ParameterizedBundleClient:
    backend_id: str
    rows_by_artifact: dict[str, list[dict[str, object]]]

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "parameterized fixture ready")

    def execute(self, artifact: QueryArtifact) -> ExecutionReport:
        rows = [dict(row) for row in self.rows_by_artifact[artifact.artifact_id]]
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
            elapsed_ms=1.0,
        )


def _bundle(tmp_path: Path):
    return generate_m15_parameterized_workload_bundle(
        workload_spec=WORKLOAD_SPEC,
        query_template_spec=QUERY_TEMPLATE,
        backend_template_root=BACKEND_TEMPLATES,
        destination=tmp_path / "bundle",
    )


def _scheduler(bundle) -> FederatedScheduler:
    rows: dict[str, dict[str, list[dict[str, object]]]] = {
        "neo4j": {},
        "fuseki": {},
    }
    for query_id in bundle.instance_ids():
        instance = load_m15_parameterized_instance(bundle, query_id)
        sources = instance["source_oracles"]
        rows["neo4j"][f"m15-f2c-{query_id}-neo4j-full"] = sources[
            "neo4j_full"
        ]
        rows["neo4j"][f"m15-f2c-{query_id}-neo4j-bound"] = sources[
            "neo4j_full"
        ]
        rows["fuseki"][f"m15-f2c-{query_id}-fuseki-risk"] = sources[
            "fuseki_risk"
        ]
    plugins = BackendPluginRegistry()
    for backend_id in ("neo4j", "fuseki"):
        plugins.register(
            NativeBackendPlugin(
                backend_id,
                ParameterizedBundleClient(backend_id, rows[backend_id]),
            )
        )
    return FederatedScheduler(BackendInvokeTool(plugins))


def test_every_parameterized_instance_has_two_exact_executable_plans(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    scheduler = _scheduler(bundle)

    for query_id in bundle.instance_ids():
        instance = load_m15_parameterized_instance(bundle, query_id)
        candidates = build_m15_parameterized_plan_candidates(
            bundle,
            query_id=query_id,
        )
        assert len(candidates) == 2
        assert len({item.semantic_equivalence_key for item in candidates}) == 1
        for candidate in candidates:
            result = scheduler.execute(candidate.plan, goal_id=query_id)
            assert result.success
            assert result.total_remote_calls == 2
            assert result.final_rows == tuple(instance["final_oracle"])


def test_plan_artifacts_bind_instance_parameters_and_identity(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    query_id = "financial-risk-bob-jul-medium-v2"
    candidates = build_m15_parameterized_plan_candidates(bundle, query_id=query_id)
    parallel = candidates[0].plan
    recent = parallel.nodes[0]
    risk = parallel.nodes[1]

    assert recent.parameters["artifact"]["parameters"] == {
        "person_id": "person-bob-jones",
        "occurred_on_gte": "2026-07-15",
        "amount_gte": 90000,
    }
    assert 'FILTER (?risk = "MEDIUM")' in risk.parameters["artifact"]["text"]
    assert parallel.metadata["semantic_deviation"] == 0
    assert parallel.metadata["family_compatibility_sha256"] == (
        bundle.manifest["family_compatibility_sha256"]
    )


def test_bind_plan_consumes_aligned_backend_local_company_ids(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    query_id = "financial-risk-carol-jun-low-v2"
    candidates = build_m15_parameterized_plan_candidates(bundle, query_id=query_id)
    bind = candidates[1].plan
    node = next(
        item for item in bind.nodes if item.kind is RuntimeNodeKind.REMOTE_BIND_QUERY
    )

    assert node.parameters["bind_field"] == "canonical_company_id"
    assert node.parameters["parameter"] == "company_ids"
    assert node.parameters["max_bindings"] == 30
    assert "company_ids" not in node.parameters["artifact"]["parameters"]


def test_alignment_catalog_covers_domain_without_answer_oracle_leakage(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    query_id = "financial-risk-bob-may-low-v2"
    candidates = build_m15_parameterized_plan_candidates(bundle, query_id=query_id)
    parallel = candidates[0].plan
    risk_alignment = next(
        node for node in parallel.nodes if node.node_id == "align-risk"
    )
    oracle_ids = {
        row["company_id"]
        for row in load_m15_parameterized_instance(bundle, query_id)[
            "source_oracles"
        ]["fuseki_risk"]
    }
    mapping = risk_alignment.parameters["mapping"]

    assert len(mapping) == bundle.spec.company_count
    assert set(mapping) > oracle_ids
    assert mapping[
        f"rdf:{bundle.spec.workload_id}:C0001"
    ] == "C0001"


def test_plan_construction_never_opens_answer_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path)
    original = parameterized_federation._json_file

    def reject_oracle(bundle_value, path):
        if "expected_" in path:
            raise AssertionError("plan construction opened an answer oracle")
        return original(bundle_value, path)

    monkeypatch.setattr(parameterized_federation, "_json_file", reject_oracle)

    candidates = build_m15_parameterized_plan_candidates(
        bundle,
        query_id=bundle.instance_ids()[0],
    )

    assert len(candidates) == 2


def test_instance_loader_rejects_unknown_query(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    try:
        load_m15_parameterized_instance(bundle, "unknown-query")
    except ValueError as exc:
        assert "unknown parameterized query instance" in str(exc)
    else:
        raise AssertionError("unknown query should fail")


def test_bundle_contract_remains_zero_relaxation(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    query_id = bundle.instance_ids()[0]
    instance = load_m15_parameterized_instance(bundle, query_id)
    contract = instance["contract"]
    constraints = [
        constraint
        for operator in contract["typed_program"]["operators"]
        for constraint in operator["constraints"]
    ]

    assert {item["policy"] for item in constraints} == {"hard", "relaxable"}
    candidates = build_m15_parameterized_plan_candidates(bundle, query_id=query_id)
    assert all(item.plan.metadata["semantic_deviation"] == 0 for item in candidates)
    assert json.loads(
        bundle.path(f"instances/{query_id}/expected_result.json").read_text(
            encoding="utf-8"
        )
    ) == instance["final_oracle"]
