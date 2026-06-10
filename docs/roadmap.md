# XGAP Roadmap

## M0 Project Skeleton

Goal: Create the Python package, documentation, examples, and tests.

Files involved: `src/xgap/**`, `docs/**`, `examples/**`, `tests/**`, `pyproject.toml`.

Acceptance criteria: Package imports work, placeholder modules exist, future behavior raises `NotImplementedError`, and pytest can discover tests.

Current status: DONE

## M1 Data Model

Goal: Implement the path-based data model and directed labeled property graph.

Files involved: `src/xgap/algebra/types.py`, `src/xgap/algebra/graph.py`, `tests/test_path_types.py`, `tests/test_graph.py`.

Acceptance criteria: `Path`, `PathSet`, `SolutionSpace`, and `PropertyGraph` satisfy the M1 behavior; graph nodes and edges convert to `PathSet`.

Current status: DONE

## M2 Core Algebra

Goal: Implement executable semantics for `Nodes(G)`, `Edges(G)`, `Selection`, `Union`, and `Join`.

Files involved: `src/xgap/algebra/conditions.py`, `src/xgap/algebra/ops.py`, `src/xgap/algebra/evaluator.py`, `tests/test_conditions.py`, `tests/test_core_ops.py`.

Acceptance criteria: Implemented operators evaluate over `PathSet`; conditions cover labels, properties, length, and boolean composition; unimplemented operators raise `NotImplementedError`.

Current status: DONE

## M2.5 Logical Plan Infrastructure

Goal: Add validation, optimizer passes, and plan formatting infrastructure.

Files involved: `src/xgap/algebra/validation.py`, `src/xgap/algebra/optimizer.py`, `src/xgap/algebra/pretty.py`.

Acceptance criteria: Plans can be validated and optimized without changing semantics; unsupported rewrites fail clearly.

Current status: DONE

## M3 Recursive Algebra

Goal: Implement `Recursive` semantics for `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, and `SHORTEST`.

Files involved: `src/xgap/algebra/ops.py`, `src/xgap/algebra/evaluator.py`, `src/xgap/algebra/types.py`, recursive tests.

Acceptance criteria: Recursive path expansion is deterministic, mode-specific, and tested.

Current status: DONE

## M4 SolutionSpace Algebra

Goal:
Implement GroupBy, OrderBy, and Projection over SolutionSpace.

Files involved:
src/xgap/algebra/types.py, src/xgap/algebra/ops.py, src/xgap/algebra/evaluator.py, src/xgap/algebra/validation.py, src/xgap/algebra/pretty.py, tests/test_solution_space.py, examples/solution_space_demo.py.

Acceptance criteria:
GroupBy transforms PathSet into SolutionSpace; OrderBy updates ranks without changing membership; Projection transforms SolutionSpace back into PathSet; selector-style plans such as ANY SHORTEST TRAIL can be represented and evaluated.

Current status:
DONE

## M4.5 Semantic Audit

Goal:
Audit the full logical algebra semantics after M4.

Files involved:
docs/operator_semantics.md, tests/**, examples/**, semantic-audit notes.

Acceptance criteria:
The implementation is checked against the path algebra paper's core, recursive, and extended semantics; selector examples are verified; empty input and tie-breaking behavior are documented; all acceptance tests pass.

Current status:
DONE

## M5 Pattern AST And Lowering

Goal:
Define structured path-pattern query objects and lower them deterministically to path-algebra logical plans.

Files involved:
`src/xgap/pattern/ast.py`, `src/xgap/pattern/types.py`, `src/xgap/pattern/typecheck.py`, `src/xgap/pattern/lowering.py`, `tests/test_pattern_typecheck.py`, `tests/test_lowering.py`, `examples/lowering_demo.py`.

Acceptance criteria:
- Regex AST supports at least `Rel`, `Seq`, `Alt`, `Plus`, and `Star`.
- Selector AST supports `ALL`, `ANY`, `ANY k`, `ANY SHORTEST`, `ALL SHORTEST`, `SHORTEST k`, and `SHORTEST k GROUP`.
- Restrictors reuse existing `PathMode` values.
- `PathPatternQuery` lowers to a valid logical operator tree.
- Lowering has no LLM dependency.
- Lowering emits only existing logical operators.
- Lowered plans pass `validate_plan`.
- Lowered plans can be evaluated by the reference evaluator.
- No compiler, backend, optimizer, or LLM logic is added.

Current status:
DONE


## M6 Backend Capability Profiles

Goal:
Represent backend capabilities separately from compiler logic.

Files involved:
Backend configuration files or schemas, capability profile tests.

Acceptance criteria:
XGAP can represent which backend supports which operators, recursive modes, filters, path return behavior, and fallback strategies.

Current status:
TODO

## M7 Compilers

Goal: Compile optimized logical plans to GQL, Cypher, and SPARQL.

Files involved: `src/xgap/compilers/base.py`, `src/xgap/compilers/gql.py`, `src/xgap/compilers/cypher.py`, `src/xgap/compilers/sparql.py`, compiler tests.

Acceptance criteria: Compilers preserve logical semantics and report unsupported features clearly.

Current status: TODO

## M8 Logical Optimization and Cost Estimation

Goal:
Add logical rewrite rules and a first cost-estimation interface.

Files involved:
src/xgap/algebra/optimizer.py, cost model modules, optimizer tests.

Acceptance criteria:
Rewrites preserve semantics; unsupported rewrites are rejected; cost features can be extracted from plans.

Current status:
TODO

## M9 LLM Planner and Grounding

Goal: Add the ambiguity-aware natural-language planner that proposes candidate path-pattern queries.

Files involved: `src/xgap/llm/schemas.py`, `src/xgap/llm/planner.py`.

Acceptance criteria: Planner output is schema-validated and deterministic lowering/validation remain LLM-free.

Current status: TODO

## M10 Disambiguation and Top-K Ranking

Goal:
Rank candidate interpretations under ambiguity.

Files involved:
Disambiguation modules, ranking modules, tests.

Acceptance criteria:
XGAP can score candidate interpretations, preserve top-K alternatives, and separate interpretation quality from execution cost.

Current status:
TODO

## M11 KGQA Evaluation

Goal: Add KGQA dataset loading, execution harnesses, and evaluation reporting.

Files involved: `src/xgap/datasets/kgqa.py`, evaluation scripts, dataset tests.

Acceptance criteria: Evaluation can compare generated queries or answers against KGQA benchmarks.

Current status: TODO
