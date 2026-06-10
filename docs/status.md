# XGAP Status

## Current Milestone

M5 completed.

Next milestone:
M6 Backend Capability Profiles.

## Completed

- M0 Project Skeleton
- M1 Data Model
- M2 Core Algebra
- M2.5 Logical Plan Infrastructure
- M3 Recursive Algebra
- M4 SolutionSpace Algebra
- M4.5 Semantic Audit
- M5 GPC-Lite Pattern AST And Lowering

## In Progress

None

## Implemented Logical Operators

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection`

## Implemented Deterministic Core

LogicalPlan
  -> validate_plan
  -> reference evaluation

## Implemented Structured Pattern Layer

PathPatternQuery
  -> type_check_path_pattern
  -> deterministic lowering
  -> LogicalPlan

## Not Implemented Yet
- Backend capability profiles
- GQL / Cypher / SPARQL compilers
- Logical optimization
- Learned cost estimator
- LLM planner
- Disambiguation
- KGQA evaluation

## Required Acceptance Command
./scripts/run_acceptance.sh

# Latest Known Acceptance Status

M0-M5 acceptance passed.

Expected checks include:

- harness check
- pytest
- examples/core_algebra_demo.py
- examples/plan_print_demo.py
- examples/recursive_demo.py
- examples/solution_space_demo.py
- examples/semantic_audit_demo.py
- examples/lowering_demo.py
- lowering tests
