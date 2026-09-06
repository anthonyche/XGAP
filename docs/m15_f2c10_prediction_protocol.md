# M15-F2C10 Pre-execution Prediction Protocol

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: plan
- Origin Date: 2026-09-06
- Verification Status: UNVERIFIED
- Version Label: m15-f2c10-prediction-protocol-decision-v1

## Status and decision boundary

This document is a design checkpoint, not an executed experiment or a frozen
paper protocol. F2C9A/B accepts a complete pre-execution estimate source, but
the current admitted source contains constructed development values. F2C10
must replace those values without allowing answer oracles, current-task
execution outcomes, evaluation shadows, or held-out observations to influence
selection.

One author-owned decision is intentionally unresolved: which source should be
the primary estimator for the first non-controlled direct semantic frontier.
No implementation or remote run is authorized until that choice is recorded.

## Provisional research question

Can XGAP use information available before a new query executes to select a
small set of direct semantic plans with lower execution cost while preserving
hard constraints and exact per-interpretation execution correctness?

This question separates three outcomes:

1. prediction quality for latency and transferred bytes;
2. decision quality of the physical/Pareto/epsilon/K pipeline;
3. semantic usefulness to a user, which requires a separate evaluation and is
   not inferred from execution correctness.

## Existing evidence and reusable components

| Component | Current evidence | F2C10 disposition |
|---|---|---|
| F2C9 candidate set | Four executable direct classes, eight physical plans, eight unavailable multihop classes | Reuse unchanged |
| F2C9 estimate snapshot | Complete, hash-bound, oracle-free, sealed before service startup | Reuse interface; replace controlled values |
| F2C9 frontier selector | Physical reduction followed by three-objective Pareto, epsilon, and K | Reuse unchanged for the first prediction gate |
| F2C5 family memory | Successful exact seed-only observations, frozen predecessor view, typed query features | Reuse storage, visibility, and provenance contracts |
| F2C5 development KNN | One family, four seeds, two held-out instances, 0/2 post hoc winner selections under order-confounded shadows | Do not promote or tune as the F2C10 paper estimator |
| F1/F2 campaign machinery | Hash-bound tasks, method isolation, Williams ordering, zero retry, independent auditors | Reuse scheduling and evidence principles |
| F2C8 overlay | Only one base query currently has all four direct semantic classes materialized | Extend before training or held-out evaluation |

## Mutually exclusive primary-estimator choices

| Choice | Primary evidence available at selection | Main scientific value | Main limitation |
|---|---|---|---|
| A — family-memory prediction | Successful exact executions from earlier seed queries in the same structural family and frozen runtime context | Makes agent memory the central mechanism and adds no current-query profiling calls | Requires a larger multi-instance direct-semantic workload and a frozen estimator |
| B — current-query backend observations | Bounded pre-execution explain/profile/sample calls for the current query | Adapts directly to current backend state and avoids cross-task transfer assumptions | Adds user-visible planning latency and tool cost before every query |
| C — confidence-gated hybrid | Family memory first; current-query observations only below a frozen confidence threshold | Can combine warm-path speed with guarded adaptation | Risks an A+B system story, adds policy degrees of freedom, and needs more ablations |

Recommended first choice: **A — family-memory prediction**. It is the narrowest
single mechanism consistent with the agentic memory story, directly exercises
the existing `family_memory_prediction` frontier evidence kind, and avoids
making ambiguity resolution itself pay for backend profiling. Choice B remains
a later baseline. Choice C should not be implemented until A and B are
independently understood.

## Design that becomes active if Choice A is approved

### Data split

- Extend the parameterized direct-semantic overlay across multiple hard-binding
  query instances rather than only Alice/August/HIGH.
- Assign query instances to train and held-out partitions before any native
  cost measurement.
- Materialize all four direct semantic classes for every admitted instance.
- Keep entity identity, time lower bound, and amount lower bound immutable.
- Keep all multihop classes excluded until their semantics are separately
  approved.
- Freeze every workload, split, artifact, query, and oracle hash before native
  calibration begins.

The final query count, split ratio, and repetitions are not selected here. The
existing 4-seed/2-held-out development workload is too small for a performance
or generalization claim.

### Measurement protocol

- On training instances only, execute both physical strategies for every
  direct semantic class.
- Counterbalance the two strategy orders within each task and retain raw
  repetitions; do not use the fixed selected-then-shadow order as an unbiased
  comparison.
- Admit a memory observation only after successful execution and exact
  post-execution oracle validation.
- Store typed query bindings, semantic-class bindings, runtime compatibility,
  elapsed time, transferred bytes, remote-call count, and order/repetition
  metadata. Never store answer rows.
- Freeze the training memory view and estimator configuration before opening
  held-out measurements.
- For each held-out query, generate estimates for all eight direct physical
  plans, seal the F2C9 snapshot, and select the frontier before executing any
  held-out plan.
- Run non-selected candidates only in a separately labeled, counterbalanced
  evaluation phase that cannot update the estimator or selection.
- Never automatically retry a failed attempt. Preserve failures as outcomes
  and let the author decide whether a new attempt is a new registered run.

### Predictor contract

The estimator must emit one latency prediction and one transferred-byte
prediction for each of the eight direct physical plans. Every prediction must
carry:

- model/version/configuration hash;
- frozen training-memory-view hash;
- feature-schema hash;
- ordered training observation IDs;
- target query-instance and semantic-class IDs;
- physical strategy ID;
- uncertainty or an explicit `unavailable` value;
- an empty oracle-input list;
- `post_execution_measurements_used=false`.

Cold-start behavior must fail closed or use a separately declared static
baseline. It must not silently substitute the F2C9 controlled values.

## Variables and metrics

### Independent variables

- estimation method: static controlled baseline versus frozen family-memory
  predictor;
- physical strategy: parallel hash versus risk-first bind;
- semantic class: exact, risk-only, predicate-only, combined;
- workload/query binding and data selectivity;
- execution order and repetition block.

### Primary dependent variables

- held-out latency prediction absolute and relative error;
- held-out transferred-byte prediction absolute and relative error;
- selected-plan latency regret against the counterbalanced evaluation oracle;
- selected-plan byte regret;
- frontier recall of the post hoc three-objective nondominated set;
- exact execution-answer rate per interpretation.

### Secondary system metrics

- end-to-end latency including planning;
- planning latency;
- remote calls and bytes moved;
- coordinator CPU and peak memory;
- estimator memory lookup cost and artifact size;
- number of returned semantic plans;
- failure and unavailable rates;
- LLM, ontology, and current-query profile calls, expected to be zero in
  Choice A.

Semantic user utility is not a proxy for answer row count, frontier diversity,
or oracle equality. It remains a separate study.

## Confounds and required controls

- Backend cache and warmup effects: fresh lifecycle policy and counterbalanced
  order must be frozen.
- Temporal drift: training and held-out collection windows and runtime identity
  must be recorded.
- Query-instance leakage: no hard-binding instance may appear in both training
  and held-out views.
- Semantic-class imbalance: every admitted query instance must expose the same
  four direct classes or be explicitly marked unavailable before measurement.
- Tuning leakage: the existing two F2C5 held-out results and the future F2C9B
  CWRU mechanism result may be used as diagnostics only, never as F2C10
  estimator-training or hyperparameter-selection data.
- Execution failures: report separately; do not impute, discard silently, or
  rerun automatically.

## Milestones after the decision

1. F2C10A — compile a multi-instance direct-semantic workload and immutable
   train/held-out split; no backend call.
2. F2C10B — define a versioned prediction-source compiler over frozen training
   memory, plus leakage and tamper tests; no held-out execution.
3. F2C10C — run deterministic backend-double validation and an independent
   reconstruction audit.
4. F2C10D — freeze order, repetitions, timeout, and analysis settings with the
   author before any CWRU calibration campaign.
5. F2C10E — collect training measurements, freeze the estimator, then run the
   held-out evaluation as separate immutable jobs.

## Current gate

Author selection required:

- Choice A: family-memory prediction;
- Choice B: current-query backend-observation prediction;
- Choice C: confidence-gated hybrid.

Until one choice is accepted, F2C9B remains the last executable milestone and
the F2C10 implementation state is `decision_required`. No paper result is
claimed.
