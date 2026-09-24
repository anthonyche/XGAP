# Native membership composition and retained-driver optimization

2026-09-24. User requested general system optimization after the verified
3868378 result. This change belongs to XGAP's shared physical planner. It has no
dataset/template dispatch, does not tune baseline methods or estimator weights,
and does not start another server job or the formal campaign.

## Diagnosis

Recent release-blocking execution failures concentrate on full D2 MovieLens20M.
This does not establish that D1/D3 are immune. Source fanout, intermediate width,
native blocking operators and federation boundaries matter in addition to size.
Several defects were in XGAP's implementation and strategy composition:

| Layer | Observed issue | Evidence and response |
| --- | --- | --- |
| Execution strategies | Large joined relations crossed HTTP or transaction-memory limits | Prefix top-K and external membership repaired the original cases without changing queries or budgets |
| Rule composition | Selecting membership contraction disabled all later read optimizations | 3868378 still returned 27,278 Movie and 138,493 User node records before the final query |
| Strategy admission | An intermediate projection carrying an external scalar blocked cycle contraction, although that scalar was absent from the answer | Static review of the unattempted cycle W3/W4 programs; scalar lineage is now checked |
| Fixed-depth search | A prerequisite bind had the same rounded work score as its parent; only the following contraction exposed the gain | Cycle W3: parent and bound intermediate about 3.5982e18 work units, contraction about 2.0445e10; D=1 cannot see through the neutral step |
| Estimation | Declared degree/join proxies remain heuristic, with no query-specific correlation or resource certificate | No parameter adjustment is justified by the above composition defects; retain the frozen model for these repairs |

3868378's measured query execution is 41.428 s versus 0.310 s of planning. The
final native HTTP call alone is 29.780 s. This repair targets avoidable driver
transfer and rule reachability; it does not claim to solve that source execution
time or to prove native index use. Old failed execution times are not speedup
baselines.

## Three checked changes

1. **Retain driver ports.** The complete native answer query is unchanged after
   contraction. Retained ancestor nodes keep their semantic output mappings.
   Existing necessary-predicate and identity-bind proofs may refine those reads
   one at a time. Removed operators have no live ports; the final membership
   query is never used as an upstream driver. Dependency checks prevent cycles.
   Shared physical reads remain ineligible for single-consumer restrictions.
2. **Track external scalar lineage.** Carry original external field identities
   through intermediate field projections and join renaming. Remove a repeated
   external predicate only after alias normalization and whole-conjunct equality
   with a predicate already enforced by the external relation. Remove its carried
   fields from native intermediate projections. Any external scalar reaching an
   answer, ordering, join key, cross-field/new predicate or computed expression
   declines the rewrite. OR/NOT retain their complete original truth conditions.
3. **Make the canonical prerequisite part of the contraction.** If the external
   read is unbound, construct exactly one necessary-key bind from the other side
   of its original identity join, using the existing typed binder. If it already
   depends on that read, decline. Then contract the native query. This is one
   equivalence-checked physical macro, not enumeration of combinations or an
   increase of lookahead depth. Its complete driver, keys and source work are
   charged by the unchanged estimator.

Correctness uses set-valued inner SPJ. Removing the external scalar dimensions
preserves precisely the existence of a matching external row for each key.
Repeated scalar filters are already true of that same row. Native columns and
remaining predicates retain their values. Membership is enforced before all
complete-witness/prefix limits. Multiple external scalar values or duplicate
physical native identities cannot substitute one arbitrary witness for another.
Aggregates are excluded: this argument is not an aggregation multiplicity proof.

One static reduction per bounded program/placement is cached; at most one such
macro is offered. Each driver proposal uses existing polynomial lineage and
dependency scans. The 64-operator/compiled-text, candidate, plan-pool, action,
state, horizon and fixed-D limits remain. No backend call occurs in generation
or ranking, and only the chosen final plan is executed online. Bind overflow
still fails, never truncates. A polynomial planner does not bound query execution.

## Verification

62 focused tests pass across membership, native SPJ, source-work estimation,
necessary binds, leaf witnesses and row filters. New cases check carried/renamed
external scalars, forbidden escapes, direct versus pre-bound contraction, and
post-contraction refinements. No blanket regression campaign was run.

Eight real private Neo4j 5.26.30 + Fuseki 5.6.0 tiny cases compare original,
contracted and refined plans: all three produce identical ordered answers.
Cases include a nonempty cycle, empty cycle, missing/multivalued flags, early
excluded prefix, duplicate native identities, parallel edges and descending order.
The fixture adds 64 unrelated nodes of each of two types to expose full-table
transfer. These are development equivalence checks, not formal result selection.

| Tiny case | Contracted driver result rows | Refined result rows | Decoded-row JSON bytes before → after |
| --- | ---: | ---: | ---: |
| allowed | 160 | 18 | 9,114 → 1,269 |
| denied | 160 | 20 | 9,124 → 1,596 |
| early prefix | 159 | 17 | 9,046 → 1,201 |
| descending | 167 | 25 | 9,598 → 1,753 |
| nullable inequality | 160 | 21 | 9,114 → 1,745 |
| cycle | 160 | 18 | 9,114 → 1,269 |
| empty / empty cycle, each | 153 | 0 | 8,290 → 2 |

Counts sum actual backend response rows including the final answer. JSON bytes
measure serialized decoded rows, not HTTP wire bytes. Nonempty cases keep five
calls; the empty cases drop from three to one through existing empty-bind
short-circuiting. No scan/I/O/latency reduction is inferred from this metric.
All owned source processes were stopped and reaped.

Local evidence under `/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/`:

- `semijoin-compose-tiny-v1/receipt.json`, SHA
  `259d6902d03d5b2ab6aa02d9727a011f79ee54bad02a67017125cb3790008135`.
- `semijoin-compose-selected-v1/access-summary.json`, SHA
  `65f738e7e2695019d8df061aa22d213e6f5d8ed8e97fae3b57b5a70478d5cbc1`;
  includes exact implementation-file pins and original estimator identity.
- W3 selected plan SHA
  `2d94248dd37858617514563a6931c3e3de1b740f950e22fb89cfba5451c0cf85`.
  Zero live calls/executions/reference-row reads; complete-query input is an
  engineering diagnostic, not an NL experiment. It now selects the screened
  User read and key-bound Movie read, with the same final native query.
- `remaining-shapes-zero-call-v3/receipt.json`, SHA
  `ff95e694bad8f6fa3249d2d5cd5a24ef591fdeb2d49af69bf341202ea319c9aa`.
  Cycle W3/W4 now select membership contraction (five remote nodes, versus
  eight/seven previously). This is plan admission, not execution admission.

## Remaining boundary

| Remaining shape | Strategy admitted | Selected | Full-source resource verification |
| --- | --- | --- | --- |
| ordered star W2 | native SPJ and anchored coordinator joins | coordinator, both edge reads anchor-bound; one Movie node read remains unbound | pending |
| cycle W1 | native prefix SPJ | one native query | pending |
| cycle W3 / W4 | external membership + native prefix SPJ | five requests, with screened anchor and bound dimensions | pending |
| witnessed sum W4 | contribution-aware leaf witness, no SPJ aggregate contraction | witness edge returns at most one qualifying row per bound key; all node dimensions except screened anchor are key-bound | pending |
| window edge W2 | anchored edge and node bind | three requests | pending |

The selected ordered-star plan remains a coordinator plan; a native alternative
exists but the frozen estimator prefers the former (548.56 vs 1,652,364.43
declared work units). That alone proves neither misranking nor failure. Two
anchor-bound edge relations can still produce a large product before the final
ordering. Frozen maximum degree is a risk indicator, not the observed degree of
this query's anchor. The unbound dimension and distinct-key estimates deserve
attention before a batch dispatch.

The witnessed aggregate remains outside this SPJ rule but its selected edge
already carries `contribution-leaf-witness-v1`: all leaf predicates precede the
one-row-per-key choice and contribution projection removes the witness identity.
It has a bounded witness response, not a bounded adjacency scan. Do not replace
the declared contribution semantics with an ordinary count/sum over witnesses.

The table separates **admitted, selected, resource-verified**. Any further
estimator work must use source-only statistics or a
separately frozen development calibration, not held-out answers or observed
current-query winners. Reuse verified cases; validate new physical paths under
the unchanged full snapshot and resource configuration. These local improvements
have not yet been measured on full D2. Complete native/RDF admission and formal
input/support/budget checks remain prerequisites to the first-dataset campaign.
