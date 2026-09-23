# Formal scalar and independent-reference failure replay

The D1 v5 RDF admission executed two cases. The first passed; the second
`D1-pilot-uniform-outgoing_maximum-000-W2` returned an empty answer while the
independent reference had 20 rows. This is an implementation/authoring mismatch,
not a baseline result: the authored question explicitly asks for lexical ID
ordering, but its predicate used legacy `scalar` ordering (numeric only).

Add explicit `lexical_string` predicates to the bounded compact/row contract,
coordinator and shared global SPARQL bridge. Compare native strings and RDF
xsd:string by Unicode code-point order. Missing values, language literals, IRIs,
numbers and booleans do not acquire string order. Preserve legacy scalar and
calendar-string `timestamp_ms` behavior. This additive grammar change is source
revision-pinned; old runs remain at their old commit and are not relabelled.
ID range factors use the same explicit type. Formal core timestamps are integer
epoch milliseconds and must use numeric scalar predicates, not the legacy
calendar-string parser. Republish queries/scopes/references under new hashes with
the same source-only anchor selection; do not edit old cohorts or replace cases.
Before actual NL dispatch, publish the corresponding shared formal prompt/profile
revision for all methods; old frozen prompt profiles are not silently modified.

D3 v5 pilot reference generation exceeded its 60-second bound. EXPLAIN shows an
unanchored node ID range scan before the selective edge join. The independent
SQLite evaluator now orders joins from anchored nodes through adjacent indexed
edges using CROSS JOIN, keeping edge/node identity and contribution-grain DISTINCT
semantics. It does not change an XGAP method plan, select a winner, or train a cost
estimator. SQL, parameters and EXPLAIN are retained for future failures. The
timeout/output bounds remain unchanged.

Targeted portable verification: 12 tests passed (one unrelated live-estimated
fixture deselected), covering coordinator/RDF lexical agreement, preserved old
timestamp behavior, integer epoch lowering, contribution/parallel-edge references,
paths, split isolation and a 20,000-isolated-node star reference. The real repaired
D1/D3 replay remains required; no full campaign has started.

Follow-up: v6 D1 RDF returned the independent answer in all 8 pilot cases. D3's
8-case reference publication completed in 8.97 seconds. D1's overall gate still
failed cleanup: JVM leaders were Z with empty sampled live groups, but the short
reap window had not obtained an exit status. The observer was then left running.
Use a bounded additional wait on the owned Popen handle and always stop the
observer, preserving a separate failed source-quiescence status when necessary.

The original core schema advertised replicated business IDs on every graph shard
and on control. This incorrectly made graph-only questions read control and made
the 8-source pilot exceed the 64-operator bound. `ch6_profile_revision.revise`
publishes a new explicit profile: the first graph shard is the complete provider
of ordinary node attributes; control supplies control attributes; all graph shards
remain required for partitioned edges. This follows the source materializer's full
node replication, with no query outcomes consulted. The raw stores, loader timings,
source snapshots and estimator weights remain frozen. A derived store-binding
receipt cites the original receipt; it is not another load. New source-schema
identity and shared scalar prompt apply equally across all five methods; regenerate
cohorts before dispatch. Two additional focused profile/routing checks passed,
including 2/4/8-source pilot lowering within 64 operators and unchanged physical
store references. One cleanup replay passed with both terminal/nonterminal cases.

D1 v7 RDF admission passed all 8 cases and verified both source reaping and observer
shutdown. D3 v6 also matched all 8 RDF answers, but retains its failed cleanup
status; do not relabel that gate as successful.

D2 v7 stopped before backend execution: the independent reference for frozen
`D2-pilot-uniform-incoming_minimum-000-W1` (anchor `user:12937`) exceeded 60 seconds.
Its contribution grain retains the rated edge but not the other-user witness.
Enumerating all popular-movie witnesses before DISTINCT is unnecessary. Compile
such unused witnesses into one correlated EXISTS, preserving their joint conditions,
parameter association, contributing edge identities and aggregate inputs. This is
an offline reference evaluator optimization, not a method optimizer change. Keep
the same query, selection seed and source snapshot, and preserve the failed receipt.
The repaired reference must pass the original bounds on the real source before
backend admission. Eight focused toy reference/factor tests passed, including
joint-witness constraints and parallel-edge contribution identity.

D1 v7 native also returned all 8 expected answers. Its final receipt was interrupted
by an NFS `Directory not empty` error while removing a reconstructable serving copy.
Keep source termination/observer closure separate from storage reclamation: persist
reclamation errors and retained paths without retrying deletion or losing query
outcomes. This does not upgrade an unknown process-group state. The old v7 native
run remains incomplete; a new admission must produce the complete closure receipt.
Five focused shutdown/retirement fixtures passed after updating stale Popen fixtures.

D1 v9 native completed 8/8 with a sealed closure. Its F6 pool measurement also
completed successfully. D2 v9 published all 8 pilot references in 66.50 seconds,
then its first fixed-scan backend attempt hit Neo4j's 537.6 MiB transaction limit.
That gate uses a predetermined scan DAG, not the evaluated online controller;
its failure cannot be labelled an observed XGAP policy failure.

Add an explicit `--planning unified` admission profile. A singleton complete Q
enters the existing fixed-depth controller and frozen estimator; only the selected
plan executes, with the same source, query, timeout, memory and observation bounds.
Record the selection trace and one final plan separately. No NL interpretation,
model calls, current-query plan races, new estimator training or baseline changes
are introduced. Preserve the original fixed-scan gate for failure evidence.
Two tiny RDF execution checks passed for both admission profiles; real D2 unified
admission remains required. A hypothesized scalar-filter issue was excluded by
checking the lowering contract; no source-filter implementation was changed.

Unified admission v1 stopped before any backend calls because its new wrapper
unpacked the catalog as the estimator. Correct the wrapper to the existing
materialize contract and make both fixture positions non-null, with a checked
predict call. This is an admission-harness bug, not a policy or backend result.

D2 RDF loading v5 reached 34 million triples while still progressing, then hit
the declared 3600-second offline bound; peak RSS was below its cap. Add an optional
new node-local workspace for loader/index I/O, followed by a hash-verified durable
copy. Keep frozen source/profile identity and the serving/query environment
unchanged. Reserve space for both copies, reject overlapping paths and symlinks,
retain failure logs, and reclaim only newly owned, successfully copied workspace
files. This changes offline preprocessing, not online experiment accounting.
Five focused checks passed for one-shot admission, durable-copy integrity,
corruption rejection and workspace separation. Real repaired gates are still needed.

The corrected D2 unified gate selected one share-read transform and then failed
at a full RATED relation scan (Neo4j transaction memory). This is an actual
selected-plan failure. Source loading and scalar reference publication succeeded;
the gate is not upgraded or excluded from its record.

Extend the shared XGAP physical neighborhood with necessary-key reductions:
(1) reuse the audited mandatory scalar-anchor/fanout proof as one finite macro
transform; (2) allow an outer inner-join key to restrict an exclusive nested
Match leaf when its column provenance survives Projects, Filters, inner Joins
or Unions. Keep final constraints and joins; reject shared answer roots,
unproved provenance, already bound/shared reads and cyclic dependencies.
The old protected seed, frozen estimator, source data, budgets and one-final-plan
rule remain. No native result is used to rank alternatives; the external baseline
is unchanged. This addresses missing alternatives, not a claimed optimal planner.

For J joins and M operators, at most O(JM + V²) local alternatives are generated;
provenance/dependency checks add polynomial O(JM(V+E)) work plus generated query
bytes. The anchor macro touches at most M target reads. D stays fixed, existing
search/representation/time caps apply, and duplicate executable DAGs are omitted.
Portable checks compare the new alternatives to an independent small D2 SQL
reference, including parallel contributing edges and a distinct-user witness.
Real D2 replay is required before declaring this bottleneck resolved.

The node-local loader reached 113 million triples in about 420 seconds, then its
10 GiB sampled RSS guard fired. Declare heap and total process RSS separately:
TDB2 native/mapped-index memory is outside the Java heap. The next offline build
uses a 64 GiB CPU allocation, 8 GiB heap and 56 GiB sampled RSS cap with the same
one-hour per-source deadline. This does not raise online method/source budgets.
The old partial node-local path and durable failure logs remain identified.

Unified admission v3 (3857752) still selected share-read and failed on the same
preserved first pilot query. Its symbolic diagnostic executed no backend/model
calls: anchor-bind was estimated at 660.56 work units, seed at 152.62 and share
at 101.77. The old model's binding-key feature used all incoming row-work units,
even though the runtime deduplicates keys and refuses lists above max_bindings.
New unified bindings mark `scheduler-distinct-key-cap-v1`; that feature now uses
min(incoming proxy, actual runtime key cap). Existing artifacts without the
marker retain their old feature meaning. Upstream work is not discounted, edge
fanout is not bounded, overflow remains a failure, and weights are unchanged.
Targeted checks verify feature/version isolation, unknown-profile rejection and
small-graph semantics. This does not by itself establish good D2 plan ranking:
the transferred small-graph model also has weak/zero full-edge work coefficients;
do not run another large replay merely because this feature fix was committed.

The D1/D3 current-bank NL manifests were successfully prepared in job 3857763:
three repetitions per case, source/config/request pins and method order frozen,
0 model and 0 backend calls. `formal-prepared-units-v1/receipt.json` is successful
but explicitly not a full formal release; global support, factors and budget
still need their combined audit.
