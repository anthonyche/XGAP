# XGAP research prototype — current engineering authority

2026-09-25 latest authorization: run existing D1's 56 authored cases as ONE
development pilot (256 supported method requests, native/r0 then RDF/r0), while
rebuilding a provenance-backed independent final workload. See
`docs/decisions/ch6_pilot_workload_rebuild_20260925.md`. Preserve old artifacts and
case IDs; do not label this pilot as an untouched final test or the full study.
No full campaign is authorized. Token thresholds are observed after each method
request; missing usage stops work, never silently becomes zero or a retry.

2026-09-23 latest task: prepare ALL formal artifacts/workflows/scripts/matrices
up to the launch boundary, not the full campaign itself. Current figure authority:
`docs/ch6_formal_execution_20260923.md`: 21 figures, all XGAP/NP/SH/GR/TS;
retain fixed references for inapplicable knobs and explicit unsupported/missing
statuses. F6 is five-method cost sensitivity. No fabricated curves or zero fill.
Preparation completeness is distinct from actual held-out/data readiness.
Latest user clarification: use a mixed workload and report each method only on
its predeclared supported subset, with support counts/rates and paired XGAP
numbers on that same subset. Unsupported is not failed; never infer support from
answer quality or timeouts. TS supports RDF federation, not native heterogeneity.

2026-09-22: current authority is `docs/ch6_experiment_plan_20260922.md`,
`docs/query_structure_spec_20260922.md`, and `docs/coding_agent_brief_20260922.md`.
The latest user instruction, “请继续推进得到实验结果”, authorizes bounded actual
model/backend pilot execution. Freeze inputs and execution budgets before calls;
the first release is `docs/decisions/ch6_first_real_pilot_20260922.md`. Do not
resume old automations, launch the full matrix, or relabel historical results.
Latest correction: `docs/decisions/ch6_external_twostage_20260922.md` overrides
method definitions. Two-stage means an actual external-method composition.
No further LLM-direct cells or internal-two-stage main comparisons are authorized.
The user also authorized replacing D2 with a usable alternative: see
`docs/decisions/ch6_dataset_and_methods_20260922.md` (MovieLens development intake;
stable 20M proposed for evaluation, no fabricated Wikidata mappings).

Current entry: `xgap.api.answer_unified`; controlled entry:
`xgap.api.answer_unified_controlled`; contract:
`docs/decisions/unified_lookahead_migration_20260921.md`.
Read `docs/goal.md`, `docs/status.md`, `docs/architecture.md`,
`docs/implementation_chapter6.md`, `docs/operator_semantics.md`, and relevant
linked decisions before changes. Read `docs/roadmap.md` for remaining work.

The user authorizes necessary tiny development gates, legacy isolation,
compressed evidence, faithful baseline integration and GitHub synchronization.
Current baseline milestone is complete on tiny single/two-source data; see
`docs/report/ch6_baseline_admission_20260922.md`. Do not tune its answer quality.
The next boundary is formal batch dispatch and same-RDF workload/budget freezing,
not another baseline correctness-improvement loop. No full matrix is released yet.
This is a bounded research prototype. Do not expand universal NL support or
build general open-source-product features instead of advancing the experiment.

## Invariants

- One fixed-D online controller; Lambda/epsilon are validation/loss parameters.
  Do not restore separate Exact/Performance algorithms or search a full H tree.
- Preserve audited algebra/compiler semantics. No invented low-level operators.
- Model/catalog output proposes; it cannot attest intent or scope completeness.
  Only the metered authoritative user tool may disclose private intent online.
- Mandatory validation is independent of singleton candidates and zero loss.
  Fixed fields/hard coordinates never relax. The current distance is structured
  query discrepancy, not output-F1 or open-NL error.
- Before optional work, preserve a compact completion witness for EVERY outcome,
  including unknown/probability-zero outcomes. Completion-aware leaf scores are
  estimates, not resource certificates. Retain protected seeds and suppress
  repeated no-progress work. Unknown bounds are never zero.
- PTime needs fixed D and explicit candidate/action/outcome/plan/representation
  bounds, plus polynomial local operations. No global-optimum/whole-policy ratio.
- Use frozen estimates or declared work models, never current-query trial plans
  to choose a winner. Physical moves are individual checked transformations.
- Execute at most one final plan. Only selected actions enter the paid ledger;
  hypothetical work, actual calls/tokens/bytes, declared cost units and offline
  preprocessing are reported separately. No invented measurements.
- Preserve old commits, frozen/failed trials, jobs and historical method IDs.
  Do not retry/cancel/switch an existing run without authority.
- Baselines run faithfully. Fix environment/transport integration only; do not
  tune their algorithms, prompts, outputs or decoding to improve their results.
  User clarification requires making supported workflows run and reporting
  single-source/cross-source strata separately. Explicit compatibility profiles
  for HTTPS IRIs, action-envelope serialization and equivalent tool syntax are
  recorded in `docs/decisions/ch6_planner_external_followup_20260922.md`; preserve
  raw responses and unadapted failures, never inject reference answers or change intended action values/final queries,
  and never label an adapted profile as byte-identical author code.
- Test changed contracts on portable toy data and necessary real tiny boundaries.
  No blanket regression/ablation campaign or GrailQA preprocessing in development.
- Keep credentials/private intent/large artifacts out of Git. Push without
  rewriting remote history. Shared compiler/runtime code is not disposable legacy.

Historical instructions: `AGENTS_history_20260921_before_unified.md` and
`docs/agent_harness_history_20260917.md`; neither is current work authorization.
