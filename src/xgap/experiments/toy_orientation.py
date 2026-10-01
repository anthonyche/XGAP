"""Versioned tiny orientation fixtures; no production compiler reads this gold."""

import json
from pathlib import Path


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_orientation_v1"


def load_orientation_cases():
    return json.loads((FIXTURE / "queries.json").read_text())


def logical_expectations():
    return json.loads((FIXTURE / "legacy_logical_plans.json").read_text())
