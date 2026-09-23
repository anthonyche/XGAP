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
