# E1-B scoring and INT-5 existing fact recovery

Parent72aeea7, 2026-09-11. R-E/E1 now has an independent entity-answer evaluator
after the existing inference/ordinary-P1 execution chain. This is a local scoring
gate and existing-data recovery, not a new model or native experiment result.

`evaluate_entity_answer_records` preserves the supplied population order and
denominator. It scores exact entity IRI sets using existing RDF term/projection
contracts, ignores labels, deduplicates entities and computes macro EM/F1.
Failed queries score zero even against empty gold; successful empty/empty scores
one. Missing runs retain unknown scores/costs. Scalar references remain visible
and prevent a full-cohort score. Only recognized terminal E1-A records enter a
method cell; schema/policy/epsilon/question mismatches and contradictory answer
claims fail. All failed-attempt costs and unknown usage remain explicit.

The evaluator cannot select a meaning or access a backend. Callers must seal
inference/execution before opening references; this pure API does not certify
that external temporal order. `paper_result` and its temporal-isolation claim
remain false. This is entity identity scoring, not general scalar equivalence,
official whole-benchmark evaluation, or a completeness claim for a data source.

Only18 new focused checks ran, first run **18passed/0failed/0skipped in0.45s**;
process0.984s, tool ee7bca exit0. They cover mixed quality/failure denominators,
valid empty versus failure, unfinished/unsupported rows, duplicate and nearby
IRIs, unknown costs, method/population/terminal/identity mismatches, and one new
controlled E1-A provider→P1→compiled SPARQL/RDFLib→independent score slice.
The latter constructs its handwritten reference after retaining the run and
verifies scoring does not change it or add a call. No actual model/native service,
old successful gate, full regression or large-data query ran. Source/test/contract
hashes were unchanged across the run; no failed-test retry was needed.

A separate actual-input compatibility check verified original pilot_ids.json and
recovered gold_answers.jsonl against the frozen manifest, then supplied no runs
to the new evaluator. All150 IDs/references are retained, all150 reference answer
lists fit entity identity scoring, all150 rows are not_run, and whole-cohort
EM/F1 and total costs remain unavailable. This says nothing about whether their
queries execute or their predictions are correct. It is not150 successful tests
or a benchmark outcome. No inference inputs or frozen gold files changed.

## Existing real facts recovered to a durable path

The previous statement that local real facts were entirely unavailable was too
broad. D201's first complete archival shard and its D202 load receipts still
existed. The initial shard was selected from the frozen inventory before data
inspection, without question/reference inputs. Current exporter source hashes
match its historical plan; no gold-driven filtering or truncated-success path
was introduced. It remains just1 of964 shards, not complete Freebase/GrailQA.

One local copy preserved24 files/436,303,952bytes in
`/Users/anthonyche/xgap-data/int5-freebase-first-shard-20260911/original/`.
All13 RDF parts (420,940,219bytes,3,247,670 historical occurrences) were fully
hashed against the frozen facts manifest. The14,984,726byte Parquet matches its
original SHA; both manifests and all copied small historical files match. The
failed verifier and its correction remain byte-identical. No facts were rebuilt,
filtered, re-exported or downloaded; old paths/files and evidence were not edited.
Migration took0.959s, tool5f0823 exit0. Its separate receipt maps old paths to the
new root without rewriting the historical absolute paths inside manifests.

Facts manifest SHA: efbd5e914e12f5263ffaf38e42dfecfcb16066c378989692f66b5538851e0b9f.
Existing FactSnapshot.load accepts the new facts root with that original pin;
this observation is from its code path, not a repeated load/verifier invocation.
Historical D202 receipts report successful loading; old database state directories
also exist, but were not copied, restarted or checked for present usability.

Raw scoring evidence: `/Users/anthonyche/xgap-data/e1b-entity-answer-evaluation-20260911/`.
Migration receipt: `/Users/anthonyche/xgap-data/int5-freebase-first-shard-20260911/migration_receipt.json`.
Machine evidence: `experiments/artifacts/entity_answer_evaluation_20260911.json`.

Next: use this declared partial source only for explicitly scoped real integration;
establish adequate source coverage for formal GrailQA, real model predictions,
genuine prior cost/forecast data and fair E1–E5 comparisons. Original150/48,
FinBench integration exposure, model0/5 and FinBench6/6 are unchanged. Job3804210
remains user-observed PENDING(Resources); the user will report changes.
