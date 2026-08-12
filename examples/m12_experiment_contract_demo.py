"""Run the controlled M12-A experiment contract in a temporary directory."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.experiments.run import run_experiment


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="xgap-m12-") as directory:
        result = run_experiment(
            ROOT / "experiments/configs/financial_risk_xgap_dev.json",
            output_root_override=directory,
            run_id_override="m12-contract-demo",
        )
        print(f"M12-A planned questions: {len(result.question_results)}")
        print(f"M12-A successful questions: {result.successful_question_count}")
        print(f"M12-A artifact files: {len(result.inventory)}")
        print("M12-A backend execution: not_available (outside this phase)")


if __name__ == "__main__":
    main()
