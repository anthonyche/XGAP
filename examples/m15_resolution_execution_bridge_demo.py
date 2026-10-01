"""Show the capability-aware E3-to-family bridge on controlled artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from xgap.experiments.m15_resolution_execution_bridge import (
    compile_m15_resolution_execution_bridge,
)
from xgap.experiments.m15_semantic_intake import run_semantic_intake


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    resolution = run_semantic_intake(
        question="查找过去一个月与 Alice 有密切资金往来的高风险公司。",
        intake_path=(
            REPO_ROOT
            / "experiments/configs/m15_e3_financial_risk_intake_dev.json"
        ),
        catalog_path=(
            REPO_ROOT
            / "experiments/specs/m15_e3_financial_risk_catalog_dev.json"
        ),
        ontology_path=(
            REPO_ROOT
            / "experiments/specs/m15_e3_financial_risk_ontology_dev.json"
        ),
        user_selections={"person-identity": "person:alice-smith"},
        user_source_id="explicit-e4-development-selection",
    )
    spec_path = (
        REPO_ROOT
        / "experiments/configs/m15_e4_resolution_execution_bridge_dev.json"
    )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    plan = compile_m15_resolution_execution_bridge(
        resolution,
        spec,
        repo_root=REPO_ROOT,
        bridge_spec_sha256=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
    ).to_dict()
    print(
        json.dumps(
            {
                "counts": plan["counts"],
                "resolution": plan["resolution"],
                "semantic_classes": [
                    {
                        "semantic_class_id": item["semantic_class_id"],
                        "selected_candidate_ids": item["selected_candidate_ids"],
                        "availability": item["availability"],
                        "missing_capability_ids": item[
                            "missing_capability_ids"
                        ],
                    }
                    for item in plan["semantic_classes"]
                ],
                "paper_result": plan["paper_result"],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
