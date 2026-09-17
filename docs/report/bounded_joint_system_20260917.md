# T4 bounded joint system engineering acceptance

The current research entry is now `xgap.api.answer`: bounded NL proposal → finite
candidate construction → paid private-user scope confirmation → shared joint-cost
strong policy → one final execution. This is an engineering release, not a new
paper-evaluation campaign. T3 artifacts/results are unchanged.

## Delivered

- Three historical controller implementations moved to `xgap.legacy`; old imports
  remain thin compatibility shims. README, current architecture/goal/roadmap and
  decision index now identify one current entry. Old documents remain archived.
- Finite scope construction supports Cartesian domains and declared Top-K proposal
  support. Unknown/out-of-scope intent does not receive a certificate. The private
  simulated user confirms scope and answers full/scoped questions through paid,
  recorded actions. A singleton confirmed intent needs no further clarification.
- Both modes share an additive information/final-execution objective, bounded
  physical alternatives and compatible frozen estimator. A labelled structural
  fallback handles missing predictions. Optional preparation/scoring has a
  cooperative deadline; a feasible seed is retained. No trial execution/online fit.
- Large worker and source-observer records can be streamed to gzip with logical and
  stored hashes. Current worker enables compression; historical worker defaults
  stay unchanged. Source accounting retains actual logical traffic bytes. Study
  budget censoring survives later shutdown-related transport errors.

## Focused correctness evidence

The selected suite has **88 distinct tests**: bounded-joint, evidence-store,
intent-strong/certificate, source-observer, family-policy-runner, three affected
legacy import boundaries, and the shared strong solver. This is not a repository-
wide green claim. The injected compact-model transport is a wire/interface test;
its reported token counts are synthetic, not new real model usage.

The new correlated Top-K test supplies three related proposals and verifies paid
scope confirmation followed by a certified early terminal with zero additional
clarification. The joint-cost test independently verifies the opposite decision:
paying for one clarification reduces the worst-outcome estimated objective from
100 to 2.25 while preserving all two outcome continuations. These are correctness
mechanisms, not performance measurements or evaluation data.

A broader legacy replay check exposed two already-stale tests in
`tests/test_one_shot_records.py`:
`test_exact_saved_answer_through_new_entry_and_post_seal_evaluation` and
`test_failed_interpretation_is_terminal_and_retained_for_scoring`.
Their v1 recorded local-admission hash is compared with the current v2 provider
contract and rejected before execution. Those recorded fixtures were not relabelled,
rewritten or admitted by weakening the identity check. Raw/gzip backend replay
compatibility is separately covered by the passing new tests. Reproducing those
historical full-model records requires their pinned historical profile/code.

## Actual Neo4j + Fuseki gate

Gate source commit: `5bd41ab`. Artifact root:
`/Users/anthonyche/xgap-data/bounded-joint-native-20260917-v1`.
Receipt SHA-256: `7b3b6860598748c8b1ecaf016a997fe8f9c44b248089edcff889b5f1a1cd857b`.
The later Top-K-only constructor addition was verified offline; this gate covers
the Cartesian path whose external runtime was unchanged.

|Observed item|Exact|Performance, ε=0.5|
|---|---:|---:|
|Constructed candidates|8|8|
|Scope confirmations|1|1|
|Further clarification calls|1|1|
|Disclosed coordinates|3|1|
|Remaining consistent candidates|1|4|
|Final plan executions|1|1|
|Backend calls|14|14|
|Response logical bytes|17,872|17,872|
|Source capture stored bytes|7,878|7,878|
|Returned rows|4|1|
|Matches exact hand-derived answer|yes|no|
|Certified structured-intent discrepancy upper bound|0|0.5|

Both calls produced complete strong policies. For each chosen interpretation,
11 physical candidates were scored, zero alternatives executed. The frozen
estimator was used in this gate. The declared total estimated costs were 3.035 and
2.535 work units, not measured milliseconds. Both sources and the observer were
closed, process groups drained, and reconstructable serving copies discarded;
frozen stores and evidence were retained.

The provider was the bounded English template, with zero model network calls.
This gate establishes system execution and certificate behavior, not live model
quality. It was one fixed-order run on one tiny query; cache/order effects prevent
latency comparisons. Backend traffic did not decrease. The Performance answer is
not an exact-answer pass: its one row instead of four illustrates that the current
distance bounds structured intent, not answer recall.

## Storage/memory check using an existing real response

Read-only input: one already-sealed T3 backend response, SHA-256
`219c6ac2df69561545b7544b5a2ce55edf277579093fc93a638759df04995fb8`.
No new dataset/model/backend execution. Full check receipt:
`/Users/anthonyche/xgap-data/bounded-joint-storage-20260917-v1/receipt.json`.

|Measurement|Previous JSON writer|Streaming gzip writer|
|---|---:|---:|
|Stored bytes|22,255,137|6,031,808|
|Additional Python allocation peak while writing|44,512,820|746,131|
|Single instrumented serialization time|1,059 ms|3,452 ms|
|Decoded result equals original|yes|yes|

This record used **72.9% less storage** and **98.3% less additional Python recording
memory**. Gzip serialization was slower in this check. Timings include tracemalloc
and one observation per writer; this is not an end-to-end speedup, whole-process
RSS reduction, or proof that every full study now fits its disk budget. The source
observer separately preserves byte-identical logical HTTP bodies. JSON evidence
preserves values/order/multiplicity, while whitespace encoding can differ.

## Explicit remaining boundaries

- This is a bounded complete-query/same-skeleton entry, not arbitrary NL or free
  entity-name grounding. Unresolved entity holes remain unsupported here.
- The initial model/scope step is common; dynamic choice among future LLM and
  metadata-probe actions is not implemented in this current controller.
- Frozen cost predictions/fallbacks need independent ranking/cost validation;
  no global optimum, calibrated quality bound or nonzero speedup is claimed.
- Backend parsing/result objects still materialize rows; gzip only removes the
  second whole serialized string and large retained capture copies. Response,
  execution and study resource bounds remain necessary.
- New worker + source compression are verified; a full batch campaign under a new
  frozen protocol is intentionally deferred to the experimental-plan discussion.

For Chapter 6 use [the implementation map](../implementation_chapter6.md), including
algorithm, polynomial bounds and file-level responsibilities. Next: discuss and
freeze Chapter 7's experimental plan; do not automatically restart T3.
