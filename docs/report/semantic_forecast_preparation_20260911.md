# A4 forecast preparation and frozen-input recovery — 2026-09-11

The bounded A3 policy now has an offline empirical preparation interface with
exact request/context/current-environment admission. Ordinary question execution
uses the prepared policy and preserves independent tiny gold and read-only
history. This closes an implementation gap for R-C/E2/E3; it does not establish
forecast calibration or workload speedup. The
[contract](../decisions/semantic_forecast_preparation_v1.md) states the inputs,
pseudocode, polynomial work, cost accounting and unchanged conditional bounds.

Review of the provisional implementation found and repaired five experiment
integrity risks: self-declared rather than current environment binding; response
operation/query provenance mismatch; inner failure mislabeled as success; original
response timestamps later than the declared cutoff; and repeated raw observations
under different sample names. These are preserved as targeted tests and in the
[replay inventory](../../experiments/replays/semantic_forecast_admission_20260911.json).

Eighteen unique new cases now have passing evidence, plus one affected legacy
zero-gain decision case. The final new-file/legacy run had 18 passes and one
test-only error-path assertion failure in 0.64s: ordinary agent failure correctly
has no successful output, so its error must be read from `state.message`.
Only that assertion was changed and that case rerun: 1 pass in 0.40s. Earlier
8-case and 2-case development checks remain historical evidence. No broad suite,
native service launch, model call or large-data run occurred.

Refresh traces now measure actual P1 reselection and common final scoring
separately while preserving their previous total. The old A1 native receipt has
two genuine same-request profile observations but no declared prior training
phase and no separable P1 timing. It is therefore **not** silently converted into
training data, and no difference between control-arm times is used to invent a
reselection measurement. Preparation tests use explicitly synthetic observations;
their cost values are not paper measurements.

The original FinBench workpack is still unavailable locally. A standalone server
collector now reads only 21 specified files from the two known frozen runs,
preserves their original bytes, verifies original workload/registry/schedule and
file identities, and caps total input at 64 MiB. It hashes/copies the sealed oracle
without parsing it. Missing or changed input leaves a diagnostic receipt and no
usable archive. It neither searches full datasets nor rebuilds a population.
Seven standalone tiny stdlib tests pass (0.065s), with optional status calls mocked;
this is collector validation, not confirmation that remote files exist.

The collector can optionally record one read-only squeue and one sacct query for
3804011, each with a 10s timeout and no retry. It does not submit/cancel a job.
The last user-confirmed state remains PENDING until new evidence arrives. A
user-owned SSH alias is unavailable locally and prior browser access failed;
the prepared ZIP and instructions make the necessary server action concrete.

Next: obtain the original FinBench workpack and real fact/load receipts, verify
the frozen small integration input and independent answers, and obtain the five
question model LINK artifacts. Prepare real prior forecasts only under a declared
training/preparation protocol, then run the frozen comparisons with every failure
and all original 150/48 instances retained. The deadline remains September 18.
Do not repeat accepted gates or add generic product features while waiting.

[Evidence receipt](../../experiments/artifacts/semantic_forecast_preparation_20260911.json)
records source hashes, test outcomes, external evidence gaps and the deliverable.
