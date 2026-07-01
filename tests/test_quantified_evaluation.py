from xgap.algebra.evaluator import evaluate_pathset
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.types import Path
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
    count_eq,
    count_ge,
    none,
    ratio_eq,
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
    graph.add_edge("r1", "h2", "n1", label="Reviews", properties={"score": 0.9})
    return graph


def node(name: str, label: str | None = None) -> FocusedNodePattern:
    return FocusedNodePattern(Var(name), label)


def edge(
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
            FocusedEdgePattern(None, label, tuple(edge_predicates)),
            Direction.OUT,
            quantifier,
        ),
    )


def query(child_node: FocusedNodePattern, *edges: QuantifiedPatternEdge) -> FocusedQuantifiedPatternQuery:
    node_names = {"x": node("x", "Account"), child_node.var.name: child_node}
    for pattern_edge in edges:
        node_names.setdefault(pattern_edge.parent_var.name, node(pattern_edge.parent_var.name))
        node_names.setdefault(pattern_edge.child_var.name, node(pattern_edge.child_var.name))
    return FocusedQuantifiedPatternQuery(Var("x"), tuple(node_names.values()), tuple(edges))


def result_nodes(pattern: FocusedQuantifiedPatternQuery) -> tuple[str, ...]:
    result = evaluate_pathset(lower_focused_quantified_pattern(pattern), build_graph())
    return tuple(path.first() for path in result.sorted())


def test_count_ge_counts_distinct_child_nodes_not_parallel_edges() -> None:
    child, branch = edge("x", "y", "Transfer", count_ge(2), child_label="HighRisk")

    assert result_nodes(query(child, branch)) == ("a1", "a2", "a4")


def test_count_eq_and_local_numeric_edge_predicate() -> None:
    child, branch = edge(
        "x",
        "y",
        "Transfer",
        count_eq(3),
        child_label=None,
        edge_predicates=(PropertyPredicate("amount", ScalarComparator.GE, 250),),
    )

    assert result_nodes(query(child, branch)) == ("a1",)


def test_ratio_ge_and_ratio_eq_use_exact_non_vacuous_semantics() -> None:
    child, branch_ge = edge("x", "y", "Transfer", ratio_ge("4/5"), child_label="HighRisk")
    assert result_nodes(query(child, branch_ge)) == ("a2", "a4")

    child, branch_eq = edge("x", "y", "Transfer", ratio_eq("4/5"), child_label="HighRisk")
    assert result_nodes(query(child, branch_eq)) == ("a2",)


def test_all_matches_requires_non_empty_domain() -> None:
    child, branch = edge("x", "y", "Transfer", all_matches(), child_label="HighRisk")

    assert result_nodes(query(child, branch)) == ("a4",)


def test_none_uses_complete_pattern_level_negation() -> None:
    child, branch = edge("x", "y", "Transfer", none(), child_label="Blocked")

    assert result_nodes(query(child, branch)) == ("a2", "a3", "a4", "a5")


def test_nested_subtree_must_pass_before_child_is_counted() -> None:
    review_child, review_branch = edge(
        "y",
        "z",
        "Reviews",
        count_ge(1),
        child_label="Normal",
        edge_predicates=(PropertyPredicate("score", ScalarComparator.GE, 0.8),),
    )
    high_risk = node("y", "HighRisk")
    transfer_branch = QuantifiedPatternEdge(
        Var("x"),
        Var("y"),
        FocusedEdgePattern(label="Transfer"),
        Direction.OUT,
        count_eq(1),
    )
    pattern = FocusedQuantifiedPatternQuery(
        Var("x"),
        (node("x", "Account"), high_risk, review_child),
        (transfer_branch, review_branch),
    )

    assert result_nodes(pattern) == ("a1", "a2", "a4")


def test_sibling_branches_are_conjunctive() -> None:
    high_risk, count_branch = edge("x", "y", "Transfer", count_ge(2), child_label="HighRisk")
    blocked, none_branch = edge("x", "b", "Transfer", none(), child_label="Blocked")
    pattern = FocusedQuantifiedPatternQuery(
        Var("x"),
        (node("x", "Account"), high_risk, blocked),
        (count_branch, none_branch),
    )

    assert result_nodes(pattern) == ("a2", "a4")


def test_focus_only_query_returns_matching_focus_nodes() -> None:
    pattern = FocusedQuantifiedPatternQuery(Var("x"), (node("x", "Account"),), ())

    assert result_nodes(pattern) == ("a1", "a2", "a3", "a4", "a5")


def test_result_is_zero_length_paths() -> None:
    pattern = FocusedQuantifiedPatternQuery(Var("x"), (node("x", "Account"),), ())
    result = evaluate_pathset(lower_focused_quantified_pattern(pattern), build_graph())

    assert all(path == Path.zero_length(path.first()) for path in result)
