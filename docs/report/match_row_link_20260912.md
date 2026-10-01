# Five real model recordings reach complete native outcomes: three correct, two rejected

2026-09-12, parent0b7c56c plus separately fingerprinted changes. This is LINK
development evidence on the frozen tiny graph, not a real-dataset paper result.

The complete original five-question cohort now has measured terminal outcomes.
B01/B04/B05 return the exact original expected rows. B02/B03 retain their
Interpretation errors before backend access. There were **zero new model calls**:
all five original v3 recordings and request contexts were reused unchanged.

| ID | Outcome | Actual rows (toy IRI suffixes) | Observation + execution calls | Replay-to-terminal ms |
|---|---|---|---:|---:|
| B01 | Correct | person=c, edge=e4 | 4 + 2 | 404.45 |
| B02 | Interpretation rejected | Not executed | 0 + 0 | 0.96 |
| B03 | Interpretation rejected | Not executed | 0 + 0 | 1.03 |
| B04 | Correct | person=a, age=30 | 2 + 1 | 118.28 |
| B05 | Correct | person=c, edge=e2 | 4 + 2 | 69.30 |

Strict correct completion is **3/5**, not3/3. B03's empty expected answer does not
make its failed interpretation correct. Cohort processing completed, while the
all-correct flag remains false; native exit1 reflects that distinction.

B01's ordinary P1 `coordinate_two_passes` selected Fuseki for paths and Neo4j for
the people Match. Their actual results joined at the coordinator. B05 used the
same ordinary algorithm but selected Fuseki for both source operators; B04 used
`independent_source_minimum` and Fuseki. Only B01 is a selected cross-engine plan.
Selected execution times were18.96/7.97/9.78ms for B01/B04/B05, separate from
planning/resolution/replay. These one-pass toy times do not establish speedup.

The run made15 query-related backend calls:10 observations and5 executions.
Two fixture loads, startup/health and shutdown are separate. Total native process
time was20.014s. The previous actual generation cost remains5calls/12169tokens/
16.231s, already recorded in the preceding report; do not charge it twice or sum
cross-time stages into a claimed online NL-to-answer latency.

## What changed

The [bounded Match extension](../decisions/match_row_constraints_v1.md) supports
named binding-row conditions on Match's own explicit output fields. The compiler
adds an existing COORDINATOR_FILTER after native Match and row normalization.
Path conditions retain their native semantics. Row conditions retain Boolean,
null and numeric rules; they are not translated into potentially different path
predicates. Missing fields fail before native observations. No property, answer,
projection or model response was invented or repaired, and hard constraints keep
their original representation and ownership. Legacy Match plans are unchanged.

This is new supported condition placement. It does not retroactively prove that
the model followed the old prompt, which required path predicates on Match.
The original payloads are unchanged; the compiler now supports their explicit
row meaning. B02/B03 still lack age production and remain rejected by the current
final-root contract. No prompt-tuning or repeated generation was performed.

The optional recorded-cohort runner preserves all five IDs and continues after
known prebackend Interpretation failures. It stops on backend failure or unknown
cost instead of using the legacy zero default for missing metrics. Partial
outcomes/costs are persisted before replay-consumption checks. Default fail-fast
gates remain unchanged. This cohort does not rerun the candidate matrix, native
reference targets or unrelated retained slice; each current actual answer is
checked against the already-frozen expected rows.

## Verification and next experiment

First focused runs passed10 compiler/typed-value/ordinary-P1 checks in0.39s and
7 cohort-accounting checks in0.16s. No old successful gate or broad regression was
repeated. The native run's342 source/runner hashes and all six recording/result
file hashes remained unchanged. Both owned services stopped successfully; a
separate process check confirms PIDs62798/62840 no longer exist.

Raw evidence: `/Users/anthonyche/xgap-data/match-row-link-20260912/`.
[Machine evidence](../../experiments/artifacts/match_row_link_20260912.json) binds
the exact rows, full denominator, separate costs, hashes, first-pass receipts and
cleanup. Original Qwen0/5, external-v2 strict0/1 plus4unrun, v3 admission3/5,
FinBench6/6 and original150/48 populations remain unchanged historical evidence.

The real model-to-native execution boundary now has correct-answer evidence;
five-question all-correct quality is still not achieved. Do not block independent
deterministic-planning experiments on perfect model generation. Next implement
the [real FinBench paid-selection pilot](../decisions/finbench_paid_selection_pilot_v1.md):
fixed hash, fixed bind and paid dual-plan acquisition, preserving costs and the
three exposed integration IDs before the original48. This is an E2 strong-baseline
track, not yet a P1/A3 result. Real-data effectiveness, calibrated prior costs,
full method/ablation comparisons and scalability remain required by the deadline.
