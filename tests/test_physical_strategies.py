"""New strategy boundaries: real local SPARQL execution, no native services."""

from copy import deepcopy
from dataclasses import replace
import json
import threading

import pytest

from xgap.backends.capabilities import SupportLevel
from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.experiments.toy_backbone import DEFAULT_FIXTURE, load_fixture
from xgap.experiments.toy_semantic import load_semantic_cases, toy_backends
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.runtime.contracts import RuntimeNodeKind as R
from xgap.runtime.physical_strategies import prepare_physical_strategies
from xgap.runtime.scheduler import FederatedScheduler
from xgap.semantic.program import SemanticGraphProgram, SemanticProgramError
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, NativeBackendPlugin


NS = "https://xgap.test/toy/"
_, _, MAPPING = load_fixture()
PREFIX = "@prefix t: <" + NS + "> .\n"


def match(identifier):
    return {"operator_id": identifier, "kind": "match", "input_ids": [], "input_kinds": [],
        "output_kind": "binding_set", "parameters": {"node": {"label": "Person"},
            "entity_field": "person", "properties": {"age": "age"}}}


def program_data():
    return {"program_id": "entity-join-and-aggregate", "operators": [match("left"), match("right"),
        {"operator_id": "eligible", "kind": "filter", "input_ids": ["left"],
         "input_kinds": ["binding_set"], "output_kind": "binding_set", "parameters": {
             "condition": {"op": "ge", "field": "age", "value": 20}}},
        {"operator_id": "join", "kind": "join", "input_ids": ["eligible", "right"],
         "input_kinds": ["binding_set", "binding_set"], "output_kind": "binding_set",
         "parameters": {"left_on": "person", "right_on": "person"}},
        {"operator_id": "total", "kind": "aggregate", "input_ids": ["join"],
         "input_kinds": ["binding_set"], "output_kind": "grouped_bindings", "parameters": {
             "group_by": ["person"], "aggregations": {"total": {"op": "sum", "field": "right_age"}}}},
        {"operator_id": "answer", "kind": "order_limit", "input_ids": ["total"],
         "input_kinds": ["grouped_bindings"], "output_kind": "grouped_bindings", "parameters": {
             "order_by": [{"field": "total", "direction": "desc"}], "limit": 2}}], "roots": ["answer"]}


def setup(*, right_empty=False):
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graphs = {"left_rdf": rdf.Graph().parse(data=PREFIX +
        "t:a a t:Person; t:age 10. t:b a t:Person; t:age 20. t:c a t:Person; t:age 30.", format="turtle"),
        "right_rdf": rdf.Graph().parse(data=PREFIX + ("" if right_empty else
        "t:b a t:Person; t:age 40. t:c a t:Person; t:age 50. t:d a t:Person; t:age 60."), format="turtle")}
    calls = []
    lock = threading.Lock()

    class LocalRDF(FusekiClient):
        def _post_query(self, text):
            calls.append((self.backend_id, text))
            with lock:
                return json.loads(graphs[self.backend_id].query(text).serialize(format="json"))

    backends, plugins = {}, BackendPluginRegistry()
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    for name in graphs:
        backends[name] = replace(toy_backends(MAPPING)["fuseki"], backend_id=name,
            backend_mapping=replace(mapping, backend_id=name),
            profile=replace(default_profile("fuseki"), backend_id=name))
        client = LocalRDF(BackendDescriptor(name, "fuseki", "sparql", "rdf_graph"))
        plugins.register(NativeBackendPlugin(name, client))
    return backends, FederatedScheduler(BackendInvokeTool(plugins)), calls, graphs


def prepare(data=None, *, backends=None, **kwargs):
    if backends is None:
        backends = setup()[0]
    return prepare_physical_strategies(SemanticGraphProgram.from_dict(data or program_data()),
        source_bindings={"left": "left_rdf", "right": "right_rdf"}, backends=backends, **kwargs)


def test_single_bind_rewrites_reach_same_independent_gold_and_reduce_returned_rows():
    backends, scheduler, calls, _ = setup()
    data = program_data()
    before = deepcopy(data)
    space = prepare(data, backends=backends)
    assert data == before and not calls
    assert len(space.candidates) == space.candidate_count_upper_bound == 3
    assert not space.rejected_strategies
    expected = ({"person": NS + "c", "total": 50}, {"person": NS + "b", "total": 40})
    result_by_strategy = {}
    for candidate in space.candidates:
        result = scheduler.execute(candidate.plan)
        assert result.success, result.to_dict()
        assert result.final_rows == expected
        assert result.total_remote_calls == 2
        assert candidate.features["bind_query_count"] <= 1
        assert candidate.plan.metadata["source_bindings"] == {"left": "left_rdf", "right": "right_rdf"}
        result_by_strategy[candidate.strategy_id] = result
    baseline = result_by_strategy["coordinator"]
    bound = result_by_strategy["entity_bind/join/left_to_right"]
    assert next(n.row_count for n in baseline.node_results if n.node_id == "right/native") == 3
    assert next(n.row_count for n in bound.node_results if n.node_id == "right/native") == 2
    assert bound.total_bytes_moved < baseline.total_bytes_moved
    assert len({c.semantic_equivalence_key for c in space.candidates}) == 1
    json.dumps(space.to_dict(), allow_nan=False)


def test_path_driver_preserves_multiple_rows_per_entity():
    backends, scheduler, calls, graphs = setup()
    rdf = pytest.importorskip("rdflib", minversion="7.1.4")
    graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")
    # Two distinct edge identities to the same matching entity must survive.
    graph.parse(data=PREFIX + 't:extra a t:Edge; t:source t:a; t:target t:c; t:label "KNOWS"; t:weight 1.', format="turtle")
    graphs.update(left_rdf=graph, right_rdf=graph)
    data = deepcopy(load_semantic_cases()[0]["program"])
    # Existing source/target query meaning is retained; this is a new tiny case.
    space = prepare_physical_strategies(SemanticGraphProgram.from_dict(data),
        source_bindings={"paths": "left_rdf", "people": "right_rdf"}, backends=backends)
    assert len(space.candidates) == 2
    assert any("Match entity field" in r["reason"] for r in space.rejected_strategies)
    expected = {json.dumps({"person": NS + "c", "edge": NS + edge}, sort_keys=True)
                for edge in ("e4", "extra")}
    for candidate in space.candidates:
        result = scheduler.execute(candidate.plan)
        assert result.success, result.to_dict()
        assert {json.dumps(r, sort_keys=True) for r in result.final_rows} == expected
    assert len(calls) == 4


@pytest.mark.parametrize("failure", ["empty", "overflow"])
def test_empty_and_excessive_driving_bindings_never_retry_or_fallback(failure):
    backends, scheduler, calls, _ = setup(right_empty=failure == "empty")
    space = prepare(backends=backends, max_bindings=1 if failure == "overflow" else 100)
    selected = next(c for c in space.candidates if c.strategy_id == "entity_bind/join/right_to_left")
    result = scheduler.execute(selected.plan)
    assert len(calls) == result.total_remote_calls == 1
    assert calls[0][0] == "right_rdf"
    assert result.success is (failure == "empty")
    if failure == "empty":
        assert result.final_rows == ()
    else:
        assert any("bindings but limit" in (n.error or "") for n in result.node_results)


def test_shared_target_and_scalar_join_are_not_silently_rewritten():
    shared = program_data()
    shared["roots"].append("right")
    space = prepare(shared)
    assert "entity_bind/join/left_to_right" not in {c.strategy_id for c in space.candidates}
    assert any("shared or a separate answer root" in r["reason"] for r in space.rejected_strategies)
    scalar = program_data()
    scalar["operators"][3]["parameters"] = {"left_on": "age", "right_on": "age"}
    # Preserve a valid aggregate field after the different collision renaming.
    scalar["operators"][4]["parameters"]["aggregations"]["total"]["field"] = "age"
    space = prepare(scalar)
    assert [c.strategy_id for c in space.candidates] == ["coordinator"]
    assert len(space.rejected_strategies) == 2


def test_backend_capability_and_program_budget_are_admission_not_fake_plans():
    backends = setup()[0]
    profile = backends["right_rdf"].profile
    features = {**profile.features, "native.sparql": replace(profile.features["native.sparql"],
                                                           level=SupportLevel.UNSUPPORTED)}
    backends["right_rdf"] = replace(backends["right_rdf"], profile=replace(profile, features=features))
    with pytest.raises(UnsupportedCompilationError, match="native.sparql"):
        prepare(backends=backends)
    backends["right_rdf"] = replace(backends["right_rdf"], profile=replace(profile, engine="other_sparql"))
    space = prepare(backends=backends)
    assert "entity_bind/join/left_to_right" not in {c.strategy_id for c in space.candidates}
    assert any("No entity-bind adapter" in r["reason"] for r in space.rejected_strategies)
    huge = {"program_id": "outside-profile", "operators": [match("m" + str(i)) for i in range(65)],
            "roots": ["m" + str(i) for i in range(65)]}
    with pytest.raises(SemanticProgramError, match="at most64"):
        prepare_physical_strategies(SemanticGraphProgram.from_dict(huge), source_bindings={}, backends={})


def test_cypher_target_uses_parameterized_identity_filter_and_same_plan_columns():
    backends = setup()[0]
    backends["right_rdf"] = replace(toy_backends(MAPPING)["neo4j"], backend_id="right_rdf",
        profile=replace(default_profile("neo4j"), backend_id="right_rdf"))
    space = prepare(backends=backends)
    bound = next(c for c in space.candidates if c.strategy_id == "entity_bind/join/left_to_right")
    remote = next(n for n in bound.plan.nodes if n.kind is R.REMOTE_BIND_QUERY)
    artifact = remote.parameters["artifact"]
    assert artifact["parameters"]["output_columns"] == ["entity", "age"]
    assert "entity.id) IN $xgap_strategy_entity_bindings" in artifact["text"]
    assert artifact["parameters"]["xgap_strategy_entity_namespace"] == NS
    hostile = NS + "x') RETURN 99 //"
    prepared, count = FederatedScheduler._bind_artifact(remote, artifact, ({"person": hostile},))
    assert count == 1 and prepared["text"] == artifact["text"]
    assert hostile not in prepared["text"]
    assert prepared["parameters"]["xgap_strategy_entity_bindings"] == [hostile]


def test_multiple_joins_generate_single_rewrites_only_and_stable_candidate_identity():
    data = program_data()
    second = deepcopy(data)
    for op in second["operators"]:
        op["operator_id"] += "2"
        op["input_ids"] = [i + "2" for i in op["input_ids"]]
    data["operators"].extend(second["operators"])
    data["roots"].append("answer2")
    backends = setup()[0]
    program = SemanticGraphProgram.from_dict(data)
    options = {"source_bindings": {"left": "left_rdf", "left2": "left_rdf",
        "right": "right_rdf", "right2": "right_rdf"}, "backends": backends}
    space = prepare_physical_strategies(program, **options)
    assert len(space.candidates) == space.candidate_count_upper_bound == 5
    assert all(c.features["bind_query_count"] <= 1 for c in space.candidates)
    again = prepare_physical_strategies(program, **options)
    assert [c.to_dict() for c in space.candidates] == [c.to_dict() for c in again.candidates]
