from __future__ import annotations

import sys
from pathlib import Path as FilePath

ROOT = FilePath(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.algebra.conditions import EdgeRef, LabelEquals
from xgap.algebra.evaluator import evaluate_pathset
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import (
    EdgesOp,
    GroupKey,
    GroupByOp,
    OrderKey,
    OrderByOp,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
)
from xgap.algebra.pretty import format_plan
from xgap.algebra.types import Path
from xgap.algebra.validation import validate_plan


def build_knows_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Moe"})
    graph.add_node("n2", label="Person", properties={"name": "Bart"})
    graph.add_node("n3", label="Person", properties={"name": "Lisa"})
    graph.add_node("n4", label="Person", properties={"name": "Apu"})
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n2", "n3", label="Knows")
    graph.add_edge("e3", "n3", "n2", label="Knows")
    graph.add_edge("e4", "n2", "n4", label="Knows")
    return graph


def knows_edges() -> SelectionOp:
    return SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp())


def any_shortest_trail_plan() -> ProjectionOp:
    return ProjectionOp(
        OrderByOp(
            GroupByOp(
                RecursiveOp(knows_edges(), RecursiveMode.TRAIL),
                GroupKey.SOURCE_TARGET,
            ),
            OrderKey.PATH,
        ),
        num_partitions=None,
        num_groups=None,
        num_paths=1,
    )


def all_shortest_acyclic_plan() -> ProjectionOp:
    return ProjectionOp(
        OrderByOp(
            GroupByOp(
                RecursiveOp(knows_edges(), RecursiveMode.ACYCLIC),
                GroupKey.SOURCE_TARGET_LENGTH,
            ),
            OrderKey.GROUP,
        ),
        num_partitions=None,
        num_groups=1,
        num_paths=None,
    )


def format_path(path: Path) -> str:
    parts = [path.node(1)]
    for index in range(1, len(path) + 1):
        parts.append(f"-[{path.edge(index)}]->")
        parts.append(path.node(index + 1))
    return " ".join(parts)


def print_plan_result(title: str, plan: ProjectionOp, graph: PropertyGraph) -> None:
    print(title)
    print(format_plan(plan))
    validate_plan(plan)
    paths = evaluate_pathset(plan, graph).sorted()
    print(f"Validation: ok; output paths: {len(paths)}")
    for path in paths:
        print(f"  {format_path(path)}")


def main() -> None:
    graph = build_knows_graph()
    print_plan_result("ANY SHORTEST TRAIL", any_shortest_trail_plan(), graph)
    print_plan_result("ALL SHORTEST ACYCLIC", all_shortest_acyclic_plan(), graph)


if __name__ == "__main__":
    main()
