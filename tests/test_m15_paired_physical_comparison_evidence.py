from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import xgap.experiments.m15_live_paired_physical_comparison as live_paired

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction_run import (
    _ControlledState,
    _clients_after_selection_seal,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_paired_physical_comparison import (
    run_m15_live_paired_physical_comparison,
)
from xgap.experiments.m15_native_services import (
    PAIRED_PHYSICAL_PREFLIGHT_SCHEMA_VERSION,
    PAIRED_PHYSICAL_SERVICE_RUN_SCHEMA_VERSION,
)
from xgap.experiments.m15_paired_physical_comparison_evidence import (
    audit_m15_paired_physical_comparison,
)
from xgap.experiments.m15_paired_physical_comparison_summary import (
    PAIRED_PHYSICAL_SUMMARY_SCHEMA_VERSION,
    build_m15_paired_physical_comparison_summary,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
COMMIT = "3" * 40
RUNTIME_BODY = {
    "schema_version": "m15-f2c5-native-runtime-compatibility-v1",
    "allocation_id": "controlled-paired-audit",
    "filesystem_type": "xfs",
    "java_major": 17,
    "runtime_lock_sha256": "4" * 64,
    "staging_manifest_sha256": "5" * 64,
    "services": [
        {"service_id": "fuseki", "product": "fuseki", "version": "test"},
        {"service_id": "neo4j", "product": "neo4j", "version": "test"},
    ],
    "reuse_scope": "same_native_service_allocation_only",
}
RUNTIME = {
    **RUNTIME_BODY,
    "runtime_compatibility_sha256": content_hash(RUNTIME_BODY),
}


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = generate_m15_parameterized_workload_bundle(
        workload_spec=CONFIGS / "m15_f2c_parameterized_workload_dev.json",
        query_template_spec=(
            CONFIGS / "m15_f2c_parameterized_financial_risk_v2.json"
        ),
        backend_template_root=(
            REPO_ROOT / "experiments/templates/m15_f2c_financial_risk"
        ),
        destination=tmp_path / "base",
    )
    direct = generate_m15_direct_semantic_workload_bundle(
        base_bundle=base,
        catalog=CONFIGS / "m15_f2c6_semantic_relaxation_dev.json",
        mapping=CONFIGS / "m15_f2c8_predicate_mapping_dev.json",
        policy=CONFIGS / "m15_f2c10_direct_semantic_workload_dev.json",
        destination=tmp_path / "direct",
    )
    state = _ControlledState()
    clients = _clients_after_selection_seal(direct.workload_bundle, state=state)
    monkeypatch.setattr(
        live_paired,
        "_git_state",
        lambda _root: {"commit": COMMIT, "clean": True},
    )
    record = run_m15_live_paired_physical_comparison(
        direct_workload=direct,
        base_bundle=base,
        catalog=CONFIGS / "m15_f2c6_semantic_relaxation_dev.json",
        mapping=CONFIGS / "m15_f2c8_predicate_mapping_dev.json",
        protocol=CONFIGS / "m15_f2c13_paired_physical_comparison_dev.json",
        family_protocol=CONFIGS / "m15_f2c10d_family_memory_pilot_dev.json",
        predictor_policy=CONFIGS / "m15_f2c10_family_memory_predictor_dev.json",
        profile_protocol=(
            CONFIGS / "m15_f2c12_current_query_profile_baseline_dev.json"
        ),
        clients=clients,
        runtime_compatibility_sha256=RUNTIME["runtime_compatibility_sha256"],
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )
    assert record.success, record.error
    assert state.invocation_count == 528
    return record.run_root


def _wrap_native(live: Path, destination: Path) -> Path:
    service = destination / "native-service-run"
    service.mkdir(parents=True)
    nested = service / "paired-physical-comparison-run"
    live.rename(nested)
    schedule = json.loads(
        (nested / "paired_schedule.json").read_text(encoding="utf-8")
    )
    preflight_root = service / "paired-physical-preflight"
    preflight_root.mkdir()
    (preflight_root / "paired_schedule.json").write_text(
        json.dumps(schedule), encoding="utf-8"
    )
    preflight = {
        "schema_version": PAIRED_PHYSICAL_PREFLIGHT_SCHEMA_VERSION,
        "sealed_before_service_start": True,
        "schedule_sha256": schedule["schedule_sha256"],
        "expected_counts": schedule["counts"],
        "backend_calls_before_seal": 0,
        "answer_oracle_opened_before_seal": False,
        "automatic_retries": 0,
        "paper_result": False,
    }
    (preflight_root / "preflight_manifest.json").write_text(
        json.dumps(preflight), encoding="utf-8"
    )
    (service / "family_runtime_compatibility.json").write_text(
        json.dumps(RUNTIME), encoding="utf-8"
    )
    service_status = {
        "schema_version": PAIRED_PHYSICAL_SERVICE_RUN_SCHEMA_VERSION,
        "status": "success",
        "error": None,
    }
    (service / "run_status.json").write_text(
        json.dumps(service_status), encoding="utf-8"
    )
    (service / "run_manifest.json").write_text(
        json.dumps(service_status), encoding="utf-8"
    )
    (destination / "run_status.json").write_text(
        json.dumps(
            {
                "status": "success",
                "exit_code": 0,
                "git_commit": COMMIT,
                "workload_mode": "paired_physical_comparison",
                "runtime_removed": True,
            }
        ),
        encoding="utf-8",
    )
    source_root = destination.parent
    (source_root / "base").rename(
        destination / "direct-family-base-workload-bundle"
    )
    (source_root / "direct").rename(
        destination / "direct-semantic-workload-bundle"
    )
    for source, target in (
        ("m15_f2c6_semantic_relaxation_dev.json", "semantic_catalog.json"),
        ("m15_f2c8_predicate_mapping_dev.json", "predicate_mapping.json"),
        (
            "m15_f2c13_paired_physical_comparison_dev.json",
            "paired_physical_protocol.json",
        ),
        (
            "m15_f2c10d_family_memory_pilot_dev.json",
            "direct_family_pilot_protocol.json",
        ),
        (
            "m15_f2c10_family_memory_predictor_dev.json",
            "direct_family_predictor_policy.json",
        ),
        (
            "m15_f2c12_current_query_profile_baseline_dev.json",
            "current_query_profile_protocol.json",
        ),
    ):
        shutil.copyfile(CONFIGS / source, destination / target)
    return destination


def test_auditor_reconstructs_both_selections_and_analysis_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _wrap_native(
        _run(tmp_path, monkeypatch), tmp_path / "native-paired-run"
    )

    audit = audit_m15_paired_physical_comparison(
        run_root=root,
        expected_commit=COMMIT,
    )

    assert audit.success, audit.failed_check_ids
    assert audit.run_tree_mutated is False
    assert len(audit.checks) > 1300

    summary = build_m15_paired_physical_comparison_summary(
        run_root=root,
        audit=audit.to_dict(),
    )

    assert summary["schema_version"] == PAIRED_PHYSICAL_SUMMARY_SCHEMA_VERSION
    assert summary["counts"]["total_plan_runs"] == 264
    assert summary["counts"]["total_backend_calls"] == 528
    assert summary["execution_boundary"] == {
        "family_memory_current_query_profile_calls": 0,
        "profile_method_current_query_profile_calls": 20,
        "shadow_measurements_used_for_evaluation_only": True,
        "automatic_retries": 0,
        "llm_calls_made": 0,
        "ontology_service_calls_made": 0,
    }
    assert set(summary["methods"]) == {
        "family_memory",
        "current_query_dual_profile",
    }
    assert len(summary["paired_profile_minus_memory"]["per_semantic_task"]) == 10
    assert summary["selection_agreement"]["semantic_task_count"] == 10
    assert summary["historical_training_cost"]["silently_amortized"] is False
    assert summary["claim_boundary"]["generalization_claim"] is False
    assert summary["paper_result"] is False

    rejected_audit = audit.to_dict()
    rejected_audit["success"] = False
    with pytest.raises(ValueError, match="accepted read-only audit"):
        build_m15_paired_physical_comparison_summary(
            run_root=root,
            audit=rejected_audit,
        )


@pytest.mark.parametrize(
    ("relative_path", "mutate", "failed_check"),
    [
        (
            "analysis.json",
            lambda value: value["methods"]["family_memory"][
                "physical_winner_accuracy"
            ].update({"accuracy": -1}),
            "analysis.exact",
        ),
        (
            "family_selection_seal.json",
            lambda value: value["selections"][0].update(
                {"selected_plan_id": "tampered-plan"}
            ),
            "family.selection_reconstruction",
        ),
        (
            "profile/profile_cost_estimates.json",
            lambda value: value["estimates"][0].update({"elapsed_ms": -1}),
            "profile.estimate_reconstruction",
        ),
    ],
)
def test_auditor_rejects_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    mutate,
    failed_check: str,
) -> None:
    root = _wrap_native(
        _run(tmp_path, monkeypatch), tmp_path / "native-paired-tamper-run"
    )
    path = (
        root
        / "native-service-run/paired-physical-comparison-run"
        / relative_path
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value), encoding="utf-8")

    audit = audit_m15_paired_physical_comparison(
        run_root=root,
        expected_commit=COMMIT,
    )

    assert not audit.success
    assert failed_check in audit.failed_check_ids
    assert audit.run_tree_mutated is False
