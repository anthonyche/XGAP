from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.m15_method_matrix import (
    main,
    run_m15_controlled_method_matrix,
)
from xgap.experiments.m15_method_policy import M15Method
from xgap.experiments.m15_workload import (
    M15WorkloadSpec,
    generate_m15_workload_bundle,
)


def _bundle(tmp_path: Path):
    return generate_m15_workload_bundle(
        M15WorkloadSpec(
            workload_id="matrix-test",
            seed="matrix-test-v1",
            company_count=20,
            transfer_count=100,
            high_risk_company_count=4,
            hot_company_count=3,
            hot_transfer_count=80,
            high_risk_placement="cold_first",
            max_bindings=20,
        ),
        tmp_path / "bundle",
    )


def test_controlled_matrix_exercises_every_distinct_method(tmp_path: Path) -> None:
    record = run_m15_controlled_method_matrix(
        workload_bundle=_bundle(tmp_path),
        output_root=tmp_path,
        run_id="matrix-run",
    )

    assert record.success, record.error
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    validation = json.loads(
        (record.run_root / "validation.json").read_text(encoding="utf-8")
    )
    assert validation["passed"] is True
    assert validation["checks"]["tool_events_match_task_accounting"] is True
    assert set(manifest["methods"]) == {method.value for method in M15Method}
    assert manifest["calibration"]["attempted_calls"] == 3
    assert manifest["calibration_accounting"]["included_in_method_metrics"] is False
    assert manifest["calibration_accounting"]["seed_memory_writes"] == 3
    assert manifest["paper_result"] is False

    methods = manifest["methods"]
    assert methods[M15Method.NO_MEMORY.value]["total_backend_calls"] == 5
    assert methods[M15Method.NO_PROFILE_PROBE.value]["total_backend_calls"] == 2
    assert methods[M15Method.NO_REPLAN.value]["replan_count"] == 0
    assert methods[M15Method.FULL_AGENT.value]["replan_count"] == 1
    assert methods[M15Method.FULL_AGENT.value]["executed_plan_id"].endswith(
        "risk-first-bind"
    )
    assert methods[M15Method.NO_REPLAN.value]["executed_plan_id"].endswith(
        "parallel-hash"
    )
    assert all(value["exact_answer"] is True for value in methods.values())
    assert sorted(path.name for path in (record.run_root / "methods").iterdir()) == [
        f"{method.value}.json" for method in sorted(M15Method, key=lambda item: item.value)
    ]


def test_controlled_matrix_refuses_overwrite(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    run_m15_controlled_method_matrix(
        workload_bundle=bundle,
        output_root=tmp_path,
        run_id="immutable-run",
    )

    with pytest.raises(FileExistsError):
        run_m15_controlled_method_matrix(
            workload_bundle=bundle,
            output_root=tmp_path,
            run_id="immutable-run",
        )


def test_controlled_matrix_cli_is_explicitly_gated(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("XGAP_RUN_M15_METHOD_MATRIX", raising=False)

    assert main(["--workload-bundle", "unused"]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
