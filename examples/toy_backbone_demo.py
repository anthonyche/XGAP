"""No model or catalog: inspect the tiny gold-to-plan-to-reference chain."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xgap.experiments.toy_backbone import check_reference, load_fixture, property_graph
from xgap.experiments.toy_orientation import logical_expectations

data, cases, _ = load_fixture()
graph = property_graph(data)
logical = logical_expectations()  # Explicit v1 orientation expectation; original T0 stays frozen.
for case in cases:
    row = check_reference(case, graph, expected_logical_plan=logical.get(case["id"]))
    if "gap" in row:
        print(case["id"], "GAP:", row["gap"])
    else:
        assert row["reference_passed"] and row["logical_plan_passed"], row
        print(case["id"], len(row["actual_paths"]), "correct complete paths")
print("Tiny logical/reference checks only; the full system and real Interpretation remain incomplete.")
