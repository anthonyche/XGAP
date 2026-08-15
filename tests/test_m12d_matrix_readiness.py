from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.aggregate import aggregate_runs
from xgap.experiments.matrix import expand_matrix, run_matrix
from xgap.experiments.readiness import check_readiness


def test_matrix_expansion_is_deterministic_and_unique() -> None:
    _, first = expand_matrix("experiments/matrices/financial_risk_pilot.json")
    _, second = expand_matrix("experiments/matrices/financial_risk_pilot.json")
    assert len(first) == 12
    assert [item.run_id for item in first] == [item.run_id for item in second]
    assert len({item.run_id for item in first}) == len(first)


def test_matrix_dry_run_does_not_write_run_artifacts(tmp_path: Path) -> None:
    result = run_matrix(
        "experiments/matrices/financial_risk_pilot.json",
        output_root_override=tmp_path,
    )
    assert len(result.instances) == 12
    assert not result.matrix_root.exists()


def test_tiny_matrix_reuses_frozen_candidates_and_aggregates(tmp_path: Path) -> None:
    result = run_matrix(
        "experiments/matrices/financial_risk_pilot.json",
        execute=True,
        offline=True,
        output_root_override=tmp_path,
    )
    assert not result.failed
    assert len(result.executed) == 12
    artifact_hashes = set()
    runs_by_method: dict[str, list[Path]] = {}
    for run in result.executed:
        first_task = json.loads((run.run_root / "tasks/000001.json").read_text())
        artifact_hashes.add(first_task["candidate_artifact"]["artifact_hash"])
        method = first_task["method"]["method_id"]
        runs_by_method.setdefault(method, []).append(run.run_root)
    assert len(artifact_hashes) == 1
    assert set(runs_by_method) == {
        "full_xgap",
        "random_feasible",
        "mean_only",
        "no_pruning",
        "no_online_update",
        "single_backend",
    }
    random_task = json.loads(
        (runs_by_method["random_feasible"][0] / "tasks/000001.json").read_text()
    )
    assert random_task["sampled_decisions"]
    random_cost = random_task["planner_result"]["selected_plans"][0]["physical_plan"]["cost"]
    assert random_cost["metadata"]["not_a_cost_estimate"] is True
    mean_task = json.loads(
        (runs_by_method["mean_only"][0] / "tasks/000001.json").read_text()
    )
    mean_cost = mean_task["planner_result"]["selected_plans"][0]["physical_plan"]["cost"]
    assert mean_cost["beta"] == 0.0
    no_pruning_task = json.loads(
        (runs_by_method["no_pruning"][0] / "tasks/000001.json").read_text()
    )
    assert no_pruning_task["method"]["confidence_pruning"] is False
    assert not any(
        (event.get("prune_reason") or "").startswith(("current_lower", "successor_lower"))
        for event in no_pruning_task["search_trace"]
    )
    no_online_tasks = [
        json.loads(path.read_text())
        for path in sorted((runs_by_method["no_online_update"][0] / "tasks").glob("*.json"))
    ]
    assert (
        no_online_tasks[0]["pre_task_posterior"]["observation_counts"]
        == no_online_tasks[1]["pre_task_posterior"]["observation_counts"]
    )
    single_task = json.loads(
        (runs_by_method["single_backend"][0] / "tasks/000001.json").read_text()
    )
    placements = single_task["planner_result"]["selected_plans"][0]["physical_plan"]["state"]["placements"]
    assert {item["backend_id"] for item in placements} == {"neo4j"}
    aggregate = aggregate_runs(
        [item.run_root for item in result.executed],
        output_prefix=tmp_path / "aggregate",
    )
    assert aggregate.run_count == 12
    assert aggregate.output_json.exists()
    assert aggregate.output_csv.exists()

    repeated = run_matrix(
        "experiments/matrices/financial_risk_pilot.json",
        execute=True,
        offline=True,
        output_root_override=tmp_path,
    )
    assert not repeated.executed
    assert len(repeated.skipped_run_ids) == 12
    assert not repeated.failed


def test_readiness_python_and_image_gates_distinguish_modes(tmp_path: Path) -> None:
    development = check_readiness(
        "experiments/matrices/financial_risk_pilot.json",
        python_version_override=(3, 9, 18),
        image_overrides={"neo4j": "neo4j:5-community", "fuseki": "fuseki:latest"},
    )
    statuses = {item.check_id: item.status for item in development.checks}
    assert statuses["python_version"] == "warning"
    assert statuses["backend_image_pinning"] == "warning"
    assert statuses["backend_mapping_compiler_contract"] == "pass"
    assert statuses["calibration_mapping_identity"] == "warning"

    raw = json.loads(Path("experiments/configs/financial_risk_m12d_dev.json").read_text())
    raw["run_id"] = "paper-gate-test"
    raw["orchestration"]["experiment_mode"] = "paper"
    config = tmp_path / "paper.json"
    config.write_text(json.dumps(raw))
    paper = check_readiness(
        config,
        python_version_override=(3, 9, 18),
        image_overrides={"neo4j": "neo4j:5-community", "fuseki": "fuseki:latest"},
    )
    paper_statuses = {item.check_id: item.status for item in paper.checks}
    assert paper_statuses["python_version"] == "fail"
    assert paper_statuses["backend_image_pinning"] == "fail"
    assert not paper.ready


def test_readiness_accepts_python_310_for_paper_mode(tmp_path: Path) -> None:
    raw = json.loads(Path("experiments/configs/financial_risk_m12d_dev.json").read_text())
    raw["run_id"] = "paper-python-310-test"
    raw["orchestration"]["experiment_mode"] = "paper"
    config = tmp_path / "paper-python-310.json"
    config.write_text(json.dumps(raw))

    report = check_readiness(
        config,
        python_version_override=(3, 10, 12),
        image_overrides={
            "neo4j": "neo4j@sha256:" + "1" * 64,
            "fuseki": "stain/jena-fuseki@sha256:" + "2" * 64,
        },
    )

    python_check = next(item for item in report.checks if item.check_id == "python_version")
    assert python_check.status == "pass"
    assert python_check.details["version"] == [3, 10, 12]
