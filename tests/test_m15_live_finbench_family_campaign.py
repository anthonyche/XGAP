from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from xgap.experiments import m15_finbench_family_memory as memory_module
from xgap.experiments import m15_finbench_family_campaign_evidence as evidence
from xgap.experiments import m15_live_finbench_family_campaign as live
from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_fixture_loader import BackendLoadReport
from xgap.infrastructure.runtime import BackendStatus


F1 = "f1_direct_transfer_control"
F2 = "f2_temporal_path_control"
F3 = "f3_aggregate_risk_ranking"
STRATEGIES = {
    F1: ("graph_first_hash", "control_first_bind"),
    F2: ("path_first_hash", "control_first_bound_path"),
    F3: ("aggregate_first_hash", "control_first_bound_aggregate"),
}


def _public_workload(root: Path) -> dict[str, object]:
    instances: list[dict[str, object]] = []
    for family_id, prefix, feature_name in (
        (F1, "finbench-f1", "structural_degree"),
        (F2, "finbench-f2", "out_degree"),
    ):
        for position in range(1, 13):
            instances.append(
                {
                    "query_id": f"{prefix}-{position:02d}",
                    "family_id": family_id,
                    "split_role": (
                        "heldout_instance"
                        if position in {3, 6, 9, 12}
                        else "training"
                    ),
                    "selection_feature": {feature_name: position},
                }
            )
    for window_position in range(1, 5):
        for risk_position in range(1, 4):
            instances.append(
                {
                    "query_id": f"finbench-f3-w{window_position}-r{risk_position}",
                    "family_id": F3,
                    "split_role": "heldout_family",
                    "selection_feature": {
                        "window_position": window_position,
                        "risk_position": risk_position,
                    },
                }
            )
    families = [
        {
            "family_id": family_id,
            "physical_strategies": list(strategies),
            **(
                {"cold_start_fallback": "aggregate_first_hash"}
                if family_id == F3
                else {}
            ),
        }
        for family_id, strategies in STRATEGIES.items()
    ]
    return {
        "root": root,
        "manifest": {
            "population_id": "test-finbench-population",
            "workload_sha256": "a" * 64,
            "source_partition_sha256": "b" * 64,
            "source_archive_sha256": "c" * 64,
            "output_files": {
                "public_instances.json": {"sha256": "d" * 64},
                "family_contracts.json": {"sha256": "e" * 64},
            },
        },
        "public_instances": {"instances": instances},
        "family_contracts": {"families": families},
    }


def _rows(family_id: str, query_id: str) -> list[dict[str, object]]:
    if family_id == F1:
        return [
            {
                "company_id": f"company-{query_id}",
                "account_id": f"account-{query_id}",
                "total_amount": "7.000",
            }
        ]
    if family_id == F2:
        return [
            {
                "other_id": f"other-{query_id}",
                "account_distance": 2,
                "medium_id": f"medium-{query_id}",
                "medium_type": "Loan",
            }
        ]
    return [{"company_id": f"company-{query_id}", "total_amount": "9.000"}]


@dataclass
class Loader:
    backend_id: str

    def load(self, path: Path) -> BackendLoadReport:
        return BackendLoadReport(
            backend_id=self.backend_id,
            success=True,
            operations_attempted=1,
            bytes_sent=path.stat().st_size,
            elapsed_ms=1.0,
        )


@dataclass
class Client:
    backend_id: str
    timeout_seconds: float = 60.0

    def healthcheck(self) -> BackendStatus:
        return BackendStatus(self.backend_id, True, "ready")


@dataclass(frozen=True)
class Plan:
    query_id: str
    family_id: str
    physical_strategy: str

    @property
    def plan_id(self) -> str:
        return f"plan-{self.query_id}-{self.physical_strategy}"


class Result:
    def __init__(self, plan: Plan) -> None:
        index = STRATEGIES[plan.family_id].index(plan.physical_strategy)
        self.success = True
        self.elapsed_ms = 10.0 + (index * 5.0)
        self.total_bytes_moved = 200 - (index * 50)
        self.total_remote_calls = 2
        self.node_results = (
            SimpleNamespace(
                remote_calls=1,
                metadata={"backend_id": "neo4j"},
                node_id="neo4j",
            ),
            SimpleNamespace(
                remote_calls=1,
                metadata={"backend_id": "fuseki"},
                node_id="fuseki",
            ),
        )
        self._rows = _rows(plan.family_id, plan.query_id)
        self.plan_id = plan.plan_id

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "success": True,
            "final_rows": copy.deepcopy(self._rows),
            "elapsed_ms": self.elapsed_ms,
            "total_remote_calls": 2,
            "total_bytes_moved": self.total_bytes_moved,
        }


class Scheduler:
    def __init__(self, oracle_open_counts: list[int]) -> None:
        self.call_count = 0
        self.oracle_open_counts = oracle_open_counts

    def execute(self, plan: Plan, *, goal_id: str) -> Result:
        assert goal_id
        self.call_count += 1
        return Result(plan)


def test_live_family_campaign_preserves_seals_and_oracle_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    workload_root = tmp_path / "workload"
    workload_root.mkdir()
    partition_root = tmp_path / "partition"
    partition_root.mkdir()
    (partition_root / "load_neo4j_batches.jsonl").write_text("{}\n")
    (partition_root / "load_fuseki.ttl").write_text("# fixture\n")
    public = _public_workload(workload_root)
    oracle = {
        query["query_id"]: {
            "final_rows": _rows(str(query["family_id"]), str(query["query_id"]))
        }
        for query in public["public_instances"]["instances"]  # type: ignore[index]
    }
    monkeypatch.setattr(
        memory_module,
        "load_finbench_primary_public_workload",
        lambda _root: copy.deepcopy(public),
    )
    monkeypatch.setattr(
        live,
        "load_finbench_primary_public_workload",
        lambda _root: copy.deepcopy(public),
    )
    monkeypatch.setattr(
        live,
        "load_finbench_source_partition",
        lambda _root: {
            "partition_sha256": "b" * 64,
            "neo4j_load": {"filename": "load_neo4j_batches.jsonl"},
        },
    )
    correctness_audit_snapshot = {
        "schema_version": live.FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
        "success": True,
        "failed_check_ids": [],
        "run_tree_mutated": False,
    }
    correctness_manifest_snapshot = {
        "status": "success",
        "summary": {
            "all_plans_exact": True,
            "all_physical_pairs_equivalent": True,
        },
    }
    admission_body = {
        "schema_version": live.FINBENCH_CORRECTNESS_ADMISSION_SCHEMA_VERSION,
        "workload_sha256": "a" * 64,
        "all_plans_exact": True,
        "all_physical_pairs_equivalent": True,
        "audit_content_sha256": content_hash(correctness_audit_snapshot),
        "producer_manifest_content_sha256": content_hash(
            correctness_manifest_snapshot
        ),
    }
    admission = {**admission_body, "admission_sha256": content_hash(admission_body)}
    monkeypatch.setattr(
        live,
        "_correctness_admission",
        lambda **_kwargs: (
            admission,
            correctness_audit_snapshot,
            correctness_manifest_snapshot,
        ),
    )
    plans = {
        (str(instance["query_id"]), strategy): Plan(
            str(instance["query_id"]), str(instance["family_id"]), strategy
        )
        for instance in public["public_instances"]["instances"]  # type: ignore[index]
        for strategy in STRATEGIES[str(instance["family_id"])]
    }
    catalog = {
        "backend_calls_before_seal": 0,
        "candidate_catalog_sha256": content_hash("candidate-catalog"),
    }
    monkeypatch.setattr(live, "_candidate_catalog", lambda *_args: (catalog, plans))
    oracle_open_counts: list[int] = []
    scheduler = Scheduler(oracle_open_counts)
    monkeypatch.setattr(live, "_scheduler", lambda _clients: scheduler)

    def open_oracle(_root: object) -> dict[str, object]:
        oracle_open_counts.append(scheduler.call_count)
        return {**copy.deepcopy(public), "sealed_oracles": {"queries": oracle}}

    monkeypatch.setattr(live, "load_finbench_primary_workload", open_oracle)
    clients = {backend_id: Client(backend_id) for backend_id in ("neo4j", "fuseki")}
    loaders = {backend_id: Loader(backend_id) for backend_id in ("neo4j", "fuseki")}
    outer = tmp_path / "outer"
    service = outer / "native-service-run"
    service.mkdir(parents=True)
    commit = "2" * 40
    monkeypatch.setattr(
        live, "_git_state", lambda _root: {"commit": commit, "clean": True}
    )
    record = live.run_m15_live_finbench_family_campaign(
        workload_root=workload_root,
        partition_root=partition_root,
        correctness_run_root=tmp_path,
        correctness_audit=tmp_path / "unused-audit.json",
        clients=clients,
        loaders=loaders,
        output_root=service,
        protocol="experiments/configs/m15_finbench_family_campaign_dev_v1.json",
        family_memory_policy=(
            "experiments/configs/m15_finbench_family_memory_policy_v1.json"
        ),
        repo_root=tmp_path,
    )

    assert record.success, record.error
    assert scheduler.call_count == 368
    assert oracle_open_counts == [368]
    manifest = json.loads(record.manifest_path.read_text())
    validation = json.loads((record.run_root / "validation.json").read_text())
    family_seal = json.loads(
        (record.run_root / "family_selection_seal.json").read_text()
    )
    profile_seal = json.loads(
        (record.run_root / "profile_selection_seal.json").read_text()
    )
    analysis = json.loads((record.run_root / "analysis.json").read_text())
    assert manifest["summary"]["total_plan_runs"] == 368
    assert manifest["summary"]["total_backend_calls"] == 736
    assert manifest["summary"]["family_memory_current_query_profile_calls"] == 0
    assert family_seal["backend_calls_before_seal"] == 256
    assert profile_seal["backend_calls_before_seal"] == 336
    assert validation["passed"] is True
    assert set(analysis["method_metrics"]) == set(live._METHODS)
    assert analysis["prediction_error"]["known_family_plan_count"] == 16
    assert analysis["predicted_observed_frontier_overlap"][
        "known_family_query_count"
    ] == 8
    assert manifest["paper_result"] is False

    (outer / "run_status.json").write_text(
        json.dumps(
            {
                "status": "success",
                "exit_code": 0,
                "git_commit": commit,
                "workload_mode": "finbench_family_campaign",
                "runtime_removed": True,
            }
        )
    )
    (service / "run_status.json").write_text(
        json.dumps({"status": "success"})
    )
    (service / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": (
                    evidence.FINBENCH_FAMILY_CAMPAIGN_SERVICE_RUN_SCHEMA_VERSION
                ),
                "status": "success",
            }
        )
    )
    workload_target = outer / "finbench-primary-workload"
    workload_target.mkdir()
    monkeypatch.setattr(
        evidence,
        "load_finbench_primary_public_workload",
        lambda _root: copy.deepcopy(public),
    )
    monkeypatch.setattr(
        evidence,
        "load_finbench_primary_workload",
        lambda _root: {
            **copy.deepcopy(public),
            "sealed_oracles": {"queries": copy.deepcopy(oracle)},
        },
    )
    monkeypatch.setattr(
        evidence, "_candidate_catalog", lambda *_args: (catalog, plans)
    )
    audit = evidence.audit_m15_finbench_family_campaign(
        run_root=outer,
        expected_commit=commit,
        protocol="experiments/configs/m15_finbench_family_campaign_dev_v1.json",
        family_memory_policy=(
            "experiments/configs/m15_finbench_family_memory_policy_v1.json"
        ),
    )
    assert audit.success, audit.failed_check_ids
    assert audit.run_tree_mutated is False


def test_correctness_admission_rejects_unsuccessful_independent_audit(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "correctness"
    live_root = run_root / "native-service-run/finbench-correctness-run"
    live_root.mkdir(parents=True)
    commit = "1" * 40
    (run_root / "run_status.json").write_text(
        json.dumps(
            {
                "status": "success",
                "git_commit": commit,
                "workload_mode": "finbench_correctness",
            }
        )
    )
    (live_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "success",
                "workload_sha256": "a" * 64,
                "summary": {
                    "query_count": 36,
                    "physical_plan_run_count": 72,
                    "backend_calls": 144,
                    "all_plans_exact": True,
                    "all_physical_pairs_equivalent": True,
                },
                "oracle_boundary": {
                    "content_parsed_after_all_plan_runs": True,
                    "used_for_selection": False,
                },
                "automatic_retries": 0,
                "paper_result": False,
            }
        )
    )
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "schema_version": live.FINBENCH_CORRECTNESS_AUDIT_SCHEMA_VERSION,
                "success": True,
                "failed_check_ids": [],
                "run_tree_mutated": False,
                "expected_commit": commit,
                "check_count": 363,
            }
        )
    )
    admission, _, _ = live._correctness_admission(
        workload_sha256="a" * 64,
        correctness_run_root=run_root,
        correctness_audit=audit_path,
    )
    assert admission["all_plans_exact"] is True
    assert admission["answer_rows_copied"] is False

    audit_link = tmp_path / "audit-link.json"
    audit_link.symlink_to(audit_path)
    try:
        live._correctness_admission(
            workload_sha256="a" * 64,
            correctness_run_root=run_root,
            correctness_audit=audit_link,
        )
    except ValueError as exc:
        assert "non-symbolic-link" in str(exc)
    else:
        raise AssertionError("symbolic-link correctness audit was admitted")

    changed = json.loads(audit_path.read_text())
    changed["success"] = False
    audit_path.write_text(json.dumps(changed))
    try:
        live._correctness_admission(
            workload_sha256="a" * 64,
            correctness_run_root=run_root,
            correctness_audit=audit_path,
        )
    except ValueError as exc:
        assert "not admissible" in str(exc)
    else:
        raise AssertionError("failed correctness audit was admitted")


def test_family_campaign_auditor_refuses_overwrite_and_in_tree_output(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    in_tree = run_root / "audit.json"
    assert evidence.main(
        [
            "--run-root",
            str(run_root),
            "--expected-commit",
            "1" * 40,
            "--output",
            str(in_tree),
        ]
    ) == 2
    assert not in_tree.exists()

    existing = tmp_path / "existing-audit.json"
    existing.write_text("preserve-me", encoding="utf-8")
    assert evidence.main(
        [
            "--run-root",
            str(run_root),
            "--expected-commit",
            "1" * 40,
            "--output",
            str(existing),
        ]
    ) == 2
    assert existing.read_text(encoding="utf-8") == "preserve-me"


def test_family_campaign_audit_canonicalizes_sets_as_json_arrays() -> None:
    check = evidence.FinBenchFamilyCampaignEvidenceCheck(
        check_id="loads.backends",
        passed=True,
        expected={"neo4j", "fuseki"},
        observed=frozenset({"fuseki", "neo4j"}),
    )

    serialized = check.to_dict()

    assert serialized["expected"] == ["fuseki", "neo4j"]
    assert serialized["observed"] == ["fuseki", "neo4j"]
    assert json.loads(json.dumps(serialized, allow_nan=False)) == serialized
