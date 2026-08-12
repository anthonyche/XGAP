"""Run the controlled M11 planner without a live LLM or backend."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.experiments.physical_planner import run_physical_planner


def main() -> None:
    artifacts = run_physical_planner(
        ROOT / "examples" / "configs" / "m11_controlled_planner.json"
    )
    print("M11 controlled planner:")
    print(f"status={artifacts.result.status}")
    print(f"selected={len(artifacts.result.selected_plans)}")
    for rank, selected in enumerate(artifacts.result.selected_plans, 1):
        print(
            f"{rank}. {selected.candidate_id} "
            f"nash={selected.objective.nash_score:.6f} "
            f"upper={selected.physical_plan.cost.upper:.6f}"
        )
    print(f"artifacts={artifacts.run_root}")


if __name__ == "__main__":
    main()
