from __future__ import annotations

import sys
from pathlib import Path as FilePath

ROOT = FilePath(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.algebra import (
    EdgeRef,
    EdgesOp,
    JoinOp,
    LabelEquals,
    NodeRef,
    PropertyEquals,
    PropertyGraph,
    SelectionOp,
    UnionOp,
    evaluate,
)
from xgap.algebra.pretty import format_plan
from xgap.algebra.types import Path
from xgap.algebra.validation import validate_plan


def build_sample_graph() -> PropertyGraph:
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


def build_plan() -> SelectionOp:
    knows_edges = SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp())
    two_hop_knows = JoinOp(knows_edges, knows_edges)
    return SelectionOp(
        PropertyEquals(NodeRef.first(), "name", "Moe"),
        UnionOp(knows_edges, two_hop_knows),
    )


def format_path(path: Path) -> str:
    parts = [path.node(1)]
    for index in range(1, len(path) + 1):
        parts.append(f"-[{path.edge(index)}]->")
        parts.append(path.node(index + 1))
    return " ".join(parts)


def main() -> None:
    graph = build_sample_graph()
    plan = build_plan()

    print("Plan:")
    print(format_plan(plan))
    validate_plan(plan)
    print("Validation: ok")
    print("Result paths:")
    for path in evaluate(plan, graph):
        print(format_path(path))


if __name__ == "__main__":
    main()
