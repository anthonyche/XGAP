# A4: offline empirical preparation for one exact acquisition request

Scope frozen on 2026-09-11 after A3 and INT-1. R-C/E2/E3 need a reproducible
source for A3's outcomes and expected acquisition/reselection costs. This is a
bounded preparation interface, not a general learned information policy. The
X mechanism is cost-aware stop/acquire; Y is correct completion and actual total
cost relative to never/always-acquire, with preparation cost separately retained.

Input is an explicit finite list of prior training/preparation observations for
one registered PROFILE request and one P1 context/environment episode. No answer
labels are consumed. A caller-declared cutoff precedes evaluation; original
timezone-qualified observation start/end must precede sample completion and that
cutoff. Source receipt hashes are retained for independent experiment intake
audit; a hash-shaped string or a caller's phase label does not prove provenance.

The builder rejects the entire preparation on any supplied failure or mismatch.
It never drops unsuccessful samples to produce a forecast. It validates the
original response's operation, backend, catalog/version and exact compiled query
artifact identity/hash, inner success/identity, and the estimate derived from that
response. The same raw tool result cannot be counted again under a new sample ID.
All accepted samples receive equal weight; there is no tuning, truncation, family
transfer, runtime fitting or external call in the builder.

Algorithm:

1. Hash the P1 semantic/local-option context, all requests, environment episode
   and cost parameters. Bind the chosen request separately.
2. Validate and retain each complete original observation and its prior phase,
   timestamps and source receipt identity.
3. Set outcomes to the observed backend latency/rows/width with weight 1/S.
   Set expected acquisition cost to mean collection wall time, and expected
   incremental reselection cost to the mean separately measured P1 reselection.
4. Return a typed A3 policy plus a content-identified preparation receipt,
   including all historical calls/costs and measured preparation CPU time.
5. Before forecast rollout or backend calls, compare with the **current** runtime
   episode, context and nominated request. Memory supplies its declared current
   episode; explicit snapshots need an explicit episode. Missing or conflicting
   episodes fail closed. The target's stored episode is not evidence of the
   current episode.

Snapshot estimates may change without changing context; if the changed initial
plan nominates a different request, the old forecast is rejected. Explicit A3
synthetic policies without a prepared target remain available for mechanism
tests; they are not certified preparation artifacts.

Let B be the total serialized sample bytes, L the serialized context/query bytes,
and S the explicit sample count. Reading, hashing and aggregation are linear in
these input bytes; canonical JSON sorting gives a conservative
O((B+L) log(B+L)) preparation bound, with O(B+L) stored input/receipt size.
A3 still performs S fixed-pass P1 selections and initial-plan scores. There is
no Cartesian placement or implicit exponential scenario expansion. The
[A3 conditional decision-regret bounds](semantic_acquisition_v1.md) are unchanged;
empirical preparation adds no calibration, generalization or actual-latency bound.

New refresh traces split actual P1 `reselection_ms` from common final
`scoring_ms`; their sum remains the previous `selection_ms`. These are measured
cost components, not free computations. Existing A1 traces combine them and
cannot retrospectively supply pure P1 time. Historical preparation acquisition,
reselection and CPU costs must be reported separately and amortized only under a
predeclared evaluation rule. Actual query E2E still includes rollout, wrapper,
collection, selection and execution overhead; the expected-cost model does not
promise to predict each of these components exactly.

Acceptance is the narrow synthetic preparation/gold chain, mismatch and leakage
replays, ordinary question/memory forwarding, and preserved cost totals. No new
native boundary is introduced. Real training/preparation source receipts and
calibration are separate pending evidence, not satisfied by these tests.
