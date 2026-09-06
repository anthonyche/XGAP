from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import xgap.experiments.m15_live_direct_family_pilot as live_pilot

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_pilot_evidence import (
    audit_m15_direct_family_pilot,
)
from xgap.experiments.m15_direct_family_pilot_summary import (
    DIRECT_FAMILY_PILOT_SUMMARY_SCHEMA_VERSION,
    build_m15_direct_family_pilot_summary,
)
from xgap.experiments.m15_direct_family_baselines import (
    DIRECT_FAMILY_BASELINE_ANALYSIS_SCHEMA_VERSION,
    analyze_m15_direct_family_baselines,
)
from xgap.experiments.m15_direct_family_prediction_run import (
    _ControlledState,
    _clients_after_selection_seal,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_direct_family_pilot import (
    run_m15_live_direct_family_pilot,
)
from xgap.experiments.m15_native_services import (
    DIRECT_FAMILY_PILOT_PREFLIGHT_SCHEMA_VERSION,
    DIRECT_FAMILY_PILOT_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
COMMIT = "1" * 40


def _native_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "native-pilot"
    root.mkdir()
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=CONFIGS / "m15_f2c_parameterized_workload_dev.json",
        query_template_spec=(
            CONFIGS / "m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=root / "direct-family-base-workload-bundle",
    )
    for source, destination in (
        ("m15_f2c6_semantic_relaxation_dev.json", "semantic_catalog.json"),
        ("m15_f2c8_predicate_mapping_dev.json", "predicate_mapping.json"),
        (
            "m15_f2c10d_family_memory_pilot_dev.json",
            "direct_family_pilot_protocol.json",
        ),
        (
            "m15_f2c10_family_memory_predictor_dev.json",
            "direct_family_predictor_policy.json",
        ),
    ):
        shutil.copyfile(CONFIGS / source, root / destination)
    direct = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=root / "semantic_catalog.json",
        mapping=root / "predicate_mapping.json",
        policy=CONFIGS / "m15_f2c10_direct_semantic_workload_dev.json",
        destination=root / "direct-semantic-workload-bundle",
    )
    state = _ControlledState()
    clients = _clients_after_selection_seal(direct.workload_bundle, state=state)
    monkeypatch.setattr(
        live_pilot,
        "_git_state",
        lambda _root: {"commit": COMMIT, "clean": True},
    )
    compatibility = content_hash({"runtime": "auditor-test"})
    record = run_m15_live_direct_family_pilot(
        direct_workload=direct,
        base_bundle=base,
        catalog=root / "semantic_catalog.json",
        mapping=root / "predicate_mapping.json",
        protocol=root / "direct_family_pilot_protocol.json",
        predictor_policy=root / "direct_family_predictor_policy.json",
        clients=clients,
        runtime_compatibility_sha256=compatibility,
        output_root=root / "native-service-run",
        run_id="direct-family-pilot-run",
        repo_root=REPO_ROOT,
    )
    assert record.success, record.error
    schedule = json.loads(
        (record.run_root / "pilot_schedule.json").read_text(encoding="utf-8")
    )
    preflight_root = root / "native-service-run/direct-family-pilot-preflight"
    preflight_root.mkdir()
    (preflight_root / "pilot_schedule.json").write_text(
        json.dumps(schedule), encoding="utf-8"
    )
    (preflight_root / "preflight_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": DIRECT_FAMILY_PILOT_PREFLIGHT_SCHEMA_VERSION,
                "sealed_before_service_start": True,
                "schedule_sha256": schedule["schedule_sha256"],
                "online_cardinality": schedule["selection_boundary"][
                    "online_cardinality"
                ],
                "expected_counts": schedule["counts"],
                "backend_calls_before_seal": 0,
                "automatic_retries": 0,
                "paper_result": False,
            }
        ),
        encoding="utf-8",
    )
    service_status = {
        "schema_version": DIRECT_FAMILY_PILOT_SERVICE_RUN_SCHEMA_VERSION,
        "status": "success",
        "error": None,
    }
    (root / "native-service-run/run_status.json").write_text(
        json.dumps(service_status), encoding="utf-8"
    )
    (root / "native-service-run/run_manifest.json").write_text(
        json.dumps(service_status), encoding="utf-8"
    )
    (root / "run_status.json").write_text(
        json.dumps(
            {
                "status": "success",
                "exit_code": 0,
                "git_commit": COMMIT,
                "workload_mode": "direct_family_pilot",
                "runtime_removed": True,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_auditor_reconstructs_the_native_pilot_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _native_run(tmp_path, monkeypatch)

    audit = audit_m15_direct_family_pilot(
        run_root=root,
        expected_commit=COMMIT,
    )

    assert audit.success, audit.failed_check_ids
    assert audit.run_tree_mutated is False
    assert len(audit.checks) > 900


def test_auditor_rejects_analysis_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _native_run(tmp_path, monkeypatch)
    path = root / "native-service-run/direct-family-pilot-run/analysis.json"
    analysis = json.loads(path.read_text(encoding="utf-8"))
    analysis["physical_winner_accuracy"]["accuracy"] = -1
    path.write_text(json.dumps(analysis), encoding="utf-8")

    audit = audit_m15_direct_family_pilot(
        run_root=root,
        expected_commit=COMMIT,
    )

    assert not audit.success
    assert "analysis.exact" in audit.failed_check_ids
    assert audit.run_tree_mutated is False


def test_compact_summary_accepts_only_the_successful_read_only_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _native_run(tmp_path, monkeypatch)
    audit = audit_m15_direct_family_pilot(
        run_root=root,
        expected_commit=COMMIT,
    ).to_dict()

    summary = build_m15_direct_family_pilot_summary(
        run_root=root,
        audit=audit,
    )

    assert summary["schema_version"] == DIRECT_FAMILY_PILOT_SUMMARY_SCHEMA_VERSION
    assert 2 <= summary["counts"]["online_selected_plan_runs"] <= 8
    assert summary["counts"]["total_plan_runs"] == (
        224 + summary["counts"]["online_selected_plan_runs"]
    )
    assert summary["counts"]["total_backend_calls"] == (
        2 * summary["counts"]["total_plan_runs"]
    )
    assert summary["execution_boundary"] == {
        "current_query_profile_calls": 0,
        "shadow_used_for_selection": False,
        "automatic_retries": 0,
    }
    assert summary["audit"]["failed_check_ids"] == []
    assert summary["paper_result"] is False

    rejected = dict(audit)
    rejected["success"] = False
    with pytest.raises(ValueError, match="accepted read-only audit"):
        build_m15_direct_family_pilot_summary(
            run_root=root,
            audit=rejected,
        )


def test_results_blind_physical_baselines_reconstruct_five_frozen_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _native_run(tmp_path, monkeypatch)
    audit = audit_m15_direct_family_pilot(
        run_root=root,
        expected_commit=COMMIT,
    ).to_dict()

    analysis = analyze_m15_direct_family_baselines(
        run_root=root,
        audit=audit,
        policy=CONFIGS / "m15_f2c11_physical_baselines_dev.json",
    )

    assert analysis["schema_version"] == (
        DIRECT_FAMILY_BASELINE_ANALYSIS_SCHEMA_VERSION
    )
    assert list(analysis["methods"]) == [
        "family_memory_primary",
        "family_global_no_instance_features",
        "fixed_parallel_hash",
        "fixed_risk_first_bind",
        "observed_oracle_upper_bound",
    ]
    assert len(analysis["per_semantic_task"]) == 10
    assert all(
        method["semantic_task_count"] == 10
        for method in analysis["methods"].values()
    )
    oracle = analysis["methods"]["observed_oracle_upper_bound"]
    assert oracle["physical_winner_accuracy"] == 1.0
    assert oracle["latency_regret_ms"]["maximum"] == 0.0
    assert all(
        method[metric]["minimum"] >= 0
        for method in analysis["methods"].values()
        for metric in ("latency_regret_ms", "bytes_regret")
    )
    assert analysis["analysis_backend_calls"] == 0
    assert analysis["analysis_scope"] == (
        "physical_strategy_within_semantic_class"
    )
    assert analysis["semantic_frontier_comparison"] is False
    assert analysis["live_current_query_profiling_baseline"] is False
    assert analysis["current_query_observation_operations"] == []
    assert analysis[
        "online_selected_results_used_for_selection_or_metrics"
    ] is False
    assert analysis[
        "answer_row_values_used_for_selection_or_metrics"
    ] is False
    assert analysis["paper_result"] is False

    rejected = dict(audit)
    rejected["success"] = False
    with pytest.raises(ValueError, match="accepted F2C10D audit"):
        analyze_m15_direct_family_baselines(
            run_root=root,
            audit=rejected,
            policy=CONFIGS / "m15_f2c11_physical_baselines_dev.json",
        )


def test_results_blind_physical_baselines_reaudit_source_before_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _native_run(tmp_path, monkeypatch)
    audit = audit_m15_direct_family_pilot(
        run_root=root,
        expected_commit=COMMIT,
    ).to_dict()
    source = next(
        (
            root
            / "native-service-run/direct-family-pilot-run/selection/queries"
        ).glob("*/prediction_source.json")
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["predictions"][0]["estimated_latency_ms"] += 1
    source.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="no longer passes"):
        analyze_m15_direct_family_baselines(
            run_root=root,
            audit=audit,
            policy=CONFIGS / "m15_f2c11_physical_baselines_dev.json",
        )
