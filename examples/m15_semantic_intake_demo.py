"""Run the controlled M15-E3 semantic-intake example without a model."""

from __future__ import annotations

import json
from pathlib import Path

from xgap.experiments.m15_semantic_intake import run_semantic_intake


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    result = run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=(
            REPO_ROOT / "experiments/configs/m15_e3_financial_risk_intake_dev.json"
        ),
        catalog_path=(
            REPO_ROOT / "experiments/specs/m15_e3_financial_risk_catalog_dev.json"
        ),
        ontology_path=(
            REPO_ROOT / "experiments/specs/m15_e3_financial_risk_ontology_dev.json"
        ),
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="explicit-development-demo-selection",
    )
    summary = {
        "status": result["goal_state"]["status"],
        "resolution": result["goal_state"]["output"],
        "cost": result["cost"],
        "artifacts": result["artifacts"],
        "paper_result": result["paper_result"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
