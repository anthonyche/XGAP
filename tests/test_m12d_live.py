from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from xgap.experiments.direct_baseline import run_direct_baseline
from xgap.experiments.matrix import run_matrix
from xgap.experiments.online_run import run_online_experiment


BACKEND_LIVE = (
    os.environ.get("XGAP_RUN_BACKENDS") == "1"
    and os.environ.get("XGAP_RUN_CALIBRATION") == "1"
    and os.environ.get("XGAP_RUN_M12D") == "1"
)
DIRECT_LIVE = (
    BACKEND_LIVE
    and os.environ.get("XGAP_RUN_LIVE_LLM") == "1"
    and bool(os.environ.get("DASHSCOPE_API_KEY"))
)


@pytest.mark.skipif(
    not BACKEND_LIVE,
    reason="Set backend, calibration, and M12-D live gates.",
)
def test_real_online_d0_d1_d2_and_row_count(tmp_path: Path) -> None:
    first = run_online_experiment(
        "experiments/configs/financial_risk_m12d_dev.json",
        output_root_override=tmp_path,
        calibration_root_override="runs/m12c-financial-risk-gp-calibration-dev",
        stop_after_tasks=1,
    )
    first_task = (first.run_root / "tasks/000001.json").read_bytes()
    assert first.status == "incomplete"
    result = run_online_experiment(
        "experiments/configs/financial_risk_m12d_dev.json",
        output_root_override=tmp_path,
        calibration_root_override="runs/m12c-financial-risk-gp-calibration-dev",
        resume=True,
    )
    assert result.status == "complete"
    assert result.resumed
    assert (result.run_root / "tasks/000001.json").read_bytes() == first_task
    execution_rows = [
        json.loads(line)
        for line in (result.run_root / "execution_results.jsonl").read_text().splitlines()
    ]
    tasks = [
        json.loads(path.read_text())
        for path in sorted((result.run_root / "tasks").glob("*.json"))
    ]
    assert len(execution_rows) == 2
    assert all(row["row_count"] is not None for row in execution_rows)
    assert all(
        row["result_status"]
        in {"execution_success_nonempty", "execution_success_empty"}
        for row in execution_rows
    )
    d0_count = sum(tasks[0]["pre_task_posterior"]["observation_counts"].values())
    d1_count = sum(tasks[1]["pre_task_posterior"]["observation_counts"].values())
    assert d1_count == d0_count + 1
    assert all(
        update["hyperparameters_unchanged"]
        for task in tasks
        for update in task["posterior_updates"]
    )
    assert any(
        record["informative_change"]
        for record in tasks[0]["posterior_change_diagnostics"]["records"]
    )


@pytest.mark.skipif(
    not BACKEND_LIVE,
    reason="Set backend, calibration, and M12-D live gates.",
)
def test_real_matrix_tiny_subset(tmp_path: Path) -> None:
    result = run_matrix(
        "experiments/matrices/financial_risk_pilot.json",
        execute=True,
        filters={
            "method": "full_xgap",
            "epsilon": "0.75",
            "budget": "32",
            "seed": "0",
        },
        output_root_override=tmp_path,
    )
    assert not result.failed
    assert len(result.executed) == 1
    assert result.executed[0].status == "complete"


@pytest.mark.skipif(
    not DIRECT_LIVE,
    reason="Set M12-D backend/live-LLM gates and DASHSCOPE_API_KEY.",
)
def test_real_direct_text2graphquery_smoke(tmp_path: Path) -> None:
    result = run_direct_baseline(
        "experiments/configs/financial_risk_direct_qwen_dev.json",
        output_root_override=tmp_path,
    )
    assert result.status == "complete"
    assert result.row_count is not None
