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
from xgap.experiments.m15_live_direct_family_pilot import (
    LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION,
    run_m15_live_direct_family_pilot,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
PROTOCOL = CONFIGS / "m15_f2c10d_family_memory_pilot_dev.json"
PREDICTOR = CONFIGS / "m15_f2c10_family_memory_predictor_dev.json"
CATALOG = CONFIGS / "m15_f2c6_semantic_relaxation_dev.json"
MAPPING = CONFIGS / "m15_f2c8_predicate_mapping_dev.json"
RUNTIME_HASH = content_hash(
    {
        "runtime": "f2c10d-live-pilot-test",
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
    record = run_m15_live_direct_family_pilot(
        direct_workload=direct,
        base_bundle=base,
        catalog=CATALOG,
        mapping=MAPPING,
        protocol=PROTOCOL,
        predictor_policy=PREDICTOR,
        clients=clients,
        runtime_compatibility_sha256=RUNTIME_HASH,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )
    return record, state


def test_live_pilot_executes_bounded_option_a_protocol(tmp_path: Path) -> None:
    record, state = _run(tmp_path)

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    seal = json.loads(
        (record.run_root / "selection_seal.json").read_text(encoding="utf-8")
    )
    analysis = json.loads(
        (record.run_root / "analysis.json").read_text(encoding="utf-8")
    )
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )

    assert manifest["schema_version"] == LIVE_DIRECT_FAMILY_PILOT_SCHEMA_VERSION
    online_runs = manifest["summary"]["online_selected_plan_runs"]
    assert 2 <= online_runs <= 8
    assert manifest["summary"] == {
        "training_plan_runs": 144,
        "online_selected_plan_runs": online_runs,
        "evaluation_shadow_plan_runs": 80,
        "total_plan_runs": 224 + online_runs,
        "training_backend_calls": 288,
        "online_backend_calls": 2 * online_runs,
        "evaluation_shadow_backend_calls": 160,
        "total_backend_calls": 448 + 2 * online_runs,
        "current_query_profile_calls": 0,
    }
    assert state.invocation_count == 448 + 2 * online_runs
    assert invocations["total_tool_invocations"] == state.invocation_count
    phases = [event["pilot_phase"] for event in invocations["events"]]
    assert phases[:288] == ["training_measurement"] * 288
    online_end = 288 + 2 * online_runs
    assert phases[288:online_end] == ["online_selected_execution"] * (
        2 * online_runs
    )
    assert phases[online_end:] == ["postselection_shadow_evaluation"] * 160
    assert seal["training_backend_calls_before_seal"] == 288
    assert seal["online_backend_calls_before_seal"] == 0
    assert seal["shadow_backend_calls_before_seal"] == 0
    assert seal["current_query_profile_calls"] == 0
    assert seal["sealed_before_heldout_oracle_access"] is True
    assert analysis["prediction_error"]["plan_count"] == 20
    assert analysis["physical_winner_accuracy"]["semantic_class_count"] == 10
    assert len(analysis["predicted_observed_frontier_overlap"]["per_query"]) == 2
    assert analysis["confirmatory_statistics"] is False
    assert manifest["paper_result"] is False
    assert manifest["validation"]["passed"] is True


def test_first_online_failure_stops_without_shadow_or_retry(tmp_path: Path) -> None:
    record, state = _run(tmp_path, fail_at=289)

    assert not record.success
    assert "online selected plan failed" in str(record.error)
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    invocations = json.loads(
        (record.run_root / "backend_invocations.json").read_text(encoding="utf-8")
    )
    assert manifest["summary"]["training_plan_runs"] == 144
    assert manifest["summary"]["evaluation_shadow_plan_runs"] == 0
    assert manifest["summary"]["evaluation_shadow_backend_calls"] == 0
    assert manifest["automatic_retries"] == 0
    assert invocations["automatic_retries"] == 0
    assert 289 <= state.invocation_count <= 290
    assert state.invocation_count == invocations["total_tool_invocations"]
