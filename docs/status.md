# XGAP Status

## Current Milestone

Backend Infrastructure Protocol And Experiment Harness is completed.

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
- Backend Environment Scaffold
- Backend Infrastructure Protocol And Experiment Harness

## In Progress

None.

## Next Planned Milestone:
Backend capability-profile and compiler-boundary preflight, unless the
M6.5 semantic audit is resumed first.

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
- Full backend capability profiles
- GQL / Cypher / SPARQL compilers
- Logical optimization
- Learned cost estimator
- LLM planner
- Disambiguation
- KGQA evaluation

## Backend Environment Scaffold

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

Latest backend-environment scaffold verification:

- `bash -n scripts/server/*.sh`: passed.
- `python -m pytest`: 234 passed.
- `docker compose --env-file services/.env.example -f services/docker-compose.yml config`:
  not available in the local development environment because the Docker
  CLI is not installed here.

## Backend Infrastructure Protocol And Experiment Harness

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

## Required Acceptance Command
./scripts/run_acceptance.sh

# Latest Known Acceptance Status

M0-M6 plus backend infrastructure acceptance passed locally.

Latest recorded command results:

- `python -m pytest`: 241 passed, 2 skipped.
- `python examples/quantified_pattern_demo.py`: passed.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, and `examples/quantified_pattern_demo.py`.

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
