# A3: cost-aware stop versus one observation — 2026-09-11

The ordinary query entry now makes a predictive cost decision before an A1
profile request. It executes the initial plan immediately when predicted savings
do not cover acquisition plus incremental reselection, or when the expected-cost
budget disallows the action. It performs one real acquisition/reselection when
the declared model predicts positive net benefit. Request nomination remains the
existing largest-historical-latency heuristic; this is not global action search.

This closes the missing stop/acquire decision rule for the bounded R-C/E2/E3
prototype. Forecast preparation/calibration and real-data comparisons remain
necessary; this result is not evidence that A3 saves actual workload time.

The caller supplies finite predictive outcomes, probabilities, costs and
provenance. Each outcome changes only the nominated key. Both hypothetical and
actual response planning start from the same initial selected plan p0, retaining
P1's non-regression guarantee within each updated model. The decision computes
paired expected execution savings minus expected extra cost. Decision CPU is
charged to the query; simple baseline methods are not forced to pay this overhead.

With valid per-outcome LB_s and returned costs U_s, Delta=sum w_s(U_s−LB_s).
Net benefit from this request with optimal subsequent placement lies between
G_hat and G_hat+Delta. The cost-aware rule's conditional decision regret is at most
Delta when acquiring, and max(0,G_hat+Delta) when stopping. Missing certificates
remain unavailable. These are discrete-model, one-request bounds; they do not
establish actual-latency, forecast-error or optimal-information-action guarantees.
The [algorithm contract](../decisions/semantic_acquisition_v1.md) gives the input,
formula, stopping conditions, assumptions and polynomial complexity in explicit
scenario count S and P1 input size. A3 does not generate scenarios or placements
by Cartesian enumeration.

The single-source synthetic decision fixture has expected execution costs
501.2ms for stopping and6.2ms after the specified P1 response, before acquisition
cost. These are **asserted model values, not measured workload latency**:

| Expected extra cost | Expected-cost budget | Net gain | Decision | Conditional regret bound |
|---:|---:|---:|---|---:|
| 2ms | 1000ms | 493ms | acquire | 0ms |
| 501ms | 1000ms | −6ms | stop | 0ms |
| 2ms | 1ms | 493ms | stop: budget | 493ms |
| 495ms | 1000ms | 0ms | stop: tie | 0ms |

An independent four-placement, two-scenario oracle also checks a nonzero gap;
the verification does not rely only on an exact single-source case. B04 uses
the unchanged ordinary question/gold chain and identical saved history for A3
acquire/stop plus A1 always/never-refresh controls. All answers are correct, only
the acquired arms issue a profile, and memory bytes remain unchanged. An actual
observation outside the forecast's row support still executes deterministically,
with support mismatch recorded and no invented realized bound. The first failed
profile retains one attempt, zero selected execution and no retry.

The first new-file run passed12 cases and failed1 in0.61s. At exact zero net
gain, subtracting two weighted cost totals produced5.684341886080802e-14ms and
incorrectly acquired. The implementation now sums paired per-outcome savings
before subtracting extra cost. Five affected cases pass in0.20s; two later
control/failure checks pass in0.56s. Fourteen unique new cases now have passing
evidence; unchanged cases were not rerun. Three affected existing A1/A2 checks
pass in0.59s. The explicit
[failure replay](../../experiments/replays/semantic_acquisition_zero_gain_d331631.json)
preserves inputs, the old formula's spurious gain and the corrected stop decision.

[Evidence receipt](../../experiments/artifacts/semantic_acquisition_20260911.json)
pins code/test hashes and the verification scope. No broad regression, native
service launch, LLM call or large dataset run occurred. The native collection and
execution adapters are unchanged; prior A1/A2 native observations are retained
as their original evidence, not relabelled as new A3 experiments.

Next finish prepared real-input/forecast interfaces and independent answers for
LINK/INT, then the frozen E1–E5 comparisons. The main Goal remains active and the
September18 new-real-results deadline unchanged. UI, general policy frameworks
and catalog reconstruction are not added to the critical path.
