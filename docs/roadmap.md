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

## M5.5 Pattern-Lowering Audit

Goal:
Audit the full M5 GPC-Lite pattern layer and deterministic lowering pipeline.

Files involved:
`tests/test_pattern_lowering_audit.py`, `examples/pattern_lowering_audit_demo.py`, `docs/pattern_lowering_audit.md`, `docs/architecture.md`, `docs/roadmap.md`, `docs/status.md`, `docs/decisions.md`, `scripts/run_acceptance.sh`.

Acceptance criteria:
- GPC-Lite AST validity, type checking, regex lowering, descriptor lowering, selector mapping, determinism, validation, and reference evaluation are audited.
- Unsupported full-GPC and future milestone features fail clearly.
- No M6 or later functionality is implemented.
- `python -m pytest` passes.
- `./scripts/run_acceptance.sh` passes.

Current status:
DONE

## M6 Bounded Focused Quantified Pattern Semantics

Goal:
Add a bounded QGP-inspired fragment for focus-oriented, rooted tree
patterns.

Files involved:
`src/xgap/pattern/quantified_ast.py`,
`src/xgap/pattern/quantified_typecheck.py`,
`src/xgap/pattern/quantified_lowering.py`,
`src/xgap/algebra/bindings.py`, focused binding operators in
`src/xgap/algebra/ops.py`, evaluator, validation, pretty printing,
tests, and `examples/quantified_pattern_demo.py`.

M6 extends the structured pattern layer with a bounded, QGP-inspired
fragment for focus-oriented rooted tree patterns.

The deterministic flow is:

FocusedQuantifiedPatternQuery
-> type_check_focused_quantified_pattern
-> validate_quantifier_bounds
-> lower_focused_quantified_pattern
-> LogicalPlan
-> validate_plan
-> reference evaluation

M6 supports quantifiers attached to atomic directed pattern edges:

existential: at least one distinct child match
numeric count: = k and >= k
ratio: = r and >= r
universal: ratio = 100%
negation: no child satisfies the complete branch pattern

Counting uses distinct child-node bindings. It does not count paths,
parallel edge instances, or complete binding multiplicities.

Ratio denominators contain distinct child nodes reachable through the
edge descriptor before applying the child-node descriptor and the child
subtree. Positive ratio conditions use non-vacuous semantics: an empty
denominator does not satisfy a ratio or universal condition.

Pattern-level negation is lowered through anti-semi-join semantics. It is
different from scalar boolean negation inside a local property condition.

M6 applies static structural bounds. On every root-to-leaf pattern path:

at most two quantifiers may be non-existential;
at most one edge may be negated.

Sibling quantified or negated branches are allowed because sibling
branches represent conjunction rather than nested quantification.

M6 introduces a minimal set-valued BindingRelation and a focused
binding-operator layer. This is an implementation substrate for bounded
focused patterns; it is not a full GPC assignment implementation.

M6 does not support:

full QGP
arbitrary conjunctive or cyclic graph patterns
quantifiers over Plus, Star, or other regular-path expressions
path counting
edge-instance counting
bag or null semantics
multiple query-focus outputs
unbounded quantifier nesting
backend compilation or execution
optimizer, LLM, disambiguation, or KGQA functionality

Current status:
DONE

## M6.5 Quantified-Pattern Semantic Audit

Goal:
Audit the M6 quantified-pattern semantics and lowering pipeline.

Files involved:
semantic audit document, audit tests, audit demo, current-state docs, and
acceptance wiring.

Acceptance criteria:
Confirms counting, ratio, negation, bounds, determinism, validation,
reference evaluation, and execution boundaries.

Current status:
TODO

## M7 Backend Infrastructure

Goal:
Move beyond local database bootstrapping by giving XGAP a backend
infrastructure layer for descriptors, runtime records, native smoke
clients, and experiment logs.

Files involved:
`services/docker-compose.yml`, `services/.env.example`,
`scripts/server/**`, `examples/financial_risk/**`,
`examples/datasets/financial_risk_toy.yaml`,
`descriptors/backends/**`, `src/xgap/infrastructure/**`,
`src/xgap/backends/**`, `src/xgap/experiments/**`,
`tests/test_backend_infrastructure.py`,
`tests/test_backend_live.py`, and backend documentation.

Acceptance criteria:
Neo4j and Fuseki can be started on a server; the financial-risk toy data
can be loaded into both backends; native Cypher/SPARQL smoke queries
return non-empty high-risk company rows; descriptor YAML files load;
runtime records serialize to JSON; the registry can list and filter
backends; default pytest does not require live services; optional live
smoke tests run when `XGAP_RUN_BACKENDS=1`; each harness run writes
`query_logs.jsonl` and normalized result JSON.

Current status:
DONE

## M8 Backend Capability Profile + Compiler Boundary Preflight

Goal:
Upgrade backend capabilities from descriptive metadata into
program-checkable capability profiles, and define the exact boundary
between XGAP logical plans, backend support checks, compiler inputs,
compiler outputs, and unsupported-feature reports.

M8 answers five questions:

1. Which XGAP path/GPC fragments does Neo4j support?
2. Which XGAP path/GPC fragments does Fuseki support?
3. Which M0-M6 logical constructs can be safely compiled?
4. Which constructs must explicitly return unsupported?
5. What is the format of compiler input, output, and failure reports?

Expected result:
Descriptor `capabilities` stop being purely descriptive metadata and
become capability profiles that can be checked by program logic.

Files expected:
`docs/m8_backend_capability_preflight.md`, backend descriptor schemas or
capability-profile modules, compatibility-check tests, and current-state
documentation. Existing M0-M7 APIs remain stable.

Acceptance criteria:
Neo4j and Fuseki profiles state support and unsupported reasons using
XGAP path/GPC vocabulary; M0-M6 constructs are mapped to supported,
conditionally supported, or unsupported categories; compiler artifact
boundaries are documented; unsupported constructs fail explicitly in
profile checks; no optimizer, semantic-deviation scoring, planner, LLM,
ontology reasoning, dominance pruning, top-K selection, KGQA evaluation,
or logical-plan-to-native-query compiler implementation is added.

Current status:
DONE

## M9 Minimal Compilers For Backend MVP

Goal:
Implement the first deterministic native-query compiler slice after M8:
validated ALL-selector path patterns or bounded path-algebra fragments
are checked against backend capability profiles and emitted as native
row-oriented `QueryArtifact` values.

Files involved:
`src/xgap/compilers/base.py`, `src/xgap/compilers/gql.py`,
`src/xgap/compilers/cypher.py`, `src/xgap/compilers/sparql.py`,
`src/xgap/compilers/artifacts.py`, `src/xgap/compilers/errors.py`,
`src/xgap/compilers/features.py`, compiler tests,
`examples/compiler_mvp_demo.py`, and `docs/m9_minimal_compilers.md`.

Acceptance criteria:
Cypher and SPARQL compilers support the agreed minimal path/GPC
fragment; GQL fails explicitly; M8 capability checks happen before
native artifact emission; unsupported features raise structured
failures; native output is deterministic; default pytest requires no
live backend services; acceptance passes.

Current status: DONE

## M10 LLM Planner Boundary + Structured Candidate Interface

Goal:
Define the boundary between future LLM-based natural-language planning
and XGAP's deterministic path/GPC stack.

Files involved:
`src/xgap/llm/schemas.py`, `src/xgap/llm/parser.py`,
`src/xgap/llm/protocol.py`, `src/xgap/llm/mock.py`,
`src/xgap/llm/validation.py`, `src/xgap/llm/planner.py`,
LLM-boundary tests, `examples/llm_boundary_demo.py`, and
`docs/m10_llm_planner_boundary.md`.

Acceptance criteria:
Structured candidate JSON parses deterministically into
`PathPatternQuery`; invalid JSON fails explicitly; native query fields
are rejected; `plan_from_question()` requires an explicit provider;
mock provider tests run without a live model; candidate validation can
run type checking, lowering, and plan validation; default pytest does
not require live LLM services.

Current status:
DONE

## M11 Logical Optimization and Cost Estimation

Goal:
Add logical rewrite rules and a first cost-estimation interface.

Files involved:
src/xgap/algebra/optimizer.py, cost model modules, optimizer tests.

Acceptance criteria:
Rewrites preserve semantics; unsupported rewrites are rejected; cost
features can be extracted from plans.

Current status:
TODO

## M12 LLM Provider Integration And Grounding

Goal:
Add optional concrete LLM provider integrations and grounding context
around the M10 structured candidate interface.

Files involved:
provider-specific LLM modules, environment configuration, live tests
gated by an opt-in environment variable, and grounding interfaces.

Acceptance criteria:
Provider output is schema-validated; deterministic lowering/validation
remain LLM-free; default pytest does not require live model services.

Current status: TODO

## M13 Disambiguation and Top-K Ranking

Goal:
Rank candidate interpretations under ambiguity.

Files involved:
Disambiguation modules, ranking modules, tests.

Acceptance criteria:
XGAP can score candidate interpretations, preserve top-K alternatives, and separate interpretation quality from execution cost.

Current status:
TODO

## M14 KGQA Evaluation

Goal: Add KGQA dataset loading, execution harnesses, and evaluation reporting.

Files involved: `src/xgap/datasets/kgqa.py`, evaluation scripts, dataset tests.

Acceptance criteria: Evaluation can compare generated queries or answers against KGQA benchmarks.

Current status: TODO
