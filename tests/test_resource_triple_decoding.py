"""URI-triple identity across native encodings, independent of native compilers."""

from dataclasses import replace
import json

import pytest

from xgap.compilers.rdf_encoding import RdfResourceTripleEncoding, RdfRowEncoding
from xgap.runtime.path_selection import select_native_paths


NS = "https://example.test/"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
EDGE_AB = 'rdf-triple-v1:["https://example.test/a","https://example.test/p","https://example.test/b"]'


def parameters(language="cypher", directions=None, **changes):
    directions = ["OUT"] if directions is None else directions
    return {"input_model": "rdf-resource-triples-v1", "language": language,
            "max_edges": len(directions), "resource_namespace": NS,
            "identity_property": "type.object.id", "directions": directions,
            "max_rows": 20, "selector": "ALL", **changes}


def row(nodes=("a", "b"), predicates=("p",)):
    return {"length": len(predicates),
            **{f"n{i}": NS + node for i, node in enumerate(nodes)},
            **{f"e{i}": NS + predicate for i, predicate in enumerate(predicates, 1)}}


def rdf_row(native):
    return {key: ({"type": "literal", "value": str(value), "datatype": XSD_INTEGER}
                  if key == "length" else {"type": "uri", "value": value})
            for key, value in native.items()}


def test_encoding_is_snapshot_bound_and_reuses_the_node_contract():
    encoding = RdfResourceTripleEncoding("mirror-v1", "snapshot-a", NS)
    assert encoding.rdf == RdfRowEncoding("mirror-v1",
        "http://rdf.freebase.com/ns/type.object.type", "type.object.id", NS)
    assert encoding.identity == replace(encoding).identity
    assert len(encoding.identity) == 64
    assert encoding.identity != replace(encoding, snapshot_id="snapshot-b").identity
    assert encoding.identity != replace(encoding, max_rows=5).identity
    for changes in ({"encoding_id": " "}, {"snapshot_id": ""}, {"max_rows": True},
                    {"max_rows": 0}, {"identity_property": ""},
                    {"resource_namespace": "relative/"}, {"class_predicate_iri": "bad iri"}):
        with pytest.raises(ValueError):
            replace(encoding, **changes)


def test_reverse_traversal_keeps_the_same_stored_edge_on_both_backends():
    for language in ("cypher", "sparql"):
        encode = rdf_row if language == "sparql" else lambda value: value
        forward = select_native_paths([encode(row())], parameters(language))
        reverse = select_native_paths([encode(row(("b", "a")))],
                                      parameters(language, ["IN"]))
        assert forward == ({"path": ["a", EDGE_AB, "b"]},)
        assert reverse == ({"path": ["b", EDGE_AB, "a"]},)


def test_duplicate_facts_collapse_but_predicates_and_endpoints_distinguish_edges():
    records = [row(), row(), row(predicates=("q",)), row(("a", "c"))]
    native = select_native_paths(records, parameters())
    rdf = select_native_paths([rdf_row(item) for item in records], parameters("sparql"))
    assert native == rdf
    assert len(native) == 3
    assert len({item["path"][1] for item in native}) == 3
    assert {tuple(json.loads(item["path"][1].removeprefix("rdf-triple-v1:")))
            for item in native} == {
                (NS + "a", NS + "p", NS + "b"),
                (NS + "a", NS + "q", NS + "b"),
                (NS + "a", NS + "p", NS + "c"),
            }


def test_mixed_three_hop_cycle_preserves_full_path_and_stored_directions():
    record = row(("a", "b", "c", "a"), ("p", "q", "r"))
    native = select_native_paths([record], parameters(directions=["OUT", "IN", "OUT"]))
    rdf = select_native_paths([rdf_row(record)], parameters("sparql", ["OUT", "IN", "OUT"]))
    assert native == rdf
    path = native[0]["path"]
    assert path[::2] == ["a", "b", "c", "a"]
    assert [json.loads(edge.removeprefix("rdf-triple-v1:")) for edge in path[1::2]] == [
        [NS + "a", NS + "p", NS + "b"],
        [NS + "c", NS + "q", NS + "b"],
        [NS + "c", NS + "r", NS + "a"],
    ]


@pytest.mark.parametrize("changes", [
    {"length": True}, {"length": 0}, {"length": 2}, {"n0": NS + "bad/id"},
    {"n0": "https://elsewhere.test/a"}, {"n1": None}, {"e1": "not-an-iri"},
    {"answer": "unexpected"},
])
def test_malformed_native_rows_do_not_become_successful_paths(changes):
    with pytest.raises(ValueError):
        select_native_paths([{**row(), **changes}], parameters())


def test_missing_columns_literals_and_blank_nodes_are_rejected():
    missing = row()
    del missing["e1"]
    with pytest.raises(ValueError):
        select_native_paths([missing], parameters())
    for key, value in (("n0", {"type": "bnode", "value": "a"}),
                       ("n1", {"type": "literal", "value": NS + "b"}),
                       ("e1", {"type": "literal", "value": NS + "p"}),
                       ("length", {"type": "literal", "value": "1"}),
                       ("length", {"type": "literal", "value": "1.0", "datatype": XSD_INTEGER}),
                       ("length", {"type": "literal", "value": "0_1", "datatype": XSD_INTEGER})):
        with pytest.raises(ValueError):
            select_native_paths([{**rdf_row(row()), key: value}], parameters("sparql"))


def test_overflow_is_checked_before_duplicate_elimination():
    for language in ("cypher", "sparql"):
        record = rdf_row(row()) if language == "sparql" else row()
        with pytest.raises(ValueError, match="row budget"):
            select_native_paths([record, record], parameters(language, max_rows=1))


@pytest.mark.parametrize("changes", [
    {"directions": ["UNDIRECTED"]}, {"directions": []}, {"max_edges": 4},
    {"max_rows": True}, {"max_rows": 0}, {"selector": "ANY_SHORTEST"},
    {"recursive_shortest": True}, {"post_shortest_lengths": [1]},
])
def test_invalid_profiles_are_rejected_even_for_empty_results(changes):
    with pytest.raises(ValueError):
        select_native_paths([], parameters(**changes))


def test_empty_valid_result_is_a_complete_empty_pathset():
    assert select_native_paths([], parameters()) == ()
