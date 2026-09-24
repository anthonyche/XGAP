# Native identity index access

The D2 native zigzag/W1 failure is an actual source transaction timeout. Its
saved Neo4j HTTP 200 body contains `TransactionTimedOutClientConfiguration` and
15,106 partial rows. The observer's later BrokenPipe classification is retained
as historical transport evidence; those rows are not a successful answer.

The failed request binds 1,896 Movie identities before incoming RATED expansion.
The old predicate concatenates a namespace onto each node property and exposes
no mandatory label to the anchor lookup. Tiny Neo4j EXPLAIN confirms an
AllNodesScan for this form, despite an existing label/identity index.

## Admitted rewrite

The edge Match compiler records the mandatory positive labels of the source and
target **traversal positions** in its exact-text binding checkpoint. For a bound
node endpoint with an explicit property-map identity view matching the backend,
the existing anchor subquery adds that label and a local-property membership
condition. The original canonical identity checks, endpoint/edge predicates,
DISTINCTs, scalar projections and final coordinator operations remain in place.
Unknown labels, absent identity views and independently wrapped text keep the
previous path. No index hint, new operator, source call, key truncation, answer
LIMIT or result-based plan selection is introduced.

For admitted canonical string identities, fixed namespace N and key set K,
`N || id in K` iff `id in {suffix_N(k) : k in K and k starts with N}`.
The positive label already holds for every valid original edge binding. Thus the
added conditions are necessary conditions and preserve the original result.
Foreign namespace keys cannot become matches; duplicate keys and parallel edge
identities retain set semantics. Malformed non-string backend identities remain
outside the declared canonical identity data contract, not a new coercion rule.

Compilation adds constant text per bound endpoint and bounded label metadata;
there is no increase in policy-search depth or candidate count. Runtime key
projection is linear in supplied key bytes. Native index availability and
relationship fanout still determine execution cost; no speed bound is claimed.

## Verification and boundary

`tests/test_native_identity_projection.py`: 7 focused tests pass.
`scripts/check_native_index_access.py`: four real tiny Neo4j comparisons pass,
including OUT/IN traversal, source/target binding, parallel edges, a self-loop,
missing optional scalar values, foreign/duplicate keys and an empty key set.
The script also checks original AllNodesScan versus indexed NodeUniqueIndexSeek
on its declared tiny indexes. Both owned services are stopped after the gate.

The complete D2 source has a separate bounded diagnostic job **3866035**: two
EXPLAIN calls, zero query executions and zero model calls. It compares the sealed
failed request with the necessary indexed predicate; results do not feed an
online estimator or method decision. Its result is pending collection. The
local rewrite is not yet a large-data correctness or performance acceptance.
Only after examining that evidence should the original failed case be replayed
under its original caps. A large true intermediate may still require a separate
semantics-preserving optimization; increasing caps or dropping rows is not a fix.
