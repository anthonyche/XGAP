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

Current local M15 verification passed 140 tests with two real-service tests
skipped. Full local acceptance passed with 612 tests and 36 explicitly gated or
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

Status: **LIVE ADAPTIVE RUNNER AND AUDITOR VERIFIED ON CWRU; SCALE/BASELINES PENDING**

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
and full agent. The no-replan control is implemented; the complete baseline
matrix remains pending. CWRU job `3787152` verified the real-backend adaptive
path, including its legitimate zero-replan branch on the tiny fixture.

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

Status: **PLANNED**

Freeze a 30–50 query hand-verified federated workload before importing a large
external benchmark. Vary data skew, latency, schema overlap, source count, and
failure injection. Report answer correctness, P50/P95 end-to-end latency,
bytes, remote calls, coordinator CPU/memory, planning overhead, LLM calls and
GPU-seconds, replans, and recovery rate.

The UI is optional and must consume the same goal/trace/artifact API as the CLI.
It is not an acceptance dependency for M15-B through M15-E.
