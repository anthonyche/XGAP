# Sprint: M4 SolutionSpace Operators

## Goal

Implement XGAP's extended path algebra operators:

- `GroupBy`
- `OrderBy`
- `Projection`

M4 completes the logical operator semantics needed for selector-style path queries.

The key data-flow shape introduced in M4 is:

PathSet -> SolutionSpace -> SolutionSpace -> PathSet

## Required Preflight

Before implementation:

1. Read AGENTS.md.
2. Read docs/architecture.md.
3. Read docs/roadmap.md.
4. Read docs/status.md.
5. Read docs/operator_semantics.md.
6. Read docs/decisions.md if it exists.
7. Inspect:
- src/xgap/algebra/types.py
- src/xgap/algebra/ops.py
- src/xgap/algebra/evaluator.py
- src/xgap/algebra/pretty.py
- src/xgap/algebra/validation.py
- existing tests

Then report:

- current milestone
- files you expect to modify
- files you will not modify
- acceptance criteria

Do not modify code before reporting the implementation plan.

## Allowed Changes

You may modify:

src/xgap/algebra/types.py
src/xgap/algebra/ops.py
src/xgap/algebra/evaluator.py
src/xgap/algebra/pretty.py
src/xgap/algebra/validation.py
tests/test_solution_space.py
tests/test_ops_metadata.py
tests/test_pretty.py
tests/test_validation.py
examples/solution_space_demo.py
scripts/run_acceptance.sh
docs/operator_semantics.md
docs/status.md
docs/roadmap.md
docs/decisions.md
Forbidden Changes

Do not change existing M1/M2/M2.5/M3 semantics.

Do not change RecursiveOp behavior.

Do not implement pattern lowering.

Do not implement GQL, Cypher, or SPARQL compilers.

Do not add LLM logic.

Do not add backend/database execution logic.

Do not implement optimizer rules.

Do not remove existing tests.

Do not silently fake future features.

## Implementation Requirements
1. Implement or finalize SolutionSpace in types.py

A SolutionSpace represents:

SS = (S, G, P, α, β, △)

where:

- S is a PathSet.
- P is a set of partitions.
- G is a set of groups.
- α maps each Path to a GroupId.
- β maps each GroupId to a PartitionId.
- △ maps each Path, GroupId, and PartitionId to a positive integer rank.

Use explicit frozen dataclasses for:

- PartitionId
- GroupId

Suggested representation:

@dataclass(frozen=True)
class PartitionId:
    key: tuple[object, ...]

@dataclass(frozen=True)
class GroupId:
    partition: PartitionId
    key: tuple[object, ...]

SolutionSpace should expose helper methods if useful:

- groups_for_partition(partition)
- paths_for_group(group)
- rank(item)
- min_len_group(group)
- min_len_partition(partition)

2. Implement GroupByOp Metadata

GroupByOp must:

- output SOLUTION_SPACE
- have one child
- have operator name "GroupBy"
- include GroupKey in pretty formatting

Its child must output PATH_SET.

3. Implement OrderByOp Metadata

OrderByOp must:

- output SOLUTION_SPACE
- have one child
- have operator name "OrderBy"
- include OrderKey in pretty formatting

Its child must output SOLUTION_SPACE.

4. Implement ProjectionOp Metadata

ProjectionOp must:

- output PATH_SET
- have one child
- have operator name "Projection"
- display None as * in pretty formatting

Its child must output SOLUTION_SPACE.

Projection limits must be either:

- None
- positive integers

Zero or negative integers are invalid.

5. Implement GroupByOp Evaluation

## Supported GroupKey values:

- NONE
- SOURCE
- TARGET
- LENGTH
- SOURCE_TARGET
- SOURCE_LENGTH
- TARGET_LENGTH
- SOURCE_TARGET_LENGTH

Grouping rules:

NONE:
  partition key = ()
  group key = ()

SOURCE:
  partition key = (path.first(),)
  group key = ()

TARGET:
  partition key = (path.last(),)
  group key = ()

LENGTH:
  partition key = ()
  group key = (len(path),)

SOURCE_TARGET:
  partition key = (path.first(), path.last())
  group key = ()

SOURCE_LENGTH:
  partition key = (path.first(),)
  group key = (len(path),)

TARGET_LENGTH:
  partition key = (path.last(),)
  group key = (len(path),)

SOURCE_TARGET_LENGTH:
  partition key = (path.first(), path.last())
  group key = (len(path),)

After GroupBy, initialize every rank to 1:

rank(path) = 1
rank(group) = 1
rank(partition) = 1

If the input PathSet is empty, return an empty SolutionSpace.

6. Implement OrderByOp Evaluation

OrderByOp must preserve:

paths
partitions
groups
path-to-group mapping
group-to-partition mapping

It only updates ranks.

Helper definitions:

MinL(group) = minimum len(path) for paths assigned to the group
MinL(partition) = minimum len(path) for paths inside groups assigned to the partition

Rank update rules:

PARTITION:
  rank(partition) = MinL(partition)
  rank(group) = unchanged
  rank(path) = unchanged

GROUP:
  rank(partition) = unchanged
  rank(group) = MinL(group)
  rank(path) = unchanged

PATH:
  rank(partition) = unchanged
  rank(group) = unchanged
  rank(path) = len(path)

PARTITION_GROUP:
  rank(partition) = MinL(partition)
  rank(group) = MinL(group)
  rank(path) = unchanged

PARTITION_PATH:
  rank(partition) = MinL(partition)
  rank(group) = unchanged
  rank(path) = len(path)

GROUP_PATH:
  rank(partition) = unchanged
  rank(group) = MinL(group)
  rank(path) = len(path)

PARTITION_GROUP_PATH:
  rank(partition) = MinL(partition)
  rank(group) = MinL(group)
  rank(path) = len(path)
7. Implement ProjectionOp Evaluation

Projection parameters:

None means *
positive integer means a concrete limit

Projection algorithm:

1. Evaluate child to SolutionSpace.
2. Sort partitions by (rank, stable_partition_key).
3. Keep the requested number of partitions.
4. For each retained partition, sort groups by (rank, stable_group_key).
5. Keep the requested number of groups per partition.
6. For each retained group, sort paths by (rank, stable_path_key).
7. Keep the requested number of paths per group.
8. Return a deduplicated PathSet.

Stable tie-breakers are required for reproducibility.

Suggested stable keys:

partition: partition.key
group: (group.partition.key, group.key)
path: full path identifier sequence

8. Update evaluate() Return Type

M4 introduces two possible evaluator outputs:

PathSet | SolutionSpace

Add helper wrappers:

def evaluate_pathset(op, graph) -> PathSet:
    ...

def evaluate_solution_space(op, graph) -> SolutionSpace:
    ...

These helpers must raise TypeError if the returned type does not match the expected kind.

9. Update Validation

Validation rules:

GroupByOp.child must output PATH_SET.
OrderByOp.child must output SOLUTION_SPACE.
ProjectionOp.child must output SOLUTION_SPACE.
Projection limits must be None or positive integers.
Existing RecursiveOp validation must remain unchanged.

10. Update Pretty Printer

Pretty format examples:

GroupBy [SOURCE_TARGET]
  Recursive [TRAIL]
    Selection [label(edge(1)) = "Knows"]
      Edges
OrderBy [PATH]
  GroupBy [SOURCE_TARGET]
    ...
Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      ...

11. Add examples/solution_space_demo.py

The demo should build a small graph and evaluate:

Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [TRAIL]
        Selection [label(edge(1)) = "Knows"]
          Edges

The demo should print:

formatted plan
validation result
output paths

12. Update Acceptance Script

If examples/solution_space_demo.py exists, scripts/run_acceptance.sh should run it.

Tests

Add or update:

- tests/test_solution_space.py
- tests/test_ops_metadata.py
- tests/test_pretty.py
- tests/test_validation.py

Required test coverage:

GroupBy(NONE)
GroupBy(SOURCE)
GroupBy(TARGET)
GroupBy(LENGTH)
GroupBy(SOURCE_TARGET)
GroupBy(SOURCE_LENGTH)
GroupBy(TARGET_LENGTH)
GroupBy(SOURCE_TARGET_LENGTH)
Empty input behavior
OrderBy(PATH)
OrderBy(GROUP)
OrderBy(PARTITION)
Combined order keys
Projection(None, None, 1)
Projection limit validation
Full ANY SHORTEST style plan
Full ALL SHORTEST style plan
Evaluation output types
Future modules remain untouched
Existing M1-M3 tests still pass

Run:

./scripts/run_acceptance.sh

## Acceptance Criteria
pytest passes.
examples/core_algebra_demo.py runs.
examples/plan_print_demo.py runs.
examples/recursive_demo.py runs.
examples/solution_space_demo.py runs.
GroupBy, OrderBy, and Projection semantics are implemented.
docs/operator_semantics.md documents GroupBy, OrderBy, and Projection.
docs/status.md marks M4 DONE only after tests pass.
docs/roadmap.md marks M4 DONE only after tests pass.
M5 and later remain TODO.
No lowering, compiler, backend, optimizer, or LLM logic is added.

## Final Report

Report:

changed files
implemented behavior
tests added
commands run
pytest result
demo result
docs/status.md update
docs/operator_semantics.md update
limitations