"""Preflight or run one bounded ordinary-entry toy question."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from xgap.experiments.one_shot_toy import main

if __name__ == "__main__":
    raise SystemExit(main())
