# Independently bound native edge endpoints

2026-09-25. General exact SPJ compiler repair, without dataset/case dispatch.
Evidence: [3868824 failure and 3868871 EXPLAIN](../report/ch6_remaining6_diagnosis_3868824.md).

## Transformation and proof

A connected Match may introduce endpoints u,v and edge e while necessary,
positive identity equalities already bind u.key=x.key and v.key=y.key to outer
node variables. Instead of leaving both equalities on a combined edge Match,
resolve the complete labeled node domains of u and v in two correlated node
subqueries, then match the edge with both physical endpoint variables bound.
Keep every original label, relationship Match, equality and nullable predicate.

For each fixed outer row, an original witness (u,e,v) belongs to both keyed node
domains and therefore remains in the rewritten join. Conversely every rewritten
witness satisfies the original edge Match and all its predicates. Duplicate
logical IDs enumerate all matching physical nodes; outer and inner nodes are
never aliased. Parallel edge identities and relationship reuse across distinct
Matches remain intact. No LIMIT or DISTINCT is added to either endpoint domain.
Complete-witness prefix checks and value regeneration are unchanged, so the
previous exact ordered DISTINCT top-K proof composes with this equivalence.

Only guaranteed identity equalities qualify. Scalar coincidence, labels alone,
OR/NOT-contained equalities or a single available endpoint do not trigger this
rule. Missing keys cannot form a successful equality and contribute no witness.
At most two node subqueries are added per closed edge. Stage order is unchanged.
Detection scans the bounded stages and identity equalities; it is polynomial,
within existing 64-operator, 512-predicate and 128-KiB generated-query caps.

## Evidence and limits

37 focused compiler/semijoin checks pass. Four affected real Neo4j/Fuseki tiny
cases have equal ordered answers, including duplicate endpoint IDs, empty
membership, descending order and projected parallel edge identities. All their
closed-edge EXPLAIN operators are Expand(Into), with nonunique node indexes.
The first gate's incorrect toy assertion and the corrected isolated rerun are
preserved and distinguished in the linked report.

Expand(Into) constrains endpoints but may still inspect adjacency; this is not
an O(1) lookup, a latency guarantee, or a source-work bound. Index availability,
fanout, upstream repeated witnesses and prefix regeneration still matter. This
repair does not prove the complete MovieLens query will fit its old deadline.

Frozen v1/v2/v3 estimator formulas and weights are unchanged; no new speed credit
is inferred from EXPLAIN or the held-out failure. Their separate greedy order
proxy still differs from the emitted stage order. Aligning/versioning that work
model remains a distinct task; the proxy must not be described as actual source
work or a resource certificate. No model was fit to this query's answer/time.

## Next gate

The repaired W4 is selected by the real zero-call inspector with the archived
source schema/statistics/policy and unchanged frozen v3 model. The pending gate
permits one original W4 final execution, zero LLM calls and no cohort rerun.
Full-source data, query, reference, source/worker RSS and 60-second HTTP timeout
remain fixed. Passing one case does not grant full native/RDF release admission.


## Frozen one-case handoff

Code `c3437fc309ef54f35d51288a9c284abbe2323127` is committed and pushed.
Local package `/Users/anthonyche/Downloads/xgapclosedc3437fc.zip`, 24,394 bytes,
SHA-256 `9a28d6c42363bbe27f3e0ff76d8858990e9a2c72dc316b99af16e5ab7e9e7b44`.
The delta requires the server's `5f94023` checkout and creates a new checkout;
old versions and results are preserved. Stage validation passed against the
actual downloaded archives; changed case/query/snapshot/estimator contracts
are rejected. Python 3.6 staging syntax, shell syntax, bundle and ZIP members
are verified. Zero remote calls/jobs were made by local validation.

Only original native index 10, cycle/W4, is admitted, with at most one final-plan
execution, no EXPLAIN or LLM calls. Source stores, frozen v3 model, reference and
120-second worker / 60-second request / 3-GiB method / 4-GiB source caps stay fixed.
Before source startup the server must reproduce the exact locally selected plan
hash. Existing journal/checkout/output blocks repeat submission. Result archive
is `xgap-native-closed-<job>.tar.gz`; journal is
`/home/hxc859/xgap-ch6-artifacts/native-closed-c3437fc` and output is
`/home/hxc859/xgap-ch6-artifacts/formal-native-closed-endpoints-v1/D2`.
The user was asked to upload and stage it because automatic access is unavailable.
Submission is not yet confirmed. Full formal launch remains closed.
