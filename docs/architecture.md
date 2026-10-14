# Architecture

The primary entry point is `xgap.api.answer_unified`. It combines semantic
interpretation with bounded physical planning and one final execution over
Neo4j and Fuseki. `answer_unified_controlled` uses the same controller from an
explicit initial state, without the natural-language initialization step.

## Request flow

1. A proposal provider uses a frozen source schema and public finite domains to
   propose a bounded candidate family.
2. The declared authority confirms scope and supplies required binding validations.
   Model output and catalogs cannot attest user intent.
3. Protected seed plans and source capability evidence establish a completion route.
4. The online controller compares eligible final plans, information actions, and
   checked local rewrites using fixed-depth lookahead.
5. One selected action is performed and metered; the controller updates its actual
   state and replans. Hypothetical lookahead makes no external calls.
6. The runtime checks the final contract and executes one selected plan, returning
   materialized rows and an observed execution trace.

## Contracts

`Lambda` identifies validations allowed to remain unresolved. `epsilon` bounds the
implemented discrepancy between structured queries over the confirmed finite
family. Neither parameter turns the system into a different algorithm. Hard fields
never relax, mandatory validation does not disappear for singleton candidates, and
query discrepancy does not bound answer error.

The controller retains protected seeds and reserves a completion recipe for every
outcome, including unknown and zero-probability outcomes. Unknown resource bounds
cannot certify a finite budget. On an optional search deadline, incomplete action
scoring cannot replace the completed fallback.

Pure symbolic lookahead may reuse completed subtrees within one decision. Cache
keys include the full state, resource consumption, action count, retry ledger,
remaining search depth, and the physical registry epoch. Partial searches are
never cached, and observations start a new decision. The bounded registry and
mandatory completion checks remain in force.

The NL and controlled unified entries share a bounded, request-local lowering
cache between seed preparation and physical transformations. It freezes the
public schema and language version, keys by the complete compact query, and
returns isolated copies. Neither authority replies nor query answers are cached.
The controller separately caches frozen base-plan predictions and fact-dependent
adjustments; a new probe observation still changes the adjusted score.
The v5 relative-work model also shares a bounded request-local subplan-estimate memo
(2,048 entries / 16 MiB serialized representation). Its dependencies include
parent estimates, typed parameters, source snapshots and scoped probe categories;
changing a fact invalidates dependent subplans. It never reuses query answers.

`FrozenSourceWorkRanker` v4 optionally prices estimated returned bytes using
frozen per-source mean row sizes and an explicit `transfer_byte_quantum`.
Scan work, binding work and coordinator work remain separate. This is a source
average proxy, not wire-byte measurement, calibrated latency or a resource bound.
Complete row-size statistics are required. Omitting the byte quantum preserves
the original v1-v3 schema, arithmetic and rankings; existing artifacts do not
silently adopt the new cost model.

`FrozenSourceWorkRanker` v5 is selected with `cardinality_aware=True` and
optional `ColumnSynopsis` entries in `column_synopses`. These are source-owned
snapshot statistics: rows, nulls, NDV and at most 256 heavy-value frequencies per
column. Column names are `node:property:<name>`, `node:entity`, or
`edge:<label>:source`, `edge:<label>:target`, `edge:<label>:property:<name>`.
`domain` declares compatible key encodings across sources. Statistics cover the
source population, not gold answers or measurements of a selected evaluation query.
Filters propagate frequencies through normalization and projections. Joins use
heavy-value overlap and uniform residuals, falling back to NDV when frequencies
are unavailable. Residual range selectivity and unmodeled inter-column dependence remain
heuristics; source scan work is not silently reduced by returned-row selectivity.
Native contracted SPJ plans retain their separate cost model.

Version 6 adds up to 1,024 `JointSynopsis` groups of 2–4 columns, each with
up to 256 frequent tuples and a residual population. Successive predicates use
joint tuple mass instead of multiplying independent marginal selectivities.
Conditioning also updates marginals used in downstream join estimates. Missing
joint groups, residual mass and dependencies between overlapping groups remain
heuristic; observed frequencies are not a certificate or a worst-case bound.

Source plugins prepare these models through
`planning.source_statistics.collect_source_statistics`: a complete, query-independent
`SourceRecordStream` contains node/edge records with canonical column keys and
comparable domains. Frequency counting uses temporary SQLite state; bounded MCVs,
NDVs, null counts, endpoint degree moments and average record sizes enter the
frozen model. Declared unique properties are checked against complete populations.
No gold answers or evaluation-query outcomes are read. Export snapshot consistency
and complete enumeration are the dataset plugin's responsibility.

Both unified entries accept `source_statistics=model_or_local_json_path`. Native
backend descriptors may instead declare one common `statistics_catalog_path`.
The entry verifies the model hash and exact active source/snapshot identities
before interpretation, then uses it in the existing planning and probe-cost
chain. An explicit estimator remains supported; supplying both is rejected.
Statistics acquisition never happens implicitly while answering. Without a
configured model the existing fallback estimator remains in effect. Catalogs are
pluggable local metadata and are not published with private dataset contents.

For v5, scoped probe categories update Match output cardinalities and downstream
work instead of adding a second row-cost penalty. Before observing a category,
the controller averages **costs of outcomes**, not the cost of average rows;
otherwise nonlinear costs can create fictitious information value. Unknown
observations retain the prior. Independent declared target priors are factorized
with at most 256 conditional scenarios; larger models fail explicitly. Probe cost
is still paid by the controller, and hypothetical scenarios do not execute tools.
Probe predicates and source snapshots must match the physical read. Predicates
already included in the observed count are not discounted twice; an incompatible
rewrite cannot reuse that count through the historical additive penalty.
Historical v1-v4 artifacts retain their original numerical model.

`agent.unified_family` manages bounded candidate and plan pools.
`runtime.unified_physical` generates individual checked transformations.
`agent.unified_information` handles registered information actions. Only selected
actual actions enter paid accounting. Backend and transport failures remain
explicit outcomes rather than successful empty answers.

The runtime preserves directed edge semantics, scalar identity, row lineage, and
join/filter/aggregation behavior. Binding restrictions and native pushdowns must
carry sufficient equivalence evidence. Approximate truncation is not a valid
replacement for exact query semantics.

The scheduler advances ready descendants as individual remote tasks complete,
without a barrier across unrelated sources. Submitted remote tasks are bounded
by the plan's parallelism; coordinator operations remain serial. Each remote
task receives a snapshot of its declared inputs, and intermediate payloads are
released only after all consumers finish. Result records retain plan order even
when task completion order differs.

Both unified entry points accept `execution_limits=ExecutionLimits(...)` from
`xgap.runtime.execution_limits`. Optional `per_backend_parallelism` limits active
tasks for each backend ID independently of global plan parallelism.
`max_registered_bytes` rejects a result that would exceed the registered payload
budget and stops downstream dispatch, rather than returning a truncated answer.
It measures serialized payloads, not process RSS or in-flight buffers.
`dispatch_timeout_s` is measured from final execution start and stops new work;
already running calls receive the same request cancellation control, and native
HTTP clients reduce transport timeouts to remaining execution time. Fuseki also
receives its protocol `timeout` in seconds. Capability-aware clients implement
`execute_controlled(artifact, control)` and register a prompt, invocation-specific
callback with `control.cancellation(callback)`. Cancellation receipts preserve
adapter acknowledgement or failure. Native HTTP response reads interrupt their
own socket where supported; closing a socket does **not** prove database-side
termination. Legacy adapters without a cancellation capability drain before return.
These are final-execution controls, not a certified end-to-end wall-time bound.

Unified final execution now uses `StreamingScheduler`: native HTTP row arrays
are incrementally decoded into request-owned replayable stores, then converted
row by row after the complete response envelope passes validation. Every local
operator consumes rows incrementally. Exact distinct, joins, aggregation, sort,
path selection and finite recursion keep blocking state on disk. Stores allow
DAG fan-out without another backend invocation and are released after the last
consumer. Root answers are materialized for API compatibility; operators currently
seal their output before dependent operators run, rather than overlapping all
stages of a pipeline. Third-party list-only clients retain an explicitly recorded
materialized fallback. The historical scheduler remains available separately.

SQLite page caches are bounded per store. `max_spill_bytes` (default 1 GiB)
bounds the accounted SQLite database pages across request-owned stores and fails
instead of truncating results. It excludes SQLite temporary sorter files,
individual JSON values, database process memory and final answer lists; it is
not a process RSS or total filesystem quota. `max_registered_bytes` and
`max_response_bytes` remain separate admission controls. Disk-backed execution
reduces intermediate heap retention but can increase latency and scratch I/O.

The streaming Neo4j adapter opens an owned explicit transaction, executes the
artifact once, and commits or rolls it back. Cancellation acknowledges only a
successful database rollback response; handles must remain on the configured
origin/database. Transaction begin/commit/rollback HTTP calls are separately
metered as `database_control_http_calls`, not hidden in query-call counts.
Fuseki confirmation uses the optional [owned-query extension](../services/fuseki-cancel/README.md).
It aborts the registered `QueryExec` and waits for the query lifecycle to close
and end its read transaction. Ordinary Fuseki continues with protocol timeouts
and socket interruption, explicitly lacking confirmed-cancellation capability.
Neither client invents confirmation on missing, failed or mismatched receipts.

## Implementations and evaluation support

`src/xgap/experiments` contains reusable data preparation, evaluation contracts,
reference scorers, process supervision, and source observations. `scripts` exposes
supporting execution and service-management entry points. These are implementation
utilities; generated results and machine-specific run packages are not distributed.

The default, no-probe, shallow, and myopic settings share semantic eligibility and
completion guards. Different deployment support and measurement boundaries must
remain explicit when comparing configurations. The legacy APIs retain separate
identities for compatibility.

## Limits

This is a bounded research prototype. It does not promise arbitrary natural-language
coverage, global optimality, or successful execution under every backend failure.
The portable demo demonstrates a small synthetic graph. It is not evidence of
large-workload performance or backend readiness on another machine.
