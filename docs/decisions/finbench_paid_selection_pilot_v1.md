# Next E2 pilot: real cost of selecting between two complete FinBench strategies

2026-09-12, read-only preparation at0b7c56c. No new FinBench execution or result
is claimed here. This pilot follows the affected tiny compiler/cohort gate.

R-C asks whether information acquisition saves total cost compared with strong
fixed choices. Reuse the original SF0.1 partition, public inputs, query templates
and independent answers already verified at INT3. Do not rebuild catalog/data.
The first integration gate keeps the original exposed IDs f1-01/f2-01/f3-01.
All three remain integration-exposed, not training data or untouched evaluation.

Use three actual methods over identical inputs: fixed hash; fixed bind; execute
both complete plans as paid acquisition, seal the cost-only winner, then execute
that winner once for the method's answer. Charge both acquisition attempts,
selection and final execution to that method's wall time. Never reuse the sampled
answer as a free final execution. Deterministic ties follow the existing measured
latency/bytes/strategy rule. Keep acquisition outputs sealed from gold and score
only after method selection/execution records have been written.

The first three-question diagnostic permits at most15 complete-plan executions
and30 query calls. Freeze exact method/acquisition order and finite budgets before
dispatch; one block is descriptive, not a speedup claim. Preserve partial failure
costs and remaining not_attempted entries, with no automatic retries. Before a
formal paired comparison, use counterbalanced repeated blocks and aggregate
within query; original32seen/16cold and all failed/unsupported entries stay in the
48-question ledger. Do not extend the population by selecting successful IDs.

Implement only a small experiments-layer entry around existing
build_finbench_plan_candidates, FederatedScheduler, the cost-only selection rule,
canonicalize_finbench_rows and post-execution independent oracle comparison.
The old family campaign expects source_partition_sha256 absent from the original
workpack; do not fabricate it or forge the old confirmatory schedule authority.

This is a complete-strategy baseline, not ordinary P1/A3: hash executes two source
queries in parallel then joins, whereas bind executes control before a bound
remote query. Their DAGs differ, so they are not equivalent source replicas.
An A1–A4 bridge additionally needs an explicit strategy space and the actual
control_ids domain in bound-request forecast identity. INT3 execution times are
not raw PROFILE receipts or free prior samples. Two-candidate choice cannot prove
P1 scaling; this one graph size cannot provide an E4 graph-size curve.

Existing inputs: /Users/anthonyche/xgap-data/int3-finbench-20260911/ and the
original workpack under /Users/anthonyche/xgap-data/int-finbench-workpack-20260911/.
Acceptance is exact answers in every attempted arm, reconstructable paid costs
and winner identity, complete failure/unrun accounting, and no relabeling as
P1/A3 or a formal performance advantage. A concrete implementation still remains.
