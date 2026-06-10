import pytest

from xgap.algebra.graph import PropertyGraph
from xgap.algebra.types import Path


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


def test_add_nodes_and_edges_retrieve_labels_and_properties() -> None:
    graph = build_sample_graph()

    assert graph.node_label("n1") == "Person"
    assert graph.node_property("n1", "name") == "Moe"
    assert graph.edge_label("e1") == "Knows"
    assert graph.edge_source("e1") == "n1"
    assert graph.edge_target("e1") == "n2"


def test_reject_duplicate_nodes_edges_and_missing_endpoints() -> None:
    graph = PropertyGraph()
    graph.add_node("n1")
    graph.add_node("n2")
    graph.add_edge("e1", "n1", "n2")

    with pytest.raises(ValueError):
        graph.add_node("n1")
    with pytest.raises(ValueError):
        graph.add_edge("e1", "n1", "n2")
    with pytest.raises(KeyError):
        graph.add_edge("e2", "missing", "n2")
    with pytest.raises(KeyError):
        graph.add_edge("e3", "n1", "missing")


def test_outgoing_and_incoming_adjacency() -> None:
    graph = build_sample_graph()

    assert graph.outgoing_edges("n2") == ("e2", "e4")
    assert graph.incoming_edges("n2") == ("e1", "e3")


def test_nodes_as_paths_returns_zero_length_paths() -> None:
    graph = build_sample_graph()

    assert graph.nodes_as_paths().sorted() == (
        Path.zero_length("n1"),
        Path.zero_length("n2"),
        Path.zero_length("n3"),
        Path.zero_length("n4"),
    )


def test_edges_as_paths_returns_one_length_paths() -> None:
    graph = build_sample_graph()

    assert graph.edges_as_paths().sorted() == (
        Path.one_length("n1", "e1", "n2"),
        Path.one_length("n2", "e2", "n3"),
        Path.one_length("n2", "e4", "n4"),
        Path.one_length("n3", "e3", "n2"),
    )
