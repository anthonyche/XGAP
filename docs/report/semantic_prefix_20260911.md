# A2: execution-prefix adaptation — 2026-09-11

A2 connects the ordinary polynomial semantic planner to one executed source
prefix and residual planning. The completed source remains on its original
backend; its exact successful results are reused. Only unfinished placement may
change. This closes an E2/E3 mechanism-integration gap, not the full research Goal.

Research question: can actual execution observations improve subsequent physical
decisions while preserving meaning and accounting for their full cost? The
controlled X factor is residual reselection enabled/disabled after the same
source prefix. Y factors are independent-answer correctness, unfinished placement,
actual calls/time, residual estimated cost and its certificate. Synthetic history
is an explicit intervention; actual responses are not rewritten. This development
gate is not evidence of a real-workload speedup.

The tiny query joins an Alice Match with a Person Match on entity identity. In
the frozen history, the first source's long latency hides the second source's
latency. The old model prefers the second source's low-cardinality option. Once
the first source completes, its ready time is zero and actual output replaces
its estimated cardinality; the unfinished source's faster option becomes better.
The no-replan arm observes the same prefix but keeps its original placement.

The [algorithm contract](../decisions/semantic_prefix_v1.md) pins the remaining
optimization domain and objective. With a sound monotone relaxation:

`LB <= OPT_remaining <= U <= cost_remaining(continue_initial)`.

All terms use the same updated estimated model and fixed completed source. Exact
P1 subcases retain exact primary-cost optimality. Coupled cases retain the two-pass
heuristic and instance-specific additive/ratio certificate; topology changes have
only baseline non-regression. No universal ratio for actual latency, optimal prefix
choice or information acquisition is established. Candidate limits are not bounds
on solution quality. No exponential candidate product is materialized.

Accounting uses final scheduler totals once because they already include reused
nodes. Prefix and continuation execution times are disjoint; residual planning
is counted separately. The full-plan call budget stays intact. Failed prefixes
stop without a second execution or retry; incomplete/altered reuse is rejected.
Partial observation updates do not overwrite or renew the historical memory.

Directed verification:

- Ten new checks pass in0.61s: changed unfinished placement, disabled/below-threshold
  arms, B04 ordinary question entry with zero residual cost and read-only memory,
  a two-option residual oracle, exact reuse and failed-prefix/conflict accounting.
- Thirty affected checks pass in0.81s: the P1 selector/certificate tests plus one
  existing three-arm A1 question-entry test. They address the shared selector
  injection and execution branch; no full-suite regression was run.
- Independent static review found no defect in the residual relaxation, restricted
  domain, prefix identity or failure/call accounting. Review is not a new test.

Native gate66672 exits0. Both arms, two independently authored Neo4j/Fuseki
reference queries and the retained federated slice pass. Method calls4 +
references2 + retained slice2 =8 validation queries, excluding setup/load/health.
All42 source hashes match; owned Fuseki15046 and Neo4j15010 stop successfully
without forced kill. No source code changed after the native launch.

| Arm | Completed source | Unfinished source | Calls | Answer | Residual estimated cost | Observed arm wall time |
|---|---|---|---:|---|---:|---:|
| replan | Neo4j, reused | Fuseki | 2 | correct | 4.50ms | 237.06ms |
| no_replan | Neo4j, reused | Neo4j | 2 | correct | 100.44ms | 53.56ms |

The residual certificate is LB1.44ms, U4.50ms, ratio bound3.125. The restricted
domain contains only the two recorded placements, so its model optimum is4.50ms:
the selected continuation is optimal in this tiny case, but the certificate is
loose. This does not upgrade the general heuristic to an exact algorithm.

**No-replan was faster in this single fixed-order observation.** Prefix timings
were184.01ms versus11.45ms; backend cache/initialization conditions were not
balanced or independently established. Arm wall time includes durable trace
writes and excludes the shared11.95ms local preparation. The planning-run trace
also attributes that preparation to each arm, giving249.01ms and65.51ms; do not
mix these boundaries or claim a causal speed difference. Historical costs are
explicitly synthetic with no measured acquisition expense, not free real history.
Both current native responses and the slower arm are retained unchanged.

[Evidence receipt](../../experiments/artifacts/semantic_prefix_20260911.json),
[per-arm CSV](../../experiments/artifacts/semantic_prefix_20260911.csv), and raw
`/Users/anthonyche/xgap-data/a2-prefix-native-20260911/result.json` retain the full
boundaries and provenance. This native gate uses the deterministic-planning track;
ordinary question forwarding is covered by the B04 module check, not claimed as
native Interpretation/GoalLoop evidence. An initial zero-call local preflight
unpacked the fixture tuple incorrectly; the diagnostic command was corrected
before the sole native launch, without changing implementation or retrying any
external action.

Remaining research obligations: deciding when acquisition is worth its cost,
real-model LINK, real-data answer integration, and the frozen E1–E5 comparisons.
Existing compiler/runtime functionality is not reclassified as absent merely
because those evaluation gates are unfinished. Keep the September18 deadline;
development remains on tiny data and all historical negative results remain valid.
