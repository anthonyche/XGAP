# ARUQULA + FedUP composition boundary

Status: implementation draft during the frozen FinBench primary run. No new
external result, model call or composition admission is claimed by this document.
The author dependency, Redis and lookup admissions are recorded separately in
[the setup report](../report/chapter7_baseline_setup_20260921.md).

## Author path

Author source stays at `9a3982baca03d62f7250572e300b1e4ba47727cc` without tracked
changes. Use its deployed API path in `deploy/app/app.py:t2s`:

1. `PartToWholeParser.initialize` and `run_batch`, concurrency one.
2. Original `post_processing`, with both options enabled, as in that API:
   `regex_use_select_distinct_and_id_not_label=True` and
   `llm_extract_prediction_if_null=True`.
3. Submit its selected SPARQL unchanged to the actual FedUP endpoint, materialize
   the response, then independently score. Preserve every exploratory request,
   original repair/extraction call and final submission.

Do not invoke the author's evaluation CLI: it executes gold queries and drops
empty references before prediction. Those dataset-selection steps conflict with
the frozen XGAP evaluation population. Calling the deployed author API preserves
the method itself without gold leakage or outcome-based filtering.

Its controller prompt asserts that questions have answers. Keep that original
assumption and report the mismatch for empty-reference requests; do not edit the
prompt or discard such requests to improve the baseline.

## Configuration and equal access

Configure the existing corporate dataset alias using `ORG_SPARQL_SERVICE_URL`
and `ORG_LOOKUP_SERVICE_URL`. The alias is an interface selector, not a claim that
FinBench is the author's corporate benchmark. Configure the existing model map
for both the primary engine and auxiliary `gpt-4o` alias to the same authorized
Qwen endpoint. Preserve all author prompt and generation parameters.

The primary wrapper is `scripts/run_chapter7_aruqula_worker.py`. It receives only
the pinned question ID/text and local observer endpoints. No gold query, private
user, answer rows, source assignment or XGAP proposal is passed to it. The
wrapper's filename/configuration is not admission evidence: a real composition
gate is still required.

Public lookup metadata must come mechanically from the complete frozen source
schema, entity names and business IDs. Where XGAP already exposes aliases, the
same frozen public metadata must be accessible to the external method. Add it as
an explicitly versioned overlay for the matched RDF deployment; preserve source
facts and give both methods the same overlay. Do not derive aliases, examples,
mapping hints or rankings from evaluation questions or outcomes. The native
primary batch already running is unaffected and belongs to its original snapshot.

Use the official lookup indexer/configuration, setting data and index paths and
index coverage for the complete metadata. Do not change search scoring or tune it
against evaluation queries. Relationship-label resources in the reified RDF
encoding are values, not RDF predicates; metadata must preserve that distinction.

## Measurement and admission still needed

Use fresh owned Redis state for each admitted method trial, retaining original
within-request caching. The parent owns the local services and process guard.
Model, lookup, federation-ingress and source observers have separate accounting;
each transmission edge is counted once. Response bytes include exploration and
final materialization. Parse tokens from actual provider usage when present;
missing streaming usage remains unknown, not zero. The wrapper does not add
retries; any original-library retries remain observed and charged.

The minimum next admission uses a previously exposed tiny public question and
the same frozen RDF facts for both methods. It must show actual author NL parsing,
original exploration, actual FedUP query execution, sealed final rows, model and
backend records, independent scoring and complete process closure. Then run the
dataset pilot and freeze the matched formal comparison. Until those gates pass,
the capability remains `SETUP_ERROR`, not `UNSUPPORTED` or a zero-score result.
