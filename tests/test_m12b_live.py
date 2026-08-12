from __future__ import annotations

import os
from pathlib import Path

import pytest

from xgap.experiments.run import run_experiment


LIVE_ENABLED = os.environ.get("XGAP_RUN_LIVE_LLM") == "1"
HAS_KEY = bool(os.environ.get("DASHSCOPE_API_KEY"))


@pytest.mark.skipif(
    not (LIVE_ENABLED and HAS_KEY),
    reason="Set XGAP_RUN_LIVE_LLM=1 and DASHSCOPE_API_KEY for the live Qwen smoke test.",
)
def test_dashscope_qwen_live_one_question_smoke(tmp_path: Path) -> None:
    result = run_experiment(
        "experiments/configs/financial_risk_qwen_live_dev.json",
        output_root_override=tmp_path,
        run_id_override="m12b-live-qwen-smoke",
    )

    assert result.attempted_question_count == 1
    assert result.successful_question_count == 1
    assert (result.run_root / "raw_model_responses.jsonl").stat().st_size > 0
    assert (result.run_root / "grounding.jsonl").stat().st_size > 0
