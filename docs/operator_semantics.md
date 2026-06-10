# Operator Semantics

XGAP's logical operator vocabulary is path-based. The primary data object is PathSet. The secondary data object is SolutionSpace, used only by selector-style extended algebra operators.

The logical algebra is organized into:

Core path algebra
Recursive path algebra
Extended path algebra
## Data Objects
## Path

A Path is an alternating sequence:
node, edge, node, edge, ..., node
A zero-length path contains a single node.
A one-length path contains:
source, edge, target
The length of a path is the number of edges.

## PathSet

A PathSet is a deduplicated set of Path objects.

Core and recursive operators consume and produce PathSet.

## SolutionSpace

A SolutionSpace is the secondary data object used by the extended algebra.

It represents:

SS = (S, G, P, α, β, △)

where:

S is a PathSet.
P is a set of partitions.
G is a set of groups.
α : S -> G assigns each path to a group.
β : G -> P assigns each group to a partition.
△ : S ∪ G ∪ P -> positive integer assigns a rank to every path, group, and partition.

SolutionSpace is used by GroupBy, OrderBy, and Projection.

## Nodes(G)

Implemented.

Returns a `PathSet` containing one zero-length `Path` for every node in graph `G`.

## Edges(G)

Implemented.

Returns a `PathSet` containing one one-length `Path` for every edge in graph `G`. Each path has the form `source, edge, target`.

## Selection

Implemented.

Evaluates a child operator and keeps only paths that satisfy a condition. Current conditions support equality over
 node labels, 
 edge labels, 
 node properties, 
 edge properties, 
 `first`, 
 `last`, 
 path length, 
 and boolean `AND`, `OR`, `NOT`.

## Union

Implemented.

Evaluates both children and returns the deduplicated set union of their paths.

## Join

Implemented.

Evaluates both children and concatenates every pair of paths `p1`, `p2` where `p1.last() == p2.first()`. The shared node appears once in the concatenated path.

## Recursive

Implemented.

Evaluates Kleene-plus recursive path construction over a child `PathSet`.

Depth 1 includes paths from the child `PathSet`. Depth `k` extends the previous frontier by joining with the child `PathSet`. Outputs are deduplicated `PathSet` values. `max_depth` counts the number of child paths concatenated, not necessarily the number of graph edges in the resulting path.

Modes:

- `WALK`: allows repeated nodes and repeated edges. Requires an explicit positive `max_depth`.
- `TRAIL`: rejects paths with repeated edges. Repeated nodes are allowed. Without `max_depth`, evaluation terminates by deduplication and frontier exhaustion on finite graphs.
- `ACYCLIC`: rejects paths with repeated nodes. Without `max_depth`, evaluation terminates by deduplication and frontier exhaustion on finite graphs.
- `SIMPLE`: rejects repeated nodes except that the first node may equal the last node as the closing repeat of a cycle. Without `max_depth`, evaluation terminates by deduplication and frontier exhaustion on finite graphs.
- `SHORTEST`: returns shortest paths per source-target pair, where shortest means minimum `Path` length. If multiple paths tie for shortest length for the same source-target pair, all tied shortest paths are kept. If `max_depth` is provided, search is bounded by it; otherwise evaluation still terminates on finite graphs.

## GroupBy

Implemented.

GroupBy(key, child) evaluates child to a PathSet and transforms it into a SolutionSpace.

GroupBy does not remove paths.

GroupBy does not impose ordering.

GroupBy initializes every rank to 1.

Supported grouping keys:

# NONE

One partition and one group.

partition key = ()
group key = ()

# SOURCE

One partition per source node.

One group per partition.

partition key = (first(path),)
group key = ()

# TARGET

One partition per target node.

One group per partition.

partition key = (last(path),)
group key = ()

# LENGTH

One partition.

One group per path length.

partition key = ()
group key = (len(path),)

# SOURCE_TARGET

One partition per source-target pair.

One group per partition.

partition key = (first(path), last(path))
group key = ()

# SOURCE_LENGTH

One partition per source node.

One group per path length inside that source partition.

partition key = (first(path),)
group key = (len(path),)

# TARGET_LENGTH

One partition per target node.

One group per path length inside that target partition.

partition key = (last(path),)
group key = (len(path),)

# SOURCE_TARGET_LENGTH

One partition per source-target pair.

One group per path length inside that source-target partition.

partition key = (first(path), last(path))
group key = (len(path),)

# Empty input

If the child PathSet is empty, XGAP returns an empty SolutionSpace with no partitions, no groups, and no mappings.

## OrderBy

Implemented.

OrderBy(key, child) evaluates child to a SolutionSpace and returns a new SolutionSpace.

OrderBy preserves:

- paths
- partitions
- groups
- path-to-group assignment α
- group-to-partition assignment β

OrderBy only updates the rank function △.

Helper definitions:

MinL(group) = minimum len(path) among paths assigned to the group
MinL(partition) = minimum len(path) among paths assigned to groups inside the partition

Supported order keys:

# PARTITION
rank(partition) = MinL(partition)
rank(group) = unchanged
rank(path) = unchanged
# GROUP
rank(partition) = unchanged
rank(group) = MinL(group)
rank(path) = unchanged
# PATH
rank(partition) = unchanged
rank(group) = unchanged
rank(path) = len(path)
# PARTITION_GROUP
rank(partition) = MinL(partition)
rank(group) = MinL(group)
rank(path) = unchanged
# PARTITION_PATH
rank(partition) = MinL(partition)
rank(group) = unchanged
rank(path) = len(path)
# GROUP_PATH
rank(partition) = unchanged
rank(group) = MinL(group)
rank(path) = len(path)
# PARTITION_GROUP_PATH
rank(partition) = MinL(partition)
rank(group) = MinL(group)
rank(path) = len(path)

## Projection

Implemented.

Projection(num_partitions, num_groups, num_paths, child) evaluates child to a SolutionSpace and returns a PathSet.

Each projection parameter is either:

None, representing *
a positive integer limit

Projection proceeds in three levels:

1.Sort partitions by (rank, stable_partition_key).
2.Retain the first num_partitions partitions, or all partitions if num_partitions is None.
3.For each retained partition, sort its groups by (rank, stable_group_key).
4.Retain the first num_groups groups, or all groups if num_groups is None.
5.For each retained group, sort its paths by (rank, stable_path_key).
6.Retain the first num_paths paths, or all paths if num_paths is None.
7.Return the retained paths as a deduplicated PathSet.

Stable tie-breakers are used for reproducible reference evaluation.

Examples:

Projection(None, None, None, child)

corresponds to:

π(*, *, *)
Projection(None, None, 1, child)

corresponds to:

π(*, *, 1)
Projection(None, 1, None, child)

corresponds to:

π(*, 1, *)
## Selector-style examples
# ANY
Projection [*, *, 1]
  GroupBy [SOURCE_TARGET]
    Recursive [...]
      ...
# ANY k
Projection [*, *, k]
  GroupBy [SOURCE_TARGET]
    Recursive [...]
      ...
# ANY SHORTEST
Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [...]
        ...
# ALL SHORTEST
Projection [*, 1, *]
  OrderBy [GROUP]
    GroupBy [SOURCE_TARGET_LENGTH]
      Recursive [...]
        ...
# SHORTEST k
Projection [*, *, k]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [...]
        ...
# SHORTEST k GROUP
Projection [*, k, *]
  OrderBy [GROUP]
    GroupBy [SOURCE_TARGET_LENGTH]
      Recursive [...]
        ...
