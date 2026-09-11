"""Nested scopes execute through the real semantic compiler and scheduler."""

from dataclasses import replace
import json
import threading

import pytest

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.errors import UnsupportedCompilationError
from xgap.compilers.features import default_profile
from xgap.experiments.toy_backbone import (DEFAULT_FIXTURE, check_reference, load_fixture, property_graph)
from xgap.experiments.toy_scoped import FIXTURE, execute_scoped_case, load_scoped_cases
from xgap.experiments.toy_semantic import toy_backends, wrap_path_case
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.llm.parser import parse_path_pattern_query
from xgap.runtime.bounded_paths import compile_bounded_path_plan
from xgap.runtime.contracts import FederatedExecutionPlan, RuntimeNodeKind as R
from xgap.runtime.path_composition import compose_paths
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans, run_semantic_plans
from xgap.semantic.program import SemanticGraphProgram
from xgap.tools import BackendInvokeTool, BackendPluginRegistry, CatalogBackendPlugin


DATA, _, MAPPING = load_fixture()
CASES = load_scoped_cases()
PARSER_LOCK = threading.Lock()  # RDFLib's shared query parser is not thread safe.


class RDF(FusekiClient):
    def __init__(self, name="fuseki"):
        super().__init__(BackendDescriptor(name, name, "sparql", "rdf"))
        rdf = pytest.importorskip("rdflib", minversion="7.1.4")
        self.graph = rdf.Graph().parse(DEFAULT_FIXTURE / "load.ttl", format="turtle")
        self.calls = 0

    def _post_query(self, text):
        with PARSER_LOCK:
            self.calls += 1
            return json.loads(self.graph.query(text).serialize(format="json"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_independent_chain_and_semantic_dag(case):
    reference = check_reference(case, property_graph(DATA))
    assert reference["logical_plan_passed"] and reference["reference_passed"], reference
    rdf = RDF()
    actual = sorted({str(row[0]) for row in rdf.graph.query(
        (FIXTURE / case["reference_target_queries"]["fuseki"]).read_text())})
    assert actual == case["expected_paths"]
    result = execute_scoped_case(case, MAPPING, client=rdf)
    assert result["success"], result
    assert rdf.calls == case["expected_remote_calls"]
    plan = FederatedExecutionPlan.from_dict(result["plan"])
    assert plan.to_dict() == result["plan"]
    assert sum(n.kind is R.REMOTE_QUERY for n in plan.nodes) == case["expected_remote_calls"]


@pytest.mark.parametrize("case", [CASES[0], CASES[7], CASES[12]], ids=lambda c:c["id"])
def test_scoped_work_enters_observation_selection_and_serving(case):
    wrapper = wrap_path_case(case, "fuseki")
    base = toy_backends(MAPPING)["fuseki"]
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    names = ("rdf_a", "rdf_b")
    backends = {name:replace(base, backend_id=name, backend_mapping=replace(mapping, backend_id=name),
        profile=replace(default_profile("fuseki"), backend_id=name)) for name in names}
    program = SemanticGraphProgram.from_dict(wrapper["program"])
    space = enumerate_semantic_plans(program, operator_sources={"traverse":"toy"},
        sources={"toy":LogicalSource("toy","frozen-v1",names)}, backends=backends)
    plugins = BackendPluginRegistry(); clients = []
    for name,catalog in space.observation_catalogs.items():
        client = RDF(name); clients.append(client)
        plugins.register(CatalogBackendPlugin(name,client,catalog))
    result = run_semantic_plans(space,BackendInvokeTool(plugins))
    assert result["success"], result
    assert result["observation_calls"] == 2 * case["expected_remote_calls"]
    assert result["execution_calls"] == case["expected_remote_calls"]
    assert sum(c.calls for c in clients) == result["observation_calls"] + result["execution_calls"]
    assert sorted("/".join(r["path"]) for r in result["execution"]["value"]["final_rows"]) == case["expected_paths"]


def test_native_profiles_and_finite_budgets_still_apply_to_scoped_plans():
    query = parse_path_pattern_query(CASES[0]["gold_path_pattern_query"])
    options = toy_backends(MAPPING)["fuseki"].path_options()
    with pytest.raises(UnsupportedCompilationError, match="budget"):
        compile_bounded_path_plan(query, max_branches=1, **options)
    with pytest.raises(UnsupportedCompilationError, match="edge identity"):
        compile_bounded_path_plan(query, **{**options,"rdf_edge_encoding":None})
    unbounded = parse_path_pattern_query(CASES[8]["gold_path_pattern_query"])
    with pytest.raises(UnsupportedCompilationError, match="max_depth"):
        compile_bounded_path_plan(replace(unbounded,max_depth=None), **options)


def test_walk_superset_never_replaces_invalid_original_mode_or_selector():
    from xgap.pattern.ast import Selector, SelectorKind
    from xgap.runtime.scoped_paths import compile_scoped_path_plan
    query = parse_path_pattern_query(CASES[0]["gold_path_pattern_query"])
    options = toy_backends(MAPPING)["fuseki"].path_options()
    with pytest.raises(ValueError):
        compile_scoped_path_plan(replace(query,restrictor="invalid"), **options)
    with pytest.raises(ValueError):
        compile_scoped_path_plan(replace(query,selector=Selector(SelectorKind.ANY_K,None)), **options)


def test_materialized_scope_arity_identity_and_bounds_fail_explicitly():
    rows = ({"path":["d","e6","d"]},)
    result = compose_paths([rows],{"operation":"join","max_edges":2})
    assert result == ({"path":["d","e6","d","e6","d"]},)
    with pytest.raises(ValueError,match="finite edge"):
        compose_paths([rows],{"operation":"join","max_edges":1})
    with pytest.raises(ValueError,match="finite positive"):
        compose_paths([rows],{"operation":"recursive","mode":"WALK","max_depth":None,"max_edges":2})
    with pytest.raises(ValueError,match="composition"):
        compose_paths([rows,rows],{"operation":"recursive","mode":"WALK","max_depth":1,"max_edges":2})


@pytest.mark.parametrize("matched", [True, False])
def test_replay_planning_comparison_accepts_optional_order_flag_and_still_checks_gold(monkeypatch, matched):
    # Replay only the local comparison boundary that failed after successful
    # native work. No backend action is repeated or claimed by this unit test.
    from types import SimpleNamespace
    import xgap.experiments.toy_planning as module
    case = wrap_path_case(CASES[0], "fuseki")
    assert "ordered" not in case
    rows = [{"path":["d","e6","d","e6","d"]}] if matched else []
    run = {"success":True,"execution":{"value":{"final_rows":rows}},
           "selection":{"selected_plan_id":"selected"}}
    plan = SimpleNamespace(plan_id="selected", metadata={"source_bindings":{"traverse":"fuseki"}})
    space = SimpleNamespace(observation_catalogs={}, candidates=(SimpleNamespace(plan=plan),))
    monkeypatch.setattr(module,"enumerate_semantic_plans",lambda *a,**k:space)
    monkeypatch.setattr(module,"run_semantic_plans",lambda *a,**k:run)
    record = module.execute_planned_semantic_case(case,MAPPING,clients={})
    assert record["success"] is matched
    assert record["planning_run"] == run
    assert record["validation_only_extra_remote_calls"] == 0
