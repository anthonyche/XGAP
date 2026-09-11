# INT-3: three original FinBench queries on real Neo4j and Fuseki

2026-09-11; fixed clean worktree 9f00414f409dedb01415d6f87cb77ea7dbc2fa60.
The real-data integration gate passed:three fixed questions, two physical plans
per question, six exact results, followed by107/107 independent audit checks.
This is a new correctness observation on real FinBench facts, not a full paper
comparison, NL result or proof of a speed advantage.

## Frozen scope and source identity

Use original f1-01/f2-01/f3-01 from the unchanged 48-question workpack. IDs were
fixed before opening answers. f1's empty answer remains in the gate; it was not
replaced by a more convenient query. The full 32 seen / 16 cold formal cohort remains.
These three IDs are now explicitly integration-exposed. Preserve that label in
later evaluation and do not silently
reclassify these timings as prior training/preparation or tune a cold-family claim
on them; do not remove the IDs to hide the exposure.

The user-supplied original archive is66,710,298bytes, SHA
`f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60`.
The existing partition builder used18 snapshot tables/365,181rows, producing194
Neo4j batches and282,426 Fuseki triples. Build8.962s plus output verification0.059s;
partition artifacts total127,970,625bytes. No catalog, workload or oracle was rebuilt.
The source archive was copied and hashed; no new download or server action occurred.

**This gate loads the complete SF0.1 fact partition.** Only query execution is
limited to three instances; it must not be described as loading a toy graph.
The native API accepts the original archive-bound workload under the explicit
mode implemented by INT-2, and records the actual partition SHA
`0ee8b18d3289ddb11fd78308f14584d20f073deaa50f72cfad74b1a379cdab2b`.

## Actual outcomes

| Original query | Strategy | Exact rows | Execution ms | Runtime exchange bytes |
|---|---|---:|---:|---:|
| f1-01 |graph_first_hash|0|300.325|37,980|
| f1-01 |control_first_bind|0|123.514|37,890|
| f2-01 |path_first_hash|1|166.806|25,098|
| f2-01 |control_first_bound_path|1|106.816|24,928|
| f3-01 |aggregate_first_hash|10|278.344|249,974|
| f3-01 |control_first_bound_aggregate|10|127.335|35,836|

Every plan used two query calls:12total. Both strategies agree with the original
answers and with each other. The byte column is the existing scheduler's sum of
serialized rows at EXCHANGE operators (411,706total), **not measured HTTP/TCP wire
traffic**. In f3 this logical exchange volume is lower for control-first; this
one-instance observation motivates the planned comparison but cannot establish
population-wide performance or an agent/P1 advantage.

There is one fixed-order observation per plan, no balanced order/repetitions,
cache control or confidence interval. Both servers are local. Execution timings
are scheduler plan elapsed times; no LLM, acquisition-policy or colocated NL-to-answer
cost is included. Do not add them to remote model time and call that a measured E2E run.

## Real lifecycle and independent evaluation

A detached clean checkout prevents concurrent interpretation edits from changing
the measured source. Existing ServiceSpec/lifecycle, typed loaders and correctness
API are reused by a saved one-time local harness. The HPC CLI requires Slurm/staging
assumptions, so it was not invoked with invented allocation metadata. All evidence
explicitly says local/macOS, Java21, Neo4j5.26.30 and Fuseki5.6.0.

Server query limits60/75s and client limits75/90s were configured. The work budget
was800s with100s cleanup allowance and a6GiB sampled process-memory guard. Actual
sampled peak RSS was1,462,943,744bytes. The entire gate, including staging/start/load/
validation/cleanup, took38.398s. Live correctness including loads took15.936s;
Neo4j load194calls/13.227s, Fuseki load1call/1.325s. These are measured setup costs,
not query latency. Sampling is not an exact instantaneous memory maximum.

All six plans sealed before fact loading. Oracle bytes were hashed for identity;
the full original48-query oracle JSON was parsed only after all12 selected query
calls, exclusively for evaluation. Only selected3 answers were compared. The
existing independent auditor then reconstructed the evidence once:107checks pass,
no failed check, run_tree_mutated=false. No input was changed to make audit pass.

Neo4j PID39221 stopped with SIGTERM/exit0; Fuseki PID39263 stopped with SIGTERM/
exit143, with no forced-kill escalation. Both process groups were confirmed absent,
and the newly owned temporary runtime was removed. Original distributions, cached
source and evidence remain. No execution failed or was retried.

## Evidence and remaining work

Raw tree: `/Users/anthonyche/xgap-data/int3-finbench-20260911/`.
Audit: `/Users/anthonyche/xgap-data/int3-finbench-20260911-audit.json`.
Fixed source: `/Users/anthonyche/Developer/XGAP-int3-9f00414`.
[Machine receipt](../../experiments/artifacts/finbench_original_three_native_20260911.json)
contains exact build/run/audit commands, source identities, all six outcomes and
fingerprinted original records. The local harness is fingerprinted and retained
with the run, not substituted for a production service feature.

The dataset-to-partition-to-native-query-to-independent-answer boundary is now
observed working for these three prepared instances. This did not exercise NL or
ordinary P1; the two FinBench strategies are partition hash/bind alternatives,
not equivalent-replica placements. Next freeze actual method/cost/forecast inputs
and fair comparisons over the original population. Real model LINK still fails
on the original five programs; its preserved failure and prepared v2 are recorded
[separately](qwen_model_link_failure_20260911.md). Formal E1–E5, GrailQA answer
projection and new model-quality observations remain unfinished.
