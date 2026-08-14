"""Run the M12-C pipeline with explicit deterministic fake measurements."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.experiments.calibrate import run_calibration


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="xgap-m12c-demo-") as directory:
        result = run_calibration(
            ROOT / "experiments" / "configs" / "financial_risk_gp_calibration_dev.json",
            output_root_override=directory,
            offline=True,
        )
        print(f"M12-C offline calibration: {result.status}")
        print(f"Measurement source: {result.measurement_source}")
        for backend_id in sorted(result.backend_statuses):
            print(
                f"{backend_id}: {result.backend_statuses[backend_id]}, "
                f"D0={len(result.d0_records[backend_id])}"
            )


if __name__ == "__main__":
    main()
