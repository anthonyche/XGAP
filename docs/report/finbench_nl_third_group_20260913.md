# Third ordinary-NL group: witness deduplication versus aggregate input

2026-09-13, prompt v2, frozen group2 FBNS-3-ba8a93f050468448. The new journal
inherited all eight prior v1 outcomes by reference and skipped their cells.
The first new four-method group made four model calls, **zero final plan/source
queries**, and scored0 for every method. All reference rows are empty; failures
are not correct empty answers. This is shared frontend evidence, not a native
FedUP/FedX result or a planner comparison.

| Method in frozen order | Input/output tokens | Complete online s | Outcome |
|---|---|---:|---|
|Shared NL→FedX|2873 /494|8.241|Invalid compact interpretation|
|Shared NL→FedUP|2873 /494|8.819|Invalid compact interpretation|
|XGAP performance|2869 /492|8.561|Invalid compact interpretation|
|XGAP precision|2873 /494|8.470|Invalid compact interpretation|

All responses correctly set generic node entities to null. They describe company
ownership, medium sign-in and transfers with the risk/time predicates, but request
`deduplicate_by=[company,account]` while SUM reads `transfer.amount`. The unchanged
compact-v1 contract requires selected property values to belong to retained
node/edge variables. It rejects this program before grounding, with:
`Post-distinct output values must belong to the retained node/edge variables`.

The question asks to qualify each account once despite multiple matching media,
while counting parallel incoming transfers separately. That requires preserving
transfer identity when removing witness multiplicity, or applying existential
qualification before combining transfers. The current language exposes the
placement of DISTINCT to the model; merely changing entity guidance did not
resolve this independent issue. Do not silently add keys to a v1 response or drop
requested semantics as a post-failure repair. A declarative, versioned treatment
must first be specified and proved on tiny parallel/witness cases. All existing
programs, prompts, answers and failure scores remain unchanged.

The live [role-contract gate](compact_roles_20260913.md) remains accepted for its
three explicitly tested cases. It does not prove risk-deduplication effectiveness.
The newly inherited profile/store/summary associations were verified by actual
serving sessions without reloading data or rebuilding summaries. The author
baseline implementations and configurations are unchanged. All four sessions
closed and controller5140 exited0. No retry, fit or extra model probe occurred.

[Artifact index](../../experiments/artifacts/finbench_nl_third_group_20260913.json)
and [CSV](../../experiments/artifacts/finbench_nl_third_group_20260913.csv).
Raw root `/Users/anthonyche/xgap-data/finbench-rdf-nl-campaign-20260913-prompt-v2`;
audit SHA `4f109ec66ea5fab0fbe25ee5504e27d4a4f9a382e32bfcef8cf26899f42d572b`.
Next unrun RDF NL group3; first three groups remain12 failed method attempts
under two prompt versions, not a homogeneous full48-question accuracy estimate.

## Separate fixed-semantic continuation

Native groups12–15 each executed one selected plan and returned the correct empty
answer with timestamp-v2 semantics. They are four new questions, not repeats of
the old wrong/censored cases. No model calls; source data, estimator and budgets
unchanged. All used six estimated candidates without actual alternative-plan runs.

| Group | Meaning | Complete online s | Source MB | Method peak GB |
|---:|---|---:|---:|---:|
|12|Risk aggregation|18.152|31.191|0.921|
|13|Temporal path/control|29.916|54.128|1.789|
|14|Temporal path/control|28.863|54.129|1.678|
|15|Direct transfer/control|16.713|25.516|1.047|

Decimal MB/GB; all below the original2GiB method limit. All gold answers here
are empty, so nonempty correctness after the time fix is still unmeasured.
Old group10 EM0/F1.8 and the three old memory interruptions remain. No cross-version
latency pooling or speedup claim. The controller86785 and source session are
terminal. [Fixed-track audit](../../experiments/artifacts/native_timestamp_next_four_20260913.json),
[CSV](../../experiments/artifacts/native_timestamp_next_four_20260913.csv);
`groups12-15-audit.json` SHA6d715fe9… . Native fixed next group16.
