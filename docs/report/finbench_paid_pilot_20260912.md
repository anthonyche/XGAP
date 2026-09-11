# Real FinBench paid-selection pilot: correct answers, charged acquisition, timing confound

2026-09-12, parent `0f741fb` plus individually fingerprinted implementation.
This R-C/E2 integration pilot executed fixed hash, fixed bind and paid selection
on the original three integration-exposed FinBench questions. **All nine final
method answers and six acquisition answers match the independent oracle.**
There are three independent questions, not fifteen independent samples.

The complete SF0.1 partition was loaded once into actual Neo4j 5.26.30 and
Fuseki 5.6.0. It covers the previously frozen 365,181 source rows. All original
48 query IDs remain in the ledger: 32 seen-family and 16 heldout-family.
F3-01 retains its original heldout label and its integration-exposed annotation;
the other 45 questions remain not_attempted. No catalog, source partition,
workload, model response or independent answer was rebuilt or modified.

## Actual observations

The frozen question IDs end in `f1-01`, `f2-01`, `f3-01`. Their exact final
answer cardinalities are respectively 0, 1 and 10 in every method. F1's empty
answer is a successful execution verified against the oracle, not a failed run
counted as correct empty.

| Query | Method | Method wall ms | Charged scheduler ms | Query calls | Logical exchange bytes |
|---|---|---:|---:|---:|---:|
| F1-01 | Fixed hash | 278.93 | 264.97 | 2 | 37,980 |
| F1-01 | Fixed bind | 153.18 | 122.34 | 2 | 37,890 |
| F1-01 | Paid selection | 235.15 | 62.90 | 6 | 113,850 |
| F2-01 | Fixed hash | 152.44 | 11.63 | 2 | 25,098 |
| F2-01 | Fixed bind | 260.43 | 161.48 | 2 | 24,928 |
| F2-01 | Paid selection | 433.72 | 117.83 | 6 | 74,954 |
| F3-01 | Fixed hash | 447.09 | 105.33 | 2 | 249,974 |
| F3-01 | Fixed bind | 475.93 | 49.15 | 2 | 35,836 |
| F3-01 | Paid selection | 1,064.44 | 406.12 | 6 | 321,646 |

Charged scheduler time sums every acquisition and final plan execution for that
method; paid selection does not report only its winning execution. Method wall
also includes synchronous progress/result persistence, selection and final row
normalization. Both columns are observed; they are different measurement scopes.
Bytes are runtime logical exchange, not HTTP wire traffic.

Paid selection chose hash for F1 and bind for F2/F3. Each choice used only
observed latency, logical bytes and the deterministic strategy tie-breaker.
Both acquisition outcomes were saved, then the choice was durably sealed before
a new final execution. No sampled answer was reused. Only after the complete
execution record was sealed did the driver parse independent answers to audit
all fifteen actual outcomes.

Total query-related calls were 30, split 15 Neo4j and 15 Fuseki; all fifteen
plan runs completed. Shared public-input validation/candidate compilation took
38.41ms, separately excluded from method wall. Service startup and loading took
20.54s, including 194 Neo4j load operations and one Fuseki load operation.
The measurement block took 4.07s and the native process 37.27s including cleanup.
No new model call, server job, download or automatic retry occurred.

## What this supports, and the measurement issue it revealed

The real heterogeneous execution and accounting boundary works for all three
prepared methods. In F3, fixed bind returned the same ten rows while exchanging
35,836 bytes versus hash's 249,974. Yet paid selection exchanged 321,646 bytes
because trying both strategies has a cost even when its final choice is bind.
This is concrete evidence for why R-C must measure acquisition plus execution.
It does not establish that the current acquisition policy saves total cost.

No performance advantage is claimed. This is one block with method positions
rotated across different questions; there is no within-question counterbalancing
or repeated measurement. The first query compilations and paid acquisition also
change cache state. For example, F1 paid scheduler time being below fixed bind
does not establish a fair speedup.

The pilot additionally exposed an instrumentation problem: every progress update
rewrites the growing full 48-question ledger and accumulated raw results. The
final sealed file is 5,800,018 bytes. F3 fixed bind has 475.93ms method wall but
only 50.53ms across the scheduler call boundary, leaving 425.40ms of non-call
work. That residual includes persistence, normalization and bookkeeping; it is
not separately measured disk time. Its dependence on accumulated results makes
this runner unsuitable for formal method timing without a small correction.
Do not repair this result by subtracting estimated overhead after the fact.

These are complete-strategy baselines, not ordinary P1 or A3. Hash and bind use
different DAGs, so they cannot be treated as interchangeable source replicas in
the current placement space. The
[frozen protocol and conditional selection bound](../decisions/finbench_paid_selection_pilot_v1.md)
state the computation/black-box-execution distinction and its assumptions.

## Verification and next gate

Twelve new focused core/cost/tiny-coordinator checks passed first run in 0.55s.
Two new post-seal evaluation checks passed first run in 0.19s; they distinguish
unattempted slots, unknown results and failed empty answers. No unchanged gate
or broad suite was rerun. The native pilot ran once and exited zero. A subsequent
artifact-only audit passed 23 consistency checks with zero execution calls.
All 361 source/input file fingerprints remained identical. Neo4j PID66620 and
Fuseki PID66664 stopped without escalation; a separate process check found both
absent, and only the owned temporary database state was removed.

Raw evidence is under
`/Users/anthonyche/xgap-data/e2-finbench-paid-pilot-20260912/`.
[Machine evidence](../../experiments/artifacts/finbench_paid_pilot_20260912.json)
contains the full population/evaluation status, separate costs, exact source and
receipt identities, frozen orders and cleanup. Previous LINK3/5, original
FinBench6/6, model failures and original150/48 populations remain unchanged.

Next persist each new action result once, retain a small synchronous progress
and selection index, and assemble the full ledger after timing. Measure journal
overhead explicitly and still charge online persistence to each method. Then
freeze within-question balanced repeated blocks over the original48 for the
real baseline comparison; retain all three exposed IDs and all failure/unrun
records. Do not rerun this successful fifteen-execution pilot. Real P1/A3
strategy integration, actual prior costs, effectiveness and scalability remain
separate required research evidence before the September18 deadline.
