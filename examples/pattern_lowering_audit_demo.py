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
    EdgePattern,
    NodePattern,
    PathMode,
    PathPatternQuery,
    Plus,
    Rel,
    Selector,
    SelectorKind,
    Star,
    Var,
    lower_path_pattern,
)


def build_knows_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Alice"})
    graph.add_node("n2", label="Person", properties={"name": "Bob"})
    graph.add_node("n3", label="Person", properties={"name": "Carol"})
    graph.add_node("n4", label="Person", properties={"name": "Dana"})
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n2", "n3", label="Knows")
    graph.add_edge("e3", "n3", "n2", label="Knows")
    graph.add_edge("e4", "n2", "n4", label="Knows")
    return graph


def any_shortest_trail_query() -> PathPatternQuery:
    return PathPatternQuery(
        path_var=Var("p"),
        source=NodePattern(var=Var("x")),
        expr=Plus(Rel(EdgePattern(label="Knows"))),
        target=NodePattern(var=Var("y")),
        selector=Selector(SelectorKind.ANY_SHORTEST),
        restrictor=PathMode.TRAIL,
    )


def all_shortest_acyclic_query() -> PathPatternQuery:
    return PathPatternQuery(
        path_var=Var("p"),
        source=NodePattern(var=Var("x")),
        expr=Plus(Rel(EdgePattern(label="Knows"))),
        target=NodePattern(var=Var("y")),
        selector=Selector(SelectorKind.ALL_SHORTEST),
        restrictor=PathMode.ACYCLIC,
    )


def star_query() -> PathPatternQuery:
    return PathPatternQuery(
        path_var=Var("p"),
        source=NodePattern(var=Var("x")),
        expr=Star(Rel(EdgePattern(label="Knows"))),
        target=NodePattern(var=Var("y")),
        selector=Selector(SelectorKind.ALL),
        restrictor=PathMode.TRAIL,
    )


def print_audit_case(title: str, query: PathPatternQuery, graph: PropertyGraph) -> None:
    first_plan = lower_path_pattern(query)
    second_plan = lower_path_pattern(query)
    assert format_plan(first_plan) == format_plan(second_plan)
    validate_plan(first_plan)
    paths = evaluate_pathset(first_plan, graph).sorted()

    print(title)
    print(format_plan(first_plan))
    print(f"Validation: ok; output paths: {len(paths)}")


def main() -> None:
    graph = build_knows_graph()

    any_shortest = lower_path_pattern(any_shortest_trail_query())
    any_shortest_paths = evaluate_pathset(any_shortest, graph)
    assert Path.one_length("n1", "e1", "n2") in any_shortest_paths
    assert Path(("n1", "e1", "n2", "e2", "n3")) in any_shortest_paths

    all_shortest = lower_path_pattern(all_shortest_acyclic_query())
    all_shortest_paths = evaluate_pathset(all_shortest, graph)
    assert Path.one_length("n1", "e1", "n2") in all_shortest_paths
    assert Path(("n1", "e1", "n2", "e2", "n3")) in all_shortest_paths

    star = lower_path_pattern(star_query())
    assert Path.zero_length("n1") in evaluate_pathset(star, graph)

    print_audit_case("ANY SHORTEST TRAIL", any_shortest_trail_query(), graph)
    print_audit_case("ALL SHORTEST ACYCLIC", all_shortest_acyclic_query(), graph)
    print_audit_case("ALL TRAIL STAR", star_query(), graph)
    print("M5.5 pattern-lowering audit demo: ok")


if __name__ == "__main__":
    main()
