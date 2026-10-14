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

Unified final execution uses `StreamingScheduler`. Native HTTP row arrays enter
small replayable memory buffers; the complete response envelope is validated
before downstream use. A remote result with exactly one immediate filter consumer
can apply that same typed predicate during reception, privately retaining only
matching rows. Every source row is still converted, validated and metered; filter
errors are deferred while the remaining response is checked. No retained prefix
is published if transport, envelope, typed conversion or cancellation fails.
Native arrays can bypass the raw spool when their column metadata precedes the
rows; other JSON member orders retain the validated spool fallback. The original
source and filter node identities, raw source counts/bytes and retrieval bounds
remain intact. Shared sources, raw root outputs, explicit registered-byte gates
and list-only adapters retain the original path. Reception filtering shares the
same intermediate memory/spill budget, and its timing belongs to source reception. Non-branching local operator islands execute as pull
pipelines: a consumer processes each available row without sealing every
intermediate result. Fan-out, native-response, binding-query and public-answer
boundaries remain replayable. Islands are capped at 64 operators to keep deep
plans independent of Python generator recursion limits. The original physical DAG, actual calls, per-node
row/byte counts and failure provenance remain visible; fused timing is reported
at each island boundary rather than inventing individual node CPU times.

`ExecutionLimits.intermediate_memory_bytes` defaults to 8 MiB per request.
Small result buffers, exact distinct keys, join indexes and compact aggregate
states share this budget with in-memory SQLite pages. A growing store promotes
its exact state and indexes to disk when its next accounted allocation does not
fit; it does not restart a source or truncate rows. Blocking sorts, DISTINCT
aggregates and finite path operations retain their blocking semantics. Non-DISTINCT
aggregates keep compact per-group states rather than all input members. Hashes
only index DISTINCT collision buckets: full typed equality still decides identity.
Request-local typed hashes avoid serializing complete canonical keys for each
lookup; unseen buckets use one indexed insert. These hashes are not persisted
identities. Join inputs can omit ordering while retaining exact DISTINCT and
canonical representatives; user-visible output ordering remains unchanged.
Replay stores create lookup indexes only when they receive keyed rows. Telemetry
counts exact canonical JSON bytes without constructing an additional whole-row
serialization. Compact aggregation keeps typed group keys in memory and promotes
integer sums to exact rational state only when a non-integer numeric value arrives.
A join feeding an order-insensitive aggregate, sort or merge can omit redundant
output DISTINCT only after observing uniform, non-overlapping non-key schemas
and exact distinct inputs. That proves pair-to-output injectivity; schema overlap
or variation retains the general exact algorithm. Root join ordering is preserved.

The memory budget accounts serialized buffers with overhead allowances and
SQLite pages. It excludes individual transient values, sorting-key arrays,
SQLite driver/cache overhead and final root answers; it is not an RSS ceiling.
`peak_intermediate_accounted_bytes`, `spilled_stores` and `peak_spill_bytes`
report accounted storage and memory-to-disk migrations. SQLite page caches are bounded per disk
store. `max_spill_bytes` (default 1 GiB) bounds accounted database pages, excluding
SQLite temporary sorter files; it is not a total filesystem quota. Registered
payload and native response budgets remain separate controls. Setting
`intermediate_memory_bytes=0` forces disk state for memory-constrained callers.

Third-party clients that only return lists retain an explicit materialized
adapter fallback; overriding `execute` is never bypassed by an inherited stream
method. Root answers remain materialized for API compatibility. Local operator
pipelining does not overlap unvalidated network responses or reorder user requests.
The historical materializing scheduler remains available for comparison.

`scripts/benchmark_execution_pipeline.py` compares a deterministic local
read/filter/join/group/sort chain without servers or model calls. Run latency
measurements without `--trace-memory`; measure Python allocations separately,
since tracing changes execution time. Use `--transport neo4j-json` to include the real native JSON parser and owned
transaction adapter over local file-backed transport doubles (no network or
database service). The script also reports process peak RSS
(including SQLite and imports), exact answers and actual backend-call counts.

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
