## Goal

Implement RecursiveOp reference evaluator semantics for path-algebra recursive queries, while keeping future SolutionSpace operators, lowering, compilers, and LLM logic unimplemented.

## Required preflight

Before implementation:

1. Read AGENTS.md.
2. Read docs/architecture.md.
3. Read docs/roadmap.md.
4. Read docs/status.md.
5. Read docs/operator_semantics.md.
6. Read docs/decisions.md if it exists.
7. Inspect relevant src/ and tests/, especially:
   - src/xgap/algebra/ops.py
   - src/xgap/algebra/evaluator.py
   - src/xgap/algebra/validation.py
   - src/xgap/algebra/pretty.py
   - src/xgap/algebra/types.py
   - src/xgap/algebra/graph.py
   - existing tests/

Then report:
- current milestone
- files you expect to modify
- files you will not modify
- acceptance criteria

Do not modify code before reporting the plan.

## Allowed changes

You may modify:

- src/xgap/algebra/ops.py
- src/xgap/algebra/evaluator.py
- src/xgap/algebra/pretty.py
- src/xgap/algebra/validation.py
- tests/test_recursive.py
- tests/test_ops_metadata.py
- tests/test_pretty.py
- tests/test_validation.py
- examples/recursive_demo.py
- docs/operator_semantics.md
- docs/status.md

## Forbidden changes

Do not implement GroupBy evaluator semantics.
Do not implement OrderBy evaluator semantics.
Do not implement Projection evaluator semantics.
Do not implement pattern lowering.
Do not implement GQL, Cypher, or SPARQL compilers.
Do not add LLM logic.
Do not add backend/database execution logic.
Do not rename existing implemented operators.
Do not remove existing tests.
Do not silently fake future features.

## Implementation requirements

1. Confirm or add RecursiveMode enum with:
   - WALK
   - TRAIL
   - ACYCLIC
   - SIMPLE
   - SHORTEST

2. Confirm or add RecursiveOp metadata:
   - output_kind: PATH_SET
   - one child
   - operator_name: "Recursive"
   - include mode and max_depth information in formatting

3. Implement RecursiveOp evaluation in evaluator.py.

4. RecursiveOp is Kleene-plus style:
   - depth 1 includes paths from the child PathSet.
   - depth k extends paths by joining with the child PathSet.
   - outputs are deduplicated PathSet values.
   - max_depth counts the number of child paths concatenated, not necessarily the number of graph edges.

5. WALK semantics:
   - allows repeated nodes.
   - allows repeated edges.
   - must require explicit positive max_depth.
   - evaluator must reject WALK without max_depth.

6. TRAIL semantics:
   - rejects paths with repeated edges.
   - repeated nodes are allowed.
   - if max_depth is provided, respect it.
   - if max_depth is absent, implementation must still terminate on finite graphs by using deduplication/frontier exhaustion.

7. ACYCLIC semantics:
   - rejects paths with repeated nodes.
   - if max_depth is provided, respect it.
   - if max_depth is absent, implementation must still terminate on finite graphs by using deduplication/frontier exhaustion.

8. SIMPLE semantics:
   - rejects repeated nodes except that first node may equal last node.
   - the only permitted repeated node is the closing node of a cycle.
   - no other node may repeat.
   - if max_depth is provided, respect it.
   - if max_depth is absent, implementation must still terminate on finite graphs by using deduplication/frontier exhaustion.

9. SHORTEST semantics:
   - returns shortest paths per source-target pair.
   - shortest means minimum path length according to the Path representation.
   - if multiple paths tie for shortest length for the same source-target pair, keep all tied shortest paths.
   - if max_depth is provided, search within that bound.
   - if max_depth is absent, implementation must still terminate on finite graphs.

10. validate_plan(op):
   - RecursiveOp child must output PATH_SET.
   - WALK RecursiveOp must have positive max_depth.
   - max_depth, if provided, must be positive.
   - recursively validate children.
   - GroupBy, OrderBy, and Projection must remain unimplemented for evaluation.

11. format_plan(op):
   - include RecursiveOp mode.
   - include max_depth when present.
   - remain stable and deterministic.

12. Add examples/recursive_demo.py:
   - builds a small graph with at least one cycle.
   - evaluates WALK with max_depth.
   - evaluates TRAIL.
   - evaluates ACYCLIC.
   - evaluates SIMPLE.
   - evaluates SHORTEST.
   - prints readable output.

13. Update docs/operator_semantics.md:
   - mark Recursive modes as implemented only after tests pass.
   - preserve existing semantics.
   - do not document future operators as implemented.

14. Update docs/status.md:
   - mark M3 DONE only after all required checks pass.
   - keep M4 and later TODO.

## Tests

Add or update:

- tests/test_recursive.py
- tests/test_ops_metadata.py
- tests/test_pretty.py
- tests/test_validation.py

Test coverage must include:

- WALK requires max_depth.
- WALK allows repeated nodes and edges.
- TRAIL rejects repeated edges.
- ACYCLIC rejects repeated nodes.
- SIMPLE allows first == last only as the closing repeat.
- SHORTEST returns shortest paths per source-target pair.
- RecursiveOp formatting is stable.
- RecursiveOp validation is recursive.
- GroupBy, OrderBy, and Projection evaluation still raise NotImplementedError.

Run:

```bash
./scripts/run_acceptance.sh