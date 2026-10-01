# Native identity transport, first nonempty answer and time-contract repair

2026-09-13. XGAP now has a correct **real nonempty** fixed-semantic answer on the
frozen FinBench SF0.1 native deployment. Another nonempty question returned an
incorrect top ten. Its saved records exposed a millisecond lexical-contract defect;
the repair is accepted on tiny data and a live predicate boundary, without
rerunning that full-data question or replacing its original score.

## Representation change, 626bb84

Native Match now returns declared identity maps plus requested scalar columns.
Parallel edge identities, node IDs, scalar/null properties and bind filters remain
intact. Direct legacy callers and RDF query text retain their prior behavior.
Four unique focused checks were accepted; the initial run had two test-fixture
errors (an unmapped property and positional pattern construction), and only those
failed checks were rerun after fixture corrections. The real tiny boundary checked
four new projection cases and one estimated, selected dual-store plan.

The same tiny source facts, five query artifacts and correct `company_id=1,
total_amount=56` answer were matched against the saved prior run. Response bytes
fell from **13,800 to 4,907 (64.44%)**, with five source calls in each. The changed
native query artifacts differ only in outer identity projection and its metadata;
RDF artifacts match exactly. This is deterministic payload evidence. It is not
a latency-speedup experiment: the new primitive checks warmed the services before
its final slice. No catalog/model rebuild or model/alternative-plan call occurred.

## Previously unrun fixed groups 8–11, same frozen order

All four used implementation 626bb84, before the timestamp repair. Each compared
six estimated strategies and executed only one final plan. Zero model calls,
fit, probe, budget increases or retries. All original groups0–7 stay recorded.

| Group | Meaning | Answer outcome | Complete online s | Source MB | Method peak GB |
|---:|---|---|---:|---:|---:|
|8|Direct transfer/control predicates|Correct empty|17.032|25.516|0.943|
|9|Risk-filtered company aggregation|Correct empty|15.496|31.205|0.998|
|10|Risk-filtered company aggregation|10 rows; EM0, row F1 .8|15.407|31.215|1.028|
|11|Increasing-time path/blocked medium|1 row; EM1|28.028|54.132|1.362|

MB/GB are decimal; method budget remains2GiB. All four finished below that cap.
These questions and the old eight are not paired timing observations; do not
derive a speedup by comparing their averages. Group11's exact answer has account
distance2, account `266838277921704456`, medium `17592186053711`, type `MAC`.
Only two questions in this new prefix have nonempty references. Do not extrapolate
overall48-question accuracy or ranking quality from this prefix.

## Why group10 was wrong, and the bounded fix 08eb4f0

The saved native transfer response contains79,909 edges. Fraction widths are
71,892 with3 digits,7,202 with2,718 with1 and97 with none. The former timestamp_ms
filter accepted exactly3 digits, rejecting8,017 valid source values. Ten of these
are eligible transfers in the failed question's time interval. Their timestamps
and amounts were also verified against the immutable offline Neo4j load file.

Those ten contributions explain the entire top-ten discrepancy in a separate
saved-input diagnostic. In particular, company1099511628006 was missing
22,572,432.13. Company7696581397233 was missing9,904,741.11 and fell outside the
returned top ten. This is not a rounding error, an identity projection error or
evidence that the estimator picked the wrong strategy. The diagnostic total is
not a new method answer. **Original EM0/F1 .8 is unchanged.**

[The v2 contract](../decisions/financial_timestamp_v2.md) accepts valid Gregorian
local-calendar timestamps with zero to three fractional digits. Omitted digits
are zeros, so .14=.140 and strict increasing comparisons do not treat them as
different times. Timezones, submillisecond precision, invalid dates and24:00
remain outside the bound. Shared-NL global SPARQL and coordinator predicates have
the same truth conditions. The original baseline code/configuration and frozen
fixed-query inputs are untouched; this is our input/compiler contract.

Four new focused tests passed first attempt in1.32s: bounded value truth and
strict ordering, global predicate parity, ten-row saved failure, and an affected
tiny estimated single-plan slice (five local RDF calls). One private real Fuseki
SELECT then evaluated23 finite boundary cases, all matching;5,733 response bytes,
zero model/data-load/fit/baseline calls. The service was drained and exited143
after our normal SIGTERM. Controller exit0 was observed. No full-data rerun.

## Reproducible evidence and remaining work

[Artifact index](../../experiments/artifacts/native_projection_timestamp_20260913.json)
and [per-question CSV](../../experiments/artifacts/native_projection_timestamp_20260913.csv)
pin the raw receipts, answer scores and timings. Main external roots:

- `…/xgap-data/native-identity-projection-20260913-v1`: receipt47428d25…;
  matched payload comparison029e291a….
- `…/xgap-data/finbench-native-fixed-campaign-20260913-v1/groups8-11-audit.json`:
  SHA cda42a0028ba91169e14e3529d158140ca6507b220bd33d40fd03b0421ddc147.
- `…/xgap-data/financial-timestamp-diagnosis-20260913-v1/receipt.json`:
  SHA a6314cee57b0341568b3980433a1524080d897f9fa1a26d2b0f986c3f8ee5828.
- `…/xgap-data/financial-timestamp-native-20260913-v1/receipt.json`:
  SHA021045280b35e6c78b6e091f0c6369cd9a016bb0752d97d75d2394e830ad3a28.

Native fixed next unrun group12; timestamps are not yet reevaluated on fresh real
fixed questions. Native NL is unstarted. The next completed ordinary RDF NL group
is reported [separately](finbench_nl_second_group_20260913.md). Broad NL quality,
planner advantage, scalability/FedShop and the approved final comparisons remain
open; this is a bounded engineering/evidence milestone, not prototype completion.
