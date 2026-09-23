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

Full-source statistics job 3858302 completed in 2:02 (the statistics receipt
records 104.82 s offline). RATED has 20,000,263 rows, 138,493 source endpoints and
26,744 target endpoints; maximum degrees are 9,254 and 67,310 respectively.
Both native/RDF v2 selection diagnostics used the endpoint statistics and kept
all sixteen selected plans free of full edge reads. They made no backend/model
calls. No latency calibration or answer-based estimator fitting occurred.

Reference v4 retained every presampled case but still stopped at native zigzag
(4 references completed) and RDF cycle (22 completed). The remaining SQL plans
use single-endpoint indexes followed by table lookups and DISTINCT sorting.
`prepare_ch6_reference_workspace.py` therefore creates an offline SQLite copy,
verifies its complete original byte digest, and applies only covering indexes
on `(src,dst)` and `(dst,src)`. No rows are inserted, removed or updated. The
derived database and exact DDL are sealed separately; the publisher checks the
original source pin and derived file digest before any evaluation. Source
selection, profile, templates, queries and backend stores remain the originals.
This is independent reference preparation, not XGAP/baseline online work. Eleven
focused reference tests pass, including unchanged source digest, covering-index
use and identical answers for zigzag/cycle/parallel contribution queries.

The covering-index preparation 3858313 has completed the native 24-case test
reference bank (76.09 s including publication work), preserving the original
private preselection exactly. RDF references are checked separately.

RDF direct-file diagnostic 3858310 did not solve the fifth-case RSS failure;
4,301,688,832 bytes were observed. Keep this negative result and retain default
file access for the next compiler replay. Query inspection revealed that the
representative compiler placed an OPTIONAL leaf-property pattern before the
edge BGP. This creates a left-join barrier while the leaf is still unbound.
All admitted guards explicitly return false when the property is unbound, so
OPTIONAL plus that filter is exactly an inner property join. The compiler now
emits that mandatory triple, allowing the endpoint and edge patterns to join
before global property expansion. Missing values still cannot pass. Ten focused
leaf/bind tests pass, including complete RDF min/sum/count results against the
independent evaluator. Actual large-source replay remains required.

Replay 3858325 again hit the fifth-case aggregate source RSS guard at
4,300,443,648 bytes. The OPTIONAL correction did not establish a large-source
resource improvement. A read-only live observation of the owned graph JVM in
3858326 reported RssAnon=639,280 KiB (about 624.3 MiB) and RssFile=2,535,900 KiB;
the control JVM reported 160,752 / 24,296 KiB respectively. Thus aggregate RSS
cannot be described as anonymous intermediate-result memory alone.

The next **separate deployment diagnostic** preregisters a 16 GiB aggregate
source RSS guard within the existing 24 GiB Slurm allocation: 3 GiB remains the
worker guard and at least 5 GiB allocation headroom remains for orchestration.
The 60 s source / 120 s worker timeouts, 1.5 GiB aggregate JVM heap, data, queries,
default file mode and all byte/call caps stay unchanged. The historical 4 GiB
failures remain. This is a declared resource-contract revision, not algorithmic
speedup or evidence that the old contract passed. If adopted for formal runs,
the same source policy must be frozen for **all five methods**. Full campaign
budgets are not yet released. No GPU or larger Slurm allocation is requested.

The resource monitor now records optional Linux anonymous/file/shared RSS
components separately, with observation timing. File-backed pages still count
in the total guard; unavailable diagnostics are unknown, not zero. Seven focused
resource/common-trial tests pass. The admission default remains 4 GiB; the larger
diagnostic requires an explicit argument that is sealed in its intent.

The updated-ranker replay 3858326 also failed the fifth case at 4,297,252,864
source RSS bytes. The corresponding prior-ranker captured call 22 contains
567 singleton witness UNION branches (685,933 UTF-8 query bytes; 967,185 HTTP
body bytes). This identifies the failing operation, not its ultimate cause.
Resource diagnostic 3858334 uses code 15ddf66 and the frozen endpoint-degree
profile at `formal-endpoint-admission-v2/D2/rdf`, with the preregistered 16 GiB
source limit. All historical trials remain separate; no campaign is launched.

Further failure replay with the actual Jena 5.6.0 algebra optimizer exposed a
compiler cause: placing the mandatory leaf-ID triple before the edge BGP lets
ARQ move its filter onto a disconnected prefix consisting of only the constant
endpoint edge pattern and **all** leaf IDs. The connecting edge-to-leaf triple
then occurs after that filter. Removing OPTIONAL alone cannot prevent this.
The compiler now expresses the jointly satisfying ID value as a correlated
`FILTER EXISTS`. The ID scalar is absent from the DISTINCT edge/endpoint
projection, so this is an exact semijoin, including multivalued properties;
missing properties still fail. Jena's optimized algebra now binds the leaf
through the edge before testing that local existence condition.

Local diagnostic artifacts: `xgap-data/ch6-rdf-leaf-algebra-20260923-v1/`, with
both queries and both optimized algebra dumps. This is a structural diagnostic,
not a measured large-source speedup. Ten targeted tests pass, including complete
min/sum/count answers against the independent reference. The follow-up replay
will retain the original 4 GiB source guard to separate this compiler fix from
the already-running resource diagnostic. No new dataset/case selection occurs.
The [Jena optimizer documentation](https://jena.apache.org/documentation/tdb/optimizer.html)
describes filter placement and algebra inspection; the observed algebra above,
not the documentation alone, establishes this particular disconnected prefix.

Resource-only diagnostic 3858334 failed at the same fifth case: the source
request reached its 60 s timeout although the enlarged RSS budget was not hit
(source sampled peak 6,856,650,752 bytes; worker observation 64.393 s).
At the last sample, the graph JVM had 778,731,520 anonymous and 5,859,815,424
file RSS bytes. Increasing the resource allowance alone is not a solution and
the 16 GiB diagnostic is not adopted as a new formal default.

Correlated-guard replay 3858337 uses code 52d2ec6 and the original 4 GiB source
limit at `formal-endpoint-admission-v3/D2/rdf`. A separate Jena synthetic replay
with 5,000 user nodes and 32 bound movie keys returns the identical one-row
answer before/after (1.374 / 0.629 s including JVM startup; a diagnostic, not a
paper performance claim). An additional regression checks missing properties,
excluded-only values, multiple property values, parallel witness edges and a
valid but unrelated node: only the actual connected satisfying witness survives.

3858337 completed the first four cases but still timed out on case five
(64.644 s worker observation). The source peak was 3,801,321,472 bytes, below
the original 4 GiB guard: memory expansion was reduced, but admission still fails.
Receipt SHA-256: `bb0b1c5e25a5d7b337090a20c528d3768a0ca7fafc87297ab6b8230eb8550d3f`.

A separate 567-key Jena 5.6.0 optimizer replay found that the flat UNION chain
exhausts a 512 MiB heap; an equivalent balanced UNION finishes optimization in
1.52 s. The binder now builds a balanced associative UNION tree, leaving the
per-key LIMIT inside each branch and keeping the outer DISTINCT. No key, row
contract, request count or budget changes. Expanded query length remains O(KL),
construction work is O(KL log K), and UNION depth is O(log K); the final complete
request still must pass the byte guard. Twelve focused tests pass, including
independent algebra-depth inspection and all 65 keys surviving a two-witness
graph (with duplicate input keys). This is not a full-source performance claim.

Qualification: that 512 MiB failure is specifically the `arq.qparse
--print=optquad` diagnostic path. Normal `arq.arq` execution on the same
synthetic 567-key input succeeds for both flat and balanced forms (one identical
answer; 1.150 / 0.926 s including startup). Therefore it does **not** establish
the cause of the server timeout. The full-source fifth-case receipt records
only 9.96 sampled source CPU seconds over 64.64 s wall time. Replay 3858348
(`ec4c61f`, `formal-endpoint-admission-v4/D2/rdf`) keeps original resource caps
and permits one read-only thread dump of its own graph JVM if case five runs
longer than ten seconds; diagnostic intent/output lives in `formal-rdf-debug-v1`.
This instrumentation must not be included as formal method performance data.

3858348 also timed out at case five (64.508 s, source peak 3,950,854,144 bytes).
The owned-thread snapshot is inside TDB2 tuple-index/B+tree access, not query
upload or socket setup. A single-branch algebra inspection with the actual
server jar succeeds and confirms the correlated guard. It also shows several
separate filtered BGP stages. The next bounded diagnostic 3858351 uses a verified
private graph-store copy and exactly the first 1 and 16 branches of the captured
failed request, each capped at 20 s / 4 GiB / 4 MiB logs, with TDB execution
explanation enabled. It is **failure replay only**, not a replacement workload,
not a new evaluation subset, and its observations never enter the estimator.
Evidence root: `formal-rdf-point-debug-v1`. No full pilot resubmission is made
without a new diagnosis/fix.


3858351 completed successfully: 1 / 16 actual witness rows; guard wall times
5,384.310 / 16,143.982 ms; sampled peaks 151,674,880 / 218,890,240 bytes.
These include JVM startup and verbose execution logging and are not comparable
formal latency measurements. The trace contains eleven execution stages per
branch, including redundant correlated positive edge-label predicates.

The one-edge reified compiler now expresses positive atomic node/edge labels
as mandatory constant-object triples and deduplicates an identical edge-label
triple already emitted by the edge pattern. Each triple adds no new variable,
is true exactly when the old EXISTS is true, and has at most one match for each
bound row in an RDF graph. Composite/negative predicates and multi-edge code
keep their existing Boolean compiler. Conflicting labels are retained.
Twenty-nine focused tests pass (including independent RDF execution, conflicting
labels, OR/NOT, both label encodings, leaf-property cases and balanced binds).
Actual Jena optimized algebra now has one continuous edge/label BGP followed
by the correlated property guard, rather than several filtered stages.
Full-source validation retains the original cases and resource caps; this is
a compiler optimization candidate, not yet a proven D2 latency improvement.


Full-source label-join replay 3858362 (`d41267c`) still fails on case five
with the 60 s source timeout (64.538 s worker observation, sampled source peak
3,835,154,432 bytes). First four cases remain EM=1. Receipt SHA-256
`62e1c47521e09bc97f0a21e6bbe6e53c17eb67c932e25f0f28197aa8e1021c47`.
The patch is semantically verified but has not removed the admission blocker.

Next diagnostic compares the first 16 captured branches with an ARQ LATERAL
representation, then all 567 captured keys under 60 s / 4 GiB per request.
It uses a private verified graph copy and no model calls, not a new evaluation
subset. Jena's documented correlated per-row LIMIT is tested separately from
portable SPARQL; nothing enables the extension for other backends by default.
Local Jena 5.6.0 synthetic 32-key execution matches the previous exact one-row
result (0.793 s including startup, not a speedup claim).
Reference: https://jena.apache.org/documentation/query/lateral-join.html .


3858371 completed the diagnostic suite (`formal-rdf-lateral-debug-v1`):
16-key UNION 28.955 s / 198,606,848 bytes peak; subsequent 16-key LATERAL
1.826 s / 192,094,208 bytes, with identical 16 actual rows/target keys.
Both include fresh JVM startup, share an OS page cache and run in fixed order,
so the ratio is not a controlled speedup. Full 567-key LATERAL hit the 60 s
guard (60.139 s; 786,202,624 bytes); no complete result was emitted.
No production LATERAL profile is enabled from these observations.

A second failure-only diagnostic removes redundant nested projections and
DISTINCT barriers from this scalar-free three-column witness relation, comparing
flat 16/567-key LATERAL and flat 567-key UNION. All leaf guards/positive labels,
actual edge identity and per-key LIMIT remain. The same local independent
32-key synthetic result matches. This tests a separate physical compiler
hypothesis without changing the held-out workload or online estimator.


3858378 (`formal-rdf-flat-debug-v1`) completed: flat LATERAL 16 keys
29.160 s / 187,265,024 bytes; flat LATERAL 567 keys still timed out at
60.139 s / 748,445,696 bytes; flat portable UNION 567 keys completed at
26.229 s / 1,985,552,384 bytes. Cache/order effects remain uncontrolled;
this is evidence of feasible complete execution in a diagnostic session, not
a speedup or a passed original 8-case gate.

The production change retains portable SPARQL and flattens only the compiler's
scalar-free leaf-witness query. Its inner projected n0/n1/e1 and source/target
variables are aliases of the final three identity columns, making inner
DISTINCTs redundant under the retained final DISTINCT. The directed compiler
exports its own body, passed through the exact-text Match checkpoint; the leaf
compiler uses that body instead of parsing arbitrary SPARQL. Scalar/OPTIONAL
queries are not admitted, and old artifacts retain the previous fallback.
Twenty-nine targeted tests pass, including min/sum/count full toy answers.
The next original 8-case gate uses a fresh service copy and unchanged budgets.
