import pytest

from xgap.algebra.conditions import EdgeRef, LabelEquals
from xgap.algebra.evaluator import evaluate_pathset, evaluate_solution_space
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import (
    EdgesOp,
    GroupKey,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderKey,
    OrderByOp,
    ProjectionOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)
from xgap.algebra.types import GroupId, PartitionId, Path, PathSet
from xgap.algebra.validation import ValidationError, validate_plan


def build_knows_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Person", properties={"name": "Moe"})
    graph.add_node("n2", label="Person", properties={"name": "Bart"})
    graph.add_node("n3", label="Person", properties={"name": "Lisa"})
    graph.add_node("n4", label="Person", properties={"name": "Apu"})
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n2", "n3", label="Knows")
    graph.add_edge("e3", "n3", "n2", label="Knows")
    graph.add_edge("e4", "n2", "n4", label="Knows")
    return graph


def build_selector_graph() -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("n1", label="Node")
    graph.add_node("n2", label="Node")
    graph.add_node("n3", label="Node")
    graph.add_edge("e1", "n1", "n2", label="Knows")
    graph.add_edge("e2", "n1", "n3", label="Knows")
    graph.add_edge("e3", "n2", "n3", label="Knows")
    graph.add_edge("e4", "n1", "n3", label="Knows")
    return graph


def knows_edges() -> SelectionOp:
    return SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp())


def recursive_trail(max_depth: int | None = 2) -> RecursiveOp:
    return RecursiveOp(knows_edges(), RecursiveMode.TRAIL, max_depth=max_depth)


def recursive_acyclic(max_depth: int | None = None) -> RecursiveOp:
    return RecursiveOp(knows_edges(), RecursiveMode.ACYCLIC, max_depth=max_depth)


def assert_subset(left: PathSet, right: PathSet) -> None:
    for path in left:
        assert path in right


def test_type_flow_validation_rejects_invalid_combinations() -> None:
    group_by_edges = GroupByOp(EdgesOp(), GroupKey.SOURCE_TARGET)
    order_grouped = OrderByOp(group_by_edges, OrderKey.PATH)

    invalid_plans = [
        SelectionOp(LabelEquals(EdgeRef(1), "Knows"), group_by_edges),
        OrderByOp(RecursiveOp(EdgesOp(), RecursiveMode.TRAIL), OrderKey.PATH),
        ProjectionOp(EdgesOp(), num_paths=1),
        JoinOp(group_by_edges, EdgesOp()),
        GroupByOp(order_grouped, GroupKey.SOURCE_TARGET),
    ]

    for plan in invalid_plans:
        with pytest.raises(ValidationError):
            validate_plan(plan)


def test_core_algebra_invariants() -> None:
    graph = build_knows_graph()
    nodes = evaluate_pathset(NodesOp(), graph)
    edges = evaluate_pathset(EdgesOp(), graph)
    selected = evaluate_pathset(knows_edges(), graph)

    assert nodes.sorted() == (
        Path.zero_length("n1"),
        Path.zero_length("n2"),
        Path.zero_length("n3"),
        Path.zero_length("n4"),
    )
    assert all(len(path) == 0 for path in nodes)
    assert edges.sorted() == (
        Path.one_length("n1", "e1", "n2"),
        Path.one_length("n2", "e2", "n3"),
        Path.one_length("n2", "e4", "n4"),
        Path.one_length("n3", "e3", "n2"),
    )
    assert all(len(path) == 1 for path in edges)
    assert_subset(selected, edges)
    assert evaluate_pathset(UnionOp(EdgesOp(), EdgesOp()), graph) == edges
    assert evaluate_pathset(UnionOp(NodesOp(), EdgesOp()), graph) == evaluate_pathset(
        UnionOp(EdgesOp(), NodesOp()),
        graph,
    )

    joined = evaluate_pathset(JoinOp(knows_edges(), knows_edges()), graph)
    for path in joined:
        left = Path(path.sequence[:3])
        right = Path(path.sequence[2:])
        assert left.last() == right.first()
        assert path.sequence == left.sequence + right.sequence[1:]


def test_recursive_audit_invariants() -> None:
    graph = build_knows_graph()

    with pytest.raises(ValueError, match="WALK mode requires"):
        evaluate_pathset(RecursiveOp(knows_edges(), RecursiveMode.WALK), graph)

    walk = evaluate_pathset(RecursiveOp(knows_edges(), RecursiveMode.WALK, max_depth=3), graph)
    assert Path(("n2", "e2", "n3", "e3", "n2", "e2", "n3")) in walk

    trail = evaluate_pathset(RecursiveOp(knows_edges(), RecursiveMode.TRAIL), graph)
    assert all(len(path.edge_ids()) == len(set(path.edge_ids())) for path in trail)

    acyclic = evaluate_pathset(RecursiveOp(knows_edges(), RecursiveMode.ACYCLIC), graph)
    assert all(len(path.node_ids()) == len(set(path.node_ids())) for path in acyclic)

    simple = evaluate_pathset(RecursiveOp(knows_edges(), RecursiveMode.SIMPLE), graph)
    for path in simple:
        node_ids = path.node_ids()
        if len(node_ids) != len(set(node_ids)):
            assert node_ids[0] == node_ids[-1]
            assert node_ids.count(node_ids[0]) == 2
            assert all(node_ids.count(node_id) == 1 for node_id in set(node_ids[1:-1]))

    shortest = evaluate_pathset(RecursiveOp(knows_edges(), RecursiveMode.SHORTEST), graph)
    min_length_by_pair: dict[tuple[str, str], int] = {}
    for path in trail:
        pair = (path.first(), path.last())
        min_length_by_pair[pair] = min(len(path), min_length_by_pair.get(pair, len(path)))
    for path in shortest:
        assert len(path) == min_length_by_pair[(path.first(), path.last())]

    tied_graph = build_selector_graph()
    tied = evaluate_pathset(RecursiveOp(SelectionOp(LabelEquals(EdgeRef(1), "Knows"), EdgesOp()), RecursiveMode.SHORTEST), tied_graph)
    assert Path.one_length("n1", "e2", "n3") in tied
    assert Path.one_length("n1", "e4", "n3") in tied

    assert all(len(path) > 0 for path in trail)
    kleene_star = evaluate_pathset(UnionOp(NodesOp(), RecursiveOp(knows_edges(), RecursiveMode.TRAIL)), graph)
    assert all(Path.zero_length(node_id) in kleene_star for node_id in ("n1", "n2", "n3", "n4"))


@pytest.mark.parametrize(
    "group_key",
    [
        GroupKey.NONE,
        GroupKey.SOURCE,
        GroupKey.TARGET,
        GroupKey.LENGTH,
        GroupKey.SOURCE_TARGET,
        GroupKey.SOURCE_LENGTH,
        GroupKey.TARGET_LENGTH,
        GroupKey.SOURCE_TARGET_LENGTH,
    ],
)
def test_solution_space_group_by_invariants(group_key: GroupKey) -> None:
    graph = build_selector_graph()
    input_paths = evaluate_pathset(recursive_trail(), graph)
    solution_space = evaluate_solution_space(GroupByOp(recursive_trail(), group_key), graph)

    assert solution_space.paths == input_paths
    assert set(solution_space.path_to_group) == set(input_paths)
    assert set(solution_space.group_to_partition) == set(solution_space.groups)
    assert all(solution_space.path_to_group[path] in solution_space.groups for path in input_paths)
    assert all(solution_space.group_to_partition[group] in solution_space.partitions for group in solution_space.groups)
    assert all(solution_space.rank(path) > 0 for path in solution_space.paths)
    assert all(solution_space.rank(group) > 0 for group in solution_space.groups)
    assert all(solution_space.rank(partition) > 0 for partition in solution_space.partitions)
    assert all(solution_space.rank(path) == 1 for path in solution_space.paths)
    assert all(solution_space.rank(group) == 1 for group in solution_space.groups)
    assert all(solution_space.rank(partition) == 1 for partition in solution_space.partitions)


def test_empty_pathset_produces_empty_solution_space() -> None:
    graph = build_selector_graph()
    empty_child = SelectionOp(LabelEquals(EdgeRef(1), "Missing"), EdgesOp())

    solution_space = evaluate_solution_space(GroupByOp(empty_child, GroupKey.NONE), graph)

    assert len(solution_space.paths) == 0
    assert solution_space.partitions == ()
    assert solution_space.groups == ()
    assert solution_space.path_to_group == {}
    assert solution_space.group_to_partition == {}


def test_order_by_preserves_structure_and_updates_requested_ranks() -> None:
    graph = build_selector_graph()
    grouped = evaluate_solution_space(GroupByOp(recursive_trail(), GroupKey.SOURCE_TARGET_LENGTH), graph)

    for order_key in OrderKey:
        ordered = evaluate_solution_space(
            OrderByOp(GroupByOp(recursive_trail(), GroupKey.SOURCE_TARGET_LENGTH), order_key),
            graph,
        )
        assert ordered.paths == grouped.paths
        assert ordered.partitions == grouped.partitions
        assert ordered.groups == grouped.groups
        assert ordered.path_to_group == grouped.path_to_group
        assert ordered.group_to_partition == grouped.group_to_partition

        updates_partitions = "PARTITION" in order_key.value
        updates_groups = "GROUP" in order_key.value
        updates_paths = "PATH" in order_key.value

        for partition in ordered.partitions:
            expected = grouped.min_len_partition(partition) if updates_partitions else 1
            assert ordered.rank(partition) == expected
        for group in ordered.groups:
            expected = grouped.min_len_group(group) if updates_groups else 1
            assert ordered.rank(group) == expected
        for path in ordered.paths:
            expected = len(path) if updates_paths else 1
            assert ordered.rank(path) == expected


def test_projection_invariants_and_determinism() -> None:
    graph = build_selector_graph()
    grouped_plan = GroupByOp(recursive_trail(), GroupKey.SOURCE_TARGET_LENGTH)
    grouped = evaluate_solution_space(grouped_plan, graph)

    all_paths = evaluate_pathset(ProjectionOp(grouped_plan), graph)
    assert all_paths == grouped.paths

    one_path_per_group = evaluate_pathset(ProjectionOp(grouped_plan, num_paths=1), graph)
    for group in grouped.groups:
        assert len([path for path in one_path_per_group if grouped.path_to_group[path] == group]) <= 1

    first_group_per_partition = evaluate_pathset(ProjectionOp(grouped_plan, num_groups=1), graph)
    for partition in grouped.partitions:
        retained_groups = {
            grouped.path_to_group[path]
            for path in first_group_per_partition
            if grouped.group_to_partition[grouped.path_to_group[path]] == partition
        }
        assert len(retained_groups) <= 1

    first_partition = evaluate_pathset(ProjectionOp(grouped_plan, num_partitions=1), graph)
    retained_partitions = {
        grouped.group_to_partition[grouped.path_to_group[path]]
        for path in first_partition
    }
    assert retained_partitions == {grouped.partitions[0]}
    assert_subset(first_partition, grouped.paths)

    deterministic_once = evaluate_pathset(
        ProjectionOp(GroupByOp(recursive_trail(), GroupKey.SOURCE_TARGET), num_paths=1),
        graph,
    )
    deterministic_twice = evaluate_pathset(
        ProjectionOp(GroupByOp(recursive_trail(), GroupKey.SOURCE_TARGET), num_paths=1),
        graph,
    )
    assert deterministic_once == deterministic_twice

    for plan in (
        ProjectionOp(grouped_plan, num_partitions=0),
        ProjectionOp(grouped_plan, num_groups=-1),
        ProjectionOp(grouped_plan, num_paths=0),
    ):
        with pytest.raises(ValueError, match="positive integer"):
            evaluate_pathset(plan, graph)


def test_selector_mapping_plans() -> None:
    graph = build_selector_graph()
    recursive = recursive_trail()

    any_result = evaluate_pathset(ProjectionOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET), num_paths=1), graph)
    any_k_result = evaluate_pathset(ProjectionOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET), num_paths=2), graph)
    any_shortest = evaluate_pathset(
        ProjectionOp(OrderByOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET), OrderKey.PATH), num_paths=1),
        graph,
    )
    all_shortest = evaluate_pathset(
        ProjectionOp(OrderByOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET_LENGTH), OrderKey.GROUP), num_groups=1),
        graph,
    )
    shortest_k = evaluate_pathset(
        ProjectionOp(OrderByOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET), OrderKey.PATH), num_paths=2),
        graph,
    )
    shortest_k_group = evaluate_pathset(
        ProjectionOp(OrderByOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET_LENGTH), OrderKey.GROUP), num_groups=2),
        graph,
    )

    assert len(any_result) <= len(any_k_result)
    assert Path.one_length("n1", "e2", "n3") in any_shortest
    assert Path(("n1", "e1", "n2", "e3", "n3")) not in any_shortest
    assert Path.one_length("n1", "e2", "n3") in all_shortest
    assert Path.one_length("n1", "e4", "n3") in all_shortest
    assert Path(("n1", "e1", "n2", "e3", "n3")) not in all_shortest
    assert len(shortest_k) >= len(any_shortest)
    assert len(shortest_k_group) >= len(all_shortest)


def test_paper_style_any_shortest_trail() -> None:
    graph = build_knows_graph()
    recursive = RecursiveOp(knows_edges(), RecursiveMode.TRAIL)
    plan = ProjectionOp(
        OrderByOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET), OrderKey.PATH),
        num_paths=1,
    )

    result = evaluate_pathset(plan, graph)
    grouped = evaluate_solution_space(GroupByOp(recursive, GroupKey.SOURCE_TARGET), graph)

    for path in result:
        partition = PartitionId((path.first(), path.last()))
        candidate_lengths = [
            len(candidate)
            for candidate in grouped.paths
            if candidate.first() == path.first() and candidate.last() == path.last()
        ]
        assert len(path) == min(candidate_lengths)
        assert len([candidate for candidate in result if candidate.first() == path.first() and candidate.last() == path.last()]) == 1
        assert partition in grouped.partitions


def test_paper_style_all_shortest_acyclic() -> None:
    graph = build_knows_graph()
    recursive = RecursiveOp(knows_edges(), RecursiveMode.ACYCLIC)
    plan = ProjectionOp(
        OrderByOp(GroupByOp(recursive, GroupKey.SOURCE_TARGET_LENGTH), OrderKey.GROUP),
        num_groups=1,
    )

    result = evaluate_pathset(plan, graph)
    grouped = evaluate_solution_space(GroupByOp(recursive, GroupKey.SOURCE_TARGET_LENGTH), graph)

    for path in result:
        partition = PartitionId((path.first(), path.last()))
        candidate_lengths = [
            len(candidate)
            for candidate in grouped.paths
            if candidate.first() == path.first() and candidate.last() == path.last()
        ]
        assert len(path) == min(candidate_lengths)
    assert Path(("n1", "e1", "n2")) in result
    assert Path(("n1", "e1", "n2", "e2", "n3")) in result
