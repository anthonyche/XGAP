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
