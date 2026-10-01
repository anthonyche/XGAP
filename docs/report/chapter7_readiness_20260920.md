# Chapter 7 T6 — protocol adopted, first readiness evidence

2026-09-20. The [user's original plan](../research_experiment_plan_20260920.md)
is adopted, with the [execution contract](../decisions/chapter7_execution_v1.md)
and [machine-readable E1–E20 matrix](../../experiments/protocols/chapter7_v1.json).
No formal release or paper superiority claim is made. The overall goal is active
in repository documents; the app's older paused goal metadata is stale and cannot
be resumed/rewritten with the currently exposed goal tool.

## Implemented for the approved experiment design

- A controlled-state entry shares the current compiler, planner and runtime with
  NL execution. Authoritative initial clues restrict the original family, without
  changing loss coordinates, weights or denominator. Subsequent user calls are paid.
- A frozen execution-feedback switch changes only execution estimates entering
  policy search. Physical-plan estimation/ranking remains enabled in both variants.
- The selected complete strong policy includes every selected action's outcomes,
  queries, certificates and deduplicated physical plans. Observed state IDs are
  separate. Unobserved branches do not receive made-up latency or byte counts.
- Query loss is independently scored after sealing, separately from answer EM/F1.
  Batch cells pin controlled state/configuration and resume without retrying attempts.
- Scope authority now accepts bounded representation equality: declaration-order
  variable renaming and WHERE conjunction order. Literals and query meaning remain
  unchanged. This fixes a real live-model rejection without reading gold into the
  frontend, adding repair calls or relaxing epsilon.
- A renderer exports sealed complete policies to DOT, PDF and PNG. A real tiny
  native preview was rendered and visually checked; it is not the final E16 case.

42 focused tests passed for the initial T6 contracts. Eleven new representation
boundary tests also passed (29-test related set, then two loss tests after helper
extraction). These are 53 distinct targeted tests, not a broad regression campaign.

## Actual runs and what they establish

All readiness queries below use an authored **eight-node toy graph**, not FinBench
SF0.1, official GrailQA or FedShop evaluation. Single observations are not speedup
estimates. Prior runs and failed attempts remain immutable.

### Controlled Neo4j + Fuseki: four cells completed

One shared initial clue fixes path depth. Four intents remain from a full family
of eight; the loss denominator stays four. Both modes and both feedback settings
use the same initial state. Each cell executes one final plan, with zero model calls.

|Mode|Execution feedback|Clarifications|Answer EM|Answer F1|Actual query loss|Certificate violated|
|---|---|---:|---:|---:|---:|---|
|Exact|on|1|1|1|0|no|
|Performance, epsilon=0.5|on|0|0|0.4|0.5|no|
|Exact|off|1|1|1|0|no|
|Performance, epsilon=0.5|off|0|0|0.4|0.5|no|

The Exact policy has ten exported nodes, including four possible terminal branches;
Performance's policy has two nodes and terminates at the root. All owned database
processes closed. This establishes the controlled input, feedback, complete-policy,
independent-loss and native execution interfaces. It does **not** demonstrate a
feedback advantage: on/off behavior is identical in this case.

### Live Qwen: two calls exposed a representation bug

The authorized `qwen3.8-27b` endpoint generated two valid proposals. Both trials
stopped at `intent_outside_proposed_scope`, before execution. Variables
`src/dst/med/p` versus `start/other/medium/reach`, and reversed WHERE order, caused
raw JSON membership to reject semantically identical queries.

Those are two real failed attempts, not two successful end-to-end results. Their
requests, responses, usage, elapsed time and failure statuses remain unchanged.

### Saved-output replay after the fix: both modes completed

The same two saved model outputs were replayed through current authority, planning,
compilation and **local RDFLib execution**, with zero additional model calls.
Exact returned the four expected rows with query loss zero. Performance returned
one row with query loss 0.5; its certificate held. Each executed one plan.

With the full initial uncertainty in this replay, **both modes clarified once**.
The zero-clarification result above is conditional on its declared initial clue;
it is not evidence that every NL request saves clarification calls.

The first diagnostic replay mispassed Performance's epsilon to Exact; its failed
receipt is preserved. The corrected replay pins a new commit and directory. It is
debug verification, not an automatic retry or a replacement for the live failures.

## Evidence locations and pins

All roots below are under `/Users/anthonyche/xgap-data/`; no data, private intents,
credentials or large artifacts are added to Git.

|Artifact|Receipt SHA-256|
|---|---|
|`ch7-controlled-native-20260920-v1/receipt.json`|`0c70467e7612606d00e2bd3ebbf5875a2631addc336acd0682e78f61cc27d43d`|
|`ch7-nl-native-20260920-v1/receipt.json` (failed, preserved)|`1360b7859b4f087985673ef7980506c0fd168d8b95b56b478f00d84407b2729a`|
|`ch7-proposal-replay-20260920-v1/receipt.json` (diagnostic failure)|`4f0e5aa67f36d463aca25158df3ed03e5eda301bab25a91d554ab6d87171fee4`|
|`ch7-proposal-replay-20260920-v2/receipt.json` (passed)|`e628f55ff898f6c70fff0f65559ffa9864f6030ccdde4a5d5a01850e4d759b42`|
|`ch7-freebase-intake-20260920-v1/receipt.json`|`77723c30564577bdc2d00f079ed881962bb5cef0530283e9dd561855011121b9`|
|`ch7-policy-preview-20260920-v1/manifest.json`|`8d6c321e5df52a70449afe4b364e6cba6806eb703b16798270972ca3fb09c3f1`|

Initial gates pin code `dda52a8`; successful saved-output replay pins `8c902ce`.
The renderer's DOT/PDF/PNG are independently hashed in its manifest.

## Intake and remaining gates

The [capability intake table](../../experiments/protocols/chapter7_capabilities_20260920.csv)
has 18 method/dataset/deployment rows. It distinguishes implemented code from
dataset admission and completed measurements. No missing setup is scored as zero
or promoted to algorithmic UNSUPPORTED.

|Track|Verified|Still required before its pilot|
|---|---|---|
|FinBench-derived|Existing SF0.1 native/RDF store receipts; current toy native logging gate|New uniformly sampled, family-disjoint release; independent references; current dataset/model admission|
|GrailQA/Freebase-derived|All 13 parts of a preselected first shard match hashes: 420,940,219 bytes|Native/RDF identity and literal/multivalue mapping, bounded workload and references; this partial shard is not full Freebase|
|FedShop-derived|Pinned author/generator source intake exists|Bounded generation, frozen output, native/RDF mappings, references and workload|
|ARUQULA + FedUP|Unmodified ARUQULA branch `aruqula`, commit `9a3982baca03d62f7250572e300b1e4ba47727cc`; FedUP source/build artifacts|Dependency environment, Redis, KG lookup/index, actual SPARQL execution composition and full model/exploration accounting|
|Source-count E19/E20|Matrix and metrics declared|Real 2/4/8 horizontal partitions with identical fact union, fixed total resources and multi-source coverage; replicas cannot stand in for shards|

ARUQULA's conda solve failed for `redis-server` on the current macOS environment;
Docker's local daemon was unavailable. This is **SETUP_ERROR**, not an unfavorable
method score and not proof of unsupported semantics. No baseline prompt, search,
repair policy or algorithm was modified. Its lookup and auxiliary-model behavior
must be retained and metered. Sources: [author ARUQULA](https://github.com/AKSW/ARUQULA/tree/aruqula),
[author FedUP](https://github.com/GDD-Nantes/fedup).

Disk observation at intake was approximately 17 GiB free. Preserve a 6 GiB reserve;
do not load three new graph deployments simultaneously. Offline build/load/index
cost stays separate from per-request cost.

The next stage is dataset/pilot admission, not final plots: publish 24 development
cases per admitted dataset with family isolation, then use the pilot to freeze
formal sample size, repeated measurements, paired order/cache protocol and total
budget. Historical answer-nonempty stratification and T3 attempts are not reused
as the new population. Formal sampling and all 20 paper figures remain pending.

## Reproduce the focused code checks

```bash
PYTHONPATH=src:tests:scripts python -m pytest -q --disable-warnings \
  tests/test_chapter7_controls.py tests/test_bounded_joint.py \
  tests/test_bounded_joint_batch.py tests/test_intent_strong.py \
  tests/test_compact_identity.py
```

Readiness runners: `scripts/check_chapter7_native.py`,
`scripts/replay_chapter7_proposals.py`, `scripts/render_chapter7_policy.py`.
Every run requires a new output directory. Rendering consumes sealed evidence and
never queries a model or backend. Fresh formal evaluation still requires its own
frozen release and resource budget; this report is not such a release.
