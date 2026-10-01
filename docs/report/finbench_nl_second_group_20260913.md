# Second ordinary-NL evaluation group: entity-role confusion

2026-09-13. Frozen group1, question FBNS-1-cdc6f66be3016baf, was attempted once
by XGAP performance, shared-NL→FedX, XGAP precision and shared-NL→FedUP in that
predeclared order. **All four stopped before physical planning/native execution**.
Their final-answer scores are0 despite the empty reference: no answer is not a
correct empty answer. No current-question retry or answer repair occurred.

| Method | Model calls | Input/output tokens | Complete online s | Source calls | Outcome |
|---|---:|---|---:|---:|---|
|XGAP performance|1|2585 /560|9.086|0|No executable interpretation|
|Shared NL→FedX|1|2589 /560|8.659|0|No grounded interpretation|
|XGAP precision|1|2589 /560|8.943|0|No executable interpretation|
|Shared NL→FedUP|1|2589 /560|9.228|0|No grounded interpretation|

Each model response has one schema-admitted compact candidate, including the
business-ID equality and the requested transfer/ownership structure. However,
all four assign generic role descriptions to required named-entity fields:
`person`, `person's accounts`, `blocked company-owned accounts`, `owning company`.
The first exact catalog lookup for `person` visits59,587 frozen entries and finds
zero entity matches. Grounding stops there; physical alternatives and final
queries are never attempted. Model contents are not all byte-identical:
performance uses company variable `c`, the other three use `co`.

This is a **shared interpretation/grounding failure**, not a catalog build failure,
source-resource shortage or native FedUP/FedX limitation. Catalog reads cost
about75–78ms for this failed lookup. Rebuilding it or adding a fictional entity
called `person` would not address the logical problem. A business ID may remain
an explicit stored-property predicate; ordinary variables need no named-entity
lookup. Unresolved required identity constraints cannot simply be dropped.

The exact profile, prompt, model, population, estimator, summary, source stores
and author baseline implementations remained pinned. An explicit implementation
epoch records08eb4f0's calendar-time fix and intervening native serving changes;
this group never reached those time predicates. Previous group0's four invalid
path-deduplication failures stay recorded. Two groups/eight failed method attempts
do not estimate full48-question effectiveness or establish a performance gap.

All four outcomes were sealed; controller exit0 and four owned-session closures
were verified. No source query/model probe, fit, data load, prompt/catalog change,
native baseline invocation or old intent redispatch. [Pinned audit](../../experiments/artifacts/finbench_nl_second_group_20260913.json)
and [CSV](../../experiments/artifacts/finbench_nl_second_group_20260913.csv).
Raw root: `/Users/anthonyche/xgap-data/finbench-rdf-nl-campaign-20260913-v1`.
`second-group-audit.json` SHA
`a953f25874aea1ddc1fadfe96ecbe5e4ee7f5f845468699a4b7c054ae965cc3f`;
run0001 receipt SHA63577700… .

Next engineering work should distinguish genuine named mentions, literal business
IDs and generic node variables using tiny independent examples and saved failure
replay. Any later common-front-end revision needs a new frozen version and exposure
disclosure for all shared-NL methods. Do not repair this query, tune baseline
algorithms or rerun it until successful. RDF NL next unrun group2; complete native
NL and the remaining evaluation are still outstanding.
