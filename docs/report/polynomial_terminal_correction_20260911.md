# P1 terminal-source correction — 2026-09-11

The ordinary polynomial planner now recognizes independent terminal source
fragments even when their estimated rows/widths differ across replicas. This
closes the concrete quality defect retained at6ed9cce. It changes neither the
semantic profile nor the compiler, cost function, native query text, or evaluation
population. The original negative result and its raw artifacts remain unchanged.

Research connection: P1/R-S asks whether placement can remain polynomial as
source operators and replica options grow, with an explicit quality guarantee.
Here X is the admission/selection algorithm on identical cost-table inputs;
Y is estimated objective regret, scoring work and diagnostic planning overhead.
The exactness proof is conditional on the existing nonnegative critical-path
surrogate. This is development evidence, not the new real-data experiment due
bySeptember18.

| Check or measurement | Outcome |
|---|---|
| Preserved m4/k8/seed9 input | Estimated cost63.936→10.096ms; frozen oracle10.096ms; model regret6.3328→1 |
| Affected frozen grid only | 150 variable-row runs;70 reused exhaustive oracle values all matched;73 primary costs improved |
| Largest placement input | m32,k8;256 local scores and at most2 full-plan scores; no product enumeration |
| Selected local tests | 29passed in0.72s, including changed-branch RDFLib execution against independent toy gold |
| Saved native decisions | All10 cold/warm native plans and primary costs identical;8 selection records identical;B04's two certificates become exact |
| New costly work | 0 backend calls,0 LLM calls,0 large-data runs,0 new exhaustive grid runs; no broad suite |

For m32/k8 variable-row cases, median allocation-traced selection time changed
from2527.24 to35.86ms. Preparation is still1173.65ms in the new run; it was not
optimized here. These CPU diagnostics include tracemalloc overhead and simulated
replicas. They are neither real endpoint scalability nor query latency speedups.

The implementation checks consumption using every semantic input ID. Sources
that have a consumer still require invariant row/width estimates; a source may
also be listed as a root. Terminal fragments contain all their own variable
work, so local minimization is sufficient. The fixed-topology, no-source-input,
and all-combinations-fit-budget checks remain. The
[algorithm contract](../decisions/planning_ptime_contract_v1.md) gives the max-plus
induction and a two-root counterexample to coordinate search. The exact branch
uses K local scores and at most2 full-plan scores; the general two-pass branch
retains baseline non-regression and conditional instance bounds, not a universal
constant approximation ratio.

Verification had one replay-harness failure: after all150 model inputs passed,
an assertion expected every native selection diagnostic to remain unchanged.
B04 is actually a terminal Match, so its selected plan is unchanged but its
certificate correctly improves. The assertion was corrected; all completed
model cells were reused and only native decisions were replayed. The failed
attempt and its source hash remain recorded. No native service was restarted.

Artifacts:

- [Explicit original counterexample](../../experiments/replays/polynomial_terminal_sources_6ed9cce.json)
- [Evidence receipt](../../experiments/artifacts/polynomial_terminal_correction_20260911.json)
- [Per-cell comparison](../../experiments/artifacts/polynomial_terminal_correction_20260911.csv)
- Raw final replay:`/Users/anthonyche/xgap-data/p1-terminal-replay-20260911-final/result.json`
- [Replay command implementation](../../scripts/replay_polynomial_terminal_probe.py)

P1's present scoped implementation gate is accepted. The research prototype is
still incomplete: ordinary-entry acquisition currently collects all observations
on a miss, reuses a complete snapshot on a hit, then selects/executes once. Older
method/adaptive runners exist, but rely on explicit candidate tuples and are not
yet connected to this polynomial placement space. That is an integration gap,
not merely absent experimental evidence.

The next bounded gate is one admitted profile refresh from a shared complete
historical snapshot and optional pre-execution reselection. Reuse the collector,
snapshot merge and P1 selector; compare refresh+reselect, refresh without
reselection, and no refresh on the same B04 input and independent gold. Freeze
J=1 acquisition, at most one reselection, full current/historical cost accounting,
and terminal failure without retry. This supports a specific E2/E3 comparison;
it must not be labelled execution-prefix adaptation or the full agent. Actual
prefix continuation requires fixed executed placements, exact reusable-node
definitions and a residual feasible-domain/cost contract. Real-model LINK and
frozen real-data INT/E1–E5 evidence remain pending. Remote3804011 was not polled
or resubmitted during this step.
