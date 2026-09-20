# T6 Chapter 7 execution contract — 2026-09-20

## Material Passport

- Mode: experiment execution and reproducibility engineering, inline ARS workflow.
- Authority: user's accepted [original 20-figure plan](../research_experiment_plan_20260920.md).
- State: intake and logging gates; no formal experimental release yet.
- Inputs: current XGAP, pinned original baseline code and existing frozen dataset artifacts.
- Outputs: capability evidence, bounded readiness runs, pilot release, then the approved matrix.
- Scope: research prototype; no human subjects and no new paid service.

## Accepted protocol and explicit interpretation

Adopt RQ1–RQ5 and E1–E20 unchanged, with FinBench-derived,
GrailQA/Freebase-derived and FedShop-derived panels using common X/Y definitions.
Two execution tracks remain separate: NL-to-materialized-answer end-to-end, and
frozen-state-to-materialized-answer controlled processing. Do not mix their latency.

Operational loss is the current frozen weighted structured-query coordinate loss,
with fixed skeleton/hard constraints and an invariant weight denominator. Epsilon
does not bound answer F1 or output-semantics discrepancy. Private intent remains
behind a metered simulated-user tool; independent loss scoring opens it only after
outcome sealing. Public metadata and data access must be equally available to all
methods in a comparison. No test reference or source assignment enters an NL method.

Controlled initial clues are an explicit shared input from the request/application.
They filter the full frozen family through observations; do not rebuild/reweight
the family after clues. Costs apply to subsequent actual actions. The test intent
distribution is not passed to the worst-case planner. A semantic choice has a
frozen name/type/group; field count is not silently relabelled as ambiguity.

The no-feedback ablation zeros only execution estimates entering the acquisition/
stopping comparison. Information prices, candidates, compiler, physical planning,
final estimated-plan selection, execution, hard constraints, budgets and stable
ties remain unchanged. It does not use the historical information-only worker.

Native and RDF comparisons are separate. Default external candidate is the author's
ARUQULA (`aruqula` branch) connected to FedUP only if its real interfaces work.
Configuration/protocol/measurement changes are allowed; prompt/exploration/repair/
search algorithms and model behavior are not optimized. Missing lookup/index or
dependencies are SETUP_ERROR. Do not label an unattempted installation UNSUPPORTED.
FedUP's plan-only mode cannot satisfy an execution gate.

## Execution stages

1. Freeze source intake and capability table. Reuse intact existing data; no
   GrailQA runtime catalog builds. Check each derived graph's provenance before use.
2. Close controlled-state, feedback, complete-policy and independent-loss logging
   gaps on tiny data. A policy must include every selected action outcome and
   distinguish hypothetical leaves from the observed path; only actual events get
   measured latency/bytes.
3. Native live-model preflight using the existing authorized Qwen service. First
   gate allows at most two model generations and two final executions, no repair,
   90 seconds per request, 1 GiB worker RSS and 2 GiB source RSS observation bounds,
   1 GiB artifact cap, 6 GiB free disk reserve. Preserve failed attempts and stop
   on unverified resource closure. This is not a 20–30-case pilot or paper result.
4. Prepare each dataset's 20–30 development cases, family-disjoint from test.
   Uniform family then uniform legal distinct intent, independent of results.
   Freeze pilot seeds/configuration before execution. Do not inherit T3's
   answer-nonemptiness stratification. Report missing datasets rather than copying
   FinBench under a different label.
5. After the pilots, freeze family-cluster sample sizing, minimum meaningful
   effects, repetitions, common-completion timing cohort, cache/order protocol,
   supported baseline deployment and total study resource budget. Then execute
   the approved matrix, preserving every formal failure and censoring event.
6. Build measured metrics, denominators and clustered intervals. Render the 20
   figures with Matplotlib and actual policies; missing evidence stays missing.

The initial gate has bounded resources, not a blank-check formal-run budget.
New paid services or spending beyond a frozen study budget need user input;
ordinary implementation/configuration within this approved plan does not.
No automatic retry of an attempted case and no resumption of T3.

## Intake findings

- Qwen GET `/v1/models` returned HTTP 200 and `qwen3.8-27b` on 2026-09-20;
  credential was entered without echo, held in process memory, not saved. This
  is connectivity evidence, not a completed generation or quality measurement.
- ARUQULA official branch cloned at
  `9a3982baca03d62f7250572e300b1e4ba47727cc`, unchanged. Its endpoint configuration
  is available, but entity lookup, Redis, chainlite and auxiliary model aliases
  require setup. No reproduced ARUQULA or ARUQULA+FedUP score is claimed.
- Existing FedShop artifacts are source/generator intake, not generated/loaded
  data. Existing Freebase shard provenance must be checked before it can qualify
  as a gold-independent derived graph. Neither is currently an admitted T6 dataset.

Original sources: [ARUQULA](https://github.com/AKSW/ARUQULA/tree/aruqula),
[FedUP](https://github.com/GDD-Nantes/fedup).
