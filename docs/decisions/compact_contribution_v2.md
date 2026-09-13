# Compact-v2: declarative contribution tuples

Milestone frozen 2026-09-13 before validation. This changes the explicit compact
language and shared frontend, not the lower algebra, planner, estimator, source
facts or baseline algorithms. V1 remains available unchanged. The observed real
group2 failure stays a v1 failure; no saved response is reinterpreted at runtime.

Research risk: joined existence witnesses multiply an aggregate, whereas dropping
transfer identity merges equal-valued parallel transfers. The local x-factor is
witness multiplicity / distinct contributor identity; the y-factor is the exact
aggregate and preserved count. This is a compiler gate, not a speed experiment.

## Frozen meaning

V2 has a different envelope, wire profile, prompt and lowering profile. Its query
requires `contribution_by` instead of `deduplicate_by`; neither wire accepts the
other key. All other finite v1 bounds and predicates remain. No new algebra
operator, data-dependent inference, response repair, source probe or model retry.

Let R be the complete matched, filtered relation. A nonnull `contribution_by`
declares node/edge anchor variables A. Let I be the identities of variables used
in any selected scalar or aggregate field; for a selected path length, its
identity is the existing (source, target, length) reachability tuple. Let V be
the selected scalar/aggregate input columns. The aggregate input is exactly
`DISTINCT PROJECT[A ∪ I ∪ V](R)`. Nonaggregate selections then determine grouping;
all aggregates in this block consume that same relation. Variables absent from
the projected tuple are existence witnesses. Nothing chooses an arbitrary row.

This projection is implemented by the existing set-valued Project operator. Its
declared anchors, retained identity variables/columns and operator ID are recorded
in program metadata. Null means no additional pre-aggregation projection.

For a company/account anchor with SUM(transfer.amount), the contribution tuple
contains company, account and transfer identities plus the needed output values.
Two risk media witnessing the same account therefore do not multiply the amount.
Two distinct transfers of amount 7 contribute 14. `SUM(DISTINCT amount)` explicitly
contributes 7 instead; these are different requested meanings, not optimizations.
COUNT(null) counts contribution tuples. With only account anchors/selected company
and COUNT(null), each qualified company/account pair contributes once. Without a
contribution projection, COUNT retains the existing complete-match multiplicity.

Bound: a nonnull contribution projection permits aggregate fields from at most
one shared stored node/edge variable. SUM(transfer.amount) and COUNT(transfer)
can coexist; SUM(account.balance) and SUM(transfer.amount) require different
grains and are rejected. Path-length aggregates with nonnull contribution keys
are rejected; nonaggregate reachability output retains endpoints and length.
Multiple independently scoped aggregates, nested aggregation and correlated
subqueries are outside this version. Property values must be single-valued as in
v1; contradictory facts are not resolved silently. Keep variable-equality joins,
all filters, identity binding and selected output/ordering unchanged.

## Complexity and acceptance

Computing the contribution projection uses O(q log(q+1)) time and O(q) space in
the number of declared fields/variables, with no data access. It adds one existing
Project node. V1's polynomial source/graph lowering bound and 64-operator admission
cap remain; execution cardinality is not bounded by this compilation statement.
The existing Ptime estimated neighborhood and one final execution remain intact.

Allowed files: compact schema/lowering/provider/profile wiring, a new prompt,
focused tests/fixtures and tiny native-gate script, progress/decision/report docs.
Forbidden: changing old frozen prompts/results, evaluation population, baseline
algorithms, estimator weights, planner domain, catalogs or data-load artifacts.

Acceptance: independent small-graph sums/counts under multiple witnesses and
equal-valued parallel edges; old-wire rejection and input immutability; explicit
mixed-grain/unknown-variable rejection; one recorded provider call with no repair;
frozen-profile isolation; one real tiny NL-to-estimated-plan-to-answer attempt.
Saved full-data failure is replayed for diagnosis only, never rescored or retried.
After acceptance, future new requests use a separately frozen profile; historical
versions and exposures are reported separately. No mass evaluation is authorized
by a tiny passing gate alone.

## Validation recorded before the live gate

Four unique new checks first pass in 1.49s: independent sums/counts with extra
witness and equal-valued parallel edge, shared global SPARQL parity, saved-v1
rejection/bounds, frozen-profile and one-call wire isolation. No external calls.
The actual tiny NL/Neo4j/Fuseki boundary is pending; no formal question rerun.
