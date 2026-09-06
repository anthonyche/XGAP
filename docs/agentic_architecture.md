# XGAP Agentic Federated Architecture

## System objective

XGAP is a cost-aware agentic federated graph-query system over heterogeneous
black-box engines. Given a user goal and a partially bound semantic graph
program, XGAP jointly chooses:

1. information-acquisition actions, such as schema inspection, entity or
   predicate resolution, user clarification, cache lookup, LLM invocation,
   sampling, and profiling; and
2. execution actions, such as backend-fragment compilation, remote execution,
   exchange, coordinator joins, materialization, and replanning.

The primary optimization objective is end-to-end cost, including planning,
LLM, remote execution, network transfer, and coordinator work, subject to
semantic validity, answer-quality, hard-constraint, resource-budget, and
termination requirements.

Cross-platform execution is the operating environment. Ontologies, catalogs,
LLMs, and clarification are optional tools. Removing any one of them must not
make the deterministic federated execution core undefined.

## Agent contract

### Environment

An XGAP environment contains:

- a user/session and an optional clarification channel;
- heterogeneous graph engines exposed only through declared tools;
- a coordinator with finite CPU, memory, network, and time budgets;
- optional schema, catalog, ontology, and identity-alignment services;
- optional local or remote LLM endpoints;
- changing backend availability, latency, load, cardinality, and schema
  versions.

XGAP treats Neo4j, Fuseki, and future systems as black boxes. It does not
modify their internal optimizers. Native `EXPLAIN` or `PROFILE` output is an
observation, not an XGAP-owned storage-level physical plan.

### Observations

The agent may observe:

- the natural-language request, session state, and declared hard constraints;
- available tool specifications and backend capabilities;
- schema, catalog, ontology, and memory results;
- compiler failures and unsupported-feature reports;
- estimated or observed cardinality, latency, bytes, rows, and resource use;
- backend errors and availability changes;
- user clarification answers.

Planning observations are collected through an explicit finite request tuple.
Every request names a registered `profile` or `sample` artifact, backend,
observation key, and call ID. All local cost-model parameters and uniqueness
constraints are validated before the first backend call. Requests execute once
in declared order, stop at the first non-success, retain partial tool evidence,
and produce a snapshot only when the complete tuple succeeds.

### Tools

The initial tool vocabulary is grouped by effect:

- semantic: `inspect_schema`, `resolve_entity`, `resolve_predicate`,
  `ontology_lookup`, and `ask_user`;
- backend: `healthcheck`, `inspect_schema`, `explain`, `profile`, `sample`, and
  `execute` through a backend plugin;
- coordinator: `align_ids`, `hash_join`, `bind_join`, `semi_join`, `union`,
  `materialize`, and `merge`;
- experiment control: `remote.executor` with typed stage, submit, status,
  bounded-log, artifact-fetch, and separately enabled cancellation actions;
- model: a bounded structured-candidate call through the existing
  OpenAI-compatible provider.

Only registered and goal-allowlisted tools can run. Every call returns a typed
success, error, or unavailable observation. Tool errors are never silently
retried.

The remote executor keeps credentials in the user's SSH configuration, stages
only an exact 40-hex commit from an explicit branch, submits only allowlisted
Slurm scripts, confines logs and artifacts to configured roots, and disables
cancellation unless separately opted in. It treats scheduling as an external
agent action, not as a graph backend's internal physical operator.

### Memory

Memory is typed and provenance-bearing:

- session memory: confirmed entity/predicate bindings and user decisions;
- schema memory: versioned backend schemas and capabilities;
- execution memory: observed latency, cardinality, bytes, and failures;
- cache memory: reusable semantic fragments, plans, and results.

Records carry a source, version, confidence, and optional expiry. Conversation
text alone is not authoritative system memory. The reference store is
in-memory; experiment runs may use the single-writer append-only JSONL store so
cross-task snapshots survive process boundaries without deleting prior values.

### Executable query-family admission

Family-local memory is available only after a query family passes one
reconstructable package contract. The package binds a typed semantic DAG,
binding and constraint schemas, registered backend templates, deterministic
instances and per-instance oracles, semantic alternatives, physical
candidates, split-safe views, and a family-memory policy to one compatibility
identity. A label alone never grants memory compatibility.

Package compilation is a deterministic validation action: it verifies source
hashes and regenerates derived artifacts without contacting a backend, LLM, or
ontology service. A family declared entirely held out may not expose its own
training records. This keeps the seen-family transfer and cold-family fallback
conditions explicit before a multi-family experiment is scheduled.

### Selective semantic resolution

M15-E1 routes unresolved semantic holes through the same finite goal loop and
typed tool boundary as backend work. A fully bound program terminates with no
tool or model call. Entity ambiguity is a distinct identity problem: a bounded
catalog may supply identity candidates, but more than one candidate requires an
authoritative user-clarification result and is never sent to an ontology or
LLM. Predicate and type candidates may be narrowed by a versioned ontology and
then by an optional bounded model proposal; source candidates may use catalog
and optional model evidence.

Resolution tools return candidate identifiers, provenance, latency, token, and
external-call counts. An LLM may select only from the identifiers in its
request, cannot mark a binding authoritative, cannot return native query text,
and may make at most one external call in one M15 tool invocation. Its result
remains a proposal for deterministic interpretation enumeration and validation.
Hard constraints are content-hashed before every action and are never mutated
by the resolution policy. A missing required clarification or candidate source
blocks explicitly; an unavailable optional ontology/model leaves the existing
bounded candidate set visible rather than masquerading as resolution.

### Actions and termination

The agent may construct or fill a semantic program, inspect the environment,
bind or partition fragments, invoke tools, schedule work, observe results,
update memory, replan, ask the user, return an answer, or fail explicitly.

Every goal declares success criteria, a tool allowlist, a step budget, and a
tool-call budget. The loop terminates as `succeeded`, `blocked`, `failed`, or
`budget_exhausted`; it cannot continue indefinitely.

## Typed plan layers

XGAP uses separate namespaces and contracts rather than one untyped workflow
graph.

### Semantic Graph Program

The v0 backend-independent query/dataflow operators are:

- `Match`
- `Traverse`
- `Filter`
- `Join`
- `Union`
- `Aggregate`
- `OrderLimit`
- `Project`
- `Align`

Each node declares typed inputs and output, constraints, parameters, required
capabilities, and stable identity. Programs are DAGs and may contain typed
entity, predicate, type, or source holes.

`PathPatternQuery` remains a rigorous path-expression sub-IR and may be carried
by `Traverse`. It is not the complete interpretation or the top-level agent
plan.

### Agent/control actions

Control actions include `Inspect`, `ResolveEntity`, `ResolvePredicate`,
`Clarify`, `Relax`, `Probe`, `Profile`, `Bind`, and `Replan`. A UI may display
the umbrella label `ResolveAmbiguity`, but the executable plan uses typed
primitive actions so their semantics and cost remain observable.

Hard constraints can never be relaxed. Entity-identity uncertainty may require
clarification even when an ontology exists.

### Federated Execution Plan

The coordinator-level runtime vocabulary includes:

- `RemoteQuery`
- `RemoteBindQuery`
- `Align`
- `Exchange`
- `CoordinatorJoin`
- `CoordinatorSemiJoin`
- `Merge`
- `Project`

This is called a federated execution plan rather than a database-internal
physical plan. Each `RemoteQuery` invokes a backend interface; the selected
backend remains responsible for its internal physical optimization.

Adaptive execution may first run an ancestor-closed common prefix. Before any
probe call, every prefix node must be structurally identical in every candidate
plan. A successful prefix can seed exactly one continuation, preserving its
rows, latency, transfer, and call accounting; it is not executed again. A
failed prefix is evidence and cannot silently select a fallback.

The live development gate accounts for planning and query work separately.
Its current M15 contract performs three registered planning observations and
then at most two query-time remote calls. A fixed, explicitly uncalibrated
coordinator cost configuration is suitable only for exercising the control
path; paper experiments require a separately frozen calibration protocol.

## Compatibility with the existing system

The audited `xgap.algebra` path and focused-binding semantics remain unchanged.
Existing `PathPatternQuery` lowering, capability profiles, bounded compilers,
backend clients, cost observations, LLM provider, and reproducible experiment
artifacts are reusable substrates.

The new mainline adds `xgap.semantic`, `xgap.tools`, `xgap.agent`, and later
`xgap.runtime`. Legacy M11 placement search and M13 semantic experiments remain
available as baselines until the new executable federated path supersedes them.

## End-to-end target loop

```text
User goal + session
  -> partially bound Semantic Graph Program
  -> observe environment, tools, and memory
  -> choose information or execution action
  -> invoke typed tool
  -> record observation and cost
  -> bind / fragment / execute / replan
  -> repeat within budget
  -> answer, clarification request, explicit failure, or budget exhaustion
```

LLM invocation is one optional action inside this loop. The easy-query fast
path must be able to complete with zero LLM calls.
