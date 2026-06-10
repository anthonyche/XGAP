# Sprint: <MILESTONE NAME>

## Goal

Make XGAP logical plans inspectable, printable, and validatable before implementing RecursiveOp.

## Required preflight

Before implementation:

1. Read AGENTS.md.
2. Read docs/architecture.md.
3. Read docs/roadmap.md.
4. Read docs/status.md.
5. Read docs/operator_semantics.md.
6. Inspect relevant src/ and tests/.

Then report:
- current milestone
- files you expect to modify
- files you will not modify
- acceptance criteria

## Allowed changes

You may modify:

- src/xgap/algebra/ops.py
- src/xgap/algebra/pretty.py
- src/xgap/algebra/validation.py
- tests/test_ops_metadata.py
- tests/test_pretty.py
- tests/test_validation.py
- examples/plan_print_demo.py
- docs/status.md

## Forbidden changes

Do not implement RecursiveOp evaluator semantics.
Do not implement GroupBy, OrderBy, or Projection evaluator semantics.
Do not implement pattern lowering.
Do not implement compilers.
Do not add LLM logic.
Do not rename existing implemented operators.
Do not remove existing tests.

## Implementation requirements

1. Add OutputKind enum:
   - PATH_SET
   - SOLUTION_SPACE

2. Add methods to AlgebraOp:
   - output_kind(self) -> OutputKind
   - children(self) -> tuple[AlgebraOp, ...]
   - operator_name(self) -> str

3. Implement metadata for current operators:
   - NodesOp: PATH_SET, no children, "Nodes"
   - EdgesOp: PATH_SET, no children, "Edges"
   - SelectionOp: PATH_SET, one child, "Selection"
   - UnionOp: PATH_SET, two children, "Union"
   - JoinOp: PATH_SET, two children, "Join"

4. Implement format_plan(op):
   - stable textual tree
   - include condition text for SelectionOp

5. Implement validate_plan(op):
   - NodesOp and EdgesOp are valid.
   - SelectionOp child must output PATH_SET.
   - UnionOp children must both output PATH_SET.
   - JoinOp children must both output PATH_SET.
   - recursively validate children.

6. Add examples/plan_print_demo.py:
   - builds a sample plan
   - prints the plan
   - validates the plan
   - evaluates the plan


## Tests

Add or update:

- tests/test_ops_metadata.py
- tests/test_pretty.py
- tests/test_validation.py


Run:


```bash
python -m pytest
python examples/core_algebra_demo.py
python examples/plan_print_demo.py