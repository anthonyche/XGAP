from __future__ import annotations

import sys
from pathlib import Path as FilePath

ROOT = FilePath(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.algebra import EdgesOp, PropertyGraph, evaluate
from xgap.algebra.ops import RecursiveMode, RecursiveOp
from xgap.algebra.types import Path


def build_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Node")
    graph.add_node("n2", label="Node")
    graph.add_node("n3", label="Node")
    graph.add_edge("e1", "n1", "n2", label="Link")
    graph.add_edge("e2", "n2", "n1", label="Link")
    graph.add_edge("e3", "n2", "n3", label="Link")
    return graph


def format_path(path: Path) -> str:
    parts = [path.node(1)]
    for index in range(1, len(path) + 1):
        parts.append(f"-[{path.edge(index)}]->")
        parts.append(path.node(index + 1))
    return " ".join(parts)


def print_sample(title: str, plan: RecursiveOp, graph: PropertyGraph) -> None:
    paths = evaluate(plan, graph).sorted()
    print(f"{title}: {len(paths)} path(s)")
    for path in paths[:5]:
        print(f"  {format_path(path)}")


def main() -> None:
    graph = build_graph()
    print_sample("WALK max_depth=3", RecursiveOp(EdgesOp(), RecursiveMode.WALK, max_depth=3), graph)
    print_sample("TRAIL", RecursiveOp(EdgesOp(), RecursiveMode.TRAIL), graph)
    print_sample("ACYCLIC", RecursiveOp(EdgesOp(), RecursiveMode.ACYCLIC), graph)
    print_sample("SIMPLE", RecursiveOp(EdgesOp(), RecursiveMode.SIMPLE), graph)
    print_sample("SHORTEST", RecursiveOp(EdgesOp(), RecursiveMode.SHORTEST), graph)


if __name__ == "__main__":
    main()
