"""Small exhaustive oracles check the algorithm, not benchmark answer quality."""

from dataclasses import replace
import json
from pathlib import Path
import random

import pytest

from test_semantic_planning import CASES, MAPPING, registry
from xgap.backends.mapping import RdfBackendMapping
from xgap.compilers.features import default_profile
from xgap.experiments.toy_semantic import toy_backends
from xgap.runtime.planning import FederatedPlanSelector, PlanObservationSnapshot, RemoteEstimate
from xgap.runtime.semantic_placement import prepare_semantic_placements
from xgap.runtime.semantic_planning import LogicalSource, enumerate_semantic_plans, run_semantic_plans
from xgap.semantic.program import (SemanticGraphProgram, SemanticOperator, SemanticOperatorKind as S,
                                   SemanticValueKind as V, SemanticProgramError)


def inputs(case=None, m=2, k=2):
    names = tuple(f"rdf_{i}" for i in range(k))
    base = toy_backends(MAPPING)["fuseki"]
    mapping = RdfBackendMapping.from_artifact(MAPPING, backend_id="fuseki")
    backends = {b: replace(base, backend_id=b, backend_mapping=replace(mapping, backend_id=b),
        profile=replace(default_profile("fuseki"), backend_id=b)) for b in names}
    if case is None:
        operators = tuple(SemanticOperator(f"s{i}", S.MATCH, (), (), V.BINDING_SET,
            {"node": {"label": "Person"}, "entity_field": "person"}) for i in range(m))
        program = SemanticGraphProgram("placement-scale", operators, tuple(o.operator_id for o in operators))
    else:
        program = SemanticGraphProgram.from_dict(case["program"])
    bindings = {op.operator_id: "toy" for op in program.operators if op.kind in (S.MATCH, S.TRAVERSE)}
    return program, dict(operator_sources=bindings, sources={"toy": LogicalSource("toy", "toy-v1", names)},
                        backends=backends, max_observation_calls=1024, max_remote_calls=max(m, 16))


def snapshot(space, seed=0, *, variable_rows=False, zero=False):
    rng = random.Random(seed)
    return PlanObservationSnapshot("controlled", "v1", tuple(
        RemoteEstimate(r.observation_key, r.backend_id, 0 if zero else rng.randint(1, 100),
            0 if zero else (rng.randint(1, 40) if variable_rows else 5),
            rng.randint(1, 80) if variable_rows else 40, "controlled model table", "v1")
        for r in space.observation_requests), 1000, 0, 0 if zero else 0.1)


def consumed_inputs(*, m=1, source_also_root=False):
    program, opts = inputs(m=m)
    projection = SemanticOperator("answer", S.PROJECT, ("s0",), (V.BINDING_SET,), V.BINDING_SET,
        {"projections": {"person": {"kind": "field", "field": "person"}}})
    roots = (*program.roots, "answer") if source_also_root else (*program.roots[1:], "answer")
    return replace(program, operators=(*program.operators, projection), roots=roots), opts


def test_terminal_plateau_is_solved_by_independent_minima():
    program, opts = inputs(m=2)
    space = prepare_semantic_placements(program, **opts)
    observed = snapshot(space)
    observed = replace(observed, estimates=tuple(replace(e,
        elapsed_ms=10 if e.backend_id == "rdf_0" else 0,
        row_count=1 if e.backend_id == "rdf_0" else 2,
        row_width_bytes=1 if e.backend_id == "rdf_0" else 100) for e in observed.estimates))
    candidate, selection = space.select(observed)
    costs = [FederatedPlanSelector().estimate(c.plan, observed).predicted_latency_ms
             for c in enumerate_semantic_plans(program, **opts).candidates]
    assert selection["certificate"]["baseline_ms"] == pytest.approx(10.101)
    assert selection["certificate"]["kind"] == "exact_separable"
    assert selection["certificate"]["upper_bound_ms"] == min(costs) == pytest.approx(0.4)
    assert set(candidate.plan.metadata["source_bindings"].values()) == {"rdf_1"}
    assert selection["local_score_evaluations"] == 4
    assert selection["evaluated_plan_count"] <= 2


def test_preserved_633_regret_input_now_matches_the_frozen_oracle():
    replay = json.loads((Path(__file__).resolve().parents[1] /
        "experiments/replays/polynomial_terminal_sources_6ed9cce.json").read_text())
    program, opts = inputs(m=4, k=8)
    assert program.to_dict() == replay["program"]
    opts["sources"] = {"toy": LogicalSource(**{**replay["source"],
        "replica_backend_ids": tuple(replay["source"]["replica_backend_ids"])})}
    opts.update(replay["limits"])
    space = prepare_semantic_placements(program, **opts)
    _, selected = space.select(PlanObservationSnapshot.from_dict(replay["snapshot"]))
    cert = selected["certificate"]
    assert replay["original_selection"]["certificate"]["upper_bound_ms"] == 63.936
    assert cert["upper_bound_ms"] == replay["frozen_grid_row"]["oracle_estimated_ms"] == 10.096
    assert cert["kind"] == "exact_separable" and cert["ratio_bound"] == 1
    assert selected["local_score_evaluations"] == 32 and selected["evaluated_plan_count"] <= 2


@pytest.mark.parametrize("source_also_root", [False, True])
def test_consumed_source_must_keep_downstream_cardinality_guard(source_also_root):
    program, opts = consumed_inputs(source_also_root=source_also_root)
    space = prepare_semantic_placements(program, **opts)
    observed = snapshot(space)
    observed = replace(observed, estimates=tuple(replace(e,
        elapsed_ms=0 if e.backend_id == "rdf_0" else 11,
        row_count=100 if e.backend_id == "rdf_0" else 0, row_width_bytes=1)
        for e in observed.estimates))
    candidate, selected = space.select(observed)
    # Source readiness alone prefers rdf_0 (10.1 < 11), but downstream
    # projection costs another 10 ms. A false exactness claim would pick rdf_0.
    assert selected["certificate"]["kind"] == "instance_gap"
    assert candidate.plan.metadata["source_bindings"] == {"s0": "rdf_1"}
    assert selected["certificate"]["upper_bound_ms"] == 11


@pytest.mark.parametrize("consumed_rows_vary", [False, True])
def test_mixed_terminal_and_consumed_sources_use_per_source_guard(consumed_rows_vary):
    program, opts = consumed_inputs(m=2)
    space = prepare_semantic_placements(program, **opts)
    terminal_keys = {n.parameters["observation_key"] for b in space.options["s1"]
        for n in space.local_nodes["s1", b] if "observation_key" in n.parameters}
    observed = snapshot(space, variable_rows=True)
    if not consumed_rows_vary:
        observed = replace(observed, estimates=tuple(e if e.observation_key in terminal_keys
            else replace(e, row_count=5, row_width_bytes=40) for e in observed.estimates))
    _, selected = space.select(observed)
    assert (selected["certificate"]["kind"] == "exact_separable") is not consumed_rows_vary
    optimum = min(FederatedPlanSelector().estimate(c.plan, observed).predicted_latency_ms
                  for c in enumerate_semantic_plans(program, **opts).candidates)
    cert = selected["certificate"]
    assert cert["lower_bound_ms"] <= optimum <= cert["upper_bound_ms"]
    if not consumed_rows_vary:
        assert cert["upper_bound_ms"] == optimum


def test_changed_terminal_branch_executes_the_tiny_gold():
    program, opts = inputs(m=1)
    source = program.operators[0]
    program = replace(program, operators=(replace(source, parameters={**source.parameters,
        "node": {"label": "Person", "properties": {"name": "Alice"}}}),))
    space = prepare_semantic_placements(program, **opts)
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, snapshot=snapshot(space, variable_rows=True))
    assert result["success"], result
    assert result["selection"]["certificate"]["kind"] == "exact_separable"
    assert result["execution"]["value"]["final_rows"] == [{"person": "https://xgap.test/toy/a"}]
    assert result["observation_calls"] == 0 and result["execution_calls"] == len(calls) == 1


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
@pytest.mark.parametrize("variable_rows", [False, True])
def test_complete_local_domain_and_model_bounds_against_exhaustive(case, variable_rows):
    program, opts = inputs(case)
    space = prepare_semantic_placements(program, **opts)
    oracle = enumerate_semantic_plans(program, **opts)
    assert {r.observation_key for r in space.observation_requests} == {r.observation_key for r in oracle.observation_requests}
    for seed in range(3):
        observed = snapshot(space, seed, variable_rows=variable_rows)
        candidate, selection = space.select(observed)
        optimum = min(e.predicted_latency_ms for e in
                      (FederatedPlanSelector().estimate(c.plan, observed) for c in oracle.candidates))
        cert = selection["certificate"]
        assert cert["lower_bound_ms"] <= optimum <= cert["upper_bound_ms"] <= cert["baseline_ms"]
        assert selection["evaluated_plan_count"] <= selection["evaluation_bound"]
        if cert["kind"] == "exact_separable":
            assert cert["upper_bound_ms"] == pytest.approx(optimum)
        assert candidate.plan.to_dict() in [c.plan.to_dict() for c in oracle.candidates]


def test_main_search_never_calls_exhaustive_enumeration(monkeypatch):
    import xgap.runtime.semantic_planning as old
    def forbidden(*a, **kw):
        pytest.fail("polynomial planner invoked exhaustive enumeration")
    monkeypatch.setattr(old, "enumerate_semantic_plans", forbidden)
    program, opts = inputs(m=16, k=2)
    space = prepare_semantic_placements(program, **opts)
    assert space.possible_placement_count == 65536 and space.local_option_count == 32
    candidate, selection = space.select(snapshot(space, variable_rows=True))
    assert len(space.candidates) == 1 and len(candidate.plan.nodes) == 48
    assert selection["evaluated_plan_count"] <= 65


def test_polynomial_plan_executes_the_independent_toy_gold():
    case = CASES[0]
    program, opts = inputs(case)
    space = prepare_semantic_placements(program, **opts)
    tool, calls = registry(space)
    result = run_semantic_plans(space, tool, snapshot=snapshot(space))
    assert result["success"], result
    assert result["execution"]["value"]["final_rows"] == case["expected_rows"]
    assert result["execution_calls"] == len(calls) == case["expected_remote_calls"]
    assert result["search_space_materialized"] is False


def test_source_capability_pruning_is_local_and_does_not_require_a_lucky_baseline():
    program, opts = inputs(m=2)
    bad = replace(opts["backends"]["rdf_0"].profile, language="unknown")
    opts["backends"]["rdf_0"] = replace(opts["backends"]["rdf_0"], profile=bad)
    space = prepare_semantic_placements(program, **opts)
    assert space.local_option_count == 2
    assert len(space.rejected_placements) == 2
    assert set(space.baseline.plan.metadata["source_bindings"].values()) == {"rdf_1"}


def test_no_ratio_is_invented_when_optimistic_lower_bound_is_zero():
    program, opts = consumed_inputs()
    space = prepare_semantic_placements(program, **opts)
    observed = snapshot(space)
    # Fast/high-cardinality versus slow/empty: independent minima are unattainable.
    estimates = tuple(replace(e, elapsed_ms=0 if i == 0 else 10, row_count=100 if i == 0 else 0)
                      for i, e in enumerate(observed.estimates))
    _, selection = space.select(replace(observed, estimates=estimates))
    cert = selection["certificate"]
    assert cert["kind"] == "instance_gap" and cert["lower_bound_ms"] == 0
    assert cert["upper_bound_ms"] > 0 and cert["ratio_bound"] is None
    _, zero = space.select(snapshot(space, zero=True))
    assert zero["certificate"]["ratio_bound"] == 1


def test_compact_huge_repetition_is_rejected_before_compilation(monkeypatch):
    import xgap.runtime.semantic_placement as module
    program, opts = inputs(CASES[0])
    traverser = next(op for op in program.operators if op.kind is S.TRAVERSE)
    raw = dict(traverser.parameters["path_pattern"])
    raw["expr"] = {"kind": "bounded", "child": raw["expr"], "min_repeats": 10**12, "max_repeats": 10**12}
    program = replace(program, operators=tuple(replace(op, parameters={**op.parameters, "path_pattern": raw})
                      if op is traverser else op for op in program.operators))
    def forbidden(*a, **kw):
        pytest.fail("oversized compact input reached a compiler")
    monkeypatch.setattr(module, "compile_semantic_source", forbidden)
    with pytest.raises(SemanticProgramError, match="compiler-input profile"):
        prepare_semantic_placements(program, **opts)


def test_topology_change_has_no_invented_global_certificate(monkeypatch):
    import xgap.runtime.semantic_placement as module
    from xgap.runtime.contracts import RuntimeNode, RuntimeNodeKind as R
    original = module.compile_semantic_source
    def extra_projection(op, backend):
        fragment = original(op, backend)
        if backend.backend_id == "rdf_1":
            node = RuntimeNode(op.operator_id + "/extra", R.PROJECT, (fragment.output,),
                               {"fields": ["person"]}, (op.operator_id,))
            return replace(fragment, nodes=(*fragment.nodes, node), output=node.node_id)
        return fragment
    monkeypatch.setattr(module, "compile_semantic_source", extra_projection)
    program, opts = inputs(m=2)
    space = prepare_semantic_placements(program, **opts)
    assert not space.same_cost_topology
    _, result = space.select(snapshot(space))
    cert = result["certificate"]
    assert cert["kind"] == "baseline_only" and cert["ratio_bound"] is None
    assert cert["lower_bound_ms"] is None and not cert["full_local_domain_covered"]
    assert cert["upper_bound_ms"] <= cert["baseline_ms"]
