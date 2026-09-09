# GrailQA two-job development repair handoff

## Release scope

This is a runnable repair package, not a new experimental result. The user
authorized verification and pushing the existing
`codex/m13e4-grailqa-semantic-paper-protocol` branch. Server jobs remain
user-submitted. Preserve the old 18-query negative run, both old catalogs and
the admitted FinBench physical campaign. No full150 run is introduced here.

Two independent development measurements can run in parallel from the same
unchanging checkout:

| Job | Intervention | Held fixed | Outputs that decide the next action |
| --- | --- | --- | --- |
| GPU development18 | Explicit revised output contract and exact per-request token checks | Old preflight18 catalog, questions, Qwen, retrieval bounds, strict grounding | Legal candidates, semantic matches, all18 and reachable-subset results, exact failure causes, actual calls/tokens/latency |
| CPU catalog comparison | Canonical eligibility before entity Top-K | Frozen Freebase source, question text/order, ontology, anchor rules and Top-K | Catalog/retrieval/prompt component coverage, gains **and losses**, entity-ID changes and construction resources |

These are isolated development interventions. Historical comparisons are not
paired confirmatory performance estimates. The GPU job does **not** consume
the new catalog; changing output contract and catalog together would prevent
attributing the result. The current historical readiness admission is v1-only,
so the v2 comparison deliberately does not fabricate its old admission files.

## CPU implementation

`scripts/slurm/run_grailqa_catalog_comparison.sbatch` requests 8 CPUs, 48 GiB
and four hours, and calls the explicit server helper. It validates small frozen
inputs and the existing catalog first, then performs the real full-source v2
build only for development18. Eighteen questions do not mean a partial-source
scan: the frozen 964-shard source is still verified and scanned. These resource
requests are bounds, not a measured completion-time or whole-process-memory
guarantee. There is no GPU, model, backend, download, submission or retry inside
this job.

The new `grailqa_catalog_comparison` module uses both actual catalog loaders and
retrievers. Input identity includes the complete same query population/order,
question file/text, source provenance, ontology/schema files and anchor rules.
The comparison validates published catalogs; it does not independently repeat
the full source scan. It persists both retrievals and an inference-only seal
before first opening or hashing reference interpretation content. References
are used only to evaluate coverage, never to build or retrieve candidates.

The report includes all questions, all three stages and entity/relation/type/
effective-type/joint coverage. Every cell retains its denominator, both counts,
gained IDs, lost IDs and unchanged IDs. Per-query catalog/retrieval/prompt MID
changes support concrete diagnosis. Resource fields are the catalogs' original
construction observations, not a fresh matched speedup benchmark.

Outputs are fresh, job-owned and non-overwriting:

```text
runs/cwru-grailqa-catalog-comparison-JOB/
  run_inputs.json
  catalog/preflight18-eligible-v2/
  comparison/
    comparison_request.json
    inference_questions.jsonl
    retrieval.jsonl
    retrieval_seal.json
    comparison.json
    run_status.json
```

Partial outputs remain after failure; do not delete them to retry invisibly.
Publication failure also attempts `comparison_failure.json`. Require scheduler
and CLI success, comparison `run_status.json` success and no failure marker,
not merely existence of a report. No `audit_summary.json`, old audit receipt,
model authorization or paper admission is issued. A coverage gain alone is
not generated-query or answer correctness.

Selected evaluation references must also parse and type-check under the
existing controlled query contract after the seal. Unknown operators cannot
silently become empty relation requirements. Historical evaluation code and
reference content are not changed.

The recorded real v1 preflight18 catalog already had 900 query-candidate
assignments (18 × 50). If this is the preserved baseline, the quota was not
reduced by post-selection eligibility filtering. Thus the synthetic backfill
repair is **not** established as the cause of its eight local-catalog misses;
the real comparison may show no improvement. That negative result must remain
visible, and must not postpone diagnosing schema/retrieval/prompt exclusions.

## Server prerequisites and explicit inputs

Use the exact release commit supplied in the handoff, keep the checkout clean,
and do not switch it while either job is pending or running. No source archive,
model or previous run needs uploading again if the following frozen server
artifacts are still intact:

- `~/xgap-data/freebase/raw/hf-archival-parquet` and
  `~/xgap-data/freebase/raw/source_manifest.json`;
- `~/xgap-data/freebase/grailqa-local-catalog-v1/preflight18`, including its
  existing `audit_summary.json` and `reachability.jsonl`;
- repository `datasets/grailqa_pilot_v1` and
  `datasets/grailqa_inference_catalog_v1/reverse_properties.json`;
- `~/venvs/xgap-core/bin/python`, `/home/hxc859/venvs/xgap-vllm`, and the frozen
  Qwen cache `/home/hxc859/.cache/huggingface`.

The CPU helper requires `XGAP_REPO_ROOT`, `XGAP_PYTHON` and
`XGAP_GRAILQA_REPAIR_RUNNER_COMMIT`. Frozen source/baseline paths have the
defaults above. Staging uses `XGAP_LOCAL_CATALOG_STAGING_ROOT`, otherwise
`TMPDIR`, otherwise `/tmp`, outside protected source/catalog trees.

The GPU helper additionally requires `VLLM_ENV`,
`XGAP_GRAILQA_GUARDED_RUNNER_COMMIT`, `XGAP_GRAILQA_GUARDED_SPEC` pointing to
`experiments/specs/grailqa_semantic_preflight_output_contract_v1_cwru_qwen3_32b.json`,
and `XGAP_GRAILQA_GUARDED_SPEC_SHA256` equal to its canonical freeze hash
`a4dee64d522108b8ae27f91fa2425dbfa125ba40e43dfc1a717844d08efae50a`.
Its entry is `scripts/slurm/run_grailqa_guarded_preflight.sbatch` (one H100,
64 GiB, four hours). It checks actual token IDs/context before each generation
and actual bounded schema repair: at most 36 inference attempts and 36
tokenization probes for18, with startup health polling accounted separately.
No automatic retry, graph execution or full150 execution is allowed. Old
environment overrides must not redirect this job to a different catalog.

GPU results live in
`runs/cwru-grailqa-guarded-JOB/results/grailqa-guarded-preflight/`. Read the final
status, `metrics.json`, `guard_diagnostics.jsonl`, tokenization checks and failure
records together. A completed job can still report zero candidates; that is a
negative development result, not repaired effectiveness.

## Next decision from the two results

- If output normalization/grounding still rejects all candidates, inspect the
  precise remaining contract, component-reference or grounding failures first.
- If v2 does not increase real coverage, retain that negative comparison;
  missing schema labels, retrieval rank and prompt exclusion remain distinct
  possible interventions. Do not claim every local-catalog miss was this bug.
- A successful v2 coverage comparison is a prerequisite, not authorization,
  for separately integrating its readiness profile and measuring generation.
- Before the full comparison, freeze baselines, unused evaluation populations,
  budgets and metrics. The development18 overlap is disclosed, not called an
  unseen test. Both datasets still need every retained original EQ1–EQ5 cell;
  FinBench semantic comparisons and GrailQA federated answer/physical
  comparisons remain incomplete.

The target is initial usable results this week, with writing proceeding from
the admitted FinBench evidence now. Actual Qwen success, full-source build
duration, GPU queue delay and complete cross-dataset readiness are not inferred
from local tests. This package removes manual reconstruction of the next two
jobs; it does not supply missing measurements.

## Verification

The final full repository regression passes **2,115 tests**, with **36 skipped**,
in **590.20 seconds**. The new modules pass **110 focused tests** (56 comparison,
54 handoff). Three offline examples (`llm_boundary_demo.py`,
`m15_goal_loop_demo.py`, `m15_llm_resolution_provider_demo.py`), both CLI help
checks, shell syntax and staged whitespace checks also pass. Skipped behavior
remains unverified. No production or test code changed after final collection.

Comparison tests exercise actual tiny catalog builds, SQL retrieval, full
denominators, reference access ordering, invalid-reference rejection and
input/output preservation. Shell tests execute the real helper with offline
process doubles. Neither substitutes for the complete Freebase scan or Qwen
inference. Original supplied-ledger replay remains 18 queries / 47 raw
candidates / 17 grounding rejections / one provider failure, without changing
those ledgers or making external calls.
