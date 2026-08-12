from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.artifacts import RUN_FILES
from xgap.experiments.run import run_experiment


def test_controlled_financial_risk_development_run(tmp_path: Path) -> None:
    result = run_experiment(
        "experiments/configs/financial_risk_xgap_dev.json",
        output_root_override=tmp_path,
        run_id_override="m12-integration",
    )

    assert len(result.question_results) == 2
    assert result.successful_question_count == 2
    assert all(item.status == "ok" for item in result.question_results)
    assert all((result.run_root / relative).exists() for relative in RUN_FILES)
    assert len(list((result.run_root / "plans/logical").glob("*.json"))) == 3
    assert len(list((result.run_root / "plans/physical").glob("*.json"))) == 3
    assert len(list((result.run_root / "queries").glob("*.xgap"))) == 3

    manifest = json.loads(
        (result.run_root / "experiment_manifest.json").read_text(encoding="utf-8")
    )
    metrics = json.loads((result.run_root / "metrics.json").read_text(encoding="utf-8"))
    raw_status = json.loads(
        (result.run_root / "results/raw/status.json").read_text(encoding="utf-8")
    )
    assert manifest["dataset"]["id"] == "financial_risk_dev"
    assert manifest["model"]["id"] == "mock_path_pattern_dev"
    assert manifest["semantic_deviation"]["config"]["method"] == "directional_ontology_hop"
    assert metrics["physical_planning"]["states_processed"]["status"] == "available"
    assert metrics["physical_planning"]["true_regret"]["status"] == "not_available"
    assert raw_status["status"] == "not_available"

    alignments = [
        json.loads(line)
        for line in (result.run_root / "alignment_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    deviations = {
        item["candidate_id"]: item["semantic_deviation"]["value"]
        for item in alignments
    }
    assert deviations["fr-q001-exact"] == 0
    assert deviations["fr-q013-generalized"] > 0

