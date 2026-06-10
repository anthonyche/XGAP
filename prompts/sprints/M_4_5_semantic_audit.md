## Goal

Audit the full XGAP logical algebra semantics after M4.

This sprint must not add new features. Its purpose is to verify that the implemented logical operators match:

docs/operator_semantics.md
the path algebra paper
existing tests and examples
expected type-flow invariants

Implemented logical operators:

Nodes(G)
Edges(G)
Selection
Union
Join
Recursive
GroupBy
OrderBy
Projection

## Required Preflight

Before implementation:

Read AGENTS.md.
Read docs/architecture.md.
Read docs/roadmap.md.
Read docs/status.md.
Read docs/operator_semantics.md.
Read docs/decisions.md.
Inspect:
src/xgap/algebra/types.py
src/xgap/algebra/graph.py
src/xgap/algebra/conditions.py
src/xgap/algebra/ops.py
src/xgap/algebra/evaluator.py
src/xgap/algebra/validation.py
src/xgap/algebra/pretty.py
all existing tests
all examples

Then report:

current milestone
files you expect to modify
files you will not modify
semantic properties to audit
acceptance criteria

Do not modify code before reporting the audit plan.

## Allowed Changes

You may modify:

tests/test_semantic_audit.py
existing tests if the change only strengthens semantic assertions
examples/semantic_audit_demo.py
docs/semantic_audit.md
docs/status.md
docs/roadmap.md
scripts/run_acceptance.sh

You may modify implementation files only if the audit reveals a real semantic bug:

src/xgap/algebra/types.py
src/xgap/algebra/evaluator.py
src/xgap/algebra/validation.py
src/xgap/algebra/pretty.py
src/xgap/algebra/conditions.py
src/xgap/algebra/graph.py
src/xgap/algebra/ops.py

If implementation files are modified, clearly explain which semantic bug was fixed.

## Forbidden Changes

Do not implement pattern lowering.

Do not implement GQL, Cypher, or SPARQL compilers.

Do not implement backend capability profiles.

Do not add LLM logic.

Do not add disambiguation logic.

Do not add learned cost estimation.

Do not add optimizer rewrite rules.

Do not change public operator names.

Do not weaken existing tests.

Do not change semantics just to make tests pass.

## Audit Requirements
1. Type-flow audit

Verify that every operator has the correct input and output type:

Nodes(G) -> PathSet
Edges(G) -> PathSet
Selection(PathSet) -> PathSet
Union(PathSet, PathSet) -> PathSet
Join(PathSet, PathSet) -> PathSet
Recursive(PathSet) -> PathSet
GroupBy(PathSet) -> SolutionSpace
OrderBy(SolutionSpace) -> SolutionSpace
Projection(SolutionSpace) -> PathSet

Add validation tests for invalid type combinations:

Selection(GroupBy(...)) should fail
OrderBy(Recursive(...)) should fail
Projection(Edges(...)) should fail
Join(GroupBy(...), Edges(...)) should fail
GroupBy(OrderBy(...)) should fail
2. Core algebra audit

Verify semantic invariants:

Nodes(G) returns exactly all zero-length paths.
Edges(G) returns exactly all one-length paths.
Selection never creates paths.
Union(A, A) == A.
Union(A, B) == Union(B, A).
Join(A, B) only concatenates paths where last(left) == first(right).
Join removes the duplicated middle node.
3. Recursive algebra audit

Verify mode-specific invariants:

WALK requires positive max_depth.
WALK may contain repeated nodes and repeated edges.
TRAIL never contains repeated edges.
ACYCLIC never contains repeated nodes.
SIMPLE only allows a repeated node when first == last.
SHORTEST returns only minimum-length paths per source-target pair.
If multiple shortest paths tie, all tied shortest paths are retained.
Recursive corresponds to Kleene-plus, not Kleene-star.
Kleene-star must remain expressible as Union(NodesOp(), RecursiveOp(...)).
4. SolutionSpace audit

Verify structural invariants:

GroupBy never removes paths.
GroupBy never creates new paths.
Every path in SolutionSpace.paths has exactly one group.
Every group has exactly one partition.
Every path, group, and partition has a positive rank.
After GroupBy, all ranks are initialized to 1.
Empty PathSet produces empty SolutionSpace.

Verify all grouping keys:

NONE
SOURCE
TARGET
LENGTH
SOURCE_TARGET
SOURCE_LENGTH
TARGET_LENGTH
SOURCE_TARGET_LENGTH
5. OrderBy audit

Verify:

OrderBy does not change paths.
OrderBy does not change partitions.
OrderBy does not change groups.
OrderBy does not change path-to-group assignments.
OrderBy does not change group-to-partition assignments.
OrderBy(PATH) sets path ranks to path lengths.
OrderBy(GROUP) sets group ranks to minimum path length in the group.
OrderBy(PARTITION) sets partition ranks to minimum path length in the partition.
Combined order keys update exactly the intended rank levels.
6. Projection audit

Verify:

Projection(None, None, None) returns all paths.
Projection(None, None, 1) returns at most one path per group.
Projection(None, 1, None) returns all paths from the first group of each partition.
Projection(1, None, None) returns paths only from the first partition.
Projection output is always a subset of the input SolutionSpace.paths.
Projection is deterministic under rank ties.
Zero and negative projection limits are invalid.

7. Selector mapping audit

Create tests for selector-style plans:

ANY
Projection(*, *, 1)
  GroupBy(SOURCE_TARGET)
    Recursive(...)
ANY k
Projection(*, *, k)
  GroupBy(SOURCE_TARGET)
    Recursive(...)
ANY SHORTEST
Projection(*, *, 1)
  OrderBy(PATH)
    GroupBy(SOURCE_TARGET)
      Recursive(...)
ALL SHORTEST
Projection(*, 1, *)
  OrderBy(GROUP)
    GroupBy(SOURCE_TARGET_LENGTH)
      Recursive(...)
SHORTEST k
Projection(*, *, k)
  OrderBy(PATH)
    GroupBy(SOURCE_TARGET)
      Recursive(...)
SHORTEST k GROUP
Projection(*, k, *)
  OrderBy(GROUP)
    GroupBy(SOURCE_TARGET_LENGTH)
      Recursive(...)

8. Paper example audit

Use a graph similar to the paper's Knows graph:

n1 -e1:Knows-> n2
n2 -e2:Knows-> n3
n3 -e3:Knows-> n2
n2 -e4:Knows-> n4

Audit:

Projection(*, *, 1)
  OrderBy(PATH)
    GroupBy(SOURCE_TARGET)
      Recursive(TRAIL)
        Selection(label(edge(1)) = "Knows")
          Edges

This should behave like ANY SHORTEST TRAIL.

Also audit:

Projection(*, 1, *)
  OrderBy(GROUP)
    GroupBy(SOURCE_TARGET_LENGTH)
      Recursive(ACYCLIC)
        Selection(label(edge(1)) = "Knows")
          Edges

This should behave like ALL SHORTEST ACYCLIC.

9. Documentation audit

Create or update docs/semantic_audit.md.

It should include:

audited operators
audited invariants
selector mapping table
known implementation choices
known limitations
commands run
result summary

Known implementation choices should include:

deterministic tie-breaking for nondeterministic selectors
None representing * in Projection
empty PathSet producing empty SolutionSpace
WALK requiring max_depth

10. Acceptance script

If examples/semantic_audit_demo.py exists, scripts/run_acceptance.sh should run it.

## Tests

Add:

tests/test_semantic_audit.py

The test suite should include:

type-flow tests
core algebra invariants
recursive mode invariants
solution-space invariants
order-by invariants
projection invariants
selector mapping tests
paper-example style tests

Run:

./scripts/run_acceptance.sh

## Acceptance Criteria
./scripts/run_acceptance.sh passes.
pytest passes.
all existing demos pass.
examples/semantic_audit_demo.py passes if added.
docs/semantic_audit.md exists.
docs/status.md marks M4.5 DONE only after tests pass.
docs/roadmap.md marks M4.5 DONE only after tests pass.
M5 and later remain TODO.
No lowering, compiler, backend, optimizer, LLM, disambiguation, or cost-estimator logic is added.
Final Report

## Report:

changed files
invariants audited
tests added
semantic bugs found, if any
semantic bugs fixed, if any
commands run
pytest result
demo result
docs/status.md update
docs/semantic_audit.md summary
limitations