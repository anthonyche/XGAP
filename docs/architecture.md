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

`FrozenSourceWorkRanker` v4 optionally prices estimated returned bytes using
frozen per-source mean row sizes and an explicit `transfer_byte_quantum`.
Scan work, binding work and coordinator work remain separate. This is a source
average proxy, not wire-byte measurement, calibrated latency or a resource bound.
Complete row-size statistics are required. Omitting the byte quantum preserves
the original v1-v3 schema, arithmetic and rankings; existing artifacts do not
silently adopt the new cost model.

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
already running calls drain under their own transport timeouts before return.
It is not an end-to-end deadline or server-side cancellation. These controls
do not turn unknown symbolic resource bounds into certified finite bounds.

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
