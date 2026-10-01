# F1–F8 effectiveness revision — 2026-09-27

Status: discussion draft responding to the user's replacement design. This file
does not revise frozen manifests, running job 3890655 (source f40dfa9), old result
tables, or authorize a new factor sweep. Dataset/support denominators and the F7
cost choice below must be agreed before publishing a replacement figure contract.

## Design principle

Retain eight figures and five metric families. Each figure has one X, one Y and
a distinct research question; metrics may recur against different factors.
Conceptual distinction does not imply statistical or algebraic independence.
All five methods remain visible, except TS is excluded from F6 as requested.
Expected rankings are hypotheses, not acceptance requirements for observations.

## Proposed figure contract

| ID | Y | X | Question |
|---|---|---|---|
| F1 | EM correct-answer rate among applicable requests | D1, D2, D3 | How reliably does each method return the correct answer across domains? |
| F2 | Same EM rate, with fixed composition weights | W1, W2, W3, W4 | How does performance change across the four declared workload conditions? |
| F3 | Overall effective coverage across the frozen mixed workload | D1, D2, D3 | What fraction of the workload receives a scorable answer? |
| F4 | Mean structured interpretation loss among answer-returning, interpretation-scoreable requests | D1, D2, D3 | How close are the returned interpretations to authoritative intent? |
| F5 | Same mean interpretation loss | epsilon = 0, 1/6, 1/3, 1/2, 1 | How does the semantic tolerance affect realized loss? |
| F6 | Normalized realized cost gap to the best plan in the frozen equivalent pool | eta = 0, .05, .1, .2, .5 | How sensitive is terminal plan selection to bounded estimation error? |
| F7 | Realized trace cost under a common frozen resource accounting rule | XGAP, NP, SH, GR, TS | How does total decision-and-execution cost change with the method? |
| F8 | Same overall effective coverage as F3 | epsilon = 0, 1/6, 1/3, 1/2, 1 | Does semantic tolerance allow more requests to return scorable answers under fixed budgets? |

F3/F8 recommend an explicitly new overall denominator; the current protocol uses
applicable requests. If that existing denominator is retained instead, rename
their Y to within-support answer coverage and report deployment support rate
alongside it. Do not switch denominators silently.

F7 follows the supplied unified manuscript's C(tau): acquisition, selected
local-planning actions, and execution through materialization. Initialization and
hypothetical lookahead are accounted separately as specified in that manuscript,
and included once in request-level elapsed time. If the intended question is
strictly physical plan quality, replace Y with C_exec(Q,P), hold Q fixed (or prove
equivalence), and use a common supported comparison cohort. That is a different
experiment; do not relabel partial trace proxies or differing-query execution
times as this quantity. TS is an external-system comparison, not a component
ablation of XGAP.

## Denominators and missingness

Let W be the predeclared mixed request frame, S_m its applicable subset for method
m, A_m the requests with scorable returned answers, and E_m the exact matches.
When outcomes are fully observed:

- F1/F2: |E_m| / |S_m|, with wrong returned answers and method non-answers distinct.
- Within-support coverage: |A_m| / |S_m|.
- Proposed F3/F8: |A_m| / |W| = support rate times within-support coverage.
- Conditional answer accuracy: |E_m| / |A_m| when the denominator is nonzero.

Thus applicable-request correct-answer rate equals within-support coverage times
conditional accuracy. Coverage and correctness answer different questions but
are not mathematically independent. EM is a rate of exactly correct answers;
mean answer F1 is a different metric and must not share that label.

Every aggregate carries total, supported, observed, answered and scoreable counts.
Study/harness censoring remains missing or separately bounded; it is not method
incorrectness. Unsupported deployments are marked unsupported in the support
ledger, not assigned invented latency, loss or plan-cost values. They contribute
no answer to the explicitly declared overall-coverage numerator.

TS supports RDF federation. Its current exclusion is native heterogeneous
deployment, not all multi-source queries. Cross-method F1 comparisons on differing
applicable subsets need a common-RDF subset check alongside the main aggregates.

## Controls and mathematical claims

1. W1/W2 are single-source; W3/W4 are multi-source and have different ambiguity
   coordinates. F2 is therefore a workload-condition comparison, not isolated
   causal evidence that ambiguity alone caused a gap. A pure ambiguity experiment
   must hold the complete query, source placement and structural composition fixed.
   Preserve the running workload; do not reclassify its strata after results arrive.
2. F4/F5 use the implemented frozen structured query/intent loss. This is not a
   general answer-output discrepancy. Report interpretation-scoreable n as well
   as answered n. TS needs a sound adapter to the same loss representation; if
   unavailable, retain its method position with N/A. Do not substitute answer EM
   or an arbitrary penalty for missing interpretation loss.
3. F5 mean loss is an appropriate central summary but cannot verify a per-output
   certificate. Retain a side audit of violation count / scoreable count and
   maximum (d - epsilon). Maximum loss is a valid statistic, just as mean loss is.
   All-zero loss is a permissible observation. The actual coordinate weights and
   outcomes determine attainable steps; epsilon values do not force those steps.
4. F6 fixes Q, deployment, equivalent retained plan pool, objective units and a
   positive normalization constant Z. If every pool estimate obeys
   |estimated_cost/Z - measured_cost/Z| <= eta, and selection is estimated argmin,
   then (selected_cost - pool_min_cost)/Z <= 2 eta. At eta zero this gap is zero
   under those assumptions. The reference optimum is within the frozen pool.
   Check the error envelope and bound per draw, even when the main Y is a mean.
   Measurement repetitions estimate reference costs; their variation remains
   visible and does not create an exact guarantee for future execution times.
5. F6 does not require monotone gaps as eta increases. A shared estimator implies
   coincident curves only with the same eligible pool, information and selection
   rule. This lemma also applies to learned estimators satisfying its assumptions;
   it does not establish that the analytic estimator is more accurate. Actual
   estimator quality requires its own error/ranking evidence.
6. Probes cannot authorize semantic bindings, but cost updates can change which
   already-certified query/plan pair is selected and whether budgets suffice.
   XGAP and NP are therefore not guaranteed to have identical semantic results.
   SH/GR share the same terminal certificate; short lookahead does not weaken it.
7. Enlarging epsilon enlarges the feasible terminal set for a fixed state, but
   does not guarantee monotone observed coverage or loss from bounded heuristic
   search. F5/F8 share requests, candidates, budgets, prices and cache policy.
   Epsilon-inapplicable TS is a fixed measured reference, not five new samples.
8. For F7, all positive-weight resource components must be measured comparably.
   The historical source-call + binding-clarification + MiB proxy does not by
   itself represent every component of the manuscript objective. Report coverage
   alongside successful-trace cost so cheap failure cannot masquerade as quality.
   Mechanism attribution uses one-switch controlled internal variants where
   possible; a five-method ordering alone does not isolate each component.

The user's final reference to "F5 varying D" belongs to the old map. New F5 varies
epsilon. Lookahead depth remains an efficiency/search-sensitivity factor and is
not silently removed from the broader experiment plan.

## Execution impact

Preserve job 3890655 and receive its sealed evidence. Its common-input 48-case run
can supply the fixed-configuration F1–F4 aggregates where metrics are scoreable,
and relevant F7 resource components. It cannot establish epsilon curves from a
single epsilon, or F6 perturbation curves without the independent fixed-pool
experiment. Reuse sealed evidence; run only genuinely missing factor settings
after the replacement contract and budgets are frozen. Do not overwrite prior
tables or label extrapolated/mock values as observations.

## Checked local sources

- `docs/ch6_experiment_plan_20260922.md`: W strata and existing metric definitions.
- `docs/ch6_formal_execution_20260923.md`: support and fixed-pool cost contracts.
- `src/xgap/agent/unified_family.py`: estimated-cost ordering across certified pairs.
- `src/xgap/agent/unified_contract.py`: shared terminal loss contract.
- `src/xgap/experiments/query_loss_score.py`: post-run loss and violation accounting.
- User unified manuscript attachment `6aec8fec-8558-4ab2-b335-5fe9e40a43b1`,
  lines 140–165: realized trace and cost objective.
