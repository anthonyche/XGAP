"""Independent finite-repeat chains, with witnesses for selection ordering."""

from dataclasses import replace
import json

import pytest

from xgap.algebra import Path, PathSet, evaluate
from xgap.algebra.conditions import LengthEquals
from xgap.algebra.ops import RecursiveMode
from xgap.backends.fuseki_client import FusekiClient
from xgap.compilers.bounded_paths import compile_bounded_paths
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.experiments.toy_backbone import (DEFAULT_FIXTURE, check_reference,
    execute_bounded_toy_case, load_fixture, property_graph, toy_rdf_edge_encoding)
from xgap.experiments.toy_repetition import FIXTURE, load_repetition_cases
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.parser import parse_path_pattern_query
from xgap.pattern import Bounded, EdgePattern, OptionalExpr, Rel, Seq, lower_regex


DATA, _, MAPPING = load_fixture()
CASES = load_repetition_cases()
OPTIONS = dict(backend_mapping=MAPPING, rdf_edge_encoding=toy_rdf_edge_encoding(MAPPING),
    rdf_node_classes=("https://xgap.test/toy/Person",), resource_namespace="https://xgap.test/toy/")


class RDF(FusekiClient):
    def __init__(self):
        super().__init__(BackendDescriptor("fuseki", "fuseki", "sparql", "rdf"))
        rdf = pytest.importorskip("rdflib", minversion="7.1.4")
        self.graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")
    def _post_query(self, text):
        return json.loads(self.graph.query(text).serialize(format="json"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_complete_repetition_chain_and_independent_rdf(case):
    reference = check_reference(case, property_graph(DATA))
    assert reference["logical_plan_passed"] and reference["reference_passed"], reference
    client = RDF()
    answers = sorted({str(row[0]) for row in client.graph.query(
        (FIXTURE / case["reference_target_queries"]["fuseki"]).read_text())})
    assert answers == case["expected_paths"]
    result = execute_bounded_toy_case(case, MAPPING, client=client)
    assert result["success"], result


@pytest.mark.parametrize("mode", list(RecursiveMode))
def test_exact_two_repetitions_apply_the_mode_to_full_paths(mode):
    child = Rel(EdgePattern(properties={"id": "e6"}))
    result = evaluate(lower_regex(Bounded(child, 2, 2), mode), property_graph(DATA))
    expected = PathSet([Path(("d", "e6", "d", "e6", "d"))]) if mode in (
        RecursiveMode.WALK, RecursiveMode.SHORTEST) else PathSet()
    assert result == expected


def test_nullable_child_shortest_is_applied_before_outer_length_filter():
    from xgap.pattern.lowering import lower_path_pattern
    query = replace(parse_path_pattern_query(CASES[8]["gold_path_pattern_query"]), condition=LengthEquals(1))
    assert evaluate(lower_path_pattern(query), property_graph(DATA)) == PathSet()
    artifact = compile_bounded_paths(query, backend_id="fuseki", **OPTIONS)
    from xgap.runtime.path_selection import select_native_paths
    rows = RDF().execute(artifact)
    assert rows.success
    assert select_native_paths(rows.rows, artifact.parameters["path_selection"]) == ()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_repetition_queries_also_enter_through_the_semantic_dag(case):
    from xgap.experiments.toy_semantic import execute_semantic_case, wrap_path_case
    result = execute_semantic_case(wrap_path_case(case, "fuseki"), MAPPING, clients={"fuseki": RDF()})
    assert result["success"], result


def test_mode_scopes_are_not_flattened_across_nested_repetition():
    query = parse_path_pattern_query(CASES[10]["gold_path_pattern_query"])
    for mode in (RecursiveMode.TRAIL, RecursiveMode.SHORTEST):
        with pytest.raises(UnsupportedCompilationError, match="nested scoped"):
            compile_bounded_paths(replace(query, restrictor=mode), backend_id="fuseki", **OPTIONS)


def test_optional_and_repetition_still_obey_finite_native_budgets():
    query = parse_path_pattern_query(CASES[8]["gold_path_pattern_query"])
    with pytest.raises(UnsupportedCompilationError, match="budget"):
        compile_bounded_paths(query, backend_id="fuseki", max_branches=2, **OPTIONS)


def test_dead_zero_power_has_no_edge_requirement_and_exact_length_is_known():
    from xgap.pattern.typecheck import _fixed_edge_count
    assert _fixed_edge_count(Bounded(Rel(EdgePattern()), 0, 0)) == 0
    assert _fixed_edge_count(Bounded(Seq(Rel(EdgePattern()), Rel(EdgePattern())), 2, 2)) == 4
    assert _fixed_edge_count(OptionalExpr(Rel(EdgePattern()))) is None
