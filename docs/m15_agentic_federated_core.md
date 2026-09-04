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

Status: **LOCAL LIVE CONTRACT IMPLEMENTED; REAL BACKEND GATE PENDING**

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
- a fail-closed live runner that invokes the existing real Neo4j and Fuseki
  clients through backend plugins and persists semantic, plan, health, result,
  validation, status, source-hash, and manifest evidence without retrying.

Local M15 verification: 40 tests passed and the one real-service test skipped.
Full acceptance passed with 512 tests passed and 35 live/external-artifact
tests skipped.

Remote execution is decomposed into explicit B0/B1 environment and CPU-smoke
gates before live services are started. See
[`docs/m15_remote_execution_loop.md`](m15_remote_execution_loop.md). These
gates distinguish the previously exercised legacy M13 CWRU/vLLM path from the
still-unverified M15 server path.

B0 artifacts established an exact checkout, working Slurm, visible
`gpu2h100`, and an existing vLLM environment. Loading the CWRU `Miniconda3`
module supplies Python 3.11.5. The separate user-owned `xgap-core` environment
now contains pytest and the server checkout is clean; B0 must be rerun at the
next exact commit before B1 submission. Podman was visible on `hpc5` but no
container runtime was visible on `hpc7`, so the B1 compute-node artifact—not a
login-node assumption—will determine the B2 packaging path.

Acceptance gate:

1. neither backend alone can answer the complete question;
2. the coordinator returns the hand-verified answer from both backends;
3. all remote calls, transferred bytes, intermediate cardinalities, and local
   join time are persisted;
4. no LLM or ontology is required;
5. offline tests remain independent of live services, and live tests are
   explicitly gated.

## M15-C — Nontrivial plan space and observation tools

Status: **PLANNED**

Add backend `inspect_schema`, `explain`, `profile`, and `sample` plugins, plus
alternative fragmentations, pushdown, join orders, hash/bind/semi joins,
parallel scheduling, and fragment fusion.

Acceptance gate: at least one workload has multiple correct executable plans,
and the selected plan changes under controlled cardinality or latency changes.

## M15-D — Memory-guided adaptation and replanning

Status: **PLANNED**

Use versioned capability and execution memory across tasks, and permit explicit
within-query replanning after observations invalidate the current estimate.

Required baselines: static federation, no memory, no profile/probe, no replan,
and full agent.

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
