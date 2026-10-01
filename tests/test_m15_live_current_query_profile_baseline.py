from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.m15_direct_family_prediction_run import (
    _ControlledState,
    _clients_after_selection_seal,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_current_query_profile_baseline import (
    LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION,
    run_m15_live_current_query_profile_baseline,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
PROTOCOL = CONFIGS / "m15_f2c12_current_query_profile_baseline_dev.json"
CATALOG = CONFIGS / "m15_f2c6_semantic_relaxation_dev.json"
MAPPING = CONFIGS / "m15_f2c8_predicate_mapping_dev.json"


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
    record = run_m15_live_current_query_profile_baseline(
        direct_workload=direct,
        base_bundle=base,
        catalog=CATALOG,
        mapping=MAPPING,
        protocol=PROTOCOL,
        clients=clients,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )
    return record, state


def test_live_profile_baseline_executes_frozen_cost_inclusive_protocol(
    tmp_path: Path,
) -> None:
    record, state = _run(tmp_path)

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    seal = json.loads(
        (record.run_root / "selection_seal.json").read_text(encoding="utf-8")
    )
    acquisition_validation = json.loads(
        (record.run_root / "acquisition_validation.json").read_text(
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

    assert manifest["schema_version"] == (
        LIVE_CURRENT_QUERY_PROFILE_BASELINE_SCHEMA_VERSION
    )
    assert manifest["summary"] == {
        "acquisition_plan_runs": 20,
        "selected_plan_runs": 10,
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 110,
        "acquisition_backend_calls": 40,
        "selected_plan_backend_calls": 20,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 220,
    }
    assert state.invocation_count == 220
    assert invocations["total_tool_invocations"] == 220
    phases = [item["profile_baseline_phase"] for item in invocations["events"]]
    assert phases[:40] == ["current_query_profile_acquisition"] * 40
    assert phases[40:60] == ["selected_plan_execution"] * 20
    assert phases[60:] == ["postselection_shadow_evaluation"] * 160

    assert seal["profile_backend_calls_before_seal"] == 40
    assert seal["selected_execution_backend_calls_before_seal"] == 0
    assert seal["shadow_backend_calls_before_seal"] == 0
    assert seal["answer_oracle_opened_before_seal"] is False
    assert seal["answer_rows_selection_input"] is False
    assert len(seal["selections"]) == 10
    assert acquisition_validation["opened_after_selection_seal"] is True
    assert acquisition_validation["all_exact"] is True

    assert analysis["semantic_task_count"] == 10
    assert len(analysis["per_semantic_task"]) == 10
    assert analysis["current_query_profile_operations"] == 20
    assert analysis["current_query_profile_backend_calls"] == 40
    assert analysis["training_memory_used"] is False
    assert analysis["shadow_measurements_used_for_evaluation_only"] is True
    assert analysis["paper_result"] is False
    assert manifest["validation"]["passed"] is True


def test_first_selected_failure_stops_without_shadow_or_retry(
    tmp_path: Path,
) -> None:
    record, state = _run(tmp_path, fail_at=41)

    assert not record.success
    assert "selected profile plan failed" in str(record.error)
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["summary"]["acquisition_plan_runs"] == 20
    assert manifest["summary"]["acquisition_backend_calls"] == 40
    assert manifest["summary"]["evaluation_shadow_plan_runs"] == 0
    assert manifest["summary"]["evaluation_shadow_backend_calls"] == 0
    assert manifest["automatic_retries"] == 0
    assert invocations["automatic_retries"] == 0
    assert 41 <= state.invocation_count <= 42
    assert state.invocation_count == invocations["total_tool_invocations"]
