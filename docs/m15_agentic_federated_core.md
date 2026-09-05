# M15 Agentic Federated Core

## Goal

Build an executable, experiment-first agentic federation layer on top of the
existing deterministic graph-query stack. M15 does not replace the audited path
algebra and does not claim access to backend-internal physical operators.

## M15-A — Contracts, tools, memory, and bounded goal loop

Status: **DONE locally**

Implemented:

- typed, backend-independent semantic DAGs with explicit value kinds,
  constraints, capabilities, and unresolved holes;
- typed tool specifications and success/error/unavailable observations;
- a plugin registry for black-box graph backends;
- an adapter that exposes existing `BackendClient` healthcheck and execution
  behavior without changing those clients;
- typed session/schema/execution/cache memory with provenance, version,
  confidence, and expiry;
- a finite goal loop with explicit success criteria, tool allowlist, step
  budget, tool-call budget, trace, and no automatic retry;
- a deterministic sequential policy used as the first baseline;
- offline tests and a two-backend adapter demonstration.

M15-A does not implement cross-source data movement, coordinator joins, plan
search, LLM policy decisions, live services, or a UI.

## M15-B — Executable two-engine vertical slice

Status: **REAL NEO4J+FUSEKI VERTICAL SLICE VERIFIED ON CWRU; STREAMING/CANCELLATION PENDING**

Goal: execute one hand-authored semantic program across Neo4j and Fuseki and
join the normalized results at the coordinator.

Required work:

- live Neo4j and Fuseki execution of the split-data fixture;
- streaming/batched rows beyond the current bounded in-memory row contract;
- cancellation for live remote work;
- one synthetic dataset whose facts are deliberately split across engines;
- exact end-to-end correctness, latency, bytes, row-count, and remote-call
  metrics.

Implemented locally:

- per-backend `SemanticFragment` compilation through the existing M9 Cypher
  and SPARQL compilers;
- typed `RemoteQuery`, `Align`, `Exchange`, `CoordinatorJoin`, `Merge`, and
  coordinator `Project` runtime nodes;
- validated finite execution DAGs with remote-call and parallelism budgets;
- parallel execution of independent remote nodes;
- deterministic coordinator alignment, exchange accounting, hash join, merge,
  failure propagation, and skipped descendants;
- a `runtime.execute_plan` agent tool that returns rows and measured runtime,
  remote-call, and transfer metrics;
- a typed `remote.executor` boundary for exact-commit staging, allowlisted
  Slurm submission, status, bounded logs, artifact retrieval, and guarded
  cancellation;
- a non-secret environment-configured CLI for the same remote-executor
  contract;
- an offline split-fact fixture where the complete answer requires both
  backend plugins;
- a deterministic vertically partitioned Neo4j/Fuseki dataset, native query
  artifacts, and exact expected result;
- a deployment-neutral, explicitly gated fixture loader that uses only the
  backend/Graph Store HTTP boundaries, performs namespaced idempotent appends,
  verifies both source results exactly, stores no credentials, and persists
  partial failures without retry. It is experiment bootstrap infrastructure,
  not an agent-visible query tool;
- a frozen native-service supply lock and fail-closed preparation runner for
  exact Neo4j/Fuseki archives. The cache path is separate from runtime state,
  verified entries require exact length and digest, conflicting entries are
  never overwritten, downloads are never retried, and preparation cannot
  extract archives or start services;
- a fail-closed live runner that invokes the existing real Neo4j and Fuseki
  clients through backend plugins and persists semantic, plan, health, result,
  validation, status, source-hash, and manifest evidence without retrying.

Current full local acceptance passes 712 tests with 36 explicitly gated or
external-artifact tests skipped.

Remote execution is decomposed into explicit B0/B1 environment and CPU-smoke
gates before live services are started. Both gates are now verified. See
[`docs/m15_remote_execution_loop.md`](m15_remote_execution_loop.md). These
gates distinguish the previously exercised legacy M13 CWRU/vLLM path from the
M15 service path, which subsequently passed the B2D/B3 live gate. The newer
M15-C2/D2 adaptive-service mode subsequently passed its independent CWRU gate
in job `3787152`.

B0 artifacts established an exact checkout, working Slurm, visible
`gpu2h100`, an existing vLLM environment, Miniconda Python 3.11.5, and the
dedicated pytest-capable `xgap-core` environment. B1 job `3784974` then passed
the M15 CPU smoke at exact commit `4c45931` on `compt365`: 40 tests passed, one
live gate skipped, and the deterministic two-source coordinator result used
two calls and 206 transferred bytes. The compute node exposed no supported
container runtime, so login-node Podman is not the B2 strategy. B2 prerequisite
job `3784980` on `compt386` then verified loopback and archive tools, exposed
OpenJDK 8 as the incompatible default, advertised `Java/17.0.6` as the highest
available module, and identified `/home` as NFS-backed. The original probe's
presence-only readiness flag is invalidated; probe v2 now validates the Java
major. B2B consequently pins Neo4j 5.26.30 LTS plus the final Java-17 Fuseki
line, 5.6.0, caches only verified archives on shared storage, and reserves
allocation-local storage for extracted runtime state.

B2B job `3787101` then ran commit `2ce4b53` on `compt398` and admitted exactly
the two locked archives to the shared cache: Neo4j 5.26.30 passed its frozen
162,360,826-byte SHA-256 and Fuseki 5.6.0 passed its frozen 50,290,245-byte
SHA-512. Each artifact used one download attempt, `automatic_retries` was zero,
and the job neither extracted an archive nor started a service. This admitted
the allocation-scoped B2D service run at a clean commit containing the
read-only evidence auditor.

B2D job `3787110` ran exact clean commit `cd564de8` on `compt331`. It staged
the locked products on allocation-local XFS, loaded the split fixture, and
executed the live coordinator path through the Neo4j and Fuseki HTTP plugins.
The exact one-row answer used two remote calls. Both loopback-only services
shut down without `SIGKILL`, the job-owned runtime was removed, and the
separate read-only audit passed all 102 checks with no mutation. This closes
the real two-engine vertical-slice gate, but it is engineering acceptance—not
a paper performance result—and does not close streaming/batching or live
cancellation.

Acceptance gate:

1. neither backend alone can answer the complete question;
2. the coordinator returns the hand-verified answer from both backends;
3. all remote calls, transferred bytes, intermediate cardinalities, and local
   join time are persisted;
4. no LLM or ontology is required;
5. offline tests remain independent of live services, and live tests are
   explicitly gated.

## M15-C — Nontrivial plan space and observation tools

Status: **LIVE OBSERVATION PATH VERIFIED ON CWRU; CALIBRATION AND SCALE PENDING**

Implemented in the first closed slice:

- a versioned, coordinator-owned observation catalog that exposes only
  registered read-only schema, query, and bounded-sample artifacts;
- black-box `inspect_schema`, `explain`, `profile`, and `sample` operations,
  with explicit `unavailable` outcomes when an engine lacks a capability;
- Neo4j HTTP `EXPLAIN` and `PROFILE` observations whose native plans remain
  evidence rather than XGAP physical operators;
- executable `RemoteBindQuery` and coordinator `SemiJoin` runtime nodes,
  including binding limits, an empty-binding short circuit, deterministic
  deduplication, call accounting, and transitive failure skipping;
- exact-semantic M15 `parallel-hash` and `risk-first-bind` plans;
- a frozen-snapshot selector using critical-path latency and explicit exchange
  bytes, with deterministic tie breaking and complete observation provenance.

The controlled M15 sanity check executes both plans to the same exact answer,
moves 530 versus 363 fixture bytes, selects bind under transfer pressure, and
flips to parallel when bound-query latency is increased. It is explicitly
marked `paper_result=false`; live profile-derived calibration is still pending.

The next slice adds a finite observation collector over the registered
catalogs. It validates the full request and cost-model contract before any
backend call, invokes each profile/sample once in declared order, retains
partial evidence on failure, and publishes a snapshot only after the complete
request tuple succeeds. The M15 live contract uses native Neo4j `PROFILE` for
the full and bound transfer artifacts and an explicit wall-clock execution
fallback for Fuseki's registered high-risk artifact. This path is implemented
and offline-tested, and CWRU job `3787152` verified all three observations
against the real services.

Alternative fragmentation, generalized pushdown/join-order enumeration,
fragment fusion, and paper-scale observations remain future M15-C work.

Acceptance gate: at least one workload has multiple correct executable plans,
and the selected plan changes under controlled cardinality or latency changes.

## M15-D — Memory-guided adaptation and replanning

Status: **LIVE ADAPTIVE RUNNER AND F1 LIVE METHOD MATRIX VERIFIED ON CWRU; PAPER CAMPAIGN PENDING**

Use versioned capability and execution memory across tasks, and permit explicit
within-query replanning after observations invalidate the current estimate.

The first slice adds an append-only JSONL memory backend, immutable snapshot
versions, an ancestor-closed scheduler continuation boundary, and a one-replan
adaptive executor. A probe must be an exact common prefix of every candidate
before any remote call. Its successful rows and accounting are reused by the
selected continuation; a failed probe is retained as evidence and does not
trigger a fallback query. The controlled demo starts from stale task memory,
changes selection from parallel hash to risk-first bind after a measured
latency deviation, returns the exact answer with two total remote calls, and
reloads the updated snapshot from disk. It is not a live or paper result.

Required baselines: static federation, no memory, no profile/probe, no replan,
and full agent. F1 now implements two fixed-plan static controls plus explicit
`no_memory`, `no_profile_probe`, `no_replan`, and `full_agent` policies. Plan
memory is reusable only under an exact context fingerprint over semantics,
candidate DAGs/artifacts, observations, cost model, workload, and catalogs.
Cold full-agent tasks profile and persist; warm tasks skip the three profiles,
probe one common prefix, and may change plan once. The controlled paired
matrix proves that the six methods have different action traces and preserve
one exact answer. It remains `paper_result=false`; a live repeated matrix is
pending. CWRU job `3787152` verified the earlier real-backend adaptive path,
including its legitimate zero-replan branch on the tiny fixture.

F1L composes those policies with the allocation-scoped native-service
lifecycle. It loads one verified workload, performs one separately accounted
three-observation calibration, seeds isolated memory histories for the three
warm methods, and executes all six policies with independent tool-event and
answer artifacts. The fail-closed auditor binds the workload hashes, policies,
18-call trace, snapshot identities, exact rows, service lifecycle, and guarded
cleanup. CWRU job `3787267` executed this path at exact clean commit
`6aafafd` on `compt336`; all six methods returned the exact answer, the
declared phase counts summed to 18 calls, runtime cleanup succeeded, and the
independent read-only audit passed 326/326 checks without mutating the run
tree. Fixed order, one selective workload, an uncalibrated cost model, and
shared unknown backend cache state remain explicit, so this is an engineering
mechanism gate rather than a latency comparison.

M15-D2 now has a separate fail-closed live runner. Within one query attempt it
accounts for exactly three planning-profile calls and two query calls, stores
the profile and runtime-updated snapshots in append-only memory, and persists
candidate plans, probe plan, tool invocations, exact answer, plan selections,
and replan decision. The allocation-scoped service lifecycle exposes this only
through an explicit `adaptive` workload mode; the previously audited vertical
slice remains the default. A mode-aware read-only auditor checks the full
service, fixture, observation, memory, query, and cleanup chain. All current
cost constants are explicitly uncalibrated development parameters and the run
is labeled `paper_result=false`.

Job `3787152` ran this mode at exact clean commit `247e714` on `compt336`.
The read-only audit passed 173 checks with no mutation, the exact
three-profile/two-execute trace and two memory versions were present, and the
federated answer was exact. Both selectors chose `m15-parallel-hash`, so the
run establishes the live no-replan outcome rather than a plan-flip result.
Scaled/skewed workloads and calibration are required before performance claims.

## M15-E — Selective semantic resolution

Status: **PLANNED**

Integrate deterministic parsing, the preserved interpretation prototype,
catalog/ontology lookup, clarification, and the existing bounded LLM provider.
Easy cases use zero LLM calls; unresolved identity ambiguity asks the user;
hard constraints remain immutable.

## M15-F — Paper experiment surface and optional UI

Status: **F0/F1/F2A LIVE GATES VERIFIED; F2B4 CWRU GATE SUBMITTED; F2C0 TASK CONTRACT LOCAL**

The first F0 slice commits two bounded workload specifications and generates
large artifacts only inside a new immutable run tree. The generator produces
namespaced Neo4j/Fuseki loads, full and bound queries, per-source oracles, and
the exact cross-source answer; every file is SHA-256 bound and the bundle is
revalidated at each trust boundary. `selective-dev-v1` has 200 companies,
5,000 transfers, 20 high-risk companies placed outside the hot set, and 120
answer rows. `broad-hot-dev-v1` keeps the same graph size but places 160
high-risk companies across the hot region and has 4,800 answer rows.

Both profiles run the same exact semantic program and the same parallel-hash
and risk-first-bind candidates through an explicit `scaled_adaptive` service
mode. The mode has its own Slurm wrapper and audit contract; the auditor binds
the profile label back to the committed spec and checks the generated bundle,
fixture, observations, memory, plan, answer, service lifecycle, and cleanup.
Local execution is development validation with `paper_result=false`. CWRU job
`3787167` exercised the first selective bundle at exact commit `36281aa`.
Archive staging, workload generation, service startup, and guarded cleanup
reached their declared boundaries, but Neo4j rejected the first load statement
before profiling because generator v1 embedded JSON objects as Cypher map
literals. The failed run made zero query calls and is not a performance result.
Generator v2 emits validated Cypher literals. New job `3787173` at clean
commit `3a2bce9` passed that syntax boundary and started both services, but
statement 6/6 still carried all 5,000 transfers and exceeded the fixed Neo4j
request deadline after five successful statements. No profile or query ran.
Generator v3 and bundle schema v2 now bind a fixed 100-row batch protocol,
producing 56 selective load statements without a timeout increase or retry.
Job `3787213` at clean commit `32c157f` then completed: all 56 Neo4j statements
loaded, the exact 120-row result used risk-first bind with two calls and 28,702
bytes moved, and a separate read-only audit passed 188/188 checks without run
mutation. This is a single-run engineering gate. Broad-hot execution,
calibrated repetitions, and the paper-scale counterbalanced campaign remain
pending. F1's
deterministic paired sanity check already executes all six
declared methods. Under one controlled stale-to-current latency transition,
all return the exact answer; full agent changes from parallel hash to
risk-first bind while no-replan observes the same preferred change but retains
the initial plan. Calibration and live timings are deliberately excluded from
this mechanism-only result. The compact clean-commit record is
`experiments/artifacts/m15_f1_local_controlled_method_matrix_20260905.json`.

The separate `scaled_method_matrix` mode now carries the same six methods into
one real Neo4j/Fuseki allocation. It preserves common calibration outside the
per-method totals, requires an exact 18-invocation trace, writes distinct
method and memory artifacts, and is covered by the read-only native evidence
auditor. Job `3787267` passed this contract and its independent 326-check audit.
The fixed-order shared-cache design remains intentionally a mechanism gate;
randomized/counterbalanced repetitions and calibrated cost parameters are
still required for paper comparisons.

F2 begins with a side-effect-free campaign compiler. Its development protocol
uses a deterministic six-sequence Williams design per workload and block, so
every method occurs once in every position and every directed first-order
method transition occurs once. Each sequence declares a fresh service pair,
separate method memory namespaces, excluded common calibration, raw
repetition preservation, exact-answer gating, and zero retry. The compiler
makes no backend, LLM, or ontology call and never labels its output as a
result. The current two-workload, one-query development configuration cannot
measure cross-task memory reuse and remains blocked from paper comparison
until query artifacts, 30--50 query contexts, cost calibration, repetitions,
live isolation validation, and an author-approved inferential analysis are
frozen.

F2A connects one compiled sequence to the existing live six-method runner.
Before a service or backend call, it recompiles the campaign, verifies the
author-supplied campaign and schedule hashes, matches both the source workload
configuration hash and normalized bundle-spec hash, and checks the exact
session, query stream, measured task IDs, logical memory namespaces, and
method order. A custom order is rejected unless the
matrix receives this complete campaign binding. The native lifecycle and
allowlisted Slurm wrapper now carry one such session through fresh
Neo4j/Fuseki services, fixture load, the 18-call sequence, cleanup, and the
read-only cross-artifact auditor. The v1 executor deliberately accepts only
the existing single financial-risk query, so the CWRU run is a mechanism gate
and cannot establish cross-task memory or counterbalanced performance.

CWRU job `3787291` executed the first selective session at exact clean commit
`c9a7afe` on `compt336`. The compiled Williams order drove all six methods,
all answers were exact, the trace contained exactly 18 tool invocations and no
automatic retry, and runtime cleanup succeeded. The independent read-only
audit passed 374/374 checks without mutating the run tree. This closes the
compiler-to-live-runner engineering gate only; the other 11 development
sessions were not dispatched and no comparative claim is supported.

F2B begins by replacing an unstructured query label with a resolved-query
contract. The committed development specification declares the immutable
person, time, amount, and risk constraints; semantic operators and answer
fields; exact Neo4j full/bound and Fuseki risk query roles; the bind parameter
contract; and source/final oracles. The compiler accepts only a verified
workload bundle, binds every query and oracle file by SHA-256, rejects role,
parameter, schema, symlink, or hard-constraint-relaxability drift, and produces
a location-independent contract hash without making an external call. This is
currently a local primitive: the v1 campaign/session still carries its old
query label, so the remaining sessions stay disabled until F2B binding is
wired through the scheduler, live runner, and read-only auditor.

F2B2 adds a separately versioned registry over the immutable F2A campaign.
It requires exact base campaign/spec hashes and complete coverage of every
workload/query key, verifies each query-spec source hash, freezes the expected
bundle-dependent contract hashes, injects contract references into every
method stream, and derives a portable query-bound schedule hash. Local file
paths remain provenance and do not affect that hash. This closes the
scheduler-side label gap, but the expected contracts have not yet been
recomputed against the live generated bundle and the existing session runner
does not consume this plan. F2B3 must perform both checks before enabling one
new remote engineering gate.

F2B3 now performs the missing live-bundle verification in a direct runner.
Before it creates an output directory or observes a backend, it recompiles the
query-bound plan, verifies the expected registry and bound-schedule hashes,
loads the deterministic bundle, and recomputes the selected resolved-query
contract. The matrix receives a v2 binding that includes the exact query-spec,
query-contract, workload, registry, and schedule identities; incomplete or
wrong contracts are rejected. The six methods then execute in the compiled
order with the existing exact-answer and 18-call gates. This path is locally
verified only: fresh Neo4j/Fuseki service lifecycle, Slurm entry, and an
independent cross-artifact audit remain F2B4.

F2B4 places that path inside a separately versioned native-service mode and
allowlisted Slurm wrapper. The native runner requires all four query-bound
inputs together and completes the F2B3 bundle-contract preflight before Java
inspection or Neo4j/Fuseki startup. The independent read-only auditor does not
trust the recorded contract identity: it recompiles the repository registry
and selected contract from the completed run's verified bundle, then checks
the wrapper, v2 matrix binding, contract artifact, exact result, 18-call
trace, service lifecycle, and cleanup as one cross-artifact chain. Local
acceptance now authorizes one selective CWRU engineering gate only. The other
eleven development sessions, multi-query execution, cross-task memory claims,
and all comparative paper claims remain disabled.

F2C0 adds the route-independent task-stream boundary needed before those
multi-query runs exist. It validates the complete F2B query-bound plan and
recomputes its binding and schedule hashes, then expands one selected session
into a deterministic method/phase/repetition/query order. Each task has a
unique content-derived identity and an immutable query-spec/contract reference.
Its pre-task memory view is frozen, restricted to eligible successful exact
predecessors in the same method namespace, and cannot observe writes from the
current task; any post-task write is separately policy- and correctness-gated.
The present session has one task per method, so its machine-readable validation
rejects a cross-task-memory claim and also records that no transfer model is
bound. F2C0 is plan-only and does not authorize another remote run.

F2C1 follows the selected family-local transfer design. A query family fixes
the semantic/operator shape, hard-constraint schema, backend artifact roles,
candidate-plan space, and compatibility versions while instances vary explicit
hard bindings and selectivity. Memory remains isolated by method and family;
held-out instances of seen families may reuse compatible history, but a
held-out family must start cold. Cross-family transfer is not part of the first
paper method and cannot occur as a fallback heuristic.

Freeze a 30–50 query hand-verified federated workload before importing a large
external benchmark. Vary data skew, latency, schema overlap, source count, and
failure injection. Report answer correctness, P50/P95 end-to-end latency,
bytes, remote calls, coordinator CPU/memory, planning overhead, LLM calls and
GPU-seconds, replans, and recovery rate.

The UI is optional and must consume the same goal/trace/artifact API as the CLI.
It is not an acceptance dependency for M15-B through M15-E.
