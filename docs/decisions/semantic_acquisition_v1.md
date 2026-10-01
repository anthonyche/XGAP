# A3: cost-aware stop versus one nominated observation

Frozen at d331631,2026-09-11. R-C/E2/E3 scope: connect an actual cost decision
to A1's existing request/collection/reselection path. Do not add general policy
search, LLM reasoning or dataset preparation. The nominated request is A1's
largest-historical-latency key in the initial selected plan (stable tie). Choosing
that request is a declared heuristic; this rule optimizes whether to issue it,
not the globally best information action.

Input: a complete warm snapshot, prepared P1 space and initial feasible plan p0;
an explicit finite list of predictive outcomes for that one key, with positive
probabilities summing to1, remote elapsed time, rows, width, and forecast provenance;
expected acquisition and incremental reselection costs in milliseconds; and a
finite budget on their expected sum. Other keys, cost parameters and the feasible
placement domain remain fixed. The acquisition observes the changed key. A model
is supplied by the caller/preparation stage; no oracle answers, hidden profiling,
or runtime fitting constructs it. Predictive calibration must be evaluated later.

For each outcome s, replace only that key in a copy of the snapshot. Run P1 with
**p0 as its baseline**, obtaining p_s and U_s=C_s(p_s). Separately score C_s(p0).
The actual post-observation P1 must also start from p0, not the preparation-time
baseline. All hypothetical and real plans preserve the same semantic program.

Let c be expected acquisition+incremental reselection cost. Compute

`G_hat = sum_s w_s [C_s(p0) - U_s] - c`.

Acquire iff G_hat>0 and c fits the expected-cost budget; otherwise stop and
execute p0. Ties stop. This compares two concrete strategies under the declared
finite predictive model. In particular, a current snapshot's U−LB is **not**
information value, and no submodularity or1−1/e claim is made. Always-acquire and
never-acquire controls use existing A1 modes; their rollout overhead is not
artificially padded to equal A3.

## Conditional decision-quality bound

When P1 supplies valid LB_s for every positive-mass outcome, define
Delta=sum_s w_s(U_s−LB_s), G_upper=G_hat+Delta. For this single request, with an
optimal full-domain placement after observing its outcome, net expected benefit
G_star satisfies G_hat≤G_star≤G_upper. This follows directly from
LB_s≤OPT_s≤U_s≤C_s(p0). Duplicate indistinguishable outcomes have identical
changed-key states and hence identical optimization problems.

Compared with an oracle choosing only stop(p0) or this request followed by an
optimal admitted placement, expected decision regret is at most:

- stop: max(0,G_upper), including when the forecast budget prevents acquisition;
- acquire chosen by this rule (G_hat>0): Delta.

G_hat≤0 only says the specified P1 response strategy has no predicted net benefit.
G_upper≤0 is the stronger sufficient condition ruling out benefit even with
optimal subsequent placement. Missing LB makes G_upper/regret unavailable, not0.
These bounds exclude the common already-incurred decision CPU time and refer to
the declared discrete cost model, the same c, and this one request. They do not
bound realized wall time, a globally best action, inference quality, or a learned
forecast's error. A forced-acquisition control need not satisfy the acquire bound.

## Ptime, runtime and accounting

S predictive outcomes are explicitly represented input. Per outcome there is
one fixed-pass P1 and one initial-plan score: O(S*(T_P1(L,K,b)+T_score(L,b))) time
and polynomial trace/storage. No Cartesian placements or exponential scenario
generation are allowed; no repeated-until-convergence loop. Actual acquisition
is at most one call and actual reselection at most once. That action count is a
resource bound, not a solution-quality theorem.

Ordinary query entry forwards a typed acquisition policy. It is mutually exclusive
with A1's explicit refresh modes, A2 prefix policy and static selection. Warm
snapshot admission, memory read-only behavior, failed-call retention and no-retry
semantics reuse A1. The expected-cost budget is not a hard wall-time guarantee;
existing native transport limits still apply. Decision CPU, acquisition, actual
reselection, execution and history are all charged at their existing boundaries.
Actual observations remain raw. Record exact forecast-support agreement as a
diagnostic; out-of-support observations still enter deterministic P1, but do not
acquire an invented realized guarantee. No forecast/memory update occurs online.

Acceptance: low/high expected cost and budget decisions, a tiny independent
two-outcome/placement oracle for G and the conditional bound, unchanged hard
meaning/gold, no-acquisition/always-acquire controls, ordinary B04 forwarding and
immutable memory, and terminal admission/failure accounting. Select only affected
A1/A2 checks. No new native boundary is introduced; existing native collector,
execution and reuse evidence is retained, not rerun or relabelled as an A3 run.
Real-model LINK and real-data INT/E1–E5 remain part of the full Goal.
