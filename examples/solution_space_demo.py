from __future__ import annotations

import sys
from pathlib import Path as FilePath

ROOT = FilePath(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.algebra import EdgeRef, EdgesOp, LabelEquals, PropertyGraph, SelectionOp
from xgap.algebra.evaluator import evaluate_pathset
from xgap.algebra.ops import (
    GroupKey,
    GroupByOp,
    OrderKey,
    OrderByOp,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
)
from xgap.algebra.pretty import format_plan
from xgap.algebra.types import Path
from xgap.algebra.validation import validate_plan


def build_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Moe"})
    graph.add_node("n2", label="Person", properties={"name": "Bart"})
    graph.add_node("n3", label="Person", properties={"name": "Lisa"})
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n1", "n3", label="Knows")
    graph.add_edge("e3", "n2", "n3", label="Knows")
    graph.add_edge("e4", "n1", "n3", label="Knows")
    return graph


def build_plan() -> ProjectionOp:
    knows_edges = SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp())
    return ProjectionOp(
        OrderByOp(
            GroupByOp(
                RecursiveOp(knows_edges, RecursiveMode.TRAIL, max_depth=2),
                GroupKey.SOURCE_TARGET,
            ),
            OrderKey.PATH,
        ),
        num_partitions=None,
        num_groups=None,
        num_paths=1,
    )


def format_path(path: Path) -> str:
    parts = [path.node(1)]
    for index in range(1, len(path) + 1):
        parts.append(f"-[{path.edge(index)}]->")
        parts.append(path.node(index + 1))
    return " ".join(parts)


def main() -> None:
    graph = build_graph()
    plan = build_plan()

    print("Plan:")
    print(format_plan(plan))
    validate_plan(plan)
    print("Validation: ok")
    print("Output paths:")
    for path in evaluate_pathset(plan, graph):
        print(format_path(path))


if __name__ == "__main__":
    main()
