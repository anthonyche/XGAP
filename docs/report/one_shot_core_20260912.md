# First one-shot core integration — 2026-09-12

This is an engineering milestone, not a new performance/effectiveness evaluation.
Parent checkpoint793cc1d; current code provides the first shared ordinary-entry
one-shot slice of the [approved two-mode contract](../decisions/one_shot_modes_v1.md).

## Implemented and checked

`run_question(..., mode="precision"|"performance", estimator=frozen_model)` now
routes through bounded top-K interpretation, frozen catalog/optional ontology
binding, real coordinator/entity-bind strategy DAGs, fitted frozen estimates,
joint proxy-quality/cost selection and a single final execution. Existing callers
without the new profile retain their historical v1 behavior.

Candidate errors are independently retained. Predicted entity bindings remain
non-authoritative and still enforce identity in the executable program. Catalog
candidate truncation is explicit; legacy strict resolution is unchanged. The
new path performs no PROFILE, current-question training, candidate-plan execution,
automatic repair/retry, or mandatory user clarification. Hard request constraints
and requested output admission remain in force. A successful result says which
predicted meaning executed, not that benchmark correctness was verified.

The physical domain is explicitly polynomial: baseline plus single-source changes,
then at most one entity-bind rewrite per plan. Estimated argmin is exact within
available scored candidates, with no universal physical/latency optimum claim.
Frozen ridge model serialization includes statistics/source/version/feature/training
identities and offline collection/fit costs. Unknown costs/tokens are not priced
as zero; wire candidate cap mismatch fails before dispatch.

## Targeted evidence

| New risk gate | Final passing cases | Evidence scope |
|---|---:|---|
| Candidate envelope + provider | 10 |6parser first pass;4provider fixture failures corrected then only those4 rerun; controlled transport, no external LLM. |
| Grounding / strict legacy opt-in | 9 |First pass0.18s; ambiguity, bounded scan, ontology fallback, hard binding and failures. |
| Real physical strategy mechanics | 8 |6first pass;2test expectation corrections then only those2 rerun. Actual in-process SPARQL answers/multiplicity/empty/overflow; Cypher compile/parameters only. |
| Frozen runtime estimator | 10 |First pass0.19s; analytic toy fitting/roundtrip, identity/unknown-feature/split checks. |
| Ordinary one-shot vertical slice | 11 |10first pass0.61s plus1new wire-cap check0.24s. Controlled NL provider and tiny RDFLib query execution. |

These48 checks are **test assertions/cases, not the48 FinBench questions**. No
unchanged broad suite, large dataset, native service or real model was run for
this milestone. Early fixture failures remain in the agent/tool record; they were
not hidden by rerunning all successful checks. Estimator first-run receipt is
`/tmp/xgap-runtime-estimator-first-20260912/receipt.json`; root vertical-slice tool
session13239 exited0. The controlled provider's synthetic usage fields test cost
propagation and must not be reported as actual model usage.

Both mode slices return the independent B01 expected answer. Precision considers
two controlled candidates and selects the higher quality proxy; performance's
wire pool is capped toone. Each invokes the provider once and executes only its
selected plan, with the original expected backend-call count and zero observation
calls. This proves wiring and bounded behavior. It does not measure which mode
answers real NL better, whether its proxy is calibrated, or whether estimates
choose a physically faster plan.

## Still required before core/evaluation freeze

Prepare one mode-matched live provider and frozen model for the actual tiny
Neo4j/Fuseki snapshot, then perform the new ordinary-entry external boundary gate
once. Preserve any failed response for local replay; no automatic retry. Current
same-shaped query selectivity is not modeled, and real estimator training and
calibration remain separate tasks. Improve those only where needed by the research
scope, then freeze the common evaluation interface and discuss external SOTA and
16–20 figures. Do not start another ablation/comparison campaign yet.

The old FinBench paid-selection negative result, LINK3/5, all original populations
and remote3804210 are unchanged. TheSep14 17:00 core andSep18 real-evaluation targets
remain in force; no claim that the entire system or paper experiments are done.
