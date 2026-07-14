# XGAP Status

## Current Milestone

M9 Minimal Compilers For Backend MVP is completed.

## Completed

- M0 Project Skeleton
- M1 Data Model
- M2 Core Algebra
- M2.5 Logical Plan Infrastructure
- M3 Recursive Algebra
- M4 SolutionSpace Algebra
- M4.5 Semantic Audit
- M5 GPC-Lite Pattern AST And Lowering
- M5.5 Pattern-Lowering Audit
- M6 Bounded Focused Quantified Pattern Semantics
- M7 Backend Infrastructure
- M8 Backend Capability Profile + Compiler Boundary Preflight
- M9 Minimal Compilers For Backend MVP

## In Progress

None.

## Next Planned Milestone:
M10 Logical Optimization and Cost Estimation.

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

FocusedQuantifiedPatternQuery
  -> type_check_focused_quantified_pattern
  -> validate_quantifier_bounds
  -> deterministic lowering
  -> LogicalPlan

## Implemented M6 Binding Layer

- `BindingRelation`
- `BindNode`
- `BindEdge`
- `BindingJoin`
- `BindingProject`
- `QuantifiedCheck`
- `AntiSemiJoin`
- `FocusProjection`

M6 supports bounded, focused, rooted-tree quantified patterns with
non-injective set-valued bindings, distinct child-node counting, exact
ratio thresholds, non-vacuous ratio and universal semantics, anti-semi-
join `NONE`, focus-only queries, deterministic lowering, static schema
inference, plan validation, pretty printing, and reference evaluation.

M6 remains QGP-inspired only. It is not full QGP, not full GPC, and not
backend support.

## Not Implemented Yet
- Full GQL / Cypher / SPARQL compiler coverage
- GQL compiler support
- Recursive, selector, and M6 quantified-pattern backend compilation
- Logical optimization
- Learned cost estimator
- LLM planner
- Disambiguation
- KGQA evaluation

## M7 Backend Infrastructure

M7 Backend Infrastructure is completed.

Server-side Docker Compose scaffolding exists for starting local Neo4j
and Apache Jena Fuseki services on a lab machine, plus a minimal
financial-risk toy dataset and smoke-query scripts.

The server scripts default to the current repository checkout instead of
creating a fixed `/xgap-lab` directory. Operators can still override
`XGAP_REPO_ROOT` explicitly when needed.

When a user cannot access the Docker daemon socket directly, the server
scripts automatically fall back to `sudo docker`.

Backend healthcheck uses Neo4j `cypher-shell` readiness over Bolt
instead of requiring the Neo4j HTTP browser endpoint to respond first.

This is runtime environment setup only. It is not a compiler, planner,
semantic-deviation layer, ontology-reasoning feature, LLM feature, or
KGQA evaluation harness.

Earlier backend-environment scaffold verification, before the full M7
infrastructure layer:

- `bash -n scripts/server/*.sh`: passed.
- `docker compose --env-file services/.env.example -f services/docker-compose.yml config`:
  not available in the local development environment because the Docker
  CLI is not installed here.

Full M7 verification is recorded below.

## M7 Backend Infrastructure Protocol And Experiment Harness

XGAP now has JSON-serializable backend infrastructure records and a
minimal native-query execution harness:

- backend descriptors under `descriptors/backends/` for
  `reference_evaluator`, `neo4j`, and `fuseki`;
- `BackendDescriptor`, `BackendStatus`, `DatasetSpec`, `QueryArtifact`,
  `ExecutionReport`, and `RunRecord`;
- a descriptor registry with load, get, list, and language-filter
  helpers;
- a minimal `BackendClient` protocol with `healthcheck()` and
  `execute(QueryArtifact)`;
- native Neo4j Cypher and Fuseki SPARQL clients implemented with the
  Python standard library rather than backend driver dependencies;
- `examples/datasets/financial_risk_toy.yaml`;
- `xgap.experiments.backend_smoke`, which executes native smoke query
  files and writes `query_logs.jsonl` plus normalized result JSON under
  `runs/<run_id>/`.

This layer executes already-authored native Cypher/SPARQL smoke queries
only. It does not compile XGAP logical plans, does not implement
semantic-deviation scoring, ontology reasoning, bounded planning,
dominance pruning, top-K selection, LLM candidate generation, KGQA
evaluation, or logical-plan-to-native-query compilation.

Default pytest skips live backend execution unless `XGAP_RUN_BACKENDS=1`
is set.

Latest backend-infrastructure verification:

- `python -m pytest tests/test_backend_infrastructure.py tests/test_backend_live.py`:
  7 passed, 2 skipped.
- `python -m pytest`: 241 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, and `examples/quantified_pattern_demo.py`.
- Server live backend test:
  `PYTHONPATH=src XGAP_RUN_BACKENDS=1 python -m pytest tests/test_backend_live.py`:
  2 passed.

## M8 Backend Capability Profile + Compiler Boundary Preflight

M8 is completed.

M8 is not a database bootstrapping milestone. It assumes the M7 backend
services and native smoke harness are available.

M8 answers five questions:

1. Which XGAP path/GPC fragments does Neo4j support?
2. Which XGAP path/GPC fragments does Fuseki support?
3. Which M0-M6 logical constructs can be safely compiled?
4. Which constructs must explicitly return unsupported?
5. What is the format of compiler input, output, and failure reports?

Descriptor `capabilities` now include program-checkable capability
profiles for `reference_evaluator`, `neo4j`, and `fuseki`.

Implemented M8 objects:

- `SupportLevel`
- `SupportReason`
- `FeatureSupport`
- `BackendCapabilityProfile`
- `CompatibilityReport`
- `UnsupportedFeature`
- `CompilerInputSpec`
- `CompilerOutputSpec`
- `CompilerFailureSpec`

Implemented M8 compatibility helpers:

- `check_backend_support(profile, feature_request)`
- `check_backend_features(profile, feature_requests)`

The compatibility checker is static. It does not compile logical plans,
call backend clients, call the reference evaluator, run optimizer code,
or invoke planner, LLM, ontology, cost, or evaluation code.

M8 remains a preflight and boundary-definition milestone. It must not
implement optimizer algorithms, semantic-deviation scoring, ontology
reasoning, bounded planning, dominance pruning, top-K selection, LLM
candidate generation, KGQA evaluation, or logical-plan-to-native-query
compilation.

Latest M8 verification:

- `python -m pytest tests/test_backend_capabilities.py tests/test_backend_compatibility.py`:
  13 passed.
- `python -m pytest tests/test_backend_infrastructure.py tests/test_backend_live.py`:
  7 passed, 2 skipped.
- `python -m pytest`: 254 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, and `examples/quantified_pattern_demo.py`.

See `docs/m8_backend_capability_preflight.md`.

## M9 Minimal Compilers For Backend MVP

M9 is completed.

XGAP now has the first deterministic native-query compiler slice after
M8 capability preflight.

Implemented M9 compiler boundary:

- `compile_cypher(...)` returns a compiled Cypher `QueryArtifact` for
  Neo4j.
- `compile_sparql(...)` returns a compiled SPARQL `QueryArtifact` for
  Fuseki.
- `compile_gql(...)` remains an explicit unsupported boundary and
  raises `UnsupportedCompilationError`.
- Compiler failures carry `CompilerFailureSpec` records with backend,
  language, unsupported feature, support level, reason, and metadata.

Supported M9 fragment:

- `Nodes(G)`;
- `Edges(G)`;
- `Selection`;
- path-chain `Join`;
- fixed-length `OUT` path fragments;
- node-label and edge-label predicates;
- scalar property equality and numeric comparisons already represented
  by XGAP conditions;
- `PathPatternQuery` only for selector `ALL`.

M9 compiler outputs are row-oriented native artifacts. They do not claim
native XGAP `PathSet` object preservation.

M9 explicitly rejects:

- `Union`;
- `Recursive`;
- `GroupBy`;
- `OrderBy`;
- selector-style `Projection`;
- M6 focused binding operators;
- `FocusedQuantifiedPatternQuery`;
- `PathPatternQuery` selectors other than `ALL`;
- reverse or undirected edge lowering;
- unsupported regex placeholders;
- boolean `OR` and `NOT` conditions;
- path-length conditions;
- GQL compilation.

M9 does not implement optimizer rules, cost estimation, semantic-
deviation scoring, ontology reasoning, bounded planning, dominance
pruning, top-K selection, LLM candidate generation, natural-language
planning, or KGQA evaluation.

Latest M9 verification:

- `python -m pytest tests/test_compiler_boundaries.py tests/test_cypher_compiler.py tests/test_sparql_compiler.py`:
  11 passed.
- `python examples/compiler_mvp_demo.py`: passed.
- `python -m pytest`: 265 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  and `examples/compiler_mvp_demo.py`.

See `docs/m9_minimal_compilers.md`.

## Required Acceptance Command
./scripts/run_acceptance.sh

# Latest Known Acceptance Status

M0-M9 acceptance passed locally and M7 live backend smoke tests passed
on the server.

Latest recorded command results:

- `python -m pytest`: 265 passed, 2 skipped.
- `python examples/quantified_pattern_demo.py`: passed.
- `python examples/compiler_mvp_demo.py`: passed.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  and `examples/compiler_mvp_demo.py`.

Expected checks include:

- harness check
- pytest
- examples/core_algebra_demo.py
- examples/plan_print_demo.py
- examples/recursive_demo.py
- examples/solution_space_demo.py
- examples/semantic_audit_demo.py
- examples/lowering_demo.py
- examples/pattern_lowering_audit_demo.py
- examples/quantified_pattern_demo.py
- lowering tests
- pattern-lowering audit tests
- quantified-pattern tests
- M9 compiler tests
