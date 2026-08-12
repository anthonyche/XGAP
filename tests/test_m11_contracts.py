import json

from xgap.algebra.ops import EdgesOp, JoinOp, NodesOp
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
    ExchangeDecision,
    MappingSufficiencyStatus,
    PlacementDecision,
    PlanningConfig,
    ProvidedSemanticDeviationScorer,
    QueryPlanningContext,
    SemanticDeviationStatus,
    index_logical_plan,
    objective_score,
)


def _candidate(candidate_id: str = "candidate-1") -> PlannerCandidate:
    query = PathPatternQuery(
        path_var=Var("p"),
        source=NodePattern(var=Var("a")),
        expr=Rel(EdgePattern(label="TRANSFER", var=Var("t"))),
        target=NodePattern(var=Var("b")),
        selector=Selector(SelectorKind.ALL),
        restrictor=PathMode.TRAIL,
    )
    return PlannerCandidate(
        question="Find transfers",
        candidate_id=candidate_id,
        pattern_query=query,
    )


def test_physical_state_has_deterministic_semantic_identity_and_progress() -> None:
    indexed = index_logical_plan(JoinOp(NodesOp(), EdgesOp()))
    root = indexed.root_state("candidate-1")

    assert indexed.root_operator_id == "op0002"
    assert root.assigned_operator_ids == ()
    assert root.unassigned_operator_ids == ("op0000", "op0001", "op0002")
    assert not root.is_complete

    placements = tuple(
        PlacementDecision(
            operator_id=operator.operator_id,
            backend_id="reference_evaluator",
            feature_id=operator.feature_id,
            support_level="supported",
        )
        for operator in root.operators
    )
    complete = type(root)(
        interpretation_id=root.interpretation_id,
        logical_plan_id=root.logical_plan_id,
        operators=root.operators,
        dependencies=root.dependencies,
        placements=tuple(reversed(placements)),
    )
    same = type(root)(
        interpretation_id=root.interpretation_id,
        logical_plan_id=root.logical_plan_id,
        operators=root.operators,
        dependencies=root.dependencies,
        placements=placements,
    )

    assert complete.is_complete
    assert complete.state_id == same.state_id
    assert complete.to_json() == same.to_json()
    assert json.loads(complete.to_json())["selected_backend_ids"] == ["reference_evaluator"]


def test_cross_backend_dependency_requires_an_executable_exchange() -> None:
    indexed = index_logical_plan(JoinOp(NodesOp(), EdgesOp()))
    root = indexed.root_state("candidate-1")
    placements = tuple(
        PlacementDecision(
            operator_id=operator.operator_id,
            backend_id="neo4j" if operator.operator_id != "op0001" else "fuseki",
            feature_id=operator.feature_id,
            support_level="conditional",
        )
        for operator in root.operators
    )
    partial = type(root)(
        interpretation_id=root.interpretation_id,
        logical_plan_id=root.logical_plan_id,
        operators=root.operators,
        dependencies=root.dependencies,
        placements=placements,
    )
    dependency = next(
        item
        for item in partial.dependencies
        if partial.placement_for(item.source_operator_id).backend_id
        != partial.placement_for(item.target_operator_id).backend_id
    )

    assert dependency.dependency_id in partial.unresolved_dependency_ids

    exchange = ExchangeDecision(
        dependency_id=dependency.dependency_id,
        source_operator_id=dependency.source_operator_id,
        target_operator_id=dependency.target_operator_id,
        source_backend_id=partial.placement_for(dependency.source_operator_id).backend_id,
        target_backend_id=partial.placement_for(dependency.target_operator_id).backend_id,
        strategy_id="controlled-row-transfer",
    )
    resolved = type(root)(
        interpretation_id=root.interpretation_id,
        logical_plan_id=root.logical_plan_id,
        operators=root.operators,
        dependencies=root.dependencies,
        placements=placements,
        exchanges=(exchange,),
    )
    assert dependency.dependency_id in resolved.resolved_dependency_ids


def test_artifact_alignment_missing_is_explicit_and_supplied_score_is_pluggable() -> None:
    provider = ArtifactOntologyAlignmentProvider(
        {
            "artifact_version": 1,
            "ontology": {"id": "risk-ontology", "version": "1"},
            "mapping": {"id": "risk-map", "version": "2"},
            "interpretations": {
                "candidate-1": {
                    "alignment_id": "align-1",
                    "mapping_status": "sufficient",
                    "required_terms": ["Transfer"],
                    "mapped_terms": ["TRANSFER"],
                    "evidence": ["mapping:Transfer->TRANSFER"],
                    "semantic_inputs": {"semantic_deviation": 0.2},
                }
            },
        }
    )
    context = QueryPlanningContext("query-1", "task-1", "Find transfers")
    alignment = provider.resolve(context, _candidate())
    missing = provider.resolve(context, _candidate("candidate-missing"))
    score = ProvidedSemanticDeviationScorer().score(context, _candidate(), alignment)

    assert alignment.mapping_sufficiency.status is MappingSufficiencyStatus.SUFFICIENT
    assert missing.mapping_sufficiency.status is MappingSufficiencyStatus.MISSING
    assert score.status is SemanticDeviationStatus.AVAILABLE
    assert score.value == 0.2


def test_objective_separates_semantic_admissibility_from_nash_eligibility() -> None:
    config = PlanningConfig(
        run_id="run-1",
        semantic_threshold=0.5,
        execution_threshold=10.0,
        top_k=2,
        global_delta=0.05,
    )
    boundary = objective_score(
        interpretation_id="candidate-1",
        semantic_deviation=0.5,
        conservative_cost=2.0,
        config=config,
    )
    eligible = objective_score(
        interpretation_id="candidate-2",
        semantic_deviation=0.2,
        conservative_cost=2.0,
        config=config,
    )

    assert boundary.semantically_admissible
    assert not boundary.nash_eligible
    assert boundary.nash_score is None
    assert eligible.nash_score == 2.4
