from xgap.algebra.ops import JoinOp, NodesOp
from xgap.compilers.features import default_profile
from xgap.planning import (
    ExchangeDecision,
    ExistingCompilerAdapter,
    PlacementDecision,
    index_logical_plan,
)


def _placement(operator, backend_id, support_level="conditional"):
    return PlacementDecision(
        operator_id=operator.operator_id,
        backend_id=backend_id,
        feature_id=operator.feature_id,
        support_level=support_level,
    )


def test_existing_compiler_adapter_emits_current_m9_native_artifact() -> None:
    plan = NodesOp()
    indexed = index_logical_plan(plan)
    root = indexed.root_state("c1")
    profile = default_profile("neo4j")
    state = type(root)(
        interpretation_id=root.interpretation_id,
        logical_plan_id=root.logical_plan_id,
        operators=root.operators,
        dependencies=root.dependencies,
        placements=(_placement(root.operators[0], "neo4j"),),
    )

    result = ExistingCompilerAdapter().compile(plan, state, {"neo4j": profile})

    assert result.feasible and result.executable
    assert result.status == "compiled_native_query"
    assert result.artifacts[0].language == "cypher"


def test_existing_compiler_adapter_reports_multi_backend_runtime_boundary() -> None:
    plan = JoinOp(NodesOp(), NodesOp())
    indexed = index_logical_plan(plan)
    root = indexed.root_state("c1")
    profiles = {
        "neo4j": default_profile("neo4j"),
        "reference_evaluator": default_profile("reference_evaluator"),
    }
    placements = (
        _placement(root.operators[0], "neo4j"),
        _placement(root.operators[1], "reference_evaluator", "supported"),
        _placement(root.operators[2], "neo4j"),
    )
    cross_dependency = next(
        item for item in root.dependencies if item.source_operator_id == "op0001"
    )
    exchange = ExchangeDecision(
        dependency_id=cross_dependency.dependency_id,
        source_operator_id=cross_dependency.source_operator_id,
        target_operator_id=cross_dependency.target_operator_id,
        source_backend_id="reference_evaluator",
        target_backend_id="neo4j",
        strategy_id="controlled-test-transfer",
    )
    state = type(root)(
        interpretation_id=root.interpretation_id,
        logical_plan_id=root.logical_plan_id,
        operators=root.operators,
        dependencies=root.dependencies,
        placements=placements,
        exchanges=(exchange,),
    )

    result = ExistingCompilerAdapter().compile(plan, state, profiles)

    assert state.is_complete
    assert result.feasible and not result.executable
    assert result.reason_code == "distributed_cross_backend_runtime_not_implemented"
