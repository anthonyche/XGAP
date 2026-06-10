import pytest

from xgap.algebra.conditions import EdgeRef, LabelEquals
from xgap.algebra.evaluator import evaluate, evaluate_pathset, evaluate_solution_space
from xgap.algebra.ops import (
    EdgesOp,
    GroupKey,
    GroupByOp,
    OrderKey,
    OrderByOp,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
)
from xgap.algebra.types import GroupId, PartitionId, Path, PathSet, SolutionSpace
from xgap.algebra.graph import PropertyGraph
from xgap.compilers.gql import compile_gql


def build_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Node")
    graph.add_node("n2", label="Node")
    graph.add_node("n3", label="Node")
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n1", "n3", label="Knows")
    graph.add_edge("e3", "n2", "n3", label="Knows")
    graph.add_edge("e4", "n1", "n3", label="Knows")
    return graph


def edge_solution_space(group_key: GroupKey) -> SolutionSpace:
    return evaluate_solution_space(GroupByOp(EdgesOp(), group_key), build_graph())


def assert_grouping(
    solution_space: SolutionSpace,
    path: Path,
    partition_key: tuple[object, ...],
    group_key: tuple[object, ...],
) -> None:
    partition = PartitionId(partition_key)
    group = GroupId(partition, group_key)

    assert solution_space.path_to_group[path] == group
    assert solution_space.group_to_partition[group] == partition
    assert solution_space.rank(path) == 1
    assert solution_space.rank(group) == 1
    assert solution_space.rank(partition) == 1


def test_group_by_none() -> None:
    solution_space = edge_solution_space(GroupKey.NONE)

    assert solution_space.partitions == (PartitionId(()),)
    assert solution_space.groups == (GroupId(PartitionId(()), ()),)
    assert_grouping(solution_space, Path.one_length("n1", "e1", "n2"), (), ())


def test_group_by_source() -> None:
    solution_space = edge_solution_space(GroupKey.SOURCE)

    assert solution_space.partitions == (PartitionId(("n1",)), PartitionId(("n2",)))
    assert_grouping(solution_space, Path.one_length("n1", "e2", "n3"), ("n1",), ())
    assert_grouping(solution_space, Path.one_length("n2", "e3", "n3"), ("n2",), ())


def test_group_by_target() -> None:
    solution_space = edge_solution_space(GroupKey.TARGET)

    assert solution_space.partitions == (PartitionId(("n2",)), PartitionId(("n3",)))
    assert_grouping(solution_space, Path.one_length("n1", "e1", "n2"), ("n2",), ())
    assert_grouping(solution_space, Path.one_length("n1", "e4", "n3"), ("n3",), ())


def test_group_by_length() -> None:
    solution_space = edge_solution_space(GroupKey.LENGTH)

    assert solution_space.partitions == (PartitionId(()),)
    assert solution_space.groups == (GroupId(PartitionId(()), (1,)),)
    assert_grouping(solution_space, Path.one_length("n1", "e1", "n2"), (), (1,))


def test_group_by_source_target() -> None:
    solution_space = edge_solution_space(GroupKey.SOURCE_TARGET)

    assert_grouping(solution_space, Path.one_length("n1", "e1", "n2"), ("n1", "n2"), ())
    assert_grouping(solution_space, Path.one_length("n1", "e2", "n3"), ("n1", "n3"), ())


def test_group_by_source_length() -> None:
    solution_space = edge_solution_space(GroupKey.SOURCE_LENGTH)

    assert_grouping(solution_space, Path.one_length("n1", "e1", "n2"), ("n1",), (1,))
    assert_grouping(solution_space, Path.one_length("n2", "e3", "n3"), ("n2",), (1,))


def test_group_by_target_length() -> None:
    solution_space = edge_solution_space(GroupKey.TARGET_LENGTH)

    assert_grouping(solution_space, Path.one_length("n1", "e1", "n2"), ("n2",), (1,))
    assert_grouping(solution_space, Path.one_length("n1", "e2", "n3"), ("n3",), (1,))


def test_group_by_source_target_length() -> None:
    solution_space = edge_solution_space(GroupKey.SOURCE_TARGET_LENGTH)

    assert_grouping(solution_space, Path.one_length("n1", "e1", "n2"), ("n1", "n2"), (1,))
    assert_grouping(solution_space, Path.one_length("n1", "e4", "n3"), ("n1", "n3"), (1,))


def test_empty_input_behavior() -> None:
    empty_plan = GroupByOp(
        SelectionOp(LabelEquals(EdgeRef(1), "Missing"), EdgesOp()),
        GroupKey.NONE,
    )

    solution_space = evaluate_solution_space(empty_plan, build_graph())

    assert len(solution_space.paths) == 0
    assert solution_space.partitions == ()
    assert solution_space.groups == ()
    assert solution_space.path_to_group == {}


def recursive_trail_paths() -> RecursiveOp:
    return RecursiveOp(EdgesOp(), RecursiveMode.TRAIL, max_depth=2)


def test_order_by_path_updates_only_path_ranks() -> None:
    plan = OrderByOp(GroupByOp(recursive_trail_paths(), GroupKey.SOURCE_TARGET), OrderKey.PATH)

    solution_space = evaluate_solution_space(plan, build_graph())

    direct = Path.one_length("n1", "e2", "n3")
    longer = Path(("n1", "e1", "n2", "e3", "n3"))
    assert solution_space.rank(direct) == 1
    assert solution_space.rank(longer) == 2
    assert all(solution_space.rank(group) == 1 for group in solution_space.groups)
    assert all(solution_space.rank(partition) == 1 for partition in solution_space.partitions)


def test_order_by_group_and_partition() -> None:
    grouped = GroupByOp(recursive_trail_paths(), GroupKey.SOURCE_TARGET_LENGTH)
    solution_space = evaluate_solution_space(OrderByOp(grouped, OrderKey.PARTITION_GROUP), build_graph())

    source_target = PartitionId(("n1", "n3"))
    short_group = GroupId(source_target, (1,))
    long_group = GroupId(source_target, (2,))

    assert solution_space.rank(source_target) == 1
    assert solution_space.rank(short_group) == 1
    assert solution_space.rank(long_group) == 2


@pytest.mark.parametrize(
    "order_key",
    [
        OrderKey.PARTITION,
        OrderKey.GROUP,
        OrderKey.PARTITION_PATH,
        OrderKey.GROUP_PATH,
        OrderKey.PARTITION_GROUP_PATH,
    ],
)
def test_combined_order_keys(order_key: OrderKey) -> None:
    plan = OrderByOp(GroupByOp(recursive_trail_paths(), GroupKey.SOURCE_TARGET_LENGTH), order_key)

    solution_space = evaluate_solution_space(plan, build_graph())

    assert isinstance(solution_space, SolutionSpace)
    assert len(solution_space.paths) > 0


def test_projection_none_none_one() -> None:
    plan = ProjectionOp(
        OrderByOp(GroupByOp(recursive_trail_paths(), GroupKey.SOURCE_TARGET), OrderKey.PATH),
        num_partitions=None,
        num_groups=None,
        num_paths=1,
    )

    result = evaluate_pathset(plan, build_graph())

    assert Path.one_length("n1", "e2", "n3") in result
    assert Path.one_length("n1", "e4", "n3") not in result
    assert Path(("n1", "e1", "n2", "e3", "n3")) not in result


def test_projection_limit_validation_in_evaluator() -> None:
    graph = build_graph()
    grouped = GroupByOp(EdgesOp(), GroupKey.SOURCE_TARGET)

    with pytest.raises(ValueError, match="positive integer"):
        evaluate(ProjectionOp(grouped, num_paths=0), graph)


def test_any_shortest_style_plan() -> None:
    plan = ProjectionOp(
        OrderByOp(GroupByOp(recursive_trail_paths(), GroupKey.SOURCE_TARGET), OrderKey.PATH),
        num_paths=1,
    )

    result = evaluate_pathset(plan, build_graph())

    assert Path.one_length("n1", "e2", "n3") in result
    assert Path.one_length("n1", "e4", "n3") not in result
    assert Path(("n1", "e1", "n2", "e3", "n3")) not in result


def test_all_shortest_style_plan() -> None:
    plan = ProjectionOp(
        OrderByOp(
            GroupByOp(recursive_trail_paths(), GroupKey.SOURCE_TARGET_LENGTH),
            OrderKey.GROUP,
        ),
        num_groups=1,
    )

    result = evaluate_pathset(plan, build_graph())

    assert Path.one_length("n1", "e2", "n3") in result
    assert Path.one_length("n1", "e4", "n3") in result
    assert Path(("n1", "e1", "n2", "e3", "n3")) not in result


def test_evaluation_output_types() -> None:
    graph = build_graph()
    grouped = GroupByOp(EdgesOp(), GroupKey.NONE)
    projected = ProjectionOp(grouped)

    assert isinstance(evaluate_pathset(projected, graph), PathSet)
    assert isinstance(evaluate_solution_space(grouped, graph), SolutionSpace)

    with pytest.raises(TypeError):
        evaluate_pathset(grouped, graph)

    with pytest.raises(TypeError):
        evaluate_solution_space(EdgesOp(), graph)


def test_future_modules_remain_unimplemented() -> None:
    with pytest.raises(NotImplementedError):
        compile_gql(EdgesOp())
