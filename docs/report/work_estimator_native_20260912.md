# Frozen workload estimator v2 — implementation and tiny native evidence

2026-09-12, source checkpoint `a2c19080220d46f1313270951352c5f81721a526`.
[Contract](../decisions/runtime_work_estimator_v2.md) ·
[Machine-readable evidence](../../experiments/artifacts/work_estimator_native_20260912.json).
Original outputs: `/Users/anthonyche/xgap-data/work-estimator-v2-native-20260912-a2c1908/`.

## Implemented behavior

The new 72-feature model associates full/bind Match/Path work with the actual
backend, compiled path span/column width, source-record/byte proxies, dependencies
and coordinator work. Swapped backend assignments no longer alias. Neither native
query text nor query IDs, answers, measured execution or observed winners enter
the feature vector. Work units are not result cardinalities or selectivity.

Fixed 128-sweep nonnegative relative-ridge fitting happens offline. Nonnegative
weights and positive scales ensure componentwise increases of represented work
cannot decrease the estimate. This is a surrogate property, not a backend-time
guarantee. Missing descriptors/statistics and unseen workload categories produce
unavailable predictions; numerical range extrapolation remains visible and
uncalibrated. The ordinary request entry and frozen-model loader accept v2.
Historical v1 code/models retain their identity and behavior.

Five new targeted checks passed once in 0.54 seconds: swapped assignments and
metadata exclusion; learned distinctions and monotonicity; unseen/missing work;
frozen loading/legacy compatibility; split and iteration bounds. A new zero-call
CLI preflight passed. The existing 64 checks and B01 answer gate were not rerun.

## Actual collection and excluded request

The manifest declared all programs, order, budgets, statistics and excluded IDs
before any service started. It covers 28 new training plans: constrained Match,
one/two-edge Path, aggregate/order, union/alignment, Match–Match and Path–Match
joins, coordinator/bind strategies and both backend assignments. The order has
one fixed seed; it was not searched. All 28 completed successfully, with 46
backend calls. Two constant warmup calls are separate. The original four training
plans and B01–B05 were not recollected or used as labels.

The fitted model was saved and reloaded before the excluded `WORK-HOLDOUT-01`
request. This request supplies an independent declared semantic program through
the ordinary performance entry. It is **not an LLM interpretation test** and is
within a covered query-template family, with unseen parameter values/identity.

Three placements generated six admitted candidate plans (construction bound nine).
Only estimated costs selected the coordinator plan with Path on Neo4j and Match
on Fuseki. One final plan made one query call to each real backend; there were
zero current-query observations, zero online fits and zero LLM calls. The sealed
answer `(person=https://xgap.test/toy/a, edge=https://xgap.test/toy/e3)` exactly
matches the independent fixture reference accessed after sealing.

| Quantity | Observed value / scope |
|---|---|
| Training collection | 852.007 ms; includes per-action persistence |
| Offline fit | 22.965 ms, once |
| Frozen reload | 0.834 ms |
| Training log RMSE | 0.8651; descriptive in-sample residual |
| Training relative RMSE | 0.4352; descriptive in-sample residual |
| Selected execution estimate | 9.524 ms |
| Actual selected scheduler execution | 18.695 ms; multiplicative error 1.963× |
| Current selected numeric features outside training ranges | None; axis-wise range membership is not a generalization guarantee |
| Ordinary planning | 37.287 ms |
| Execution wrapper | 18.906 ms |
| Ordinary end-to-end | 58.465 ms; declared semantic input, no LLM |
| Separate service setup / fixture load | 7,379.449 / 247.548 ms |
| Separate constant warmup calls | Neo4j 24.508 ms, Fuseki 35.243 ms |
| Owned lifecycle including cleanup | 20,324.241 ms; not query latency |

The new estimate is finite and useful enough to exercise selection, but one
excluded point does not establish estimator accuracy, ranking quality or speedup.
No other plan for this query was timed, so actual plan regret is unknown. The
old 0.0054 ms versus 78.93 ms result concerns a different request/run/model; do not
compute an improvement ratio or speedup between those points. Planning overhead
is material on this tiny workload and remains part of total online time.

## Integrity and remaining gates

All 434 input fingerprints match. The 28 measurement hashes, manifest hash and
held-out result/evaluation seal match, and excluded IDs do not overlap training.
The previous frozen model's SHA is unchanged. New model SHA:
`33badbbe8e8ecea1e69c5318902a809219a96d5d4a775e36fd06750070eee177`.
Owned Neo4j PID 9206 and Fuseki PID 9247 stopped without SIGKILL; an independent
process check found neither present. No service, Slurm job or model request is
pending from this gate.

Real cross-backend execution is now verified in the new ordinary deterministic
chain. Both stores still contain complete replicas of the toy graph, so this is
not a demonstration that distributed data requires both sources. Next use a
tiny split-source fixture and verify an NL-only input without prepared operator
IDs/structured constraints. The guided real-model precision gate remains accepted.

The wider prototype and evaluation goal remains active. Preserve all previous
failure/negative results and continue with new-boundary tests only; no baseline,
ablation, scale campaign or big-data development ran in this milestone.
