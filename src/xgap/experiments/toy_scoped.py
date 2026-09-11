"""Complete independently specified nested-path cases through semantic Traverse."""

import json
from pathlib import Path

from xgap.experiments.toy_semantic import execute_semantic_case, wrap_path_case


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_scoped_v1"


def load_scoped_cases():
    return json.loads((FIXTURE / "queries.json").read_text())


def execute_scoped_case(case, mapping, *, client):
    wrapper = wrap_path_case(case, client.backend_id)
    wrapper["expected_remote_calls"] = case["expected_remote_calls"]
    result = execute_semantic_case(wrapper, mapping, clients={client.backend_id: client})
    return {**result, "backend": client.backend_id, "expected_paths": case["expected_paths"],
        "actual_paths": sorted("/".join(row["path"]) for row in result["actual_rows"])
        if result["actual_rows"] is not None else None}
