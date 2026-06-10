from dataclasses import dataclass

import pytest

from xgap.algebra.conditions import EdgeRef, LabelEquals, LengthEquals
from xgap.algebra.ops import (
    AlgebraOp,
    EdgesOp,
    GroupKey,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderKey,
    OrderByOp,
    OutputKind,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)
from xgap.algebra.validation import ValidationError, validate_plan


@dataclass(frozen=True)
class SolutionSpaceSourceOp(AlgebraOp):
    def output_kind(self) -> OutputKind:
        return OutputKind.SOLUTION_SPACE

    def children(self) -> tuple[AlgebraOp, ...]:
        return ()

    def operator_name(self) -> str:
        return "SolutionSpaceSource"


@dataclass(frozen=True)
class UnknownPathSetOp(AlgebraOp):
    def output_kind(self) -> OutputKind:
        return OutputKind.PATH_SET

    def children(self) -> tuple[AlgebraOp, ...]:
        return ()

    def operator_name(self) -> str:
        return "UnknownPathSet"


def test_validate_nodes_edges_and_nested_path_set_plan() -> None:
    knows_edges = SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp())
    plan = SelectionOp(
        LengthEquals(2),
        UnionOp(JoinOp(knows_edges, knows_edges), EdgesOp()),
    )

    validate_plan(NodesOp())
    validate_plan(EdgesOp())
    validate_plan(plan)


def test_selection_child_must_output_path_set() -> None:
    plan = SelectionOp(LengthEquals(1), SolutionSpaceSourceOp())

    with pytest.raises(ValidationError, match="Selection child must output PATH_SET"):
        validate_plan(plan)


def test_union_children_must_output_path_set() -> None:
    with pytest.raises(ValidationError, match="Union left child must output PATH_SET"):
        validate_plan(UnionOp(SolutionSpaceSourceOp(), EdgesOp()))

    with pytest.raises(ValidationError, match="Union right child must output PATH_SET"):
        validate_plan(UnionOp(EdgesOp(), SolutionSpaceSourceOp()))


def test_join_children_must_output_path_set() -> None:
    with pytest.raises(ValidationError, match="Join left child must output PATH_SET"):
        validate_plan(JoinOp(SolutionSpaceSourceOp(), EdgesOp()))

    with pytest.raises(ValidationError, match="Join right child must output PATH_SET"):
        validate_plan(JoinOp(EdgesOp(), SolutionSpaceSourceOp()))


def test_validation_recurses_into_children() -> None:
    plan = SelectionOp(LengthEquals(1), UnknownPathSetOp())

    with pytest.raises(NotImplementedError, match="UnknownPathSetOp"):
        validate_plan(plan)


def test_recursive_validation_accepts_valid_path_set_child() -> None:
    validate_plan(RecursiveOp(EdgesOp(), RecursiveMode.WALK, max_depth=2))
    validate_plan(RecursiveOp(EdgesOp(), RecursiveMode.TRAIL))


def test_recursive_child_must_output_path_set() -> None:
    plan = RecursiveOp(SolutionSpaceSourceOp(), RecursiveMode.TRAIL)

    with pytest.raises(ValidationError, match="Recursive child must output PATH_SET"):
        validate_plan(plan)


def test_recursive_walk_requires_max_depth() -> None:
    with pytest.raises(ValidationError, match="WALK mode requires a positive max_depth"):
        validate_plan(RecursiveOp(EdgesOp(), RecursiveMode.WALK))


def test_recursive_max_depth_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="max_depth must be positive"):
        validate_plan(RecursiveOp(EdgesOp(), RecursiveMode.TRAIL, max_depth=0))


def test_recursive_validation_recurses_into_child() -> None:
    plan = RecursiveOp(UnknownPathSetOp(), RecursiveMode.TRAIL)

    with pytest.raises(NotImplementedError, match="UnknownPathSetOp"):
        validate_plan(plan)


def test_future_and_unknown_plans_are_not_faked() -> None:
    with pytest.raises(NotImplementedError, match="object"):
        validate_plan(object())


def test_group_by_child_must_output_path_set() -> None:
    with pytest.raises(ValidationError, match="GroupBy child must output PATH_SET"):
        validate_plan(GroupByOp(SolutionSpaceSourceOp(), GroupKey.SOURCE_TARGET))


def test_order_by_child_must_output_solution_space() -> None:
    with pytest.raises(ValidationError, match="OrderBy child must output SOLUTION_SPACE"):
        validate_plan(OrderByOp(EdgesOp(), OrderKey.PATH))


def test_projection_child_must_output_solution_space() -> None:
    with pytest.raises(ValidationError, match="Projection child must output SOLUTION_SPACE"):
        validate_plan(ProjectionOp(EdgesOp(), num_paths=1))


def test_projection_limits_must_be_none_or_positive() -> None:
    grouped = GroupByOp(EdgesOp(), GroupKey.SOURCE_TARGET)

    for plan in (
        ProjectionOp(grouped, num_partitions=0),
        ProjectionOp(grouped, num_groups=-1),
        ProjectionOp(grouped, num_paths=0),
    ):
        with pytest.raises(ValidationError, match="must be None or a positive integer"):
            validate_plan(plan)


def test_solution_space_plan_validates_recursively() -> None:
    plan = ProjectionOp(
        OrderByOp(
            GroupByOp(
                RecursiveOp(EdgesOp(), RecursiveMode.TRAIL),
                GroupKey.SOURCE_TARGET,
            ),
            OrderKey.PATH,
        ),
        num_paths=1,
    )

    validate_plan(plan)


def test_unsupported_legacy_solution_space_keys_are_not_faked() -> None:
    with pytest.raises(NotImplementedError):
        validate_plan(GroupByOp(EdgesOp(), keys=("first",)))

    with pytest.raises(NotImplementedError):
        validate_plan(OrderByOp(GroupByOp(EdgesOp(), GroupKey.NONE), keys=("length",)))

    with pytest.raises(NotImplementedError):
        validate_plan(ProjectionOp(GroupByOp(EdgesOp(), GroupKey.NONE), fields=("first",)))
