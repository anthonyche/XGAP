# XGAP Status

## Current Milestone

M12-D Baselines/Ablations + Server Experiment Runner is completed.
Post-M12-D paper-environment hardening is completed without opening a new
algorithm milestone.

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
- M10 LLM Planner Boundary + Structured Candidate Interface
- M11 Ontology-Bounded Physical Planning
- M12-A Experiment Artifact Contract + Dataset Bundle
- M12-B Live LLM + Ontology/Alignment Artifacts
- M12-C Cost Calibration + Online GP Protocol
- M12-D Baselines/Ablations + Server Experiment Runner

## In Progress

- None

## Next Planned Milestone

M12 experimentalization is complete. The next research/data milestone is not
started; the roadmap currently names M13 automated semantic disambiguation.

## M12 Experimentalization

Current phase status:

- M12-A Experiment Artifact Contract + Dataset Bundle: Completed
- M12-B Live LLM + Ontology/Alignment Artifacts: Completed
- M12-C Cost Calibration + Online GP Protocol: Completed
- M12-D Baselines/Ablations + Server Experiment Runner: Completed

M12-A freezes experiment-facing semantics and artifact contracts. It does not
claim, by itself, live model access, production ontology reasoning/alignment,
KGQA execution, a final financial-risk benchmark, or final SIGMOD
experimental results. M12-B through M12-D add bounded live inputs, real-cost
calibration, and reproducible orchestration while preserving that separation.

See `docs/m12_experimentalization.md`.

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
- Logical rewrite optimization
- Paper-scale calibrated observations beyond the controlled development workload
- Production ontology/schema, stronger retrieval, and automated reasoning
- Distributed cross-backend execution
- Provider-specific production hardening beyond the generic OpenAI-compatible boundary
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

## M10 LLM Planner Boundary + Structured Candidate Interface

M10 is completed.

XGAP now has a structured LLM boundary without connecting any live model
provider.

Implemented M10 objects and helpers:

- `PlannerRequest`
- `PlannerCandidate`
- `PlannerResponse`
- `CandidateValidationReport`
- `StructuredCandidateProvider`
- `MockStructuredCandidateProvider`
- `PlannerSchemaError`
- `parse_path_pattern_query(...)`
- `parse_planner_response(...)`
- `path_pattern_query_to_dict(...)`
- `plan_from_question(...)`
- `plan_response_from_question(...)`
- `validate_candidate(...)`

M10 accepts only controlled JSON that parses into existing
`PathPatternQuery` objects. It rejects native query fields such as
`cypher`, `sparql`, `gql`, `native_query`, and `query_text`.

`plan_from_question()` has no default live provider in M10. Callers must
pass an explicit provider, and the included mock provider is for tests
and local demos only.

Candidate validation is deterministic:

PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> validate_plan

M10 does not implement Qwen/OpenAI/DashScope/vLLM clients, LoRA,
prompt optimization, semantic-deviation scoring, ontology reasoning,
logical optimization, bounded planning, dominance pruning, top-K
selection, KGQA evaluation, native query generation by an LLM, or live
model tests.

Latest M10 verification:

- `python -m pytest tests/test_llm_boundary.py`: 7 passed.
- `python examples/llm_boundary_demo.py`: passed.
- `python -m pytest`: 272 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  `examples/compiler_mvp_demo.py`, and `examples/llm_boundary_demo.py`.

See `docs/m10_llm_planner_boundary.md`.

## M11 Ontology-Bounded Physical Planning

M11 is completed in four sequential phases:

- M11-A Planning Objective and Physical-State Contract
- M11-B Bounded Branch-and-Bound Physical Search
- M11-C Bayesian Cost Model and Search Trace
- M11-D XGAP Main Planner and Exhaustive Oracle Evaluation

The logical plan for an interpretation remains the deterministic output of
the existing M5/M10 pipeline. M11 does not enumerate logical rewrites. Its
search variables are backend placement and explicit cross-backend exchange
decisions for that fixed logical plan.

Ontology/schema definitions, source-to-ontology mappings, aliases, alignment
evidence, and semantic-deviation inputs are external, versioned,
replaceable planning artifacts. Missing, unknown, unsupported, or
insufficient mapping evidence is not treated as success. Bounded physical
search neither invents nor enumerates ontology mappings.

The M11 planning contract uses a strict execution threshold: a plan is
returnable only when its conservative upper estimate satisfies
`C_bar < T_max`. No threshold relaxation or fallback outside that bound is
allowed. Each interpretation contributes at most one discovered physical
representative, chosen by minimum conservative upper estimate within the
search budget. Final deterministic top-K ranking uses the Nash score only
when semantic and execution utilities are both strictly positive.

M11 explicitly excludes live LLM providers, KGQA dataset integration,
LoRA/model training, automatic ontology induction, a built-in OWL/DL
reasoner, full GQL, new M9 compiler coverage, logical rewrite search, new
backend engines, and distributed cross-backend execution.

Implemented M11-A contracts and interfaces:

- deterministic frozen physical-state, placement, exchange, realization,
  plan, objective, cost, feature, observation, trace, and configuration
  records;
- stable logical-operator and dependency identifiers derived from existing
  plan structure;
- `OntologyAlignmentProvider`, `SemanticDeviationScorer`, `CostEstimator`,
  `StateFeatureExtractor`, `BudgetPolicy`, and `PhysicalCompiler` protocols;
- controlled `ArtifactOntologyAlignmentProvider` and
  `ProvidedSemanticDeviationScorer` boundaries.

Implemented M11-B physical search:

- deterministic child-before-parent placement order;
- configured exchange strategies with automatic single-strategy resolution,
  branching only for explicitly supplied alternatives, and explicit
  infeasibility when none exists;
- lower-bound priority queue, one budget unit per processed `ExtractMin`,
  strict incumbent replacement by lower conservative upper cost, successor
  pruning, early bound termination, and anytime-prefix records.

Implemented M11-C cost and trace layer:

- positive complete-plan log-cost observations in a versioned append-only
  JSONL store;
- deterministic features with explicit missing-value flags;
- an immutable RBF Gaussian-process snapshot in log-cost space;
- finite combinatorial state-space bounds, per-interpretation and across-task
  confidence utilities, positive raw-cost bounds, and deterministic JSONL
  traces.

The repository has no NumPy, SciPy, or scikit-learn dependency. The M11 GP is
therefore a deliberately small standard-library implementation using a
jittered Cholesky factorization, isolated from the algebra core and tested on
controlled small planning datasets.

Implemented M11-D composition and experiments:

- M10 structured candidates through versioned alignment, supplied semantic
  deviation, deterministic lowering, bounded physical search, strict
  `C_bar < T_max`, one representative per interpretation, positive-utility
  Nash ranking, and deterministic top K;
- an adapter to existing M9 compilers or structured unsupported boundaries;
- `python -m xgap.experiments.physical_planner --config <path>` and complete
  `runs/<run_id>/` planner artifacts;
- a test/experiment-only tiny exhaustive oracle with true-cost regret,
  reachable/processed/generated/pruned metrics, pruning and reduction
  measures, budget-quality curves, and the `eta_search + eta_select`
  decomposition.

Controlled M11 inputs are:

- `examples/configs/m11_candidates.json`;
- `examples/configs/m11_alignment.json`;
- `examples/configs/m11_controlled_planner.json`.

These are deterministic fixtures, not a production ontology, automated
alignment system, ontology reasoner, live model, or benchmark dataset.

The current deterministic `PathPatternQuery` lowering preserves selector
`GroupBy`/`Projection` operators. Neo4j and Fuseki profiles correctly reject
those complete logical plans under current M8/M9 coverage, so the controlled
end-to-end M11 demo selects the reference evaluator. M11 does not bypass the
logical plan by compiling the original pattern directly and does not expand
M9 selector coverage. Direct logical fragments already within M9 remain
compilable through the adapter.

Latest M11 verification:

- `python -m pytest tests/test_m11_contracts.py tests/test_m11_search.py tests/test_m11_cost.py tests/test_m11_planner.py tests/test_m11_oracle.py tests/test_m11_runner.py tests/test_m11_compiler_adapter.py -q`:
  26 passed.
- `python examples/m11_physical_planner_demo.py`: passed; 2 selected plans,
  both with conservative upper estimate `6.289246`.
- `python examples/m11_exhaustive_oracle_demo.py`: passed; 3 reachable states,
  3 processed states, oracle and BnB true cost `2.0`, log-cost regret `0.0`.
- `python -m pytest`: 298 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check, full pytest,
  all M0-M10 examples, and both M11 demos.

See `docs/m11_ontology_bounded_physical_planning.md`.

## M12-A Experiment Artifact Contract + Dataset Bundle

M12-A is completed. It freezes and implements the experiment-facing
contracts around the existing M10/M11 deterministic pipeline without
changing M11 planning behavior.

Implemented M12-A artifacts and APIs:

- stable SHA-256 canonical hashing that excludes resolved local bundle roots;
- `DatasetBundle`, normalized question/entity/alignment/schema records, and
  the four-way fragment-support taxonomy;
- validated ontology graphs with positive `H`, directed shortest-hop
  subsumption distance, and explicit admissible sibling pairs;
- directional semantic deviation with fixed multipliers `0`, `1/3`, `2/3`,
  and `1`, uniform slot aggregation, and symbolic `infinity` for missing,
  incomplete, unrelated, or inadmissible evidence;
- the default epsilon sweep `{0, 0.1, 0.25, 0.5, 0.75, 1.0}` with config
  override support;
- `ModelBundle` and prompt contracts plus an offline M10 mock response
  bundle, with no live model endpoint;
- `ExperimentSpec`, GP/calibration and M11 feature-schema references,
  execution protocol, explicit artifact availability, baseline IDs,
  ablation switches, and grouped nullable metric records;
- frozen run layout and traceable manifest with explicit unavailable
  CUDA/GPU/Docker/backend-version fields;
- `python -m xgap.experiments.run --config <path>` for the controlled
  `full_xgap` development path only.

The frozen GP experiment protocol retains the M11 RBF GP and
`log_execution_cost` target. Future calibration samples complete physical
plans into `D_0`, fits hyperparameters once on `D_0`, freezes those
hyperparameters during evaluation, and permits posterior updates only
between tasks. M12-A serializes and validates this protocol; it does not
collect real observations or perform server calibration.

The controlled development bundle at `datasets/financial_risk_dev/` contains
20 explicitly synthetic cases spanning exact, specialization,
generalization, explicit sibling, inadmissible/missing/incomplete mapping,
fixed path, filter, compiler/representation gaps, multiple interpretations,
and placement alternatives. It reuses the existing native financial-risk
load artifacts. It is not the final paper benchmark.

The formal development run used two currently representable OUT-path cases
and three controlled candidates. It produced 27 files under
`runs/m12-financial-risk-xgap-dev/`, including logical and physical plans,
search traces, reference logical query artifacts, manifests, and explicit
`not_available` backend-result records. Both questions completed
successfully. No backend execution is claimed.

Frozen baseline IDs:

`full_xgap`, `random_feasible`, `mean_only`, `no_pruning`,
`no_online_update`, `single_backend`, `exhaustive_oracle`, and
`direct_text2graphquery`.

Frozen ablation switches:

`no_uncertainty`, `no_pruning`, `no_online_learning`, `no_semantic_bound`,
`cost_only`, and `no_nash`.

M12-A executes only the controlled `full_xgap` development path. M12-D
subsequently adds executable baseline and ablation policies around the frozen
pipeline.

Latest M12-A verification:

- `PYTHONPATH=src python -m pytest tests/test_m12_semantic.py tests/test_m12_contracts.py tests/test_m12_runner.py -q`: 15 passed.
- `python examples/m12_experiment_contract_demo.py`: passed; 2/2 questions
  succeeded and 27 artifact files were produced in the temporary run.
- `PYTHONPATH=src python -m xgap.experiments.run --config experiments/configs/financial_risk_xgap_dev.json`: passed; 2/2 questions succeeded and
  the frozen run tree was produced.
- `python -m pytest`: 313 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including the harness, full pytest,
  all previous examples, both M11 demos, and the M12-A demo.

M12-B subsequently replaces the controlled inference inputs with the bounded
live/runtime path described below. M12-C subsequently implements real-backend
D0 collection capability and the online posterior lifecycle. M12-D now
provides executable baselines, ablations, and server orchestration.

See `docs/m12_experimentalization.md`.

## M12-B Live LLM + Ontology/Alignment Artifacts

M12-B is completed. The same configuration-driven M12 runner now selects
either the existing M12-A mock path or a live structured provider path from
`ExperimentSpec` and `ModelBundle`; the M11 physical planner is unchanged.

Implemented M12-B boundaries:

- a generic `OpenAICompatibleStructuredCandidateProvider` implementing the
  existing M10 `StructuredCandidateProvider` protocol;
- one generation call and at most one schema/syntax repair call, with exact
  generation/repair counts and exact sanitized assembled requests in run
  artifacts;
- a fixed DashScope ModelBundle for `qwen3-max-2026-01-23` and a portable
  configuration-only vLLM OpenAI-compatible template;
- deterministic bounded lexical/alias retrieval over the versioned ontology,
  entity catalog, source schema snapshot, and backend mappings;
- per-question `PromptSchemaView`, explicit query anchors, separate candidate
  slot realizations, prompt-visible ID validation, full slot-coverage checks,
  real kind-compatible pattern-component validation, and explicit
  missing-mapping failures;
- `FileBackedRuntimeAlignmentProvider`, which creates real runtime inputs for
  the frozen M12-A directional ontology-hop `c_sem` implementation without
  using benchmark gold artifacts;
- live invocation, exact sanitized assembled requests, usage, prompt-view,
  query-slot, grounding, alignment, diagnostics, and optional live-generation
  metrics artifacts;
- stable failure categories for provider, parsing, repair, grounding,
  mapping, semantic, representation, and compiler boundaries.

The anti-leakage boundary excludes gold answers, gold logical forms, gold
alignments, and evaluation labels from runtime retrieval, prompts, model
requests, candidate validation, semantic deviation, and M11 planning. The
runtime artifact loader has no gold-bearing DatasetBundle reference after
construction. Gold remains available only to a future explicit evaluation
path.

The financial-risk ontology remains a controlled development artifact. The
retriever is deterministic lexical/alias retrieval, not a full OWL/DL
reasoner. The live provider emits grounded `PathPatternQuery` JSON only;
native Cypher, SPARQL, or GQL remains deterministic compiler output.

The M12-B end-to-end audit is recorded in
`docs/report/m12b_llm_boundary_audit.md`. Its final verdict is PASS after the
required fixes and a credentialed post-fix smoke. The fixes persist
`llm_requests.jsonl`, reject empty semantic context, validate typed
`component_ref` attachments, and clarify the zero-shot semantic contract and
interpretation diversity. They do not change M11, `c_sem`, PathPatternQuery
semantics, or downstream planning.

M12-B itself does not implement model training, LoRA, model deployment, real
D0 collection, GP calibration, online posterior updates, executable
baselines, ablation matrices, KGQA evaluation, or server-scale orchestration.
M12-C and M12-D subsequently add calibration/lifecycle and experiment
orchestration; model training, deployment, and KGQA remain later work.

Latest M12-B verification:

- `python -m pytest tests/test_m12b_provider.py tests/test_m12b_runtime_alignment.py tests/test_m12b_runner.py tests/test_m12b_live.py -q`:
  23 passed, 1 skipped;
- `python -m pytest tests/test_llm_boundary.py tests/test_m12_contracts.py tests/test_m12_runner.py tests/test_m12_semantic.py tests/test_m12b_provider.py tests/test_m12b_runtime_alignment.py tests/test_m12b_runner.py tests/test_m12b_live.py -q`:
  45 passed, 1 skipped;
- `python -m pytest -q`: 336 passed, 3 skipped;
- the skipped M12-B test is the real DashScope smoke test, gated by both
  `XGAP_RUN_LIVE_LLM=1` and `DASHSCOPE_API_KEY`;
- credentialed post-fix command
  `XGAP_RUN_LIVE_LLM=1 PYTHONPATH=src python -m pytest tests/test_m12b_live.py -v`:
  1 passed in 33.64 seconds;
- the post-fix run made one generation call and no repair call, persisted an
  exact `llm_requests.jsonl` payload whose hash matches the invocation, and
  produced one fully validated logical/physical candidate;
- the fake-HTTP integration exercised the real OpenAI-compatible provider,
  runtime grounding, frozen `c_sem`, unchanged M11 planner, and live artifact
  layout without network access;
- the M12-A mock runner regression planned 2/2 questions successfully;
- `./scripts/run_acceptance.sh`: passed with 336 tests passed, 3 gated live
  tests skipped, and all existing examples successful.

## M12-C Cost Calibration + Online GP Protocol

M12-C is completed. It adds a separate, server-friendly calibration path and
does not modify `PathPatternQuery`, logical lowering, M11 BnB, `c_sem`, the
Nash objective, or the frozen M12-B model/alignment boundary.

Implemented M12-C boundaries:

- typed calibration config, case, workload, plan, measurement, D0, calibrated
  model, posterior snapshot, and posterior-update artifacts;
- deterministic stratified selection of complete plans from a dedicated
  calibration split;
- M9 compilation followed by repeated execution through the existing Neo4j
  and Fuseki clients, including support for M9 `compiled` native artifacts;
- raw millisecond and `log(execution_ms)` persistence with all warmup and
  measured repetitions retained;
- separate `D0_neo4j` and `D0_fuseki` datasets with no cross-backend
  observation mixing;
- deterministic negative-log-marginal-likelihood calibration of the existing
  RBF GP family, with repeated-run noise evidence and a positive noise floor;
- persisted config, protocol, descriptor, feature-schema, D0, model, and
  hyperparameter hashes;
- immutable `BackendCostModelRegistry` snapshots that expose calibrated
  estimators through the existing M11 `CostEstimator` interface;
- `OnlinePosteriorLifecycle`, which gives task q one fixed `D_(q-1)` snapshot
  and atomically appends only successful executed complete-plan observations
  after the whole task batch finishes;
- backend-isolated updates, batch IDs and K_q records, temporal anti-leakage
  checks, persisted execution evidence, and unchanged hyperparameter hashes;
- explicit unavailable handling for unsupported distributed cross-backend
  movement measurement;
- a two-plan financial-risk development workload, a dual-backend calibration
  config, an offline deterministic demo, and an optional gated live smoke.

The local offline development run created two D0 records per backend and two
independently calibrated model artifacts. It demonstrated that the calibrated
posterior differs from the development prior for at least one state. These are
explicit fake development latencies and are not claimed as real Neo4j/Fuseki
calibration results.

Real server command:

```bash
XGAP_RUN_BACKENDS=1 PYTHONPATH=src \
python -m xgap.experiments.calibrate \
  --config experiments/configs/financial_risk_gp_calibration_dev.json
```

Optional live pytest additionally requires `XGAP_RUN_CALIBRATION=1`. Default
pytest remains fully offline.

M12-C does not add a joint backend-aware GP, cross-backend movement-cost
learning, distributed runtime orchestration, new compiler coverage, baseline
or ablation execution, matrix scheduling, new benchmarks, semantic-deviation
changes, ontology reasoning, or new LLM behavior. M12-D subsequently adds
baseline/ablation execution and matrix scheduling without adding the other
features.

Latest M12-C verification:

- `PYTHONPATH=src python -m pytest tests/test_m12c_calibration.py tests/test_m12c_live.py -q`:
  9 passed, 1 live calibration test skipped;
- the M11/M12-A/M12-B focused regression suite: 57 passed, 1 gated live LLM
  test skipped;
- `PYTHONPATH=src python examples/m12c_calibration_demo.py`: passed, with 2
  explicit fake D0 records and one calibrated model per backend;
- `python -m pytest`: 345 passed, 4 gated live tests skipped;
- `./scripts/run_acceptance.sh`: passed, including the harness, full pytest,
  all historical examples, and the M12-C offline calibration demo.

The real M12-C backend calibration was run separately on the server after both
native smoke queries returned nonempty results. The two backend live tests and
the live calibration test reported `3 passed in 2.11s`; calibration reported
`measurement_source=real_backend` and D0 observation count 2 for each of
Neo4j and Fuseki. These are development acceptance observations, not final
paper calibration data.

## M12-D Baselines/Ablations + Server Experiment Runner

M12-D is completed. It composes the frozen M10-M12-C boundaries into a
declarative, resumable experiment system without changing logical semantics,
`c_sem`, M11's default BnB/Nash behavior, or GP formulas.

Implemented M12-D boundaries:

- explicit policies for `full_xgap`, seeded `random_feasible`, `mean_only`,
  `no_pruning`, `no_online_update`, configured `single_backend`, controlled
  bounded `exhaustive_oracle`, and separate `direct_text2graphquery`;
- real behavior for `no_uncertainty`, `no_pruning`, `no_online_learning`,
  `no_semantic_bound`, `cost_only`, and configured `no_nash` ablations, with
  contradictory combinations rejected;
- immutable candidate/grounding artifacts shared across comparable planning
  methods, with prompt/model/grounding/artifact hashes and exact live request
  evidence where available;
- an online task runner that snapshots `D_(q-1)`, fixes it for all planning
  decisions in task q, executes selected complete plans, then atomically
  commits K_q observations to produce D_q;
- deterministic matrix expansion and run IDs, completed-run skipping,
  explicit resume/retry, per-task recovery records, collision checks, and a
  bounded 12-run financial-risk development matrix;
- normalized execution cardinality and separate
  `execution_success_nonempty`, `execution_success_empty`, and
  `execution_error` statuses;
- calibration-query cardinality diagnostics with explicit expected-nonempty
  cases, relevant mapped IRIs, and separate empty-success handling;
- method-aware search traces, cost prediction/confidence observations,
  separated latency/result/failure metrics, and JSON/CSV aggregation;
- development/pilot/paper modes, environment capture, readiness checks, and a
  paper freeze manifest. Paper mode supports Python 3.10+ and requires pinned,
  identified backend versions/images plus a passing RDF mapping/data/compiler
  contract. Exact runtime and image identity remain recorded per run.

Offline completion verifies the runner lifecycle and D0 -> D1 -> D2
transition using deterministic fake backend timings. The real M12-D online
D0 -> D1 -> D2 pilot remains a separately gated server command and is not
claimed by local completion.

M12 completion means experiment infrastructure is ready for paper-grade
dataset/model artifact preparation and large-scale runs. It does not mean
final datasets or paper numbers exist, MetaQA/QALD are integrated,
cross-backend distributed execution or transfer-cost learning exists, or new
compiler fragments are supported.

## Post-M12-D Paper-Environment Hardening

This completed hardening pass did not change `PathPatternQuery`, logical
algebra, `c_sem`, M11 search/ranking, GP formulas, prompt/schema contracts,
baselines, or M12-D experiment semantics.

- package metadata, paper readiness, and the online paper gate now support
  Python 3.10+; the dependency and 3.10 syntax/API audit found no blocker;
- paper backend startup uses `services/.env.paper` and requires current
  validated `repository@sha256:<digest>` image references, while development
  floating tags remain warning-only;
- environment manifests record repository, tag, digest, local image ID and
  RepoDigests when visible, plus backend-reported software version where
  available;
- the DatasetBundle backend mapping is now the sole source for M9 SPARQL RDF
  IRIs; missing or invalid mappings fail explicitly;
- the financial-risk RDF bundle retains reified Transfer records and adds the
  mapped direct `transfersTo` predicate needed by the existing bounded M9 path
  fragment;
- `python -m xgap.experiments.backend_mapping_audit` verifies
  `URI_data == URI_mapping == URI_m9`, and readiness fails on any unresolved
  mismatch;
- readiness also rejects paper use of Fuseki calibration artifacts whose
  query mapping hash is absent or differs from the active DatasetBundle, so
  pre-hardening D0 must be regenerated after the updated data is loaded;
- configured expected-nonempty live calibration cases assert positive Fuseki
  row counts; arbitrary empty results remain valid successful executions.

## Required Acceptance Command

```bash
./scripts/run_acceptance.sh
```

# Latest Known Acceptance Status

M0-M12-D acceptance passed locally. M7 backend smoke and M12-C real
calibration acceptance passed on the server. A real DashScope M12-B
development run completed one question with one generation call, no repair,
and three candidates; its credentialed post-fix rerun verified the revised
prompt, typed grounding, and exact-request artifact. M12-D live online and
direct-baseline tests remain explicitly gated and have not been claimed from
the local completion run.

Latest recorded command results:

- `python -m pytest -q`: 370 passed, 7 skipped.
- `python -m pytest` over the focused M9-M12-D and hardening regression set:
  109 passed, 5 live-gated tests skipped.
- `python -m xgap.experiments.backend_mapping_audit --dataset
  datasets/financial_risk_dev`: passed with no three-way IRI mismatches.
- `python examples/quantified_pattern_demo.py`: passed.
- `python examples/compiler_mvp_demo.py`: passed.
- `python examples/llm_boundary_demo.py`: passed.
- `python examples/m11_physical_planner_demo.py`: passed.
- `python examples/m11_exhaustive_oracle_demo.py`: passed.
- `python examples/m12_experiment_contract_demo.py`: passed; 2/2 controlled
  questions and 27 artifact files.
- `python examples/m12c_calibration_demo.py`: passed; the explicit offline
  fake path produced 2 D0 records and one calibrated GP per backend.
- `python examples/m12d_experiment_matrix_demo.py`: passed; 12 runs and 12
  aggregate groups completed with frozen candidate reuse.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  `examples/compiler_mvp_demo.py`, `examples/llm_boundary_demo.py`, both M11
  demos, the M12-A demo, the M12-C calibration demo, and the M12-D matrix
  demo. The M12-B fake-HTTP and M12-D offline paths are exercised by pytest.

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
- M10 LLM-boundary tests
- M11 contracts, search, cost, main-planner, oracle, and runner tests
- examples/m11_physical_planner_demo.py
- examples/m11_exhaustive_oracle_demo.py
- M12-A semantic, bundle/contract, and runner tests
- examples/m12_experiment_contract_demo.py
- M12-C calibration, model, measurement, and online-posterior tests
- examples/m12c_calibration_demo.py
- M12-D methods, ablations, candidate freeze, direct baseline, online
  lifecycle, matrix, resume, aggregation, and readiness tests
- examples/m12d_experiment_matrix_demo.py
