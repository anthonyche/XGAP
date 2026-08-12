import json
from pathlib import Path

from xgap.experiments.physical_planner import run_physical_planner


ROOT = Path(__file__).resolve().parents[1]


def test_controlled_runner_writes_reproducible_planner_artifacts(tmp_path) -> None:
    artifacts = run_physical_planner(
        ROOT / "examples" / "configs" / "m11_controlled_planner.json",
        runs_dir_override=tmp_path,
    )

    assert artifacts.result.status == "ok"
    assert len(artifacts.result.selected_plans) == 2
    for path in artifacts.paths.values():
        assert Path(path).exists()
    summary = json.loads(Path(artifacts.paths["summary"]).read_text(encoding="utf-8"))
    assert summary["selected_count"] == 2
    assert summary["ontology_alignment_provider"] == "artifact-ontology-alignment"
    assert "no distributed cross-backend runtime" in summary["unsupported_boundaries"]
    compiled = artifacts.run_root / "compiled"
    assert sorted(path.suffix for path in compiled.glob("*.xgap")) == [".xgap", ".xgap"]
