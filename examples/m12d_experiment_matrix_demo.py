"""Run the complete small M12-D development matrix with explicit fake execution."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.experiments.aggregate import aggregate_runs
from xgap.experiments.matrix import run_matrix


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="xgap-m12d-demo-") as directory:
        result = run_matrix(
            ROOT / "experiments/matrices/financial_risk_pilot.json",
            execute=True,
            offline=True,
            output_root_override=Path(directory),
        )
        if result.failed or len(result.executed) != 12:
            raise RuntimeError("M12-D development matrix did not complete.")
        aggregate = aggregate_runs(
            [item.run_root for item in result.executed],
            output_prefix=Path(directory) / "aggregate",
        )
        print("M12-D offline development matrix completed.")
        print(f"Runs: {len(result.executed)}")
        print(f"Aggregate groups: {aggregate.group_count}")
        print("Candidate generation was frozen and replayed across methods.")


if __name__ == "__main__":
    main()
