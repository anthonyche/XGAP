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
