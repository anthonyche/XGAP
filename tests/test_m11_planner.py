from dataclasses import dataclass

from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    FeatureSupport,
    SupportLevel,
    SupportReason,
)
from xgap.llm import MockStructuredCandidateProvider, plan_from_question
from xgap.llm.schemas import PlannerCandidate
from xgap.pattern import (
    EdgePattern,
    NodePattern,
    PathMode,
    PathPatternQuery,
    Rel,
    Selector,
    SelectorKind,
    Var,
)
from xgap.planning import (
    ArtifactOntologyAlignmentProvider,
    CostPrediction,
    ExchangeCatalog,
    FixedBudgetPolicy,
    PhysicalCompilationResult,
    PlanningConfig,
    ProvidedSemanticDeviationScorer,
    QueryPlanningContext,
    XGAPPhysicalPlanner,
)


M11_FEATURES = (
    "path_algebra.Nodes",
    "path_algebra.Edges",
    "path_algebra.Selection",
    "path_algebra.Union",
    "path_algebra.Join",
    "path_algebra.Recursive.WALK",
    "path_algebra.Recursive.TRAIL",
    "path_algebra.Recursive.ACYCLIC",
    "path_algebra.Recursive.SIMPLE",
    "path_algebra.Recursive.SHORTEST",
    "extended_path.GroupBy",
    "extended_path.OrderBy",
    "extended_path.Projection",
)


def _profile(backend_id: str = "controlled") -> BackendCapabilityProfile:
    return BackendCapabilityProfile(
        backend_id=backend_id,
        engine=backend_id,
        language="controlled",
        data_model="controlled",
        version=1,
        feature_namespace="xgap.path_gpc",
        features={
            feature_id: FeatureSupport(
                feature_id=feature_id,
                level=SupportLevel.SUPPORTED,
                reason=SupportReason(code="controlled", message="controlled profile"),
            )
            for feature_id in M11_FEATURES
        },
    )


def _candidate(candidate_id: str) -> PlannerCandidate:
    return PlannerCandidate(
        question="Find transfer targets",
        candidate_id=candidate_id,
        pattern_query=PathPatternQuery(
            path_var=Var("p"),
            source=NodePattern(var=Var("source")),
            expr=Rel(EdgePattern(var=Var("transfer"), label="TRANSFER")),
            target=NodePattern(var=Var("target")),
            selector=Selector(SelectorKind.ALL),
            restrictor=PathMode.TRAIL,
        ),
    )


def _alignment(values, statuses=None):
    statuses = statuses or {}
    return ArtifactOntologyAlignmentProvider(
        {
            "artifact_version": 1,
            "ontology": {"id": "controlled-ontology", "version": "1"},
            "mapping": {"id": "controlled-mapping", "version": "1"},
            "interpretations": {
                candidate_id: {
                    "alignment_id": f"alignment-{candidate_id}",
                    "mapping_status": statuses.get(candidate_id, "sufficient"),
                    "required_terms": ["Transfer"],
                    "mapped_terms": ["TRANSFER"],
                    "evidence": ["controlled fixture"],
                    "semantic_inputs": {"semantic_deviation": deviation},
                }
                for candidate_id, deviation in values.items()
            },
        }
    )


@dataclass(frozen=True)
class CandidateCostEstimator:
    complete_costs: dict[str, float]
    estimator_id: str = "controlled-candidate-cost"
    model_version: str = "1"

    def predict(self, state, confidence_context):
        del confidence_context
        cost = self.complete_costs[state.interpretation_id] if state.is_complete else 0.1
        upper = cost if state.is_complete else 100.0
        return CostPrediction(
            mu=0.0,
            sigma=0.0,
            lower=cost,
            upper=upper,
            beta=0.0,
            estimator_id=self.estimator_id,
            model_version=self.model_version,
        )


@dataclass(frozen=True)
class ControlledCompiler:
    compiler_id: str = "controlled-compiler"

    def compile(self, logical_plan, state, backend_profiles, *, pattern_query=None):
        del logical_plan, backend_profiles, pattern_query
        return PhysicalCompilationResult(
            feasible=state.is_complete,
            executable=False,
            status="controlled",
            reason_code="controlled_test_artifact",
        )


def _planner(alignment, costs):
    return XGAPPhysicalPlanner(
        alignment_provider=alignment,
        semantic_scorer=ProvidedSemanticDeviationScorer(),
        backend_profiles=(_profile(),),
        exchange_catalog=ExchangeCatalog(),
        budget_policy=FixedBudgetPolicy(50),
        cost_estimator=CandidateCostEstimator(costs),
        physical_compiler=ControlledCompiler(),
    )


def _config(top_k=3, t_max=10.0):
    return PlanningConfig(
        run_id="run-1",
        semantic_threshold=0.5,
        execution_threshold=t_max,
        top_k=top_k,
        global_delta=0.05,
    )


def test_main_planner_uses_nash_ranking_one_plan_per_interpretation_and_no_pareto_filter() -> None:
    candidates = (_candidate("c1"), _candidate("c2"), _candidate("c3"))
    planner = _planner(
        _alignment({"c1": 0.1, "c2": 0.2, "c3": 0.3}),
        {"c1": 8.0, "c2": 2.0, "c3": 5.0},
    )

    result = planner.plan(
        query_context=QueryPlanningContext("q1", "t1", "Find transfer targets"),
        candidates=candidates,
        config=_config(),
    )

    assert result.status == "ok"
    assert [item.candidate_id for item in result.selected_plans] == ["c2", "c3", "c1"]
    assert [item.objective.nash_score for item in result.selected_plans] == [2.4, 1.0, 0.8]
    assert len({item.candidate_id for item in result.selected_plans}) == 3
    assert all(len(record.search.discovered_complete_plans) == 1 for record in result.candidate_records)


def test_mapping_semantic_and_hard_execution_bound_fail_explicitly_without_fallback() -> None:
    candidates = (_candidate("missing"), _candidate("outside"), _candidate("threshold"))
    planner = _planner(
        _alignment(
            {"missing": 0.1, "outside": 0.6, "threshold": 0.2},
            statuses={"missing": "missing"},
        ),
        {"missing": 1.0, "outside": 1.0, "threshold": 10.0},
    )

    result = planner.plan(
        query_context=QueryPlanningContext("q1", "t1", "Find transfer targets"),
        candidates=candidates,
        config=_config(t_max=10.0),
    )

    statuses = {record.candidate_id: record.status for record in result.candidate_records}
    assert statuses == {
        "missing": "mapping_missing",
        "outside": "semantic_threshold_exceeded",
        "threshold": "no_plan_under_execution_threshold",
    }
    assert result.status == "no_plan_under_threshold"
    assert result.selected_plans == ()


def test_semantic_boundary_equality_is_admissible_but_not_nash_ranked() -> None:
    candidate = _candidate("boundary")
    planner = _planner(_alignment({"boundary": 0.5}), {"boundary": 1.0})

    result = planner.plan(
        query_context=QueryPlanningContext("q1", "t1", "Find transfer targets"),
        candidates=(candidate,),
        config=_config(),
    )

    record = result.candidate_records[0]
    assert record.objective is not None
    assert record.objective.semantically_admissible
    assert not record.objective.nash_eligible
    assert record.status == "semantic_utility_not_positive"
    assert result.selected_plans == ()


def test_top_k_ties_and_logical_compilation_are_deterministic() -> None:
    candidates = (_candidate("c2"), _candidate("c1"))
    planner = _planner(_alignment({"c1": 0.2, "c2": 0.2}), {"c1": 2.0, "c2": 2.0})
    context = QueryPlanningContext("q1", "t1", "Find transfer targets")

    first = planner.plan(query_context=context, candidates=candidates, config=_config(top_k=1))
    second = planner.plan(query_context=context, candidates=tuple(reversed(candidates)), config=_config(top_k=1))

    assert first.selected_plans[0].candidate_id == "c1"
    assert first.to_dict() == second.to_dict()
    assert first.candidate_records[0].logical_plan_id == second.candidate_records[0].logical_plan_id


def test_m10_mock_provider_drives_m11_without_live_llm() -> None:
    provider = MockStructuredCandidateProvider(
        payload={
            "provider_id": "mock",
            "candidates": [
                {
                    "candidate_id": "c1",
                    "pattern_query": {
                        "path_var": "p",
                        "source": {"var": "source"},
                        "expr": {
                            "kind": "rel",
                            "edge": {"var": "transfer", "label": "TRANSFER", "direction": "OUT"},
                        },
                        "target": {"var": "target"},
                        "selector": {"kind": "ALL"},
                        "restrictor": "TRAIL",
                    },
                }
            ],
        }
    )
    candidates = plan_from_question("Find transfer targets", provider=provider)
    planner = _planner(_alignment({"c1": 0.1}), {"c1": 2.0})

    result = planner.plan(
        query_context=QueryPlanningContext("q1", "t1", "Find transfer targets"),
        candidates=candidates,
        config=_config(),
    )

    assert result.status == "ok"
    assert result.selected_plans[0].candidate_id == "c1"
