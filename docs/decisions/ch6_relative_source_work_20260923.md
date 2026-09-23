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
