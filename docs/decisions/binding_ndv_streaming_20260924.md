# Distinct binding keys and streaming SPJ tails

2026-09-24. General shared-runtime optimization following the verified original
W3 repair (3868378). No dataset/template dispatch, answer-dependent selection,
new semantic operator, online trial-plan executions or change to query budgets.
Full D2 and all frozen questions/references remain intact.

## Diagnosis and changes

The binder sends distinct keys, but the old relative-work estimator charged
incoming rows. A join can have 100 rows with only ten distinct binding keys.
Conflating these quantities overprices binding and can falsely penalize its
capacity risk. `xgap-relative-source-work-v3` propagates column NDV estimates
through typed normalization, field projection, equality filters and joins, using
existing frozen endpoint degrees and source populations. Unknown lineage falls
back to incoming rows. Correlated tuple bindings also retain this fallback.
Estimates are not safety bounds; actual key/byte overflow still fails, never
truncates. No weights, source statistics, latency observations or held-out answers
are fitted. v1/v2 loading, serialization and predictions remain available unchanged.
`scripts/prepare_ch6_binding_work.py` freezes a separate model/profile/seal and
reuses the existing stores; it cannot overwrite the parent or revise twice.

A necessary dimension bind can now derive its keys from an earlier already
restricted Match along proven identity lineage. Those keys may be a superset of
the eventual joined domain. This is safe because the original joins and filters
remain; an extra dimension row cannot create a result without its original
witness. UNION branches cannot provide the entire domain and are excluded;
unrestricted leaf reads and dependency cycles are not adopted. This avoids
materializing a large join solely to find the binding keys needed by that join.

`runtime/streaming_topk.py` evaluates eligible existing coordinator operators as
one pipeline in root-only execution. It absorbs exclusive left-deep inner joins,
filters and field-only projections into a root sort/limit (1 <= K <= 1000,
at most 64 nodes). Shared consumers and intermediate roots are barriers. Before
streaming, it verifies complete column schemas, unambiguous join columns,
representation-compatible predicates and fully ordered string/null answer
columns. Aggregates, partial ordering, calendar conversion, RDF terms, numeric
answer representations and unsupported shapes keep their existing evaluator.

Under this restricted set semantics, delaying intermediate duplicate elimination
cannot change predicates or final answer representatives. The bounded heap keeps
the K best distinct answers under the original ASC/DESC/null comparator. Once a
key is evicted its rank cannot improve the monotonically improving threshold,
so an unbounded set of previously seen answers is unnecessary. All original
predicates still run before terminal selection. No intermediate arbitrary LIMIT
is introduced. Required memory is input payloads plus right-side hash indexes
plus O(K) answers, not all joined tuples. **The number of scanned pairs and CPU
time remain unbounded by K.** Query execution is not promised polynomial in
output size; fixed-D online planning retains its previous polynomial bounds.

The execution receipt explicitly marks streamed intermediate counts as emitted
occurrences, not materialized distinct cardinalities. Whole-pipeline time is
charged at its root; per-node times are unavailable. These counts never train
the current query's estimator. Backend calls/traffic remain separately observed.
The admission worker now preserves compact retention/pipeline evidence without
saving intermediate row payloads.

## Verification and limits

- 74 focused tests pass across changed runtime, key estimates, binding rules,
  retained payloads and native SPJ/membership. The capture-corruption test was
  updated for the existing evidence loader's more specific hash-error wording;
  rejection and replay non-consumption remain required. Six additional focused
  admission/selection tests pass, including one-execution and retention receipts.
- A concrete 80-by-80 star produces 6,400 join occurrences. Registered row
  payload peaks fall from at least 6,400 to at most 180 while the same 20 ordered
  answers are returned. This metric excludes hash indexes, transient buffers and
  process RSS; it is a development memory check, not a paper performance result.
- Ten real private Neo4j 5.26.30/Fuseki 5.6.0 tiny cases pass ordered-answer
  differential checks: the eight membership cases plus ascending/descending
  stars. The two tiny stars each stream 49 pairs into three answers. Their
  overall registered-payload peaks both remain 136 because an earlier dimension
  dominates; no overall memory or latency advantage is claimed for these cases.
  All owned services are stopped and reaped.
- Source-only v3 static selection over original unattempted indices 7–12 has
  zero backend/model calls, zero query executions and zero reference-row reads.
  Star W2 now binds both dimensions from early keys and exposes the large join
  tail to streaming. Cycle W1 selects one native query; W3/W4 retain external
  membership with five remote nodes; witnessed sum retains contribution-aware
  leaf-witness semantics. No full edge read is selected in these six plans.

Local evidence root:
`/Users/anthonyche/xgap-data/ch6-release-boundary-20260924/`.

| Artifact | SHA-256 |
| --- | --- |
| `streaming-star-tiny-v1/receipt.json` | `9343d8fbd058e3409f021ab56e8f10e4ed01a13d5a198658bdf4d79ce22baf55` |
| `remaining-streaming-zero-call-v1/receipt.json` | `f7b6e3d3889391ad2c96055666579a9fb9eff2d7213058134ae7a0c34ba45751` |
| `remaining-streaming-zero-call-v1/relative-work-v3.json` | `e89110803937f261ca5ca3268806685c1aa232f69027395f5034bd6c8c4374bf` |

The zero-call receipt describes the working implementation before commit; the
handoff seals exact code and plan pins. Static eligibility is not full-source
resource admission. Next: original six still-unattempted cases, original order,
one fresh CPU source session, one execution per case, stop on first failure,
no repeats of W1/W2/W3 successes. Server byte/time/RSS caps are unchanged.
After that, remaining complete native/RDF admission and formal input/support/
budget checks still gate the first-dataset campaign. Historical F6 raw costs
remain valid evidence for their original pool/model; new v3 estimates must be
rebound/audited against that pool before being reported, not relabeled as v2.
Full formal dispatch remains closed.

## Frozen six-case handoff

Implementation `5f9402384308ecf2a98a0a3baf40d92271439487` is pushed to
`codex/m13e4-grailqa-semantic-paper-protocol`. Package:
`/Users/anthonyche/Downloads/xgapremaining6-5f94023.zip`, 56,497 B, SHA-256
`e959153455b3ae1ea1cfed3e5bb1b44018a5256572be868512ae6ec0f75634a2`.
It contains an incremental Git bundle from the untouched `9fbcb8d` checkout,
Python 3.6-compatible staging, CPU submission, exact pins and the admission driver.

Local package verification checks the actual sealed 3868378 success/closure,
3868312 attempted set, original bundle/prepared profile and six case pins.
Mutated query, order and snapshot are rejected. ZIP members, Git prerequisites
and shell syntax pass. The actual planning inspector, supplied the pinned
materialized archived profile in place of unavailable host file paths, selects
all six exact presealed plan hashes with zero calls/executions/reference reads.
This isolates local file availability; server-side full profile validation remains
mandatory before source startup.

The driver freezes v3 separately, proves estimator-only rebinding leaves every
case and execution input intact, then checks selected plan hashes before starting
sources. Actual worker plans must match the same hashes. The first failure stops
the sequence and retains its evidence. A journal/output/checkout already present
rejects resubmission; no automatic retry. Original cases 7–12 keep their indices.

Server intended journal: `/home/hxc859/xgap-ch6-artifacts/native-remaining6-5f94023`;
output: `formal-native-remaining6-stream-v1/D2` beneath the same artifact root.
The user subsequently supplied verified staging/checkout and **SUBMISSION
3868824**. The exact checkout is `5f94023`; no version is changed in flight.
A fresh SSH/browser read again timed out. Current Slurm state, attempted count
and admission result remain unknown; submission is not evidence of success.
Log: `native-remaining6-5f94023/native-remaining6-3868824.out` under the artifact root.
Validation report: local `native-remaining6-pack-5f94023/verification.json` under
the evidence root above. Model/policy setup and source serving remain offline
costs; this diagnostic is not a six-question NL result or a formal method campaign.


## 3868824 terminal report (archive audit pending)

The user supplied `FAILED/2:0`, 146 s, compt311 and attempted=audited=4.
The first failing case is original index 10, `D2-test-uniform-cycle-000-W4`.
By the frozen order/first-failure contract, ordered-star/W2 and cycle/W1/W3
passed; witnessed-sum/W4 and active-anchor window-edge/W2 were not attempted.
These are reported admission outcomes, pending individual raw-evidence checks.
No failure category, latency improvement, memory improvement or estimator
misranking is inferred from this summary.

Archive: `/home/hxc859/xgap-native-remaining6-3868824.tar.gz`, 179,113 B, SHA-256
`012935574200aa8605709d2842e8bc5a71184c579bdddc1baa4606d864e8230d`.
Direct SSH again timed out. The user has been asked to download the archive;
a bounded read-only audit is prepared locally. No new query/job is submitted.
Preserve all three newly successful cases and inspect the failed worker, final
plan, source responses and resource counters before changing implementation.
