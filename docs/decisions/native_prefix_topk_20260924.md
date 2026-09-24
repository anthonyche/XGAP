# Exact completion-checked prefix top-K

## Motivation and evidence boundary

3867524 passed its full-source EXPLAIN structure gate and then failed the single
unchanged D2 query. The user pasted a Neo4j transaction-memory error at 537.6 MiB,
23,519.153 ms execution / 26,503.284 ms worker wall, one final query and one call.
The sampled source RSS (1,567,068,160 bytes) stayed below 4 GiB. Sampled storage
read_bytes and major faults were zero; this is not evidence of an I/O-wait fault.
The archive (116,163 bytes, SHA-256
`68822b58663d559590ea2586a8ad01cef972cd76b2dd443a2a38c86fb52db8c1`)
is not yet downloaded. The exact allocating native operator is unverified;
the existing compiler does require full-tuple DISTINCT before top-K. The new
transform removes that global tuple set without changing the answer contract.

## Admitted transformation and proof

Keep the bounded single-source positive SPJ profile, complete typed output
ordering and original K (1..1000). This additional profile admits 1..8 ordered
output columns, each a field of a node Match. No node-identity uniqueness is
assumed. Unsupported outputs retain the existing connected contraction/seed.

Let R be the DISTINCT final result and P_i its DISTINCT prefixes of length i in
the declared lexicographic order (including direction and explicit null order).
Every prefix considered for truncation must have a witness for the COMPLETE
original query, not just its locally generated partial path. For each retained
prefix of length i-1, generate possible i-th values and check remaining query
conditions using a correlated EXISTS. Retain its first K distinct values, then
retain the first K resulting prefixes globally. Regenerate witnesses from the
original patterns at the next level, constrained by retained VALUE prefixes;
do not retain a single arbitrary physical witness for each prefix.

Induction: a discarded parent prefix has K preceding completable parents, each
contributing at least one complete result. A discarded child has K preceding
completable children of the same parent. Neither can contribute to the first K
full tuples. Global prefix truncation has the same argument. At full width the
retained prefix set is exactly top-K(R). This fails without completion checks;
an early lexicographic partial path may be a dead end. Rebuilding by values
preserves alternate witnesses, duplicate logical identities and parallel edges.
Null-safe equality binds prior prefixes; OR/NOT predicates remain whole and
nullable predicate truth conditions are unchanged.

## Implementation and cost boundary

Compile one native query with nested CALL subqueries. Reuse the deterministic
connected schedule and earliest predicate placement. For each output field,
generate only through its producing Match; the suffix is a correlated EXISTS
with complete predicates. Inner DISTINCT is on ONE scalar field per prefix,
not the Cartesian set of all output tuples. Each outer boundary retains at
most K prefixes; at most K^2 rows enter its Top operator. A local scalar-domain
DISTINCT may still contain up to the node population, and EXISTS expansion may
still be expensive. This is not a constant total-memory or time certificate.

Code generation is O(W * M^2 * E + emitted bytes), W<=8, M<=64, E<=512,
with a 128 KiB query cap. It emits one deterministic alternative, does not
enumerate plans or read results during planning, and dispatches one final query.
Frozen work estimates must explicitly charge repeated prefix passes; final K
does not cap source scans or suffix witness work. Observed EXPLAIN/latency is
not fed into the estimator. Keep all remote and source memory/time caps intact.

## Admission still required

First validate dead prefixes, duplicate value/identity witnesses, nulls,
descending/Unicode ordering, OR/NOT and edge reuse on toy data against the
unchanged coordinator. Inspect the generated native plan on toy data before
any full-source replay. No new server submission or full campaign is authorized
by the existence of this design document.

Local implementation evidence: 31 focused compiler/work-model/controller checks
passed. Tiny real Neo4j compares ten cases against the original coordinator;
ordered results match with 2/0/23/7/76/56/1/5/5/1 rows. This fixture adds dead
prefixes and alternate physical witnesses; counts are not the earlier fixture's
six-case counts. Source closure passed. Receipt at local artifact root
`ch6-release-boundary-20260924/native-prefix-tiny-v2/receipt.json`, SHA-256
`7cdb88ebda01b934ca8b158fa4c3a0ed57dca1370e3e023613af61501d23dc26`.
The earlier v1 gate retained seven successes and a harness error: compact NL
order does not accept a `nulls` field. The v2 test sets null placement through
the already-supported semantic OrderLimit layer; no NL grammar expansion.

Tiny EXPLAIN has zero CartesianProduct and three one-field DISTINCT operators,
each followed by a bounded Top; two SemiApply implement suffix existence checks.
This is structural evidence, not measured big-source peak-memory attribution.
The original D2 program compiles unchanged to 13,096 query bytes, three ordered
columns, cuts [2,4,6], K=20 and at most 41 prefix subquery invocations. Full scan
and join proxies are charged 41 times rather than pretending the suffix checks
are free. This is deliberately conservative; it is neither a runtime nor a
memory bound. The frozen model parameters and other plan scores are unchanged.
Zero-call D2 compilation artifact `native-prefix-d2-compile-v1.json`, SHA-256
`453cbef759c93ba8183eb663caf306d64c07c1763ce7128c8e400d2d73a05a5f`.
Exact frozen-model selection and full-source structure/execution admission
remain required; neither compiled size nor tiny equivalence establishes them.

One additional focused width-bound fallback check passed (16 compiler tests in
the final subset; 32 distinct focused tests across the changed contracts).
The unchanged D2 query also received ONE EXPLAIN on a fresh tiny graph with ONLY
internal-identity indexes: 3 anchor label scans, 18 index seeks, 3 one-scalar
DISTINCT operators, zero CartesianProduct/ValueHashJoin/unbounded Sort/Eager
aggregation. No D2 result query was run locally. Receipt
`spj-prefix-explain-v1/receipt.json`, SHA-256
`355a93f3e74471d1c7fd836b72570893f508fc2b3ac9a4a0ba86826f9baad0a0`.

## Frozen conditional single-case package

Source `6169b8fa2b994be5877f180f5ec952d4ab1b240a` is pushed to GitHub.
`/Users/anthonyche/Downloads/xgapprefix6169b8f.zip`, 22,092 bytes, SHA-256
`54e87c6aa2fcc37e6abd039ca3e2895314a7993f0c93dcb5f32816c47f47a18c`.
Requires the already-staged e22a32e checkout. Stage and driver verify the sealed
3867524 archive, original bundle/store, previous selected-plan hash, closure,
structural checks, single attempt and selected-artifact identity. They refuse
existing journal/output paths; no automatic resubmission or query retry.

Before starting any source, the existing zero-call selection diagnostic must
select the prefix artifact under the frozen estimator. Otherwise the gate fails
with zero final executions; it does not force a different plan. One full-source
EXPLAIN must show one scalar DISTINCT per output column, only anchor scans,
indexed bindings, no Cartesian product/value hash join/unbounded sort/eager
aggregation. Only then a separate fresh source session executes the unchanged
failed case once with the common independent answer check. All query/resource
limits remain as 3867524 (CPU only, zero model calls); the allocation is 70
minutes for two setup phases, not a larger query-time allowance.

Stage Python 3.6 grammar, driver syntax, shell syntax, bundle prerequisite and
member hashes were checked. The user confirmed upload, checksum verification,
staging at exact source `6169b8f`, and submission as **3868056**. Do not resubmit.
Automatic terminal input remains disabled after earlier control failures;
the user has been asked for one read-only status/log query. Local command file
retained for provenance (already executed, not a retry instruction):
`/Users/anthonyche/Downloads/xgapprefix6169b8f-command.txt`.

Remote journal `native-prefix-6169b8f`, log `native-prefix-3868056.out`, output
`formal-native-prefix-gate-v1/D2`, archive
`/home/hxc859/xgap-prefix-gate-3868056.tar.gz`.

## Server completion: 3868056

The user supplied and the read-only OnDemand terminal independently displayed
COMPLETED/0:0, compt311, elapsed 00:03:26. Native receipt summary reports
success=true, attempted=audited=1, error=null; the final gate summary reports
success=true, explain_success=true, attempted=1. The 206 seconds are allocation
elapsed time including source setup, not measured query latency.

The archive is 209,955 bytes with server-reported SHA-256
`68d2540e205134d901a0ce61ac60f4ad7273189a7269f5efc85fc6a3f34b4e8f`.
Local bytes, detailed answer equality, execution latency, resource samples and
closure remain to be audited. The file listing showed the archive, but the
automated page became blank again; manual download to local Downloads was
requested. No new job or repeated query was submitted. Stop rewriting this
case; audit and freeze its evidence before choosing the remaining admission
scope. This successful single-case gate does not establish full held-out admission.
