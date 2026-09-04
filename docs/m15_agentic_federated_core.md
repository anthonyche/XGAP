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

Status: **LOCAL COORDINATOR IMPLEMENTED; LIVE BACKEND GATE PENDING**

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
- typed `RemoteQuery`, `Align`, `Exchange`, `CoordinatorJoin`, and `Merge`
  runtime nodes;
- validated finite execution DAGs with remote-call and parallelism budgets;
- parallel execution of independent remote nodes;
- deterministic coordinator alignment, exchange accounting, hash join, merge,
  failure propagation, and skipped descendants;
- a `runtime.execute_plan` agent tool that returns rows and measured runtime,
  remote-call, and transfer metrics;
- an offline split-fact fixture where the complete answer requires both
  backend plugins.

Local verification: 20 focused M15 tests passed; full acceptance passed with
492 tests passed and 34 live/external-artifact tests skipped.

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
