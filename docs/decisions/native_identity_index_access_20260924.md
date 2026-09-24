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
on its declared tiny indexes. The owned Neo4j process is stopped after the gate.

The complete D2 source has a separate bounded diagnostic job **3866035**: two
EXPLAIN calls, zero query executions and zero model calls. It compares the sealed
failed request with the necessary indexed predicate; results do not feed an
online estimator or method decision. Its result is pending collection. The
local rewrite is not yet a large-data correctness or performance acceptance.
Only after examining that evidence should the original failed case be replayed
under its original caps. A large true intermediate may still require a separate
semantics-preserving optimization; increasing caps or dropping rows is not a fix.

## Full-source EXPLAIN accepted; single-case replay prepared

3866035 completed the two EXPLAIN calls successfully. The downloaded 77,767-byte
archive matches the server SHA-256
`fcc2d522abddc917d7e3035748a2890a5579f0079982e355f1bb9e13b691e2e9`.
Both compressed response pins and uncompressed body digests match; both bodies
contain no errors and no data rows. Original and indexed requests use identical
parameters (1,896 canonical keys). Service/process/copy closure is verified.

On the full frozen D2 store, the original anchor is `AllNodesScan`, while the
necessary-label/local-key form is `NodeUniqueIndexSeek`. Both retain the same
incoming expansion, predicates, DISTINCT and projections. This confirms the
access-path defect and its proposed index entry, not a completed query or speedup.
In particular, estimated seek rows (~25) are not the actual 1,896 supplied keys;
the sharply different estimated expansion cardinalities are not actual scans or
evidence that the real fanout disappeared. EXPLAIN observations never feed online
selection or estimator training.

The unchanged failed `D2-test-uniform-zigzag-000-W1` is the next single-case gate.
Package `xgapnativec517451.zip` pins source `c517451`, the original 24-case bundle,
prepared store, failed receipt and EXPLAIN receipt. SHA-256:
`efd44ea387e33a1c9c76a766225ce9c6af97cf3bd7a7c48f517b313c439ce3a0`.
One final unified plan, no retries/LLM, worker 120s/3GiB, HTTP 60s, source 4GiB,
same compt311 and node-local serving. It does not rerun the successful prefix.
Output `formal-native-index-replay-v1/D2/native` remains diagnostic, never full
admission. After browser upload became unavailable, the user completed the
SHA-checked staging and returned unique job **3867351**. Final evidence is pending.
Journal: `native-index-c517451/`; output log: `native-index-3867351.out`.
Do not resubmit while awaiting this job or treat submission as successful execution.
