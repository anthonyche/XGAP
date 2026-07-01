"""Executable semantics for implemented path-algebra plans."""

from __future__ import annotations

from fractions import Fraction

from xgap.algebra.bindings import (
    BindingKind,
    BindingRelation,
    BindingRow,
    BindingSchema,
)
from xgap.algebra.graph import PropertyGraph
from xgap.algebra.ops import (
    AntiSemiJoinOp,
    BindEdgeOp,
    BindNodeOp,
    BindingJoinOp,
    BindingProjectOp,
    EdgesOp,
    FocusProjectionOp,
    GroupKey,
    GroupByOp,
    JoinOp,
    NodesOp,
    OrderKey,
    OrderByOp,
    ProjectionOp,
    QuantifiedCheckOp,
    RecursiveMode,
    RecursiveOp,
    SelectionOp,
    UnionOp,
)
from xgap.algebra.types import GroupId, PartitionId, Path, PathSet, SolutionSpace


EvaluationResult = PathSet | SolutionSpace | BindingRelation


def evaluate(op: object, graph: PropertyGraph) -> EvaluationResult:
    if isinstance(op, NodesOp):
        return graph.nodes_as_paths()
    if isinstance(op, EdgesOp):
        return graph.edges_as_paths()
    if isinstance(op, SelectionOp):
        child_paths = evaluate_pathset(op.child, graph)
        return PathSet(path for path in child_paths if op.condition.evaluate(path, graph))
    if isinstance(op, UnionOp):
        return evaluate_pathset(op.left, graph).union(evaluate_pathset(op.right, graph))
    if isinstance(op, JoinOp):
        left_paths = evaluate_pathset(op.left, graph)
        right_paths = evaluate_pathset(op.right, graph)
        return _join_path_sets(left_paths, right_paths)
    if isinstance(op, RecursiveOp):
        return _evaluate_recursive(op, graph)
    if isinstance(op, GroupByOp):
        return _evaluate_group_by(op, graph)
    if isinstance(op, OrderByOp):
        return _evaluate_order_by(op, graph)
    if isinstance(op, ProjectionOp):
        return _evaluate_projection(op, graph)
    if isinstance(op, BindNodeOp):
        return _evaluate_bind_node(op, graph)
    if isinstance(op, BindEdgeOp):
        return _evaluate_bind_edge(op, graph)
    if isinstance(op, BindingJoinOp):
        return _evaluate_binding_join(op, graph)
    if isinstance(op, BindingProjectOp):
        return _evaluate_binding_project(op, graph)
    if isinstance(op, QuantifiedCheckOp):
        return _evaluate_quantified_check(op, graph)
    if isinstance(op, AntiSemiJoinOp):
        return _evaluate_anti_semi_join(op, graph)
    if isinstance(op, FocusProjectionOp):
        return _evaluate_focus_projection(op, graph)
    raise NotImplementedError(f"Evaluation is not implemented for {type(op).__name__}.")


def evaluate_pathset(op: object, graph: PropertyGraph) -> PathSet:
    result = evaluate(op, graph)
    if not isinstance(result, PathSet):
        raise TypeError(f"Expected PathSet from {type(op).__name__}, got {type(result).__name__}.")
    return result


def evaluate_solution_space(op: object, graph: PropertyGraph) -> SolutionSpace:
    result = evaluate(op, graph)
    if not isinstance(result, SolutionSpace):
        raise TypeError(
            f"Expected SolutionSpace from {type(op).__name__}, got {type(result).__name__}."
        )
    return result


def evaluate_binding_relation(op: object, graph: PropertyGraph) -> BindingRelation:
    result = evaluate(op, graph)
    if not isinstance(result, BindingRelation):
        raise TypeError(
            f"Expected BindingRelation from {type(op).__name__}, got {type(result).__name__}."
        )
    return result


def _join_path_sets(left_paths: PathSet, right_paths: PathSet) -> PathSet:
    result = PathSet()
    for left in left_paths:
        for right in right_paths:
            if left.can_concatenate(right):
                result.add(left.concatenate(right))
    return result


def _evaluate_recursive(op: RecursiveOp, graph: PropertyGraph) -> PathSet:
    _validate_recursive_depth(op)
    child_paths = evaluate_pathset(op.child, graph)
    if op.mode is RecursiveMode.SHORTEST:
        return _evaluate_shortest_recursive(child_paths, op.max_depth)
    return _evaluate_bounded_or_frontier_recursive(child_paths, op.mode, op.max_depth)


def _evaluate_group_by(op: GroupByOp, graph: PropertyGraph) -> SolutionSpace:
    group_key = op.group_key()
    paths = evaluate_pathset(op.child, graph)

    partitions: set[PartitionId] = set()
    groups: set[GroupId] = set()
    path_to_group: dict[Path, GroupId] = {}
    group_to_partition: dict[GroupId, PartitionId] = {}

    for path in paths:
        partition_key, group_key_value = _group_by_keys(group_key, path)
        partition = PartitionId(partition_key)
        group = GroupId(partition, group_key_value)

        partitions.add(partition)
        groups.add(group)
        path_to_group[path] = group
        group_to_partition[group] = partition

    return SolutionSpace(
        paths=paths,
        partitions=tuple(partitions),
        groups=tuple(groups),
        path_to_group=path_to_group,
        group_to_partition=group_to_partition,
        path_ranks={path: 1 for path in paths},
        group_ranks={group: 1 for group in groups},
        partition_ranks={partition: 1 for partition in partitions},
    )


def _group_by_keys(group_key: GroupKey, path: Path) -> tuple[tuple[object, ...], tuple[object, ...]]:
    if group_key is GroupKey.NONE:
        return (), ()
    if group_key is GroupKey.SOURCE:
        return (path.first(),), ()
    if group_key is GroupKey.TARGET:
        return (path.last(),), ()
    if group_key is GroupKey.LENGTH:
        return (), (len(path),)
    if group_key is GroupKey.SOURCE_TARGET:
        return (path.first(), path.last()), ()
    if group_key is GroupKey.SOURCE_LENGTH:
        return (path.first(),), (len(path),)
    if group_key is GroupKey.TARGET_LENGTH:
        return (path.last(),), (len(path),)
    if group_key is GroupKey.SOURCE_TARGET_LENGTH:
        return (path.first(), path.last()), (len(path),)
    raise NotImplementedError(f"GroupBy key {group_key.value} is not implemented.")


def _evaluate_order_by(op: OrderByOp, graph: PropertyGraph) -> SolutionSpace:
    order_key = op.order_key()
    solution_space = evaluate_solution_space(op.child, graph)

    partition_ranks = dict(solution_space.partition_ranks)
    group_ranks = dict(solution_space.group_ranks)
    path_ranks = dict(solution_space.path_ranks)

    if _orders_partitions(order_key):
        partition_ranks = {
            partition: solution_space.min_len_partition(partition)
            for partition in solution_space.partitions
        }
    if _orders_groups(order_key):
        group_ranks = {
            group: solution_space.min_len_group(group)
            for group in solution_space.groups
        }
    if _orders_paths(order_key):
        path_ranks = {path: len(path) for path in solution_space.paths}

    return SolutionSpace(
        paths=solution_space.paths,
        partitions=solution_space.partitions,
        groups=solution_space.groups,
        path_to_group=solution_space.path_to_group,
        group_to_partition=solution_space.group_to_partition,
        path_ranks=path_ranks,
        group_ranks=group_ranks,
        partition_ranks=partition_ranks,
    )


def _orders_partitions(order_key: OrderKey) -> bool:
    return order_key in {
        OrderKey.PARTITION,
        OrderKey.PARTITION_GROUP,
        OrderKey.PARTITION_PATH,
        OrderKey.PARTITION_GROUP_PATH,
    }


def _orders_groups(order_key: OrderKey) -> bool:
    return order_key in {
        OrderKey.GROUP,
        OrderKey.PARTITION_GROUP,
        OrderKey.GROUP_PATH,
        OrderKey.PARTITION_GROUP_PATH,
    }


def _orders_paths(order_key: OrderKey) -> bool:
    return order_key in {
        OrderKey.PATH,
        OrderKey.PARTITION_PATH,
        OrderKey.GROUP_PATH,
        OrderKey.PARTITION_GROUP_PATH,
    }


def _evaluate_projection(op: ProjectionOp, graph: PropertyGraph) -> PathSet:
    if op.fields is not None:
        raise NotImplementedError("Field-based projection is not part of M4 SolutionSpace semantics.")
    _validate_projection_limit(op.num_partitions, "num_partitions")
    _validate_projection_limit(op.num_groups, "num_groups")
    _validate_projection_limit(op.num_paths, "num_paths")

    solution_space = evaluate_solution_space(op.child, graph)
    result = PathSet()

    partitions = sorted(
        solution_space.partitions,
        key=lambda partition: (solution_space.rank(partition), partition.key),
    )
    for partition in _limit(partitions, op.num_partitions):
        groups = sorted(
            solution_space.groups_for_partition(partition),
            key=lambda group: (solution_space.rank(group), group.partition.key, group.key),
        )
        for group in _limit(groups, op.num_groups):
            paths = sorted(
                solution_space.paths_for_group(group),
                key=lambda path: (solution_space.rank(path), path.sequence),
            )
            for path in _limit(paths, op.num_paths):
                result.add(path)

    return result


def _evaluate_bind_node(op: BindNodeOp, graph: PropertyGraph) -> BindingRelation:
    schema = BindingSchema.from_pairs(((op.var, BindingKind.NODE),))
    rows: list[BindingRow] = []
    for path in evaluate_pathset(op.child, graph):
        if len(path) != 0:
            raise ValueError("BindNode child paths must have length zero.")
        rows.append(BindingRow(schema, (path.first(),)))
    return BindingRelation(schema, rows)


def _evaluate_bind_edge(op: BindEdgeOp, graph: PropertyGraph) -> BindingRelation:
    pairs: list[tuple[str, BindingKind]] = [(op.source_var, BindingKind.NODE)]
    if op.edge_var is not None:
        pairs.append((op.edge_var, BindingKind.EDGE))
    pairs.append((op.target_var, BindingKind.NODE))
    schema = BindingSchema.from_pairs(tuple(pairs))

    rows: list[BindingRow] = []
    for path in evaluate_pathset(op.child, graph):
        if len(path) != 1:
            raise ValueError("BindEdge child paths must have length one.")
        values = {op.source_var: path.first(), op.target_var: path.last()}
        if op.edge_var is not None:
            values[op.edge_var] = path.edge(1)
        rows.append(BindingRow.from_mapping(schema, values))
    return BindingRelation(schema, rows)


def _evaluate_binding_join(op: BindingJoinOp, graph: PropertyGraph) -> BindingRelation:
    left = evaluate_binding_relation(op.left, graph)
    right = evaluate_binding_relation(op.right, graph)
    schema = left.schema.merge(right.schema)
    rows: list[BindingRow] = []
    for left_row in left:
        for right_row in right:
            if left_row.compatible_with(right_row):
                rows.append(left_row.merge(right_row))
    return BindingRelation(schema, rows)


def _evaluate_binding_project(op: BindingProjectOp, graph: PropertyGraph) -> BindingRelation:
    relation = evaluate_binding_relation(op.child, graph)
    schema = relation.schema.project(op.vars)
    return BindingRelation(schema, [row.project(op.vars) for row in relation])


def _evaluate_quantified_check(op: QuantifiedCheckOp, graph: PropertyGraph) -> BindingRelation:
    candidates = evaluate_binding_relation(op.candidates, graph)
    witnesses = evaluate_binding_relation(op.witnesses, graph)
    domain = evaluate_binding_relation(op.domain, graph) if op.domain is not None else None
    kind = _quantifier_kind(op.quantifier)
    comparator = _quantifier_comparator(op.quantifier)
    threshold = _quantifier_threshold(op.quantifier)

    kept: list[BindingRow] = []
    for candidate in candidates:
        witness_values = _correlated_child_values(
            candidate,
            witnesses,
            op.correlation_vars,
            op.child_var,
        )
        if kind == "EXISTS":
            ok = len(witness_values) >= 1
        elif kind == "COUNT":
            count = len(witness_values)
            if comparator == "EQ":
                ok = count == threshold
            elif comparator == "GE":
                ok = count >= threshold
            else:
                raise ValueError(f"Unsupported count comparator {comparator!r}.")
        elif kind == "RATIO":
            if domain is None:
                raise ValueError("Ratio quantifier requires a domain relation.")
            domain_values = _correlated_child_values(
                candidate,
                domain,
                op.correlation_vars,
                op.child_var,
            )
            if not witness_values.issubset(domain_values):
                raise ValueError("Ratio witnesses must be a subset of the ratio domain.")
            ratio = Fraction(len(witness_values), len(domain_values)) if domain_values else None
            if ratio is None:
                ok = False
            elif comparator == "EQ":
                ok = ratio == threshold
            elif comparator == "GE":
                ok = ratio >= threshold
            else:
                raise ValueError(f"Unsupported ratio comparator {comparator!r}.")
        elif kind == "NONE":
            raise ValueError("NONE quantifiers must be evaluated through AntiSemiJoin.")
        else:
            raise ValueError(f"Unsupported quantifier kind {kind!r}.")
        if ok:
            kept.append(candidate)
    return BindingRelation(candidates.schema, kept)


def _evaluate_anti_semi_join(op: AntiSemiJoinOp, graph: PropertyGraph) -> BindingRelation:
    left = evaluate_binding_relation(op.left, graph)
    right = evaluate_binding_relation(op.right, graph)
    kept: list[BindingRow] = []
    for left_row in left:
        has_match = any(_rows_agree_on(left_row, right_row, op.on) for right_row in right)
        if not has_match:
            kept.append(left_row)
    return BindingRelation(left.schema, kept)


def _evaluate_focus_projection(op: FocusProjectionOp, graph: PropertyGraph) -> PathSet:
    relation = evaluate_binding_relation(op.child, graph)
    result = PathSet()
    for row in relation:
        result.add(Path.zero_length(row.value(op.focus_var)))
    return result


def _correlated_child_values(
    candidate: BindingRow,
    relation: BindingRelation,
    correlation_vars: tuple[str, ...],
    child_var: str,
) -> set[str]:
    result: set[str] = set()
    for row in relation:
        if _rows_agree_on(candidate, row, correlation_vars):
            result.add(row.value(child_var))
    return result


def _rows_agree_on(left: BindingRow, right: BindingRow, names: tuple[str, ...]) -> bool:
    return all(left.value(name) == right.value(name) for name in names)


def _quantifier_kind(quantifier: object) -> str:
    kind = getattr(quantifier, "kind", None)
    value = getattr(kind, "value", kind)
    if not isinstance(value, str):
        raise ValueError("Quantifier must expose a string kind.")
    return value


def _quantifier_comparator(quantifier: object) -> str | None:
    comparator = getattr(quantifier, "comparator", None)
    value = getattr(comparator, "value", comparator)
    if value in (None, "EQ", "="):
        return "EQ" if value is not None else None
    if value in ("GE", ">="):
        return "GE"
    raise ValueError(f"Unsupported quantifier comparator {value!r}.")


def _quantifier_threshold(quantifier: object) -> int | Fraction | None:
    return getattr(quantifier, "threshold", None)


def _validate_projection_limit(limit: int | None, name: str) -> None:
    if limit is not None and limit <= 0:
        raise ValueError(f"Projection {name} must be None or a positive integer.")


def _limit(items: list[object], limit: int | None) -> list[object]:
    if limit is None:
        return items
    return items[:limit]


def _validate_recursive_depth(op: RecursiveOp) -> None:
    if op.max_depth is not None and op.max_depth <= 0:
        raise ValueError("RecursiveOp max_depth must be positive when provided.")
    if op.mode is RecursiveMode.WALK and op.max_depth is None:
        raise ValueError("RecursiveOp WALK mode requires a positive max_depth.")


def _evaluate_bounded_or_frontier_recursive(
    child_paths: PathSet,
    mode: RecursiveMode,
    max_depth: int | None,
) -> PathSet:
    result = PathSet()
    base_paths = child_paths.sorted()
    seen: set[Path] = set()
    frontier = tuple(path for path in base_paths if _path_allowed(path, mode))
    depth = 1

    while frontier:
        for path in frontier:
            result.add(path)
            seen.add(path)

        if max_depth is not None and depth >= max_depth:
            break

        next_paths: list[Path] = []
        next_seen: set[Path] = set()
        for path in frontier:
            for child_path in base_paths:
                if not path.can_concatenate(child_path):
                    continue
                joined = path.concatenate(child_path)
                if joined in seen or joined in next_seen:
                    continue
                if not _path_allowed(joined, mode):
                    continue
                next_paths.append(joined)
                next_seen.add(joined)

        frontier = tuple(sorted(next_paths, key=lambda path: path.sequence))
        depth += 1

    return result


def _evaluate_shortest_recursive(child_paths: PathSet, max_depth: int | None) -> PathSet:
    if max_depth is not None and max_depth <= 0:
        raise ValueError("RecursiveOp max_depth must be positive when provided.")

    base_paths = child_paths.sorted()
    frontier = base_paths
    seen: set[Path] = set()
    best_by_pair: dict[tuple[str, str], tuple[int, set[Path]]] = {}
    depth = 1

    while frontier:
        for path in frontier:
            seen.add(path)
            _record_shortest(path, best_by_pair)

        if max_depth is not None and depth >= max_depth:
            break

        next_paths: list[Path] = []
        next_seen: set[Path] = set()
        for path in frontier:
            for child_path in base_paths:
                if not path.can_concatenate(child_path):
                    continue
                joined = path.concatenate(child_path)
                if joined in seen or joined in next_seen:
                    continue
                if _has_strictly_shorter_pair_path(joined, best_by_pair):
                    continue
                next_paths.append(joined)
                next_seen.add(joined)

        frontier = tuple(sorted(next_paths, key=lambda path: path.sequence))
        depth += 1

    return PathSet(
        path
        for _, paths in sorted(best_by_pair.values(), key=lambda item: item[0])
        for path in paths
    )


def _record_shortest(
    path: Path,
    best_by_pair: dict[tuple[str, str], tuple[int, set[Path]]],
) -> None:
    pair = (path.first(), path.last())
    path_length = len(path)
    current = best_by_pair.get(pair)
    if current is None or path_length < current[0]:
        best_by_pair[pair] = (path_length, {path})
        return
    if path_length == current[0]:
        current[1].add(path)


def _has_strictly_shorter_pair_path(
    path: Path,
    best_by_pair: dict[tuple[str, str], tuple[int, set[Path]]],
) -> bool:
    current = best_by_pair.get((path.first(), path.last()))
    return current is not None and current[0] < len(path)


def _path_allowed(path: Path, mode: RecursiveMode) -> bool:
    if mode is RecursiveMode.WALK:
        return True
    if mode is RecursiveMode.TRAIL:
        edge_ids = path.edge_ids()
        return len(edge_ids) == len(set(edge_ids))
    if mode is RecursiveMode.ACYCLIC:
        node_ids = path.node_ids()
        return len(node_ids) == len(set(node_ids))
    if mode is RecursiveMode.SIMPLE:
        return _is_simple_path(path)
    raise NotImplementedError(f"Recursive mode {mode.value} is not implemented.")


def _is_simple_path(path: Path) -> bool:
    node_ids = path.node_ids()
    if len(node_ids) == len(set(node_ids)):
        return True
    first = node_ids[0]
    if node_ids[-1] != first:
        return False
    for node_id in set(node_ids):
        count = node_ids.count(node_id)
        if node_id == first:
            if count != 2:
                return False
        elif count != 1:
            return False
    return True
