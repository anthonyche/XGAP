from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import xgap.experiments.m15_live_current_query_profile_baseline as live_profile

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_current_query_profile_baseline_evidence import (
    audit_m15_current_query_profile_baseline,
)
from xgap.experiments.m15_direct_family_prediction_run import (
    _ControlledState,
    _clients_after_selection_seal,
)
from xgap.experiments.m15_direct_semantic_workload import (
    generate_m15_direct_semantic_workload_bundle,
)
from xgap.experiments.m15_live_current_query_profile_baseline import (
    run_m15_live_current_query_profile_baseline,
)
from xgap.experiments.m15_parameterized_workload import (
    generate_m15_parameterized_workload_bundle,
)
from xgap.experiments.m15_native_services import (
    CURRENT_QUERY_PROFILE_PREFLIGHT_SCHEMA_VERSION,
    CURRENT_QUERY_PROFILE_SERVICE_RUN_SCHEMA_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "experiments/configs"
COMMIT = "2" * 40


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
        live_profile,
        "_git_state",
        lambda _root: {"commit": COMMIT, "clean": True},
    )
    record = run_m15_live_current_query_profile_baseline(
        direct_workload=direct,
        base_bundle=base,
        catalog=CONFIGS / "m15_f2c6_semantic_relaxation_dev.json",
        mapping=CONFIGS / "m15_f2c8_predicate_mapping_dev.json",
        protocol=(
            CONFIGS / "m15_f2c12_current_query_profile_baseline_dev.json"
        ),
        clients=clients,
        output_root=tmp_path / "runs",
        repo_root=REPO_ROOT,
    )
    assert record.success, record.error
    assert state.invocation_count == 220
    return record.run_root


def _wrap_as_native_run(live: Path, destination: Path) -> Path:
    service = destination / "native-service-run"
    service.mkdir(parents=True)
    nested = service / "current-query-profile-baseline-run"
    live.rename(nested)
    schedule = json.loads(
        (nested / "profile_schedule.json").read_text(encoding="utf-8")
    )
    preflight_root = service / "current-query-profile-preflight"
    preflight_root.mkdir()
    (preflight_root / "profile_schedule.json").write_text(
        json.dumps(schedule), encoding="utf-8"
    )
    preflight = {
        "schema_version": CURRENT_QUERY_PROFILE_PREFLIGHT_SCHEMA_VERSION,
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
    service_status = {
        "schema_version": CURRENT_QUERY_PROFILE_SERVICE_RUN_SCHEMA_VERSION,
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
                "workload_mode": "current_query_profile_baseline",
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
            "m15_f2c12_current_query_profile_baseline_dev.json",
            "current_query_profile_protocol.json",
        ),
    ):
        shutil.copyfile(CONFIGS / source, destination / target)
    return destination


def test_auditor_reconstructs_selection_and_analysis_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _run(tmp_path, monkeypatch)
    root = _wrap_as_native_run(live, tmp_path / "native-profile-run")

    audit = audit_m15_current_query_profile_baseline(
        run_root=root,
        expected_commit=COMMIT,
    )

    assert audit.success, audit.failed_check_ids
    assert audit.run_tree_mutated is False
    assert len(audit.checks) > 470

    schedule_path = (
        root
        / "native-service-run/current-query-profile-baseline-run/"
        "profile_schedule.json"
    )
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["counts"]["total_plan_runs"] = 999
    schedule["schedule_sha256"] = content_hash(
        {key: value for key, value in schedule.items() if key != "schedule_sha256"}
    )
    schedule_path.write_text(json.dumps(schedule), encoding="utf-8")

    rejected = audit_m15_current_query_profile_baseline(
        run_root=root,
        expected_commit=COMMIT,
    )

    assert not rejected.success
    assert "schedule.source_reconstruction" in rejected.failed_check_ids


@pytest.mark.parametrize(
    ("relative_path", "mutate", "failed_check"),
    [
        (
            "analysis.json",
            lambda value: value["physical_winner_accuracy"].update(
                {"accuracy": -1}
            ),
            "analysis.exact",
        ),
        (
            "profile_cost_estimates.json",
            lambda value: value["estimates"][0].update({"elapsed_ms": -1}),
            "estimate.reconstruction",
        ),
        (
            "selection_seal.json",
            lambda value: value["selections"][0].update(
                {"selected_plan_id": "tampered-plan"}
            ),
            "selection.reconstruction",
        ),
    ],
)
def test_auditor_rejects_evidence_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    mutate,
    failed_check: str,
) -> None:
    root = _run(tmp_path, monkeypatch)
    path = root / relative_path
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value), encoding="utf-8")

    audit = audit_m15_current_query_profile_baseline(
        run_root=root,
        expected_commit=COMMIT,
    )

    assert not audit.success
    assert failed_check in audit.failed_check_ids
    assert audit.run_tree_mutated is False
