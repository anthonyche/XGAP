# Bounded exact anchor reduction in XGAP physical plans

2026-09-13. Scope: runtime/anchor_reduction.py, physical_strategies.py, focused
tiny tests and research evidence. No semantic language, shared baseline input,
LLM prompt, catalog, estimator weights, source data or budget change.

Saved NL group5 has an explicit start-account business-ID equality, but its
compact DAG expands all 1–3-hop branches before joining the account property
read and applying that equality. Both modes were interrupted at the existing
2GiB method RSS threshold. This is evidence of a missing early restriction,
not proof that this is the sole memory bottleneck. Do not retry that question.

Normalize XGAP's physical base plan with at most one proven scalar-equality
anchor. Reuse an existing mandatory node-property read (including a union of
providers), evaluate the original predicate in the coordinator, and semijoin
eligible edge-Match outputs with these canonical entity keys before expansion.
The final implementation realizes this semijoin as DISTINCT one-column key
projection plus existing inner joins; it introduces no unseen estimator operator.
Do not push a control-only property into a graph endpoint. Retain the original
join and final filter. No additional remote query, model call or probing occurs.
Native source responses remain unchanged in this first bounded mechanism.

Admission must prove, from operators and schemas rather than metadata claims:
the property read is mandatory under inner joins/filters; all its union leaves
are node Matches with the same identity/property columns; every use of a target
edge output flows through the enforcing filter with the same identity column.
Decline paths through aggregate, limit, identity-dropping/renaming projection,
separate roots or unsafe join-column collisions. Only a top-level conjunctive
scalar equality is admitted; no OR, timestamp or null rewrite. Select the first
admissible anchor in semantic input order, with no data-dependent choice.

For n semantic operators, p predicate atoms, e DAG edges and L compiled plan
size, inspect at most p equalities times n edge Matches with memoized lineage:
O(p*n*(n+e)+L) time and O(p*n*(n+e)+L) space are conservative polynomial bounds.
The existing input byte/operator limits also bound p. Add at most n+2 runtime nodes.
The existing candidate domain remains at most 1+2J: this normalization precedes
the single-join bind alternatives. Reject a bind rewrite if the new dependency
would create a cycle. Selection minimizes the frozen estimate in this finite
domain; no actual-cost or approximation-ratio improvement is claimed.

Correctness: every surviving row satisfies the original predicate on a node
read joined by canonical identity. It therefore has an identity in the filtered
read. Removing edge rows outside that identity set cannot remove a surviving
row when every use has the proved lineage. A semijoin preserves distinct edge
identities and does not multiply rows when several providers/witnesses carry a
key. Original final constraints still enforce the full meaning. This assumes
the existing stable snapshot, canonical identity and scalar contracts.

RQ: can early use of explicit constraints reduce avoidable intermediate work
while keeping one-shot answer semantics? X: late versus early anchor use on an
independent tiny graph with irrelevant paths. Y: exact answer, intermediate
row count and remote-call count. This is an engineering correctness gate, not
an ablation campaign or an observed SF0.1 speedup. Acceptance also covers
multi-provider disagreement, parallel transfers, empty keys, unsafe separate
roots/limit, a saved-plan-only admission replay, and one estimated-choice tiny
vertical slice. Do not rerun unchanged successful gates or full-data failures.

First four new checks pass in0.91s. On five tiny entities/eight edges, all six
independently specified reachability rows agree; total coordinator join outputs
fall from78 to36, with eight source calls in each execution. Four outgoing edges
including a parallel pair/self-loop reach the original path constraints. Union
provider disagreement, duplicate keys, edge count, empty anchors and unsafe
limit/OR/separate-root uses pass. The ordinary controlled-provider entry selects
by a frozen analytic test estimator and executes one reduced plan; no model
service, online fit, native service or actual-performance claim. Next: one new
authored business-ID temporal query on the existing frozen tiny native stores.

A fifth new dependency check passes0.26s: an otherwise eligible bind that would
depend on its own anchor source is rejected before execution; the other bind
and coordinator plans remain within the1+2J bound. Native query artifacts are
unchanged by the anchor reduction itself. Offline replay of both saved group5
interpretations admits three first-hop targets and eight estimated candidates
each, with no model/source/fit call or semantic edit. It does not rerun the data.

The first actual tiny native attempt (076c2f4) stopped before final execution:
the real frozen work estimator had no training support for the standalone
coordinator_semi_join category. The source services started and were closed;
query/source/model calls were zero and original EM0 remains. The test estimator
was analytic and did not establish this actual deployment support. Do not bypass
the unseen-work check or refit from evaluation answers.

The exact DISTINCT-key join expansion uses already supported projection/filter/
join work categories with unchanged weights, feature dimensions and data. All
five affected checks pass0.87s after this physical-form change. Offline replay
of the failed tiny request yields eight available frozen predictions; still no
query/model/fit call. New native attempts preflight model support before starting
services and retain the original worker error/costs if selection is unavailable.
This repaired development gate may run once on tiny data; no SF0.1 failure retry.

The repaired native gate at0f62658 passes: four independent nonempty rows exact,
eight estimates/bound17 choose one coordinator plan;14 calls/18,606 source bytes,
1719.774ms online, zero model/fit/load/alternative execution. All owned services
terminal. Next explicitly bounded evaluation continuation is unrun RDF NL group6
only, four methods once with original inputs/budgets and an implementation epoch.
The old handoff and RSS failures are not rerun or rescored.

New group6 at38ea7ab still hits the original RSS guard in both modes, after14
source calls and325,110,752 response bytes each. The14 saved native requests
are all unbound. The tiny acceptance establishes exactness, not a sufficient
real-scale memory fix. All four method failures remain; next frontier isgroup7.
Before new full queries, use tiny source-anchor binding and saved response
footprint analysis. Update the candidate bound if introducing a new strategy;
keep the original baseline input and estimator checks. No repeat ofgroups0–6.
