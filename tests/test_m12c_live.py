import os
from pathlib import Path

import pytest

from xgap.experiments.calibrate import run_calibration


ROOT = Path(__file__).resolve().parents[1]
LIVE_ENABLED = (
    os.environ.get("XGAP_RUN_BACKENDS") == "1"
    and os.environ.get("XGAP_RUN_CALIBRATION") == "1"
)


@pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="Set XGAP_RUN_BACKENDS=1 and XGAP_RUN_CALIBRATION=1 for live calibration.",
)
def test_real_backend_calibration_smoke(tmp_path: Path) -> None:
    result = run_calibration(
        ROOT / "experiments" / "configs" / "financial_risk_gp_calibration_dev.json",
        output_root_override=tmp_path,
    )

    assert result.status == "ok"
    assert all(result.d0_records[backend_id] for backend_id in ("neo4j", "fuseki"))
    assert result.measurement_source == "real_backend"
