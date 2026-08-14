from __future__ import annotations

import json
from pathlib import Path

import pytest

from xgap.experiments.calibrate import run_calibration
from xgap.experiments.calibration_sanity import inspect_calibration
from xgap.experiments.online_run import run_online_experiment


@pytest.fixture()
def calibration_root(tmp_path: Path) -> Path:
    return run_calibration(
        "experiments/configs/financial_risk_gp_calibration_dev.json",
        output_root_override=tmp_path / "calibration",
        offline=True,
    ).run_root


def _tasks(run_root: Path) -> list[dict]:
    return [
        json.loads(path.read_text())
        for path in sorted((run_root / "tasks").glob("*.json"))
    ]


def test_online_runner_commits_d0_to_d1_to_d2_after_each_task(
    tmp_path: Path, calibration_root: Path
) -> None:
    result = run_online_experiment(
        "experiments/configs/financial_risk_m12d_dev.json",
        output_root_override=tmp_path / "runs",
        calibration_root_override=calibration_root,
        offline=True,
    )
    assert result.status == "complete"
    tasks = _tasks(result.run_root)
    counts_0 = sum(tasks[0]["pre_task_posterior"]["observation_counts"].values())
    counts_1 = sum(tasks[1]["pre_task_posterior"]["observation_counts"].values())
    assert counts_1 == counts_0 + 1
    assert tasks[0]["within_task_update"] is False
    assert tasks[0]["posterior_commit_timing"] == "after_all_task_executions"
    assert all(
        update["hyperparameters_unchanged"]
        for task in tasks
        for update in task["posterior_updates"]
    )
    assert any(
        record["informative_change"]
        for record in tasks[0]["posterior_change_diagnostics"]["records"]
    )
    assert [row["row_count"] for task in tasks for row in task["execution_results"]] == [1, 1]
    assert all(
        row["result_status"] == "execution_success_nonempty"
        for task in tasks
        for row in task["execution_results"]
    )
    assert (result.run_root / "server_environment.json").exists()
    assert (result.run_root / "paper_freeze_manifest.json").exists()
    metrics = json.loads((result.run_root / "metrics.json").read_text())
    assert metrics["states_generated"] > 0
    assert metrics["cost_prediction_absolute_error_ms"]["count"] == 2
    assert 0.0 <= metrics["empirical_confidence_coverage"] <= 1.0
    assert metrics["confidence_coverage_is_theoretical_proof"] is False


def test_online_runner_resumes_without_reexecuting_completed_task(
    tmp_path: Path, calibration_root: Path
) -> None:
    first = run_online_experiment(
        "experiments/configs/financial_risk_m12d_dev.json",
        output_root_override=tmp_path / "runs",
        calibration_root_override=calibration_root,
        offline=True,
        stop_after_tasks=1,
    )
    first_task = (first.run_root / "tasks/000001.json").read_bytes()
    assert first.status == "incomplete"
    resumed = run_online_experiment(
        "experiments/configs/financial_risk_m12d_dev.json",
        output_root_override=tmp_path / "runs",
        calibration_root_override=calibration_root,
        offline=True,
        resume=True,
    )
    assert resumed.status == "complete"
    assert resumed.resumed
    assert (resumed.run_root / "tasks/000001.json").read_bytes() == first_task
    assert json.loads((resumed.run_root / "checkpoint.json").read_text())["next_task_index"] == 3


def test_completed_run_collision_is_rejected(tmp_path: Path, calibration_root: Path) -> None:
    run_online_experiment(
        "experiments/configs/financial_risk_m12d_dev.json",
        output_root_override=tmp_path,
        calibration_root_override=calibration_root,
        offline=True,
    )
    with pytest.raises(FileExistsError, match="Completed run"):
        run_online_experiment(
            "experiments/configs/financial_risk_m12d_dev.json",
            output_root_override=tmp_path,
            calibration_root_override=calibration_root,
            offline=True,
            resume=True,
        )


def test_calibration_sanity_records_query_hash_latency_and_empty_flag(
    calibration_root: Path,
) -> None:
    report = inspect_calibration(
        calibration_root,
        config_path="experiments/configs/financial_risk_gp_calibration_dev.json",
    )
    assert report["records"]
    assert all(record["query_hash"] for record in report["records"])
    assert all(record["latencies_ms"] for record in report["records"])
    assert report["suspicious_empty_calibration_queries"]


def test_unsupported_task_advances_posterior_before_next_supported_task(
    tmp_path: Path, calibration_root: Path
) -> None:
    raw = json.loads(
        Path("experiments/configs/financial_risk_m12d_dev.json").read_text()
    )
    raw["run_id"] = "m12d-unsupported-then-supported"
    raw["question_ids"] = ["fr-q006", "fr-q001"]
    config = tmp_path / "unsupported-then-supported.json"
    config.write_text(json.dumps(raw))

    result = run_online_experiment(
        config,
        output_root_override=tmp_path / "runs",
        calibration_root_override=calibration_root,
        offline=True,
    )

    tasks = _tasks(result.run_root)
    assert result.status == "complete"
    assert tasks[0]["failure_category"] == "missing_mapping"
    assert tasks[0]["online_observations"] == []
    assert all(update["batch_size"] == 0 for update in tasks[0]["posterior_updates"])
    assert tasks[1]["pre_task_posterior"]["task_index"] == 2
