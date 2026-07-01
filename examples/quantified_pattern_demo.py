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
from xgap.algebra.validation import validate_plan
from xgap.pattern import (
    Direction,
    FocusedEdgePattern,
    FocusedNodePattern,
    FocusedQuantifiedPatternQuery,
    PropertyPredicate,
    QuantifiedPatternEdge,
    ScalarComparator,
    Var,
    all_matches,
    count_ge,
    none,
    ratio_ge,
)
from xgap.pattern.quantified_lowering import lower_focused_quantified_pattern


def build_graph() -> PropertyGraph:
    graph = PropertyGraph()
    for node_id, label in (
        ("a1", "Account"),
        ("a2", "Account"),
        ("a3", "Account"),
        ("a4", "Account"),
        ("a5", "Account"),
        ("h1", "HighRisk"),
        ("h2", "HighRisk"),
        ("h3", "HighRisk"),
        ("h4", "HighRisk"),
        ("n1", "Normal"),
        ("blocked", "Blocked"),
    ):
        graph.add_node(node_id, label=label)

    graph.add_edge("e1", "a1", "h1", label="Transfer", properties={"amount": 100})
    graph.add_edge("e2", "a1", "h1", label="Transfer", properties={"amount": 200})
    graph.add_edge("e3", "a1", "h2", label="Transfer", properties={"amount": 300})
    graph.add_edge("e4", "a1", "n1", label="Transfer", properties={"amount": 400})
    graph.add_edge("e5", "a1", "blocked", label="Transfer", properties={"amount": 500})
    graph.add_edge("e6", "a2", "h1", label="Transfer", properties={"amount": 100})
    graph.add_edge("e7", "a2", "h2", label="Transfer", properties={"amount": 100})
    graph.add_edge("e8", "a2", "h3", label="Transfer", properties={"amount": 100})
    graph.add_edge("e9", "a2", "h4", label="Transfer", properties={"amount": 100})
    graph.add_edge("e10", "a2", "n1", label="Transfer", properties={"amount": 100})
    graph.add_edge("e11", "a3", "n1", label="Transfer", properties={"amount": 100})
    graph.add_edge("e12", "a4", "h1", label="Transfer", properties={"amount": 100})
    graph.add_edge("e13", "a4", "h2", label="Transfer", properties={"amount": 100})
    return graph


def node(name: str, label: str | None = None) -> FocusedNodePattern:
    return FocusedNodePattern(Var(name), label)


def branch(
    parent: str,
    child: str,
    label: str,
    quantifier,
    *,
    child_label: str | None = None,
    edge_predicates=(),
) -> tuple[FocusedNodePattern, QuantifiedPatternEdge]:
    return (
        node(child, child_label),
        QuantifiedPatternEdge(
            Var(parent),
            Var(child),
            FocusedEdgePattern(
                None,
                label,
                tuple(edge_predicates),
            ),
            Direction.OUT,
            quantifier,
        ),
    )


def query(
    child_node: FocusedNodePattern,
    *edges: QuantifiedPatternEdge,
) -> FocusedQuantifiedPatternQuery:
    nodes = {"x": node("x", "Account"), child_node.var.name: child_node}
    for edge in edges:
        nodes.setdefault(edge.parent_var.name, node(edge.parent_var.name))
        nodes.setdefault(edge.child_var.name, node(edge.child_var.name))
    return FocusedQuantifiedPatternQuery(Var("x"), tuple(nodes.values()), tuple(edges))


def result_nodes(
    pattern: FocusedQuantifiedPatternQuery,
    graph: PropertyGraph,
) -> tuple[str, ...]:
    plan = lower_focused_quantified_pattern(pattern)
    validate_plan(plan)
    result = evaluate_pathset(plan, graph)
    assert all(len(path) == 0 for path in result)
    return tuple(path.first() for path in result.sorted())


def print_case(
    title: str,
    pattern: FocusedQuantifiedPatternQuery,
    graph: PropertyGraph,
) -> None:
    first_plan = lower_focused_quantified_pattern(pattern)
    second_plan = lower_focused_quantified_pattern(pattern)
    assert format_plan(first_plan) == format_plan(second_plan)
    validate_plan(first_plan)
    answers = result_nodes(pattern, graph)

    print(title)
    print(format_plan(first_plan))
    print(f"Answers: {', '.join(answers) if answers else '(none)'}")


def main() -> None:
    graph = build_graph()

    high_risk, count_branch = branch(
        "x",
        "y",
        "Transfer",
        count_ge(2),
        child_label="HighRisk",
    )
    count_query = query(high_risk, count_branch)
    assert result_nodes(count_query, graph) == ("a1", "a2", "a4")

    high_risk_ratio, ratio_branch = branch(
        "x",
        "y",
        "Transfer",
        ratio_ge("4/5"),
        child_label="HighRisk",
    )
    ratio_query = query(high_risk_ratio, ratio_branch)
    assert result_nodes(ratio_query, graph) == ("a2", "a4")

    high_risk_all, all_branch = branch(
        "x",
        "y",
        "Transfer",
        all_matches(),
        child_label="HighRisk",
    )
    all_query = query(high_risk_all, all_branch)
    assert result_nodes(all_query, graph) == ("a4",)

    blocked, none_branch = branch(
        "x",
        "b",
        "Transfer",
        none(),
        child_label="Blocked",
    )
    none_query = query(blocked, none_branch)
    assert result_nodes(none_query, graph) == ("a2", "a3", "a4", "a5")

    expensive_target, expensive_branch = branch(
        "x",
        "z",
        "Transfer",
        count_ge(2),
        edge_predicates=(PropertyPredicate("amount", ScalarComparator.GE, 250),),
    )
    expensive_query = query(expensive_target, expensive_branch)
    assert result_nodes(expensive_query, graph) == ("a1",)

    print_case("COUNT >= 2 distinct high-risk transfer targets", count_query, graph)
    print_case("RATIO >= 4/5 high-risk transfer targets", ratio_query, graph)
    print_case("ALL transfer targets are high-risk, non-vacuously", all_query, graph)
    print_case("NONE blocked transfer target", none_query, graph)
    print_case("COUNT >= 2 transfer targets with amount >= 250", expensive_query, graph)
    print("M6 quantified-pattern demo: ok")


if __name__ == "__main__":
    main()
