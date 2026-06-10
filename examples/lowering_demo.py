from __future__ import annotations

import sys
from pathlib import Path as FilePath

ROOT = FilePath(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xgap.algebra.evaluator import evaluate_pathset
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.pretty import format_plan
from xgap.algebra.types import Path
from xgap.algebra.validation import validate_plan
from xgap.pattern import (
    Direction,
    EdgePattern,
    NodePattern,
    PathMode,
    PathPatternQuery,
    Plus,
    Rel,
    Selector,
    SelectorKind,
    Var,
    lower_path_pattern,
)


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


def build_query() -> PathPatternQuery:
    return PathPatternQuery(
        path_var=Var("p"),
        source=NodePattern(var=Var("x")),
        expr=Plus(Rel(EdgePattern(label="Knows", direction=Direction.OUT))),
        target=NodePattern(var=Var("y")),
        selector=Selector(SelectorKind.ANY_SHORTEST),
        restrictor=PathMode.TRAIL,
    )


def format_path(path: Path) -> str:
    parts = [path.node(1)]
    for index in range(1, len(path) + 1):
        parts.append(f"-[{path.edge(index)}]->")
        parts.append(path.node(index + 1))
    return " ".join(parts)


def main() -> None:
    graph = build_knows_graph()
    plan = lower_path_pattern(build_query())

    print("Lowered plan:")
    print(format_plan(plan))
    validate_plan(plan)
    print("Validation: ok")
    print("Output paths:")
    for path in evaluate_pathset(plan, graph):
        print(format_path(path))


if __name__ == "__main__":
    main()
