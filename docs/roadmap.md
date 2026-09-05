# XGAP Roadmap

## Current Mainline: M15 Agentic Federated Core

The M0-M14 milestones below record the original ambiguity-aware planning and
semantic-experiment track. They remain reproducible legacy baselines. The new
mainline is specified in
[`docs/m15_agentic_federated_core.md`](m15_agentic_federated_core.md).

### M15-A Contracts, Tools, Memory, and Bounded Goal Loop

Goal: define the agent environment and implement the first executable control
substrate without changing the audited path algebra.

Acceptance criteria: typed semantic DAGs and holes; typed tool outcomes;
pluggable backend adapters; provenance-bearing memory; explicit goals and
success criteria; tool allowlists; finite step/tool budgets; no automatic
retry; offline tests and example.

Current status: **DONE LOCALLY**

### M15-B Executable Two-Engine Vertical Slice

Goal: execute one hand-verified semantic program whose answer requires both
Neo4j and Fuseki, then join normalized results at the coordinator.

Acceptance criteria: fragment compilation, remote execution, exchange,
alignment, coordinator join/merge, correctness, latency, bytes, cardinality,
and remote-call artifacts; no LLM or ontology required.

Current status: **REAL NEO4J+FUSEKI VERTICAL SLICE VERIFIED ON CWRU; STREAMING/CANCELLATION PENDING**

Execution order:

1. **M15-B0 CWRU environment gate** — verified: clean Git checkout, Slurm,
   H100 feature, vLLM environment, Miniconda Python, and a dedicated
   pytest-capable `xgap-core` environment are present.
2. **M15-B1 CWRU CPU smoke** — verified by job `3784974` at commit `4c45931`
   on `compt365`: exit `0:0`, 40 passed/1 live skip, exact one-row result, two
   calls, and 206 transferred bytes.
3. **M15-B2 live backend packaging** — the authoritative compute node has no
   supported container runtime, so login-node Podman is rejected for Slurm
   service execution. The runtime-neutral loader and exact per-source oracle
   are implemented. Prerequisite job `3784980` verified loopback/archive tools,
   found Java 8 as the incompatible default, advertised Java 17 as the highest
   module, and found NFS-backed home storage. The v1 presence-only Java
   readiness flag is explicitly invalidated and fixed in probe v2. B2B pins
   Neo4j 5.26.30 and Fuseki 5.6.0 to a common Java 17 runtime and provides a
   single-attempt, digest-verified, no-overwrite shared archive cache. One CWRU
   artifact-preparation job `3787101` passed at commit `2ce4b53`: both archives
   matched their locked lengths and digests in one attempt each, with no retry,
   extraction, or service startup. B2C is implemented locally as a second,
   allocation-only trust boundary: verified archives are inspected for safe
   members and staged atomically into a new empty runtime directory. Real
   service launch remains gated on both cached archives and an explicit
   allocation-local filesystem check. B2D now implements the allocation-scoped
   launcher, exact Java 17 check, dynamic loopback ports, local Neo4j/Fuseki
   state, bounded health waits, one fixture/load run, reverse shutdown, and
   guarded cleanup. Combined service job `3787110` passed on `compt331` at
   exact commit `cd564de8`; both engines were healthy and loopback-only, the
   fixture and exact federated answer passed, shutdown and cleanup passed, and
   the read-only cross-artifact audit accepted all 102 checks.
4. **M15-B3 live federated vertical slice** — the typed program, real-plugin
   runner, vertically split fixture, exact oracle, immutable evidence, and
   gated live test are implemented. Job `3787110` verified the same contract
   against real Neo4j 5.26.30 and Fuseki 5.6.0 on CWRU.

The typed remote-executor plugin and its CLI are implemented locally. They
stage exact commits, allowlist batch entry points, observe jobs, and retrieve
scoped artifacts without storing credentials or silently retrying.

The command and artifact contract is frozen in
[`docs/m15_remote_execution_loop.md`](m15_remote_execution_loop.md).

### M15-C Nontrivial Plan Space and Observation Tools

Goal: add schema/explain/profile/sample tools and alternative correct plans for
pushdown, join strategy/order, parallel scheduling, and fragment fusion.

Current status: **LIVE OBSERVATION PATH IMPLEMENTED LOCALLY; CWRU VALIDATION AND CALIBRATION PENDING**

The first slice provides catalog-allowlisted observation tools, native Neo4j
plan/profile evidence, executable bind-query and semi-join nodes, two
exact-semantic M15 plans, and a deterministic critical-path/transfer selector.
Both plans return the same fixture answer and the selected plan reverses under
a controlled bound-query latency change. The controlled artifact is not a
paper result. A bounded collector now executes one declared, duplicate-free
observation tuple with no retry and publishes a plan snapshot only when every
observation succeeds. The live path obtains native Neo4j PROFILE evidence and
an explicitly labeled Fuseki wall-clock execution fallback. Its fixed cost
model is intentionally marked uncalibrated. General fragmentation,
pushdown/order enumeration, fusion, calibrated estimates, and the CWRU live
gate remain open.

### M15-D Memory-Guided Adaptation and Replanning

Goal: use versioned observations across tasks and explicitly replan within a
query when runtime evidence invalidates the current estimate.

Current status: **LIVE ADAPTIVE PIPELINE IMPLEMENTED LOCALLY; CWRU ADAPTIVE GATE PENDING**

The current slice persists versioned plan snapshots to append-only JSONL,
validates a probe as an exact common plan prefix before invocation, reuses that
prefix during continuation, and permits at most one explicit replan. The
controlled fixture flips from parallel hash to risk-first bind after observed
latency invalidates stale memory without duplicating the probe call. Probe
failure and the no-replan control are covered. CWRU observation evidence,
calibration, the complete baseline matrix, and a live adaptive run remain open.
The new live-service mode
collects exactly three registered planning observations, reopens the persisted
snapshot, executes one two-backend federated query with at most one replan,
persists and reopens two memory versions, and records a five-event tool trace.
It has its own Slurm entry point and mode-aware read-only audit so the verified
M15-B vertical slice remains reproducible. Until that job runs and the cost
model is calibrated, the artifacts remain a development gate with
`paper_result=false`.

### M15-E Selective Semantic Resolution

Goal: integrate deterministic interpretation, clarification, optional
catalog/ontology lookup, and bounded LLM fallback without making any one of
them a prerequisite for federated execution.

Current status: **PLANNED**

### M15-F Paper Experiment Surface and Optional UI

Goal: freeze a cross-platform workload and baselines/ablations; add a thin UI
only after the CLI, goal trace, coordinator, and remote-executor contracts are
stable.

Current status: **PLANNED**

## Historical Milestones

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

## M11 Ontology-Bounded Physical Planning

Goal:
Keep logical compilation deterministic for each interpretation and search
only physical realizations: backend placement and explicit cross-backend
exchange decisions. Ontology, schema, source mappings, and semantic
alignment are external, versioned planning inputs rather than search
dimensions.

M11 is decomposed into:

- M11-A Planning Objective and Physical-State Contract
- M11-B Bounded Branch-and-Bound Physical Search
- M11-C Bayesian Cost Model and Search Trace
- M11-D XGAP Main Planner and Exhaustive Oracle Evaluation

Files involved:
`src/xgap/planning/**`, `src/xgap/experiments/**`, M11 tests and controlled
artifacts, M11 demos, `docs/m11_ontology_bounded_physical_planning.md`,
and current-state documentation. Existing logical operators, deterministic
lowering, backend capability profiles, compiler contracts, and M10
candidate objects are reused rather than duplicated.

Acceptance criteria:

- physical states have deterministic identities and contain a fixed logical
  plan, backend placements, and exchange decisions;
- mapping sufficiency and semantic deviation are resolved through pluggable,
  versioned ontology/alignment providers before physical search;
- bounded best-first branch-and-bound search charges one budget unit per
  processed `ExtractMin`, preserves anytime prefixes, and retains the
  discovered complete plan with minimum conservative upper estimate;
- cost observations contain positive raw costs for complete plans and a
  frozen Gaussian-process snapshot predicts log-cost confidence bounds;
- returnable plans satisfy the strict hard bound `C_bar < T_max` and the
  strictly positive Nash-output domain;
- at most one representative is retained per interpretation and deterministic
  top-K ranking uses the planning-time Nash score;
- a tiny exhaustive oracle measures planning regret and search reduction in
  tests and experiments without being used by the production planner;
- compiler and runtime gaps are represented explicitly rather than expanded
  or approximated;
- unit tests, controlled demos, full pytest, and acceptance pass.

M11 does not implement live LLM providers, KGQA loading/evaluation, LoRA or
model training, automatic ontology induction, a built-in general-purpose
OWL/DL reasoner, full GQL, new compiler coverage for recursive/selectors/M6,
logical rewrite enumeration, new execution engines, or distributed
cross-backend runtime orchestration.

Current status:
DONE

## M12 Experimentalization

Goal:
Turn the M10/M11 controlled pipeline into a reproducible experiment surface
without changing the deterministic planner core.

M12 is decomposed into:

- M12-A Experiment Artifact Contract + Dataset Bundle
- M12-B Live LLM + Ontology/Alignment Artifacts
- M12-C Cost Calibration + Online GP Protocol
- M12-D Baselines/Ablations + Server Experiment Runner

M12-A freezes experimental semantics and introduces versioned contracts for
dataset bundles, model bundles, experiment specifications, semantic
deviation, GP protocols, metrics, execution protocols, manifests, hashing,
and run artifacts. It also adds a controlled financial-risk development
bundle and offline development runner over existing M10/M11 interfaces.

M12-B adds a generic OpenAI-compatible structured provider, a fixed DashScope
Qwen ModelBundle, a portable vLLM configuration boundary, bounded runtime
ontology/schema retrieval, query anchors, candidate slot realizations, and a
gold-free file-backed runtime alignment provider. It supplies real runtime
semantic/model inputs to the unchanged M11 planner while reusing M12-A's
frozen semantic deviation exactly.

Files involved:
`src/xgap/experiments/**`, `datasets/**`, `models/**`, `experiments/**`, M12-A
tests and demo, `docs/m12_experimentalization.md`, the M12-A sprint prompt,
and current-state documentation. M11 planner contracts are reused unchanged.

M12-A acceptance criteria:

- the frozen directional ontology-hop semantics and uniform slot aggregation
  are typed, serializable, and tested;
- DatasetBundle, ModelBundle, and ExperimentSpec load deterministically with
  stable versions and content hashes;
- fragment-support, baseline, ablation, metric, execution, GP, and run-layout
  contracts reject invalid combinations explicitly;
- missing optional benchmark gold data remains explicitly unavailable;
- a controlled financial-risk development bundle exercises the contract;
- one offline runner materializes the complete M12 artifact tree through the
  existing M10 mock boundary and M11 planner;
- targeted tests, full pytest, the development run, and acceptance pass.

M12-B acceptance criteria:

- changing only ExperimentSpec/ModelBundle selects the mock or live structured
  candidate provider;
- one generation call and at most one repair call produce no more than M
  grounded `PathPatternQuery` candidates;
- prompt context is bounded, deterministic, content-hashed, and contains no
  gold answers, gold logical forms, gold alignments, or evaluation labels;
- query-side anchors and candidate slot realizations remain separate and feed
  the frozen M12-A `c_sem` implementation;
- ontology/entity IDs, slot coverage, and backend mappings are validated
  explicitly before the unchanged M11 planner runs;
- DashScope uses the fixed `qwen3-max-2026-01-23` snapshot and the same generic
  provider remains configurable for a future/local vLLM endpoint;
- default pytest remains offline, fake-HTTP tests exercise the full provider
  path, and the real Qwen smoke test is explicitly gated.

M12-B does not implement LoRA, model deployment, full ontology reasoning,
real D0 collection, GP calibration, executable baselines/ablations, final
KGQA evaluation, or server experiment orchestration.

M12-C implements real-cost calibration and the online GP lifecycle while
preserving M11 planning semantics. It provides deterministic complete-plan
calibration workloads, repeated Neo4j/Fuseki execution through the existing
M7 clients and M9 compiler boundary, backend-specific D0 artifacts, fitting
of the existing RBF GP family, immutable calibrated-model registration, and
atomic between-task posterior updates.

M12-C acceptance criteria:

- Neo4j and Fuseki use independent backend-local `D0` datasets and RBF GPs;
- raw execution cost is persisted in milliseconds and the GP target is its
  natural logarithm;
- only complete, backend-local, actually executed plans become observations;
- calibration and evaluation splits are distinct and evaluation gold is not
  admitted to calibration cases or features;
- repeated measurements, failures, feature schema, protocol, D0, model, and
  hyperparameter identities are persisted and hashed;
- hyperparameters remain frozen during evaluation, and all plans in task q
  use the same posterior derived from `D_(q-1)`;
- a task batch is appended only after execution and updates only the model for
  the observed backend;
- unsupported distributed movement remains explicitly unavailable;
- offline tests and demos do not require live services, while live calibration
  is explicitly gated;
- M11 search, M12-B inference semantics, and all previous acceptance tests
  remain unchanged.

M12-C does not implement a joint backend-aware GP, transfer-cost learning,
new compiler coverage, distributed runtime orchestration, executable
baselines/ablations, experiment-matrix scheduling, new benchmarks, or new
LLM/ontology behavior.

M12-D composes the frozen M10-M12-C boundaries into a configuration-driven,
resumable experiment system. It implements explicit policies for
`full_xgap`, `random_feasible`, `mean_only`, `no_pruning`,
`no_online_update`, `single_backend`, controlled `exhaustive_oracle`, and the
separate `direct_text2graphquery` system baseline. Frozen candidate artifacts
support fair planner comparisons, while matrix expansion varies dataset,
model, method, epsilon, budget, and seed without planner-code changes.

M12-D acceptance criteria:

- task q plans against one immutable `D_(q-1)` snapshot and commits its
  successful execution observations atomically only after task execution;
- all frozen method and ablation identifiers have explicit behavior or an
  explicit controlled-only boundary;
- candidate generation can be frozen and replayed across comparable physical
  planning methods;
- deterministic matrix run IDs, collision checks, checkpoints, resume, and
  completed-run skipping make sequential server runs reproducible;
- execution records distinguish nonempty success, empty success, and error,
  and retain normalized `row_count`;
- planning, prediction, confidence, latency, failure, and aggregate-ready
  metrics remain separate and unavailable gold/oracle values remain null;
- readiness distinguishes development, pilot, and paper modes, with Python
  3.10+, immutable hashes, pinned backend versions/images, and a consistent
  DatasetBundle mapping/data/M9 native-IRI contract required for paper mode;
- aggregation emits analysis-ready JSON and CSV without claiming publication
  results;
- default pytest remains offline and live backend/model tests are explicitly
  gated.

M12 completion means the experiment infrastructure is ready for paper-grade
dataset/model artifact preparation and large-scale runs. It does not mean
that final datasets or numbers exist, MetaQA/QALD are integrated,
cross-backend distributed execution or movement-cost learning exists, or new
compiler fragments are supported.

Current status:
M12-A DONE; M12-B DONE; M12-C DONE; M12-D DONE

## M13 Automated Semantic Disambiguation

Goal:
Replace controlled semantic-deviation inputs with a separately specified,
evidence-backed disambiguation stage. Reuse M11 one-representative Nash top-K
rather than introducing a second physical ranking algorithm.

Files involved:
Disambiguation modules, ranking modules, tests.

Acceptance criteria:
XGAP can derive reproducible semantic-deviation evidence for candidate
interpretations and supply it through the M11 scorer boundary while keeping
semantic quality separate from conservative execution cost.

Current status:
TODO

## M13-C GrailQA Paper Vertical Slice

Goal:
Extend the current fixed-path fragment only where justified by the GrailQA
audit, normalize the public ontology reproducibly, construct evaluation-only
ambiguity evidence and a versioned pilot DatasetBundle, and run an actual
semantic-to-native-compilation vertical slice.

Acceptance criteria:
The historical M13-A output remains unchanged; the v2 audit reports measured
coverage and structural diversity; ontology SCC normalization and backend
mapping are frozen; gold artifacts remain isolated from inference; the pilot
traverses deterministic lowering, M11 planning, and M9 compilation; unavailable
Freebase execution is reported rather than fabricated; all tests and
acceptance checks pass.

Current status:
DONE. GrailQA is currently recommended for semantic-only paper evaluation.
Real Freebase execution and a rich physical-plan space remain unavailable.

## M13-D Server-Executed GrailQA Semantic Pilot Preparation

Goal:
Freeze and package the first real GrailQA RQ1 semantic pilot so a human can run
it on the experiment server without Codex, source edits, or parameter choices.
The path is NL question to query-independent public metadata retrieval, bounded
M12-B Qwen candidates, existing deterministic validation/grounding, unchanged
`c_sem`, epsilon filtering, deterministic semantic ranking, conservative
reference support, and automatic metrics.

Acceptance criteria:
The repository contains a versioned public inference catalog, file-level
gold-isolation boundary, deterministic retrieval and post-inference Recall@k,
immutable 150-ID spec, safe resumable runner, exact readiness/smoke/full
commands, first-failure accounting, all required raw/summary outputs, and a
150-query fake-provider orchestration run. Existing M12-B prompt/model bounds
remain frozen, candidate generation is reused across epsilon, and normal tests
never call live Qwen.

Current status:
DONE. Local fake-provider orchestration and the real frozen 150-query server
run completed. The result is retained as a diagnostic baseline: zero joint
prompt reachability makes its zero Candidate Recall unsuitable as an isolated
model-capability result. M13-D does not add backend execution, RQ2/RQ3, KQA
Pro, prompt tuning, new algebra, or changed M11/GP/Nash behavior.

## M13-E1 GrailQA Reachability And Interpretation Contract Repair

Goal:
Repair the scientific inference/evaluation boundary before another paid run:
replace the incomplete entity-source path with a reproducible query-independent
Freebase catalog build, measure catalog/retrieval/prompt reachability, separate
semantic choices from canonical representation, and guard a small live
preflight with an offline gate.

Acceptance criteria:
M13-D reachability is reproducible; catalog v2 construction accepts no gold
input and records public provenance/hashes; deterministic retrieval persists
alias, relation-slot, reverse, and domain/range evidence; typed conditions and
canonical normalized equivalence agree; failures and `c_sem` are observable;
the 18-query live runner cannot call the provider when reachability fails; no
full live run, tuning, algebra extension, `c_sem` change, M11/GP change, or
backend execution is added.

Current status:
LOCAL OFFLINE IMPLEMENTATION DONE; SERVER DATA GATE BLOCKED. The v1 audit
reproduces joint prompt reachability 0/150. The comprehensive official Freebase
dump is not local, so catalog-v2 counts, all-35,439 catalog coverage, repaired
retrieval metrics, and the credentialed v2 preflight remain unclaimed until
the server builder and offline gate pass.

## M13-E2 CWRU H100 + vLLM Experiment Backend

Goal:
Make the existing OpenAI-compatible structured-candidate interface runnable
as a self-contained Slurm job on CWRU Pioneer using one scheduler-selected
H100 NVL and the frozen dense `Qwen/Qwen3-32B` vLLM condition.

Acceptance criteria:
Configuration externalizes endpoint, credential environment, and served model;
non-thinking JSON Schema requests are preserved in exact request artifacts;
the shared environment/cache and resolved revision are verified and logged;
readiness and a tiny structured smoke precede inference; generic and 18-query
preflight Slurm wrappers capture reproducibility artifacts and always clean up;
normal tests require no GPU; M13-E1's gate remains authoritative; no semantic,
planning, GP, backend, training, or 150-query behavior changes.

Current status:
LOCAL IMPLEMENTATION DONE; CWRU SUBMISSION PENDING THE M13-E1 CATALOG GATE.
The manually validated CWRU runtime is frozen in a machine-readable contract.
No live H100 inference was run by local acceptance.

## M13-E3 Freebase Catalog-v2 Construction And Reachability Audit

Goal:
Instantiate the existing M13-E1 query-independent catalog design over a frozen
representation of the final public Freebase data and determine, entirely offline, whether all
reference-required GrailQA entities, relations, and types are jointly visible
to the bounded inference prompt.

Acceptance criteria:
Raw download, checksum verification, streaming build, integrity validation,
and reachability audit are independent and restart-safe; external persistent
storage is configurable; the catalog records MID/name/English-alias/type
metadata while retaining the frozen GrailQA ontology as schema authority; all
35,439 supported questions receive catalog coverage; the frozen 150 receive
Recall@1/5/10/20, relation-slot/all-required metrics, prompt truncation, Q/path
strata, and first-loss attribution; compact hashed outputs expose an explicit
`live_preflight_allowed` decision; normal tests use only fixtures and no LLM,
GPU, backend, or download.

Current status:
**IMPLEMENTATION READY; REAL CWRU BUILD AND AUDIT PENDING.** The CPU Slurm job,
runbook, manifests, fixture tests, and report templates are ready. M13-E3A
freezes the reachable `CleverThis/freebase` archival Parquet tree at immutable
revision `dbb1931c2698295653effe9b980a02ab29f004e0` after direct Google object
retrieval returned HTTP 403 from CWRU. Source selection is explicit and has no
fallback; both source modes feed unchanged Catalog-v2 extraction semantics.
No catalog statistics or improved retrieval claims are made before all 964
shards are processed and the compact audit results are returned.

## M13-E3B Gold-Blind Query-Conditioned Local Freebase Catalog

Goal:
Determine whether bounded inference-time grounding can replace a global
Freebase entity index for the frozen 18-query preflight and 150-query pilot.
For each question, derive a local candidate universe solely from its text,
public Freebase English names/aliases/type metadata, and the frozen GrailQA
ontology, while allowing one physical scan to batch independent questions.

Acceptance criteria:
Construction accepts only inference question IDs/text; rejects gold,
reference, answer, and logical-form fields; uses the immutable E3A Parquet
source without redownload; performs bounded name/alias selection and retained
MID type enrichment; produces two isolated Catalog-v2-compatible artifacts;
enforces per-question candidates by ID and text hash; publishes from node-local
staging atomically; preserves persisted query-local entity ranking at
downstream retrieval while leaving global Catalog-v2 FTS unchanged; runs
M13-E1 reachability metrics only after construction; distinguishes
local-catalog misses; preserves the 0.20 gate; and leaves the independent
global E3/E3A job unchanged.

Current status:
**M13-E3B.4 COMPLETE; M13-E3B.5 LOCALLY IMPLEMENTED, CWRU LIVE PREFLIGHT
PENDING.** The real preflight18 build completed with 865 unique entities and
900 assignments. Its
first audit exposed a generic local/global ranking-contract mismatch: local
entity coverage was 10/18 but entity Recall@20 and joint prompt reachability
were both 0/18. E3B.2 makes persisted per-question rank authoritative only for
explicit query-local catalogs, adds before/after and relation/type diagnostics,
and leaves global FTS, candidate construction, prompt bounds, and the 0.20 gate
unchanged. The real E3B.2 rerun validated Entity Recall@1/5/10/20 of 3/7/8/8
over 18 and exposed relation/type ranking as the remaining bottleneck.

E3B.3 freezes deterministic phrase-aware relation/type ranking, ontology-only
IDF tie-breaking, bounded relation-slot domain/range coherence, and
pre-truncation type provenance. Its audit preserves prior artifact hashes and
writes relation/type ranking decompositions, v2 failure stages, and exact
before/after metrics. The real rerun improved Relation Recall@1/5/10/20 to
5/11/12/13 of 18 and relation prompt coverage to 10/18. Type Recall@1/5/10/20
became 1/4/8/13, explicit Type prompt coverage remained 4/18, and joint prompt
reachability remained 1/18.

E3B.4 freezes a shared role-aware relation-endpoint visibility contract. Exact
domain/range types may ground only the source/target endpoint adjacent to the
candidate's selected prompt-visible relation, respecting OUT, IN, and
UNDIRECTED direction. Fixed linear paths use the first and last relation hop;
ambiguous regular expressions receive no derived evidence. Offline audit keeps
explicit Type metrics unchanged, reports `effective_type` separately, and uses
that same runtime contract for joint reachability and the existing gate. Its
real acceptance was an audit-only rerun over the existing preflight18 SQLite
artifact. Effective Type prompt coverage rose from 4/18 to 12/18 and joint
prompt reachability from 1/18 to 5/18, so the unchanged 0.20 gate passed at
0.2778 while explicit Type Top-4 remained 4/18.

E3B.5 connects that passing query-local artifact to the frozen 18-query CWRU
Qwen3-32B preflight. An explicit artifact profile validates the exact question
set, catalog hash, audit hash, reachability-row hash, prompt bound, and
endpoint contract before model startup. The structured request exposes the
same endpoint rule used by deterministic runtime validation, and evaluation
reports both overall metrics and metrics conditioned on the jointly reachable
five-question subset. It does not rescan Freebase, alter Top-50 or Top-4,
change the gate, run pilot150, or modify ranking, Qwen parameters, planner,
compiler, or backend behavior.

The first real CWRU E3B.5 submission passed the 5/18 gate but stopped before
model loading because readiness compared JSONL row order with spec order.
E3B.5.1 treats physical row order as irrelevant while still requiring one
unique record for every frozen preflight ID and no extras. The second
submission passed readiness, loaded Qwen3-32B on H100, and passed strict
structured-output serving. It then exposed one additive diagnostic-contract
gap: the shared classifier rejected the already documented local-catalog stage
`reference_not_in_local_catalog`. E3B.5.2 admits that stage without weakening
unknown-stage rejection. The next submission completed cleanly but every live
request received HTTP 400 before generation: the 8192-token serving context
could not hold the observed 4146-4590 input tokens plus the frozen 4096 output
budget. E3B.5.3 preserves both bundle budgets and expands only the deployment
context to their exact sum, 12288. It also checks that arithmetic before model
startup. The next run reached 17/18 provider success and 5/5 provider success
on the jointly reachable subset, with zero malformed responses, but strict
guided decoding returned `candidates=[]` for every successful call because the
schema permitted an empty array. E3B.5.4 requires one to three generated
candidates in the CWRU schema and prompt while preserving all downstream
validation and rejection boundaries. The next run proved that vLLM 0.11.1 did
not enforce those array cardinality keywords and again returned only empty
arrays. E3B.5.5 deterministically checks the active bundle's candidate
`minItems/maxItems` at the provider boundary and routes violations through the
existing single repair call. The rerun remains the next experiment action.

## M14 KGQA Evaluation

Goal: Add KGQA dataset loading, execution harnesses, and evaluation reporting.

Files involved: `src/xgap/datasets/kgqa.py`, evaluation scripts, dataset tests.

Acceptance criteria: Evaluation can compare generated queries or answers against KGQA benchmarks.

Current status: TODO
