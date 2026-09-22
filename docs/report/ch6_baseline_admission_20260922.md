# Baseline end-to-end admission, 2026-09-22

This milestone admits an executable external baseline pipeline. Completion and
answer correctness are separate outcomes. The tiny fixtures are development
cases, not a formal accuracy/performance comparison.

## Fixed components and compatibility

- Front end: ARUQULA author commit `9a3982baca03d62f7250572e300b1e4ba47727cc`.
- Model: shared Qwen `qwen3.8-27b`, thinking disabled. Original author prompts,
  sampling values, token limits, action search and final-query selection remain.
- Formatter: the existing three string fields use a strict output schema. This
  changes the JSON serialization constraint and is explicitly an adapted profile;
  no action-value repair, gold access, answer repair or extra retry is added.
- Both HTTP and HTTPS absolute IRIs are handled by two exact tool-source patches.
- FedX profile additionally reorders one entity-label tool expression, verified
  equivalent on the same Jena fixture. Final generated queries are not rewritten.
- FedX 5.1.2 external class bytes remain pinned. Its default OPTIONAL configuration
  is retained. The failed configuration-switch diagnostic is preserved.

The Qwen deployment differs from the author's paper model; this is a disclosed
external-method composition with a shared model, not a reproduction of published
scores. ARUQULA retains its original exploratory database/model calls; only XGAP
has the separate one-final-plan design contract.

## Results

Results will be sealed here after the composition admission finishes. The native
single-source component already produced four rows; it selected internal IDs and
scored EM=0, row F1=0 against the business-ID reference. No correction was applied.

## Tool-level checks and limits

Eight worker boundary tests passed before the final tool bridge; its additional
source-preservation test passed separately. The real client wire preserved the
original prompt and sampling parameters and carried the intended action schema.
Four original/adapted query pairs had identical Jena results. Twelve FedX requests
(GET/form/raw) executed; nine matched the reference. The entity probe returned
27 rows versus 15, including duplicate labels. This engine behavior is preserved,
not reported as a successful correctness check. All checks used the tiny fixture.

Both admission questions and budgets were fixed before the corresponding model
calls: 300 seconds per worker, at most 64 model and 256 source HTTP attempts, with
owned resource limits. Previous failed configurations remain separate evidence.
Original model responses and answers are stored privately, with receipt hashes in
[the artifact index](../../experiments/artifacts/ch6_planner_external_followup_20260922.json).
The [decision record](../decisions/ch6_planner_external_followup_20260922.md)
retains the compatibility steps and failed diagnostic configurations.

No full benchmark matrix or SOTA superiority claim follows from these admissions.
Single-source and cross-source strata must remain separate in the actual study.
