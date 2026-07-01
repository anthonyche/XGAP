from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

import pytest

from xgap.algebra.conditions import EdgeRef, LabelEquals, PropertyEquals
from xgap.algebra.evaluator import evaluate_binding_relation, evaluate_pathset
from xgap.algebra.bindings import (
    BindingField,
    BindingKind,
    BindingRelation,
    BindingRow,
    BindingSchema,
)
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import (
    AntiSemiJoinOp,
    BindEdgeOp,
    BindNodeOp,
    BindingJoinOp,
    BindingProjectOp,
    EdgesOp,
    FocusProjectionOp,
    NodesOp,
    QuantifiedCheckOp,
    SelectionOp,
)
from xgap.algebra.types import Path
from xgap.algebra.validation import ValidationError, infer_binding_schema, validate_plan


class FakeKind(Enum):
    EXISTS = "EXISTS"
    COUNT = "COUNT"
    RATIO = "RATIO"
    NONE = "NONE"


class FakeComparator(Enum):
    EQ = "EQ"
    GE = "GE"


@dataclass(frozen=True)
class FakeQuantifier:
    kind: FakeKind
    comparator: FakeComparator | None = None
    threshold: int | Fraction | None = None


def node_edge_schema() -> BindingSchema:
    return BindingSchema.from_pairs(
        (
            ("x", BindingKind.NODE),
            ("e", BindingKind.EDGE),
            ("y", BindingKind.NODE),
        )
    )


def build_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Account")
    graph.add_node("n2", label="Account")
    graph.add_node("n3", label="Account")
    graph.add_edge("e1", "n1", "n2", label="Transfer", properties={"amount": 100})
    graph.add_edge("e2", "n1", "n3", label="Transfer", properties={"amount": 200})
    graph.add_edge("e3", "n2", "n3", label="Knows")
    graph.add_edge("d1", "n1", "n2", label="Domain")
    return graph


def test_binding_schema_rejects_invalid_fields_and_duplicates() -> None:
    with pytest.raises(ValueError):
        BindingField("", BindingKind.NODE)
    with pytest.raises(TypeError):
        BindingField("x", "NODE")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        BindingSchema.from_pairs((("x", BindingKind.NODE), ("x", BindingKind.NODE)))


def test_binding_schema_project_and_merge() -> None:
    left = BindingSchema.from_pairs((("x", BindingKind.NODE), ("e", BindingKind.EDGE)))
    right = BindingSchema.from_pairs((("x", BindingKind.NODE), ("y", BindingKind.NODE)))

    assert left.project(("e", "x")).names() == ("e", "x")
    assert left.merge(right).names() == ("x", "e", "y")

    conflict = BindingSchema.from_pairs((("x", BindingKind.EDGE),))
    with pytest.raises(ValueError):
        left.merge(conflict)


def test_binding_row_creation_projection_compatibility_and_merge() -> None:
    left_schema = BindingSchema.from_pairs((("x", BindingKind.NODE), ("e", BindingKind.EDGE)))
    right_schema = BindingSchema.from_pairs((("x", BindingKind.NODE), ("y", BindingKind.NODE)))
    left = BindingRow.from_mapping(left_schema, {"x": "n1", "e": "e1"})
    right = BindingRow.from_mapping(right_schema, {"x": "n1", "y": "n2"})

    assert left.value("x") == "n1"
    assert left.project(("e",)).as_mapping() == {"e": "e1"}
    assert left.compatible_with(right)
    assert left.merge(right).as_mapping() == {"x": "n1", "e": "e1", "y": "n2"}

    incompatible = BindingRow.from_mapping(right_schema, {"x": "n3", "y": "n2"})
    assert not left.compatible_with(incompatible)
    with pytest.raises(ValueError):
        left.merge(incompatible)


def test_binding_row_rejects_bad_values() -> None:
    schema = node_edge_schema()

    with pytest.raises(KeyError):
        BindingRow.from_mapping(schema, {"x": "n1", "e": "e1"})
    with pytest.raises(TypeError):
        BindingRow(schema, ("n1", "e1", 7))  # type: ignore[list-item]


def test_binding_relation_is_deduplicated_and_deterministically_ordered() -> None:
    schema = node_edge_schema()
    first = BindingRow.from_mapping(schema, {"x": "n2", "e": "e2", "y": "n3"})
    second = BindingRow.from_mapping(schema, {"x": "n1", "e": "e1", "y": "n1"})

    relation = BindingRelation(schema, [first, second, first])

    assert len(relation) == 2
    assert tuple(row.as_mapping() for row in relation) == (
        {"x": "n1", "e": "e1", "y": "n1"},
        {"x": "n2", "e": "e2", "y": "n3"},
    )


def test_binding_relation_rejects_rows_with_different_schema() -> None:
    schema = BindingSchema.from_pairs((("x", BindingKind.NODE),))
    other = BindingSchema.from_pairs((("y", BindingKind.NODE),))
    row = BindingRow.from_mapping(other, {"y": "n1"})

    with pytest.raises(ValueError):
        BindingRelation(schema, [row])


def test_distinct_variables_may_bind_same_graph_object() -> None:
    schema = BindingSchema.from_pairs((("x", BindingKind.NODE), ("y", BindingKind.NODE)))
    relation = BindingRelation.from_mappings(schema, [{"x": "n1", "y": "n1"}])

    assert tuple(row.as_mapping() for row in relation) == ({"x": "n1", "y": "n1"},)


def test_bind_node_and_bind_edge_evaluate_and_infer_schema() -> None:
    graph = build_graph()
    node_plan = BindNodeOp("x", EdgesOp())
    with pytest.raises(ValueError, match="length zero"):
        evaluate_binding_relation(node_plan, graph)

    edge_plan = BindEdgeOp(
        "x",
        "e",
        "y",
        SelectionOp(LabelEquals(EdgeRef(1), "Transfer"), EdgesOp()),
    )
    validate_plan(edge_plan)

    assert infer_binding_schema(edge_plan).names() == ("x", "e", "y")
    assert tuple(row.as_mapping() for row in evaluate_binding_relation(edge_plan, graph)) == (
        {"x": "n1", "e": "e1", "y": "n2"},
        {"x": "n1", "e": "e2", "y": "n3"},
    )


def test_binding_join_project_anti_and_focus_projection() -> None:
    graph = build_graph()
    transfer_edges = BindEdgeOp(
        "x",
        "e",
        "y",
        SelectionOp(LabelEquals(EdgeRef(1), "Transfer"), EdgesOp()),
    )
    all_nodes = BindNodeOp("x", FocusProjectionOp("x", transfer_edges))
    joined = BindingJoinOp(all_nodes, transfer_edges)
    projected = BindingProjectOp(("x", "y"), joined)
    n3_edges = BindingProjectOp(
        ("x", "y"),
        BindEdgeOp(
            "x",
            "e2",
            "y",
            SelectionOp(PropertyEquals(EdgeRef(1), "amount", 200), EdgesOp()),
        ),
    )
    no_n3 = AntiSemiJoinOp(projected, n3_edges, ("x", "y"))

    validate_plan(projected)
    assert tuple(row.as_mapping() for row in evaluate_binding_relation(projected, graph)) == (
        {"x": "n1", "y": "n2"},
        {"x": "n1", "y": "n3"},
    )
    assert tuple(row.as_mapping() for row in evaluate_binding_relation(no_n3, graph)) == (
        {"x": "n1", "y": "n2"},
    )
    assert evaluate_pathset(FocusProjectionOp("x", projected), graph).sorted() == (
        Path.zero_length("n1"),
    )


def test_binding_validation_failures() -> None:
    edge_plan = BindEdgeOp("x", "e", "y", EdgesOp())

    with pytest.raises(ValidationError):
        validate_plan(BindingProjectOp(("missing",), edge_plan))
    with pytest.raises(ValidationError):
        validate_plan(AntiSemiJoinOp(edge_plan, BindingProjectOp(("x",), edge_plan), ("y",)))
    with pytest.raises(ValidationError):
        validate_plan(FocusProjectionOp("e", edge_plan))


def test_quantified_check_count_ratio_and_malformed_domain() -> None:
    graph = build_graph()
    candidates = BindNodeOp("x", NodesOp())
    witnesses = BindingProjectOp(
        ("x", "y"),
        BindEdgeOp("x", "e", "y", SelectionOp(LabelEquals(EdgeRef(1), "Transfer"), EdgesOp())),
    )
    domain = BindingProjectOp(
        ("x", "y"),
        BindEdgeOp("x", "e", "y", SelectionOp(LabelEquals(EdgeRef(1), "Transfer"), EdgesOp())),
    )

    count_plan = QuantifiedCheckOp(
        candidates,
        witnesses,
        FakeQuantifier(FakeKind.COUNT, FakeComparator.GE, 2),
        correlation_vars=("x",),
        child_var="y",
    )
    validate_plan(count_plan)
    assert tuple(row.as_mapping() for row in evaluate_binding_relation(count_plan, graph)) == (
        {"x": "n1"},
    )

    ratio_plan = QuantifiedCheckOp(
        candidates,
        witnesses,
        FakeQuantifier(FakeKind.RATIO, FakeComparator.EQ, Fraction(1, 1)),
        correlation_vars=("x",),
        child_var="y",
        domain=domain,
    )
    validate_plan(ratio_plan)
    assert tuple(row.as_mapping() for row in evaluate_binding_relation(ratio_plan, graph)) == (
        {"x": "n1"},
    )

    malformed = QuantifiedCheckOp(
        candidates,
        witnesses,
        FakeQuantifier(FakeKind.RATIO, FakeComparator.GE, Fraction(1, 2)),
        correlation_vars=("x",),
        child_var="y",
        domain=BindingProjectOp(
            ("x", "y"),
            BindEdgeOp("x", "d", "y", SelectionOp(LabelEquals(EdgeRef(1), "Domain"), EdgesOp())),
        ),
    )
    validate_plan(malformed)
    with pytest.raises(ValueError, match="subset"):
        evaluate_binding_relation(malformed, graph)


def test_quantified_check_validation_failures() -> None:
    candidates = BindNodeOp("x", NodesOp())
    witnesses = BindingProjectOp(
        ("x", "y"),
        BindEdgeOp("x", "e", "y", SelectionOp(LabelEquals(EdgeRef(1), "Transfer"), EdgesOp())),
    )
    domain = witnesses

    with pytest.raises(ValidationError, match="requires a domain"):
        validate_plan(
            QuantifiedCheckOp(
                candidates,
                witnesses,
                FakeQuantifier(FakeKind.RATIO, FakeComparator.GE, Fraction(1, 2)),
                correlation_vars=("x",),
                child_var="y",
            )
        )
    with pytest.raises(ValidationError, match="must not have a domain"):
        validate_plan(
            QuantifiedCheckOp(
                candidates,
                witnesses,
                FakeQuantifier(FakeKind.EXISTS),
                correlation_vars=("x",),
                child_var="y",
                domain=domain,
            )
        )
    with pytest.raises(ValidationError, match="does not accept NONE"):
        validate_plan(
            QuantifiedCheckOp(
                candidates,
                witnesses,
                FakeQuantifier(FakeKind.NONE),
                correlation_vars=("x",),
                child_var="y",
            )
        )
