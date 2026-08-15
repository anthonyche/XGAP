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

## M14 KGQA Evaluation

Goal: Add KGQA dataset loading, execution harnesses, and evaluation reporting.

Files involved: `src/xgap/datasets/kgqa.py`, evaluation scripts, dataset tests.

Acceptance criteria: Evaluation can compare generated queries or answers against KGQA benchmarks.

Current status: TODO
