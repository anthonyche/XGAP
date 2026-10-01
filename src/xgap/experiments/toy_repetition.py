"""Load independently authored optional/repetition development queries."""

import json
from pathlib import Path


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_repetition_v1"


def load_repetition_cases():
    return json.loads((FIXTURE / "queries.json").read_text())
