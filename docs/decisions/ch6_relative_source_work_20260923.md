# Frozen relative source-work ranking and safe rewrite composition

## Trigger and boundary

D2 native v3 chose a shared full-edge scan and exceeded the existing Neo4j
transaction memory ceiling. The old tiny-trained model gave weak/zero weight to
large edge scans. Correcting transmitted-key units alone cannot fix that missing
signal. Preserve its frozen model, failed receipts, and original sample.

The new **opt-in** `xgap-relative-source-work-v1` is an analytic ordering model,
not latency regression, an oracle, or a feasibility/approximation guarantee.
Its initial target is the authored node/one-edge Match core (including D2's
multi-Match joins), not arbitrary bounded-path compiler artifacts. Unsupported
operators fail explicitly; incompatible structural/ms fallback scores are refused.
Do not activate it for D1/D3 bounded paths without admitting that coverage.

## Inputs, units and algorithm

Freeze complete per-source node/physical-edge counts, source snapshot identity,
the materializer's unique `id`/`xgap_id` contract, and `record_quantum=1024`.
No answers, observed winners, measured durations, query IDs, or native query text
enter its score. The source-only publisher does not read queries or refit weights.

A topological pass propagates row proxies and typed unique-column provenance.
Full scans always incur their complete population's work. A proved identity
equality may lower output rows without pretending its full scan is free. Binds
use capped transmitted-key counts and uniform mean degree; joins use declared
key preservation or an explicit heuristic for many-to-many output. Predicted
key overflow adds a source-work penalty. This is a heuristic warning, not proof
of runtime overflow or a reason to silently truncate answers.

Score = remote calls + (scan + returned rows + keys + overflow penalty)/1024
+ coordinator input rows/(10*1024). These are **declared relative work units**;
`estimated_ms` remains null. Acquisition prices remain separately declared in
the common objective; wall time is measured only during actual execution.
No score coefficient is fitted to D2 pilot outcomes.

For V nodes, E dependencies, B sources and bounded descriptor size S, the pass
is O(V log V + E + B + S) (the initial deterministic queue is sorted).
This leaves the existing fixed-depth, bounded-plan online search unchanged.
It promises neither global optimality nor a multiplicative quality bound.

## Correctness fix discovered by one-plan testing

Applying a semantic Match's mandatory equality **after physical read sharing**
could restrict another Match served by that read. The old proof covered only
the original consumer graph. A shared native read now declines this single-
consumer prefilter. Final filters/joins remain. The tiny D2-shaped replay uses
a distinct-user witness and parallel edges, chooses one plan with the new
ranker, and matches the independent SQL answer. This is a real composition fix,
not an estimator-quality assertion or a reason to rewrite old results.

## Admission and evidence

`prepare_ch6_relative_work.py` writes a new estimator/profile/seal while retaining
the same stores. `inspect_ch6_core_planning.py` can rebind a presampled bundle
only when all non-estimator execution inputs match. Its selection diagnostic
executes zero native plans, reads zero reference rows, and is explicitly **not**
a backend admission. Only a subsequent one-selected-plan real gate can admit it.

Focused validation: 27 source-filter/sharing/ranker tests passed; after adding
source-profile rebinding and zero-execution diagnostics, 9 ranker/necessary-bind
tests passed. No full regression, model call, or baseline tuning was performed.
Real D2 admission remains pending; do not claim the memory bottleneck is fixed.

Remote diagnostic 3858096 (`b5005f2`) completed in 7 seconds: all 8 original
D2 native pilot cases selected plans with zero **unbound edge-read nodes**,
and 3–4 bound reads. This is a symbolic plan property, not a measured database
scan count, latency, answer result, or proof that the engine uses an index.

Native bindings also now use a compiler-owned, text-hash-checked insertion point
to apply the identical canonical-ID predicate before the innermost DISTINCT.
The final outer identity predicate remains. Legacy/wrapped text with a different
hash retains the old correct wrapper; arbitrary Cypher is never parsed or edited.
This addresses an execution barrier in the generated query; 9 focused native
identity/bind tests passed, while real Neo4j execution remains the next gate.

The real v4 gate (3858143, `180632c`) failed on the original first question:
`cq5/native` timed out, 4 backend calls, about 78.93 seconds total execution.
The previous transaction-memory exception was not observed in this replay;
this is not yet a successful memory/performance/correctness result. The read
observer retained about 14.55 MB of completed response bodies. Failure preserved
under `formal-unified-admission-v4/D2/native`.

The next bounded compiler revision also places a node-only endpoint subquery
before the edge MATCH for source/target binds. It returns each matching endpoint
once, then expands from that bound variable; the identical inner and outer
identity predicates remain. This exact local semijoin does not promise an index
seek or bypass the existing limits. Node/edge-identity binds retain their previous
path. Four targeted compiler/identity checks pass; real replay remains necessary.

The analogous RDF boundary is now explicit as well: new compiler-owned artifacts
place a parameterized VALUES block on the original node/edge variable inside the
innermost BGP, before projected subqueries. Placing VALUES only outside nested
SELECTs is logically correct but need not restrict the scan early. Exact text
hash and variable provenance gate the rewrite; modified/legacy text keeps the
old correct wrapper. Existing escaping, key/byte caps and overflow rejection are
unchanged. Seventeen focused physical strategy/identity/necessary-bind tests
passed, including actual tiny RDF answer equivalence and one-selected-plan
execution. This does not substitute for the forthcoming real Fuseki gate.
