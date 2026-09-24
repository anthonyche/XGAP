# Exact external membership before native SPJ/top-K

2026-09-24. This extends the shared unified planner, not a D2-specific query override.
No dataset name, template family, query ID or observed answer is consulted by the rule.
Full experiment launch remains closed.

## Evidence, not another speculative rewrite

3868312 archive (4,869,184 bytes) SHA-256
`5819b5cf13e57f15d250da0efae5f8c3d064b9e53fdcc105aaeb0cb7c7c56892`
was downloaded and checked. W2 passed: ordered empty reference, execution 4.731 s,
worker 7.999 s, one backend call. W3 did not produce an answer: execution 27.538 s,
worker 30.795 s, six calls, zero models. The sixth request, `cq9/native`, tried to
return the incoming edge relation for movies passing the Fuseki filter. Its
partial response reached 67,108,865 bytes, triggering `harness_response_budget`.
This is not evidence of the earlier Neo4j transaction-memory failure or I/O wait.
W3 observed source/method peak RSS: 1,750,884,352 / 275,279,872 bytes.
All prior serving groups, observer and private copies closed/reclaimed.

Local audit: `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/native-next8-3868312-audit.json`,
SHA `dcb23e8eba7fdc5ab6e4b39311b8cc7cd7abfa7cc88290efe305ba52ef00ace2`.
39 available pins verified; 52 referenced external artifacts are unavailable
locally and explicitly listed, not claimed rehashed. The selected plans match
zero-call diagnostics. The remaining six selected cases were not executed.

## Equivalence and scope

For set-valued SPJ, let N be the native core and E the external node relation
following its required filters. If the only interaction with E is a canonical
identity equality on k, and no external scalar is projected or compared with a
native scalar, then projected answers are exactly those from N restricted by
`k in projection_k(E)`. Duplicate external keys do not change that set.

The existing legally bound external read and all its ancestors are retained;
they compute K without a new probe or trial execution. Such necessary-join
reductions cannot remove the key of a complete original answer. The native core
is recompiled with `k in K` as a mandatory predicate in the complete witness,
BEFORE every prefix limit and the final ordering/limit. Merely applying the
external filter after top-K would be incorrect and is not used.

Admitted shape: grounded semantic tree of <=64 operators; exactly one external
node Match with a Filter chain; exactly one Neo4j core; shared canonical identity
namespace; a unique native representative for k; exclusive inner equality join;
no aggregate, optional/union/align, external scalar output, cross-field external
comparison, unsupported capability or scalar collision. Repeated side predicates
elsewhere may be removed only as whole conjuncts identical to predicates already
proved on E. OR/NOT are not weakened. Native identity equality keeps distinct
physical witnesses, and multi-valued external fields preserve existential
membership. The original compiler remains available when the rule declines.

A bound external read is required before this move is offered. A driver containing
ordering/limits or unsupported operators is declined. The existing scheduler
checks and deduplicates actual keys; empty K gives an empty result, and exceeding
the frozen key bound fails without truncation. HTTP/RSS/time guards are unchanged.
This does not establish a resource certificate or solve all federated join shapes.

## Algorithm and accounting

`native_semijoin.py` performs one bounded tree reduction and dependency-closure
walk. The static reduction is cached per program/placement. It yields at most one
new physical neighbor per state, reusing the existing fixed-D controller and
compiler representation bounds. It does not enumerate source outcome products,
probe alternatives, or change the one-final-plan contract.

The original source-work proxy charges native scans, join work and repeated
prefix passes; membership keys and the retained external driver are also charged.
Top-K bounds final output, not source scans. Frozen model parameters are unchanged.
The absent local model file was reconstructed from archived source-only receipts
and verified byte-for-byte against its original SHA
`d45af62450f999f25542c13defb147517075806aa77f978fd07f28d483f50401`.
The ordinary zero-call controller selects this move for original W3 in 179
expanded states, five remote nodes in the selected DAG. No reference rows were
read by this selection diagnostic. Relative work scores are not measured speedups.

## Verification and next boundary

29 focused tests pass (8 new membership/rejection/key-cap checks, 16 existing SPJ,
5 source-work tests). Six real private Neo4j 5.26.30 + Fuseki 5.6.0 tiny differential
cases preserve ordered answers, including denied early prefix, alternate keys
with equal output values, duplicate physical identities, parallel edges,
multivalued/absent flags, empty output, nullable inequality and descending order.
Both owned services stopped. These are correctness tests, not paper performance.
Tiny evidence: `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/semijoin-tiny-v1`.
Zero-call selection: `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/semijoin-zero-call-v1`.

Next: freeze a new exact checkout and execute original W3 at most once under the
same full MovieLens20M snapshot and budgets, conditional on unchanged frozen
estimator selecting this admitted move. Preserve 3868312; do not rerun W2 or the
eight-case batch. Success is only single-case admission. Further native/RDF
admission and release checks still precede a first-dataset formal run.
