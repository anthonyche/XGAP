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

The v5 real gate (3858218, `9e56a15`) also failed at the first question.
The last source call bound 197 movies and returned a partial 23,618-row response
with `Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration` at
about 60.3 seconds. Do not use the partial rows as an answer. Thus the endpoint
rewrite alone has not established the required large-source performance.

The next infrastructure check uses a declared private node-local serving copy,
with the same immutable stores, query, plan selection, heap, worker/transaction
limits and answer reference. Frozen inputs and durable query/closure logs stay
on research storage. Source storage is a common deployment parameter for all
methods, not an XGAP-only advantage; old NFS timings are not paired speedup data.
Setup may have a separately declared longer copy deadline; this is offline time,
not a relaxation of the 60-second source query or 120-second worker bounds.

`copy_sealed_store` verifies hashes while copying each source byte once, instead
of a separate full verification read followed by copying. It checks exact member
inventory, sizes and hashes, rejects links and non-new/disjoint destinations,
and never starts a service on a failed copy. The guard counts durable evidence
plus the separate serving directory and checks free space on both filesystems.
Only reconstructable copies are removed after source quiescence; original stores
and all evidence remain. Seven focused copy/cleanup/accounting checks pass.

Local-serving gate 3858243 retained the native first-case timeout (about 75.55 s
whole execution, 4 requests). Thus storage placement alone does not solve the
fanout bottleneck. RDF gate 3858244 completed preparation but its first case
hit the 4 GiB aggregate source RSS guard after about 48.92 s; the two edge
requests timed out. The requests contained an inner VALUES row for a single
user, yet still consumed excessive resources. The output remains censored, not
an empty or incorrect answer.

For exact compiler-owned reified edge Matches, singleton endpoint binding now
adds the redundant triple `?edge source-or-target <key>` next to VALUES. Its
predicate comes from the frozen RDF edge encoding, adjusted for direction.
This exposes a literal index key without relying solely on late VALUES joining.
It is implied by the existing triple and the singleton binding; all original
constraints remain. Multiple/empty keys keep the existing query. The added
clause is included in the existing byte cap. Tiny execution equivalence plus
direction/key-cap tests pass; actual Fuseki benefit is still unverified.

The user requires D2 to pass before formal results. Source-side fanout, estimator
error and missing physical alternatives are now tracked separately. Reference
bank v2 (3858253) still timed out: EXPLAIN shows node-range Cartesian iteration
and global DISTINCT/ORDER sorting despite independent edge EXISTS predicates.
The independent reference now admits ordered adjacency enumeration for the exact
node-ID set projection fragment. It visits ID domains in declared lexicographic
order, seeds each domain from a bound incident edge, retains every conjunct and
stops only at the query's own LIMIT. All unanchored nodes must be projected, all
projected nodes must be ordered, and cross-edge predicates fall back to the
general evaluator. A single shared deadline and output cap remain; no partial
answer or sample substitution is allowed. Six focused reference tests pass,
including parallel edges, cycles, reversed ordering, 20,000 isolated nodes and
comparison with the original exhaustive relational evaluator on tiny facts.

RDF constant-anchor replay 3858266 passed the four presampled outgoing-maximum
cases with exact reference agreement. It then hit the source RSS guard on the
first incoming-minimum case. This isolates remaining witness fanout from the
previous singleton binding defect. It is not an eight-case admission pass.

## Existential leaf physical move

`contribution-leaf-witness-v1` admits only a degree-one witness node and its edge
that both disappear at the declared contribution projection. Every predicate
involving either must be enforced before selecting a representative; other
retained-variable dependencies, edge-property couplings, path cases, shared/union
reads and remote witness properties are declined. Only a mandatory string-ID
anchor may substitute another variable's ID. The original final filters, joins,
contribution projection and aggregation remain. Thus one *real satisfying edge*
per retained boundary identity preserves the exact joint contribution set; it
is not a result truncation or approximate answer. Parallel contributing edges
remain distinct. A witness depending on another unbound retained node cannot be
reduced this way (the outgoing-maximum case is explicitly declined).

Cypher uses bounded keys and a correlated subquery with LIMIT 1 per key. RDF
expands a finite UNION of singleton, constant-indexed subqueries with LIMIT 1 per
branch; the complete expanded request obeys the declared byte cap. Empty keys
return no rows, overflow fails, and no partial key set is executed. The RDF rule
also declines guards on potentially multivalued boundary properties. Each local
move changes one remote artifact; it can combine its proved mandatory bind with
the witness reduction without enumerating a plan product. At most O(J*N) checked
proposals are added, and wire generation is O(K*L) for capped key count K and
query size L. Only one selected plan is executed by the online controller.

The ranker recognizes the proven returned-row cap of one per key while retaining
its unreduced adjacency-scan proxy: result cardinality does not certify search
work or elapsed time. Tiny RDF end-to-end min/sum/count queries match the separate
SQLite reference. Real Neo4j 5.26.30 min/sum/count equivalents also pass in
`/Users/anthonyche/xgap-data/ch6-leaf-witness-native-20260923-v2/receipt.json`;
its private source was stopped. These are correctness gates, not speedup results.
The original failed v1 native gate receipt is preserved (the harness incorrectly
expected the deliberately inadmissible outgoing-maximum rewrite).

Remote planning-only diagnostic 3858292 selected the leaf move for all eight
incoming-minimum occurrences across the unchanged native/RDF pilot bundles;
all sixteen selected plans have zero full edge reads. It performed no backend
execution and read no reference rows. Large-source correctness and resource
admission remain separate gates.

## Endpoint-degree ranking and incremental reference checks

The opt-in `xgap-relative-source-work-v2` freezes source/target degree moments
separately for each stored relation and temporal view. A single offline pass
over the complete source index records rows, distinct endpoints, squared degree
sum and maximum. No query, answer, timing label or candidate winner is read.
Singleton-key work uses the endpoint mean; multi-key work uses the size-biased
mean as an explicit heuristic for edge-derived keys. Direction comes from the
typed compiler descriptor. These are ranking proxies, not certified cardinality
or latency bounds. Unknown many-to-many joins use a capped Cartesian proxy
instead of assuming their cardinality is just the larger input. The leaf's
proven output cap remains separate from its estimated scan work. Historical v1
models are unchanged. Rebinding requires identical source and query inputs.

Reference-bank v3 (3858282) still timed out for both deployments. EXPLAIN exposed
repeated scans of already satisfied edge predicates at each deeper prefix.
Ordered adjacency now checks each edge when all its dependencies first become
bound, and checks each node predicate when its last dependency is introduced.
Earlier prefix facts are retained by construction, so they need no revalidation
per neighbor. New cyclic constraints still run. Fifteen targeted estimator and
reference tests pass, including reversed endpoint skew, original relational
equivalence, descending order and untouched parallel-edge contribution grain.
No large-D2 success is inferred from these portable checks.

The subsequent native replay 3858296 passed all eight original cases on the full
20M source, with exact independent-reference agreement. Parent-observed case
wall times were 2.263–8.429 s and sampled source RSS stayed below 1.151 GiB.
RDF replay 3858297 passed the first four cases, but the fifth again crossed
4 GiB sampled RSS (4,302,888,960 bytes); the failed run is preserved.

An explicit RDF serving-only diagnostic now accepts `rdf_file_mode=direct`.
Default remains unchanged. Jena's [storage architecture](https://jena.apache.org/documentation/tdb/architecture.html)
distinguishes file mappings from Java heap, so heap caps alone do not bound
resident mapped pages. The installed Fuseki 5.6.0 CLI and TDB2 class were checked:
`--set=tdb2:fileMode=direct` selects direct file access. A real two-triple gate
opened the identical TDB2 store in default/direct modes, returned the same two
ordered answers, and verified `direct (forced)` in the source log:
`/Users/anthonyche/xgap-data/tdb2-direct-check-20260923-v1/receipt.json`.
The selection is recorded in the intent, serving profile and ready receipt.
Heap, source RSS, query time and worker limits remain unchanged. This is a
deployment diagnostic, not an improved baseline algorithm. Any adopted formal
serving configuration must be shared by all methods and frozen before comparison.
The original RDF failure is not yet attributed conclusively to mapped pages.
