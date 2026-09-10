"""No model or catalog: inspect the tiny gold-to-plan-to-reference chain."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xgap.experiments.toy_backbone import check_reference, load_fixture, property_graph

data, cases, _ = load_fixture()
graph = property_graph(data)
for case in cases:
    row = check_reference(case, graph)
    if "gap" in row:
        print(case["id"], "GAP:", row["gap"])
    else:
        assert row["reference_passed"] and row["logical_plan_passed"], row
        print(case["id"], len(row["actual_paths"]), "correct complete paths")
print("T0 fixture check only; full native backbone and real interpretation are not yet complete.")
