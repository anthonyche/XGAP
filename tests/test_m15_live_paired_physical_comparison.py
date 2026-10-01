from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_direct_family_prediction_run import (
    _ControlledState,
    _clients_after_selection_seal,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_paired_physical_comparison import (
    LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION,
    run_m15_live_paired_physical_comparison,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
PROTOCOL = CONFIGS / "m15_f2c13_paired_physical_comparison_dev.json"
FAMILY_PROTOCOL = CONFIGS / "m15_f2c10d_family_memory_pilot_dev.json"
PREDICTOR = CONFIGS / "m15_f2c10_family_memory_predictor_dev.json"
PROFILE_PROTOCOL = CONFIGS / "m15_f2c12_current_query_profile_baseline_dev.json"
CATALOG = CONFIGS / "m15_f2c6_semantic_relaxation_dev.json"
MAPPING = CONFIGS / "m15_f2c8_predicate_mapping_dev.json"
RUNTIME_HASH = content_hash(
    {
        "runtime": "f2c13b-live-paired-test",
        "neo4j": "oracle-double",
        "fuseki": "oracle-double",
    }
)


def _bundles(tmp_path: Path):
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
        catalog=CATALOG,
        mapping=MAPPING,
        policy=CONFIGS / "m15_f2c10_direct_semantic_workload_dev.json",
        destination=tmp_path / "direct",
    )
    return base, direct


def _run(tmp_path: Path, *, fail_at: int | None = None):
    base, direct = _bundles(tmp_path)
    state = _ControlledState(fail_at_invocation=fail_at)
    clients = _clients_after_selection_seal(direct.workload_bundle, state=state)
    record = run_m15_live_paired_physical_comparison(
        direct_workload=direct,
        base_bundle=base,
        catalog=CATALOG,
        mapping=MAPPING,
        protocol=PROTOCOL,
        family_protocol=FAMILY_PROTOCOL,
        predictor_policy=PREDICTOR,
        profile_protocol=PROFILE_PROTOCOL,
        clients=clients,
        runtime_compatibility_sha256=RUNTIME_HASH,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )
    return record, state


def test_live_paired_runner_executes_exact_frozen_budget(tmp_path: Path) -> None:
    record, state = _run(tmp_path)

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    family_seal = json.loads(
        (record.run_root / "family_selection_seal.json").read_text(
            encoding="utf-8"
        )
    )
    profile_seal = json.loads(
        (record.run_root / "profile_selection_seal.json").read_text(
            encoding="utf-8"
        )
    )
    analysis = json.loads(
        (record.run_root / "analysis.json").read_text(encoding="utf-8")
    )
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["schema_version"] == LIVE_PAIRED_PHYSICAL_SCHEMA_VERSION
    assert manifest["summary"] == {
        "training_plan_runs": 144,
        "profile_acquisition_plan_runs": 20,
        "paired_selected_plan_runs": 20,
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 264,
        "training_backend_calls": 288,
        "profile_acquisition_backend_calls": 40,
        "paired_selected_backend_calls": 40,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 528,
        "family_memory_current_query_profile_calls": 0,
        "profile_method_current_query_profile_calls": 20,
    }
    assert state.invocation_count == 528
    assert invocations["total_tool_invocations"] == 528
    phases = [item["paired_phase"] for item in invocations["events"]]
    assert phases[:288] == ["training_measurement"] * 288
    assert phases[288:328] == ["current_query_profile_acquisition"] * 40
    assert phases[328:368] == ["paired_selected_execution"] * 40
    assert phases[368:] == ["postselection_shadow_evaluation"] * 160

    assert family_seal["training_backend_calls_before_seal"] == 288
    assert family_seal["profile_backend_calls_before_seal"] == 0
    assert family_seal["heldout_answer_oracle_fields"] == []
    assert len(family_seal["selections"]) == 10
    assert profile_seal["training_backend_calls_before_seal"] == 288
    assert profile_seal["profile_backend_calls_before_seal"] == 40
    assert profile_seal["selected_backend_calls_before_seal"] == 0
    assert profile_seal["answer_oracle_opened_before_seal"] is False
    assert len(profile_seal["selections"]) == 10

    assert set(analysis["methods"]) == {
        "family_memory",
        "current_query_dual_profile",
    }
    assert analysis["semantic_task_count"] == 10
    assert analysis["profile_acquisition"]["plan_runs"] == 20
    assert analysis["historical_training"]["plan_runs"] == 144
    assert analysis["count_based_training_break_even_future_tasks"] == 72
    assert set(analysis["evaluation_only_controls"]) == {
        "fixed_parallel_hash",
        "fixed_risk_first_bind",
        "observed_oracle_upper_bound",
    }
    assert analysis["confirmatory_statistics"] is False
    assert analysis["paper_result"] is False
    assert manifest["validation"]["passed"] is True


def test_first_profile_failure_stops_without_selection_execution_or_retry(
    tmp_path: Path,
) -> None:
    record, state = _run(tmp_path, fail_at=289)

    assert not record.success
    assert "paired profile acquisition failed" in str(record.error)
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    assert (record.run_root / "family_selection_seal.json").is_file()
    assert not (record.run_root / "profile_selection_seal.json").exists()
    assert manifest["summary"]["training_plan_runs"] == 144
    assert manifest["summary"]["paired_selected_plan_runs"] == 0
    assert manifest["summary"]["evaluation_shadow_plan_runs"] == 0
    assert manifest["automatic_retries"] == 0
    assert invocations["automatic_retries"] == 0
    assert 289 <= state.invocation_count <= 290
    assert state.invocation_count == invocations["total_tool_invocations"]


def test_first_selected_failure_stops_without_shadow_or_retry(
    tmp_path: Path,
) -> None:
    record, state = _run(tmp_path, fail_at=329)

    assert not record.success
    assert "paired selected plan failed" in str(record.error)
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert (record.run_root / "profile_selection_seal.json").is_file()
    assert manifest["summary"]["profile_acquisition_plan_runs"] == 20
    assert manifest["summary"]["evaluation_shadow_plan_runs"] == 0
    assert manifest["summary"]["evaluation_shadow_backend_calls"] == 0
    assert manifest["automatic_retries"] == 0
    assert 329 <= state.invocation_count <= 330
