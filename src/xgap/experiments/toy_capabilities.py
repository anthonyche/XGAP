"""Explicit requirements over frozen complete toy semantic chains."""

import json
from pathlib import Path

from xgap.experiments.toy_semantic import load_semantic_cases
from xgap.experiments.toy_planning import execute_planned_semantic_case


FIXTURE = Path(__file__).resolve().parents[3] / "datasets/backbone_capabilities_v1"


def load_capability_cases():
    base = {case["id"]: case for case in load_semantic_cases()}
    cases = []
    for overlay in json.loads((FIXTURE / "cases.json").read_text()):
        case = json.loads(json.dumps(base[overlay["base_case"]]))
        case.update(id=overlay["id"], base_case=overlay["base_case"],
                    expected_placements=overlay["expected_placements"])
        case["program"]["program_id"] = "capabilities-" + case["id"]
        for op in case["program"]["operators"]:
            op["required_capabilities"] = overlay["requirements"].get(op["operator_id"], [])
        cases.append(case)
    return cases


def execute_capability_case(case, mapping, *, clients):
    record = execute_planned_semantic_case(case, mapping, clients=clients)
    actual = [check["source_bindings"] for check in record["candidate_checks"]]
    canonical = lambda items: sorted(json.dumps(item, sort_keys=True) for item in items)
    record["expected_placements"] = case["expected_placements"]
    record["placements_match"] = canonical(actual) == canonical(case["expected_placements"])
    record["success"] = record["success"] and record["placements_match"]
    return record
